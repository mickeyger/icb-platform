"""chassis module permission keys + role grants (WO v4.28 §0.9).

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-06

Seeds the 4 chassis permission keys + role grants into icb_costings.permissions /
role_permissions (idempotent ON CONFLICT, mirroring 0005's MES-permission seed). Kept separate from
the 0012 schema migration so the already-applied 0012 (with its translated chassis_records) is not
disturbed. Role mapping: the WO's "Workshop" capture role maps to the existing `production` role;
"PM" create/edit maps to `planner`. Admin stays a code-level wildcard (no rows).
"""
from typing import Sequence, Union

from alembic import op

revision: str = '0013'
down_revision: Union[str, Sequence[str], None] = '0012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PERMS = [
    ("chassis.create", "Create a chassis record"),
    ("chassis.update", "Edit a chassis record"),
    ("chassis.vcl", "Capture a VCL (book-in) event"),
    ("chassis.dcl", "Capture a DCL (dispatch) event"),
]
# (role, permission_key). Workshop -> production; PM -> planner. Admin = code-level wildcard.
_GRANTS = [
    ("planner", "chassis.create"), ("planner", "chassis.update"),
    ("planner", "chassis.vcl"), ("planner", "chassis.dcl"),
    ("production", "chassis.update"), ("production", "chassis.vcl"), ("production", "chassis.dcl"),
]


def upgrade() -> None:
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
    names = ", ".join(f"'{n}'" for n, _ in _PERMS)
    op.execute(
        f"DELETE FROM icb_costings.role_permissions WHERE permission_id IN "
        f"(SELECT id FROM icb_costings.permissions WHERE name IN ({names}))")
    op.execute(f"DELETE FROM icb_costings.permissions WHERE name IN ({names})")
