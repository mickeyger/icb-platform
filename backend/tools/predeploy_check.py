"""
Pre-deploy check for IceCold GRP Costing System.
Runs locally before every release to catch problems before they reach production.
Also SSHs into the server to verify critical server-side files exist.

Usage:
    python tools/predeploy_check.py
    python tools/predeploy_check.py --skip-ssh   (if SSH is unavailable)
"""

import json
import os
import subprocess
import sys
import argparse
from pathlib import Path

# ── Windows UTF-8 fix ──────────────────────────────────────────────────────────
# Reconfigure stdout/stderr to UTF-8 so box-drawing / tick characters don't crash
# when piped through devtools.py on Windows (which defaults to CP1252).
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass  # Python < 3.7 — best-effort

# ── Colour helpers ─────────────────────────────────────────────────────────────
def green(s):  return f"\033[92m{s}\033[0m"
def red(s):    return f"\033[91m{s}\033[0m"
def yellow(s): return f"\033[93m{s}\033[0m"
def bold(s):   return f"\033[1m{s}\033[0m"
def cyan(s):   return f"\033[96m{s}\033[0m"

ROOT = Path(__file__).parent.parent
CONFIG_FILE = ROOT / "deploy_config.json"

def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)

# ── Result tracker ─────────────────────────────────────────────────────────────
results = []

def ok(msg):
    results.append(("ok", msg))
    print(f"  {green('✓')} {msg}")

def fail(msg, fix=None):
    results.append(("fail", msg))
    print(f"  {red('✗')} {msg}")
    if fix:
        print(f"    {yellow('→ Fix:')} {fix}")

def warn(msg):
    results.append(("warn", msg))
    print(f"  {yellow('⚠')} {msg}")

def section(title):
    print(f"\n{bold(cyan('── ' + title + ' ' + '─' * (50 - len(title))))}")

# ══════════════════════════════════════════════════════════════════════════════
# LOCAL CHECKS
# ══════════════════════════════════════════════════════════════════════════════

def check_git_clean():
    section("Git Status")
    result = subprocess.run(["git", "status", "--short"], capture_output=True, text=True, cwd=ROOT)
    dirty = [l for l in result.stdout.strip().splitlines() if not l.startswith("??")]
    if dirty:
        warn(f"{len(dirty)} uncommitted change(s) — commit before releasing")
        for line in dirty[:5]:
            print(f"    {line}")
    else:
        ok("Working tree is clean")

    # Check we are on the right branch
    branch = subprocess.run(["git", "branch", "--show-current"],
                            capture_output=True, text=True, cwd=ROOT).stdout.strip()
    if branch == "main":
        ok(f"On branch: {branch}")
    else:
        fail(f"On branch '{branch}' — should be 'main' before releasing",
             "Run: git checkout main")

def check_no_secrets_in_git():
    section("Secrets & Sensitive Files")
    cfg = load_config()
    required_ignores = cfg["required_git_ignores"]

    gitignore_path = ROOT / ".gitignore"
    if not gitignore_path.exists():
        fail(".gitignore missing entirely", "Create a .gitignore at project root")
        return
    gitignore_content = gitignore_path.read_text(encoding="utf-8", errors="replace")

    for pattern in required_ignores:
        if pattern in gitignore_content:
            ok(f".gitignore covers: {pattern}")
        else:
            fail(f".gitignore missing: {pattern}",
                 f"Add '{pattern}' to .gitignore")

    # Check nothing bad is staged/tracked
    tracked = subprocess.run(["git", "ls-files"], capture_output=True, text=True, cwd=ROOT).stdout
    bad_files = [".env", "costing.db", ".pyc", ".db-shm", ".db-wal"]
    for bad in bad_files:
        matches = [l for l in tracked.splitlines() if bad in l]
        if matches:
            fail(f"Tracked file contains '{bad}': {matches[0]}",
                 f"Run: git rm --cached {matches[0]}")
        else:
            ok(f"No tracked files containing '{bad}'")

def check_requirements():
    section("Requirements & Dependencies")
    req_file = ROOT / "app" / "requirements.txt"
    if not req_file.exists():
        fail("app/requirements.txt not found")
        return
    ok("app/requirements.txt exists")

    content = req_file.read_text(encoding="utf-8", errors="replace")
    critical = ["fastapi", "uvicorn", "SQLAlchemy", "a2wsgi", "pymysql", "python-dotenv"]
    for pkg in critical:
        if pkg.lower() in content.lower():
            ok(f"Dependency present: {pkg}")
        else:
            fail(f"Missing dependency: {pkg}",
                 f"Add '{pkg}' to app/requirements.txt")

