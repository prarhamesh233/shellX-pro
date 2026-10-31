"""Automated check evaluators, one function per workbook check ID.

Each returns a CheckOutcome. result=None means 'unverifiable' (no data) — never fraud.
Thresholds come from the workbook's Thresholds sheet (P1..P11).
"""
from __future__ import annotations

import datetime as dt
from difflib import SequenceMatcher
from typing import Any, Callable

from .models import CheckOutcome, Intake
from .sources import static_lists as SL
from .sources.web import years_since

# Source reliability (how much we trust a source for the check it feeds).
REL = {"crustdata": 0.8, "rdap": 0.9, "website": 0.7, "news": 0.55, "ofac": 0.95, "gstin": 0.55,
       "internal": 0.9, "heuristic": 0.5, "declared": 0.6, "static": 0.8}

SRC_LABEL = {"crustdata": "Crustdata", "rdap": "RDAP/WHOIS", "website": "Website fetch", "news": "News (Google News + Crustdata)",
             "ofac": "OFAC SDN list", "gstin": "GSTIN checksum", "internal": "Internal graph DB",
             "heuristic": "Text heuristic", "static": "FATF / policy lists"}


def g(d: Any, path: str, default=None):
    cur = d
    for k in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(k)
        else:
            return default
        if cur is None:
            return default
    return cur


def O(cid, result, value, evidence, src, url=None, rel=None) -> CheckOutcome:
    return CheckOutcome(id=cid, result=result, value=None if value is None else str(value)[:140], evidence=evidence,
                        source=SRC_LABEL.get(src, src), source_url=url, reliability=REL.get(src, 0.5) if rel is None else rel,
                        ts=dt.datetime.now().isoformat(timespec="seconds"))


def U(cid, why, src="crustdata") -> CheckOutcome:
    """Unverifiable: no data. Excluded from score, lowers coverage."""
    return CheckOutcome(id=cid, result=None, evidence=f"Couldn't check: {why}.", source=SRC_LABEL.get(src, src))


def NA(cid, why) -> CheckOutcome:
    return CheckOutcome(id=cid, result="N/A", evidence=why, source="Applicability rule")



COUNTRY_NAMES = {"IND": "India", "USA": "the United States", "GBR": "the United Kingdom", "SGP": "Singapore", "ARE": "the UAE",
                 "EST": "Estonia", "RUS": "Russia", "CHN": "China", "DEU": "Germany", "FRA": "France", "NLD": "the Netherlands",
                 "CAN": "Canada", "AUS": "Australia", "JPN": "Japan", "HKG": "Hong Kong", "MUS": "Mauritius", "CYP": "Cyprus",
                 "VGB": "the British Virgin Islands", "CYM": "the Cayman Islands", "SYC": "Seychelles", "PAN": "Panama",
                 "IRN": "Iran", "PRK": "North Korea", "MMR": "Myanmar", "IRL": "Ireland", "CHE": "Switzerland", "ISR": "Israel"}


def country(code):
    return COUNTRY_NAMES.get(code, code) if code else "unknown"


def usd(x):
    x = float(x or 0)
    if x >= 1e9:
        return f"${x / 1e9:.1f} billion"
    if x >= 1e6:
        return f"${x / 1e6:.1f} million"
    if x >= 1e3:
        return f"${x / 1e3:.0f} thousand"
    return f"${x:,.0f}"


def big(n):
    n = float(n or 0)
    return f"{n / 1e6:.1f} million" if n >= 1e6 else f"{n:,.0f}"

def name_sim(a: str, b: str) -> float:
    from .sources.sanctions import norm
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def observed_headcount(c):
    return g(c, "headcount.total")


def claims_scale(inp: Intake, P) -> bool:
    t = inp.turnover_usd() or 0
    return (inp.declared_headcount or 0) > P["P1"] or t >= 250_000


# --------------------------------------------------------------------------- checks
def reg02(ctx):
    c, inp = ctx["company"], ctx["inp"]
    if not c:
        return U("REG-02", "no company profile found to compare with")
    nm = g(c, "basic_info.name", "")
    sim = name_sim(inp.company_name, nm)
    dom = g(c, "basic_info.primary_domain")
    dom_ok = (not inp.domain) or (dom and (inp.domain == dom or inp.domain in (g(c, "basic_info.all_domains") or [])))
    hq_c = g(c, "locations.country")
    ctry_ok = (not hq_c) or SL.to_iso3(inp.country) in (None, hq_c)
    how = "the same" if sim >= 0.9 else "very similar" if sim >= 0.7 else "somewhat different" if sim >= 0.5 else "very different"
    ev = (f"Name given '{inp.company_name}', name found '{nm}' ({how}). "
          f"Website {'matches' if dom_ok else f'differs ({inp.domain} vs {dom})'}. "
          f"Country {'matches' if ctry_ok else f'differs ({inp.country} vs {country(hq_c)})'}.")
    if sim < 0.5 and not dom_ok:
        return O("REG-02", "Flag", how, ev, "crustdata")
    if sim < 0.7 or not dom_ok or not ctry_ok:
        return O("REG-02", "Partial", how, ev + " A brand name or rebrand can explain this.", "crustdata")
    return O("REG-02", "Pass", how, ev, "crustdata")


