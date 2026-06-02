@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0.."

:: ══════════════════════════════════════════════════════════════
::  IceCold GRP Costing System — Rollback Script
::  Usage: tools\rollback.bat v1.2
::  Rolls back production to a specific tagged version.
:: ══════════════════════════════════════════════════════════════

echo.
echo ╔══════════════════════════════════════════════════╗
echo ║   IceCold GRP — Rollback Manager                ║
echo ╚══════════════════════════════════════════════════╝
echo.

set TARGET_TAG=%1

:: If no tag supplied, show available tags and prompt
if "%TARGET_TAG%"=="" (
    echo  Available tags to rollback to:
    echo.
    git tag --sort=-version:refname
    echo.
    set /p TARGET_TAG="  Enter tag to rollback to (e.g. v1.1): "
)

:: Validate tag exists
git tag | findstr /x "%TARGET_TAG%" >nul
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  ✗ Tag '%TARGET_TAG%' not found.
    echo    Run: git tag   to see available tags.
    pause
    exit /b 1
)

:: Get current version for reference
for /f "tokens=*" %%i in ('git tag --sort=-version:refname 2^>nul') do (
    set CURRENT_TAG=%%i
    goto :got_current
)
:got_current

echo  Current version : %CURRENT_TAG%
echo  Rollback target : %TARGET_TAG%
echo.
echo  ⚠  WARNING: This will revert ALL app code on production to %TARGET_TAG%.
echo     The production DATABASE will NOT be changed (data is safe).
echo.
choice /C YN /M "  Confirm rollback to %TARGET_TAG%?"
if %ERRORLEVEL%==2 (
    echo  Rollback cancelled.
    pause
    exit /b 0
)

echo.
echo  Rolling back to %TARGET_TAG%...

:: Create a revert commit pointing to the tag
git checkout %TARGET_TAG% -- .
if %ERRORLEVEL% NEQ 0 (
    echo  ✗ Checkout of %TARGET_TAG% failed.
    pause
    exit /b 1
)

git add -A
git commit -m "revert: rollback to %TARGET_TAG% from %CURRENT_TAG%

Emergency rollback. Previous version was %CURRENT_TAG%.
To re-apply: git revert HEAD then push.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"

git push origin main
if %ERRORLEVEL% NEQ 0 (
    echo  ✗ Push failed. Rollback commit is local only.
    echo    Run: git push origin main
    pause
    exit /b 1
)

echo.
echo  ✓ Rollback to %TARGET_TAG% pushed to production.
echo.
echo  Waiting 15 seconds then running smoke test...
timeout /t 15 /nobreak >nul
python tools\smoke_test.py

echo.
echo  Rollback complete. Live site should now be at version %TARGET_TAG%.
echo  To restore %CURRENT_TAG% later: git revert HEAD ^&^& git push origin main
echo.
pause
