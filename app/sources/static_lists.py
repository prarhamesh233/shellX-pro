"""Static reference data: GSTIN validation, FATF lists, free-mail domains, high-risk sectors.

FATF lists are a snapshot and MUST be verified against fatf-gafi.org before production use.
"""
from __future__ import annotations

import re

FATF_SNAPSHOT_NOTE = "FATF snapshot (Oct 2025 plenary); verify at fatf-gafi.org"
FATF_BLACK = {"PRK", "IRN", "MMR"}
FATF_GREY = {"DZA", "AGO", "BOL", "BGR", "CMR", "CIV", "HRV", "COD", "HTI", "KEN", "LAO", "LBN", "MCO",
             "NAM", "NPL", "SSD", "SYR", "VEN", "VNM", "YEM", "VGB"}
LOW_TRANSPARENCY = {"VGB", "CYM", "SYC", "PAN", "MHL", "BLZ", "VUT", "WSM", "KNA", "AIA", "BHS", "BMU",
                    "LBR", "MUS", "ARE", "LIE", "JEY", "GGY", "IMN", "CYP"}

COUNTRY_ALIASES = {
    "india": "IND", "in": "IND", "ind": "IND", "united states": "USA", "us": "USA", "usa": "USA",
    "united kingdom": "GBR", "uk": "GBR", "gb": "GBR", "singapore": "SGP", "sg": "SGP",
    "united arab emirates": "ARE", "uae": "ARE", "ae": "ARE", "germany": "DEU", "de": "DEU",
    "british virgin islands": "VGB", "bvi": "VGB", "cayman islands": "CYM", "hong kong": "HKG",
    "china": "CHN", "netherlands": "NLD", "france": "FRA", "canada": "CAN", "australia": "AUS",
    "japan": "JPN", "mauritius": "MUS", "seychelles": "SYC", "panama": "PAN", "cyprus": "CYP",
}


def to_iso3(c: str | None) -> str | None:
    if not c:
        return None
    c = c.strip()
    if len(c) == 3 and c.isalpha() and c.upper() == c:
        return c
    return COUNTRY_ALIASES.get(c.lower(), c.upper()[:3] if len(c) == 3 else None)


FREE_MAIL = {"gmail.com", "yahoo.com", "yahoo.co.in", "hotmail.com", "outlook.com", "live.com", "rediffmail.com",
             "aol.com", "icloud.com", "protonmail.com", "proton.me", "zoho.com", "gmx.com", "mail.com", "yandex.com"}

HIGH_RISK_SECTOR_TERMS = ["crypto", "cryptocurrency", "virtual asset", "blockchain exchange", "gambling", "casino",
                          "betting", "precious metal", "bullion", "gold trading", "jewel", "arms", "defense trading",
                          "money services", "remittance", "forex", "foreign exchange", "money transfer", "hawala",
                          "trade intermediation", "import export", "import-export", "general trading", "commodity trading"]

GENERIC_DESC_TERMS = ["general trading", "trading company", "consulting", "consultancy", "general services",
                      "import and export", "import export", "merchant", "solutions provider", "multi business",
                      "diversified", "all kinds of", "and other services"]

# ---- GSTIN -----------------------------------------------------------------
GST_STATES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh", "05": "Uttarakhand",
    "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura", "17": "Meghalaya",
    "18": "Assam", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
    "24": "Gujarat", "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra", "29": "Karnataka",
    "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh", "97": "Other Territory",
}
_GST_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
PAN_ENTITY_TYPES = {"C": "Company", "P": "Individual/Proprietor", "H": "HUF", "F": "Firm/LLP", "A": "AOP",
                    "T": "Trust", "B": "BOI", "L": "Local authority", "J": "Artificial juridical person", "G": "Government"}


def gstin_checksum(g: str) -> str:
    total = 0
    for i, ch in enumerate(g[:14]):
        v = _CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += v // 36 + v % 36
    return _CHARS[(36 - total % 36) % 36]


def validate_gstin(g: str | None) -> dict:
    if not g:
        return {"provided": False}
    g = g.strip().upper()
    out = {"provided": True, "gstin": g, "format_ok": bool(_GST_RE.match(g))}
    if not out["format_ok"]:
        out["valid"] = False
        out["reason"] = "Does not match the 15-character GSTIN pattern"
        return out
    out["checksum_ok"] = gstin_checksum(g) == g[14]
    out["state_code"] = g[:2]
    out["state"] = GST_STATES.get(g[:2])
    out["pan"] = g[2:12]
    out["pan_entity_type"] = PAN_ENTITY_TYPES.get(g[5], "Unknown")
    out["valid"] = out["checksum_ok"] and out["state"] is not None
    if not out["checksum_ok"]:
        out["reason"] = "Checksum digit does not match"
    elif out["state"] is None:
        out["reason"] = "Unknown state code"
    return out