def reg03(ctx):
    c, inp, P = ctx["company"], ctx["inp"], ctx["P"]
    yf = g(c, "basic_info.year_founded")
    if not yf:
        return U("REG-03", "founding year not available")
    age_m = (dt.date.today().year - int(yf)) * 12
    t = inp.turnover_usd()
    ev = f"Founded in {yf} (about {age_m // 12} years ago)." + (f" Claimed turnover about {usd(t)} a year." if t else "")
    if age_m < P["P3"] and (t or 0) >= 1_000_000:
        return O("REG-03", "Flag", f"{yf}", ev + " A very young company claiming large business.", "crustdata")
    if age_m < P["P3"]:
        return O("REG-03", "Partial", f"{yf}", ev + " A very young company.", "crustdata")
    return O("REG-03", "Pass", f"{yf}", ev, "crustdata")


def reg05(ctx):
    c = ctx["company"]
    hq = g(c, "locations.country") or SL.to_iso3(ctx["inp"].country)
    lhc = g(c, "headcount.largest_headcount_country")
    if not hq:
        return U("REG-05", "head-office country unknown")
    risky = hq in SL.LOW_TRANSPARENCY or hq in SL.FATF_GREY or hq in SL.FATF_BLACK
    ev = f"Head office in {country(hq)}" + (f"; most staff in {country(lhc)}." if lhc else ".")
    if risky and (not lhc or lhc != hq):
        return O("REG-05", "Flag", country(hq), ev + " This is a secrecy or high-risk country and no staff are visible there.", "static")
    if risky:
        return O("REG-05", "Partial", country(hq), ev + " This is a secrecy or high-risk country, but staff are there; ask why.", "static")
    return O("REG-05", "Pass", country(hq), ev + " Not a secrecy or high-risk country.", "static")


def reg07(ctx):
    inp, gst, c = ctx["inp"], ctx["gst"], ctx["company"]
    if SL.to_iso3(inp.country) != "IND":
        return NA("REG-07", "GSTIN only applies to Indian entities (other tax IDs not automated)")
    if not gst.get("provided"):
        return U("REG-07", "no GSTIN supplied", "gstin")
    if not gst.get("valid"):
        return O("REG-07", "Flag", gst.get("gstin"), f"The GST number is not valid ({(gst.get('reason') or '').lower()}). A made-up or mistyped number usually fails this.", "gstin", rel=0.85)
    notes = [f"The GST number is correctly formed and registered to {gst['state']}; the PAN inside belongs to a {gst['pan_entity_type'].lower()}"]
    res = "Pass"
    nm = inp.company_name.lower()
    if any(k in nm for k in ("pvt", "private", "limited", "ltd")) and gst["pan"][3] not in ("C",) and "llp" not in nm:
        res = "Partial"; notes.append("but the name says it is a company while the PAN is not a company PAN")
    notes.append("(We can check the format only — the government GST website needs a manual check)")
    return O("REG-07", res, gst["gstin"], " ".join(notes) + ".", "gstin")


def adr03(ctx):
    gst, c = ctx["gst"], ctx["company"]
    st = (g(c, "locations.state") or "").lower()
    if not gst.get("valid") or not st:
        return U("ADR-03", "needs both a valid GSTIN and a profile HQ state", "gstin")
    gs = (gst.get("state") or "").lower()
    import unicodedata
    clean = lambda s: unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    if clean(gs)[:5] == clean(st)[:5]:
        return O("ADR-03", "Pass", gst["state"], f"GST registered in {gst['state']}, same state as the head office.", "crustdata")
    return O("ADR-03", "Partial", gst["state"], f"GST registered in {gst['state']}, but the head office is in {g(c, 'locations.state')}. (Companies can legitimately have GST in several states.)", "crustdata")


def adr04(ctx):
    inp, c, site = ctx["inp"], ctx["company"], ctx["site"]
    emails = [e for e in [inp.contact_email, g(c, "funding.contact_email")] + (site.get("emails") or []) if e]
    if not emails:
        return U("ADR-04", "no contact email available", "website")
    dom = inp.domain or g(c, "basic_info.primary_domain") or ""
    e = emails[0].lower()
    ed = e.split("@")[-1]
    if ed in SL.FREE_MAIL:
        return O("ADR-04", "Partial", e, f"The company uses a free email address ({ed}). Common for very small firms, unusual for larger ones.", "website")
    base = lambda d: ".".join(d.split(".")[-2:])
    if dom and base(ed) != base(dom):
        return O("ADR-04", "Flag", e, f"The contact email is on a different website ({ed}) from the company's own ({dom}).", "website")
    return O("ADR-04", "Pass", e, f"Uses an email address on its own website ({ed}).", "website")


def adr05(ctx):
    r = ctx["rdap"]
    if not r.get("found"):
        return U("ADR-05", "no registration record found for the website address", "rdap")
    yrs = years_since(r.get("created"))
    ev = (f"Website address registered on {r.get('created')} ({yrs:.1f} years ago). "
          f"Owner details are {'hidden' if r.get('privacy') else 'public'}.")
    url = f"https://rdap.org/domain/{r['domain']}"
    if yrs is not None and yrs < 0.5:
        return O("ADR-05", "Flag", f"{yrs:.1f} yrs", ev + " Very new.", "rdap", url)
    if yrs is not None and (yrs < 1.5 or (r.get("privacy") and yrs < 2)):
        return O("ADR-05", "Partial", f"{yrs:.1f} yrs", ev + " Fairly new.", "rdap", url)
    return O("ADR-05", "Pass", f"{yrs:.1f} yrs", ev, "rdap", url)


