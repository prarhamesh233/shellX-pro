"""SQLite persistence: investigations + an entity/identifier graph used for
network checks (shared directors, shared identifiers, watchlist links)."""
from __future__ import annotations

import json
import sqlite3
import threading
from difflib import SequenceMatcher

from .config import DATA

DB = DATA / "shellx.db"
_lock = threading.Lock()


def conn():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _lock, conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS investigations(id TEXT PRIMARY KEY, created TEXT, company TEXT, verdict TEXT, data TEXT);
        CREATE TABLE IF NOT EXISTS entities(key TEXT PRIMARY KEY, name TEXT, synthetic INTEGER, watchlist INTEGER,
                                            status TEXT, description TEXT);
        CREATE TABLE IF NOT EXISTS identifiers(entity TEXT, kind TEXT, value TEXT, UNIQUE(entity, kind, value));
        """)


def save_investigation(inv: dict):
    with _lock, conn() as c:
        c.execute("REPLACE INTO investigations VALUES(?,?,?,?,?)",
                  (inv["id"], inv["created"], inv["input"]["company_name"], inv.get("verdict"), json.dumps(inv, default=str)))


def get_investigation(iid: str) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT data FROM investigations WHERE id=?", (iid,)).fetchone()
    return json.loads(r["data"]) if r else None


def list_investigations(limit=50):
    with conn() as c:
        rows = c.execute("SELECT id, created, company, verdict, data FROM investigations ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = json.loads(r["data"])
        out.append({"id": r["id"], "created": r["created"], "company": r["company"], "verdict": r["verdict"],
                    "risk_score": d.get("score", {}).get("risk_score"), "confidence": d.get("score", {}).get("confidence"),
                    "synthetic": d.get("synthetic", False)})
    return out


def norm_val(kind, v):
    v = str(v).strip().lower()
    if kind in ("director", "address"):
        v = " ".join(v.replace(",", " ").split())
    return v


def upsert_entity(key, name, identifiers: list[tuple[str, str]], *, synthetic=False, watchlist=False, status="", description=""):
    with _lock, conn() as c:
        c.execute("INSERT INTO entities VALUES(?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET name=excluded.name, "
                  "description=excluded.description, status=CASE WHEN excluded.status!='' THEN excluded.status ELSE status END",
                  (key, name, int(synthetic), int(watchlist), status, description))
        for kind, v in identifiers:
            if v:
                c.execute("INSERT OR IGNORE INTO identifiers VALUES(?,?,?)", (key, kind, norm_val(kind, v)))


def graph_signals(key: str, identifiers: list[tuple[str, str]], description: str | None) -> dict:
    """Compare a candidate's identifiers with everything else in the DB."""
    shared, watch, director_links = [], [], {}
    with conn() as c:
        for kind, v in identifiers:
            if not v:
                continue
            nv = norm_val(kind, v)
            rows = c.execute("SELECT i.entity, e.name, e.watchlist FROM identifiers i JOIN entities e ON e.key=i.entity "
                             "WHERE i.kind=? AND i.value=? AND i.entity!=?", (kind, nv, key)).fetchall()
            if kind == "director":
                director_links[v] = len(rows) + 1
            for r in rows:
                if kind != "director":
                    shared.append({"kind": kind, "value": v, "other": r["name"]})
                if r["watchlist"]:
                    watch.append((r["name"], kind))
        dup = None
        if description and len(description) > 40:
            for r in c.execute("SELECT name, description FROM entities WHERE key!=? AND description!=''", (key,)):
                s = SequenceMatcher(None, description.lower(), r["description"].lower()).ratio()
                if s > 0.9 and (not dup or s > dup["score"]):
                    dup = {"other": r["name"], "score": s}
    return {"shared": shared, "watchlist": sorted(set(watch)), "director_links": director_links, "dup_desc": dup}


def network(key: str, depth: int = 2) -> dict:
    """vis-network nodes/edges around an entity (entity—identifier bipartite graph)."""
    nodes, edges, seen_e, seen_i = {}, [], set(), set()
    frontier = {key}
    with conn() as c:
        for _ in range(depth):
            nxt = set()
            for ek in frontier:
                if ek in seen_e:
                    continue
                seen_e.add(ek)
                e = c.execute("SELECT * FROM entities WHERE key=?", (ek,)).fetchone()
                if not e:
                    continue
                nodes[ek] = {"id": ek, "label": e["name"], "group": "watch" if e["watchlist"] else ("focus" if ek == key else "company"),
                             "synthetic": bool(e["synthetic"]), "status": e["status"]}
                for i in c.execute("SELECT kind, value FROM identifiers WHERE entity=? AND kind IN ('director','address','phone','email','pan','domain')", (ek,)):
                    iid = f"{i['kind']}:{i['value']}"
                    edges.append({"from": ek, "to": iid})
                    if iid not in seen_i:
                        seen_i.add(iid)
                        nodes[iid] = {"id": iid, "label": i["value"][:40], "group": i["kind"]}
                        for o in c.execute("SELECT entity FROM identifiers WHERE kind=? AND value=? AND entity!=?", (i["kind"], i["value"], ek)):
                            nxt.add(o["entity"])
            frontier = nxt - seen_e
        # include entities discovered at the edge
        for ek in frontier:
            e = c.execute("SELECT * FROM entities WHERE key=?", (ek,)).fetchone()
            if e and ek not in nodes:
                nodes[ek] = {"id": ek, "label": e["name"], "group": "watch" if e["watchlist"] else "company", "synthetic": bool(e["synthetic"])}
                for i in c.execute("SELECT kind, value FROM identifiers WHERE entity=?", (ek,)):
                    iid = f"{i['kind']}:{i['value']}"
                    if iid in nodes:
                        edges.append({"from": ek, "to": iid})
    # drop identifier nodes with a single edge to reduce clutter, except for the focus entity
    deg = {}
    for e in edges:
        deg[e["to"]] = deg.get(e["to"], 0) + 1
    focus_ids = {e["to"] for e in edges if e["from"] == key}
    keep = {n for n in nodes if n not in seen_i or deg.get(n, 0) > 1 or n in focus_ids}
    return {"nodes": [nodes[n] for n in keep], "edges": [e for e in edges if e["from"] in keep and e["to"] in keep]}
