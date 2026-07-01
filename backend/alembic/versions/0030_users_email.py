"""v1.39.3 backport — users.email (Migration 0030).

Revision ID: 0030
Revises: 0029
Create Date: 2026-07-01

Adds icb_costings.users.email (VARCHAR(255), NOT NULL, server_default ''). Phase-1 go-live
needs real addresses on the three primary users (Burt/Deon/Simeon) so the Pre-Job Card
"Submit for Check" transition can auto-send to the Sales + Planner signers (+ CC). Until now
users carried NO email column — the check "email" was a client-side mailto: the operator
addressed by hand (WO v4.33 §0.11 / v4.38 §3.0).

Existing rows backfill to '' (the server_default); the seed_phase1_users script then sets the
three real addresses. Inspector-guarded; additive ALTER; up->down->up round-trips clean.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision: str = "0030"
down_revision: Union[str, Sequence[str], None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COSTINGS = "icb_costings"


def _cols(bind, table, schema) -> set:
    return {c["name"] for c in sa_inspect(bind).get_columns(table, schema=schema)}


def upgrade() -> None:
    bind = op.get_bind()
    if "email" not in _cols(bind, "users", COSTINGS):
        op.add_column(
            "users",
            sa.Column("email", sa.String(length=255), nullable=False, server_default=""),
            schema=COSTINGS,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "email" in _cols(bind, "users", COSTINGS):
        op.drop_column("users", "email", schema=COSTINGS)
