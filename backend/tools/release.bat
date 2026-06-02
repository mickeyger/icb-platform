@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0.."

:: ══════════════════════════════════════════════════════════════
::  IceCold GRP Costing System — Release Script
::  Usage: tools\release.bat
::  Runs pre-deploy checks, bumps version, tags, and pushes.
:: ══════════════════════════════════════════════════════════════

echo.
echo ╔══════════════════════════════════════════════════╗
echo ║   IceCold GRP — Release Manager                 ║
echo ╚══════════════════════════════════════════════════╝
echo.

:: ── Step 1: Run pre-deploy checks ─────────────────────────────
echo [1/5] Running pre-deploy checks...
echo.
python tools\predeploy_check.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  ✗ Pre-deploy checks FAILED. Fix the issues above before releasing.
    echo    To skip SSH checks: python tools\predeploy_check.py --skip-ssh
    pause
    exit /b 1
)

echo.
echo  ✓ Pre-deploy checks passed.
echo.

:: ── Step 2: Determine current version ────────────────────────
echo [2/5] Determining version...
for /f "tokens=*" %%i in ('git tag --sort=-version:refname 2^>nul') do (
    set LATEST_TAG=%%i
    goto :found_tag
)
set LATEST_TAG=none
:found_tag

if "%LATEST_TAG%"=="none" (
    echo    No existing tags found. Starting at v1.0
    set CURRENT_MAJOR=1
    set CURRENT_MINOR=0
    set SUGGESTED_TAG=v1.0
    goto :show_version
)

echo    Latest tag: %LATEST_TAG%

:: Parse vMAJOR.MINOR from tag
set TAG_STRIPPED=%LATEST_TAG:~1%
for /f "tokens=1,2 delims=." %%a in ("%TAG_STRIPPED%") do (
    set CURRENT_MAJOR=%%a
    set CURRENT_MINOR=%%b
)

:: Increment minor
set /a NEW_MINOR=CURRENT_MINOR+1
set /a NEW_MAJOR=CURRENT_MAJOR

:: Prompt for major bump if minor hits 10
if !NEW_MINOR! GEQ 10 (
    echo.
    echo  ⚠  Minor version has reached !NEW_MINOR!
    echo     This is a good point to consider a major version bump.
    echo.
    choice /C YN /M "    Bump to v!NEW_MAJOR!.0 → v%NEW_MAJOR%.0 as MAJOR release (Y=Major, N=Minor v!CURRENT_MAJOR!.!NEW_MINOR!)?"
    if !ERRORLEVEL!==1 (
        set /a NEW_MAJOR=CURRENT_MAJOR+1
        set NEW_MINOR=0
    )
)

set SUGGESTED_TAG=v!NEW_MAJOR!.!NEW_MINOR!

:show_version
echo.
echo    Suggested next version: %SUGGESTED_TAG%
echo.
set /p CONFIRM_TAG="    Accept %SUGGESTED_TAG% or enter a different tag (e.g. v2.0): "
if not "%CONFIRM_TAG%"=="" set SUGGESTED_TAG=%CONFIRM_TAG%

:: Validate tag format
echo %SUGGESTED_TAG% | findstr /r "^v[0-9][0-9]*\.[0-9][0-9]*$" >nul
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  ✗ Invalid tag format: %SUGGESTED_TAG%
    echo    Must be in format vMAJOR.MINOR e.g. v1.2 or v2.0
    pause
    exit /b 1
)

:: Check tag doesn't already exist
git tag | findstr /x "%SUGGESTED_TAG%" >nul
if %ERRORLEVEL%==0 (
    echo.
    echo  ✗ Tag %SUGGESTED_TAG% already exists. Choose a different version.
    pause
    exit /b 1
)

:: ── Step 3: Get release notes ─────────────────────────────────
echo.
echo [3/5] Release notes...
echo    Changes since %LATEST_TAG%:
echo.
if "%LATEST_TAG%"=="none" (
    git log --oneline -10
) else (
    git log %LATEST_TAG%..HEAD --oneline
)
echo.
set /p RELEASE_NOTE="    Enter a short release description: "
if "%RELEASE_NOTE%"=="" set RELEASE_NOTE="Release %SUGGESTED_TAG%"

:: ── Step 4: Commit anything outstanding, tag, and push ────────
echo.
echo [4/5] Tagging and pushing %SUGGESTED_TAG%...

:: Stage any final changes
git add -A
git diff --cached --quiet
if %ERRORLEVEL% NEQ 0 (
    git commit -m "chore: pre-release tidy for %SUGGESTED_TAG%

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
    echo    Committed outstanding changes.
)

:: Create annotated tag
git tag -a %SUGGESTED_TAG% -m "%RELEASE_NOTE%"
if %ERRORLEVEL% NEQ 0 (
    echo  ✗ Failed to create tag.
    pause
    exit /b 1
)
echo    ✓ Tag created: %SUGGESTED_TAG%

:: Push commits and tag
git push origin main
if %ERRORLEVEL% NEQ 0 (
    echo  ✗ Push to origin/main failed.
    git tag -d %SUGGESTED_TAG%
    echo    Tag %SUGGESTED_TAG% removed. Fix push issue and retry.
    pause
    exit /b 1
)

git push origin %SUGGESTED_TAG%
if %ERRORLEVEL% NEQ 0 (
    echo  ✗ Failed to push tag. Push the tag manually: git push origin %SUGGESTED_TAG%
)

echo    ✓ Pushed to origin/main and tagged %SUGGESTED_TAG%

:: ── Step 5: Post-deploy smoke test ───────────────────────────
echo.
echo [5/5] Waiting 15 seconds for server to restart, then running smoke test...
timeout /t 15 /nobreak >nul

python tools\smoke_test.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  ⚠  Smoke test reported issues. Check the live site manually.
    echo     To rollback: tools\rollback.bat %LATEST_TAG%
)

:: ── Done ──────────────────────────────────────────────────────
echo.
echo ╔══════════════════════════════════════════════════╗
echo ║   Release %SUGGESTED_TAG% complete!                       ║
echo ║   Live at: https://faje.co.za                   ║
echo ╚══════════════════════════════════════════════════╝
echo.
echo    To rollback if needed:  tools\rollback.bat %LATEST_TAG%
echo.
pause
