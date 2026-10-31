"""The investigation agent. A small explicit graph:

  intake → resolve → [enrich | jobs | website | rdap | news | sanctions] (parallel)
         → adverse-media classify → graph signals → evaluate → score
         → router: REVIEW → investigate-more (≤2 rounds) → rescore
         → LLM critic → output

Every step emits an event for the live log (SSE)."""
from __future__ import annotations

import asyncio
import datetime as dt
import time
import uuid
from typing import Any, Awaitable, Callable

from . import config, llm, store
from .crustdata import CreditCapExceeded, Ledger, crust
from .evaluators import _people, find_director, g, run_all
from .models import Disambiguation, HeadlineClassification, Intake, LLMSummary
from .scoring import score
from .seed import SYNTHETIC
from .sources import sanctions, web
from .sources import static_lists as SL
from .workbook import VERDICT_LABELS, load_workbook, strip_codes

Emit = Callable[[dict], Awaitable[None]]


class Run:
    def __init__(self, inp: Intake, emit: Emit):
        self.id = uuid.uuid4().hex[:10]
        self.inp = inp
        self.emit_cb = emit
        self.t0 = time.time()
        self.ledger = Ledger()
        self.sources: set[str] = set()
        self.ctx: dict[str, Any] = {}
        self.synthetic = inp.domain in SYNTHETIC if inp.domain else False

    async def emit(self, kind: str, msg: str, **kw):
        await self.emit_cb({"type": kind, "msg": msg, "t": round(time.time() - self.t0, 2),
                            "credits": round(self.ledger.spent, 2), **kw})

    async def step(self, name: str, coro, ok_msg=None):
        await self.emit("step", f"{name}…", step=name, status="start")
        try:
            res = await coro
            await self.emit("step", ok_msg(res) if callable(ok_msg) else (ok_msg or f"{name} done"), step=name, status="done")
            return res
        except CreditCapExceeded as e:
            await self.emit("step", str(e), step=name, status="warn")
        except Exception as e:  # noqa: BLE001
            await self.emit("step", f"{name}: {type(e).__name__}: {str(e)[:160]}", step=name, status="error")
        return None


async def _none():
    return None


GENERIC_NAME_WORDS = {"europe", "india", "global", "international", "market", "markets", "technologies", "technology", "tech",
                      "solutions", "services", "systems", "group", "holdings", "trading", "traders", "ventures", "enterprises",
                      "industries", "labs", "digital", "software", "consulting", "capital", "partners", "ou", "otc", "asia", "uk", "usa"}


def plausible_name(applicant: str, candidate: str, name_sim) -> bool:
    """Candidate must share a distinctive (non-generic) word with the applicant AND look similar overall."""
    from .sources.sanctions import norm
    a = {w for w in norm(applicant).split() if w not in GENERIC_NAME_WORDS and len(w) > 2}
    b = set(norm(candidate).split())
    if a and not any(x == y or (len(x) > 4 and (y.startswith(x) or x.startswith(y))) for x in a for y in b):
        return False
    return name_sim(applicant, candidate) >= 0.5


