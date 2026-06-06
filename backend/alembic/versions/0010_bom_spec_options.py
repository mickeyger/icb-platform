"""bom_spec_options + UNIQUE hardening — DDM/early-binding (WO v4.26, Phase 3 §4.1).

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-06

Additive: new `icb_mes.bom_spec_options` (the DDM dropdown catalogue / early-binding data
model) + a UNIQUE constraint on `bom_rules (body_type, section, panel, output_field)` (the
v4.25 dup-seed-guard carry-forward, §0.5). No destructive ops.

IDEMPOTENT (mirrors 0007/0009): 0003's model-driven create_all builds the icb_mes tables, so on
a FRESH DB it already creates `bom_spec_options` (the model now declares it) AND creates
`bom_rules` WITH the new UNIQUE (the model now declares it). Both adds therefore guard on
existence (table-name / constraint-name inspector checks), keeping the CI upgrade→downgrade→
upgrade round-trip green.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision: str = '0010'
down_revision: Union[str, Sequence[str], None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_TABLES = ["bom_spec_options"]
_BR_UQ = "uq_bom_rules_body_section_panel_field"


def _new_table_objs():
    from app.database import Base
    import app.models.mes  # noqa: F401  (registers BomSpecOption + the BomRule UNIQUE)
    return [Base.metadata.tables[f"icb_mes.{n}"] for n in _NEW_TABLES]


def _tables(bind) -> set:
    return set(sa_inspect(bind).get_table_names(schema="icb_mes"))


def _bom_rules_uqs(bind) -> set:
    return {c["name"] for c in sa_inspect(bind).get_unique_constraints("bom_rules", schema="icb_mes")}


def _lookup_cols(bind) -> set:
    return {c["name"] for c in sa_inspect(bind).get_columns("bom_rule_lookups", schema="icb_mes")}


def upgrade() -> None:
    bind = op.get_bind()
    have = _tables(bind)
    missing = [t for t in _new_table_objs() if t.name not in have]
    if missing:
        from app.database import Base
        Base.metadata.create_all(bind=bind, tables=missing)
    if "bom_rules" in have and _BR_UQ not in _bom_rules_uqs(bind):
        op.create_unique_constraint(
            _BR_UQ, "bom_rules", ["body_type", "section", "panel", "output_field"], schema="icb_mes")
    # WO v4.26 §0.4 — audit-by columns on bom_rule_lookups (guarded: 0003's create_all already
    # adds them on a fresh DB since the model now declares them).
    if "bom_rule_lookups" in have:
        cols = _lookup_cols(bind)
        for col in ("created_by", "updated_by"):
            if col not in cols:
                op.add_column("bom_rule_lookups", sa.Column(col, sa.String(128)), schema="icb_mes")


def downgrade() -> None:
    bind = op.get_bind()
    if "bom_rules" in _tables(bind) and _BR_UQ in _bom_rules_uqs(bind):
        op.drop_constraint(_BR_UQ, "bom_rules", schema="icb_mes", type_="unique")
    if "bom_rule_lookups" in _tables(bind):
        cols = _lookup_cols(bind)
        for col in ("created_by", "updated_by"):
            if col in cols:
                op.drop_column("bom_rule_lookups", col, schema="icb_mes")
    have = _tables(bind)
    present = [t for t in _new_table_objs() if t.name in have]
    if present:
        from app.database import Base
        Base.metadata.drop_all(bind=bind, tables=present)
