"""Officer-facing dossier PDF (fpdf2, DejaVu for Unicode). Plain language, no internal check codes.

Layout rule: every wrapped paragraph returns the cursor to the LEFT margin
(new_x=LMARGIN) — the previous version left it at the right edge, which cut text off."""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

from .workbook import (CATEGORY_LABELS, RESULT_LABELS, SOURCE_LABELS, TIER_LABELS, VERDICT_LABELS, WEIGHT_LABELS,
                       plain_name, strip_codes)

SHORT = {"Flag": "RED FLAG", "Partial": "CONCERN", "Pass": "OK", "N/A": "N/A", None: "NO DATA"}
COL = 26

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
VCOL = {"CLEAR": (31, 157, 107), "REVIEW": (214, 140, 20), "HIGH_RISK": (205, 55, 55), "INSUFFICIENT_DATA": (110, 120, 140)}
RCOL = {"Flag": (205, 55, 55), "Partial": (214, 140, 20), "Pass": (31, 140, 95), "N/A": (130, 130, 130), None: (130, 130, 130)}
MARGIN = 15


class PDF(FPDF):
    font_name = "helvetica"
    case_id = ""

    def footer(self):
        self.set_y(-12)
        self.set_font(self.font_name, size=7)
        self.set_text_color(130)
        self.cell(0, 5, "ShellX Pro · decision support only — indicators, not a legal finding", align="L")
        self.set_x(self.l_margin)
        self.cell(0, 5, f"Case {self.case_id} · page {self.page_no()}/{{nb}}", align="R")


