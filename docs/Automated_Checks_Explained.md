# ShellX Pro — The 38 Automated Checks, Explained

*Plain-language guide to every check the agent runs on its own: what it looks at, where the data comes from, exactly how it decides, and when a warning might be innocent.*

Prepared 31 Oct 2026 · matches the code in `app/evaluators.py` · weights and thresholds come from `KYB_Shell_Company_Checks (1).xlsx`

---

## Part 1 — How an investigation works

When you press **Run investigation**, the agent does this, in order:

1. **Reads what you typed** (company name, website, GSTIN, director, claimed turnover and staff, business type) and validates it. The GSTIN is checked for the correct format and check-digit straight away.
2. **Finds the company on Crustdata** (free lookup). If you gave a website it matches on that. If you only gave a name and several companies match, an AI picks one *only if it is confident*; otherwise it asks you to choose, or continues without a profile if none of the matches look right.
3. **Collects evidence from six places at the same time:**

   | Source | What it gives us | Cost |
   |---|---|---|
   | **Crustdata company profile** | staff count and its history, staff by department and country, estimated revenue, funding, web traffic, followers, news, employee reviews, founders/executives, head-office address | 2 credits |
   | **Crustdata job postings** | each posting's title, department, description, location and date | ~0.03 credit per posting |
   | **The company's own website** | does it open, is it parked/for sale, does it look like a template, contact emails on the page | free |
   | **Domain registry (WHOIS / RDAP)** | when the web address was registered, whether the owner is hidden | free |
   | **News search** (Google News + Crustdata news) | headlines mentioning the company together with words like fraud, scam, raid | free |
   | **US sanctions list (OFAC)** | ~40,000 sanctioned companies and people, with aliases | free |

   Plus two things we hold ourselves: **our records of every company checked before** (to spot shared addresses, phones and directors) and **fixed reference lists** (high-risk countries, high-risk sectors, free-email providers, GSTIN state codes).
4. **Runs the 38 checks** below. Each one gives one of five results.
5. **Calculates the score and verdict** with the workbook formula (Part 3).
6. If the verdict is *Needs a human review*, it **digs deeper once or twice** (looks up the director separately, or runs an extra news search) and re-scores.
7. **An AI writes the plain-English summary**, possible innocent explanations and questions to ask. The AI never changes the score.

### The five possible results

| Result | Meaning | Effect on risk score |
|---|---|---|
| **Red flag** | The warning rule is clearly met | counts 100 % of the check's importance |
| **Concern** | A minor or partly-explained warning | counts 50 % |
| **OK** | Checked, nothing wrong | 0 % |
| **Not applicable** | The check doesn't apply to this company (e.g. GSTIN for a foreign firm) | left out completely |
| **Couldn't verify** | No data was available | left out of the score, **lowers confidence** |

> **Core rule:** *missing data is never treated as proof of fraud.* Many genuine small firms have almost no online presence. "Couldn't verify" makes us *less sure*, it does not make the company *look worse*.

### Importance (weight) levels

Every check has an importance from the workbook: **1 Low · 2 Moderate · 3 Significant · 4 High · 5 Critical.**
Three automated checks are **deal-breakers**: if they come back as a red flag, the case is sent to a senior reviewer no matter what the score is.

---

## Part 2 — The 38 checks

Checks are grouped by area. For each: *what it asks*, *why it matters*, *how it decides*, and *when it could be innocent*.
Numbers like "3 people" or "40 %" are the workbook's tunable thresholds — change them in the **Thresholds** sheet and the app follows.

---

### A. Company identity & registration (4 of 8 automated)

#### 1. Registration details match across sources
*Importance: High (4) · Workbook ref REG-02 · Source: Crustdata*

- **Asks:** Is the company we found the same one you described?
- **Why:** Shells often borrow a real company's name or website to look legitimate.
- **How it decides:** compares the name you typed with Crustdata's name (similarity score 0–1, after removing words like "Pvt Ltd"), your website with Crustdata's, and your country with Crustdata's head-office country.
  - **Red flag:** names very different (similarity < 0.5) **and** website differs.
  - **Concern:** names somewhat different (< 0.7), or website or country don't match.
  - **OK:** all line up.
  - **Couldn't verify:** no Crustdata profile.
