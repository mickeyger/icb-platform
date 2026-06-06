"""bom_rules + bom_rule_lookups + material_price_overrides — three icb_mes tables.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-06

WO v4.25 (Phase 3 §4.1) — the rules-engine substrate. Purely ADDITIVE: three new
standard-ORM icb_mes tables (`bom_rules`, `bom_rule_lookups`, `material_price_overrides`).
No destructive changes; no touch to icb_costings / icb_sap.

IDEMPOTENT (mirrors 0004/0006/0007): migration 0003 builds the icb_mes tables via
model-driven create_all, so on a FRESH DB it already creates these three (the models now
declare them); on a v4.13–v4.24 DB it does not. The per-table inspector guard converges
both paths and keeps the CI upgrade/downgrade/upgrade round-trip green. Standard ORM tables
(unlike icb_sap's raw DDL) → autogenerate-compatible (icb_mes is in env.py _RELEVANT_SCHEMAS).
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect as sa_inspect

revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_TABLES = ["bom_rules", "bom_rule_lookups", "material_price_overrides"]


def _new_table_objs():
    from app.database import Base
    import app.models.mes  # noqa: F401  (registers BomRule + BomRuleLookup + MaterialPriceOverride)
    return [Base.metadata.tables[f"icb_mes.{n}"] for n in _NEW_TABLES]


def _existing(bind) -> set:
    return set(sa_inspect(bind).get_table_names(schema="icb_mes"))


def upgrade() -> None:
    bind = op.get_bind()
    have = _existing(bind)
    missing = [t for t in _new_table_objs() if t.name not in have]
    if missing:
        from app.database import Base
        Base.metadata.create_all(bind=bind, tables=missing)


def downgrade() -> None:
    bind = op.get_bind()
    have = _existing(bind)
    present = [t for t in _new_table_objs() if t.name in have]
    if present:
        from app.database import Base
        Base.metadata.drop_all(bind=bind, tables=present)
