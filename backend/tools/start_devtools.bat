@echo off
cd /d "%~dp0.."

echo.
echo  IceCold GRP -- Dev Tools Dashboard
echo  ------------------------------------
echo.

:: ── Kill every process listening on port 8001 ──────────────────────────────
echo  Clearing port 8001 (removing any old server instances)...
for /f "tokens=5" %%p in ('netstat -ano 2^>nul ^| findstr ":8001 "') do (
    taskkill /PID %%p /F >nul 2>&1
)
timeout /t 2 /nobreak >nul

:: ── Verify port is free ────────────────────────────────────────────────────
netstat -ano 2>nul | findstr ":8001 " >nul
if %ERRORLEVEL% EQU 0 (
    echo  WARNING: Port 8001 still in use after kill attempt.
    echo  Try closing all Python windows manually, then retry.
    pause
    exit /b 1
)

:: ── Check Python ───────────────────────────────────────────────────────────
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo  ERROR: Python not found on PATH.
    pause
    exit /b 1
)

:: ── Install Flask if missing ───────────────────────────────────────────────
python -c "import flask" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo  Flask not installed -- installing now...
    pip install flask --quiet
)

echo  Starting on http://localhost:8001
echo  Browser opens automatically.
echo  Press Ctrl+C to stop.
echo.

python tools\devtools.py

pause