- **Could be innocent:** brand name vs legal name, rebrands, regional subsidiaries.

#### 2. Company age vs claimed activity
*Importance: Significant (3) · REG-03 · Source: Crustdata founding year*

- **Asks:** Is a brand-new company claiming big business?
- **Why:** Shells are often freshly created to push large invoices quickly.
- **How:** age = this year − founding year.
  - **Red flag:** younger than **12 months** and claimed turnover ≥ US$1 million.
  - **Concern:** younger than 12 months (any turnover).
  - **OK:** older.
- **Could be innocent:** real start-ups and new subsidiaries of established groups.

#### 3. Country of incorporation
*Importance: High (4) · REG-05 · Source: Crustdata + high-risk/low-transparency country list*

- **Asks:** Is it registered in a secrecy haven or high-risk country, with nobody actually working there?
- **How:** checks the head-office country against a list of low-transparency places (e.g. BVI, Cayman, Seychelles, Panama, UAE, Mauritius, Cyprus) and the FATF high-risk lists, then compares with the country where most staff actually are.
  - **Red flag:** risky country **and** staff mostly elsewhere (or no staff seen).
  - **Concern:** risky country but staff are there too.
  - **OK:** not a risky country.
- **Could be innocent:** holding companies legitimately sit in these places; ask for the business reason.

#### 4. Tax registration (GSTIN) is valid
*Importance: Significant (3) · REG-07 · Source: GSTIN format rules*

- **Asks:** Is the GST number real-looking and consistent with the company?
- **How:** checks the 15-character pattern, the state code (first two digits), and the **check-digit** (the last character is calculated from the other 14 — a typed-in fake usually fails this). Also reads the PAN inside the GSTIN: the 4th letter shows the holder type (C = company, P = individual, F = firm…).
  - **Red flag:** wrong format, unknown state code, or wrong check-digit.
  - **Concern:** valid, but the PAN belongs to an individual/firm while the name says "Pvt Ltd/Limited".
  - **OK:** valid.
  - **Not applicable:** company outside India. **Couldn't verify:** no GSTIN given.
- **Limit:** the government GST portal has a captcha, so we can't confirm the number is *registered and active* — only that it is *well-formed*. That part stays on the person-to-check list.

---

### B. Address, contact & website (3 of 5 automated)

#### 5. Address consistency
*Importance: Moderate (2) · ADR-03 · Source: GSTIN state vs Crustdata head-office state*

- **Asks:** Is the GST registered in the same state as the head office?
- **How:** compares the state from the GSTIN code with Crustdata's head-office state.
  - **Concern:** different states. **OK:** same.
  - **Couldn't verify:** no valid GSTIN or no head-office state.
- **Could be innocent:** companies hold separate GSTINs in every state they operate in.

#### 6. Contact details
*Importance: Moderate (2) · ADR-04 · Source: the email you entered, Crustdata, emails on the website*

- **Asks:** Does the company use a proper business email?
- **How:** takes the first available contact email.
  - **Concern:** Gmail/Yahoo/Rediffmail-type free email.
  - **Red flag:** a business email on a *different* domain from the company's website.
  - **OK:** email on the company's own domain.
- **Could be innocent:** very small businesses commonly use Gmail.

#### 7. Domain (website address) age
*Importance: Moderate (2) · ADR-05 · Source: domain registry (RDAP/WHOIS)*

- **Asks:** When was the website address registered?
- **Why:** shell sites are typically registered days or weeks before they apply.
- **How:**
  - **Red flag:** registered less than **6 months** ago.
  - **Concern:** less than 18 months, or less than 2 years with the owner's identity hidden.
  - **OK:** older.

---

### C. Signs of a real, operating business (15 of 15 automated)

This is the heart of shell detection: *does the observable reality match the claim?*

#### 8. Company has a matching public profile
*Importance: Significant (3) · OPS-01 · Source: Crustdata*

- **How:**
  - **Red flag:** no profile found **while** the application claims a real size (more than 3 staff or turnover ≥ US$250k).
  - **Concern:** no profile but no big claims (small/new firms are often missing), or a match with low confidence.
  - **OK:** confidently matched.

#### 9. Staff count vs claimed size
*Importance: High (4) · OPS-02 · Source: Crustdata live headcount*

