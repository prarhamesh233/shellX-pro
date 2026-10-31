"""Central configuration. Everything tunable lives in .env or the KYB workbook."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "cache"
WEB = ROOT / "web"
DATA.mkdir(exist_ok=True)
CACHE.mkdir(exist_ok=True)

load_dotenv(ROOT / ".env")

CRUSTDATA_API_KEY = os.getenv("CRUSTDATA_API_KEY", "").strip()
CRUSTDATA_BASE = "https://api.crustdata.com"
CRUSTDATA_VERSION = "2025-11-01"

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
LLM_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "openai/gpt-oss-20b")

TECHNOGRAPHICS = os.getenv("CRUSTDATA_TECHNOGRAPHICS", "auto")  # auto | off
CREDIT_CAP = float(os.getenv("CREDIT_CAP_PER_INVESTIGATION", "25"))
# Offline replay: never hit Crustdata, only cache/fixtures (for demos without network).
REPLAY_MODE = os.getenv("REPLAY_MODE", "0") == "1"

# Currency conversion for declared turnover given in INR (static, configurable).
INR_PER_USD = float(os.getenv("INR_PER_USD", "88"))

# Coverage threshold applied to the *automated* scope (the workbook's T3 applies to full scope).
AUTO_COVERAGE_MIN = float(os.getenv("AUTO_COVERAGE_MIN", "0.6"))

# Benchmark for the "vs manual" cost panel.
MANUAL_BENCHMARK_HOURS = float(os.getenv("MANUAL_BENCHMARK_HOURS", "16"))
MANUAL_BENCHMARK_COST_INR = float(os.getenv("MANUAL_BENCHMARK_COST_INR", "15000"))

HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "20"))
USER_AGENT = "ShellXPro/0.1 (KYB due-diligence research prototype)"
