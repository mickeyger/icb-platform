"""WO v4.34 §3.1 — chassis pipeline provenance + job-number strategy (Migration 0020).

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-13

Additive + two deliberate constraint relaxations (BA-locked 13 Jun):
  * prejob_cards.chassis_record_id  — direct FK to chassis_records (ON DELETE SET NULL);
    the §0.5 auto-create link (today the card→chassis link is indirect via the job).
  * chassis_records.created_via / created_source_ref — provenance (§0.4).
  * chassis_records.vin DROP NOT NULL — "VIN unknown until receive" (decision #2; Postgres
    keeps multiple NULLs out of the unique index natively, so uq_chassis_records_vin stays).
  * production_jobs.job_number_source / job_number_locked — the §0.7/§0.9 trio.
  * production_jobs.job_number: DROP UNIQUE → non-unique index (decision #1 — numeric cores
    collide across letter prefixes; production_jobs.id stays the true PK). Unique dropped
    BEFORE the backfill so the numeric rewrite can't trip it.
  * Backfill: job_number → numeric core of the quote (`A32744/06/2026` → `32744`),
    job_number_source='quote_derived'; chassis_records.created_via='legacy_import_v4_28'.
  * Seed SAP_RETIRED='false' into icb_costings.admin_settings (§0.9; admin UI to flip = v4.35).

Inspector-guarded throughout; up→down→up round-trips clean. The backfill is one-way (the
pre-migration quote-string job_numbers are not restored on downgrade — documented).
Status values-in-comments gain `expected` + `expected_orphaned` (no DDL on the column).
"""
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision: str = "0020"
down_revision: Union[str, Sequence[str], None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MES = "icb_mes"


def _cols(insp, table):
    return {c["name"] for c in insp.get_columns(table, schema=MES)}


def _numeric_core(ref):
    """`A32744/06/2026` → `32744`; `Q-32891` → `32891`. First digit run = the core after the
    letter prefix and before the /MM/YYYY (or after a legacy dash)."""
    if not ref:
        return None
    m = re.search(r"\d+", str(ref))
    return m.group(0) if m else None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa_inspect(bind)

    # 1. prejob_cards.chassis_record_id (+ FK ON DELETE SET NULL + index) — §0.5 direct link
    op.execute(f"ALTER TABLE {MES}.prejob_cards ADD COLUMN IF NOT EXISTS chassis_record_id INTEGER")
    fk_names = {fk["name"] for fk in insp.get_foreign_keys("prejob_cards", schema=MES)}
    if "fk_prejob_cards_chassis_record" not in fk_names:
        op.create_foreign_key(
            "fk_prejob_cards_chassis_record", "prejob_cards", "chassis_records",
            ["chassis_record_id"], ["id"],
            source_schema=MES, referent_schema=MES, ondelete="SET NULL")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_prejob_cards_chassis_record_id "
               f"ON {MES}.prejob_cards (chassis_record_id)")

    # 2. chassis_records provenance (§0.4)
    op.execute(f"ALTER TABLE {MES}.chassis_records ADD COLUMN IF NOT EXISTS created_via VARCHAR(32)")
    op.execute(f"ALTER TABLE {MES}.chassis_records ADD COLUMN IF NOT EXISTS created_source_ref VARCHAR(64)")

    # 3. chassis_records.vin DROP NOT NULL (decision #2) — uq_chassis_records_vin stays
    op.execute(f"ALTER TABLE {MES}.chassis_records ALTER COLUMN vin DROP NOT NULL")

    # 4. production_jobs job-number trio (§0.7/§0.9)
    op.execute(f"ALTER TABLE {MES}.production_jobs ADD COLUMN IF NOT EXISTS job_number_source VARCHAR(16)")
    op.execute(f"ALTER TABLE {MES}.production_jobs "
               f"ADD COLUMN IF NOT EXISTS job_number_locked BOOLEAN NOT NULL DEFAULT FALSE")

    # 5. drop UNIQUE on job_number (decision #1), add non-unique index — BEFORE the backfill
    for uc in insp.get_unique_constraints("production_jobs", schema=MES):
        if uc["column_names"] == ["job_number"]:
            op.drop_constraint(uc["name"], "production_jobs", schema=MES, type_="unique")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_production_jobs_job_number "
               f"ON {MES}.production_jobs (job_number)")

    # 6. backfill — numeric job_number from the quote (collisions now allowed)
    rows = bind.execute(sa.text(
        f"SELECT pj.id, COALESCE(c.quote_number, pj.job_number) AS ref "
        f"FROM {MES}.production_jobs pj "
        f"LEFT JOIN icb_costings.calculations c ON c.id = pj.calculation_record_id")).fetchall()
    for jid, ref in rows:
        core = _numeric_core(ref)
        if core:
            bind.execute(sa.text(
                f"UPDATE {MES}.production_jobs SET job_number = :jn, "
                f"job_number_source = 'quote_derived' WHERE id = :id"), {"jn": core, "id": jid})
    # chassis provenance backfill — existing rows predate the pipeline → v4.28 import lineage
    op.execute(f"UPDATE {MES}.chassis_records SET created_via = 'legacy_import_v4_28' "
               f"WHERE created_via IS NULL")

    # 7. SAP_RETIRED site setting (§0.9) — admin_settings lives in icb_costings
    op.execute("INSERT INTO icb_costings.admin_settings (key, value) "
               "VALUES ('SAP_RETIRED', 'false') ON CONFLICT (key) DO NOTHING")


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa_inspect(bind)

    op.execute("DELETE FROM icb_costings.admin_settings WHERE key = 'SAP_RETIRED'")

    # prejob_cards FK + index + column
    fk_names = {fk["name"] for fk in insp.get_foreign_keys("prejob_cards", schema=MES)}
    if "fk_prejob_cards_chassis_record" in fk_names:
        op.drop_constraint("fk_prejob_cards_chassis_record", "prejob_cards", schema=MES, type_="foreignkey")
    op.execute(f"DROP INDEX IF EXISTS {MES}.ix_prejob_cards_chassis_record_id")
    if "chassis_record_id" in _cols(insp, "prejob_cards"):
        op.drop_column("prejob_cards", "chassis_record_id", schema=MES)

    # production_jobs: drop trio + non-unique index; restore UNIQUE only if no collisions remain
    op.execute(f"DROP INDEX IF EXISTS {MES}.ix_production_jobs_job_number")
    for col in ("job_number_source", "job_number_locked"):
        if col in _cols(insp, "production_jobs"):
            op.drop_column("production_jobs", col, schema=MES)
    dupes = bind.execute(sa.text(
        f"SELECT 1 FROM {MES}.production_jobs WHERE job_number IS NOT NULL "
        f"GROUP BY job_number HAVING COUNT(*) > 1 LIMIT 1")).fetchone()
    have_uc = any(uc["column_names"] == ["job_number"]
                  for uc in insp.get_unique_constraints("production_jobs", schema=MES))
    if not dupes and not have_uc:
        op.create_unique_constraint("production_jobs_job_number_key", "production_jobs",
                                    ["job_number"], schema=MES)

    # chassis_records: restore vin NOT NULL only if no NULLs present; drop provenance cols
    null_vin = bind.execute(sa.text(
        f"SELECT 1 FROM {MES}.chassis_records WHERE vin IS NULL LIMIT 1")).fetchone()
    if not null_vin:
        op.execute(f"ALTER TABLE {MES}.chassis_records ALTER COLUMN vin SET NOT NULL")
    for col in ("created_via", "created_source_ref"):
        if col in _cols(insp, "chassis_records"):
            op.drop_column("chassis_records", col, schema=MES)
