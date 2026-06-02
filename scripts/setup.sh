#!/usr/bin/env bash
# ICB Platform - first-time developer setup (Linux/Mac). WO v4.12 Phase 1.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== [1/6] Backend venv + dependencies ==="
[ -x backend/.venv/bin/python ] || python3 -m venv backend/.venv
# shellcheck disable=SC1091
source backend/.venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt

echo "=== [2/6] backend/.env ==="
[ -f backend/.env ] || { cp .env.example backend/.env; echo "Created backend/.env - review DATABASE_URL / SESSION_SECRET."; }

echo "=== [3/6] Frontend dependencies ==="
( cd frontend && npm ci )
echo "=== [4/6] Build frontend (served at /mes-app/) ==="
( cd frontend && npm run build )

echo "=== [5/6] Database migrations ==="
echo "If the database does not exist yet, create it first (one-time, as a superuser):"
echo "   psql -U postgres -p 5432 -f deploy/postgres/init.sql"
( cd backend && alembic upgrade head ) || echo "[warn] alembic failed - did you run deploy/postgres/init.sql first?"

echo "=== [6/6] Seed MES data from mockup JSON (icb_mes) ==="
python -m backend.scripts.seed_from_mockup --reset

echo "Setup complete. Start with: scripts/start.sh"
