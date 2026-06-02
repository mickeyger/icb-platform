#!/usr/bin/env bash
# ICB Platform - hot-reload dev: FastAPI :8000 (reload) + Vite :5173.
set -euo pipefail
cd "$(dirname "$0")/.."

( cd backend && source .venv/bin/activate && alembic upgrade head \
    && python -m uvicorn app.main:app --reload --port 8000 ) &
BACK=$!
( cd frontend && npm run dev ) &
FRONT=$!
trap 'kill $BACK $FRONT 2>/dev/null || true' EXIT
echo "Unified: http://localhost:8000   |   Hot-reload MES: http://localhost:5173/mes-app/"
wait
