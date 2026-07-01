"""v1.39.3 backport — seed the three Phase-1 primary users with real addresses + operational roles.

Phase-1 go-live (6-8 Jul 2026) needs real email addresses on the users who sign / are CC'd on a
Pre-Job Card check, so the "Submit for Check" transition can auto-send (migration 0030 added
users.email). This upserts BY USERNAME — an existing persona is UPDATED in place (email + role),
never duplicated; an absent one is created with a default password to reset on first login.

Targets (icb_costings.users):
    Burt    role=sales    burt@icecoldgrp.co.za      → the Sales signer  (Sales-Rep dropdown)
    Deon    role=planner  deon@icecoldgrp.co.za      → a Planner signer  (Planner dropdown)
    Simeon  role=planner  planner@icecoldgrp.co.za   → Planner-eligible + auto-CC (role-based addr)

Note on roles: the Sales-Rep dropdown lists ONLY role='sales' (admins excluded); the Planner
dropdown lists ('planner','admin'). Burt/Deon were seeded as 'admin' in earlier demo data — this
sets their Phase-1 operational roles so Burt appears in the Sales dropdown and both Deon+Simeon in
the Planner dropdown. Re-runnable: converges to the target state and reports what changed.

    python -m scripts.seed_phase1_users            # apply (Tier-2 confirm on a shared DB)
    python -m scripts.seed_phase1_users --dry-run  # report the diff without writing
"""
from __future__ import annotations

import argparse
import sys

# username -> (role, email). Domain is icecoldgrp.co.za (NOT icecoldbodies.co.za).
_TARGETS = {
    "Burt":   ("sales",   "burt@icecoldgrp.co.za"),
    "Deon":   ("planner", "deon@icecoldgrp.co.za"),
    "Simeon": ("planner", "planner@icecoldgrp.co.za"),
}
# Default password for a NEWLY-created persona (only Simeon, typically) — reset on first login.
_DEFAULT_PASSWORD = "ChangeMe123!"


def seed(dry_run: bool = False) -> dict:
    from app.database import SessionLocal, User
    from app.deps import pwd_context

    created, updated, unchanged, changes = 0, 0, 0, []
    with SessionLocal() as db:
        for username, (role, email) in _TARGETS.items():
            u = db.query(User).filter_by(username=username).first()
            if u is None:
                changes.append(f"CREATE {username}: role={role}, email={email} (default password)")
                if not dry_run:
                    db.add(User(username=username, role=role, email=email,
                                password_hash=pwd_context.hash(_DEFAULT_PASSWORD)))
                created += 1
                continue
            diffs = []
            if (u.email or "") != email:
                diffs.append(f"email {u.email!r} -> {email!r}")
            if (u.role or "") != role:
                diffs.append(f"role {u.role!r} -> {role!r}")
            if diffs:
                changes.append(f"UPDATE {username}: " + "; ".join(diffs))
                if not dry_run:
                    u.email = email
                    u.role = role
                updated += 1
            else:
                unchanged += 1
        if not dry_run:
            db.commit()
    return {"created": created, "updated": updated, "unchanged": unchanged,
            "dry_run": dry_run, "changes": changes}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Seed/upsert the 3 Phase-1 primary users.")
    ap.add_argument("--dry-run", action="store_true", help="report the diff without writing")
    args = ap.parse_args()

    if not args.dry_run:
        # Tier-2: this MUTATES existing user rows (Burt/Deon roles) — confirm before a shared-DB run.
        from scripts._environment_guard import confirm_if_shared_db
        confirm_if_shared_db("seed_phase1_users",
                             destroys="update Burt/Deon roles + set email on Burt/Deon/Simeon")

    result = seed(dry_run=args.dry_run)
    for line in result["changes"]:
        print("  " + line)
    print(result)
    sys.exit(0)
