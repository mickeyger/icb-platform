"""
Post-deploy smoke test for IceCold GRP Costing System.
Hits the live URL and verifies the app is responding correctly.

Usage:
    python tools/smoke_test.py
    python tools/smoke_test.py --url https://faje.co.za   (override URL)
    python tools/smoke_test.py --timeout 30
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).parent.parent

def green(s):  return f"\033[92m{s}\033[0m"
def red(s):    return f"\033[91m{s}\033[0m"
def yellow(s): return f"\033[93m{s}\033[0m"
def bold(s):   return f"\033[1m{s}\033[0m"
def cyan(s):   return f"\033[96m{s}\033[0m"

results = []

def ok(msg):
    results.append(("ok", msg))
    print(f"  {green('✓')} {msg}")

def fail(msg, detail=None):
    results.append(("fail", msg))
    print(f"  {red('✗')} {msg}")
    if detail:
        print(f"    {yellow('Detail:')} {detail}")

def warn(msg):
    results.append(("warn", msg))
    print(f"  {yellow('⚠')} {msg}")

def section(title):
    print(f"\n{bold(cyan('── ' + title + ' ' + '─' * (50 - len(title))))}")

def load_config():
    with open(ROOT / "deploy_config.json") as f:
        return json.load(f)

def fetch(url, timeout=15, follow_redirects=True, expected_status=None):
    """Fetch a URL and return (status_code, body_snippet, error)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "IceCold-SmokeTest/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(4096).decode("utf-8", errors="ignore")
            return resp.status, body, None
    except urllib.error.HTTPError as e:
        body = e.read(2048).decode("utf-8", errors="ignore")
        return e.code, body, None
    except urllib.error.URLError as e:
        return None, "", str(e.reason)
    except Exception as e:
        return None, "", str(e)

def check_https_redirect(base_url):
    section("HTTPS Redirect")
    http_url = base_url.replace("https://", "http://")
    status, body, err = fetch(http_url, timeout=10)
    if err:
        warn(f"Could not test HTTP redirect: {err}")
    elif status in (301, 302, 308):
        ok(f"HTTP correctly redirects to HTTPS (HTTP {status})")
    elif status == 200:
        warn("HTTP returns 200 without redirecting to HTTPS — check .htaccess")
    else:
        warn(f"HTTP returned unexpected status: {status}")

def check_login_page(base_url):
    section("Login Page")
    url = base_url.rstrip("/") + "/login"
    status, body, err = fetch(url, timeout=15)
    if err:
        fail(f"Could not reach {url}", err)
        return False
    if status == 200:
        ok(f"Login page returned HTTP 200")
    else:
        fail(f"Login page returned HTTP {status}", f"Expected 200")
        return False

    # Check for expected content
    markers = [
        ("IceCold", "brand name present"),
        ("password", "password field present"),
        ("Login",    "login button/heading present"),
    ]
    for marker, label in markers:
        if marker.lower() in body.lower():
            ok(f"Login page contains: {label}")
        else:
            warn(f"Login page missing expected content: {label}")

    return True

def check_no_debug_info(base_url):
    section("Security Checks")
    url = base_url.rstrip("/") + "/login"
    _, body, _ = fetch(url, timeout=10)

    leaks = ["Traceback", "sqlite", "SECRET_KEY", "DEBUG=True", "Stack trace"]
    for leak in leaks:
        if leak.lower() in body.lower():
            fail(f"Possible sensitive info exposed in page: '{leak}'",
                 "Set DEBUG=False in server .env")
        else:
            ok(f"No '{leak}' exposed in response")

def check_static_assets(base_url):
    section("Static Assets")
    assets = [
        ("/static/css/style.css", "Main CSS"),
        ("/static/js/app.js",     "Main JS"),
    ]
    for path, label in assets:
        url = base_url.rstrip("/") + path
        status, body, err = fetch(url, timeout=10)
        if err:
            fail(f"{label} unreachable", err)
        elif status == 200:
            ok(f"{label} returns HTTP 200")
        else:
            fail(f"{label} returned HTTP {status}", url)

def check_response_time(base_url):
    section("Response Time")
    url = base_url.rstrip("/") + "/login"
    start = time.time()
    status, _, err = fetch(url, timeout=20)
    elapsed = time.time() - start

    if err:
        fail(f"Could not measure response time: {err}")
        return
    if elapsed < 3:
        ok(f"Response time: {elapsed:.2f}s (good)")
    elif elapsed < 8:
        warn(f"Response time: {elapsed:.2f}s (slow — Passenger cold start?)")
    else:
        fail(f"Response time: {elapsed:.2f}s (too slow — app may be struggling)")

def check_error_page(base_url):
    section("Error Handling")
    url = base_url.rstrip("/") + "/nonexistent-page-xyz-404"
    status, body, err = fetch(url, timeout=10)
    if err:
        warn(f"Could not test 404 handling: {err}")
    elif status == 404:
        ok("404 page returns correct HTTP 404 status")
    elif status == 200:
        warn("404 page returns HTTP 200 — may be redirecting to login (acceptable)")
    else:
        warn(f"404 page returned HTTP {status}")

def print_summary(base_url):
    section("Smoke Test Summary")
    fails  = [r for r in results if r[0] == "fail"]
    warns  = [r for r in results if r[0] == "warn"]
    passes = [r for r in results if r[0] == "ok"]

    print(f"  {green('✓')} {len(passes)} passed")
    if warns:
        print(f"  {yellow('⚠')} {len(warns)} warning(s)")
    if fails:
        print(f"  {red('✗')} {len(fails)} failed\n")
        print(red(f"  ✗ SMOKE TEST FAILED — check the live site at {base_url}"))
        print(f"  {yellow('→ To rollback:')} tools\\rollback.bat")
        return False
    elif warns:
        print(f"\n{yellow('  ⚠ Site is up but review warnings above.')}")
        return True
    else:
        print(f"\n{green('  ✓ All smoke tests passed — production is healthy.')}")
        return True

def main():
    parser = argparse.ArgumentParser(description="Smoke test for IceCold GRP Costing System")
    parser.add_argument("--url",     default=None, help="Override base URL")
    parser.add_argument("--timeout", default=15,   type=int, help="Request timeout in seconds")
    args = parser.parse_args()

    cfg = load_config()
    base_url = args.url or cfg.get("live_url", "https://faje.co.za")

    print(bold(cyan("\n╔══════════════════════════════════════════════════╗")))
    print(bold(cyan(  "║   IceCold GRP — Post-Deploy Smoke Test           ║")))
    print(bold(cyan( f"║   Target: {base_url:<39}║")))
    print(bold(cyan(  "╚══════════════════════════════════════════════════╝")))

    check_https_redirect(base_url)
    alive = check_login_page(base_url)
    if alive:
        check_no_debug_info(base_url)
        check_static_assets(base_url)
        check_response_time(base_url)
        check_error_page(base_url)
    else:
        fail("Site is not responding — skipping remaining checks")

    passed = print_summary(base_url)
    sys.exit(0 if passed else 1)

if __name__ == "__main__":
    main()
