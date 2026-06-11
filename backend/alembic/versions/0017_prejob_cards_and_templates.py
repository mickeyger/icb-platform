"""Pre-Job Card tables + sales-rep quote capture + chassis body gap (WO v4.33 §3.1, ADR 0020).

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-11

Phase 3 §4.7 — the Pre-Job Card workflow's storage, per the §0 locks:

  A. NEW icb_mes.prejob_templates (Nadie's 23-template library; §0.5 JSONB sections; imported
     is_active=False by the §3.2 script — review-and-normalize, §0.15) and
     NEW icb_mes.prejob_cards (the 3-role workflow instance: Internal Sales creates → Sales Rep
     + Planner check-sign → pre_job_confirmed; §0.14 reject returns to draft).
     Cross-schema FKs (calculation_id -> icb_costings.calculations RESTRICT; created_by/
     sales_rep/planner _user_id -> icb_costings.users SET NULL) are NOT on the models — created
     here, guarded by name (the 0003/0012/0016 idiom).
  B. icb_costings.calculations gains sales_rep_user_id (nullable FK -> users) — §0.13 quote-time
     capture; defaults the modal's Sales Rep dropdown. ADD COLUMN IF NOT EXISTS (0015 idiom; the
     column is also on the legacy model so fresh-DB create_all builds it WITH its FK).
  C. icb_mes.chassis_records gains body_gap_mm (nullable int) — §0.8: the customer's specified
     gap; Simeon enters/verifies during VCL (BA-approved §3.0 concern-5 widening).
  D. Permissions: prejob.create + prejob.signoff_sales -> sales; prejob.signoff_planner ->
     planner (admin = code-level wildcard; §0.3 — production deliberately has NO grant).

IDEMPOTENT (mirrors 0012/0016): 0003's model-driven create_all builds the two icb_mes tables +
the model-declared columns on a FRESH DB, so every add guards on existence; FKs guard by name;
seeds are ON CONFLICT DO NOTHING. Downgrade removes grants/perms, drops the prejob FKs then
tables, and drops the two added columns (icb-owned post-pivot — safe to drop, unlike 0015's
faje-shared columns).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision: str = '0017'
down_revision: Union[str, Sequence[str], None] = '0016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_TABLES = ["prejob_templates", "prejob_cards"]

# (constraint name, source col, referent table, ondelete) — all on icb_mes.prejob_cards.
_CARD_FKS = [
    ("fk_prejob_cards_calculation", "calculation_id", "calculations", "RESTRICT"),
    ("fk_prejob_cards_created_by", "created_by_user_id", "users", "SET NULL"),
    ("fk_prejob_cards_sales_rep", "sales_rep_user_id", "users", "SET NULL"),
    ("fk_prejob_cards_planner", "planner_user_id", "users", "SET NULL"),
]

_CALC_FK = "fk_calculations_sales_rep_user"

_PERMS = [
    ("prejob.create", "Create + submit Pre-Job Cards (Internal Sales)"),
    ("prejob.signoff_sales", "Sales Rep check sign-off on a Pre-Job Card"),
    ("prejob.signoff_planner", "Planner check sign-off on a Pre-Job Card"),
]
_GRANTS = [
    ("sales", "prejob.create"),
    ("sales", "prejob.signoff_sales"),
    ("planner", "prejob.signoff_planner"),
]


def _new_table_objs():
    from app.database import Base
    import app.models.mes  # noqa: F401  (registers PrejobTemplate/PrejobCard)
    return [Base.metadata.tables[f"icb_mes.{n}"] for n in _NEW_TABLES]


def _mes_tables(bind) -> set:
    return set(sa_inspect(bind).get_table_names(schema="icb_mes"))


def _cols(bind, table, schema) -> set:
    return {c["name"] for c in sa_inspect(bind).get_columns(table, schema=schema)}


def _fks(bind, table, schema) -> set:
    return {fk["name"] for fk in sa_inspect(bind).get_foreign_keys(table, schema=schema)}


def upgrade() -> None:
    bind = op.get_bind()

    # ── A. prejob tables (guard: 0003 create_all already builds them on a fresh DB) ──
    have = _mes_tables(bind)
    missing = [t for t in _new_table_objs() if t.name not in have]
    if missing:
        from app.database import Base
        Base.metadata.create_all(bind=bind, tables=missing)
    for name, col, referent, ondelete in _CARD_FKS:
        if name not in _fks(bind, "prejob_cards", "icb_mes"):
            op.create_foreign_key(
                name, "prejob_cards", referent, [col], ["id"],
                source_schema="icb_mes", referent_schema="icb_costings", ondelete=ondelete,
            )

    # ── B. calculations.sales_rep_user_id (§0.13; 0015 ADD-IF-NOT-EXISTS idiom + named FK) ──
    op.execute("ALTER TABLE icb_costings.calculations "
               "ADD COLUMN IF NOT EXISTS sales_rep_user_id INTEGER")
    if _CALC_FK not in _fks(bind, "calculations", "icb_costings"):
        op.create_foreign_key(
            _CALC_FK, "calculations", "users", ["sales_rep_user_id"], ["id"],
            source_schema="icb_costings", referent_schema="icb_costings", ondelete="SET NULL",
        )

    # ── C. chassis_records.body_gap_mm (§0.8; model-declared → guard for fresh DBs) ──
    if "body_gap_mm" not in _cols(bind, "chassis_records", "icb_mes"):
        op.add_column("chassis_records", sa.Column("body_gap_mm", sa.Integer(), nullable=True),
                      schema="icb_mes")

    # ── D. permissions + grants (idempotent; 0013/0016 precedent) ──
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


def downgrade() -> None:
    bind = op.get_bind()

    # D. grants + permission keys.
    names = ", ".join(f"'{n}'" for n, _ in _PERMS)
    op.execute(
        f"DELETE FROM icb_costings.role_permissions WHERE permission_id IN "
        f"(SELECT id FROM icb_costings.permissions WHERE name IN ({names}))")
    op.execute(f"DELETE FROM icb_costings.permissions WHERE name IN ({names})")

    # C. chassis_records.body_gap_mm.
    if "chassis_records" in _mes_tables(bind) and \
            "body_gap_mm" in _cols(bind, "chassis_records", "icb_mes"):
        op.drop_column("chassis_records", "body_gap_mm", schema="icb_mes")

    # B. calculations FK + column (icb-owned post-pivot — safe to drop, unlike 0015).
    if _CALC_FK in _fks(bind, "calculations", "icb_costings"):
        op.drop_constraint(_CALC_FK, "calculations", schema="icb_costings", type_="foreignkey")
    op.execute("ALTER TABLE icb_costings.calculations DROP COLUMN IF EXISTS sales_rep_user_id")

    # A. prejob FKs (by name) then tables (cards before templates — template FK).
    have = _mes_tables(bind)
    if "prejob_cards" in have:
        for name, *_ in _CARD_FKS:
            if name in _fks(bind, "prejob_cards", "icb_mes"):
                op.drop_constraint(name, "prejob_cards", schema="icb_mes", type_="foreignkey")
    present = [t for t in _new_table_objs() if t.name in have]
    if present:
        from app.database import Base
        Base.metadata.drop_all(bind=bind, tables=present)