def ops01(ctx):
    c, inp, P = ctx["company"], ctx["inp"], ctx["P"]
    if not c:
        if claims_scale(inp, P):
            return O("OPS-01", "Flag", "not found", "We could not find this company in business databases, even though it claims to be a sizeable business.", "crustdata")
        return O("OPS-01", "Partial", "not found", "We could not find this company in business databases. Small or new firms are often missing.", "crustdata")
    conf = ctx.get("match_conf", 1.0)
    url = g(c, "basic_info.professional_network_url")
    ev = f"Found as '{g(c, 'basic_info.name')}' ({g(c, 'basic_info.primary_domain')})" + ("." if conf >= 0.7 else ", but we're not fully sure it's the same company.")
    return O("OPS-01", "Pass" if conf >= 0.7 else "Partial", g(c, "basic_info.name"), ev, "crustdata", url)


def ops02(ctx):
    c, inp, P = ctx["company"], ctx["inp"], ctx["P"]
    hc = observed_headcount(c)
    if hc is None:
        return U("OPS-02", "no staff data")
    dh = inp.declared_headcount
    ev = f"We found {hc:,} employees" + (f"; the company claims {dh:,}." if dh is not None else "; no staff number was claimed.")
    if hc <= P["P1"] and claims_scale(inp, P):
        return O("OPS-02", "Flag", hc, ev + f" That is {int(P['P1'])} or fewer people for a business claiming real size.", "crustdata")
    if dh:
        ratio = hc / dh
        if ratio < P["P11"]:
            return O("OPS-02", "Flag", hc, ev + f" Only {ratio:.0%} of the claim. (Contractors don't show up in this data.)", "crustdata")
        if ratio < 0.5:
            return O("OPS-02", "Partial", hc, ev + f" About {ratio:.0%} of the claim.", "crustdata")
    return O("OPS-02", "Pass", hc, ev, "crustdata")


def ops03(ctx):
    c = ctx["company"]
    ts = g(c, "headcount.timeseries") or []
    hc = observed_headcount(c)
    if hc is None:
        return U("OPS-03", "no staff data")
    yoy = g(c, "headcount.growth_percent.yoy")
    fund = g(c, "funding.total_investment_usd") or 0
    rev_u = g(c, "revenue.estimated.upper_bound_usd") or 0
    span = ""
    if len(ts) >= 2:
        try:
            first = dt.date.fromisoformat(str(ts[0]["date"])[:10])
            span = f" going back about {max(1, round((dt.date.today() - first).days / 365.25))} year(s)"
        except (ValueError, KeyError):
            pass
    ev = (f"We have {len(ts)} monthly staff records{span}." + (f" Staff changed {yoy:+.0f}% over the last year." if yoy is not None else ""))
    if len(ts) < 3 and hc <= 3:
        return O("OPS-03", "Flag", f"{len(ts)} pts", ev + " Almost no history and almost no staff.", "crustdata")
    if yoy is not None and yoy > 300 and fund == 0 and rev_u < 1_000_000:
        return O("OPS-03", "Flag", f"+{yoy:.0f}%", ev + " A sudden jump in staff with no funding or revenue to explain it.", "crustdata")
    if len(ts) < 3:
        return O("OPS-03", "Partial", f"{len(ts)} pts", ev + " Very little history.", "crustdata")
    return O("OPS-03", "Pass", f"{len(ts)} pts", ev, "crustdata")


def ops04(ctx):
    c, P = ctx["company"], ctx["P"]
    six = g(c, "headcount.growth_percent.six_months")
    if six is None:
        return U("OPS-04", "no recent staff trend")
    if six < -P["P8"] * 100:
        return O("OPS-04", "Flag", f"{six:.0f}%", f"Staff fell {abs(six):.0f}% in the last 6 months.", "crustdata")
    if six < -20:
        return O("OPS-04", "Partial", f"{six:.0f}%", f"Staff fell {abs(six):.0f}% in the last 6 months; check the news for layoffs.", "crustdata")
    return O("OPS-04", "Pass", f"{six:+.0f}%", f"Staff {'grew' if six >= 0 else 'fell'} {abs(six):.1f}% in the last 6 months.", "crustdata")


def ops05(ctx):
    c = ctx["company"]
    roles = g(c, "headcount.by_role_absolute") or {}
    hc = observed_headcount(c) or 0
    if not roles:
        return U("OPS-05", "no department breakdown")
    tot = sum(roles.values()) or 1
    top, n = max(roles.items(), key=lambda kv: kv[1])
    share = n / tot
    ev = f"Staff work in {len(roles)} department(s); the largest is {top} ({share:.0%})."
    if hc >= 10 and (len(roles) == 1 or share > 0.85):
        return O("OPS-05", "Flag", f"{len(roles)} depts", ev + " Almost everyone is in one department.", "crustdata")
    if len(roles) <= 2:
        return O("OPS-05", "Partial", f"{len(roles)} depts", ev + " Very few departments.", "crustdata")
    return O("OPS-05", "Pass", f"{len(roles)} depts", ev, "crustdata")


def ops06(ctx):
    c, inp = ctx["company"], ctx["inp"]
    lhc = g(c, "headcount.largest_headcount_country")
    if not lhc:
        return U("OPS-06", "no data on where staff are located")
    want = {x for x in (SL.to_iso3(inp.country), g(c, "locations.country")) if x}
    ev = f"Most staff are in {country(lhc)}."
    if want and lhc not in want:
        return O("OPS-06", "Flag", country(lhc), ev + f" But the company says it operates in {', '.join(country(w) for w in sorted(want))}.", "crustdata")
    return O("OPS-06", "Pass", country(lhc), ev + " This matches where it says it operates.", "crustdata")


