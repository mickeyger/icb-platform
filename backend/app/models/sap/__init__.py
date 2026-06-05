"""SAP-mock landing zone — the `icb_sap` schema (WO v4.23, ADR 0013).

SAP Business One-shaped tables (OITM / OITW / OWHS) with SAP B1-native table + column
names, so the eventual swap to live SAP is a connection change, not a re-mapping.
READ-ONLY from app code (convention, ADR 0013); written only by the ETL loader
(`import_inventory_to_sap_mock.py`).

The tables are created by migration 0008 via RAW DDL (the STORED generated `Available`
column + composite OITW PK + quoted mixed-case SAP names don't round-trip cleanly through
model-driven create_all). These models are for ORM reads + ETL inserts only and are
deliberately NOT imported by alembic/env.py — `icb_sap` is excluded from autogenerate
(not in env.py `_RELEVANT_SCHEMAS`), so `alembic check` ignores the schema. `init_db()`
never calls create_all, so registering these on the shared Base is safe. Mixed-case
column names are preserved + auto-quoted by SQLAlchemy (e.g. `"ItemCode"`, `"OnHand"`).
"""
from datetime import datetime, timezone

from sqlalchemy import Column, Computed, DateTime, Integer, Numeric, String

from app.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class OWHS(Base):
    """Warehouses (SAP B1 OWHS)."""
    __tablename__ = "OWHS"
    __table_args__ = {"schema": "icb_sap"}
    WhsCode = Column(String(8), primary_key=True)        # 'HEIDEL'
    WhsName = Column(String(64), nullable=False)
    Inactive = Column(String(1), nullable=False, default="N")   # SAP Y/N
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class OITM(Base):
    """Item master (SAP B1 OITM). ItemCode is the natural PK (varchar, not a serial)."""
    __tablename__ = "OITM"
    __table_args__ = {"schema": "icb_sap"}
    ItemCode = Column(String(64), primary_key=True)
    ItemName = Column(String(255))
    InvntryUom = Column(String(16))
    ItmsGrpCod = Column(Integer)                          # derived from the code prefix
    U_ItemGroup = Column(String(32))
    U_LastPurchasePrice = Column(Numeric(18, 4))
    U_LastEvaluatedPrice = Column(Numeric(18, 4))
    U_Manufacturer = Column(String(128))
    MinLevel = Column(Numeric(18, 3))
    validFor = Column(String(1), nullable=False, default="Y")
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class OITW(Base):
    """Item-warehouse stock (SAP B1 OITW). Composite PK (ItemCode, WhsCode);
    `Available` is a STORED generated column (created in 0008 DDL)."""
    __tablename__ = "OITW"
    __table_args__ = {"schema": "icb_sap"}
    ItemCode = Column(String(64), primary_key=True)
    WhsCode = Column(String(8), primary_key=True)
    OnHand = Column(Numeric(18, 3), nullable=False, default=0)
    IsCommited = Column(Numeric(18, 3), nullable=False, default=0)
    OnOrder = Column(Numeric(18, 3), nullable=False, default=0)
    # GENERATED ALWAYS ... STORED — SQLAlchemy excludes it from INSERTs, reads it back.
    Available = Column(Numeric(18, 3), Computed('"OnHand" - "IsCommited" + "OnOrder"', persisted=True))
    AvgPrice = Column(Numeric(18, 4))
    updated_at = Column(DateTime(timezone=True), default=_utcnow)


__all__ = ["OWHS", "OITM", "OITW"]
