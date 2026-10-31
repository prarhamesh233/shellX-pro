#!/usr/bin/env bash
# Start ShellX Pro on http://127.0.0.1:8000
cd "$(dirname "$0")"
[ -x .venv/bin/uvicorn ] || { echo "Run setup first: see README"; exit 1; }
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8000}"
