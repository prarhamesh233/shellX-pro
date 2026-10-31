"""FastAPI app: investigations, live SSE log, analyst edits, dossier PDF, badge page."""
from __future__ import annotations

import asyncio
import datetime as dt
import html
import json
import threading
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import agent, config, store
from .dossier import build_pdf
from .models import Intake
from .seed import SYNTHETIC, seed_network
from .sources import sanctions
from .workbook import load_workbook

app = FastAPI(title="ShellX Pro")
RUNS: dict[str, dict] = {}


@app.on_event("startup")
async def _startup():
    store.init()
    seed_network()
    load_workbook()
    threading.Thread(target=sanctions.refresh_lists, daemon=True).start()


@app.get("/api/health")
async def health():
    wb = load_workbook()
    lst, status = sanctions.load_list()
    return {"crustdata": bool(config.CRUSTDATA_API_KEY), "llm": bool(config.GROQ_API_KEY), "llm_model": config.LLM_MODEL,
            "replay_mode": config.REPLAY_MODE, "workbook": wb.path.split("/")[-1], "checks": len(wb.checks),
            "automated_checks": len(agent.run_all.__globals__["EVALUATORS"]), "sanctions": status, "credit_cap": config.CREDIT_CAP}


@app.get("/api/workbook")
async def workbook():
    from .workbook import labels_json
    return {**load_workbook().to_json(), "labels": labels_json()}


@app.get("/api/demos")
async def demos():
    return [{"domain": d, "label": v["label"], "intake": v["intake"]} for d, v in SYNTHETIC.items()]


@app.post("/api/investigate")
async def start(inp: Intake):
    rid = uuid.uuid4().hex[:10]
    run = {"events": [], "done": False, "result": None, "cond": asyncio.Condition()}
    RUNS[rid] = run

    async def emit(ev):
        async with run["cond"]:
            run["events"].append(ev)
            run["cond"].notify_all()

    async def go():
        try:
            run["result"] = await asyncio.wait_for(agent.investigate(inp, emit, run_id=rid), timeout=240)
        except Exception as e:  # noqa: BLE001
            await emit({"type": "error", "msg": f"{type(e).__name__}: {e}"})
            run["result"] = {"id": rid, "status": "error", "error": str(e)}
        finally:
            async with run["cond"]:
                run["done"] = True
                run["cond"].notify_all()

    asyncio.create_task(go())
    return {"id": rid}


@app.get("/api/stream/{rid}")
async def stream(rid: str):
    run = RUNS.get(rid)
    if not run:
        raise HTTPException(404)

    async def gen():
        i = 0
        while True:
            async with run["cond"]:
                while i >= len(run["events"]) and not run["done"]:
                    await run["cond"].wait()
                evs = run["events"][i:]
                i = len(run["events"])
                done = run["done"]
            for ev in evs:
                yield {"event": "log", "data": json.dumps(ev, default=str)}
            if done:
                yield {"event": "result", "data": json.dumps(run["result"], default=str)}
                return

    return EventSourceResponse(gen())


@app.get("/api/investigations")
async def list_inv():
    return store.list_investigations()


@app.get("/api/investigations/{iid}")
async def get_inv(iid: str):
    inv = store.get_investigation(iid)
    if not inv:
        raise HTTPException(404)
    return inv


class AnalystEdit(BaseModel):
    result: str | None  # Pass | Partial | Flag | N/A | null (clear)
    note: str = ""


@app.post("/api/investigations/{iid}/checks/{cid}")
async def analyst_edit(iid: str, cid: str, edit: AnalystEdit):
    inv = store.get_investigation(iid)
    if not inv:
        raise HTTPException(404)
    if cid not in load_workbook().by_id():
        raise HTTPException(400, "unknown check")
    if edit.result not in (None, "Pass", "Partial", "Flag", "N/A"):
        raise HTTPException(400, "bad result")
    prev = inv["outcomes"].get(cid, {})
    inv["outcomes"][cid] = {**prev, "id": cid, "result": edit.result, "evidence": edit.note or prev.get("evidence", ""),
                            "source": "Analyst", "analyst": True, "automated": prev.get("automated", False) and False,
                            "reliability": 0.95, "ts": dt.datetime.now().isoformat(timespec="seconds")}
    if edit.result is None and not edit.note:
        inv["outcomes"].pop(cid, None)
    inv = agent.rescore(inv)
    store.save_investigation(inv)
    return inv


@app.get("/api/investigations/{iid}/graph")
async def graph(iid: str):
    inv = store.get_investigation(iid)
    if not inv:
        raise HTTPException(404)
    key = inv["entity_key"]
    if inv.get("synthetic"):
        # make sure the synthetic applicant is in the graph for display
        from .agent import identifiers
        from .models import Intake as I
        d = inv["input"]["domain"]
        store.upsert_entity(key, inv["input"]["company_name"], identifiers(I(**inv["input"]), SYNTHETIC[d]["company"], inv["gst"]), synthetic=True)
    return store.network(key)


@app.get("/api/investigations/{iid}/dossier.pdf")
async def dossier(iid: str):
    inv = store.get_investigation(iid)
    if not inv:
        raise HTTPException(404)
    pdf = build_pdf(inv, load_workbook())
    name = "".join(ch for ch in inv["input"]["company_name"] if ch.isalnum() or ch in " -_").strip().replace(" ", "_")
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="ShellX_{name}_{iid}.pdf"'})


@app.get("/badge/{iid}", response_class=HTMLResponse)
async def badge(iid: str):
    inv = store.get_investigation(iid)
    if not inv:
        raise HTTPException(404)
    e = html.escape
    name = e(inv["profile"].get("name") or inv["input"]["company_name"])
    date = e(inv["created"][:10])
    ok = inv["verdict"] == "CLEAR"
    syn = '<p class="syn">SYNTHETIC DEMO ENTITY</p>' if inv.get("synthetic") else ""
    body = (f'<div class="b ok"><div class="tick">✓</div><h1>{name}</h1><p class="v">Operating-entity indicators verified</p>'
            f'<p>Last verified {date} · confidence {inv["score"]["confidence"]:.0%}</p>{syn}'
            '<p class="n">Automated KYB footprint check by ShellX Pro. Not a legal certification, credit rating or endorsement.</p></div>') if ok else (
            f'<div class="b"><h1>{name}</h1><p class="v">No badge issued</p><p>Badges are shown only for CLEAR verdicts.</p></div>')
    return f"""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>ShellX Trust Badge</title><style>
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b1020;font-family:Inter,system-ui,sans-serif;color:#e7ecf5}}
.b{{max-width:420px;margin:16px;padding:32px;border-radius:20px;background:#121933;border:1px solid #26305a;text-align:center}}
.ok{{border-color:#1f9d6b;box-shadow:0 0 60px #1f9d6b33}} .tick{{width:64px;height:64px;margin:0 auto 12px;border-radius:50%;background:#1f9d6b;display:grid;place-items:center;font-size:34px}}
h1{{font-size:22px;margin:8px 0}} .v{{color:#5fe0a8;font-weight:600}} .n{{font-size:12px;color:#8b95b5;margin-top:18px}} .syn{{color:#f5b84a;font-weight:700;font-size:12px}}
</style></head><body>{body}</body></html>"""


app.mount("/", StaticFiles(directory=config.WEB, html=True), name="web")
