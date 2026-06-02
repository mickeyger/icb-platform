@echo off
cd /d "%~dp0.."

set LOGFILE=tools\check_results.log
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

echo.
echo  Running pre-deploy check — output saved to %LOGFILE%
echo.

:: Write header to log
echo ============================================================ > "%LOGFILE%"
echo  IceCold GRP — Pre-Deploy Check >> "%LOGFILE%"
echo  Run at: %DATE% %TIME% >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"
echo. >> "%LOGFILE%"

:: Run the check, capturing all output
python tools\predeploy_check.py --skip-ssh >> "%LOGFILE%" 2>&1

echo. >> "%LOGFILE%"
echo Exit code: %ERRORLEVEL% >> "%LOGFILE%"

echo.
echo  Done. Results written to: %LOGFILE%
echo  Opening log file...
echo.

:: Open the log in Notepad
notepad "%LOGFILE%"

pause
