"""sap_schema — icb_sap (OWHS/OITM/OITW) SAP-mock landing zone.

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-05

WO v4.23 (SAP-mock). Creates the `icb_sap` landing zone — SAP Business One-shaped
(OITM/OITW/OWHS, SAP-native quoted names, a STORED generated `Available` column +
composite OITW PK), populated by `import_inventory_to_sap_mock.py`.

Raw DDL (the generated column + composite PK + mixed-case SAP names don't round-trip
through model-driven create_all). Idempotent (IF NOT EXISTS), so the CI upgrade/
downgrade/upgrade round-trip stays green. `icb_sap` is excluded from autogenerate (not
in env.py `_RELEVANT_SCHEMAS`), so `alembic check` ignores it. Runs as `icb_app` (can
CREATE SCHEMA — verified). Downgrade drops the schema CASCADE.

§0.5 cross-schema FK — DEFERRED (build-time decision; see ADR 0013 + the load report):
the planned `icb_mes.demand_lines.sap_code -> icb_sap.OITM.ItemCode` FK is NOT added here.
The demand (icb_mes / workbook ETL) and OITM (icb_sap / inventory ETL) are loaded by
SEPARATE one-shot ETLs with no guaranteed ordering, so an enforced FK (even NOT VALID):
(1) CASCADE-truncates demand_lines whenever OITM is reloaded; (2) blocks the independent
OITM reload cycle; (3) rejects the demo demand_lines the mock seed inserts (OITM empty in
CI) -> breaks CI. The demand<->OITM relationship is instead DOCUMENTED + measured by the
orphan-reconciliation report (the §0.5 deliverable). The enforced FK is added once the two
loaders are coordinated and the codes reconciled (a follow-on micro-WO). Flagged for BA.
"""
from typing import Sequence, Union

from alembic import op

revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS icb_sap AUTHORIZATION icb_app")

    op.execute('''
        CREATE TABLE IF NOT EXISTS icb_sap."OWHS" (
            "WhsCode"   VARCHAR(8)  PRIMARY KEY,
            "WhsName"   VARCHAR(64) NOT NULL,
            "Inactive"  CHAR(1)     NOT NULL DEFAULT 'N',
            created_at  TIMESTAMPTZ DEFAULT now(),
            updated_at  TIMESTAMPTZ DEFAULT now()
        )''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS icb_sap."OITM" (
            "ItemCode"             VARCHAR(64)  PRIMARY KEY,
            "ItemName"             VARCHAR(255),
            "InvntryUom"           VARCHAR(16),
            "ItmsGrpCod"           INTEGER,
            "U_ItemGroup"          VARCHAR(32),
            "U_LastPurchasePrice"  NUMERIC(18,4),
            "U_LastEvaluatedPrice" NUMERIC(18,4),
            "U_Manufacturer"       VARCHAR(128),
            "MinLevel"             NUMERIC(18,3),
            "validFor"             CHAR(1) NOT NULL DEFAULT 'Y',
            created_at             TIMESTAMPTZ DEFAULT now(),
            updated_at             TIMESTAMPTZ DEFAULT now()
        )''')
    op.execute('CREATE INDEX IF NOT EXISTS "ix_OITM_ItmsGrpCod" ON icb_sap."OITM" ("ItmsGrpCod")')
    op.execute('CREATE INDEX IF NOT EXISTS "ix_OITM_U_ItemGroup" ON icb_sap."OITM" ("U_ItemGroup")')

    op.execute('''
        CREATE TABLE IF NOT EXISTS icb_sap."OITW" (
            "ItemCode"   VARCHAR(64)   NOT NULL,
            "WhsCode"    VARCHAR(8)    NOT NULL,
            "OnHand"     NUMERIC(18,3) NOT NULL DEFAULT 0,
            "IsCommited" NUMERIC(18,3) NOT NULL DEFAULT 0,
            "OnOrder"    NUMERIC(18,3) NOT NULL DEFAULT 0,
            "Available"  NUMERIC(18,3) GENERATED ALWAYS AS ("OnHand" - "IsCommited" + "OnOrder") STORED,
            "AvgPrice"   NUMERIC(18,4),
            updated_at   TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY ("ItemCode", "WhsCode"),
            FOREIGN KEY ("ItemCode") REFERENCES icb_sap."OITM"("ItemCode") ON DELETE CASCADE,
            FOREIGN KEY ("WhsCode")  REFERENCES icb_sap."OWHS"("WhsCode")  ON DELETE RESTRICT
        )''')
    op.execute('CREATE INDEX IF NOT EXISTS "ix_OITW_OnHand" ON icb_sap."OITW" ("OnHand") WHERE "OnHand" > 0')


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS icb_sap CASCADE")
