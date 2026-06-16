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
    ("chassis_records", "dealer_id", "customers", "SET NULL"),   # WO v4.34.1 §0.3 (0022)
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
        Index("ix_production_jobs_chassis_record_id", "chassis_record_id"),   # WO v4.29 (0014)
        Index("ix_production_jobs_job_number", "job_number"),                 # WO v4.34 (0020)
        {"schema": "icb_mes"},
    )

    id = Column(Integer, primary_key=True)
    # cross-schema -> icb_costings.calculations.id (FK in 0003, RESTRICT). NULLABLE from
    # 0006 (WO v4.21): workbook-imported jobs have no originating calculation. UNIQUE kept
    # (Postgres allows multiple NULLs; quote-born jobs still can't share a calc).
    calculation_record_id = Column(Integer, nullable=True, unique=True)
    # cross-schema -> icb_costings.branches.id (FK in 0003, RESTRICT); NOT NULL from 0005 (WO v4.16)
    branch_id = Column(Integer, nullable=False)
    # WO v4.34 §0.7 (0020): UNIQUE dropped — job_number is the NUMERIC core of the quote
    # (A32744/06/2026 -> 32744). Numeric cores collide across letter prefixes, so id stays the
    # true PK; non-unique ix_production_jobs_job_number (declared in __table_args__).
    job_number = Column(String(32))
    job_number_source = Column(String(16))                # quote_derived | sap_assigned | manual
    job_number_locked = Column(Boolean, nullable=False,   # §0.9 — TRUE locks override post-SAP-retirement
                               server_default=sa_text("false"), default=False)
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
    # DEPRECATED-as-write per ADR 0016 (WO v4.29) — see the DB COMMENT (matched here so `alembic check`
    # stays clean). Reads prefer the read-bridge JOIN (chassis_records.lifecycle_events via
    # chassis_record_id); this column is a transitional fallback for legacy rows.
    chassis_received_at = Column(
        DateTime(timezone=True),
        comment="DEPRECATED as write column per ADR 0016 (v4.29). Reads prefer "
                "JOIN(chassis_records.lifecycle_events); retained as legacy fallback.",
    )
    chassis_received_by = Column(String(64))

    # ── production scheduling ──
    planned_start_date = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))

    # ── WO v4.27 (0011): BOM persistence link ──
    # current_bom_id -> icb_mes.generated_boms.id; the FK is added in migration 0011
    # (column-on-model / FK-in-migration) to avoid the production_jobs <-> generated_boms
    # create_all cycle. bom_status: pending | complete | incomplete | manual.
    current_bom_id = Column(Integer, nullable=True)
    bom_status = Column(String(16), nullable=False, default="pending", server_default="pending")

    # ── WO v4.28 (0012): chassis link ──
    # chassis_record_id -> icb_mes.chassis_records.id; FK added in migration 0012 (column-on-model /
    # FK-in-migration; nullable, ON DELETE RESTRICT). The chassis_data_json blob stays for back-compat.
    # WO v4.29 (0014): backfilled from the job_number match + indexed (the Index is declared in
    # __table_args__ to match the migration's name) for the chassis read-bridge JOIN (§0.3).
    # Postgres does not auto-index a FK's referencing column.
    chassis_record_id = Column(Integer, nullable=True)

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
# 8b. production_jobs_audit — workflow state-transition trail (WO v4.34.2 §0.6).
#     Append-only; one row per transition. First (only-in-v4.34.2) consumer is the
#     scheduled → unscheduled revert. previous/new_status are the SCHEDULING state
#     (slot status), NOT the job lifecycle status — a scheduled job's production_jobs.status
#     stays 'planning' throughout (ADR 0008 §0.4), so the transition lives on the slot.
# ─────────────────────────────────────────────────────────────────────────────
class ProductionJobAudit(Base):
    __tablename__ = "production_jobs_audit"
    __table_args__ = (
        Index("ix_production_jobs_audit_job_id", "production_job_id"),
        Index("ix_production_jobs_audit_created_at", "created_at"),
        {"schema": "icb_mes"},
    )
    id = Column(Integer, primary_key=True)
    # ON DELETE CASCADE — matches the other job-children (work_orders, planning_acks). Production jobs
    # have no delete endpoint in prod, so this only ever fires in test teardown (where the trail rides
    # along with its job); the audit table is otherwise append-only.
    production_job_id = Column(
        Integer, ForeignKey("icb_mes.production_jobs.id", ondelete="CASCADE"), nullable=False
    )
    action = Column(String(32), nullable=False, default="revert_to_unscheduled")  # extensible discriminator
    previous_status = Column(String(24))           # scheduling state before, e.g. 'scheduled'
    new_status = Column(String(24))                # scheduling state after,  e.g. 'unscheduled'
    # the deleted slot's placement — NO FK (the planning_slots row is removed on revert)
    previous_slot_id = Column(Integer)
    previous_lane = Column(String(32))
    previous_bay = Column(String(32))
    previous_week = Column(Date)
    user_id = Column(Integer)                      # cross-schema -> icb_costings.users.id (FK SET NULL in 0023)
    user_name = Column(String(64))                 # snapshot so the trail survives a user rename/delete
    reason = Column(Text)                          # optional, <=500 chars (server-enforced); empty allowed
    created_at = Column(DateTime(timezone=True), default=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# 8c. production_job_bay_events — JOB-centric bay events (WO v4.35 §0.19, STRETCH).
#     Distinct from chassis_lifecycle_events (chassis-centric): this records that a JOB's panels
#     arrived in a bay ('panels_arrived_in_bay'), the panel-side of the merge. The chassis side stays
#     on chassis_lifecycle_events ('assembly_assigned'). When BOTH point at the same bay + the job's
#     chassis, the bay is "ready to merge" (see services.chassis.compute_bay_merge_readiness).
# ─────────────────────────────────────────────────────────────────────────────
class ProductionJobBayEvent(Base):
    __tablename__ = "production_job_bay_events"
    __table_args__ = (
        Index("ix_production_job_bay_events_job_bay", "production_job_id", "bay_id"),
        {"schema": "icb_mes"},
    )
    id = Column(Integer, primary_key=True)
    production_job_id = Column(
        Integer, ForeignKey("icb_mes.production_jobs.id", ondelete="CASCADE"), nullable=False
    )
    bay_id = Column(
        Integer, ForeignKey("icb_mes.assembly_bays.id", ondelete="CASCADE"), nullable=False
    )
    event_type = Column(String(32), nullable=False)   # 'panels_arrived_in_bay' (ALLOWED_BAY_EVENT_TYPES)
    user_id = Column(Integer)                          # cross-schema -> icb_costings.users.id (FK SET NULL in 0024)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=_utcnow)


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
        UniqueConstraint("body_type", "section", "panel", "output_field",
                         name="uq_bom_rules_body_section_panel_field"),  # WO v4.26 §0.5 (dup-seed guard)
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
    created_by = Column(String(128))                      # WO v4.26 — admin CRUD audit (§0.4)
    updated_by = Column(String(128))


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


# ─────────────────────────────────────────────────────────────────────────────
# 22. bom_spec_options — DDM dropdown catalogue / early-binding data model (WO v4.26 §3.1).
#     One row per (spec_field_type × body_type × spec_value): the value a formula consumes +
#     the dropdown label Nadie sees. Most rows are body_type='*' (the DDM options are
#     field-scoped, largely body-agnostic); the resolver tries the exact body_type then '*'.
#     sap_code is usually NULL — the panel's SAP code early-binds at the (material × thickness)
#     COMBINATION via bom_rule_lookups, NOT per single dropdown (ADR 0014); populated only for
#     genuinely 1:1-coded options. Validated against icb_sap.OITM at the app layer (no FK).
# ─────────────────────────────────────────────────────────────────────────────
class BomSpecOption(Base):
    __tablename__ = "bom_spec_options"
    __table_args__ = (
        Index("ix_bom_spec_options_field_body", "spec_field_type", "body_type", "active"),
        UniqueConstraint("spec_field_type", "body_type", "section", "spec_value",
                         name="uq_bom_spec_options_field_body_value"),
        {"schema": "icb_mes"},
    )
    id = Column(Integer, primary_key=True)
    spec_field_type = Column(String(64), nullable=False)   # 'roof_material', 'roof_material_thickness'
    body_type = Column(String(32), nullable=False)         # 'Freezer' … or '*' for cross-body
    section = Column(String(64), nullable=False, default="Vacuum Materials",
                     server_default="Vacuum Materials")
    option_label = Column(String(255), nullable=False)     # 'EPS 24DV' shown in the dropdown
    spec_value = Column(String(255), nullable=False)       # the value formulas/lookups consume
    sap_code = Column(String(64))                          # usually NULL (combination-bound; ADR 0014)
    is_default = Column(Boolean, nullable=False, default=False, server_default=sa_text("false"))
    priority = Column(Integer, nullable=False, default=100, server_default="100")
    active = Column(Boolean, nullable=False, default=True, server_default=sa_text("true"))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    created_by = Column(String(128))
    updated_by = Column(String(128))


# ─────────────────────────────────────────────────────────────────────────────
# 23. generated_boms — immutable, versioned BOM snapshot per production job
#     (WO v4.27 §0.3/§0.8). One row per BOM-on-accept; each re-accept adds a new
#     version. `current` flags the active version — the partial-unique index enforces
#     at most one current=true per job. production_jobs.current_bom_id points back to it
#     (that FK is created in 0011, not here, to avoid a create_all cycle).
# ─────────────────────────────────────────────────────────────────────────────
class GeneratedBom(Base):
    __tablename__ = "generated_boms"
    __table_args__ = (
        UniqueConstraint("production_job_id", "version", name="uq_generated_boms_job_version"),
        # at most one current BOM per job (partial unique)
        Index("ux_generated_boms_current", "production_job_id",
              unique=True, postgresql_where=sa_text('"current"')),
        Index("ix_generated_boms_production_job_id", "production_job_id"),
        {"schema": "icb_mes"},
    )
    id = Column(Integer, primary_key=True)
    production_job_id = Column(
        Integer, ForeignKey("icb_mes.production_jobs.id", ondelete="CASCADE"), nullable=False
    )
    version = Column(Integer, nullable=False, default=1, server_default="1")
    bom_status = Column(String(16), nullable=False, default="complete", server_default="complete")
    # complete | incomplete | manual
    grand_total = Column(Numeric(18, 4))
    current = Column(Boolean, nullable=False, default=True, server_default=sa_text("true"))
    metadata_json = Column(JSONB)
    generated_at = Column(DateTime(timezone=True), default=_utcnow, server_default=sa_text("now()"))
    generated_by = Column(String(128))


# ─────────────────────────────────────────────────────────────────────────────
# 24. bom_lines — the line items of a generated_boms snapshot (WO v4.27 §0.8).
# ─────────────────────────────────────────────────────────────────────────────
class BomLine(Base):
    __tablename__ = "bom_lines"
    __table_args__ = (
        Index("ix_bom_lines_generated_bom_id", "generated_bom_id"),
        Index("ix_bom_lines_sap_code", "sap_code"),
        {"schema": "icb_mes"},
    )
    id = Column(Integer, primary_key=True)
    generated_bom_id = Column(
        Integer, ForeignKey("icb_mes.generated_boms.id", ondelete="CASCADE"), nullable=False
    )
    sap_code = Column(String(64), nullable=False)
    description = Column(String(255))
    qty = Column(Numeric(18, 6), nullable=False)
    unit_price = Column(Numeric(18, 4))
    line_total = Column(Numeric(18, 4))
    section = Column(String(64))
    source = Column(String(16), nullable=False, default="rule", server_default="rule")  # rule | manual
    price_source = Column(String(16))                     # 'override' | 'sap' (v4.25 pricing)
    line_order = Column(Integer, nullable=False, default=0, server_default="0")


# ─────────────────────────────────────────────────────────────────────────────
# 25. chassis_records — VIN-anchored chassis lifecycle record (WO v4.28 §0.2).
#     Relational successor to the v4.22 chassis_register workbook table (which stays for
#     rollback). One row per VIN; cycle detail lives in chassis_lifecycle_events.
# ─────────────────────────────────────────────────────────────────────────────
class ChassisRecord(Base):
    __tablename__ = "chassis_records"
    __table_args__ = (
        UniqueConstraint("vin", name="uq_chassis_records_vin"),
        Index("ix_chassis_records_job_number", "job_number"),
        Index("ix_chassis_records_dealer_id", "dealer_id"),    # WO v4.34.1 §0.3 (0022) — keeps autogenerate clean
        {"schema": "icb_mes"},
    )
    id = Column(Integer, primary_key=True)
    # WO v4.34 §0.3 (0020): VIN nullable — unknown until receive ('expected' chassis carry NULL).
    # uq_chassis_records_vin stays; Postgres keeps NULLs out of the unique index natively.
    vin = Column(String(32))                               # vehicle_id_no (VIN anchor; UNIQUE when set)
    job_number = Column(String(32))                        # soft link (text; no FK — register provenance)
    customer_name = Column(String(128))
    contact_person = Column(String(128))
    telephone = Column(String(64))
    make = Column(String(64))
    model = Column(String(64))
    description = Column(String(255))
    status = Column(String(24), nullable=False, default="received", server_default="received")
    # received | in_workshop | in_assembly | dispatched | returned | expected | expected_orphaned
    # (denormalised from the latest event; 'in_assembly' WO v4.31 §0.12; 'expected' +
    # 'expected_orphaned' WO v4.34 §0.3 for the pipeline — values-in-comments only, NO bay column
    # here: "which bay" is derived from the latest 'assembly_assigned' lifecycle event.
    # WO v4.33 §0.8 (migration 0017): the customer's specified cab-to-body gap. Captured from the
    # quote when known; Simeon enters/verifies it during the chassis VCL (the VCL checklist's
    # body_gap_mm field write-through in services/chassis.capture_event). Pre-Job Cards
    # pre-populate from here and render "Pending — awaiting chassis VCL" while NULL.
    body_gap_mm = Column(Integer)
    submit_status = Column(String(32))                    # legacy register value
    source = Column(String(16), nullable=False, default="register", server_default="register")  # register | vcl_form | manual | pre_job_card | planning_ack (WO v4.34 §3.2/§3.3)
    source_register_id = Column(Integer)                   # originating chassis_register.id (traceability)
    notes = Column(Text)
    # WO v4.34 §0.4 (0020) — pipeline provenance: how + whence this row was created.
    created_via = Column(String(32))                       # pre_job_card | planning_job_create | manual_chassis_menu | legacy_import_v4_28
    created_source_ref = Column(String(64))                # e.g. "A32744/06/2026" or "Planning · Job 32791"
    # WO v4.34.1 §0.3 — the dealer that SUPPLIED this chassis (cross-schema FK → icb_costings.customers
    # with is_dealer=true; plain Integer here, FK created in migration 0022 per ADR 0006, SET NULL).
    dealer_id = Column(Integer)
    vin_source = Column(String(32))                        # WO v4.34.1 §0.17 — VIN provenance: vcl | chassis_page_manual (Gap A) | …
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    created_by = Column(String(128))
    updated_by = Column(String(128))


# ─────────────────────────────────────────────────────────────────────────────
# 26. chassis_lifecycle_events — per-cycle book-in (VCL) / dispatch (DCL) events (WO v4.28 §0.2).
#     Cycle N has up to two events: VCL (paired with date_received_N) + DCL (date_left_N).
#     Multi-cycle chassis (re-visits) carry cycle_number 2+.
# ─────────────────────────────────────────────────────────────────────────────
class ChassisLifecycleEvent(Base):
    __tablename__ = "chassis_lifecycle_events"
    __table_args__ = (
        UniqueConstraint("chassis_record_id", "cycle_number", "event_type",
                         name="uq_chassis_events_record_cycle_type"),
        Index("ix_chassis_events_record", "chassis_record_id"),
        {"schema": "icb_mes"},
    )
    id = Column(Integer, primary_key=True)
    chassis_record_id = Column(
        Integer, ForeignKey("icb_mes.chassis_records.id", ondelete="CASCADE"), nullable=False
    )
    cycle_number = Column(Integer, nullable=False, default=1, server_default="1")
    event_type = Column(String(24), nullable=False)         # 'VCL' (book-in) | 'DCL' (dispatch) | 'assembly_assigned' (WO v4.31 §0.4)
    assembly_bay_id = Column(Integer)  # WO v4.31 §0.4 — plain Integer; FK->icb_mes.assembly_bays created
    # in migration 0016. Set only on 'assembly_assigned' events (the destination bay); NULL for VCL/DCL.
    event_date = Column(Date)                              # date_received_N (VCL) / date_left_N (DCL)
    legacy_reference = Column(String(128))                 # vcl_N / dcl_N free-text carried from the register
    checklist_json = Column(JSONB)                         # structured checklist from the new screens (NULL for legacy)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    created_by = Column(String(128))                       # captured-by (workshop role)


# ─────────────────────────────────────────────────────────────────────────────
# 27. chassis_photos — photo evidence attached to a VCL/DCL event (WO v4.28 §0.2).
#     Local-filesystem storage now; TODO(§5.3/v4.31): swap to a file-store abstraction.
# ─────────────────────────────────────────────────────────────────────────────
class ChassisPhoto(Base):
    __tablename__ = "chassis_photos"
    __table_args__ = (
        Index("ix_chassis_photos_event", "lifecycle_event_id"),
        {"schema": "icb_mes"},
    )
    id = Column(Integer, primary_key=True)
    lifecycle_event_id = Column(
        Integer, ForeignKey("icb_mes.chassis_lifecycle_events.id", ondelete="CASCADE"), nullable=False
    )
    file_path = Column(String(512), nullable=False)        # relative: chassis/{record}/{cycle}/{type}/{id}-{name}
    original_filename = Column(String(255))
    content_type = Column(String(64))
    size_bytes = Column(Integer)
    caption = Column(String(255))
    uploaded_at = Column(DateTime(timezone=True), default=_utcnow)
    uploaded_by = Column(String(128))


# ─────────────────────────────────────────────────────────────────────────────
# 28. parking_bays — the ~24 outside parking slots (WO v4.31 §0.3, ADR 0018).
#     Reference/master data: one row per physical parking bay; seeded ParkingBay-1..24 in 0016.
#     Phase-3 scope renders the parking lane; per-chassis parking allocation is Phase 4 (out of scope).
# ─────────────────────────────────────────────────────────────────────────────
class ParkingBay(Base):
    __tablename__ = "parking_bays"
    __table_args__ = (
        UniqueConstraint("code", name="uq_parking_bays_code"),
        {"schema": "icb_mes"},
    )
    id = Column(Integer, primary_key=True)
    code = Column(String(32), nullable=False)              # 'ParkingBay-1' .. 'ParkingBay-24' (UNIQUE)
    label = Column(String(64))                             # human label, e.g. 'Parking Bay 1'
    sort_order = Column(Integer)                           # 1..N — natural ordering for the lane
    is_active = Column(Boolean, nullable=False, default=True, server_default=sa_text("true"))
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# 29. assembly_bays — the 5 inside assembly bays (WO v4.31 §0.2 — Michael's on-floor count, 10 Jun).
#     Reference/master data: one row per physical assembly bay; seeded AssemblyBay-1..5 in 0016.
#     A chassis is attributed here via an 'assembly_assigned' lifecycle event; its CURRENT bay is
#     DERIVED from that latest event (§0.12 — no denormalised column on chassis_records; see
#     services/chassis.py:_current_assembly_bay_id).
# ─────────────────────────────────────────────────────────────────────────────
class AssemblyBay(Base):
    __tablename__ = "assembly_bays"
    __table_args__ = (
        UniqueConstraint("code", name="uq_assembly_bays_code"),
        {"schema": "icb_mes"},
    )
    id = Column(Integer, primary_key=True)
    code = Column(String(32), nullable=False)              # 'AssemblyBay-1' .. 'AssemblyBay-5' (UNIQUE)
    label = Column(String(64))                             # human label, e.g. 'Assembly Bay 1'
    sort_order = Column(Integer)                           # 1..5 — natural ordering for the lane
    is_active = Column(Boolean, nullable=False, default=True, server_default=sa_text("true"))
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# 30. prejob_templates — Nadie's Pre-Job Card template library (WO v4.33 §0.5/§0.15, ADR 0020).
#     One row per template (23 migrated from the Word originals via review-and-normalize: imported
#     is_active=False, BA/Nadie approve via the admin screen). `sections` is the §0.5 JSONB shape:
#     [{name: "GRP SECTION", items: [{text, note?, sub_items?[], sap_item_code?}]}, ...] — section
#     names/counts vary by product class (SUB FRAME vs STEEL SECTION vs CHASSIS MODIFICATIONS);
#     sap_item_code is the §0.10 stub (lookup mechanism is v4.33.1).
# ─────────────────────────────────────────────────────────────────────────────
class PrejobTemplate(Base):
    __tablename__ = "prejob_templates"
    __table_args__ = (
        UniqueConstraint("name", name="uq_prejob_templates_name"),
        Index("ix_prejob_templates_body_size", "body_type", "size_category", "is_active"),
        {"schema": "icb_mes"},
    )
    id = Column(Integer, primary_key=True)
    body_type = Column(String(32), nullable=False)
    # chiller | freezer | meathanger | bakery | dry_freight | icecream | explosive | medical_waste | trailer
    size_category = Column(String(32))                     # '2.3m' | '3.2m' | 'mid' | 'big' | '15.5m' | ...
    name = Column(String(255), nullable=False)
    product_line = Column(String(24), nullable=False, default="standard", server_default="standard")
    # standard | rhinorange_legacy | rhinorange_2_0  (§0.6: default selector to rhinorange_2_0)
    header_format = Column(String(255))                    # "{size}mm GRP {body_type} Chassis: ..."
    sections = Column(JSONB, nullable=False)
    default_fridge_note = Column(String(255))
    is_active = Column(Boolean, nullable=False, default=False, server_default=sa_text("false"))
    version = Column(Integer, nullable=False, default=1, server_default="1")
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    created_by = Column(String(128))                       # admin CRUD audit (v4.26 pattern)
    updated_by = Column(String(128))


# ─────────────────────────────────────────────────────────────────────────────
# 31. prejob_cards — per-costing Pre-Job Card instance (WO v4.33 §0.1-§0.14, ADR 0020).
#     The 3-role workflow record: Internal Sales creates (created_by_user_id) → Sales Rep +
#     Planner check-sign (either may reject → status back to 'draft' + reject_reason) → both
#     signoffs auto-flip status to 'pre_job_confirmed' (§0.21: ALSO drives the production_jobs
#     pre_job_* status flips — prejob_cards is the source of truth; the legacy job-level signoff
#     columns are NOT written by this flow). Cross-schema *_user_id / calculation_id columns are
#     plain Integers here; their FKs to icb_costings are created in migration 0017 (the 0003/0012
#     idiom). Costing reference is canonical (§0.7) — no separate Pre-Job Card number.
# ─────────────────────────────────────────────────────────────────────────────
class PrejobCard(Base):
    __tablename__ = "prejob_cards"
    __table_args__ = (
        Index("ix_prejob_cards_calculation", "calculation_id"),
        Index("ix_prejob_cards_status", "status"),
        Index("ix_prejob_cards_chassis_record_id", "chassis_record_id"),   # WO v4.34 (0020)
        {"schema": "icb_mes"},
    )
    id = Column(Integer, primary_key=True)
    calculation_id = Column(Integer, nullable=False)       # cross-schema -> icb_costings.calculations (FK in 0017, RESTRICT)
    template_id = Column(Integer,
                         ForeignKey("icb_mes.prejob_templates.id", ondelete="RESTRICT"),
                         nullable=True)                    # NULL = started from blank (edge case)
    body_description = Column(String(255))
    chassis_make_model = Column(String(128))
    vin_number = Column(String(64))                        # nullable until chassis VCL (or TBD for complete-build trailers)
    body_gap_mm = Column(Integer)                          # §0.8 — from quote spec / chassis VCL
    # WO v4.34 §0.5 (0020) — direct FK to the auto-created/linked chassis (ON DELETE SET NULL).
    # Supersedes the indirect card→job→chassis path as the pipeline single source of truth.
    chassis_record_id = Column(Integer)
    body_gap_pending = Column(Boolean, nullable=False, default=True, server_default=sa_text("true"))
    sections = Column(JSONB, nullable=False)               # mutated copy of template.sections (§0.5 shape)
    fridge_ordering_mode = Column(String(24))              # icb_orders | customer_supplies | none
    fridge_model = Column(String(128))
    customer_notes = Column(Text)
    # ── Stage A: Internal Sales creates ──
    created_by_user_id = Column(Integer)                   # cross-schema -> users (FK in 0017, SET NULL)
    # ── Stage B: Sales Rep check ──
    sales_rep_user_id = Column(Integer)                    # cross-schema -> users (FK in 0017, SET NULL)
    sales_rep_signoff_at = Column(DateTime(timezone=True))
    sales_rep_attestation = Column(Text)
    # ── Stage C: Planner check (hasRole('planner') || isAdmin — §0.3; production excluded) ──
    planner_user_id = Column(Integer)                      # cross-schema -> users (FK in 0017, SET NULL)
    planner_signoff_at = Column(DateTime(timezone=True))
    planner_attestation = Column(Text)
    # ── Stage D: lifecycle ──
    status = Column(String(24), nullable=False, default="draft", server_default="draft")
    # draft | sent_for_check | pre_job_confirmed  (§0.14: reject returns to 'draft')
    sent_for_check_at = Column(DateTime(timezone=True))
    reject_reason = Column(Text)                           # captured on reject; cleared on re-submit
    pdf_file_id = Column(String(512))                      # file-store relative path of the generated PDF (§3.6)
    # WO v4.33 CC addition (migration 0019, Michael-approved): comma-separated free-text email
    # addresses CC'd on the check-notification mailto (users carry no email column until v4.34
    # — Nadie types the addresses). Stored raw; email-shaped entries feed the &cc= param.
    cc_recipients = Column(Text)
    version = Column(Integer, nullable=False, default=1, server_default="1")
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# 32. fridge_units — fridge DDM master (WO v4.33 scope addition, migration 0018).
#     One row per (manufacturer × model) from the ICB standard mounting drawings;
#     v4.33 seeds Drawing A (Front Mount) only — B/D/F/G/H per-style cutouts are a
#     v4.33.1 enhancement (extra rows or a mounting_styles JSONB). display_name is
#     what fills the {{fridge_make}} template token.
# ─────────────────────────────────────────────────────────────────────────────
class FridgeUnit(Base):
    __tablename__ = "fridge_units"
    __table_args__ = (
        UniqueConstraint("manufacturer", "model", name="uq_fridge_units_manufacturer_model"),
        Index("ix_fridge_units_active", "is_active", "manufacturer"),
        {"schema": "icb_mes"},
    )
    id = Column(Integer, primary_key=True)
    manufacturer = Column(String(64), nullable=False)
    model = Column(String(64), nullable=False, default="", server_default="")
    display_name = Column(String(128), nullable=False)     # fills {{fridge_make}}
    mounting_drawing = Column(String(8))                   # 'A' (v4.33) | 'B'|'D'|'F'|'G'|'H' later
    cutout_width_mm = Column(Integer)                      # fills {{fridge_cutout_width}}
    cutout_height_mm = Column(Integer)                     # fills {{fridge_cutout_height}}
    is_active = Column(Boolean, nullable=False, default=True, server_default=sa_text("true"))
    version = Column(Integer, nullable=False, default=1, server_default="1")
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    created_by = Column(String(128))
    updated_by = Column(String(128))


# ─────────────────────────────────────────────────────────────────────────────
# 33. chassis_models — chassis make/model DDM (WO v4.34 §3.7, migration 0021).
#     ONE controlled vocabulary for the chassis-type dropdowns (Planning ack +
#     Pre-Job Card + Chassis +New/edit) so free-text variants ("Isuzu NPR 400"
#     vs "NPR 400") stop fragmenting chassis_records lookups + token substitution.
#     Seeded read-only (mirrors the fridge_units DDM); admin CRUD is v4.35.
# ─────────────────────────────────────────────────────────────────────────────
class ChassisModel(Base):
    __tablename__ = "chassis_models"
    __table_args__ = (
        UniqueConstraint("code", name="uq_chassis_models_code"),
        Index("ix_chassis_models_active", "is_active", "make"),
        {"schema": "icb_mes"},
    )
    id = Column(Integer, primary_key=True)
    code = Column(String(64), nullable=False)              # stable key, e.g. ISUZU-FTR-850-AMT
    make = Column(String(64), nullable=False)
    model = Column(String(128), nullable=False)            # 128 — full model strings are long
    category = Column(String(32))                          # truck | bakkie | trailer
    max_payload_kg = Column(Integer)
    is_active = Column(Boolean, nullable=False, default=True, server_default=sa_text("true"))
    sort_order = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    created_by = Column(String(128))
    updated_by = Column(String(128))


__all__ = [
    "ProductionJob", "WorkOrder", "Task", "SignOff", "Photo", "ReworkTicket",
    "PlanningSlot", "PlanningAck", "ProductionJobAudit", "ProductionJobBayEvent",
    "StockCount", "Discrepancy", "POSuggestion", "DemandLine",
    "MesMaterial", "StockPosition", "Supplier", "SessionBranch",
    "LiveDailyCount", "ChassisRegister",
    "BomRule", "BomRuleLookup", "MaterialPriceOverride", "BomSpecOption",
    "GeneratedBom", "BomLine",
    "ChassisRecord", "ChassisLifecycleEvent", "ChassisPhoto",
    "ParkingBay", "AssemblyBay",
    "PrejobTemplate", "PrejobCard", "FridgeUnit", "ChassisModel",
    "CROSS_SCHEMA_FKS",
]
