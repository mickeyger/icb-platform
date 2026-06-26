"""WO v4.36c — Kenny QC + Dispatch: qc tables + permissions (Migration 0028).

Revision ID: 0028
Revises: 0027
Create Date: 2026-06-25

Ship-order alembic assignment (§0.18, BA-ratified 25 Jun): v4.36c ships 4 Jul so it takes 0028 off
0027; CA4 v4.36.5 (ships ~1 Aug; pre-§3.1, no migration file built) rebases its claim to 0029.

Adds three icb_mes tables (defect_categories, qc_inspections, qc_signoffs — model-declared in
app.models.mes, created via create_all here, inspector-guarded), the cross-schema inspector_user_id ->
icb_costings.users FKs (SET NULL — a signoff outlives a user delete, mirroring 0027), the qc.inspect /
qc.signoff permission keys + role grants (0016 precedent — permissions ship with the feature they gate;
admin is a code-level wildcard), and the 5 seed defect categories (admin-editable, §0.5).

This adds 3 icb_mes tables, so tests/test_smoke.py's icb_mes table-count assertion rises 36 -> 39
(bumped in THIS same commit — §0.19 corrected for this repo: CI is migration-built [create_all was
removed from init], so the smoke count couples to the migration, NOT the model-introduction commit).

chassis_records.status '+dispatched' is a VARCHAR value-add (no DDL — already in the model comment +
frontend styles, §3.0 §2b), so it is NOT in this migration. Inspector-guarded; up->down->up clean.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect as sa_inspect

revision: str = "0028"
down_revision: Union[str, Sequence[str], None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MES = "icb_mes"
_TABLES = ["defect_categories", "qc_inspections", "qc_signoffs"]   # FK-dependency create order
_FKS = {  # cross-schema inspector_user_id -> icb_costings.users (SET NULL)
    "qc_inspections": "fk_qc_inspections_inspector",
    "qc_signoffs": "fk_qc_signoffs_inspector",
}
_PERMS = [
    ("qc.inspect", "Record QC inspection verdicts (Kenny's inbox + per-category)"),
    ("qc.signoff", "Finalize a QC inspection sign-off (pass -> dispatch)"),
]
# admin is a code-level wildcard (no row needed); supervisors inspect, the inspector also signs off.
_GRANTS = [
    ("qc_inspector", "qc.inspect"), ("planner", "qc.inspect"), ("production", "qc.inspect"),
    ("qc_inspector", "qc.signoff"),
]
_CATEGORIES = [("Chassis", 10), ("Panels", 20), ("Fridge Unit", 30),   # 5 seed defaults (§0.5)
               ("Electrical", 40), ("Finishing", 50)]


def _mes_tables(bind) -> set:
    return set(sa_inspect(bind).get_table_names(schema=MES))


def _fks(bind, table) -> set:
    return {fk["name"] for fk in sa_inspect(bind).get_foreign_keys(table, schema=MES)}


def _table_objs():
    from app.database import Base
    import app.models.mes  # noqa: F401 — registers DefectCategory/QcInspection/QcSignoff on Base.metadata
    return [Base.metadata.tables[f"{MES}.{t}"] for t in _TABLES]


def upgrade() -> None:
    bind = op.get_bind()
    have = _mes_tables(bind)

    # 1. create the three tables (model-declared; uniques + indexes ride on create_all). create_all
    #    resolves FK-dependency order (defect_categories before qc_inspections.category_id).
    missing = [t for t in _table_objs() if t.name not in have]
    if missing:
        from app.database import Base
        Base.metadata.create_all(bind=bind, tables=missing)

    # 2. cross-schema inspector_user_id -> icb_costings.users (SET NULL — signoff outlives a user delete).
    for table, fkname in _FKS.items():
        if fkname not in _fks(bind, table):
            op.create_foreign_key(
                fkname, table, "users", ["inspector_user_id"], ["id"],
                source_schema=MES, referent_schema="icb_costings", ondelete="SET NULL")

    # 3. permission keys + grants (idempotent; 0016 precedent; admin = code wildcard).
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

    # 4. seed the 5 default defect categories (admin-editable; §0.5). Idempotent on name.
    for name, order in _CATEGORIES:
        op.execute(
            f"INSERT INTO icb_mes.defect_categories (name, sort_order, is_active, created_by) "
            f"VALUES ('{name}', {order}, true, 'migration_0028') ON CONFLICT (name) DO NOTHING")


def downgrade() -> None:
    bind = op.get_bind()

    # 3 reversed: remove permission grants + keys (the 5 categories drop with their table).
    names = ", ".join(f"'{n}'" for n, _ in _PERMS)
    op.execute(
        f"DELETE FROM icb_costings.role_permissions WHERE permission_id IN "
        f"(SELECT id FROM icb_costings.permissions WHERE name IN ({names}))")
    op.execute(f"DELETE FROM icb_costings.permissions WHERE name IN ({names})")

    # 2 reversed: drop the cross-schema FKs before dropping the tables.
    have = _mes_tables(bind)
    for table, fkname in _FKS.items():
        if table in have and fkname in _fks(bind, table):
            op.drop_constraint(fkname, table, schema=MES, type_="foreignkey")

    # 1 reversed: drop the three tables (drop_all resolves reverse FK order).
    present = [t for t in _table_objs() if t.name in have]
    if present:
        from app.database import Base
        Base.metadata.drop_all(bind=bind, tables=present)
