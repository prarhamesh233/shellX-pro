"""Synthetic demo data. Every entity here is FICTIONAL and labelled synthetic in the UI.
Domains use the reserved-looking '.demo' TLD so they can never collide with real firms."""
from __future__ import annotations

import datetime as dt

from . import store

Y = dt.date.today().year
SHELL_ADDR = "Unit 4, 2nd Floor, Shree Complex, Andheri East, Mumbai 400069"
SHELL_DIRECTOR = "Rakesh Nair"


def _ts(n, start, step=0):
    base = dt.date.today() - dt.timedelta(days=30 * n)
    return [{"date": (base + dt.timedelta(days=30 * i)).isoformat(), "employee_count": max(0, start + step * i)} for i in range(n)]


SYNTHETIC = {
    "nimbustradelink.demo": {
        "label": "Synthetic shell (high risk)",
        "intake": {"company_name": "Nimbus Tradelink Pvt Ltd", "domain": "nimbustradelink.demo", "gstin": "27AABCN1234M1ZX",
                   "director": SHELL_DIRECTOR, "declared_turnover": 1200000000, "turnover_currency": "INR",
                   "declared_headcount": 45, "business_type": "trading",
                   "stated_business": "General trading and import export of electronic goods",
                   "contact_email": "nimbus.tradelink@gmail.com", "claims_funding": True},
        "company": {
            "crustdata_company_id": -101,
            "basic_info": {"name": "Nimbus Tradelink Pvt Ltd", "primary_domain": "nimbustradelink.demo", "all_domains": ["nimbustradelink.demo"],
                           "description": "General trading company providing import export and general services.",
                           "company_type": "Privately Held", "year_founded": Y - 1, "employee_count_range": "2-10", "status": "active"},
            "headcount": {"total": 2, "largest_headcount_country": "IND", "growth_percent": {"six_months": 0.0, "yoy": 0.0},
                          "by_role_absolute": {"Administrative": 2}, "timeseries": _ts(2, 2)},
            "locations": {"country": "IND", "state": "Maharashtra", "headquarters": SHELL_ADDR},
            "revenue": {"estimated": {"lower_bound_usd": 0, "upper_bound_usd": 100000}},
            "funding": {"total_investment_usd": 0.0, "num_funding_rounds": 0, "phone_number": "+91 98200 11111"},
            "taxonomy": {"professional_network_industry": "Import and Export", "categories": ["Trading"]},
            "people": {"founders": [{"basic_profile": {"name": SHELL_DIRECTOR, "current_title": "Director", "headline": "Director at multiple companies"}}]},
            "followers": {"count": 12}, "news": [], "web_traffic": {"domain_traffic": {}},
            "employee_reviews": None, "software_reviews": None,
        },
        "site": {"checked": True, "reachable": True, "status": 200, "https": False, "final_url": "http://nimbustradelink.demo",
                 "parked": False, "template": True, "title": "Your Company Name | Home", "links": 6, "bytes": 9000,
                 "emails": ["nimbus.tradelink@gmail.com"], "error": None},
        "rdap": {"domain": "nimbustradelink.demo", "found": True, "created": (dt.date.today() - dt.timedelta(days=80)).isoformat(),
                 "registrar": "Example Registrar", "privacy": True},
        "jobs": {"job_listings": [], "total_count": 0},
        "news": [],
    },
    "orbitsoftech.demo": {
        "label": "Synthetic thin-footprint firm (review)",
        "intake": {"company_name": "Orbit Softech Solutions Pvt Ltd", "domain": "orbitsoftech.demo", "gstin": "29AAACO7777K1ZP",
                   "director": "Meera Iyer", "declared_turnover": 80000000, "turnover_currency": "INR", "declared_headcount": 25,
                   "business_type": "b2b", "stated_business": "Software development and IT consulting for SMEs",
                   "contact_email": "orbitsoftech.blr@gmail.com"},
        "company": {
            "crustdata_company_id": -102,
            "basic_info": {"name": "Orbit Softech Solutions", "primary_domain": "orbitsoftech.demo", "all_domains": ["orbitsoftech.demo"],
                           "description": "Consulting and general services for small businesses.",
                           "year_founded": Y - 3, "status": "active"},
            "headcount": {"total": 5, "largest_headcount_country": "IND", "growth_percent": {"six_months": -42.0, "yoy": -45.0},
                          "by_role_absolute": {"Engineering": 4, "Administrative": 1}, "timeseries": _ts(2, 7, -2)},
            "locations": {"country": "IND", "state": "Karnataka", "headquarters": "HSR Layout, Bengaluru"},
            "revenue": {"estimated": {"lower_bound_usd": 50000, "upper_bound_usd": 250000}},
            "funding": {"total_investment_usd": 0.0, "num_funding_rounds": 0},
            "taxonomy": {"professional_network_industry": "IT Services and IT Consulting", "categories": ["Software"]},
            "people": {"founders": [{"basic_profile": {"name": "Arjun Rao", "current_title": "Founder & CEO", "headline": "Founder, Orbit Softech"}}]},
            "followers": {"count": 40}, "news": [], "web_traffic": {"domain_traffic": {"orbitsoftech.demo": {"domain": "orbitsoftech.demo", "monthly_visitors": 900, "source_direct_pct": 60, "source_search_pct": 35}}},
        },
        "site": {"checked": True, "reachable": True, "status": 200, "https": True, "final_url": "https://orbitsoftech.demo",
                 "parked": False, "template": False, "title": "Orbit Softech — software for SMEs", "links": 22, "bytes": 40000,
                 "emails": ["hello@orbitsoftech.demo"], "error": None},
        "rdap": {"domain": "orbitsoftech.demo", "found": True, "created": (dt.date.today() - dt.timedelta(days=300)).isoformat(),
                 "registrar": "Example Registrar", "privacy": True},
        "jobs": {"job_listings": [], "total_count": 0},
        "news": [],
    },
    "kestrelanalytics.demo": {
        "label": "Synthetic operating firm (clear)",
        "intake": {"company_name": "Kestrel Analytics Pvt Ltd", "domain": "kestrelanalytics.demo", "gstin": "07AAICK4321P1Z7",
                   "director": "Ananya Sharma", "declared_turnover": 450000000, "turnover_currency": "INR", "declared_headcount": 120,
                   "business_type": "platform", "stated_business": "Analytics software platform for retail supply chains",
                   "contact_email": "contact@kestrelanalytics.demo", "claims_funding": True},
        "company": {
            "crustdata_company_id": -103,
            "basic_info": {"name": "Kestrel Analytics", "primary_domain": "kestrelanalytics.demo", "all_domains": ["kestrelanalytics.demo"],
                           "description": "Kestrel builds demand-forecasting and inventory analytics software used by 200+ retail chains across India and South-East Asia.",
                           "year_founded": Y - 7, "status": "active"},
            "headcount": {"total": 112, "largest_headcount_country": "IND", "growth_percent": {"six_months": 8.0, "yoy": 18.0},
                          "by_role_absolute": {"Engineering": 48, "Sales": 18, "Operations": 12, "Support": 10, "Product Management": 8, "Marketing": 6, "Finance": 4},
                          "timeseries": _ts(24, 70, 2)},
            "locations": {"country": "IND", "state": "Delhi", "headquarters": "Connaught Place, New Delhi"},
            "revenue": {"estimated": {"lower_bound_usd": 5000000, "upper_bound_usd": 10000000}},
            "funding": {"total_investment_usd": 12000000.0, "num_funding_rounds": 3, "contact_email": "contact@kestrelanalytics.demo"},
            "taxonomy": {"professional_network_industry": "Software Development", "categories": ["Analytics", "Retail Tech", "Supply Chain"]},
            "people": {"founders": [{"basic_profile": {"name": "Ananya Sharma", "current_title": "Co-founder & CEO", "headline": "Building retail analytics"}}],
                       "cxos": [{"basic_profile": {"name": "Vikram Menon", "current_title": "CTO", "headline": "CTO at Kestrel"}}]},
            "followers": {"count": 14500}, "news": [{"article_title": "Kestrel Analytics raises Series A"}],
            "web_traffic": {"domain_traffic": {"kestrelanalytics.demo": {"domain": "kestrelanalytics.demo", "monthly_visitors": 42000, "mom_pct": 4, "source_direct_pct": 40, "source_search_pct": 45, "source_social_pct": 10}}},
            "employee_reviews": {"overall_rating": {"total_count": 64, "rating": 4.1}}, "software_reviews": {"review_count": 21},
        },
        "site": {"checked": True, "reachable": True, "status": 200, "https": True, "final_url": "https://kestrelanalytics.demo",
                 "parked": False, "template": False, "title": "Kestrel Analytics — retail demand forecasting", "links": 85, "bytes": 120000,
                 "emails": ["contact@kestrelanalytics.demo"], "error": None},
        "rdap": {"domain": "kestrelanalytics.demo", "found": True, "created": f"{Y - 7}-03-14", "registrar": "Example Registrar", "privacy": False},
        "jobs": {"job_listings": [
            {"job_details": {"title": t, "category": c, "employment_type": "Full-time", "workplace_type": "Hybrid", "reposted_job": False,
                             "url": None},
             "content": {"description": f"Kestrel Analytics is hiring a {t} to join our {c} team in New Delhi. You will work on demand-forecasting models "
                                        f"and inventory analytics used by 200+ retail chains. Responsibilities include {d}. We offer ESOPs and hybrid work."},
             "location": {"raw": "New Delhi, Delhi, India", "country": "India"},
             "metadata": {"date_added": (dt.date.today() - dt.timedelta(days=a)).isoformat()}}
            for t, c, d, a in [("Senior Data Engineer", "Engineering", "building Spark and dbt pipelines on retail POS data", 12),
                               ("Account Executive", "Sales", "owning the mid-market retail pipeline across North India", 25),
                               ("Product Designer", "Design", "designing planner workflows for store managers", 40),
                               ("Site Reliability Engineer", "Engineering", "running our Kubernetes platform on AWS", 64)]], "total_count": 14},
        "news": [],
    },
}


