# ShellX Pro

**Check a supplier before you pay them.** Type a company's name and website. In under a minute ShellX tells you whether it looks like a real, operating business or shows signs of being a shell company. You get a plain-English explanation, the documents to ask the supplier for, and a downloadable PDF report.

Built for a hackathon using [Crustdata](https://crustdata.com) company data.

---

## Quick start

Requires Python 3.11+.

```bash
git clone <this-repo-url> shellx && cd shellx
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # then add your CRUSTDATA_API_KEY and GROQ_API_KEY
./run.sh                      # open http://127.0.0.1:8000
```

If `venv` fails with *"ensurepip is not available"* (Debian/Ubuntu), run `sudo apt install python3-venv` first.
Free keys: Groq at [console.groq.com/keys](https://console.groq.com/keys). Crustdata from your Crustdata account.
On first start the app downloads the US sanctions list (~7 MB) in the background.

**Try it:** click any example on the right of the form.

| Example | Expected result |
|---|---|
| Kestrel Analytics *(made-up)* | Looks legitimate |
| Orbit Softech *(made-up)* | Needs a human review |
| Nimbus Tradelink *(made-up)* | High risk: part of a shell network |
| Zerodha *(real, live data)* | Looks legitimate |
| Garantex Europe *(real, on US sanctions list)* | High risk: deal-breaker |

---

## What it checks

The checklist lives in `KYB_Shell_Company_Checks (1).xlsx`: **86 checks** in 11 areas, with weights, deal-breakers and thresholds. Edit the spreadsheet and the app follows; any `.xlsx` with a `Checks` sheet is picked up.

- **38 checks run automatically**, each phrased as a plain question such as *"Does it have the staff it claims?"* or *"Is the company on a sanctions list?"*
- **48 need a person** (ownership papers, bank statements, government portals). You can mark them in the app and the risk level updates instantly.

Every automatic check is explained in **[docs/Automated_Checks_Explained.md](docs/Automated_Checks_Explained.md)**.

**Data sources:**
- Crustdata: company profile, staff and history, revenue estimate, funding, web traffic, job ads, news
- The company's website
- Domain registration records
- Google News
- The US sanctions list (OFAC)
- GST number format rules
- The app's own records of companies checked before

## How the verdict is made

1. **Find the company** on Crustdata. If the name is ambiguous, the app asks you instead of guessing.
2. **Collect evidence** from all sources in parallel.
3. **Run the 38 checks.** Each returns *OK*, *Concern*, *Red flag*, *Not relevant* or *No data*.
4. **Score it with fixed rules** from the workbook:
   - **Risk level (0–100):** red flags count fully, concerns half.
   - **How sure we are:** how much data we found × how reliable the sources are.
   - **Verdict:**
     - any deal-breaker red flag → **High risk**
     - too little data → **Not enough data**
     - otherwise the score decides: 40+ **High risk**, 20–40 **Needs a human review**, under 20 **Looks legitimate**
5. **AI writes the words.** Groq `gpt-oss-120b` writes the summary, possible innocent explanations and the questions to ask. It sees only the check results and **never changes the verdict**.

**Missing data is never treated as fraud.** It only lowers how sure we are.

## What you get

- A result page with the verdict, a "What you should do" box, warning signs, good signs, what we couldn't check, and a **Copy as email** button for the document requests
- **Linked companies:** shared directors, addresses or phone numbers with other companies, including ones previously rejected
- A downloadable **PDF report**, and a shareable **verified badge** page (only for "Looks legitimate" results)
- Light and dark themes (dark by default)

## Project layout

```
app/          FastAPI backend
  agent.py      investigation pipeline
  evaluators.py the 38 automated checks
  scoring.py    workbook scoring and verdict
  crustdata.py  API client (cached, credit-capped)
  sources/      website, domain records, news, sanctions, GSTIN
  dossier.py    PDF report
web/          single-page UI (no build step)
docs/         check-by-check explanation
```

## Limits

- **Sanctions:** US OFAC list only. The high-risk-country list is a static snapshot.
- **GST numbers:** checked for format only; the government portal has a captcha.
- **Tech stack:** Crustdata's software data is a paid add-on. The app uses it automatically once enabled, and judges the website instead until then.
- **Linked companies:** only knows companies checked in this app, plus a fictional demo network.
- **Manual-review benchmark** (16 hours / ₹15,000): a placeholder you can set in `.env`.
- **Not legal advice:** the app shows warning signs to support a decision.