def job_stats(jobs: dict | None, company=None) -> dict | None:
    """Summarise detailed job postings (Crustdata /job/search)."""
    if jobs is None:
        return None
    L = jobs.get("job_listings") or []
    today = dt.date.today()

    def age_days(j):
        d = (g(j, "metadata.date_added") or "")[:10]
        try:
            return (today - dt.date.fromisoformat(d)).days
        except ValueError:
            return None
    ages = [a for a in (age_days(j) for j in L) if a is not None]
    descs = [(g(j, "content.description") or "").strip() for j in L]
    real = [d for d in descs if len(d.replace(".", "").replace(" ", "")) >= 120]
    titles = [g(j, "job_details.title") for j in L if g(j, "job_details.title")]
    cats = {}
    for j in L:
        k = g(j, "job_details.category") or "Unspecified"
        cats[k] = cats.get(k, 0) + 1
    hq = g(company, "locations.country")
    countries = [g(j, "location.country") for j in L if g(j, "location.country")]
    norm_d = [d.lower()[:400] for d in real]
    return {
        "total": jobs.get("total_count") or len(L), "sampled": len(L),
        "last_12m": sum(1 for a in ages if a <= 365), "newest_days": min(ages) if ages else None,
        "titles": titles[:8], "unique_titles": len(set(titles)), "categories": cats,
        "thin_descriptions": len(descs) - len(real), "duplicate_descriptions": len(norm_d) - len(set(norm_d)),
        "reposted": sum(1 for j in L if g(j, "job_details.reposted_job")),
        "countries": sorted(set(countries)), "hq_country": hq,
        "openings": sum((g(j, "job_details.number_of_openings") or 0) for j in L),
        "hiring_open_now": g(company, "hiring.openings_count"),
        "listings": [{"title": g(j, "job_details.title"), "category": g(j, "job_details.category"),
                      "location": g(j, "location.raw"), "date": (g(j, "metadata.date_added") or "")[:10],
                      "type": g(j, "job_details.employment_type"), "workplace": g(j, "job_details.workplace_type"),
                      "url": g(j, "job_details.url"), "desc_len": len(d)} for j, d in zip(L, descs)][:10],
    }


def ops07(ctx):
    st = ctx.get("job_stats")
    if st is None:
        return U("OPS-07", "job search not run")
    tot, inp, c = st["total"], ctx["inp"], ctx["company"]
    yoy = g(c, "headcount.growth_percent.yoy") or 0
    claims_growth = (inp.declared_headcount or 0) > (observed_headcount(c) or 0) * 1.5 or yoy > 20
    newest = st["newest_days"]
    when = ("" if newest is None else f"; the latest was {newest} days ago" if newest < 60 else f"; the latest was about {round(newest / 30)} months ago"
            if newest < 730 else f"; the latest was about {round(newest / 365)} years ago")
    ev = (f"{tot} job post(s) on record, {st['last_12m']} in the last 12 months{when}."
          + (f" Recent roles: {', '.join(st['titles'][:3])}." if st["titles"] else ""))
    url = (st["listings"][0]["url"] if st["listings"] else None)
    if tot == 0:
        return O("OPS-07", "Flag" if claims_growth else "Partial", 0,
                 ev + (" It claims to be growing but has never advertised a job." if claims_growth else " No hiring history (a weak sign on its own)."), "crustdata")
    issues = []
    s = st["sampled"]
    if s >= 3 and st["duplicate_descriptions"] >= s / 2:
        issues.append(f"{st['duplicate_descriptions']} of {s} postings share an identical description")
    if s >= 3 and st["unique_titles"] == 1:
        issues.append("all sampled postings have the same title")
    if s >= 3 and st["thin_descriptions"] >= s * 0.8:
        issues.append(f"{st['thin_descriptions']} of {s} postings have empty/boilerplate descriptions")
    if st["hq_country"] and st["countries"] and SL.to_iso3(st["countries"][0]) and all(SL.to_iso3(x) not in (st["hq_country"], None) for x in st["countries"]):
        issues.append(f"all postings are outside the HQ country ({', '.join(st['countries'][:3])})")
    if issues:
        return O("OPS-07", "Flag" if len(issues) >= 2 else "Partial", tot, ev + " Problems: " + "; ".join(issues) + ".", "crustdata", url)
    if claims_growth and st["last_12m"] == 0:
        return O("OPS-07", "Partial", tot, ev + " No job ads in the last year despite claimed growth.", "crustdata", url)
    return O("OPS-07", "Pass", tot, ev, "crustdata", url)


def _traffic(c):
    dt_ = g(c, "web_traffic.domain_traffic") or {}
    if not dt_:
        return None
    return max(dt_.values(), key=lambda v: (v or {}).get("monthly_visitors") or 0)


def ops08(ctx):
    c, inp, P, site = ctx["company"], ctx["inp"], ctx["P"], ctx["site"]
    t = _traffic(c)
    no_site = site.get("checked") and not site.get("reachable")
    if no_site:
        return O("OPS-08", "Flag", "no site", f"The company website does not open ({_why(site)}).", "website")
    if not t or t.get("monthly_visitors") is None:
        if inp.business_type == "b2b":
            return NA("OPS-08", "Business-to-business companies naturally get few website visitors, so this is not checked.")
        return U("OPS-08", "no website visitor data")
    mv = t["monthly_visitors"]
    ev = f"About {big(mv)} visitors a month to {t.get('domain')}."
    if inp.business_type in ("consumer", "platform") and mv < P["P4"]:
        return O("OPS-08", "Flag", big(mv), ev + f" Very low for a business that sells to the public online (under {int(P['P4'])}).", "crustdata")
    return O("OPS-08", "Pass", big(mv), ev, "crustdata")


