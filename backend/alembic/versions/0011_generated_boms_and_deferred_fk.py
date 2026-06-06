"""generated_boms + bom_lines persistence + production_jobs BOM cols + deferred demand→OITM FK
(WO v4.27, Phase 3 §4.1 close-out).

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-06

Additive:
  * NEW icb_mes.generated_boms — versioned, immutable BOM snapshot per production job
    (partial-unique `current` = at most one active version per job).
  * NEW icb_mes.bom_lines — the lines of a snapshot.
  * production_jobs.current_bom_id (FK -> generated_boms, ON DELETE SET NULL) + bom_status.
  * The v4.23-DEFERRED cross-schema FK demand_lines.sap_code -> icb_sap."OITM"."ItemCode",
    DEFERRABLE INITIALLY DEFERRED, ON DELETE NO ACTION. Safe to land now that the inventory
    loader UPSERTs + soft-deletes (validFor='N') instead of TRUNCATE+RELOAD (WO v4.27 §3.6 /
    ADR 0013) — so a reload can never cascade-wipe demand_lines.

IDEMPOTENT (mirrors 0007/0009/0010): 0003's model-driven create_all builds the icb_mes tables on a
FRESH DB, so generated_boms + bom_lines + the new production_jobs columns already exist there; every
add therefore guards on existence. Two FKs are NOT on the models and are always created here (guarded
by constraint name): production_jobs.current_bom_id -> generated_boms (breaks the create_all cycle),
and demand_lines.sap_code -> icb_sap.OITM (targets the autogenerate-excluded icb_sap). This keeps the
CI upgrade→downgrade→upgrade round-trip green.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision: str = '0011'
down_revision: Union[str, Sequence[str], None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_TABLES = ["generated_boms", "bom_lines"]
_PJ_FK = "fk_production_jobs_current_bom"
_DEMAND_FK = "fk_demand_lines_sap_code"


def _new_table_objs():
    from app.database import Base
    import app.models.mes  # noqa: F401  (registers GeneratedBom + BomLine)
    return [Base.metadata.tables[f"icb_mes.{n}"] for n in _NEW_TABLES]


def _tables(bind) -> set:
    return set(sa_inspect(bind).get_table_names(schema="icb_mes"))


def _pj_cols(bind) -> set:
    return {c["name"] for c in sa_inspect(bind).get_columns("production_jobs", schema="icb_mes")}


def _fk_names(bind, table) -> set:
    return {fk["name"] for fk in sa_inspect(bind).get_foreign_keys(table, schema="icb_mes")}


def upgrade() -> None:
    bind = op.get_bind()
    have = _tables(bind)

    # 1) New persistence tables (guard: 0003 create_all already builds them on a fresh DB).
    missing = [t for t in _new_table_objs() if t.name not in have]
    if missing:
        from app.database import Base
        Base.metadata.create_all(bind=bind, tables=missing)

    # 2) production_jobs.current_bom_id + bom_status (guard: model-declared → present on fresh DB).
    pj_cols = _pj_cols(bind)
    if "current_bom_id" not in pj_cols:
        op.add_column("production_jobs", sa.Column("current_bom_id", sa.Integer(), nullable=True),
                      schema="icb_mes")
    if "bom_status" not in pj_cols:
        op.add_column(
            "production_jobs",
            sa.Column("bom_status", sa.String(16), nullable=False, server_default="pending"),
            schema="icb_mes",
        )

    # 3) production_jobs.current_bom_id -> generated_boms.id (NOT on the model: breaks the
    #    production_jobs <-> generated_boms create_all cycle). Always created here, guarded by name.
    if "generated_boms" in _tables(bind) and _PJ_FK not in _fk_names(bind, "production_jobs"):
        op.create_foreign_key(
            _PJ_FK, "production_jobs", "generated_boms",
            ["current_bom_id"], ["id"],
            source_schema="icb_mes", referent_schema="icb_mes", ondelete="SET NULL",
        )

    # 4) The v4.23-deferred cross-schema FK demand_lines.sap_code -> icb_sap.OITM.ItemCode.
    #    DEFERRABLE INITIALLY DEFERRED (validates at commit, so a single-transaction CI seed stays
    #    green) + ON DELETE NO ACTION. Guarded by constraint name.
    if "demand_lines" in have and _DEMAND_FK not in _fk_names(bind, "demand_lines"):
        op.create_foreign_key(
            _DEMAND_FK, "demand_lines", "OITM",
            ["sap_code"], ["ItemCode"],
            source_schema="icb_mes", referent_schema="icb_sap",
            ondelete="NO ACTION", deferrable=True, initially="DEFERRED",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "demand_lines" in _tables(bind) and _DEMAND_FK in _fk_names(bind, "demand_lines"):
        op.drop_constraint(_DEMAND_FK, "demand_lines", schema="icb_mes", type_="foreignkey")
    if "production_jobs" in _tables(bind):
        if _PJ_FK in _fk_names(bind, "production_jobs"):
            op.drop_constraint(_PJ_FK, "production_jobs", schema="icb_mes", type_="foreignkey")
        pj_cols = _pj_cols(bind)
        for col in ("bom_status", "current_bom_id"):
            if col in pj_cols:
                op.drop_column("production_jobs", col, schema="icb_mes")
    have = _tables(bind)
    present = [t for t in _new_table_objs() if t.name in have]
    if present:
        from app.database import Base
        Base.metadata.drop_all(bind=bind, tables=present)
