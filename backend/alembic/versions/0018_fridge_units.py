"""fridge_units DDM master (WO v4.33 scope addition — Template Variable Substitution + Fridge DDM).

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-12

NEW icb_mes.fridge_units — the fridge dropdown master behind the {{fridge_make}} /
{{fridge_drawing}} / {{fridge_cutout_*}} template tokens. Seeded separately by
scripts/seed_fridge_units.py (30 rows from Standard Drawing FRIDGE MOUNTING A — Front Mount;
drawings B/D/F/G/H are the v4.33.1 enhancement). A NEW migration rather than a 0017 fold-in:
0017 is committed AND applied on the dev DBs — additive 0018 upgrades with a plain
`alembic upgrade head`, no downgrade dance.

IDEMPOTENT (house idiom): the model-driven create_all builds the table on a fresh DB, so
creation guards on existence; downgrade drops it guarded.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect as sa_inspect

revision: str = '0018'
down_revision: Union[str, Sequence[str], None] = '0017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_obj():
    from app.database import Base
    import app.models.mes  # noqa: F401  (registers FridgeUnit)
    return Base.metadata.tables["icb_mes.fridge_units"]


def _have(bind) -> bool:
    return "fridge_units" in sa_inspect(bind).get_table_names(schema="icb_mes")


def upgrade() -> None:
    bind = op.get_bind()
    if not _have(bind):
        from app.database import Base
        Base.metadata.create_all(bind=bind, tables=[_table_obj()])


def downgrade() -> None:
    bind = op.get_bind()
    if _have(bind):
        from app.database import Base
        Base.metadata.drop_all(bind=bind, tables=[_table_obj()])