def ops09(ctx):
    t = _traffic(ctx["company"])
    if not t or t.get("monthly_visitors") is None:
        return U("OPS-09", "no website visitor breakdown")
    names = {"direct": "typing the address directly", "search": "search engines", "social": "social media",
             "paid_referral": "paid ads", "referral": "links from other sites"}
    srcs = {k.replace("source_", "").replace("_pct", ""): v for k, v in t.items() if k.startswith("source_") and k.endswith("_pct") and v is not None}
    mom = t.get("mom_pct")
    top = max(srcs.items(), key=lambda kv: kv[1]) if srcs else (None, 0)
    ev = (f"Most visitors ({top[1]:.0f}%) arrive by {names.get(top[0], top[0])}." if top[0] else "Visitor sources unknown.") + \
         (f" Visits changed {mom:+.0f}% last month." if mom is not None else "")
    if (top[1] or 0) > 95 or (mom or 0) > 300:
        return O("OPS-09", "Partial", f"{top[0]} {top[1]:.0f}%", ev + " Traffic is unusually concentrated or spiky.", "crustdata")
    return O("OPS-09", "Pass", f"{top[0]} {top[1]:.0f}%", ev, "crustdata")


def ops10(ctx):
    site, inp, c = ctx["site"], ctx["inp"], ctx["company"]
    digital = inp.business_type in ("platform", "consumer")
    tech = g(c, "technographics")
    if tech:  # Crustdata technographics (gated add-on) — preferred source
        n = tech.get("total_technologies") or len(tech.get("technologies") or [])
        top = [t if isinstance(t, str) else (t or {}).get("name") for t in (tech.get("top_technologies") or [])][:6]
        ev = f"Crustdata technographics: {n} technologies detected" + (f" (e.g. {', '.join(x for x in top if x)})" if top else "")
        if n == 0 and digital:
            return O("OPS-10", "Flag", 0, ev + " — none for a company claiming a digital product", "crustdata")
        if n < 5 and digital:
            return O("OPS-10", "Partial", n, ev + " — very thin stack for a digital product", "crustdata")
        return O("OPS-10", "Pass", n, ev, "crustdata")
    if not site.get("checked"):
        return U("OPS-10", "website not checked and technographics unavailable", "website")
    if not site.get("reachable"):
        return U("OPS-10", "website unreachable", "website")
    ev = (f"Its homepage has {site.get('links')} links" + (" and contains template placeholder text" if site.get("template") else "") +
          ". (Judged from the website, because detailed software data is not enabled on our data plan.)")
    if site.get("parked") or (site.get("template") and site.get("links", 0) < 15):
        return O("OPS-10", "Flag" if digital else "Partial", "template", ev, "website", site.get("final_url"))
    if site.get("links", 0) < 8:
        return O("OPS-10", "Partial", "thin", ev + " It looks like a one-page site.", "website", site.get("final_url"))
    return O("OPS-10", "Pass", f"{site.get('links')} links", ev, "website", site.get("final_url"))


def ops11(ctx):
    c, inp, P = ctx["company"], ctx["inp"], ctx["P"]
    t = inp.turnover_usd()
    if t is None:
        return NA("OPS-11", "No turnover was given, so there is nothing to compare.")
    up = g(c, "revenue.estimated.upper_bound_usd")
    lo = g(c, "revenue.estimated.lower_bound_usd")
    if not up:
        return U("OPS-11", "no revenue estimate available")
    mult = t / up
    ev = f"Claimed turnover about {usd(t)}; estimated revenue {usd(lo or 0)} to {usd(up)} a year."
    if mult > P["P9"]:
        return O("OPS-11", "Flag", f"{mult:.1f}x", ev + f" The claim is {mult:.0f} times the top estimate. (Estimates are rough.)", "crustdata")
    return O("OPS-11", "Pass", f"{mult:.1f}x", ev + " The claim is within a realistic range.", "crustdata")


def ops12(ctx):
    c, inp = ctx["company"], ctx["inp"]
    if not inp.claims_funding:
        return NA("OPS-12", "no funding claimed")
    if not c:
        return U("OPS-12", "no profile")
    tot = g(c, "funding.total_investment_usd") or 0
    n = g(c, "funding.num_funding_rounds") or 0
    ev = f"Investment on record: {usd(tot)} in {n} funding round(s)."
    if tot == 0 and n == 0:
        return O("OPS-12", "Flag", "none", ev + " It claims to have investors, but none are on record.", "crustdata")
    return O("OPS-12", "Pass", f"USD {tot:,.0f}", ev, "crustdata")


def ops13(ctx):
    c, inp = ctx["company"], ctx["inp"]
    hc = max(observed_headcount(c) or 0, inp.declared_headcount or 0)
    er = g(c, "employee_reviews.overall_rating.total_count") or 0
    sr = g(c, "software_reviews.review_count") or 0
    if hc < 50:
        return NA("OPS-13", "Small companies (under 50 staff) often have no reviews, so this is not checked.")
    ev = f"{er:,} employee reviews and {sr:,} product reviews found."
    if er + sr == 0:
        return O("OPS-13", "Partial", 0, ev + " None at all, despite the size.", "crustdata")
    return O("OPS-13", "Pass", er + sr, ev, "crustdata")


