"""backfill production_jobs.chassis_record_id from job_number + add its index (WO v4.29 D3).

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-07

WO v4.28 (0012) added icb_mes.production_jobs.chassis_record_id + the FK to chassis_records, but never
populated it — §3.0 found it NULL for every job, so the v4.29 read-bridge (§0.3) had no key to JOIN on.
The de-facto chassis<->job link is chassis_records.job_number == production_jobs.job_number. This:

  1. Backfills chassis_record_id from that match (latest chassis_record per job_number wins when a
     job_number recurs across cycles), only where currently NULL — idempotent + non-destructive.
  2. Adds ix_production_jobs_chassis_record_id (Postgres does NOT auto-index a FK's referencing column;
     the join + per-job detail reads need it). Schema-qualified to icb_mes; CREATE ... IF NOT EXISTS.

The legacy production_jobs.chassis_received_at column is RETAINED (read fallback) but is deprecated as a
write target per ADR 0016 — see the model comment. Downgrade drops the index only; the backfill is a
one-way data repair (pre-migration the column was uniformly NULL, so re-nulling would also wipe any
links created after this migration).
"""
from typing import Sequence, Union

from alembic import op

revision: str = '0014'
down_revision: Union[str, Sequence[str], None] = '0013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Backfill the FK from the job_number match (latest chassis_record per job_number).
    op.execute(
        """
        UPDATE icb_mes.production_jobs pj
        SET chassis_record_id = cr.id
        FROM icb_mes.chassis_records cr
        WHERE pj.chassis_record_id IS NULL
          AND pj.job_number IS NOT NULL
          AND cr.job_number = pj.job_number
          AND cr.id = (
              SELECT MAX(cr2.id) FROM icb_mes.chassis_records cr2
              WHERE cr2.job_number = pj.job_number
          )
        """
    )
    # 2. Index the FK column for the read-bridge JOIN + per-job detail lookups.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_production_jobs_chassis_record_id "
        "ON icb_mes.production_jobs (chassis_record_id)"
    )
    # 3. Mark the legacy column deprecated-as-write (WO §2 lock b / ADR 0016).
    op.execute(
        "COMMENT ON COLUMN icb_mes.production_jobs.chassis_received_at IS "
        "'DEPRECATED as write column per ADR 0016 (v4.29). Reads prefer "
        "JOIN(chassis_records.lifecycle_events); retained as legacy fallback.'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS icb_mes.ix_production_jobs_chassis_record_id")
    op.execute("COMMENT ON COLUMN icb_mes.production_jobs.chassis_received_at IS NULL")
    # Backfill intentionally not reversed (see module docstring).