async def resolve(run: Run) -> dict | None:
    inp = run.inp
    if run.synthetic:
        run.ctx["match_conf"] = 1.0
        await run.emit("log", "Synthetic demo entity — using fixture data (no credits spent)")
        return SYNTHETIC[inp.domain]["company"]
    if inp.crustdata_company_id == -1:  # user chose "none of these"
        await run.emit("log", "Analyst chose to continue without a Crustdata profile")
        return None
    if inp.crustdata_company_id:
        run.ctx["match_conf"] = 1.0
        return {"crustdata_company_id": inp.crustdata_company_id}
    matches = []
    if inp.domain:
        matches = await crust.identify(run.ledger, domain=inp.domain)
        await run.emit("log", f"Identify by domain {inp.domain}: {len(matches)} candidate(s) (free)")
    if not matches:
        matches = await crust.identify(run.ledger, name=inp.company_name)
        await run.emit("log", f"Identify by name '{inp.company_name}': {len(matches)} candidate(s) (free)")
    if not matches:
        return None
    cands = [{"i": i, "id": m["company_data"]["crustdata_company_id"], "name": g(m, "company_data.basic_info.name"),
              "domain": g(m, "company_data.basic_info.primary_domain"), "founded": g(m, "company_data.basic_info.year_founded"),
              "size": g(m, "company_data.basic_info.employee_count_range"), "industry": (g(m, "company_data.basic_info.industries") or [None])[0],
              "conf": m.get("confidence_score", 0)} for i, m in enumerate(matches[:25])]
    # Name search is fuzzy: drop candidates whose name doesn't resemble the applicant (e.g. 'TJX Europe' for 'Garantex Europe OU').
    from .evaluators import name_sim
    total = len(cands)
    cands = [c for c in cands if (inp.domain and c["domain"] == inp.domain) or plausible_name(inp.company_name, c["name"] or "", name_sim)][:8]
    for i, c in enumerate(cands):
        c["i"] = i
    if total and not cands:
        await run.emit("log", f"None of the {total} name-search results resemble '{inp.company_name}' — continuing without a profile (unverifiable, not fraud)")
        return None
    run.ctx["candidates"] = cands
    # Domain match, or a single candidate: deterministic, no LLM.
    if inp.domain:
        for c in cands:
            if c["domain"] == inp.domain:
                run.ctx["match_conf"] = 1.0
                return {"crustdata_company_id": c["id"]}
    if len(cands) == 1:
        run.ctx["match_conf"] = float(cands[0]["conf"] or 0.8)
        return {"crustdata_company_id": cands[0]["id"]}
    prompt = ("Pick which candidate company the applicant refers to. Applicant: "
              f"{inp.model_dump(include={'company_name', 'domain', 'country', 'director', 'stated_business', 'declared_headcount', 'business_type'})}\n"
              f"Candidates: {cands}\nUse country, legal form, size vs declared headcount, industry, domain. "
              "If NONE of the candidates is the applicant, set chosen_index to null. "
              "confidence = how sure you are of your decision (including a 'none' decision).")
    d, meta = await llm.ask(prompt, Disambiguation, max_tokens=500)
    if d and d.chosen_index is None and d.confidence >= 0.75:
        await run.emit("log", f"LLM: none of the candidates is the applicant (conf {d.confidence:.2f}) — continuing without a profile. {d.reason[:140]}")
        return None
    if d and d.chosen_index is not None and 0 <= d.chosen_index < len(cands) and d.confidence >= 0.75:
        run.ctx["match_conf"] = d.confidence
        await run.emit("log", f"LLM disambiguation → '{cands[d.chosen_index]['name']}' (conf {d.confidence:.2f}): {d.reason[:140]}")
        return {"crustdata_company_id": cands[d.chosen_index]["id"]}
    # A confirmed sanctions hit is a hard stop whichever profile is right — don't block on disambiguation.
    hit = sanctions.screen(inp.company_name, "entity")
    if hit.get("matches") and hit["matches"][0]["score"] >= 0.93:
        await run.emit("log", f"Exact sanctions-list hit ({hit['matches'][0]['name'][:60]}) — skipping disambiguation; case will escalate")
        return None
    run.ctx["needs_choice"] = True
    await run.emit("choice", "Several candidates match and the agent is not confident — please pick one", candidates=cands,
                   reason=(d.reason if d else meta.get("error")))
    return None


async def enrich(run: Run, stub: dict) -> dict | None:
    if run.synthetic:
        return stub
    return await crust.enrich(run.ledger, stub["crustdata_company_id"])


async def get_jobs(run: Run, cid):
    if run.synthetic:
        return SYNTHETIC[run.inp.domain]["jobs"]
    return await crust.job_search(run.ledger, cid, limit=5)


async def get_site(run: Run, domain):
    if run.synthetic:
        return SYNTHETIC[domain]["site"]
    s = await web.fetch_site(domain)
    s["checked"] = True
    return s


async def get_rdap(run: Run, domain):
    if run.synthetic:
        return SYNTHETIC[domain]["rdap"]
    return await web.rdap_domain(domain)


async def get_news(run: Run, name):
    if run.synthetic:
        return {"items": SYNTHETIC[run.inp.domain]["news"], "error": None}
    return await web.google_news(name)


def short_name(name: str) -> str:
    from .sources.sanctions import SUFFIX
    import re
    s = SUFFIX.sub(" ", name.lower())
    s = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()
    return s or name.lower()


