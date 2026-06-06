"""MES domain models — the `icb_mes` schema (WO v4.13, Phase 2A).

All 12 tables defined per WO v4.13 §3.1. They share the single declarative
`Base` from `app.database`, each pinned to the `icb_mes` schema via
`__table_args__`.

Cross-schema FK note (important):
  The legacy Cost-Calculator models in `app.database` are schema-less in the
  metadata (they rely on the role search_path to land in `icb_costings`), so a
  declarative `ForeignKey("icb_costings.calculations.id")` cannot resolve at
  mapper-config time. Therefore the **cross-schema** columns below
  (`calculation_record_id`, `branch_id`, every `*_user_id`) are plain `Integer`
  here, and their FK constraints to `icb_costings.*` are created in migration
  `0003` via `op.create_foreign_key(... referent_schema='icb_costings')`.
  `alembic/env.py` excludes cross-schema FKs from autogenerate so `alembic check`
  stays clean. Intra-`icb_mes` FKs ARE declared here (they resolve fine).

Other deviations (documented in the WO as-shipped note + ADR 0005/0007):
  * `production_jobs` carries ALL 18 MES-lifecycle columns moved from
    `icb_costings.calculations` (the spec named only 7), plus a new `accepted_at`.
  * Spec sign-off actors are `*_user_id` FKs; the mockup carries display NAMES,
    so each keeps a nullable `*_by_name` string seeded losslessly.
  * Mockup business keys with no numeric id are preserved:
    `rework_tickets.ticket_code`, `demand_lines.job_ref`.

Status/enum-like fields are VARCHAR (matching `calculations.status`) with allowed
values in comments — avoids native PG ENUM churn in migrations.
"""
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text,
    UniqueConstraint, text as sa_text,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.database import Base

# Cross-schema FK constraints to create in migration 0003 (icb_mes -> icb_costings).
# (source_table, local_col, referent_table, ondelete)
CROSS_SCHEMA_FKS = [
    ("production_jobs", "calculation_record_id", "calculations", "RESTRICT"),
    ("production_jobs", "branch_id", "branches", "RESTRICT"),
    ("work_orders", "assigned_to_user_id", "users", "SET NULL"),
    ("tasks", "completed_by_user_id", "users", "SET NULL"),
    ("sign_offs", "signed_off_by_user_id", "users", "SET NULL"),
    ("planning_acks", "acknowledged_by_user_id", "users", "SET NULL"),
    ("stock_counts", "counted_by_user_id", "users", "SET NULL"),
    ("stock_counts", "branch_id", "branches", "RESTRICT"),
    ("discrepancies", "raised_to_buyer_user_id", "users", "SET NULL"),
    ("po_suggestions", "raised_by_user_id", "users", "SET NULL"),
]


def _utcnow():
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# 1. production_jobs — central MES entity, 1:1 with an accepted calculation.
# ─────────────────────────────────────────────────────────────────────────────
class ProductionJob(Base):
    __tablename__ = "production_jobs"
    __table_args__ = (
        Index("ix_production_jobs_status_start", "status", "planned_start_date"),
        Index("ix_production_jobs_branch_id", "branch_id"),
        Index("ix_production_jobs_calculation_record_id", "calculation_record_id"),
        {"schema": "icb_mes"},
    )

    id = Column(Integer, primary_key=True)
    # cross-schema -> icb_costings.calculations.id (FK in 0003, RESTRICT). NULLABLE from
    # 0006 (WO v4.21): workbook-imported jobs have no originating calculation. UNIQUE kept
    # (Postgres allows multiple NULLs; quote-born jobs still can't share a calc).
    calculation_record_id = Column(Integer, nullable=True, unique=True)
    # cross-schema -> icb_costings.branches.id (FK in 0003, RESTRICT); NOT NULL from 0005 (WO v4.16)
    branch_id = Column(Integer, nullable=False)
    job_number = Column(String(32), unique=True)          # derived from Q-32891 -> 32891
    status = Column(String(24), nullable=False, default="accepted")
    # accepted | pre_job_sent | pre_job_confirmed | planning | in_production | completed
    accepted_at = Column(DateTime(timezone=True))         # NEW (spec); no source column in calculations

    # ── WO v4.21 (0006): workbook-imported jobs (no originating calculation) ──
    source = Column(String(16), nullable=False, default="quote", server_default="quote")
    # carriers populated for workbook jobs; quote-born jobs leave these NULL and derive
    # customer/description/selling from the calc join (read-path falls back to carriers).
    customer_name = Column(String(128))
    description = Column(String(255))
    selling_zar = Column(Float)

    # ── 18 columns moved from icb_costings.calculations (ordinals 15-32) ──
    pre_job_sent_at = Column(DateTime(timezone=True))
    pre_job_confirmed_at = Column(DateTime(timezone=True))
    job_number_assigned = Column(String(32))
    repair_phases_json = Column(Text)
    pre_job_signoff_sales_at = Column(DateTime(timezone=True))
    pre_job_signoff_sales_by = Column(String(64))
    pre_job_signoff_sales_attestation = Column(Text)
    pre_job_signoff_production_at = Column(DateTime(timezone=True))
    pre_job_signoff_production_by = Column(String(64))
    pre_job_signoff_production_attestation = Column(Text)
    planning_acknowledged_at = Column(DateTime(timezone=True))   # spec: planning_ack_at
    planning_acknowledged_by = Column(String(64))
    chassis_eta = Column(DateTime(timezone=True))
    chassis_eta_captured_at = Column(DateTime(timezone=True))
    chassis_eta_captured_by = Column(String(64))
    chassis_data_json = Column(Text)
    chassis_received_at = Column(DateTime(timezone=True))
    chassis_received_by = Column(String(64))

    # ── production scheduling ──
    planned_start_date = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# 2. work_orders — per-bay work parcels for a production job.
