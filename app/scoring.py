"""Deterministic scoring — the workbook formula, plus a confidence figure.

risk_score   = Σ(weight × multiplier) / Σ(weight of assessed checks) × 100     (workbook)
coverage     = Σ(weight assessed) / Σ(weight applicable, i.e. non-N/A)          (workbook)
confidence   = automated coverage × weighted mean source reliability             (ShellX)
               — 'how much of what we could check did we actually see, and how much do we trust it'

Verdict (plan vocabulary):
  any hard-stop Flag                         → HIGH_RISK (escalate to senior reviewer)
  < 2 independent sources, or low coverage   → INSUFFICIENT_DATA
  score ≥ T2 → HIGH_RISK ; score ≥ T1 → REVIEW ; else CLEAR
"""
from __future__ import annotations

from collections import defaultdict

from . import config
from .evaluators import EVALUATORS
from .models import CheckOutcome
from .workbook import Workbook


def score(wb: Workbook, outcomes: dict[str, CheckOutcome], sources_with_data: set[str]) -> dict:
    mult = wb.multipliers
    defs = wb.by_id()
    auto_ids = set(EVALUATORS)

    def agg(ids):
        assessed_w = risk = applicable_w = 0.0
        rel_w = 0.0
        flags = hard = crit = n_assessed = n_na = 0
        for cid in ids:
            d = defs.get(cid)
            if not d:
                continue
            o = outcomes.get(cid)
            r = o.result if o else None
            if r == "N/A":
                n_na += 1
                continue
            applicable_w += d.weight
            if r is None:
                continue
            n_assessed += 1
            assessed_w += d.weight
            risk += d.weight * mult.get(r, 0)
            rel_w += d.weight * (o.reliability if not o.analyst else 0.95)
            if r == "Flag":
                flags += 1
                hard += d.hard_stop
                crit += d.weight >= 5
        return dict(score=round(100 * risk / assessed_w, 1) if assessed_w else 0.0,
                    coverage=round(assessed_w / applicable_w, 3) if applicable_w else 0.0,
                    reliability=round(rel_w / assessed_w, 3) if assessed_w else 0.0,
                    flags=flags, hard_stops=hard, critical=crit, assessed=n_assessed, na=n_na,
                    risk_points=risk, weight_assessed=assessed_w)

    all_ids = [c.id for c in wb.checks]
    auto = agg([i for i in all_ids if i in auto_ids or (outcomes.get(i) and outcomes[i].analyst)])
    full = agg(all_ids)

    # Category breakdown (full scope, matches the Summary sheet).
    cats = []
    by_cat = defaultdict(list)
    for c in wb.checks:
        by_cat[c.category].append(c.id)
    for cat in wb.categories:
        a = agg(by_cat[cat])
        cats.append({"category": cat, "checks": len(by_cat[cat]), "assessed": a["assessed"], "flags": a["flags"],
                     "risk_points": a["risk_points"], "weight_assessed": a["weight_assessed"],
                     "category_risk": round(a["risk_points"] / a["weight_assessed"], 3) if a["weight_assessed"] else 0})

    confidence = round(min(1.0, auto["coverage"]) * auto["reliability"], 3)
    T1, T2, T3 = wb.tiers["T1"], wb.tiers["T2"], wb.tiers["T3"]
    s = auto["score"]
    hard = full["hard_stops"]
    n_src = len(sources_with_data)
    reasons = []
    if hard:
        verdict = "HIGH_RISK"; reasons.append(f"{hard} deal-breaker check{'s' if hard > 1 else ''} failed — this case must go to a senior reviewer")
    elif n_src < 2:
        verdict = "INSUFFICIENT_DATA"; reasons.append(f"Only {n_src} independent data source{'s' if n_src != 1 else ''} had information on this company (we need at least 2 to decide)")
    elif auto["coverage"] < config.AUTO_COVERAGE_MIN:
        verdict = "INSUFFICIENT_DATA"; reasons.append(f"We could only verify {auto['coverage']:.0%} of the automatic checks (we need {config.AUTO_COVERAGE_MIN:.0%} to decide)")
    elif s >= T2:
        verdict = "HIGH_RISK"
    elif s >= T1:
        verdict = "REVIEW"
    else:
        verdict = "CLEAR"

    # Workbook tier on the full 86-check scope (what the Summary sheet would show).
    if hard:
        tier = "ESCALATE"
    elif full["coverage"] < T3:
        tier = "INCOMPLETE"
    else:
        tier = "HIGH" if full["score"] >= T2 else "MEDIUM" if full["score"] >= T1 else "LOW"

    # 'Less is more': top drivers and top mitigators only.
    def pts(cid):
        o = outcomes[cid]
        return defs[cid].weight * mult.get(o.result, 0)
    scored = [cid for cid, o in outcomes.items() if o.result in ("Flag", "Partial") and cid in defs]
    drivers = sorted(scored, key=lambda c: (-pts(c), -defs[c].hard_stop))[:5]
    mitig = sorted([cid for cid, o in outcomes.items() if o.result == "Pass" and cid in defs],
                   key=lambda c: -defs[c].weight * outcomes[c].reliability)[:4]
    gaps = sorted([cid for cid in auto_ids if cid in defs and outcomes.get(cid) and outcomes[cid].result is None],
                  key=lambda c: -defs[c].weight)[:5]

    return {
        "verdict": verdict, "verdict_reasons": reasons,
        "risk_score": s, "confidence": confidence,
        "automated": auto, "full": full, "workbook_tier": tier,
        "independent_sources": sorted(sources_with_data),
        "categories": cats, "drivers": drivers, "mitigators": mitig, "gaps": gaps,
        "thresholds": {"T1": T1, "T2": T2, "T3": T3, "auto_coverage_min": config.AUTO_COVERAGE_MIN},
    }
