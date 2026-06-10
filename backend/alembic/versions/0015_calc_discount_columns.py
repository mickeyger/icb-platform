"""add Cost Calculator discount columns to icb_costings.calculations (WO v4.30 §3.1 — port of GRP d2da5bf).

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-09

The 7-Jun edit-functionality release (GRP-Costing-System d2da5bf) added four nullable discount columns to
the calculations table. On the SHARED prod DB faje's own deploy already ran that ALTER, so the columns
exist there. icb-platform's schema is Alembic-owned (create_all() and the legacy _run_migrations() were
removed at v4.12), so icb's OWN separately-built DBs — CI and the local dev DB — need these columns too.

This migration adds them GUARDED (`ADD COLUMN IF NOT EXISTS`), so on the shared prod DB it is a strict
no-op: §0.2a / WO §2 hold — the shared icb_costings schema is unchanged at cutover; this only materialises
the columns on icb's own DBs. (The §0.2a note "no migration needed" assumed the prod DB; icb's
Alembic-owned CI/local DBs require this one — see the v4.30 as-shipped escalation note.)

    discount_kind   VARCHAR(16)        -- 'percent' | 'amount' | NULL
    discount_input  DOUBLE PRECISION   -- raw value typed (the % or the flat amount)
    discount_amount DOUBLE PRECISION   -- computed currency discount
    net_total       DOUBLE PRECISION   -- selling_price - discount_amount (post-discount headline)

Downgrade is a deliberate NO-OP: these columns are faje-owned on the shared prod DB, so an accidental
`alembic downgrade` must never DROP them (which would lose live discount data). `ADD COLUMN IF NOT EXISTS`
keeps the up/down/up CI round-trip green regardless. (Same one-way-by-design rationale as 0014's backfill.)
"""
from typing import Sequence, Union

from alembic import op

revision: str = '0015'
down_revision: Union[str, Sequence[str], None] = '0014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DISCOUNT_COLUMNS = [
    ("discount_kind",   "VARCHAR(16)"),
    ("discount_input",  "DOUBLE PRECISION"),
    ("discount_amount", "DOUBLE PRECISION"),
    ("net_total",       "DOUBLE PRECISION"),
]


def upgrade() -> None:
    for name, type_ in _DISCOUNT_COLUMNS:
        op.execute(
            f"ALTER TABLE icb_costings.calculations ADD COLUMN IF NOT EXISTS {name} {type_}"
        )


def downgrade() -> None:
    # Intentional no-op — these columns are faje-owned on the shared prod DB; never auto-drop them.
    # The up/down/up round-trip stays green because upgrade() uses ADD COLUMN IF NOT EXISTS.
    pass
