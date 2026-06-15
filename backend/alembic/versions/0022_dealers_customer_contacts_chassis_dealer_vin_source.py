"""WO v4.34.1 §3.1 — dealers (is_dealer) + customer_contacts + chassis dealer_id/vin_source.

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-14

- icb_costings.customers.is_dealer (BOOLEAN, default false) — §0.2 single-table dealer flag.
- icb_costings.customer_contacts — §0.6 multi-contact per customer + a PARTIAL UNIQUE index (one
  is_primary per customer) + the §0.7 one-shot migration of customers.email/telephone into a primary
  contact row (deprecate-not-drop: the customer cache columns stay).
- icb_mes.chassis_records.dealer_id (Integer + cross-schema FK → icb_costings.customers, SET NULL,
  per ADR 0006 — registered in CROSS_SCHEMA_FKS) — §0.3 the supplying dealer.
- icb_mes.chassis_records.vin_source (String) — §0.17 VIN provenance (chassis_page_manual late-entry).

Inspector-guarded throughout; the contact backfill is idempotent (NOT EXISTS guard); up→down→up
round-trips clean (downgrade drops customer_contacts — the email/telephone cache is preserved).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision: str = "0022"
down_revision: Union[str, Sequence[str], None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MES = "icb_mes"
COST = "icb_costings"


def _has_col(insp, table, col, schema) -> bool:
    return any(c["name"] == col for c in insp.get_columns(table, schema=schema))


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa_inspect(bind)

    # §0.2 — customers.is_dealer
    if not _has_col(insp, "customers", "is_dealer", COST):
        op.add_column("customers", sa.Column("is_dealer", sa.Boolean(), nullable=False,
                      server_default=sa.text("false")), schema=COST)

    # §0.6 — customer_contacts (+ partial unique: one is_primary per customer)
    if "customer_contacts" not in insp.get_table_names(schema=COST):
        op.create_table(
            "customer_contacts",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("customer_id", sa.Integer, nullable=False),
            sa.Column("name", sa.String(200)),
            sa.Column("role", sa.String(100)),
            sa.Column("email", sa.String(300)),
            sa.Column("telephone", sa.String(100)),
            sa.Column("is_primary", sa.Boolean, nullable=False, server_default=sa.text("false")),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("created_by", sa.String(128)),
            sa.Column("updated_by", sa.String(128)),
            schema=COST,
        )
        op.create_foreign_key("fk_customer_contacts_customer", "customer_contacts", "customers",
                              ["customer_id"], ["id"], source_schema=COST, referent_schema=COST,
                              ondelete="CASCADE")
        op.create_index("ix_customer_contacts_customer", "customer_contacts", ["customer_id"], schema=COST)
        op.create_index("uq_customer_contacts_one_primary", "customer_contacts", ["customer_id"],
                        unique=True, schema=COST, postgresql_where=sa.text("is_primary"))

    # §0.7 — one-shot backfill: each customer with a non-empty email or telephone gets a primary
    # contact row (name unknown → NULL). Idempotent: skips customers that already have a primary.
    bind.execute(sa.text(f"""
        INSERT INTO {COST}.customer_contacts (customer_id, email, telephone, is_primary, is_active, created_by)
        SELECT c.id, NULLIF(c.email, ''), NULLIF(c.telephone, ''), true, true, 'migration_0022'
        FROM {COST}.customers c
        WHERE (NULLIF(c.email, '') IS NOT NULL OR NULLIF(c.telephone, '') IS NOT NULL)
          AND NOT EXISTS (SELECT 1 FROM {COST}.customer_contacts cc
                          WHERE cc.customer_id = c.id AND cc.is_primary)
    """))

    # §0.3 — chassis_records.dealer_id (+ cross-schema FK) ; §0.17 — vin_source
    if not _has_col(insp, "chassis_records", "dealer_id", MES):
        op.add_column("chassis_records", sa.Column("dealer_id", sa.Integer, nullable=True), schema=MES)
        op.create_index("ix_chassis_records_dealer_id", "chassis_records", ["dealer_id"], schema=MES)
        op.create_foreign_key("fk_chassis_records_dealer_id", "chassis_records", "customers",
                              ["dealer_id"], ["id"], source_schema=MES, referent_schema=COST,
                              ondelete="SET NULL")
    if not _has_col(insp, "chassis_records", "vin_source", MES):
        op.add_column("chassis_records", sa.Column("vin_source", sa.String(32)), schema=MES)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa_inspect(bind)
    if _has_col(insp, "chassis_records", "vin_source", MES):
        op.drop_column("chassis_records", "vin_source", schema=MES)
    if _has_col(insp, "chassis_records", "dealer_id", MES):
        op.drop_constraint("fk_chassis_records_dealer_id", "chassis_records", schema=MES, type_="foreignkey")
        op.drop_index("ix_chassis_records_dealer_id", "chassis_records", schema=MES)
        op.drop_column("chassis_records", "dealer_id", schema=MES)
    if "customer_contacts" in insp.get_table_names(schema=COST):
        op.drop_table("customer_contacts", schema=COST)   # drops its FK + indexes
    if _has_col(insp, "customers", "is_dealer", COST):
        op.drop_column("customers", "is_dealer", schema=COST)
