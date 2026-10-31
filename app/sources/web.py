"""Free web signals: website liveness/parking, RDAP domain age, Google News RSS.
All fetched text is treated as untrusted data: we extract numbers/flags only,
and never forward raw page text to the LLM."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import httpx

from .. import config

PARKED_MARKERS = [
    "domain is for sale", "buy this domain", "this domain may be for sale", "parked free", "sedoparking",
    "godaddy.com/domainsearch", "hugedomains", "dan.com", "afternic", "domain parking", "coming soon",
    "under construction", "website is under construction", "index of /",
]
TEMPLATE_MARKERS = ["lorem ipsum", "your company name", "sample text", "theme by", "just another wordpress site"]


def _cache_get(kind: str, key: str, ttl: float = 86400 * 3):
    p = config.CACHE / f"{kind}__{hashlib.sha1(key.encode()).hexdigest()[:16]}.json"
    if p.exists():
        d = json.loads(p.read_text())
        if config.REPLAY_MODE or time.time() - d["t"] < ttl:
            return d["v"], p
    return None, p


def _cache_put(p, v):
    p.write_text(json.dumps({"t": time.time(), "v": v}))


async def fetch_site(domain: str) -> dict:
    """Return liveness and coarse structural signals for a domain's homepage."""
    v, p = _cache_get("site", domain)
    if v is not None:
        return v
    out = {"domain": domain, "reachable": False, "status": None, "https": False, "final_url": None,
           "parked": False, "template": False, "title": None, "links": 0, "bytes": 0,
           "emails": [], "error": None, "has_contact_page": False, "has_privacy": False}
    if config.REPLAY_MODE:
        out["error"] = "replay mode"
        return out
    headers = {"User-Agent": "Mozilla/5.0 " + config.USER_AGENT}
    for scheme in ("https://", "http://"):
        try:
            async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers=headers, verify=scheme == "https://") as c:
                r = await c.get(scheme + domain)
            html = r.text[:400_000]
            low = html.lower()
            out.update(reachable=r.status_code < 400, status=r.status_code, https=str(r.url).startswith("https"),
                       final_url=str(r.url), bytes=len(r.content))
            m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
            out["title"] = re.sub(r"\s+", " ", m.group(1)).strip()[:120] if m else None
            out["links"] = len(re.findall(r"<a\s", low))
            out["parked"] = any(k in low for k in PARKED_MARKERS) and out["links"] < 25
            out["template"] = any(k in low for k in TEMPLATE_MARKERS)
            out["emails"] = sorted(set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", html)))[:10]
            out["has_contact_page"] = "contact" in low
            out["has_privacy"] = "privacy" in low
            out["error"] = None
            break
        except Exception as e:  # noqa: BLE001
            out["error"] = f"{type(e).__name__}: {str(e)[:120]}"
    _cache_put(p, out)
    return out


async def rdap_domain(domain: str) -> dict:
    """Free WHOIS replacement. Returns registration/expiry dates and privacy masking."""
    v, p = _cache_get("rdap", domain, ttl=86400 * 14)
    if v is not None:
        return v
    out = {"domain": domain, "found": False, "created": None, "expires": None, "updated": None,
           "registrar": None, "privacy": None, "error": None}
    if config.REPLAY_MODE:
        out["error"] = "replay mode"
        return out
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={"User-Agent": config.USER_AGENT}) as c:
            r = await c.get(f"https://rdap.org/domain/{domain}")
        if r.status_code == 200:
            d = r.json()
            out["found"] = True
            for ev in d.get("events", []):
                a, when = ev.get("eventAction"), (ev.get("eventDate") or "")[:10]
                if a == "registration":
                    out["created"] = when
                elif a == "expiration":
                    out["expires"] = when
                elif a == "last changed":
                    out["updated"] = when
            blob = json.dumps(d.get("entities", [])).lower()
            out["privacy"] = any(k in blob for k in ("redacted", "privacy", "withheld", "proxy", "not disclosed"))
            for e in d.get("entities", []):
                if "registrar" in e.get("roles", []):
                    vc = e.get("vcardArray", [None, []])[1]
                    for item in vc:
                        if item[0] == "fn":
                            out["registrar"] = item[3]
        else:
            out["error"] = f"RDAP HTTP {r.status_code}"
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {str(e)[:120]}"
    _cache_put(p, out)
    return out


ADVERSE_TERMS = ["fraud", "scam", "money laundering", "shell company", "fake invoice", "gst evasion", "tax evasion",
                 "raid", "arrested", "ponzi", "cheating", "ed probe", "sfio", "hawala", "bogus", "sanction"]


async def google_news(company: str, extra_terms: list[str] | None = None) -> dict:
    """Adverse-media scan via Google News RSS (free, no key). Entity-matched on title."""
    terms = extra_terms or ADVERSE_TERMS[:8]
    q = f'"{company}" ({" OR ".join(terms)})'
    v, p = _cache_get("gnews", q, ttl=86400)
    if v is not None:
        return v
    out = {"query": q, "items": [], "error": None}
    if config.REPLAY_MODE:
        out["error"] = "replay mode"
        return out
    try:
        url = f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=en-IN&gl=IN&ceid=IN:en"
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={"User-Agent": config.USER_AGENT}) as c:
            r = await c.get(url)
        root = ET.fromstring(r.content)
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            out["items"].append({"title": title[:200], "url": it.findtext("link"),
                                 "date": (it.findtext("pubDate") or "")[:16],
                                 "source": (it.find("source").text if it.find("source") is not None else "")})
            if len(out["items"]) >= 20:
                break
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {str(e)[:120]}"
    _cache_put(p, out)
    return out


def years_since(date_str: str | None) -> float | None:
    if not date_str:
        return None
    try:
        d = dt.date.fromisoformat(date_str[:10])
        return (dt.date.today() - d).days / 365.25
    except ValueError:
        return None