def ops14(ctx):
    c = ctx["company"]
    if not c:
        return U("OPS-14", "no company profile")
    f = g(c, "followers.count")
    news = len(g(c, "news") or [])
    if f is None and news == 0:
        return U("OPS-14", "no social media or news data")
    ev = f"{big(f or 0)} followers on its business profile and {news} news article(s) found."
    if (f or 0) < 50 and news == 0:
        return O("OPS-14", "Flag", f, ev + " Almost no public presence.", "crustdata")
    if (f or 0) < 500 and news == 0:
        return O("OPS-14", "Partial", f, ev + " Very small public presence.", "crustdata")
    return O("OPS-14", "Pass", f, ev, "crustdata")


def ops15(ctx):
    c, r = ctx["company"], ctx["rdap"]
    yf = g(c, "basic_info.year_founded")
    dy = years_since(r.get("created"))
    if not yf or dy is None:
        return U("OPS-15", "needs both the founding year and the website registration date", "rdap")
    claimed = dt.date.today().year - int(yf)
    gap = claimed - dy
    ev = f"Says it started in {yf} (about {claimed} years ago); its website address is {dy:.0f} years old."
    if gap > 6:
        return O("OPS-15", "Flag", f"gap {gap:.0f}y", ev + " Its online presence is much younger than its claimed history.", "rdap")
    if gap > 3:
        return O("OPS-15", "Partial", f"gap {gap:.0f}y", ev + " A rebrand or new website could explain the gap.", "rdap")
    return O("OPS-15", "Pass", f"gap {max(gap, 0):.0f}y", ev + " These line up.", "rdap")


def _people(c):
    out, seen = [], set()
    for grp in ("founders", "cxos", "decision_makers"):
        for p in g(c, f"people.{grp}") or []:
            n = g(p, "basic_profile.name")
            if n and n not in seen:
                seen.add(n)
                out.append({"name": n, "title": g(p, "basic_profile.current_title") or "", "group": grp,
                            "headline": g(p, "basic_profile.headline") or ""})
    return out


def find_director(ctx):
    d = ctx["inp"].director
    if not d:
        return None
    best = None
    for p in _people(ctx["company"]):
        s = name_sim(d, p["name"])
        if s > 0.85 and (not best or s > best[0]):
            best = (s, p)
    return best[1] if best else None


def ppl02(ctx):
    inp = ctx["inp"]
    if not inp.director:
        return U("PPL-02", "no director named in application")
    p = find_director(ctx)
    if p:
        return O("PPL-02", "Pass", p["title"], f"{p['name']} is listed as '{p['title']}' at this company.", "crustdata")
    ext = ctx.get("director_search")
    if ext:
        return O("PPL-02", "Partial", ext.get("title"), f"We found a profile for {inp.director}, but at another company ({ext.get('employer')}).", "crustdata")
    return U("PPL-02", f"no professional profile found for {inp.director}")


def ppl04(ctx):
    inp, c = ctx["inp"], ctx["company"]
    if not inp.director:
        return U("PPL-04", "no director named")
    if not c:
        return U("PPL-04", "no profile")
    p = find_director(ctx)
    if p:
        return O("PPL-04", "Pass", p["title"], f"{inp.director} is listed in the company's leadership as '{p['title']}'.", "crustdata")
    ext = ctx.get("director_search")
    if ext and ext.get("employer") and name_sim(ext["employer"], g(c, "basic_info.name", "")) < 0.6:
        return O("PPL-04", "Flag", ext["employer"], f"{inp.director}'s own profile says they currently work at '{ext['employer']}', not this company.", "crustdata")
    return O("PPL-04", "Partial", "not listed", f"{inp.director} is not among the {len(_people(c))} founders and leaders we found for this company.", "crustdata")


def ppl05(ctx):
    c = ctx["company"]
    hc = observed_headcount(c)
    if hc is None:
        return U("PPL-05", "no headcount")
    n = len(_people(c))
    ev = f"{hc:,} staff and {n} named leader(s) found."
    if hc <= 2 and n <= 1:
        return O("PPL-05", "Flag", f"{n} leaders", ev + " One person appears to be the whole company (common in very small businesses).", "crustdata")
    return O("PPL-05", "Pass", f"{n} leaders", ev, "crustdata")


def grf01(ctx):
    links = ctx["graph"].get("director_links") or {}
    if not ctx["inp"].director and not links:
        return U("GRF-01", "no director names to check", "internal")
    P = ctx["P"]
    worst = max(links.items(), key=lambda kv: kv[1]) if links else (ctx["inp"].director, 1)
    n = worst[1]
    ev = (f"{worst[0]} is linked to {n} compan{'y' if n == 1 else 'ies'} in our records." if n > 1
          else "None of its directors appear at other companies in our records.")
    if n > P["P5"]:
        return O("GRF-01", "Flag", n, ev + " Typical of front-men or nominee directors.", "internal")
    if n > 3:
        return O("GRF-01", "Partial", n, ev, "internal")
    return O("GRF-01", "Pass", n, ev, "internal")


