@echo off
REM ICB Platform - first-time developer setup (Windows). WO v4.12 Phase 1.
setlocal
cd /d "%~dp0.."

echo === [1/5] Backend virtual environment + dependencies ===
if not exist "backend\.venv\Scripts\python.exe" py -3 -m venv backend\.venv
call backend\.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt

echo === [2/5] backend\.env ===
if not exist "backend\.env" (
    copy ".env.example" "backend\.env" >nul
    echo Created backend\.env from .env.example - review DATABASE_URL / SESSION_SECRET.
)

echo === [3/5] Frontend dependencies ===
pushd frontend
call npm ci
echo === [4/5] Build frontend (served at /mes-app/) ===
call npm run build
popd

echo === [5/5] Database migrations ===
echo If the database does not exist yet, create it first (one-time, as the postgres superuser):
echo    "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -p 5433 -f deploy\postgres\init.sql
pushd backend
alembic upgrade head
if errorlevel 1 echo [warn] alembic failed - did you run deploy\postgres\init.sql first?
popd

echo.
echo Setup complete. Start the app with:  scripts\start.bat
endlocal
