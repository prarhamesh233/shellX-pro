"""Sanctions screening against the free OFAC SDN list (+ alternate names).
Downloaded once, cached in data/. Fuzzy matching with legal-suffix stripping."""
from __future__ import annotations

import csv
import io
import re
import time
from difflib import SequenceMatcher
from functools import lru_cache

import httpx

from .. import config

SDN_URL = "https://www.treasury.gov/ofac/downloads/sdn.csv"
ALT_URL = "https://www.treasury.gov/ofac/downloads/alt.csv"
SUFFIX = re.compile(r"\b(private|pvt|limited|ltd|llp|llc|inc|incorporated|corp|corporation|co|company|plc|gmbh|sa|ag|"
                    r"fze|fzco|fzc|bv|nv|srl|spa|pte|pty|holdings?|group|international|intl|the|and|&)\b\.?")


def norm(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = SUFFIX.sub(" ", s)
    return " ".join(sorted(s.split()))


def _download(url: str, path):
    # The list is downloaded out-of-band (scripts/fetch_lists or at startup in a thread);
    # here we only read what is on disk so an investigation never blocks on a slow server.
    if path.exists():
        return path.read_text(encoding="latin-1")
    raise FileNotFoundError(str(path))


def refresh_lists():
    """Download OFAC lists (slow, ~minutes). Call from a background thread."""
    for url, name in ((SDN_URL, "ofac_sdn.csv"), (ALT_URL, "ofac_alt.csv")):
        path = config.DATA / name
        if path.exists() and time.time() - path.stat().st_mtime < 86400 * 7:
            continue
        try:
            r = httpx.get(url, timeout=300, follow_redirects=True, headers={"User-Agent": config.USER_AGENT})
            r.raise_for_status()
            tmp = path.with_suffix(".part")
            tmp.write_bytes(r.content)
            tmp.replace(path)
        except Exception:  # noqa: BLE001
            pass
    load_list.cache_clear()


@lru_cache(maxsize=1)
def load_list() -> tuple[list[tuple[str, str, str, str]], str]:
    """Returns ([(normalized, original, type, program)], status)."""
    out = []
    try:
        sdn = _download(SDN_URL, config.DATA / "ofac_sdn.csv")
        by_id = {}
        for row in csv.reader(io.StringIO(sdn)):
            if len(row) < 4:
                continue
            ent, name, typ, prog = row[0], row[1], row[2], row[3]
            typ = "individual" if typ.strip().lower() == "individual" else "entity"
            by_id[ent] = (name, typ, prog)
            out.append((norm(name), name, typ, prog))
        try:
            alt = _download(ALT_URL, config.DATA / "ofac_alt.csv")
            for row in csv.reader(io.StringIO(alt)):
                if len(row) >= 4 and row[0] in by_id:
                    n, typ, prog = by_id[row[0]]
                    out.append((norm(row[3]), f"{row[3]} (alias of {n})", typ, prog))
        except Exception:  # noqa: BLE001
            pass
        return out, f"OFAC SDN ({len(out)} names)"
    except Exception as e:  # noqa: BLE001
        return [], f"unavailable: {type(e).__name__}"


def screen(name: str, kind: str = "entity", threshold: float = 0.86) -> dict:
    """Return best matches above threshold. kind: 'entity' | 'individual'."""
    lst, status = load_list()
    if not lst and (config.DATA / "ofac_sdn.csv").exists():
        load_list.cache_clear()
        lst, status = load_list()
    if not lst:
        return {"status": status, "available": False, "matches": []}
    q = norm(name)
    if not q:
        return {"status": status, "available": True, "matches": []}
    qtok = set(q.split())
    hits = []
    for n, orig, typ, prog in lst:
        if typ != kind or not n:
            continue
        # cheap prefilter: share at least one token
        if not qtok & set(n.split()):
            continue
        sc = SequenceMatcher(None, q, n).ratio()
        ntok = set(n.split())
        if len(qtok) >= 2 and qtok <= ntok:  # e.g. "viktor bout" within "bout viktor anatolijevitch"
            sc = max(sc, 0.9)
        if sc >= threshold:
            hits.append({"name": orig, "score": round(sc, 3), "program": prog})
    hits.sort(key=lambda h: -h["score"])
    return {"status": status, "available": True, "matches": hits[:5]}