def grf03(ctx):
    sh = ctx["graph"].get("shared") or []
    if not sh:
        return O("GRF-03", "Pass", 0, "Its address, phone, email and directors are not shared with other companies we know of", "internal")
    by: dict[str, list[str]] = {}
    for x in sh:
        by.setdefault(x["kind"], [])
        if x["other"] not in by[x["kind"]]:
            by[x["kind"]].append(x["other"])
    parts = []
    for kind, others in by.items():
        names = ", ".join(o.replace(" Pvt Ltd", "") for o in others[:3]) + (f" and {len(others) - 3} more" if len(others) > 3 else "")
        parts.append(f"same {kind} as {len(others)} other compan{'y' if len(others) == 1 else 'ies'} ({names})")
    ev = "Shares the " + "; the ".join(parts)
    return O("GRF-03", "Flag" if len(sh) >= 2 else "Partial", len(sh), ev, "internal")


def grf04(ctx):
    d = ctx["graph"].get("dup_desc")
    if not d:
        return O("GRF-04", "Pass", "-", "Its business description is not copied from any company we know of.", "internal")
    return O("GRF-04", "Flag", f"{d['score']:.2f}", f"Its business description is {d['score']:.0%} identical to {d['other']}'s.", "internal")


def grf06(ctx):
    w = ctx["graph"].get("watchlist") or []
    if not w:
        return O("GRF-06", "Pass", 0, "Not connected to any company we previously rejected or reported", "internal")
    by: dict[str, list[str]] = {}
    for name, kind in w:
        by.setdefault(name, []).append(kind)
    txt = "; ".join(f"{n} (shares its {' and '.join(dict.fromkeys(k))})" for n, k in by.items())
    return O("GRF-06", "Flag", len(by), "Connected to a company we previously rejected or reported: " + txt, "internal")


def bus01(ctx):
    c, inp = ctx["company"], ctx["inp"]
    desc = (g(c, "basic_info.description") or inp.stated_business or "").strip()
    if not desc:
        return U("BUS-01", "no business description available", "heuristic")
    low = desc.lower()
    hits = [t for t in SL.GENERIC_DESC_TERMS if t in low]
    short = desc[:110] + ("…" if len(desc) > 110 else "")
    if hits and len(desc) < 160:
        return O("BUS-01", "Flag", "generic", f"Description is short and vague (\"{short}\"), using words like {', '.join(hits[:3])}.", "heuristic")
    if hits or len(desc) < 60:
        return O("BUS-01", "Partial", "vague", f"Description is somewhat vague (\"{short}\").", "heuristic")
    return O("BUS-01", "Pass", "specific", f"Description is specific: \"{short}\"", "heuristic")


def bus03(ctx):
    c, inp = ctx["company"], ctx["inp"]
    if not inp.stated_business or not c:
        return U("BUS-03", "needs stated business and profile industry", "heuristic")
    tax = " ".join([g(c, "taxonomy.professional_network_industry") or ""] + (g(c, "taxonomy.categories") or []) +
                   (g(c, "taxonomy.professional_network_specialities") or []) + (g(c, "basic_info.industries") or [])).lower()
    words = {w for w in inp.stated_business.lower().replace(",", " ").split() if len(w) > 3}
    hit = [w for w in words if w[:5] in tax]
    ev = f"Says it does '{inp.stated_business[:60]}'; listed industry is '{g(c, 'taxonomy.professional_network_industry')}'."
    if hit:
        return O("BUS-03", "Pass", ", ".join(hit[:3]), ev, "heuristic")
    return O("BUS-03", "Partial", "no overlap", ev + " These don't obviously match (may just be different wording).", "heuristic")


def bus04(ctx):
    c, inp = ctx["company"], ctx["inp"]
    text = " ".join([g(c, "basic_info.description") or "", inp.stated_business or "", g(c, "taxonomy.professional_network_industry") or ""]
                    + (g(c, "taxonomy.categories") or [])).lower()
    if not text.strip():
        return U("BUS-04", "no sector information", "heuristic")
    hits = [t for t in SL.HIGH_RISK_SECTOR_TERMS if t in text]
    if inp.business_type == "trading":
        hits.append("declared trading business")
    if hits:
        return O("BUS-04", "Flag", hits[0], f"Works in a higher-risk area ({', '.join(sorted(set(hits))[:3])}). This means extra checks are needed — it is not proof of wrongdoing.", "static")
    return O("BUS-04", "Pass", "-", "Not in a higher-risk industry.", "static")


def _scr(cid, res, label):
    if not res or not res.get("available"):
        return U(cid, "the sanctions list could not be loaded", "ofac")
    m = res["matches"]
    n = res["status"].split("(")[-1].split(" ")[0] if "(" in res["status"] else ""
    if not m:
        return O(cid, "Pass", "no match", f"No {label} found on the US sanctions list ({n} names checked).", "ofac",
                 "https://sanctionssearch.ofac.treas.gov/")
    top = m[0]
    strong = top["score"] >= 0.93
    nm = top["name"].split(" (alias of")[0]
    ev = (f"The name matches '{nm}' on the US sanctions list." if strong
          else f"The name is similar to '{nm}' on the US sanctions list (could be a coincidence).")
    return O(cid, "Flag" if strong else "Partial", top["score"],
             ev + (" Confirm identity before any business." if strong else " A person must check whether it is the same party."), "ofac",
             "https://sanctionssearch.ofac.treas.gov/")


def scr01(ctx):
    return _scr("SCR-01", ctx.get("sanc_entity"), "company with this name")


def scr02(ctx):
    res = ctx.get("sanc_people")
    if res and res.get("available") and res.get("screened") == 0:
        return U("SCR-02", "no named people to screen", "ofac")
    return _scr("SCR-02", res, "director or leader")