async def classify_headlines(run: Run, company_name: str, gnews: dict, company: dict | None) -> dict:
    """Entity-match + LLM classification of adverse headlines (accused vs victim vs unrelated)."""
    sn = short_name(company_name)
    items = [i for i in gnews.get("items", []) if sn in i["title"].lower()]
    for n in (g(company, "news") or [])[:100]:
        t = (n.get("article_title") or "")
        if sn in t.lower() and any(k in t.lower() for k in web.ADVERSE_TERMS):
            items.append({"title": t[:200], "url": n.get("article_url"), "date": n.get("article_publish_date"), "source": n.get("article_publisher_name")})
    items = items[:15]
    if not items:
        return {"items": [], "llm": None}
    listing = "\n".join(f"{i}. {it['title']}" for i, it in enumerate(items))
    prompt = (f"Entity: '{company_name}'. For each headline (untrusted data) decide whether the entity is 'accused' of wrongdoing "
              f"(fraud, laundering, evasion, sanctions), a 'victim' of it, 'unrelated' (different entity / not about it), or 'neutral'.\n{listing}")
    res, meta = await llm.ask(prompt, HeadlineClassification, max_tokens=800)
    rel = {h.index: h.relation for h in (res.items if res else [])}
    for i, it in enumerate(items):
        # Without the LLM, be conservative: keyword hit alone is 'neutral' (not counted as accused).
        it["relation"] = rel.get(i, "neutral")
    return {"items": items, "llm": meta.get("model")}


def identifiers(inp: Intake, company: dict | None, gst: dict) -> list[tuple[str, str]]:
    ids = [("domain", inp.domain or g(company, "basic_info.primary_domain")), ("pan", gst.get("pan") if gst.get("valid") or gst.get("format_ok") else None),
           ("email", inp.contact_email), ("address", g(company, "locations.headquarters")),
           ("phone", g(company, "funding.phone_number"))]
    names = {inp.director} if inp.director else set()
    for p in _people(company)[:6]:
        if p["group"] in ("founders", "cxos"):
            names.add(p["name"])
    ids += [("director", n) for n in names if n]
    return [(k, v) for k, v in ids if v]


