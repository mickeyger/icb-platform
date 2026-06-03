"""planning_branch_roles — branch NOT NULL, permission seed, PR sequence, session_branches.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-02

WO v4.16 (Phase 2B-3). Parts:
  A. NOT NULL on production_jobs.branch_id + stock_counts.branch_id (pre-flight assert
     zero NULLs first; abort with a clear error otherwise — operator backfills).
  B. Seed the 15 MES permission keys + role grants into the costing-side
     icb_costings.permissions / role_permissions (idempotent ON CONFLICT).
  D. CREATE SEQUENCE icb_mes.pr_number_seq, initialised to max existing PR-N + 1.
  E. Create icb_mes.session_branches (active-branch-per-session).
(Part C = ADR 0005 doc update — not DDL.)

Additive + reversible. The deferred calculations column-drop slides to 0006+ (ADR 0005).
On a fresh DB, alembic runs before the seed, so the Part-A tables are empty and the
pre-flight passes; the seed then inserts non-NULL branch_id (WO v4.16 seed change).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (name, description) — 15 MES mutation permission keys (ADR 0010).
_PERMS = [
    ("production.accept", "Accept a calculation into production"),
    ("production.pre_job_card", "Send the pre-job card"),
    ("production.signoff_sales", "Sales pre-job sign-off"),
    ("production.signoff_production", "Production pre-job sign-off"),
    ("production.chassis_received", "Confirm chassis received"),
    ("planning.acknowledge", "Acknowledge a job on the Planning Board"),
    ("planning.schedule", "Schedule / move a job into a slot"),
    ("planning.unschedule", "Remove a job from a slot"),
    ("stores.count", "Record a stock cycle count"),
    ("stores.raise_discrepancy", "Raise a stock discrepancy to Buying"),
    ("buying.resolve_discrepancy", "Resolve a stock discrepancy"),
    ("buying.raise_pr", "Raise a single PR"),
    ("buying.defer_pr", "Defer a PO suggestion"),
    ("buying.override_supplier", "Override the suggested supplier"),
    ("buying.bulk_raise", "Bulk-raise PRs"),
]
# (role, permission_key) grants — admin stays a code-level wildcard (no rows).
_GRANTS = [
    ("sales", "production.accept"), ("sales", "production.pre_job_card"),
    ("sales", "production.signoff_sales"),
    ("production", "production.signoff_production"), ("production", "production.chassis_received"),
    ("production", "planning.acknowledge"),
    ("planner", "planning.acknowledge"), ("planner", "planning.schedule"),
    ("planner", "planning.unschedule"), ("planner", "production.chassis_received"),
    ("stores", "stores.count"), ("stores", "stores.raise_discrepancy"),
    ("buyer", "buying.raise_pr"), ("buyer", "buying.defer_pr"), ("buyer", "buying.resolve_discrepancy"),
    ("buyer_senior", "buying.raise_pr"), ("buyer_senior", "buying.defer_pr"),
    ("buyer_senior", "buying.resolve_discrepancy"), ("buyer_senior", "buying.override_supplier"),
    ("buyer_senior", "buying.bulk_raise"),
]


def _session_branch_table():
    from app.database import Base
    import app.models.mes  # noqa: F401  (registers SessionBranch)
    return Base.metadata.tables["icb_mes.session_branches"]


def upgrade() -> None:
    bind = op.get_bind()

    # ── Part A — NOT NULL with pre-flight assert ──────────────────────────────
    for tbl in ("production_jobs", "stock_counts"):
        n = bind.execute(sa.text(
            f"SELECT count(*) FROM icb_mes.{tbl} WHERE branch_id IS NULL")).scalar()
        if n:
            raise RuntimeError(
                f"0005 pre-flight: {n} NULL icb_mes.{tbl}.branch_id — backfill before migrating.")
    op.alter_column("production_jobs", "branch_id", nullable=False, schema="icb_mes")
    op.alter_column("stock_counts", "branch_id", nullable=False, schema="icb_mes")

    # ── Part B — permission keys + role grants (idempotent) ───────────────────
    for name, desc in _PERMS:
        d = desc.replace("'", "''")
        op.execute(
            f"INSERT INTO icb_costings.permissions (name, description, category) "
            f"VALUES ('{name}', '{d}', 'mes') ON CONFLICT (name) DO NOTHING")
    for role, key in _GRANTS:
        op.execute(
            f"INSERT INTO icb_costings.role_permissions (role, permission_id) "
            f"SELECT '{role}', p.id FROM icb_costings.permissions p WHERE p.name = '{key}' "
            f"ON CONFLICT (role, permission_id) DO NOTHING")

    # ── Part D — PR sequence (init = max existing PR-N + 1) ───────────────────
    mx = bind.execute(sa.text(
        "SELECT COALESCE(MAX((substring(pr_number from 'PR-([0-9]+)'))::int), 0) "
        "FROM icb_mes.po_suggestions WHERE pr_number ~ '^PR-[0-9]+$'")).scalar() or 0
    op.execute(f"CREATE SEQUENCE IF NOT EXISTS icb_mes.pr_number_seq START WITH {mx + 1} MINVALUE 1")

    # ── Part E — session_branches table ───────────────────────────────────────
    from app.database import Base
    Base.metadata.create_all(bind=bind, tables=[_session_branch_table()])


def downgrade() -> None:
    bind = op.get_bind()
    from app.database import Base
    Base.metadata.drop_all(bind=bind, tables=[_session_branch_table()])
    op.execute("DROP SEQUENCE IF EXISTS icb_mes.pr_number_seq")
    names = ", ".join(f"'{n}'" for n, _ in _PERMS)
    op.execute(
        f"DELETE FROM icb_costings.role_permissions WHERE permission_id IN "
        f"(SELECT id FROM icb_costings.permissions WHERE name IN ({names}))")
    op.execute(f"DELETE FROM icb_costings.permissions WHERE name IN ({names})")
    op.alter_column("stock_counts", "branch_id", nullable=True, schema="icb_mes")
    op.alter_column("production_jobs", "branch_id", nullable=True, schema="icb_mes")
