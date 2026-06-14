"""WO v4.34 §3.7 — chassis-type DDM (Migration 0021).

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-13

Creates icb_mes.chassis_models — ONE controlled vocabulary for the chassis make/model dropdowns
(Planning ack + Pre-Job Card + Chassis +New/edit), replacing the hardcoded frontend list so
free-text variants ("Isuzu NPR 400" vs "NPR 400") stop fragmenting chassis_records lookups + token
substitution. Seeded with the 10 starter entries lifted from the mockup list; read-only in v4.34
(admin CRUD = v4.35). Mirrors the fridge_units DDM shape. Inspector-guarded; the seed runs only
when the table is empty (idempotent); up→down→up round-trips clean (downgrade drops the table).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision: str = "0021"
down_revision: Union[str, Sequence[str], None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MES = "icb_mes"

# Starter vocabulary (lifted verbatim from frontend/src/data/icb_mock_data.json → chassis_models).
_SEED = [
    ("HINO-300-614-SWB-EU3", "Hino", "300 614 SWB (EU3)", "truck", 2500),
    ("HINO-300-815", "Hino", "300 815", "truck", 3500),
    ("HINO-300-816-SWB-FB3", "Hino", "300 816 SWB (FB3)", "truck", 3500),
    ("HINO-500-1627-LWB-EJ5", "Hino", "500 1627 LWB (EJ5)", "truck", 7500),
    ("ISUZU-FTR-850-AMT", "Isuzu", "FTR 850 AMT (MY22)", "truck", 6800),
    ("TOYOTA-HILUX-24-SC-LWB", "Toyota", "Hilux 2.4 S/C LWB Bakkie", "bakkie", 1000),
    ("MAN-TGM-26290", "MAN", "TGM 26.290 (Tag Down)", "truck", 12000),
    ("VOLVO-FMX440-6X4", "Volvo", "FMX440 6X4 LH Drive", "truck", 15000),
    ("TRAILER-TRI-AXLE", "ICB", "Tri-Axle Trailer Chassis", "trailer", 28000),
    ("TRAILER-TANDEM", "ICB", "Tandem Trailer Chassis", "trailer", 20000),
]


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa_inspect(bind)
    if "chassis_models" not in insp.get_table_names(schema=MES):
        op.create_table(
            "chassis_models",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("code", sa.String(64), nullable=False),
            sa.Column("make", sa.String(64), nullable=False),
            sa.Column("model", sa.String(128), nullable=False),
            sa.Column("category", sa.String(32)),
            sa.Column("max_payload_kg", sa.Integer),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
            sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("created_by", sa.String(128)),
            sa.Column("updated_by", sa.String(128)),
            sa.UniqueConstraint("code", name="uq_chassis_models_code"),
            schema=MES,
        )
        op.create_index("ix_chassis_models_active", "chassis_models",
                        ["is_active", "make"], schema=MES)
    # Seed only when empty — idempotent, safe to re-run, won't clobber later admin edits (v4.35).
    count = bind.execute(sa.text(f"SELECT count(*) FROM {MES}.chassis_models")).scalar()
    if not count:
        for i, (code, make, model, cat, payload) in enumerate(_SEED):
            bind.execute(sa.text(
                f"INSERT INTO {MES}.chassis_models "
                "(code, make, model, category, max_payload_kg, sort_order, created_by) "
                "VALUES (:code, :make, :model, :cat, :payload, :so, 'migration_0021')"
            ), {"code": code, "make": make, "model": model, "cat": cat,
                "payload": payload, "so": i})


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa_inspect(bind)
    if "chassis_models" in insp.get_table_names(schema=MES):
        op.drop_table("chassis_models", schema=MES)