- **Asks:** Do they actually have the people they claim?
- **How:**
  - **Red flag:** **3 people or fewer** while claiming real operations, **or** observed staff are under **25 %** of the claimed number.
  - **Concern:** under 50 % of claimed.
  - **OK:** otherwise.
- **Could be innocent:** contractors and outsourced staff don't show up in profiles.

#### 10. Staff history
*Importance: Significant (3) · OPS-03 · Source: Crustdata headcount history (up to ~3 years of monthly points)*

- **How:**
  - **Red flag:** almost no history (< 3 data points) and 3 or fewer staff; **or** staff jumped by more than 300 % in a year with no funding and tiny revenue.
  - **Concern:** thin history.
  - **OK:** steady history.

#### 11. Sudden staff decline
*Importance: Significant (3) · OPS-04 · Source: Crustdata 6-month growth*

- **How:** **Red flag** if staff fell more than **40 %** in 6 months; **Concern** if more than 20 %; otherwise OK.
- **Could be innocent:** layoffs at real businesses — check the news.

#### 12. Department mix makes sense
*Importance: Significant (3) · OPS-05 · Source: Crustdata headcount by function*

- **Asks:** Does the company have the kinds of staff a real business needs?
- **How:** **Red flag** if 10+ staff but everyone is in one department (or > 85 % in one); **Concern** if only 1–2 departments; OK otherwise.

#### 13. Where the staff are
*Importance: Significant (3) · OPS-06 · Source: Crustdata largest headcount country*

- **How:** **Red flag** if most staff are in a different country from the one you stated and from the head office; OK otherwise.

#### 14. Hiring activity
*Importance: Moderate (2) · OPS-07 · Source: Crustdata job postings (full details)*

- **Asks:** Does the company really hire, and do its job ads look genuine?
- **How:** pulls up to 15 recent postings with title, department, description, location and date, then looks for:
  - never having posted a job **while claiming growth** (claimed staff 1.5× more than observed, or > 20 % growth) → **Red flag**;
  - never posted, no growth claimed → **Concern**;
  - half or more postings with **identical descriptions**, all postings with the **same title**, 80 %+ with **empty/boilerplate descriptions**, or **all postings abroad** while the head office is elsewhere — two of these → **Red flag**, one → **Concern**;
  - no postings in the last 12 months despite claimed growth → **Concern**;
  - otherwise **OK**.
- The website shows the job table with links to each posting.

#### 15. Website traffic
*Importance: Significant (3) · OPS-08 · Source: Crustdata web traffic + website check*

- **How:**
  - **Red flag:** website doesn't open at all, **or** a consumer/platform business with under **500** monthly visitors.
  - **Not applicable:** B2B business with no traffic data (B2B sites are naturally quiet).
  - **OK:** otherwise.

#### 16. Unusual traffic patterns
*Importance: Moderate (2) · OPS-09 · Source: Crustdata traffic sources*

- **How:** **Concern** if more than 95 % of visits come from one single source (e.g. all paid ads) or traffic jumped more than 300 % in a month; otherwise OK.

#### 17. Technology / tech stack
*Importance: Moderate (2) · OPS-10 · Source: Crustdata technographics if unlocked, otherwise the website itself*

- **Asks:** Is there real software behind the business, or just a landing page?
- **How (when Crustdata technographics is available):** counts detected technologies — **Red flag** if zero for a digital/consumer business, **Concern** if fewer than 5, else OK.
- **How (currently — technographics is locked on our API key):** inspects the homepage —
  - parked/for-sale page, or template text ("Your Company Name", "lorem ipsum") with few links → **Red flag** for digital businesses, **Concern** for others;
  - fewer than 8 links (a one-page site) → **Concern**;
  - otherwise **OK**.

#### 18. Estimated revenue vs claimed turnover
*Importance: Significant (3) · OPS-11 · Source: Crustdata revenue estimate*

- **How:** converts claimed turnover to US$ (at ₹88 = $1). **Red flag** if the claim is more than **3×** the top of Crustdata's estimated range; OK otherwise. Not applicable if no turnover was claimed.
- **Could be innocent:** private-company revenue estimates are rough; use as a sanity check.

#### 19. Funding claims
*Importance: Significant (3) · OPS-12 · Source: Crustdata funding history*