def check_key_files():
    section("Key Local Files")
    must_exist = [
        ("passenger_wsgi.py",      "passenger_wsgi.py"),
        ("deploy_config.json",     "deploy_config.json"),
        (".cpanel.yml",            ".cpanel.yml"),
        ("app/main.py",            "app/main.py"),
        ("app/requirements.txt",   "app/requirements.txt"),
    ]
    for label, rel_path in must_exist:
        path = ROOT / rel_path
        if path.exists():
            ok(f"Found: {label}")
        else:
            fail(f"Missing: {label}",
                 f"Ensure {rel_path} exists at project root")

    # .env should NOT be committed but SHOULD exist locally
    env_path = ROOT / ".env"
    if env_path.exists():
        ok(".env exists locally (not committed — good)")
        content = env_path.read_text(encoding="utf-8", errors="replace")
        if "MYSQL_URL" in content and "SQLITE_URL" in content:
            ok(".env has both SQLITE_URL and MYSQL_URL defined")
        if "DATABASE_URL=sqlite" in content:
            ok("DATABASE_URL points to SQLite (safe local default)")
        elif "DATABASE_URL=mysql" in content:
            warn("DATABASE_URL points to MySQL — you are using the PROD database locally!")
    else:
        warn(".env missing locally — app won't start in dev without it")

def check_passenger_wsgi():
    section("Passenger WSGI Entry Point")
    wsgi = ROOT / "passenger_wsgi.py"
    if not wsgi.exists():
        fail("passenger_wsgi.py not found at project root")
        return
    content = wsgi.read_text(encoding="utf-8", errors="replace")
    checks = [
        ("a2wsgi",           "imports a2wsgi"),
        ("ASGIMiddleware",   "uses ASGIMiddleware"),
        ("app.main",         "imports from app.main"),
        ("load_dotenv",      "loads .env"),
        ("application =",   "defines 'application' entry point"),
    ]
    for needle, label in checks:
        if needle in content:
            ok(f"passenger_wsgi.py {label}")
        else:
            fail(f"passenger_wsgi.py missing: {label}")

def check_git_tags():
    section("Version Tags")
    tags = subprocess.run(["git", "tag", "--sort=-version:refname"],
                          capture_output=True, text=True, cwd=ROOT).stdout.strip().splitlines()
    if tags:
        ok(f"Latest tag: {tags[0]}")
        if len(tags) > 1:
            ok(f"Previous tag: {tags[1]} (rollback target)")
        print(f"    All tags: {', '.join(tags[:8])}")
    else:
        warn("No version tags yet — run tools/release.bat to create v1.0")

# ══════════════════════════════════════════════════════════════════════════════
# SSH SERVER CHECKS
# ══════════════════════════════════════════════════════════════════════════════

def _ssh_key_args(cfg):
    """Return [-i, keypath] if ssh_key_path is set in deploy_config, else []."""
    key = cfg.get("server", {}).get("ssh_key_path", "").strip()
    if key:
        import os
        expanded = os.path.expanduser(key)
        if os.path.isfile(expanded):
            return ["-i", expanded]
        # Key path configured but file missing — warn but continue
        print(f"    Note: ssh_key_path '{key}' not found on disk — trying default keys")
    return []


def ssh_run(cfg, command):
    """Run a command on the server via SSH and return (stdout, stderr, returncode)."""
    server  = cfg["server"]
    ssh_cmd = (
        ["ssh"]
        + _ssh_key_args(cfg)
        + [
            "-p", str(server["ssh_port"]),
            "-o", "ConnectTimeout=10",
            "-o", "StrictHostKeyChecking=no",
            "-o", "BatchMode=yes",
            f"{server['ssh_user']}@{server['host']}",
            command,
        ]
    )
    result = subprocess.run(ssh_cmd, capture_output=True, text=True)
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def _diagnose_ssh_error(stderr: str, host: str, port: int) -> str:
    """Return a human-readable fix hint based on the SSH error text."""
    s = stderr.lower()
    if "connection refused" in s:
        return f"Port {port} is blocked or SSH daemon not running — contact your host"
    if "connection closed" in s or "disconnected" in s:
        return (
            "Server closed the connection — SSH key is probably not set up.\n"
            "    Fix:\n"
            "      1. In cPanel go to  Security > SSH Access > Manage Keys\n"
            "      2. Generate a new key (or import your existing public key)\n"
            "      3. Click Authorise next to the key\n"
            "      4. Download the private key (.pem) and save it locally\n"
            "      5. Add  \"ssh_key_path\": \"C:/Users/YOU/.ssh/cpanel_key.pem\"\n"
            "         to the \"server\" block in deploy_config.json"
        )
    if "timeout" in s or "timed out" in s:
        return "Connection timed out — firewall may be blocking port " + str(port)
    if "permission denied" in s:
        return (
            "Permission denied — key auth failed.\n"
            "    Fix: Check the key in deploy_config.json ssh_key_path matches\n"
            "         the key Authorised in cPanel > SSH Access > Manage Keys"
        )
    if "host key" in s:
        return "Host key changed — run: ssh-keygen -R " + host
    return "Check SSH key, IP ban (wait 30 min), or use cPanel Terminal"