def build_pdf(inv: dict, wb) -> bytes:
    pdf = PDF(format="A4")
    pdf.set_margins(MARGIN, MARGIN, MARGIN)
    pdf.set_auto_page_break(True, 18)
    if (FONT_DIR / "DejaVuSans.ttf").exists():
        pdf.add_font("dv", "", str(FONT_DIR / "DejaVuSans.ttf"))
        pdf.add_font("dv", "B", str(FONT_DIR / "DejaVuSans-Bold.ttf"))
        pdf.font_name = "dv"
    F = pdf.font_name
    pdf.case_id = inv["id"]
    pdf.alias_nb_pages()
    pdf.add_page()
    W = pdf.w - 2 * MARGIN
    sc, prof, inp, s = inv["score"], inv["profile"], inv["input"], inv["summary"]
    defs = wb.by_id()

    def para(text, size=9.5, bold=False, color=(40, 40, 40), h=5.2, indent=0):
        pdf.set_font(F, "B" if bold else "", size)
        pdf.set_text_color(*color)
        pdf.set_x(MARGIN + indent)
        pdf.multi_cell(W - indent, h, str(text), new_x="LMARGIN", new_y="NEXT", align="L")

    def bullet(text, num=None, color=(40, 40, 40)):
        pdf.set_font(F, "", 9.5)
        pdf.set_text_color(*color)
        pdf.set_x(MARGIN + 2)
        pdf.cell(6, 5.2, f"{num}." if num else "•")
        pdf.multi_cell(W - 8, 5.2, strip_codes(str(text)), new_x="LMARGIN", new_y="NEXT", align="L")

    def heading(t):
        if pdf.get_y() > pdf.h - 45:
            pdf.add_page()
        pdf.ln(4)
        pdf.set_font(F, "B", 13)
        pdf.set_text_color(20, 25, 45)
        pdf.cell(W, 7, t, new_x="LMARGIN", new_y="NEXT", align="L")
        pdf.set_draw_color(210, 214, 225)
        pdf.line(MARGIN, pdf.get_y() + 0.5, MARGIN + W, pdf.get_y() + 0.5)
        pdf.ln(2.5)

    def sub(t):
        pdf.ln(1.5)
        para(t, size=10, bold=True, color=(20, 25, 45))

    # ---------- Title ----------
    pdf.set_font(F, "B", 19)
    pdf.set_text_color(20, 25, 45)
    pdf.cell(W, 10, "Supplier Due-Diligence Report", new_x="LMARGIN", new_y="NEXT", align="L")
    para(f"{prof.get('name') or inp['company_name']}  ·  prepared {inv['created'][:16].replace('T', ' ')}  ·  case {inv['id']}",
         size=9, color=(110, 110, 120))
    if inv.get("synthetic"):
        para("FICTIONAL DEMO COMPANY — all names, people and addresses are made up.", size=9, bold=True, color=(200, 120, 0))
    pdf.ln(3)

    # ---------- Verdict banner ----------
    c = VCOL.get(inv["verdict"], (100, 100, 100))
    y0 = pdf.get_y()
    pdf.set_fill_color(*c)
    pdf.rect(MARGIN, y0, W, 22, style="F")
    pdf.set_xy(MARGIN + 5, y0 + 3)
    pdf.set_text_color(255)
    pdf.set_font(F, "B", 17)
    pdf.cell(W - 10, 8, VERDICT_LABELS.get(inv["verdict"], inv["verdict"]).upper())
    pdf.set_xy(MARGIN + 5, y0 + 12)
    pdf.set_font(F, "", 10)
    pdf.cell(W - 10, 6, f"Risk score {sc['risk_score']:.0f} / 100     ·     Confidence {sc['confidence']:.0%}     ·     "
                        f"{sc['full']['flags']} red flag(s) found")
    pdf.set_y(y0 + 25)
    for r in sc.get("verdict_reasons", []):
        para(r, bold=True, color=c)
    para("Risk score: 0 = no warning signs, 100 = every check failed. Below 20 looks legitimate, 20–40 needs a human review, "
         "40+ is high risk. Confidence shows how much information we could find and how reliable it is.",
         size=8.5, color=(110, 110, 120), h=4.5)

    # ---------- Summary ----------
    heading("In plain words")
    para(strip_codes(s.get("summary", "")), size=10.5, h=5.8)
    if s.get("key_concerns"):
        sub("Main concerns")
        for x in s["key_concerns"]:
            bullet(x)
    if s.get("innocent_explanations"):
        sub("Could there be an innocent explanation?")
        for x in s["innocent_explanations"]:
            bullet(x)
    if s.get("analyst_questions"):
        sub("What to ask the company for")
        for i, x in enumerate(s["analyst_questions"], 1):
            bullet(x, num=i)

    # ---------- Company ----------
    heading("Company details")
    to = inp.get("declared_turnover")
    rows = [("Name given", inp["company_name"]), ("Matched profile", prof.get("name") or "No public profile found"),
            ("Website", inp.get("domain") or prof.get("domain") or "—"), ("GSTIN", inp.get("gstin") or "—"),
            ("Director named", inp.get("director") or "—"),
            ("Claimed turnover", f"{to:,.0f} {inp.get('turnover_currency')}" if to else "—"),
            ("Claimed employees", inp.get("declared_headcount") or "—"),
            ("Employees we found", prof.get("headcount") if prof.get("headcount") is not None else "—"),
            ("Founded", prof.get("founded") or "—"), ("Head office", prof.get("hq") or "—"), ("Industry", prof.get("industry") or "—")]
    for k, v in rows:
        pdf.set_x(MARGIN)
        pdf.set_font(F, "B", 9)
        pdf.set_text_color(90, 95, 110)
        pdf.cell(42, 5.4, k)
        pdf.set_font(F, "", 9.5)
        pdf.set_text_color(30, 30, 30)
        pdf.multi_cell(W - 42, 5.4, str(v), new_x="LMARGIN", new_y="NEXT", align="L")

    # ---------- Areas ----------
    heading("Results by area")
    widths = (84, 26, 26, 22, W - 158)
    pdf.set_font(F, "B", 8.5)
    pdf.set_text_color(90, 95, 110)
    pdf.set_x(MARGIN)
    for t, w in zip(("Area", "Checks", "Done", "Red flags", "Area risk"), widths):
        pdf.cell(w, 6.5, t, border="B")
    pdf.ln()
    for cat in sc["categories"]:
        pdf.set_x(MARGIN)
        pdf.set_font(F, "", 9)
        pdf.set_text_color(30, 30, 30)
        risk = cat["category_risk"]
        vals = (CATEGORY_LABELS.get(cat["category"], cat["category"]), str(cat["checks"]), str(cat["assessed"]), str(cat["flags"]),
                f"{risk:.0%}" if cat["assessed"] else "not checked")
        for i, (t, w) in enumerate(zip(vals, widths)):
            if i == 4 and cat["assessed"]:
                pdf.set_text_color(*((205, 55, 55) if risk >= .4 else (214, 140, 20) if risk >= .2 else (31, 140, 95)))
            pdf.cell(w, 6, t, border="B")
        pdf.ln()
    para(f"Checked automatically: {sc['automated']['coverage']:.0%} of what can be automated  ·  "
         f"full checklist done: {sc['full']['coverage']:.0%}  ·  full checklist status: {TIER_LABELS.get(sc['workbook_tier'], sc['workbook_tier'])}",
         size=8.5, color=(110, 110, 120), h=4.8)

    # ---------- Evidence ----------
    heading("What we checked and what we found")
    para("Most serious first. RED FLAG = clear warning sign · CONCERN = minor warning · OK = no problem · NO DATA = we couldn't find information (this is not evidence of wrongdoing) · N/A = doesn't apply.",
         size=8.5, color=(110, 110, 120), h=4.6)
    order = {"Flag": 0, "Partial": 1, "Pass": 2, "N/A": 4, None: 3}
    items = [o for o in inv["outcomes"].values() if o["id"] in defs]
    items.sort(key=lambda o: (order.get(o.get("result"), 3), -defs[o["id"]].weight))
    last_group = None
    for o in items:
        d = defs[o["id"]]
        r = o.get("result")
        grp = RESULT_LABELS.get(r, "Couldn't verify")
        if grp != last_group:
            sub({"Red flag": "Red flags", "Concern": "Concerns", "OK": "Passed", "Not applicable": "Not applicable",
                 "Couldn't verify": "Couldn't verify"}.get(grp, grp))
            last_group = grp
        if pdf.get_y() > pdf.h - 32:
            pdf.add_page()
        # label column
        y = pdf.get_y()
        pdf.set_xy(MARGIN, y)
        pdf.set_font(F, "B", 7.5)
        pdf.set_text_color(*RCOL.get(r, (130, 130, 130)))
        pdf.cell(COL, 5.2, SHORT.get(r, "NO DATA"))
        # title + importance
        pdf.set_xy(MARGIN + COL, y)
        pdf.set_font(F, "B", 9.5)
        pdf.set_text_color(25, 25, 35)
        tag = "   (deal-breaker)" if d.hard_stop else ""
        pdf.multi_cell(W - COL, 5.2, plain_name(d.id, d.name) + tag, new_x="LMARGIN", new_y="NEXT", align="L")
        src = SOURCE_LABELS.get(o.get("source", ""), o.get("source", ""))
        ev = strip_codes(o.get("evidence", "")).replace("Unverifiable: ", "").replace("Couldn't check: ", "No data: ")
        pdf.set_x(MARGIN + COL)
        pdf.set_font(F, "", 8.8)
        pdf.set_text_color(70, 72, 85)
        pdf.multi_cell(W - COL, 4.7, f"{ev}" + (f"  Source: {src}." if src and src != "Not relevant for this company" else ""), new_x="LMARGIN", new_y="NEXT", align="L")
        pdf.ln(1.2)

    # ---------- Not automated ----------
    manual = [c for c in wb.checks if c.id not in inv["outcomes"]]
    if manual:
        heading("Still to be checked by a person")
        para(f"{len(manual)} checks need documents, registry access or bank data that the agent cannot reach automatically "
             "(for example ownership records, original documents, bank statements). They are not counted in the score yet.",
             size=9, color=(80, 80, 90))
        by = {}
        for c in manual:
            by.setdefault(CATEGORY_LABELS.get(c.category, c.category), []).append(c.name)
        for cat, names in by.items():
            bullet(f"{cat}: {', '.join(n.lower() for n in names)}")

    # ---------- Method ----------
    heading("How this report was made")
    cost = inv["cost"]
    para(f"Time taken: {cost['seconds']} seconds. Data credits used: {cost['credits']} (limit {cost['cap']:.0f}). "
         f"A comparable manual review is assumed at about {cost['manual_hours']:.0f} analyst-hours "
         f"(≈ ₹{cost['manual_cost_inr']:,.0f}) — an editable benchmark, not a measured figure.", size=9)
    para("Sources: Crustdata company and job data, the company website, domain registry records, news search, the US sanctions "
         "list (OFAC), GSTIN format rules, and our own records of previously checked companies.", size=9)
    para("Each check is weighted by importance; red flags count fully and concerns count half. The verdict is set by fixed rules, "
         "not by AI. AI is used only to match the company name, read news headlines, and write the plain-language summary. "
         "Missing information is treated as 'couldn't verify', never as proof of fraud. This report describes warning signs; "
         "it is not a legal finding.", size=9)
    return bytes(pdf.output())