- **How:** only if you ticked "claims funding". **Red flag** if Crustdata shows zero funding rounds and zero investment; OK otherwise.

#### 20. Reviews and reputation
*Importance: Low (1) · OPS-13 · Source: Crustdata employee and software reviews*

- **How:** only for companies with 50+ staff (claimed or observed). **Concern** if there are no reviews at all; OK otherwise.

#### 21. Social media and press footprint
*Importance: Moderate (2) · OPS-14 · Source: Crustdata followers and news*

- **How:** **Red flag** if under 50 followers and no news at all; **Concern** if under 500 followers and no news; OK otherwise.

#### 22. Online age vs claimed history
*Importance: Significant (3) · OPS-15 · Source: Crustdata founding year vs domain registry*

- **Asks:** Does a company claiming 15 years of history have a website registered last year?
- **How:** gap = claimed years in business − domain age. **Red flag** if the gap is over 6 years, **Concern** over 3 years, else OK.
- **Could be innocent:** domain changes after a rebrand.

---

### D. Key people behind it (3 of 8 automated)

#### 23. The director's professional background
*Importance: Significant (3) · PPL-02 · Source: Crustdata founders/executives, then a person search if needed*

- **How:** **OK** if the director you named appears in the company's leadership with a title; **Concern** if we only find their profile at an unrelated company; **Couldn't verify** if no profile exists.

#### 24. Director's title and employer match
*Importance: Significant (3) · PPL-04 · Source: Crustdata*

- **How:** **OK** if the named director is listed in the company's leadership; **Red flag** if their own profile says they currently work somewhere else; **Concern** if they simply aren't listed.

#### 25. One person is the whole company
*Importance: Moderate (2) · PPL-05 · Source: Crustdata*

- **How:** **Red flag** if there are 2 or fewer staff and at most one named leader; OK otherwise.
- **Could be innocent:** very common in genuine micro-businesses.

---

### E. Links to other companies (4 of 10 automated)

These use **our own records** of every company the app has checked before (plus a small *fictional* demo network). They get stronger the more you use the app.

#### 26. Directors shared across many companies
*Importance: High (4) · GRF-01*

- **How:** counts how many companies in our records share each of this company's directors. **Red flag** if more than **10**, **Concern** if more than 3, OK otherwise.
- **Could be innocent:** professional/nominee directors and company-secretarial firms.

#### 27. Shared address, phone, email or PAN
*Importance: High (4) · GRF-03*

- **How:** looks for other companies with the same address, phone, email, website or PAN. **Red flag** if two or more such links, **Concern** if one, OK if none.

#### 28. Copy-paste companies
*Importance: Significant (3) · GRF-04*

- **How:** compares the business description with all known companies. **Red flag** if 90 %+ identical to another company's description.

#### 29. Connected to a previously rejected company — **deal-breaker**
*Importance: Critical (5) · GRF-06*

- **How:** if any shared identifier (address, phone, director…) links to a company on our **watchlist** (previously rejected or reported), it is a **Red flag** and the case goes straight to a senior reviewer.

---

### F. What the business does (3 of 7 automated)

#### 30. Business description is specific
*Importance: Significant (3) · BUS-01 · Source: Crustdata description or what you typed*

- **How:** looks for vague phrases ("general trading", "consulting", "general services", "import export"…).
  - **Red flag:** vague phrases **and** a short description (< 160 characters).
  - **Concern:** vague phrases, or a very short description.
  - **OK:** specific.

#### 31. Stated business matches the industry
*Importance: Moderate (2) · BUS-03*

- **How:** compares keywords in what you typed as the business with Crustdata's industry, categories and specialities. **OK** if they overlap; **Concern** if no overlap (could just be different wording).

#### 32. High-risk sector
*Importance: Significant (3) · BUS-04*

- **How:** **Red flag** if the description/industry mentions crypto, gambling, bullion/precious metals, forex/remittance, arms, or general/commodity trading, or you selected "Trading" as business type.
- **Note:** this only means *extra checks are needed*; it is not proof of wrongdoing.

---

### G. Sanctions & negative news (4 of 6 automated)

#### 33. Company is on the sanctions list — **deal-breaker**
*Importance: Critical (5) · SCR-01 · Source: US Treasury OFAC list (~40,000 names incl. aliases)*

