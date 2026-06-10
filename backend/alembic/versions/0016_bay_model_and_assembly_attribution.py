"""bay-model entities + chassis assembly attribution (WO v4.31 §3.1, §0.12, ADR 0018).

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-10

Phase 3 §4.6 — the two PHYSICAL-LOCATION master tables + the chassis assembly-attribution capability,
realigned to the §0.12 LOCKED sketch (10 Jun PM):

  A. NEW icb_mes.parking_bays  (seeded ParkingBay-1..24 — the ~24 outside slots)
     NEW icb_mes.assembly_bays (seeded AssemblyBay-1..5 — the 5 inside bays; Michael's on-floor count)
     Vacuum V-1..5 / Press P-1..3 stay free-text in planning_slots (NOT promoted — Phase 4 territory).
  B. chassis attribution:
       * widen chassis_lifecycle_events.event_type VARCHAR(8) -> VARCHAR(24) so 'assembly_assigned'
         (17 chars) fits beside 'VCL'/'DCL' — no DB enum (ADR 0015).
       * chassis_lifecycle_events.assembly_bay_id -> assembly_bays (set only on the event; the SINGLE
         source of truth for "which bay" — the service derives it from the latest such event).
       * chassis_records.status gains the value 'in_assembly' — VALUES-IN-COMMENTS ONLY, NO DDL (the
         column is already VARCHAR(24); §0.12 forbids a denormalised bay column on chassis_records,
         matching the 0007/0011/0012 status-enum-via-comment pattern).
  C. permission chassis.assembly_assign + grants (planner, production) into icb_costings.permissions /
     role_permissions, idempotent ON CONFLICT (0013 precedent — permissions ship with the event they
     gate; admin is a code-level wildcard).

IDEMPOTENT (mirrors 0007/0011/0012/0014): 0003's model-driven create_all builds the icb_mes tables on a
FRESH DB, so the two bay tables + the new event column may already exist there; every add guards on
existence (sa_inspect). The assembly_bay_id FK is NOT on the model (created here, guarded by name).
Additive upgrade. Downgrade resets status 'in_assembly'->'in_workshop' and DELETEs 'assembly_assigned'
events BEFORE narrowing event_type back to VARCHAR(8) so the narrow can never truncate — keeping the CI
upgrade->downgrade->upgrade round-trip green.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision: str = '0016'
down_revision: Union[str, Sequence[str], None] = '0015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_TABLES = ["parking_bays", "assembly_bays"]
_EVENT_FK = "fk_chassis_events_assembly_bay"

# Reference data — physical bays. (code, label, sort_order)
_PARKING_BAYS = [(f"ParkingBay-{n}", f"Parking Bay {n}", n) for n in range(1, 25)]   # 24 outside
_ASSEMBLY_BAYS = [(f"AssemblyBay-{n}", f"Assembly Bay {n}", n) for n in range(1, 6)]  # 5 inside

# Permission key + grants (0013 precedent; Workshop->production, PM->planner; admin = code-level wildcard).
_PERMS = [("chassis.assembly_assign", "Assign a chassis to an assembly bay (parking -> assembly)")]
_GRANTS = [("planner", "chassis.assembly_assign"), ("production", "chassis.assembly_assign")]


def _new_table_objs():
    from app.database import Base
    import app.models.mes  # noqa: F401  (registers ParkingBay/AssemblyBay)
    return [Base.metadata.tables[f"icb_mes.{n}"] for n in _NEW_TABLES]


def _tables(bind) -> set:
    return set(sa_inspect(bind).get_table_names(schema="icb_mes"))


def _cols(bind, table) -> set:
    return {c["name"] for c in sa_inspect(bind).get_columns(table, schema="icb_mes")}


def _fks(bind, table) -> set:
    return {fk["name"] for fk in sa_inspect(bind).get_foreign_keys(table, schema="icb_mes")}


def upgrade() -> None:
    bind = op.get_bind()
    have = _tables(bind)

    # ── A. bay master tables (guard: 0003 create_all may already build them on a fresh DB) + seed ──
    missing = [t for t in _new_table_objs() if t.name not in have]
    if missing:
        from app.database import Base
        Base.metadata.create_all(bind=bind, tables=missing)
    for code, label, order in _PARKING_BAYS:
        op.execute(
            f"INSERT INTO icb_mes.parking_bays (code, label, sort_order, is_active) "
            f"VALUES ('{code}', '{label}', {order}, true) ON CONFLICT (code) DO NOTHING")
    for code, label, order in _ASSEMBLY_BAYS:
        op.execute(
            f"INSERT INTO icb_mes.assembly_bays (code, label, sort_order, is_active) "
            f"VALUES ('{code}', '{label}', {order}, true) ON CONFLICT (code) DO NOTHING")

    # ── B. event_type widen (8->24) + assembly_bay_id FK on the EVENT (the single source of truth) ──
    # 'in_assembly' is added to chassis_records.status as a VALUE only (model comment) — NO DDL here.
    op.alter_column("chassis_lifecycle_events", "event_type",
                    type_=sa.String(24), existing_type=sa.String(8),
                    existing_nullable=False, schema="icb_mes")
    if "assembly_bay_id" not in _cols(bind, "chassis_lifecycle_events"):
        op.add_column("chassis_lifecycle_events",
                      sa.Column("assembly_bay_id", sa.Integer(), nullable=True), schema="icb_mes")
    if "assembly_bays" in _tables(bind) and _EVENT_FK not in _fks(bind, "chassis_lifecycle_events"):
        op.create_foreign_key(_EVENT_FK, "chassis_lifecycle_events", "assembly_bays",
                              ["assembly_bay_id"], ["id"],
                              source_schema="icb_mes", referent_schema="icb_mes", ondelete="SET NULL")

    # ── C. permission key + grants (idempotent; 0013 precedent) ──
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

    # C. remove permission grants + key.
    names = ", ".join(f"'{n}'" for n, _ in _PERMS)
    op.execute(
        f"DELETE FROM icb_costings.role_permissions WHERE permission_id IN "
        f"(SELECT id FROM icb_costings.permissions WHERE name IN ({names}))")
    op.execute(f"DELETE FROM icb_costings.permissions WHERE name IN ({names})")

    # B. revert the assembly-attribution feature: reset the new status value, drop the event FK+column,
    #    clear the new event kind, then narrow event_type back (no truncation — only VCL/DCL remain).
    op.execute("UPDATE icb_mes.chassis_records SET status = 'in_workshop' WHERE status = 'in_assembly'")
    if "chassis_lifecycle_events" in _tables(bind):
        if _EVENT_FK in _fks(bind, "chassis_lifecycle_events"):
            op.drop_constraint(_EVENT_FK, "chassis_lifecycle_events", schema="icb_mes", type_="foreignkey")
        if "assembly_bay_id" in _cols(bind, "chassis_lifecycle_events"):
            op.drop_column("chassis_lifecycle_events", "assembly_bay_id", schema="icb_mes")
        op.execute("DELETE FROM icb_mes.chassis_lifecycle_events WHERE event_type = 'assembly_assigned'")
        op.alter_column("chassis_lifecycle_events", "event_type",
                        type_=sa.String(8), existing_type=sa.String(24),
                        existing_nullable=False, schema="icb_mes")

    # A. drop the bay master tables (the referencing event FK is already gone).
    have = _tables(bind)
    present = [t for t in _new_table_objs() if t.name in have]
    if present:
        from app.database import Base
        Base.metadata.drop_all(bind=bind, tables=present)
