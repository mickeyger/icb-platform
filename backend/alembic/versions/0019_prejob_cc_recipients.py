"""prejob_cards.cc_recipients (WO v4.33 CC addition — Michael-approved 12 Jun).

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-12

Comma-separated free-text CC addresses for the Pre-Job Card check-notification email
(mailto &cc= — users carry no email column until v4.34's notification config). ADD COLUMN
IF NOT EXISTS (0015 idiom; the column is model-declared so fresh-DB create_all builds it);
downgrade drops it guarded.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect as sa_inspect

revision: str = '0019'
down_revision: Union[str, Sequence[str], None] = '0018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE icb_mes.prejob_cards ADD COLUMN IF NOT EXISTS cc_recipients TEXT")


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa_inspect(bind).get_columns("prejob_cards", schema="icb_mes")}
    if "cc_recipients" in cols:
        op.drop_column("prejob_cards", "cc_recipients", schema="icb_mes")