def scr04(ctx):
    am = ctx.get("adverse")
    if am is None:
        return U("SCR-04", "news search did not run", "news")
    acc = [i for i in am["items"] if i.get("relation") == "accused"]
    vic = [i for i in am["items"] if i.get("relation") == "victim"]
    if not am["items"]:
        return O("SCR-04", "Pass", 0, "No news found linking this company to fraud, scams, raids or similar.", "news")
    ev = f"{len(am['items'])} headline(s) mention the company alongside words like fraud or scam: {len(acc)} describe it as the wrongdoer, {len(vic)} as the victim."
    if acc:
        ev += " For example: " + "; ".join(f"“{i['title'][:90]}”" for i in acc[:2])
        return O("SCR-04", "Flag" if len(acc) >= 2 else "Partial", len(acc), ev, "news", acc[0].get("url"))
    return O("SCR-04", "Pass", 0, ev, "news")


def scr05(ctx):
    c, inp = ctx["company"], ctx["inp"]
    places = {x for x in (g(c, "locations.country"), g(c, "headcount.largest_headcount_country"), SL.to_iso3(inp.country)) if x}
    if not places:
        return U("SCR-05", "no country information", "static")
    blk, gry = places & SL.FATF_BLACK, places & SL.FATF_GREY
    names = ", ".join(country(p) for p in sorted(places))
    if blk:
        return O("SCR-05", "Flag", ",".join(blk), f"Linked to {', '.join(country(b) for b in blk)}, on the international blacklist of high-risk countries.", "static")
    if gry:
        return O("SCR-05", "Partial", ",".join(gry), f"Linked to {', '.join(country(b) for b in gry)}, on the international watch-list of high-risk countries.", "static")
    return O("SCR-05", "Pass", names, f"Countries involved ({names}) are not on the international high-risk lists.", "static")


def txn01(ctx):
    c, inp, P = ctx["company"], ctx["inp"], ctx["P"]
    t = inp.turnover_usd()
    if t is None:
        return NA("TXN-01", "No turnover was given, so there is nothing to compare.")
    hc = observed_headcount(c)
    if hc is None:
        return U("TXN-01", "no staff data")
    per = t / max(hc, 1)
    ev = f"Claimed turnover works out to about {usd(per)} per employee ({hc:,} staff found)."
    if per > P["P2"]:
        return O("TXN-01", "Flag", usd(per), ev + f" More than {usd(P['P2'])} per person is unrealistic for most businesses.", "crustdata")
    if per > P["P2"] / 2:
        return O("TXN-01", "Partial", usd(per), ev + " Very high per person.", "crustdata")
    return O("TXN-01", "Pass", usd(per), ev + " Realistic.", "crustdata")


def _why(site):
    e = (site.get("error") or "")
    if "Timeout" in e:
        return "no response — it may be offline or seized"
    if "ConnectError" in e or "Name or service" in e or "getaddrinfo" in e:
        return "the address does not exist"
    if site.get("status"):
        return f"server error {site['status']}"
    return "could not connect"


def mon01(ctx):
    s = ctx["site"]
    if not s.get("checked"):
        return U("MON-01", "no website address to check", "website")
    if not s.get("reachable"):
        return O("MON-01", "Flag", "offline", f"The website does not open ({_why(s)}).", "website")
    if s.get("parked"):
        return O("MON-01", "Flag", "parked", "The website is a parked or 'for sale' page.", "website", s.get("final_url"))
    return O("MON-01", "Pass", f"HTTP {s.get('status')}", f"The website opens normally{' over a secure connection' if s.get('https') else ''}.",
             "website", s.get("final_url"))


EVALUATORS: dict[str, Callable] = {
    "REG-02": reg02, "REG-03": reg03, "REG-05": reg05, "REG-07": reg07,
    "ADR-03": adr03, "ADR-04": adr04, "ADR-05": adr05,
    "OPS-01": ops01, "OPS-02": ops02, "OPS-03": ops03, "OPS-04": ops04, "OPS-05": ops05, "OPS-06": ops06,
    "OPS-07": ops07, "OPS-08": ops08, "OPS-09": ops09, "OPS-10": ops10, "OPS-11": ops11, "OPS-12": ops12,
    "OPS-13": ops13, "OPS-14": ops14, "OPS-15": ops15,
    "PPL-02": ppl02, "PPL-04": ppl04, "PPL-05": ppl05,
    "GRF-01": grf01, "GRF-03": grf03, "GRF-04": grf04, "GRF-06": grf06,
    "BUS-01": bus01, "BUS-03": bus03, "BUS-04": bus04,
    "SCR-01": scr01, "SCR-02": scr02, "SCR-04": scr04, "SCR-05": scr05,
    "TXN-01": txn01, "MON-01": mon01,
}
# Checks needing a Crustdata profile: if no profile, they become unverifiable.
NEEDS_PROFILE = {"REG-03", "OPS-02", "OPS-03", "OPS-04", "OPS-05", "OPS-06", "OPS-09", "OPS-11", "OPS-13", "OPS-14", "OPS-15",
                 "PPL-05", "TXN-01", "ADR-03"}


def run_all(ctx) -> dict[str, CheckOutcome]:
    out = {}
    for cid, fn in EVALUATORS.items():
        if cid in NEEDS_PROFILE and not ctx["company"] and cid not in ("OPS-11", "TXN-01"):
            out[cid] = U(cid, "no Crustdata profile resolved")
            continue
        try:
            out[cid] = fn(ctx)
        except Exception as e:  # noqa: BLE001 — one broken check never breaks the investigation
            out[cid] = U(cid, f"evaluator error {type(e).__name__}: {e}", "internal")
    return out
