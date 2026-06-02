"""materials_buying_stores — add icb_mes.mes_materials, stock_positions, suppliers
and the po_suggestions.jobs_impacted column.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-02

WO v4.15 (Phase 2B-2). Purely ADDITIVE — three new tables + one column, no
destructive changes. The materials catalogue is self-contained in icb_mes
(ADR 0009): icb_costings.materials is empty in dev, lacks abc_class/dept/lead_days,
and uses non-matching demo codes; and no icb_costings.suppliers exists (verified
against information_schema). So these three are the system of record for the
Materials/Buying/Stores screens. No cross-schema FKs are added — reads MAY LEFT
JOIN icb_costings.materials ON sap_code for reconciliation only.

NOTE: the deferred drop of the 18 moved columns from icb_costings.calculations
(previously earmarked '0004') slides to a later revision (0005+), post-UAT — see
ADR 0005.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_TABLES = ["mes_materials", "stock_positions", "suppliers"]


def _new_table_objs():
    from app.database import Base
    import app.models.mes  # noqa: F401  (ensures the new models are registered)
    return [Base.metadata.tables[f"icb_mes.{n}"] for n in _NEW_TABLES]


def _has_jobs_impacted(bind) -> bool:
    from sqlalchemy import inspect as _inspect
    cols = [c["name"] for c in _inspect(bind).get_columns("po_suggestions", schema="icb_mes")]
    return "jobs_impacted" in cols


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Create the 3 new icb_mes tables (+ their indexes). Cycle-safe; no FKs.
    from app.database import Base
    Base.metadata.create_all(bind=bind, tables=_new_table_objs())

    # 2. jobs_impacted on po_suggestions (WO v4.15 Q3). IDEMPOTENT: migration 0003
    #    builds the icb_mes tables via model-driven create_all, so on a FRESH DB it
    #    already creates this column (the POSuggestion model now declares it); on a
    #    DB migrated at v4.13 (pre-column) it does not. Guard so both paths converge.
    if not _has_jobs_impacted(bind):
        op.add_column(
            "po_suggestions", sa.Column("jobs_impacted", JSONB(), nullable=True),
            schema="icb_mes",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_jobs_impacted(bind):
        op.drop_column("po_suggestions", "jobs_impacted", schema="icb_mes")
    from app.database import Base
    Base.metadata.drop_all(bind=bind, tables=_new_table_objs())