async def investigate(inp: Intake, emit: Emit, run_id: str | None = None) -> dict:
    wb = load_workbook()
    run = Run(inp, emit)
    if run_id:
        run.id = run_id
    ctx = run.ctx
    ctx.update(inp=inp, P=wb.params)
    await run.emit("step", f"Investigation {run.id} started for '{inp.company_name}'", step="intake", status="start")

    # [1] intake
    gst = SL.validate_gstin(inp.gstin)
    ctx["gst"] = gst
    if gst.get("provided"):
        run.sources.add("gstin")
        await run.emit("log", f"GSTIN {gst['gstin']}: {'valid format+checksum, ' + str(gst.get('state')) if gst.get('valid') else 'INVALID — ' + gst.get('reason', '')}")
    await run.emit("step", "Intake validated", step="intake", status="done")

    # [2] entity resolution
    stub = await run.step("resolve", resolve(run), lambda r: "Entity resolved" if r else "No confident match")
    if ctx.get("needs_choice"):
        return {"id": run.id, "status": "needs_choice", "candidates": ctx.get("candidates")}

    # [3] parallel evidence collection
    domain = inp.domain
    company = None
    if stub:
        company = await run.step("enrich", enrich(run, stub), lambda c: f"Crustdata profile: {g(c, 'basic_info.name')} · headcount {g(c, 'headcount.total')}" if c else "Profile empty")
        if company:
            run.sources.add("crustdata")
            site_url = (g(company, "basic_info.website") or "").lower()
            domain = domain or g(company, "basic_info.primary_domain") or (site_url.split("//")[-1].split("/")[0].removeprefix("www.") or None)
    ctx["company"] = company
    cid = g(company, "crustdata_company_id")
    names_to_screen = list({n for n in ([inp.director] if inp.director else []) + [p["name"] for p in _people(company) if p["group"] in ("founders", "cxos")][:6] if n})

    def screen_all():
        e = sanctions.screen(inp.company_name, "entity")
        people = [sanctions.screen(n, "individual") for n in names_to_screen]
        best = {"status": e["status"], "available": e["available"], "screened": len(names_to_screen),
                "matches": sorted([m for p in people for m in p["matches"]], key=lambda m: -m["score"])[:5]}
        return e, best

    jobs, site, rdap, gnews, sanc = await asyncio.gather(
        run.step("jobs", get_jobs(run, cid) if cid else _none(), lambda j: f"Job postings: {(j or {}).get('total_count', 0)}"),
        run.step("website", get_site(run, domain) if domain else _none(), lambda s: f"Website {'live' if s and s.get('reachable') else 'unreachable'}" if s else "No domain"),
        run.step("domain_age", get_rdap(run, domain) if domain else _none(), lambda r: f"Domain registered {r.get('created')}" if r and r.get("found") else "No RDAP record"),
        run.step("news", get_news(run, g(company, "basic_info.name") or inp.company_name), lambda n: f"{len((n or {}).get('items', []))} adverse-keyword headlines"),
        run.step("sanctions", asyncio.to_thread(screen_all), lambda s: f"Sanctions screened: entity + {len(names_to_screen)} people ({s[0]['status']})"),
    )
    ctx["jobs"] = jobs
    from .evaluators import job_stats
    ctx["job_stats"] = job_stats(jobs, company)
    ctx["site"] = site or {"checked": False}
    ctx["rdap"] = rdap or {}
    if jobs is not None:
        run.sources.add("crustdata")
    if site and site.get("checked") and site.get("reachable"):
        run.sources.add("website")
    if rdap and rdap.get("found"):
        run.sources.add("rdap")
    if sanc:
        ctx["sanc_entity"], ctx["sanc_people"] = sanc
        if sanc[0].get("available"):
            run.sources.add("ofac")
    if gnews and not gnews.get("error"):
        run.sources.add("news")

    # [3b] adverse media classification (LLM sees only headlines, as data)
    ctx["adverse"] = await run.step("adverse_media", classify_headlines(run, g(company, "basic_info.name") or inp.company_name, gnews or {}, company),
                                    lambda a: f"{len(a['items'])} entity-matched headlines classified" + (f" by {a['llm']}" if a.get("llm") else ""))

    # [3c] network / graph
    key = f"syn:{inp.domain}" if run.synthetic else (f"cd:{cid}" if cid else f"name:{inp.company_name.lower()}")
    ids = identifiers(inp, company, gst)
    desc = g(company, "basic_info.description") or inp.stated_business
    ctx["graph"] = store.graph_signals(key, ids, desc)
    run.sources.add("internal")
    await run.emit("log", f"Graph: {len(ctx['graph']['shared'])} shared identifier(s), {len(ctx['graph']['watchlist'])} watchlist link(s)")

    # [4-5] evaluate + score
    outcomes = run_all(ctx)
    sc = score(wb, outcomes, run.sources - {"internal", "gstin"})
    await run.emit("score", f"Round 1: {sc['verdict']} · risk {sc['risk_score']} · confidence {sc['confidence']:.2f}",
                   verdict=sc["verdict"], risk=sc["risk_score"])

    # [6-7] router: investigate-more for REVIEW (max 2 rounds)
    rounds = 1
    while sc["verdict"] == "REVIEW" and rounds < 3 and not run.synthetic:
        did = False
        if inp.director and company and not find_director(ctx) and "director_search" not in ctx:
            res = await run.step("investigate_more", crust.person_search(run.ledger, inp.director, limit=3),
                                 lambda r: f"Director lookup: {len((r or {}).get('profiles', []))} profile(s)")
            prof = ((res or {}).get("profiles") or [None])[0]
            cur = (g(prof, "experience.employment_details.current") or [{}])[0] if prof else {}
            ctx["director_search"] = {"title": g(prof, "basic_profile.current_title"), "employer": cur.get("name") or cur.get("company_name")} if prof else None
            did = True
        elif gnews and gnews.get("error") and "web_news" not in ctx:
            res = await run.step("investigate_more", crust.web_search(run.ledger, f'"{inp.company_name}" fraud OR scam OR raid'),
                                 lambda r: f"Crustdata news search: {len((r or {}).get('results', []))} results")
            ctx["web_news"] = True
            items = [{"title": r.get("title", "")[:200], "url": r.get("url")} for r in (res or {}).get("results", [])]
            ctx["adverse"] = await classify_headlines(run, inp.company_name, {"items": items}, company)
            did = True
        if not did:
            break
        rounds += 1
        outcomes = run_all(ctx)
        sc = score(wb, outcomes, run.sources - {"internal", "gstin"})
        await run.emit("score", f"Round {rounds}: {sc['verdict']} · risk {sc['risk_score']} · confidence {sc['confidence']:.2f}",
                       verdict=sc["verdict"], risk=sc["risk_score"])

    # [8] LLM critic — structured evidence only
    defs = wb.by_id()
    RL = {"Flag": "RED FLAG", "Partial": "CONCERN", "Pass": "OK"}
    ev_lines = [f"- {defs[cid].name}: {RL[o.result]} — {o.evidence[:160]} (source: {o.source})"
                for cid, o in sorted(outcomes.items(), key=lambda kv: {"Flag": 0, "Partial": 1, "Pass": 2}.get(kv[1].result, 3))
                if o.result in ("Flag", "Partial", "Pass")][:40]
    drivers = [defs[d].name for d in sc["drivers"]]
    gaps = [defs[d].name for d in sc["gaps"]]
    prompt = (f"Applicant: {inp.company_name}. Verdict: {VERDICT_LABELS[sc['verdict']]}; risk {sc['risk_score']}/100; confidence {sc['confidence']:.0%}.\n"
              f"Biggest risk drivers: {drivers}. Could not verify: {gaps}.\nEvidence:\n" + "\n".join(ev_lines) +
              "\n\nThe reader is a busy business owner with NO compliance background. Use plain, everyday English, short sentences, "
              "no jargon, no abbreviations, and NEVER mention check codes or IDs. Things we simply could not check are NOT concerns — only list real warning signs as concerns (if there are none, return an empty list). Write: "
              "summary (2-3 sentences: what we found and why the verdict is what it is); "
              "innocent_explanations (up to 3 legitimate reasons that could explain the warning signs); "
              "key_concerns (up to 4 short bullets in plain words); "
              "analyst_questions (3-6 concrete documents or answers to ask the company for).")
    critic = await run.step("critic", llm.ask(prompt, LLMSummary, max_tokens=1200), lambda r: f"Critic review by {r[1].get('model')}" if r and r[0] else "Critic unavailable — deterministic summary used")
    summary = critic[0] if critic and critic[0] else None
    if summary:
        summary = LLMSummary(summary=strip_codes(summary.summary),
                             innocent_explanations=[strip_codes(x) for x in summary.innocent_explanations],
                             key_concerns=[strip_codes(x) for x in summary.key_concerns],
                             analyst_questions=[strip_codes(x) for x in summary.analyst_questions])
    if not summary:
        summary = LLMSummary(summary=(f"{VERDICT_LABELS[sc['verdict']]}. Main warning signs: " + "; ".join(defs[d].name.lower() for d in sc["drivers"][:3]) + ".") if sc["drivers"] else f"{VERDICT_LABELS[sc['verdict']]}. No warning signs found in the automated checks.",
                             analyst_questions=["Provide certificate of incorporation and latest filed accounts.", "Provide payroll or PF/ESI records."])

    # persist entity into the graph for future cross-checks (not synthetic fixtures)
    if not run.synthetic:
        store.upsert_entity(key, g(company, "basic_info.name") or inp.company_name, ids, description=desc or "",
                            status=sc["verdict"].lower())

    elapsed = round(time.time() - run.t0, 1)
    result = {
        "id": run.id, "status": "done", "created": dt.datetime.now().isoformat(timespec="seconds"),
        "input": inp.model_dump(), "synthetic": run.synthetic,
        "synthetic_label": SYNTHETIC[inp.domain]["label"] if run.synthetic else None,
        "entity_key": key, "verdict": sc["verdict"], "score": sc, "rounds": rounds,
        "outcomes": {k: v.model_dump() for k, v in outcomes.items()},
        "summary": summary.model_dump(),
        "profile": {"name": g(company, "basic_info.name"), "domain": domain, "logo": g(company, "basic_info.logo_permalink"),
                    "description": g(company, "basic_info.description"), "founded": g(company, "basic_info.year_founded"),
                    "headcount": g(company, "headcount.total"), "hq": g(company, "locations.headquarters"),
                    "industry": g(company, "taxonomy.professional_network_industry"), "linkedin": g(company, "basic_info.professional_network_url"),
                    "headcount_ts": [x.get("employee_count") for x in (g(company, "headcount.timeseries") or [])][-36:],
                    "people": _people(company)[:8]},
        "jobs": ctx.get("job_stats"), "tech": g(company, "technographics"), "adverse": ctx.get("adverse"), "site": ctx.get("site"), "rdap": ctx.get("rdap"), "gst": gst,
        "cost": {"credits": round(run.ledger.spent, 2), "cap": run.ledger.cap, "calls": run.ledger.calls, "seconds": elapsed,
                 "manual_hours": config.MANUAL_BENCHMARK_HOURS, "manual_cost_inr": config.MANUAL_BENCHMARK_COST_INR},
    }
    store.save_investigation(result)
    await run.emit("done", f"Finished in {elapsed}s · {run.ledger.spent:.2f} credits", verdict=sc["verdict"], id=run.id)
    return result


def rescore(inv: dict) -> dict:
    """Recompute score after analyst edits (no new data fetched)."""
    from .models import CheckOutcome
    wb = load_workbook()
    outcomes = {k: CheckOutcome(**v) for k, v in inv["outcomes"].items()}
    sc = score(wb, outcomes, set(inv["score"]["independent_sources"]))
    inv["score"] = sc
    inv["verdict"] = sc["verdict"]
    return inv
