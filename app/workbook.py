"""Load checks, weights, hard stops and thresholds from the KYB workbook.

The workbook is the source of truth: tune a weight or threshold there and the
app picks it up on restart. The file name may vary; we look for any .xlsx in the
project root or data/ that has a 'Checks' sheet.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

import openpyxl

from .config import DATA, ROOT


@dataclass
class CheckDef:
    id: str
    category: str
    name: str
    rule: str
    weight: float
    hard_stop: bool
    source: str = ""
    crustdata_signal: str = ""
    method: str = ""
    stage: str = ""
    notes: str = ""


@dataclass
class Workbook:
    path: str
    checks: list[CheckDef]
    params: dict[str, float] = field(default_factory=dict)  # P1..P11
    tiers: dict[str, float] = field(default_factory=dict)   # T1..T3
    multipliers: dict[str, float] = field(default_factory=dict)  # Pass/Partial/Flag
    categories: list[str] = field(default_factory=list)

    def by_id(self) -> dict[str, CheckDef]:
        return {c.id: c for c in self.checks}

    def to_json(self) -> dict:
        d = asdict(self)
        d["path"] = Path(self.path).name
        return d


def _find_workbook() -> Path:
    candidates = sorted(ROOT.glob("*.xlsx")) + sorted(DATA.glob("*.xlsx"))
    # Prefer files whose name mentions KYB.
    candidates.sort(key=lambda p: (0 if "kyb" in p.name.lower() else 1, p.name))
    for p in candidates:
        if p.name.startswith("~$"):
            continue
        try:
            wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
            if any(s.lower() == "checks" for s in wb.sheetnames):
                return p
        except Exception:
            continue
    raise FileNotFoundError("No KYB workbook with a 'Checks' sheet found in project root or data/")


def _norm(s) -> str:
    return str(s or "").strip().lower()


def _sheet(wb, name):
    for s in wb.sheetnames:
        if s.lower() == name.lower():
            return wb[s]
    return None


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


@lru_cache(maxsize=1)
def load_workbook() -> Workbook:
    path = _find_workbook()
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = _sheet(wb, "Checks")
    rows = list(ws.iter_rows(values_only=True))
    # Locate header row by finding a row containing 'ID' and 'Weight'.
    hdr_idx = next(i for i, r in enumerate(rows) if r and "id" in [_norm(c) for c in r] and any("weight" in _norm(c) for c in r))
    hdr = [_norm(c) for c in rows[hdr_idx]]

    def col(*keys):
        for k in keys:
            for i, h in enumerate(hdr):
                if h.startswith(k):
                    return i
        return None

    c_id, c_cat, c_chk = col("id"), col("category"), col("check")
    c_rule, c_w, c_hs = col("red-flag", "red flag"), col("weight assessed") and col("weight"), col("hard stop")
    c_w = next(i for i, h in enumerate(hdr) if h == "weight")
    c_src, c_cd, c_m, c_st, c_n = col("primary source"), col("crustdata"), col("method"), col("stage"), col("notes")

    checks: list[CheckDef] = []
    for r in rows[hdr_idx + 1:]:
        if not r or not r[c_id] or "-" not in str(r[c_id]):
            continue
        g = lambda i: (str(r[i]).strip() if i is not None and r[i] is not None else "")
        checks.append(CheckDef(
            id=g(c_id), category=g(c_cat), name=g(c_chk), rule=g(c_rule),
            weight=_num(r[c_w], 1), hard_stop=g(c_hs).upper().startswith("Y"),
            source=g(c_src), crustdata_signal=g(c_cd), method=g(c_m), stage=g(c_st), notes=g(c_n),
        ))

    params, tiers, mult = {}, {}, {"Pass": 0.0, "Partial": 0.5, "Flag": 1.0}
    th = _sheet(wb, "Thresholds")
    if th is not None:
        for r in th.iter_rows(values_only=True):
            if not r or r[0] is None:
                continue
            k = str(r[0]).strip()
            if k[:1] == "P" and k[1:].isdigit():
                params[k] = _num(r[2])
            elif k[:1] == "T" and k[1:].isdigit():
                tiers[k] = _num(r[2])
            elif k in ("Pass", "Partial", "Flag"):
                mult[k] = _num(r[2], mult[k])
    defaults_p = {"P1": 3, "P2": 5e6, "P3": 12, "P4": 500, "P5": 10, "P6": 25, "P7": 4, "P8": 0.4, "P9": 3, "P10": 2, "P11": 0.25}
    for k, v in defaults_p.items():
        params.setdefault(k, v)
    tiers.setdefault("T1", 20); tiers.setdefault("T2", 40); tiers.setdefault("T3", 0.8)

    cats: list[str] = []
    for c in checks:
        if c.category not in cats:
            cats.append(c.category)

    w = Workbook(path=str(path), checks=checks, params=params, tiers=tiers, multipliers=mult, categories=cats)
    # Keep a JSON snapshot for debugging / offline use.
    (DATA / "checks_snapshot.json").write_text(json.dumps(w.to_json(), indent=1))
    return w


# ---- Plain-language labels for non-expert readers (UI + PDF). Codes stay internal. ----
CATEGORY_LABELS = {
    "Identity & Registration": "Company identity & registration",
    "Ownership & Control": "Who owns and controls it",
    "Address, Contact & Web Presence": "Address, contact & website",
    "Operating Footprint (Crustdata)": "Signs of a real, operating business",
    "People & Key Persons": "Key people behind it",
    "Network & Graph Analytics": "Links to other companies",
    "Business Profile": "What the business does",
    "Screening & Adverse Media": "Sanctions & negative news",
    "Documents & Onboarding Conduct": "Documents & behaviour during onboarding",
    "Expected Activity & Transactions": "Money flows",
    "Ongoing Monitoring": "Ongoing monitoring",
}
RESULT_LABELS = {"Flag": "Red flag", "Partial": "Concern", "Pass": "OK", "N/A": "Not applicable", None: "Couldn't verify"}
WEIGHT_LABELS = {1: "Low", 2: "Moderate", 3: "Significant", 4: "High", 5: "Critical"}
VERDICT_LABELS = {"CLEAR": "Looks legitimate", "REVIEW": "Needs a human review", "HIGH_RISK": "High risk",
                  "INSUFFICIENT_DATA": "Not enough data to decide"}
TIER_LABELS = {"ESCALATE": "Escalate to senior reviewer", "INCOMPLETE": "Incomplete — manual checks pending",
               "HIGH": "High", "MEDIUM": "Medium", "LOW": "Low"}
SOURCE_LABELS = {"OFAC SDN list": "US sanctions list (OFAC)", "RDAP/WHOIS": "Domain registry (WHOIS)",
                 "Internal graph DB": "Our records of other companies", "Text heuristic": "Description analysis",
                 "FATF / policy lists": "High-risk country & sector lists", "GSTIN checksum": "GSTIN format check",
                 "Website fetch": "Company website", "News (Google News + Crustdata)": "News search",
                 "Applicability rule": "Not relevant for this company", "Analyst": "Analyst"}

import re as _re
_CODE_RE = _re.compile(r"\s*\(?\b(?:REG|OWN|ADR|OPS|PPL|GRF|BUS|SCR|DOC|TXN|MON)-\d{2}\b(?:\s*(?:,|and|&|/)\s*\b(?:REG|OWN|ADR|OPS|PPL|GRF|BUS|SCR|DOC|TXN|MON)-\d{2}\b)*\)?")


def strip_codes(text: str | None) -> str:
    """Remove internal check codes like 'OPS-02' / '(GRF-03, GRF-04)' from human-facing text."""
    if not text:
        return text or ""
    t = _CODE_RE.sub("", text)
    return _re.sub(r"\s+([,.;:])", r"\1", _re.sub(r"\(\s*\)", "", t)).strip()


def labels_json() -> dict:
    return {"categories": CATEGORY_LABELS, "results": {str(k): v for k, v in RESULT_LABELS.items()},
            "weights": WEIGHT_LABELS, "verdicts": VERDICT_LABELS, "tiers": TIER_LABELS, "sources": SOURCE_LABELS}

# Plain-question titles for the automated checks (business-owner friendly). Manual checks keep the workbook name.
PLAIN_NAMES = {
    "REG-02": "Do the company details match what was given?", "REG-03": "Is it a brand-new company claiming big business?",
    "REG-05": "Is it registered in a secrecy or high-risk country?", "REG-07": "Is the GST number valid?",
    "ADR-03": "Is the GST registered in the same state as the head office?", "ADR-04": "Does it use a proper business email?",
    "ADR-05": "How old is its website address?", "OPS-01": "Can we find the company in business databases?",
    "OPS-02": "Does it have the staff it claims?", "OPS-03": "Has it had staff for a while?",
    "OPS-04": "Has it lost a lot of staff recently?", "OPS-05": "Does it have a normal mix of departments?",
    "OPS-06": "Are its staff where it says it operates?", "OPS-07": "Does it really hire people?",
    "OPS-08": "Do people visit its website?", "OPS-09": "Does its website traffic look natural?",
    "OPS-10": "Is there a real website or product behind it?", "OPS-11": "Is its claimed turnover realistic?",
    "OPS-12": "Is its claimed funding on record?", "OPS-13": "Do employees or customers review it?",
    "OPS-14": "Does it have a social media or press presence?", "OPS-15": "Is its online history as old as it claims?",
    "PPL-02": "Does the director have a real work history?", "PPL-04": "Does the director actually work there?",
    "PPL-05": "Is it a one-person company?", "GRF-01": "Is the director behind many other companies?",
    "GRF-03": "Does it share an address or phone with other companies?", "GRF-04": "Is it a copy of another company?",
    "GRF-06": "Is it linked to a company we rejected before?", "BUS-01": "Is its business description specific?",
    "BUS-03": "Does its industry match what it says it does?", "BUS-04": "Is it in a high-risk industry?",
    "SCR-01": "Is the company on a sanctions list?", "SCR-02": "Are its directors on a sanctions list?",
    "SCR-04": "Is there negative news about it?", "SCR-05": "Is it linked to high-risk countries?",
    "TXN-01": "Is its claimed business possible with its staff?", "MON-01": "Does its website work?",
}


def plain_name(cid: str, default: str) -> str:
    return PLAIN_NAMES.get(cid, default)


_old_labels_json = labels_json


def labels_json() -> dict:  # noqa: F811
    return {**_old_labels_json(), "checks": PLAIN_NAMES}
