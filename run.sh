#!/usr/bin/env bash
# One-shot local run: installs dependencies, builds the frontend and starts the API on :8000
set -euo pipefail
cd "$(dirname "$0")"
python3 -m pip install -q -r backend/requirements.txt
(cd frontend && npm install --no-audit --no-fund && npm run build)
cd backend && exec uvicorn fintea.main:app --host 0.0.0.0 --port "${PORT:-8000}"
