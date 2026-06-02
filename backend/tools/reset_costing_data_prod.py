"""
tools/reset_costing_data_prod.py

PRODUCTION equivalent of reset_costing_data.py — wipes costing data from the
production MySQL database while keeping users/customers/themes/admin_settings.

KEEPS:
    users, customers, themes, admin_settings
WIPES:
    bill_of_materials, trailer_ratios, price_history, calculations,
    pdf_templates, formulas, materials, material_categories,
    bom_sections, trailer_types

Tables are emptied in FK-dependency order. AUTO_INCREMENT counters are
reset so fresh imports start from id=1.

Connection
----------
    Reads connection string from (in order):
      1) --url "<sqlalchemy url>" command-line arg
      2) PROD_DATABASE_URL env var
      3) MYSQL_URL env var (from .env)
    .env in the project root is auto-loaded.

Usage
-----
    python tools/reset_costing_data_prod.py                # interactive
    python tools/reset_costing_data_prod.py --yes          # skip confirm
    python tools/reset_costing_data_prod.py --url "mysql+pymysql://user:pass@host:3306/db"
    python tools/reset_costing_data_prod.py --dry-run      # report only

WARNING: this is destructive. Take a DB backup in cPanel BEFORE running.
"""

from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Best-effort .env load (without requiring python-dotenv at import time)
_env_file = PROJECT_ROOT / ".env"
if _env_file.exists():
    for line in _env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

WIPE_ORDER = [
    "bill_of_materials",
    "trailer_ratios",
    "price_history",
    "calculations",
    "pdf_templates",
    "formulas",
    "materials",
    "material_categories",
    "bom_sections",
    "trailer_types",
]

KEEP = ["users", "customers", "themes", "admin_settings"]


def redact(url: str) -> str:
    import re
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="SQLAlchemy URL (overrides env)")
    ap.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
    ap.add_argument("--dry-run", action="store_true", help="Report counts only, no DELETE")
    args = ap.parse_args()

    url = (args.url
           or os.environ.get("PROD_DATABASE_URL")
           or os.environ.get("MYSQL_URL")
           or "").strip()
    if not url:
        print("ERROR: no DB URL. Pass --url or set PROD_DATABASE_URL / MYSQL_URL.")
        return 1

    if "sqlite" in url.lower():
        print("ERROR: this script targets MySQL/prod. Use reset_costing_data.py for SQLite.")
        return 1

    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        print("ERROR: SQLAlchemy not installed in this Python.")
        return 1

    print(f"Target DB: {redact(url)}")
    print()

    try:
        engine = create_engine(url, connect_args={"connect_timeout": 10})
    except Exception as e:
        print(f"ERROR creating engine: {e}")
        return 1

    with engine.connect() as conn:
        print("Pre-wipe row counts:")
        existing = []
        for t in WIPE_ORDER:
            try:
                n = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
                print(f"  {t:25s} {n}")
                existing.append(t)
            except Exception as e:
                print(f"  {t:25s} (skip: {type(e).__name__})")

        print()
        print("Will keep (unchanged):")
        for t in KEEP:
            try:
                n = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
                print(f"  {t:25s} {n}")
            except Exception:
                pass

        if args.dry_run:
            print("\n[dry-run] no changes made.")
            return 0

        if not args.yes:
            print()
            print("*** THIS WILL DELETE PRODUCTION DATA. ***")
            print(f"   Target: {redact(url)}")
            ans = input("Type DELETE to proceed: ").strip()
            if ans != "DELETE":
                print("Aborted.")
                return 2

        print()
        print("Wiping...")
        try:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            for t in existing:
                try:
                    conn.execute(text(f"DELETE FROM {t}"))
                    try:
                        conn.execute(text(f"ALTER TABLE {t} AUTO_INCREMENT = 1"))
                    except Exception:
                        pass
                    print(f"  wiped {t}")
                except Exception as e:
                    print(f"  ! {t}: {e}")
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
            conn.commit()
        except Exception as e:
            print(f"ERROR during wipe: {e}")
            return 1

        print()
        print("Post-wipe row counts:")
        for t in existing:
            try:
                n = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
                print(f"  {t:25s} {n}")
            except Exception:
                pass

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
