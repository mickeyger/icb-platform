"""WO v4.34.4 §3.2 — environment guard for the DB-mutating maintenance scripts.

A thin, settings-aware wrapper over ``app.db_guard`` for the command-line scripts in this package.
Every script that writes to the database calls in here at its entry point, so the destructive vector
that contaminated the shared dev DB in the 14-15 June session can never recur from a script run.

Three tiers, matched to the real blast radius of each script (see docs/scripting/environment_guard.md):

  * ``require_test_db``    — FULL-WIPE / RECONCILE ops (TRUNCATE-all, calc/job backfills). HARD-REFUSED
                             unless DATABASE_URL points at an isolated ``*_test`` DB. No override — these
                             must NEVER run against the shared dev DB. This is the v4.27 rule, in code.
  * ``confirm_if_shared_db`` — SCOPED-DESTRUCTIVE ops (delete-a-slice-then-reinsert, CASCADE re-imports,
                             in-place token rewrites). Allowed against the shared dev DB, but only after an
                             explicit confirmation, so they can't fire by accident.
  * ``announce_target``   — ADDITIVE / idempotent (insert-when-absent) seeds. Never blocks; just announces
                             the target DB (loudly when it's not a test DB).

Keyed on db-NAME, not hostname — dev/test/CI all share localhost (WO v4.34.4 §3.0). All three delegate the
name resolution to ``app.db_guard`` (the single source of truth, also used by the pytest session guard).
"""
import getpass
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Confirm-tier escape hatch for non-interactive contexts (does NOT apply to the hard-refuse tier).
_CONFIRM_ENV = "ICB_ALLOW_SHARED_DB_WRITE"

# WO v4.34.4 (BA ask, post-merge-review): every Tier-2 confirm that ALLOWS a scoped-destructive op
# against a NON-test DB is the residual risk surface (a fat-finger 'y' or a stale ICB_ALLOW_SHARED_DB_WRITE
# in the shell). Record each one. backend/scripts_audit.log is gitignored (*.log) — an operational trail,
# not a committed artifact.
_AUDIT_LOG = Path(__file__).resolve().parent.parent / "scripts_audit.log"


def _url():
    # Lazy: app/.env may only be importable after the calling script sets up sys.path.
    from app.config import settings
    return settings.DATABASE_URL


def _target() -> str:
    from app.db_guard import resolve_db_name, resolve_host
    url = _url()
    return f"host={resolve_host(url)} db={resolve_db_name(url)}"


def _audit_confirm(context: str, *, mode: str) -> None:
    """Append one tab-delimited line recording a Tier-2 confirm that allowed a scoped-destructive op
    against a non-test DB: timestamp, operator, script, args, the env-flag value, and the target.
    Best-effort — a logging failure NEVER blocks the operation (the gate is the confirm, not the log)."""
    try:
        try:
            user = getpass.getuser()
        except Exception:                                  # noqa: BLE001 — getuser can fail in odd shells
            user = "?"
        env = os.environ.get(_CONFIRM_ENV)
        line = (f"{datetime.now(timezone.utc).isoformat()}\tuser={user}\tscript={context}\tmode={mode}\t"
                f"{_CONFIRM_ENV}={env!r}\targv={sys.argv}\ttarget={_target()}\n")
        with _AUDIT_LOG.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception as exc:                               # noqa: BLE001 — audit logging must never block
        print(f"[env-guard] WARNING: could not write {_AUDIT_LOG.name}: {exc}")


def require_test_db(context: str) -> str:
    """Tier 1 — HARD gate for full-wipe / reconcile ops. Raises RuntimeError unless DATABASE_URL is a
    ``*_test`` DB. There is deliberately no override: these ops can never touch the shared dev DB."""
    from app.db_guard import assert_test_db
    name = assert_test_db(_url(), context=context)
    print(f"[env-guard] {context}: OK — isolated test DB ({_target()}).")
    return name


def confirm_if_shared_db(context: str, *, destroys: str) -> None:
    """Tier 2 — gate for scoped-destructive ops. On a ``*_test`` DB: proceed silently. On any non-test DB
    (the shared dev DB): require explicit confirmation — env ``ICB_ALLOW_SHARED_DB_WRITE=1`` or an
    interactive 'y'. Fails safe (refuses) when neither is available."""
    from app.db_guard import is_test_db
    if is_test_db(_url()):
        print(f"[env-guard] {context}: isolated test DB ({_target()}) — proceeding.")
        return
    banner = (f"[env-guard] ⚠ {context} targets the SHARED DEV DB ({_target()}).\n"
              f"            This will: {destroys}")
    if os.environ.get(_CONFIRM_ENV) == "1":
        print(f"{banner}\n            {_CONFIRM_ENV}=1 set — proceeding.")
        _audit_confirm(context, mode="env")
        return
    if sys.stdin is not None and sys.stdin.isatty():
        print(banner)
        ans = input("            Type 'y' to proceed against the shared dev DB: ").strip().lower()
        if ans == "y":
            _audit_confirm(context, mode="interactive")
            return
        raise RuntimeError(f"[env-guard] REFUSED: {context} was not confirmed against the shared dev DB.")
    raise RuntimeError(
        f"[env-guard] REFUSED: {context} would write to the shared dev DB ({_target()}) non-interactively. "
        f"Re-run against a *_test DB, or set {_CONFIRM_ENV}=1 to confirm a deliberate dev-DB run.")


def announce_target(context: str) -> None:
    """Tier 3 — announce-only gate for additive / idempotent seeds. Never blocks; warns when not a test DB."""
    from app.db_guard import is_test_db
    if is_test_db(_url()):
        print(f"[env-guard] {context}: isolated test DB ({_target()}).")
    else:
        print(f"[env-guard] {context}: writing to NON-TEST DB ({_target()}) — additive/idempotent, proceeding.")