# ─────────────────────────────────────────────────────────────────────────────
class WorkOrder(Base):
    __tablename__ = "work_orders"
    __table_args__ = (
        Index("ix_work_orders_production_job_id", "production_job_id"),
        {"schema": "icb_mes"},
    )
    id = Column(Integer, primary_key=True)
    production_job_id = Column(
        Integer, ForeignKey("icb_mes.production_jobs.id", ondelete="CASCADE"), nullable=False
    )
    bay = Column(String(32))                       # "Vacuum-1", "Pre-Assy"
    sequence = Column(Integer)
    status = Column(String(24))
    assigned_to_user_id = Column(Integer)          # cross-schema -> icb_costings.users.id (FK in 0003)
    assigned_to_name = Column(String(64))          # mockup display name (FK companion)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# 3. tasks — per-work-order checklist items.
# ─────────────────────────────────────────────────────────────────────────────
class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_work_order_id", "work_order_id"), {"schema": "icb_mes"})
    id = Column(Integer, primary_key=True)
    work_order_id = Column(
        Integer, ForeignKey("icb_mes.work_orders.id", ondelete="CASCADE"), nullable=False
    )
    description = Column(Text)
    sequence = Column(Integer)
    required = Column(Boolean, default=True)
    completed_at = Column(DateTime(timezone=True))
    completed_by_user_id = Column(Integer)         # cross-schema -> icb_costings.users.id (FK in 0003)
    completed_by_name = Column(String(64))
    created_at = Column(DateTime(timezone=True), default=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# 4. sign_offs — captured at task or work-order completion.
# ─────────────────────────────────────────────────────────────────────────────
class SignOff(Base):
    __tablename__ = "sign_offs"
    __table_args__ = (Index("ix_sign_offs_work_order_id", "work_order_id"), {"schema": "icb_mes"})
    id = Column(Integer, primary_key=True)
    work_order_id = Column(
        Integer, ForeignKey("icb_mes.work_orders.id", ondelete="CASCADE"), nullable=False
    )
    task_id = Column(Integer, ForeignKey("icb_mes.tasks.id", ondelete="SET NULL"), nullable=True)
    signed_off_by_user_id = Column(Integer)        # cross-schema -> icb_costings.users.id (FK in 0003)
    signed_off_by_name = Column(String(64))
    signed_at = Column(DateTime(timezone=True))
    comment = Column(Text)
    photo_count = Column(Integer, default=0)
    severity = Column(String(16))                  # info | minor | major | critical
    created_at = Column(DateTime(timezone=True), default=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# 5. photos — attached to a sign-off.
# ─────────────────────────────────────────────────────────────────────────────
class Photo(Base):
    __tablename__ = "photos"
    __table_args__ = (Index("ix_photos_sign_off_id", "sign_off_id"), {"schema": "icb_mes"})
    id = Column(Integer, primary_key=True)
    sign_off_id = Column(
        Integer, ForeignKey("icb_mes.sign_offs.id", ondelete="CASCADE"), nullable=False
    )
    file_path = Column(String(500))                # resolved by the FileStore Protocol (Phase 3)
    caption = Column(String(255))
    uploaded_at = Column(DateTime(timezone=True), default=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# 6. rework_tickets — raised when a QC sign-off fails.
# ─────────────────────────────────────────────────────────────────────────────
class ReworkTicket(Base):
    __tablename__ = "rework_tickets"
    __table_args__ = (Index("ix_rework_tickets_sign_off_id", "sign_off_id"), {"schema": "icb_mes"})
    id = Column(Integer, primary_key=True)
    sign_off_id = Column(
        Integer, ForeignKey("icb_mes.sign_offs.id", ondelete="CASCADE"), nullable=True
    )
    ticket_code = Column(String(32))               # mockup business key e.g. "RW-2089"
    routed_to_bay = Column(String(32))
    status = Column(String(16))                    # open | closed
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    closed_at = Column(DateTime(timezone=True))


# ─────────────────────────────────────────────────────────────────────────────
# 7. planning_slots — Planning Board cells.
# ─────────────────────────────────────────────────────────────────────────────
class PlanningSlot(Base):
    __tablename__ = "planning_slots"
    __table_args__ = (
        Index("ix_planning_slots_production_job_id", "production_job_id"),
        Index("ix_planning_slots_week_lane", "week", "lane"),
        {"schema": "icb_mes"},
    )
    id = Column(Integer, primary_key=True)
    production_job_id = Column(
        Integer, ForeignKey("icb_mes.production_jobs.id", ondelete="SET NULL"), nullable=True
    )
    week = Column(Date)                            # Monday of the week
    bay = Column(String(32))
    lane = Column(String(32))                      # vacuum | panelshop | ...
    slot_position = Column(Integer)                # 1..N within the lane
    status = Column(String(16))                    # unscheduled | scheduled | in_progress | completed
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# 8. planning_acks — planner acknowledgement records.
# ─────────────────────────────────────────────────────────────────────────────
class PlanningAck(Base):
    __tablename__ = "planning_acks"
    __table_args__ = (Index("ix_planning_acks_production_job_id", "production_job_id"), {"schema": "icb_mes"})
    id = Column(Integer, primary_key=True)
    production_job_id = Column(
        Integer, ForeignKey("icb_mes.production_jobs.id", ondelete="CASCADE"), nullable=False
    )
    acknowledged_by_user_id = Column(Integer)      # cross-schema -> icb_costings.users.id (FK in 0003)
    acknowledged_by_name = Column(String(64))
    acknowledged_at = Column(DateTime(timezone=True))
    chassis_eta_at_ack = Column(DateTime(timezone=True))
    notes = Column(Text)


# ─────────────────────────────────────────────────────────────────────────────
# 9. stock_counts — Stores cycle counts.
# ─────────────────────────────────────────────────────────────────────────────
class StockCount(Base):
    __tablename__ = "stock_counts"
    __table_args__ = (
        Index("ix_stock_counts_status_counted", "status", "counted_at"),
        Index("ix_stock_counts_branch_id", "branch_id"),
        {"schema": "icb_mes"},
    )
    id = Column(Integer, primary_key=True)
    sap_code = Column(String(100))
    bin = Column(String(32))
    sap_stock_at_count = Column(Float)
    physical_count = Column(Float)
    counted_by_user_id = Column(Integer)           # cross-schema -> icb_costings.users.id (FK in 0003)
    counted_by_name = Column(String(64))
    counted_at = Column(DateTime(timezone=True))
    status = Column(String(16))                    # confirmed | discrepancy | pending
    branch_id = Column(Integer, nullable=False)    # cross-schema -> icb_costings.branches.id (FK in 0003); NOT NULL from 0005 (WO v4.16)
    created_at = Column(DateTime(timezone=True), default=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# 10. discrepancies — buyer notifications from Stores.
# ─────────────────────────────────────────────────────────────────────────────
class Discrepancy(Base):
    __tablename__ = "discrepancies"
    __table_args__ = (Index("ix_discrepancies_stock_count_id", "stock_count_id"), {"schema": "icb_mes"})
    id = Column(Integer, primary_key=True)
    stock_count_id = Column(
        Integer, ForeignKey("icb_mes.stock_counts.id", ondelete="CASCADE"), nullable=False
    )
    raised_to_buyer_user_id = Column(Integer)      # cross-schema -> icb_costings.users.id (FK in 0003)
    raised_to_buyer_name = Column(String(64))
    raised_at = Column(DateTime(timezone=True))
    notes = Column(Text)
    resolved_at = Column(DateTime(timezone=True))
    resolution_notes = Column(Text)


# ─────────────────────────────────────────────────────────────────────────────
# 11. po_suggestions — buyer's PR queue.
# ─────────────────────────────────────────────────────────────────────────────
class POSuggestion(Base):
    __tablename__ = "po_suggestions"
    __table_args__ = (Index("ix_po_suggestions_status_urgency", "status", "urgency"), {"schema": "icb_mes"})
    id = Column(Integer, primary_key=True)
    sap_code = Column(String(100))
    qty = Column(Float)
    suggested_supplier = Column(String(128))
    last_price = Column(Float)
    total = Column(Float)
    need_by = Column(Date)
    urgency = Column(String(16))                   # critical | order_now | advisory
    status = Column(String(16))                    # pending | raised | deferred
    pr_number = Column(String(32))                 # populated after SAP roundtrip
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    raised_at = Column(DateTime(timezone=True))
    raised_by_user_id = Column(Integer)            # cross-schema -> icb_costings.users.id (FK in 0003)
    raised_by_name = Column(String(64))
    deferred_until = Column(Date)
    jobs_impacted = Column(JSONB)                  # list[str] of job refs (WO v4.15 Q3); seeded from mockup


# ─────────────────────────────────────────────────────────────────────────────
# 12. demand_lines — per-BOM-line demand against the schedule (cached).
# ─────────────────────────────────────────────────────────────────────────────
class DemandLine(Base):
    __tablename__ = "demand_lines"
    __table_args__ = (
        Index("ix_demand_lines_sap_week", "sap_code", "week_bucket"),
        Index("ix_demand_lines_production_job_id", "production_job_id"),
        {"schema": "icb_mes"},
    )
    id = Column(Integer, primary_key=True)
    sap_code = Column(String(100))
    qty = Column(Float)
    need_by = Column(Date)
    production_job_id = Column(
        Integer, ForeignKey("icb_mes.production_jobs.id", ondelete="SET NULL"), nullable=True
    )
    job_ref = Column(String(32))                   # mockup job_id e.g. "2025-1138" (may not resolve)
    bom_line_ref = Column(String(64))
    week_bucket = Column(String(16))               # e.g. 2026-W23
    created_at = Column(DateTime(timezone=True), default=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# 13. mes_materials — MES materials catalogue (master data). WO v4.15 (Q1).
#     Self-contained in icb_mes: the costing catalogue (icb_costings.materials)
#     lacks abc_class/dept/lead_days and uses different codes, so the catalogue
#     the Materials/Buying/Stores screens need lives here, seeded from the mockup.
#     Reads MAY LEFT JOIN icb_costings.materials ON sap_code for reconciliation.
#     Table is "mes_materials" (NOT "materials"): the connection search_path is
#     `icb_mes, icb_costings, public`, so a bare `materials` would SHADOW the
#     schema-less costing Material model and break /calculator. Class stays MesMaterial.
# ─────────────────────────────────────────────────────────────────────────────
class MesMaterial(Base):
    __tablename__ = "mes_materials"
    __table_args__ = (
        Index("ix_mes_materials_dept_abc", "dept", "abc_class"),
        {"schema": "icb_mes"},
    )
    id = Column(Integer, primary_key=True)
    sap_code = Column(String(100), nullable=False, unique=True)
    description = Column(String(255))
    supplier = Column(String(128))                 # supplier NAME (joins icb_mes.suppliers.name)
    lead_days = Column(Integer)
    last_price = Column(Float)
    abc_class = Column(String(1))                  # A | B | C
    dept = Column(String(16))                      # vacuum | panelshop | assy | paint
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# 14. stock_positions — current SAP stock per material (one row per sap_code).
#     Refreshed from SAP in production (mocked here). WO v4.15 (Q1).
# ─────────────────────────────────────────────────────────────────────────────
class StockPosition(Base):
    __tablename__ = "stock_positions"
    __table_args__ = ({"schema": "icb_mes"},)
    id = Column(Integer, primary_key=True)
    sap_code = Column(String(100), nullable=False, unique=True)
    sap_stock = Column(Float)
    allocated = Column(Float)
    free = Column(Float)
    open_po_qty = Column(Float)
    open_po_eta = Column(Date)
    last_refreshed = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# 15. suppliers — supplier master. No icb_costings.suppliers exists (verified
#     against information_schema), so this is the system of record. WO v4.15 (§0.1/Q1).
# ─────────────────────────────────────────────────────────────────────────────
class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = ({"schema": "icb_mes"},)
    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False, unique=True)
    contact_person = Column(String(128))
    payment_terms = Column(String(32))
    phone = Column(String(32))
    created_at = Column(DateTime(timezone=True), default=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# 16. session_branches — active branch per login session (WO v4.16, §0.1).
#     Keyed by the costing UserSession.id (UUID string). Soft mapping (no FK):
#     ephemeral session state; an orphaned row is harmless.
# ─────────────────────────────────────────────────────────────────────────────
class SessionBranch(Base):
    __tablename__ = "session_branches"
    __table_args__ = ({"schema": "icb_mes"},)
    session_id = Column(String(36), primary_key=True)  # icb_costings.user_sessions.id
    branch_id = Column(Integer, nullable=False)         # -> icb_costings.branches.id (no FK; soft)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# 17. live_daily_count — Stores physical counts (WO v4.22, §0.2). Loaded from
#     "02 - Live Daily Count 2026.xlsx"; the 6 category sheets (ALU/STEEL/TIMBER/
#     EPS/PU/COILS) melted into one row per counted item, tagged with `category`.
#     NUMERIC columns from the WO §3.1 sketch are Float here, matching every other
#     icb_mes money/qty column (po_suggestions.last_price, stock_counts.* etc.).
# ─────────────────────────────────────────────────────────────────────────────
class LiveDailyCount(Base):
    __tablename__ = "live_daily_count"
    __table_args__ = (
        Index("ix_live_daily_count_sap_code", "sap_code"),
        Index("ix_live_daily_count_category", "category"),
        {"schema": "icb_mes"},
    )
    id = Column(Integer, primary_key=True)
    sap_code = Column(String(64), nullable=False)
    description = Column(String(255))
    uom = Column(String(16))
    category = Column(String(32), nullable=False)   # ALU | STEEL | TIMBER | EPS | PU | COILS
    on_hand = Column(Float)
    rejected_stock = Column(Float)
    max_stock = Column(Float)
    top_up = Column(Float)
    ordered = Column(Float)
    price = Column(Float)
    variance_qty = Column(Float)
    variance_value = Column(Float)
    counted_at = Column(DateTime(timezone=True), default=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# 18. chassis_register — chassis lifecycle (WO v4.22, §0.3). Loaded from
#     "Book1 TRUCK REGISTER 2026.xlsx / JOBS & CHASSIS": 17 hoisted columns +
#     the full 112-col source row preserved in `raw_row_json` (so future fields
#     don't require a re-import). Linked to production_jobs by `job_number` (soft).
# ─────────────────────────────────────────────────────────────────────────────
class ChassisRegister(Base):
    __tablename__ = "chassis_register"
    __table_args__ = (
        Index("ix_chassis_register_job_number", "job_number"),
        Index("ix_chassis_register_vehicle_id_no", "vehicle_id_no"),
        {"schema": "icb_mes"},
    )
    id = Column(Integer, primary_key=True)
    job_number = Column(String(32))
    customer_name = Column(String(255))
    telephone = Column(String(64))
    contact_person = Column(String(255))
    vehicle_id_no = Column(String(64))     # VIN
    model = Column(String(64))
    make = Column(String(64))
    description = Column(String(255))       # "Existing Chassis", "Freezer Body", ...
    submit_status = Column(String(64))      # "Documents Done", "CANCELLED", ...
    date_received_1 = Column(Date)
    vcl_1 = Column(String(64))
    date_left_1 = Column(Date)
    dcl_1 = Column(String(64))
    date_received_2 = Column(Date)
    vcl_2 = Column(String(64))
    date_left_2 = Column(Date)
    dcl_2 = Column(String(64))
    raw_row_json = Column(JSONB)            # full 112-col source row (future-proofing)
    imported_at = Column(DateTime(timezone=True), default=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# 19. bom_rules — rules-engine geometry rules (WO v4.25, §3.1). One row per
#     (body_type × section × panel × output_field); `formula_expression` is an
#     expression string run by the AST-safe evaluator. Seeded from the v4.24 spike's
#     geometry.py. `panel` carries the foam/skin layer ('Floor (foam)'/'Floor (skin)')
#     since a panel face has two material layers in the BOM.
# ─────────────────────────────────────────────────────────────────────────────
class BomRule(Base):
    __tablename__ = "bom_rules"
    __table_args__ = (
        Index("ix_bom_rules_body_section", "body_type", "section", "panel"),
        {"schema": "icb_mes"},
    )
    id = Column(Integer, primary_key=True)
    body_type = Column(String(32), nullable=False)        # 'Freezer' (v4.25 scope)
    section = Column(String(64), nullable=False)           # 'Vacuum Materials'
    panel = Column(String(64), nullable=False)             # 'Roof (foam)', 'Floor (skin)', ...
    output_field = Column(String(32), nullable=False)      # 'qty' (v4.25); v4.27 adds others
    formula_expression = Column(Text, nullable=False)      # 'ceil((length_mm - 275) / 1220)'
    priority = Column(Integer, nullable=False, default=100, server_default="100")
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    created_by = Column(String(128))
    updated_by = Column(String(128))


# ─────────────────────────────────────────────────────────────────────────────
# 20. bom_rule_lookups — description/code resolution data (WO v4.25, §3.1 + §0
#     nuance). v4.25 seeds lookup_type='spec_to_sap_code' (key '<material>|<thickness>'
#     -> value SAP ItemCode; human description in `notes`) — the 6-row representation
#     of the spike's (material,thickness)->code map (keeps the §5 6-lookup count).
# ─────────────────────────────────────────────────────────────────────────────
class BomRuleLookup(Base):
    __tablename__ = "bom_rule_lookups"
    __table_args__ = (
        Index("ix_bom_rule_lookups_lookup", "body_type", "section", "lookup_type", "lookup_key"),
        UniqueConstraint("body_type", "section", "lookup_type", "lookup_key",
                         name="uq_bom_rule_lookups_key"),
        {"schema": "icb_mes"},
    )
    id = Column(Integer, primary_key=True)
    body_type = Column(String(32), nullable=False)
    section = Column(String(64), nullable=False)
    lookup_type = Column(String(32), nullable=False)      # 'spec_to_sap_code'
    lookup_key = Column(String(255), nullable=False)      # 'EPS 24DV|76'
    lookup_value = Column(String(255), nullable=False)    # 'GRP-MPS-A-0077'
    notes = Column(Text)                                  # human description
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# 21. material_price_overrides — Nadie-managed per-item price overrides (WO v4.25,
#     §0.5). Pricing precedence: an active override (valid_from <= today AND
#     (valid_to IS NULL OR valid_to >= today)) wins; else fall back to
#     icb_sap.OITM.U_LastPurchasePrice. Empty initially (the v4.24 spike found OITM
#     diverges from the Module's internal prices, −12%…+18%).
# ─────────────────────────────────────────────────────────────────────────────
class MaterialPriceOverride(Base):
    __tablename__ = "material_price_overrides"
    __table_args__ = (
        Index("ix_material_price_overrides_sap_code_valid", "sap_code", "valid_from", "valid_to"),
        {"schema": "icb_mes"},
    )
    id = Column(Integer, primary_key=True)
    sap_code = Column(String(64), nullable=False)         # -> icb_sap.OITM.ItemCode (no FK; soft)
    override_price = Column(Numeric(18, 4), nullable=False)
    reason = Column(Text)
    valid_from = Column(Date, nullable=False, default=date.today, server_default=sa_text("CURRENT_DATE"))
    valid_to = Column(Date)                               # null = current
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    created_by = Column(String(128))
    updated_by = Column(String(128))


__all__ = [
    "ProductionJob", "WorkOrder", "Task", "SignOff", "Photo", "ReworkTicket",
    "PlanningSlot", "PlanningAck", "StockCount", "Discrepancy", "POSuggestion", "DemandLine",
    "MesMaterial", "StockPosition", "Supplier", "SessionBranch",
    "LiveDailyCount", "ChassisRegister",
    "BomRule", "BomRuleLookup", "MaterialPriceOverride",
    "CROSS_SCHEMA_FKS",
]
