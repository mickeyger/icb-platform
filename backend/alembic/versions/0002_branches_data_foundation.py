"""branches_data_foundation

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-02

Multi-branch DATA foundation (WO v4.12 step 4). The `branches` table and the
nullable `branch_id` FK columns are materialised by the 0001 baseline (which
runs create_all over the models, now including the Branch model + branch_id
columns). This migration establishes the *data*: it seeds the three operating
branches (JHB, CPT, CEN) and backfills every existing operational row to JHB so
no record is left branch-less once the columns are live.

On a fresh local dev database the backfill UPDATEs are no-ops (the operational
tables are empty); they matter when this chain is applied to a populated
database in a later data migration. No branch UI ships in Phase 1 (that is
Phase 2) — this is purely the schema + seed foundation.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Operational tables that carry a nullable branch_id (see app/database.py).
_BRANCHED_TABLES = (
    "customers",
    "calculations",
    "bom_snapshots",
    "configurator_snapshots",
    "configurator_drafts",
)

# (code, display name) — JHB is the default branch (DEFAULT_BRANCH_CODE).
_BRANCHES = (
    ("JHB", "Johannesburg"),
    ("CPT", "Cape Town"),
    ("CEN", "Central"),
)


def upgrade() -> None:
    bind = op.get_bind()
    # 1. Seed the three branches (idempotent on the unique code).
    for code, name in _BRANCHES:
        bind.execute(
            sa.text(
                "INSERT INTO branches (code, name, is_active, created_at) "
                "VALUES (:code, :name, true, NOW()) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "name": name},
        )
    # 2. Backfill existing operational rows to the default branch (JHB).
    jhb_id = bind.execute(
        sa.text("SELECT id FROM branches WHERE code = 'JHB'")
    ).scalar_one()
    for table in _BRANCHED_TABLES:
        bind.execute(
            sa.text(f"UPDATE {table} SET branch_id = :bid WHERE branch_id IS NULL"),
            {"bid": jhb_id},
        )


def downgrade() -> None:
    bind = op.get_bind()
    # Null out the backfilled FKs, then remove the seeded branches.
    for table in _BRANCHED_TABLES:
        bind.execute(sa.text(f"UPDATE {table} SET branch_id = NULL"))
    bind.execute(sa.text("DELETE FROM branches WHERE code IN ('JHB', 'CPT', 'CEN')"))