- **How:** cleans both names (removes "Pvt", "Ltd", punctuation, sorts words) and compares with every sanctioned company.
  - **Red flag:** match score ≥ **0.93** (practically the same name) → senior reviewer.
  - **Concern:** score 0.86–0.93 — a *possible* match a person must resolve (often a name coincidence).
  - **OK:** no match.

#### 34. Directors / founders on the sanctions list — **deal-breaker**
*Importance: Critical (5) · SCR-02*

- **How:** same as above, against sanctioned *individuals*, for the director you named plus up to 6 founders/executives Crustdata lists. Also catches partial names (e.g. "Viktor Bout" inside "BOUT, Viktor Anatolijevitch").

#### 35. Negative news
*Importance: High (4) · SCR-04 · Source: Google News + Crustdata news, read by AI*

- **How:** searches headlines that contain the company's name **and** words like fraud, scam, money laundering, GST evasion, raid. An AI then reads each headline and decides whether the company is the **wrongdoer**, the **victim**, or unrelated. (Example: *"How 15 men scammed Zerodha"* → victim, so it does **not** count against Zerodha.)
  - **Red flag:** 2+ headlines name it as the wrongdoer. **Concern:** 1. **OK:** none.

#### 36. Exposure to high-risk countries
*Importance: High (4) · SCR-05 · Source: FATF lists (snapshot)*

- **How:** looks at head-office country, main staff country and the country you entered. **Red flag** if any is on the FATF "call for action" list (North Korea, Iran, Myanmar); **Concern** if on the "increased monitoring" (grey) list; OK otherwise.
- **Limit:** the list is a fixed snapshot — verify against fatf-gafi.org.

---

### H. Money flows (1 of 9 automated)

#### 37. Claimed business volume per employee
*Importance: High (4) · TXN-01*

- **Asks:** Could this many people realistically handle that much business?
- **How:** claimed turnover (in US$) ÷ observed staff. **Red flag** if more than **US$5 million per person**; **Concern** above US$2.5 million; OK otherwise.
- **Could be innocent:** marketplaces and payment platforms legitimately have very high volume per person.

---

### I. Ongoing monitoring (1 of 3 automated)

#### 38. Website status
*Importance: Significant (3) · MON-01 · Source: live website check*

- **How:** **Red flag** if the website does not open (we explain why: no response — may be offline or seized; address doesn't exist; server error) or shows a parked/for-sale page; **OK** if it loads normally.

---

## Part 3 — From 38 results to one verdict

**Risk score (0–100)** — the workbook's own formula:

> risk score = (sum of importance × result value) ÷ (sum of importance of the checks we could do) × 100
> where Red flag = 1, Concern = 0.5, OK = 0

**Confidence (0–100 %)** = *share of automated checks that had data* × *how reliable the sources are* (e.g. sanctions list 95 %, domain registry 90 %, Crustdata 80 %, website 70 %, news 55 %).

**Verdict rules (fixed, not AI):**

| Condition | Verdict |
|---|---|
| Any deal-breaker check is a red flag | **High risk** — send to senior reviewer |
| Fewer than 2 independent sources had data, or under 60 % of automated checks had data | **Not enough data to decide** |
| Score 40 or more | **High risk** |
| Score 20–40 | **Needs a human review** |
| Score under 20 | **Looks legitimate** |

**Showing only what matters ("less is more"):** the result screen shows at most 5 biggest warning signs, 4 reassuring signs and 5 things we couldn't check. Everything else is one click away.

---

## Part 4 — Known limits

- The **48 checks that are not automated** (ownership records, original documents, bank transactions, interviews, government portals with captchas) appear on the website under **"For a person to check"**. Marking them updates the score immediately.
- **Score dilution:** many "OK" results can soften a few strong red flags — weights and the 20/40 cut-offs should be tuned on real past cases.
- Only the **US OFAC** sanctions list is used so far (no UN/EU/Indian lists).
- **GSTIN** is checked for format only, not live registration status.
- **Tech stack** uses a website proxy until Crustdata unlocks technographics on our key.
- **Links to other companies** only know about companies this app has already checked (plus the fictional demo network).
- All wording describes **warning signs**, never a legal finding.
