"""Crustdata client: one file, disk cache keyed by (endpoint, normalized body),
credit ledger from the X-Credits-Used header, hard per-investigation cap."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any

import httpx

from . import config


class CreditCapExceeded(Exception):
    pass


class Ledger:
    """Per-investigation credit + call accounting."""

    def __init__(self, cap: float = config.CREDIT_CAP):
        self.cap = cap
        self.spent = 0.0
        self.calls: list[dict] = []

    def can_spend(self, estimate: float) -> bool:
        return self.spent + estimate <= self.cap

    def record(self, endpoint: str, credits: float, cached: bool, ms: int):
        self.spent += credits
        self.calls.append({"endpoint": endpoint, "credits": credits, "cached": cached, "ms": ms})


# Rough upfront estimates so we can refuse before spending.
ESTIMATES = {
    "/company/identify": 0, "/company/enrich": 4, "/company/search": 0.5,
    "/person/search": 0.5, "/job/search": 0.5, "/web/search/live": 1, "/web/enrich/live": 1,
}


def _norm(obj: Any) -> Any:
    if isinstance(obj, str):
        return obj.strip().lower()
    if isinstance(obj, list):
        return [_norm(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _norm(v) for k, v in sorted(obj.items())}
    return obj


def _cache_path(endpoint: str, body: dict):
    key = hashlib.sha1(json.dumps([endpoint, _norm(body)], sort_keys=True).encode()).hexdigest()[:20]
    return config.CACHE / f"{endpoint.strip('/').replace('/', '_')}__{key}.json"


class Crustdata:
    def __init__(self):
        self.enabled = bool(config.CRUSTDATA_API_KEY)
        self._sem = asyncio.Semaphore(4)

    async def post(self, endpoint: str, body: dict, ledger: Ledger, use_cache: bool = True) -> Any:
        path = _cache_path(endpoint, body)
        t0 = time.time()
        if use_cache and path.exists():
            data = json.loads(path.read_text())
            ledger.record(endpoint, 0, True, int((time.time() - t0) * 1000))
            return data["response"]
        if config.REPLAY_MODE or not self.enabled:
            raise RuntimeError(f"Crustdata unavailable (replay mode or no key) and no cache for {endpoint}")
        est = ESTIMATES.get(endpoint, 1)
        if not ledger.can_spend(est):
            raise CreditCapExceeded(f"Credit cap {ledger.cap} reached; skipped {endpoint}")
        headers = {
            "Authorization": f"Bearer {config.CRUSTDATA_API_KEY}",
            "x-api-version": config.CRUSTDATA_VERSION,
            "Content-Type": "application/json",
        }
        async with self._sem:
            async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT) as c:
                for attempt in range(3):
                    r = await c.post(config.CRUSTDATA_BASE + endpoint, json=body, headers=headers)
                    if r.status_code == 429:
                        await asyncio.sleep(2 * (attempt + 1))
                        continue
                    break
        credits = float(r.headers.get("x-credits-used", 0) or 0)
        ms = int((time.time() - t0) * 1000)
        ledger.record(endpoint, credits, False, ms)
        if r.status_code == 404:
            resp: Any = []
        elif r.status_code >= 400:
            raise RuntimeError(f"Crustdata {endpoint} HTTP {r.status_code}: {r.text[:300]}")
        else:
            resp = r.json()
        path.write_text(json.dumps({"endpoint": endpoint, "body": body, "fetched_at": time.time(),
                                    "credits": credits, "response": resp}))
        return resp

    # ---- typed helpers -------------------------------------------------
    async def identify(self, ledger: Ledger, *, domain: str | None = None, name: str | None = None) -> list[dict]:
        body = {"domains": [domain]} if domain else {"names": [name]}
        resp = await self.post("/company/identify", body, ledger)
        if not resp:
            return []
        return resp[0].get("matches", []) if isinstance(resp, list) else []

    ENRICH_FIELDS = ["basic_info", "revenue", "headcount", "funding", "hiring", "locations", "taxonomy",
                     "people", "followers", "web_traffic", "news", "social_profiles", "employee_reviews",
                     "reviews", "software_reviews"]

    # Technographics is a gated add-on (+2 credits). 'auto' tries it and falls back on 403 (free).
    tech_enabled: bool | None = None if config.TECHNOGRAPHICS != "off" else False

    async def enrich(self, ledger: Ledger, company_id: int) -> dict | None:
        fields = list(self.ENRICH_FIELDS)
        if self.tech_enabled is not False:
            fields.append("technographics")
        body = {"crustdata_company_ids": [company_id], "fields": fields}
        try:
            resp = await self.post("/company/enrich", body, ledger)
            if "technographics" in fields:
                Crustdata.tech_enabled = True
        except RuntimeError as e:
            if "technographics" in fields and "403" in str(e) and "technographics" in str(e):
                Crustdata.tech_enabled = False  # locked on this account; remember for this process
                body["fields"] = list(self.ENRICH_FIELDS)
                resp = await self.post("/company/enrich", body, ledger)
            else:
                raise
        try:
            return resp[0]["matches"][0]["company_data"]
        except (IndexError, KeyError, TypeError):
            return None

    async def job_search(self, ledger: Ledger, company_id: int, limit: int = 15) -> Any:
        body = {"filters": {"field": "company.basic_info.company_id", "type": "=", "value": company_id},
                "fields": ["job_details", "content.description", "location.raw", "location.country",
                           "metadata.date_added", "metadata.date_updated"],
                "sorts": [{"field": "metadata.date_added", "order": "desc"}],
                "limit": limit}
        return await self.post("/job/search", body, ledger)

    async def person_search(self, ledger: Ledger, name: str, company_name: str | None = None, limit: int = 5) -> Any:
        conds = [{"field": "basic_profile.name", "type": "(.)", "value": name}]
        body = {"filters": {"op": "and", "conditions": conds} if len(conds) > 1 else conds[0], "limit": limit}
        return await self.post("/person/search", body, ledger)

    async def web_search(self, ledger: Ledger, query: str) -> Any:
        return await self.post("/web/search/live", {"query": query, "sources": ["news"]}, ledger)


crust = Crustdata()
