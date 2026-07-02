"""WO v1.39.2 — assembly_bays build progress (Migration 0031).

Revision ID: 0031
Revises: 0030
Create Date: 2026-07-01

NOTE — originally cut as 0030, RENUMBERED to 0031: the parallel v1.39.3 backport (#67) landed its own
0030 (icb_costings.users.email) on backport/v1.39-base first. Both effects are already live on the
shared icb DB (users.email + assembly_bays.build_stage/pct); this migration is inspector-guarded, so a
deployer at 0030 runs it as a no-op that simply stamps 0031 — no manual DB surgery. Chain is now
0029 → 0030 (users.email) → 0031 (assembly_bays build progress), single head.

Adds two additive, defaulted columns to icb_mes.assembly_bays for the Pre-Assembly build-progress
model (v1.39.2 Phase 2). A body builds inside a bay while it holds panels (pre_assembly); these two
columns carry that build forward-only and reset when the bay empties:

  - build_stage         VARCHAR(16), NULLABLE, default NULL — the body's forward-only stage.
                        NULL = no body / EMPTY bay; otherwise one of
                        'entry' | 'pre_assembly' | 'stage_2' | 'stage_3' | 'merge'.
  - build_progress_pct  INTEGER, NOT NULL, server_default '0' — 0..100, derived from the stage.
                        Guarded by a DB CHECK (0..100) — cheap defense-in-depth (BA-ratified):
                        a stray write of e.g. 150 fails loudly at the DB, not silently in the UI.

The stage VOCABULARY (ENTRY/PRE_ASSEMBLY/STAGE_2/STAGE_3/MERGE) is enforced at the app layer by the
advance-stage chokepoint (Phase 3, forward-only) — NO DB CHECK on build_stage, matching the existing
"bay state is app-derived, not DB-constrained" pattern, so future stage additions need no migration.
The 5 existing bays backfill to build_stage=NULL, build_progress_pct=0 via the column defaults.

Inspector-guarded (columns + CHECK) → idempotent on re-run; purely additive ALTER; up→down→up
round-trips clean (mirrors the proven 0026 pattern).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision: str = "0031"
down_revision: Union[str, Sequence[str], None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MES = "icb_mes"
CK_PROGRESS = "assembly_bays_build_progress_pct_range"


def _cols(bind, table, schema) -> set:
    return {c["name"] for c in sa_inspect(bind).get_columns(table, schema=schema)}


def _checks(bind, table, schema) -> set:
    return {c["name"] for c in sa_inspect(bind).get_check_constraints(table, schema=schema)}


def upgrade() -> None:
    bind = op.get_bind()
    cols = _cols(bind, "assembly_bays", MES)
    if "build_stage" not in cols:
        op.add_column("assembly_bays",
                      sa.Column("build_stage", sa.String(length=16), nullable=True), schema=MES)
    if "build_progress_pct" not in cols:
        op.add_column("assembly_bays",
                      sa.Column("build_progress_pct", sa.Integer(), nullable=False, server_default="0"),
                      schema=MES)
    # BA-ratified — cheap defense-in-depth: reject any progress write outside 0..100 at the DB.
    if CK_PROGRESS not in _checks(bind, "assembly_bays", MES):
        op.create_check_constraint(
            CK_PROGRESS, "assembly_bays",
            "build_progress_pct BETWEEN 0 AND 100", schema=MES,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if CK_PROGRESS in _checks(bind, "assembly_bays", MES):
        op.drop_constraint(CK_PROGRESS, "assembly_bays", type_="check", schema=MES)
    cols = _cols(bind, "assembly_bays", MES)
    if "build_progress_pct" in cols:
        op.drop_column("assembly_bays", "build_progress_pct", schema=MES)
    if "build_stage" in cols:
        op.drop_column("assembly_bays", "build_stage", schema=MES)
