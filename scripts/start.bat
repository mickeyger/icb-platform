@echo off
REM ICB Platform - production-like local run: one FastAPI service on port 8000.
setlocal
cd /d "%~dp0.."
if not exist "frontend\dist\index.html" (
    echo [start] Frontend not built - building now...
    pushd frontend
    call npm run build
    popd
)
cd backend
call .venv\Scripts\activate.bat
echo [start] Applying migrations (alembic upgrade head)...
alembic upgrade head
echo [start] Unified app -> http://localhost:8000   (MES app at /mes-app/)
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
endlocal