def seed_network():
    """A fictional cluster: one professional director across 12 companies at one address,
    plus a previously-rejected (watchlisted) entity sharing the address and a phone."""
    names = ["Zenith Impex", "Silverline Commerce", "Apex Global Traders", "Crescent Merchandise", "Bluewave Exports",
             "Trident Overseas", "Pinnacle Tradecorp", "Horizon Ventures India", "Summit Enterprises", "Lotus Tradeways",
             "Galaxy Distributors"]
    for i, n in enumerate(names):
        store.upsert_entity(f"syn:{i}", n + " Pvt Ltd", [("director", SHELL_DIRECTOR), ("address", SHELL_ADDR if i % 3 != 2 else f"Shop {i}, Masjid Bunder, Mumbai"),
                                                       ("phone", "+91 98200 11111" if i < 4 else f"+91 98200 2{i:04d}")],
                            synthetic=True, description="General trading company providing import export and general services." if i % 2 == 0 else "")
    store.upsert_entity("syn:watch", "Vertex Bullion Traders Pvt Ltd (rejected 2025, suspicious activity reported)",
                        [("address", SHELL_ADDR), ("director", "Sunil Kapoor"), ("phone", "+91 98200 11111")],
                        synthetic=True, watchlist=True, status="rejected")
    store.upsert_entity("syn:other", "Kavya Textiles Pvt Ltd", [("director", "Sunil Kapoor"), ("address", "Plot 9, Surat")], synthetic=True)
