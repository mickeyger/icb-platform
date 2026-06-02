@echo off
REM ICB Platform - hot-reload dev: FastAPI :8000 (reload) + Vite :5173.
setlocal
set "ROOT=%~dp0.."
echo [start-dev] Launching FastAPI :8000 (reload) and Vite :5173 in separate windows...
start "ICB backend :8000" /d "%ROOT%\backend" cmd /k ".venv\Scripts\activate.bat && alembic upgrade head && python -m uvicorn app.main:app --reload --port 8000"
start "ICB frontend :5173" /d "%ROOT%\frontend" cmd /k "npm run dev"
echo.
echo   Unified (Jinja + built MES):  http://localhost:8000
echo   Hot-reload MES (Vite):        http://localhost:5173/mes-app/   (proxies /api + /mes -^> :8000)
endlocal
