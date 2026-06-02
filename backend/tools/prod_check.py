"""
Standalone production diagnostic script.

Run on prod from the cPanel terminal when the web app is misbehaving:

    cd ~/icecoldgrp
    python tools/prod_check.py

Imports the FastAPI app, checks DB connectivity, lists registered routes,
and prints recent crash log entries — all without needing a live HTTP server.
Useful when /debug/health itself won't load.
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _heading(t: str) -> None:
    print()
    print("=" * 70)
    print(t)
    print("=" * 70)


def main() -> int:
    rc = 0

    _heading("Environment")
    print(f"cwd:      {os.getcwd()}")
    print(f"python:   {sys.version.split()[0]}")
    print(f"root:     {ROOT}")
    print(f"DATABASE_URL set: {bool(os.getenv('DATABASE_URL'))}")

    _heading("Import app")
    try:
        from app.main import app  # noqa: F401
        from app.database import SessionLocal, User, CalculationRecord
        print("OK — FastAPI app imported")
    except Exception:
        print("FAILED to import app:")
        traceback.print_exc()
        return 2

    _heading("Database")
    try:
        from sqlalchemy import text
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            users = db.query(User).count()
            recs = db.query(CalculationRecord).count()
            print(f"connected: yes")
            print(f"users:     {users}")
            print(f"records:   {recs}")
    except Exception:
        print("DB FAILED:")
        traceback.print_exc()
        rc = 3

    _heading("Routes")
    try:
        from app.main import app
        routes = sorted(
            (
                f"{','.join(sorted(r.methods or [])):<10} {r.path}"
                for r in app.routes
                if hasattr(r, "methods") and hasattr(r, "path")
            )
        )
        print(f"total: {len(routes)}")
        for r in routes:
            print(f"  {r}")
    except Exception:
        print("Route enumeration failed:")
        traceback.print_exc()
        rc = 4

    _heading("Recent crashes (logs/crash.log)")
    crash_log = ROOT / "logs" / "crash.log"
    if crash_log.exists():
        try:
            data = crash_log.read_text(encoding="utf-8", errors="replace").splitlines()
            tail = data[-80:] if len(data) > 80 else data
            for line in tail:
                print(line)
            if not tail:
                print("(empty)")
        except Exception:
            traceback.print_exc()
    else:
        print(f"(no crash log at {crash_log})")

    _heading("Done")
    print("rc =", rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