def check_server(cfg):
    section("Server — SSH Verification")
    server = cfg["server"]

    # Test SSH connectivity
    stdout, stderr, rc = ssh_run(cfg, "echo OK")
    if rc != 0:
        hint = _diagnose_ssh_error(stderr, server["host"], server["ssh_port"])
        fail(f"SSH connection failed to {server['host']}:{server['ssh_port']}", hint)
        if stderr:
            print(f"    Raw error: {stderr[:200]}")
        return False
    ok(f"SSH connected to {server['host']}")

    # Check required server files
    for filepath in cfg["required_server_files"]:
        stdout, _, rc = ssh_run(cfg, f"test -f {filepath} && echo EXISTS || echo MISSING")
        if "EXISTS" in stdout:
            ok(f"Server file exists: {filepath.split('/')[-1]}")
        else:
            fail(f"Server file MISSING: {filepath}",
                 f"Upload or create: {filepath}")

    # Check .env has DATABASE_URL
    stdout, _, rc = ssh_run(cfg, f"grep -c 'DATABASE_URL' {server['env_file']} 2>/dev/null || echo 0")
    if stdout.strip() != "0":
        ok(".env on server contains DATABASE_URL")
    else:
        fail(".env on server missing DATABASE_URL",
             f"Create {server['env_file']} with correct MySQL connection string")

    # Check .htaccess has correct app root
    htaccess_path = server["htaccess"]
    stdout, _, _ = ssh_run(cfg, f"grep 'PassengerAppRoot' {htaccess_path} 2>/dev/null")
    if "icecoldgrp" in stdout:
        ok(f"PassengerAppRoot correctly set to icecoldgrp")
    else:
        fail("PassengerAppRoot may be misconfigured in .htaccess",
             "Check cPanel → Setup Python App → Application Root = icecoldgrp")

    # Check virtualenv pip exists
    pip = server["virtualenv_pip"]
    stdout, _, rc = ssh_run(cfg, f"test -f {pip} && echo EXISTS || echo MISSING")
    if "EXISTS" in stdout:
        ok(f"Virtualenv pip found")
    else:
        fail("Virtualenv pip not found",
             f"Recreate virtualenv in cPanel → Setup Python App")

    # Check a2wsgi is installed on server
    python = server["virtualenv_python"]
    stdout, _, rc = ssh_run(cfg, f"{python} -c \"import a2wsgi; print('OK')\" 2>/dev/null || echo MISSING")
    if "OK" in stdout:
        ok("a2wsgi installed on server")
    else:
        fail("a2wsgi not installed on server",
             f"Run: {server['virtualenv_pip']} install a2wsgi")

    return True

# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════════

def print_summary():
    section("Summary")
    fails  = [r for r in results if r[0] == "fail"]
    warns  = [r for r in results if r[0] == "warn"]
    passes = [r for r in results if r[0] == "ok"]

    print(f"  {green('✓')} {len(passes)} passed")
    if warns:
        print(f"  {yellow('⚠')} {len(warns)} warning(s)")
    if fails:
        print(f"  {red('✗')} {len(fails)} failed\n")
        print(red("  ✗ PRE-DEPLOY CHECK FAILED — fix the issues above before releasing."))
        return False
    elif warns:
        print(f"\n{yellow('  ⚠ Checks passed with warnings — review before releasing.')}")
        return True
    else:
        print(f"\n{green('  ✓ All checks passed — safe to release.')}")
        return True

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Pre-deploy check for IceCold Costing System")
    parser.add_argument("--skip-ssh", action="store_true",
                        help="Skip SSH server checks (use if SSH is blocked)")
    args = parser.parse_args()

    print(bold(cyan("\n╔══════════════════════════════════════════════════╗")))
    print(bold(cyan(  "║   IceCold GRP — Pre-Deploy Check                ║")))
    print(bold(cyan(  "╚══════════════════════════════════════════════════╝")))

    cfg = load_config()

    # Local checks — always run
    check_git_clean()
    check_no_secrets_in_git()
    check_requirements()
    check_key_files()
    check_passenger_wsgi()
    check_git_tags()

    # Server checks — SSH required
    if args.skip_ssh:
        section("Server — SSH Verification")
        warn("SSH skipped — deployment uses GitHub push + cPanel auto-deploy (no SSH needed)")
        print(f"    {cyan('Tip:')} Use cPanel Terminal at https://da25.host-ww.net:2083 for manual server checks")
    else:
        check_server(cfg)

    passed = print_summary()
    sys.exit(0 if passed else 1)

if __name__ == "__main__":
    main()
