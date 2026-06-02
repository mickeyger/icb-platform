#!/usr/bin/env bash
# ICB Platform - production-like local run: one FastAPI service on port 8000.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f frontend/dist/index.html ] || ( cd frontend && npm run build )
cd backend
# shellcheck disable=SC1091
source .venv/bin/activate
echo "Applying migrations (alembic upgrade head)..."
alembic upgrade head
echo "Unified app -> http://localhost:8000 (MES app at /mes-app/)"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
