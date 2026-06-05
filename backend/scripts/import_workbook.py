"""WO v4.21 (Phase 2D-2) — ENTERPRISE PLANNING workbook ETL into icb_mes.

One-shot loader (Q-Ph2D-03 lock): TRUNCATE icb_mes + reload from the planning
workbook, then re-seed the Materials/Buying/Stores master data from the mockup
(§0.6-A). Writes ONLY icb_mes; reference-reads icb_costings but never mutates the
catalogue, faje, or the Cost Calculator path.

Sources (workbook sheets):
  * JOBS  (PLANNED block, cols 9-31) -> production_jobs (source='workbook', NULL calc).
  * derived from JOBS dates           -> planning_slots (MVP; full 336-col grid deferred, §0.4).
  * MATERIAL PLANNING (item x job)    -> demand_lines (melted; ITEM CODE as-is, §0.5).
  * frontend mockup JSON              -> mes_materials / stock_positions / suppliers (§0.6-A).

Run from repo root:
    python -m backend.scripts.import_workbook [--workbook PATH] [--today YYYY-MM-DD]
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import openpyxl

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = Path(__file__).resolve().parents[2]
_DATA = _REPO / "frontend" / "src" / "data"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import text as sa_text  # noqa: E402

from app.database import (  # noqa: E402
    Branch, Customer, SapItemCode, SessionLocal,
)
from app.models.mes import (  # noqa: E402
    DemandLine, MesMaterial, PlanningSlot, ProductionJob, StockPosition, Supplier,
)

DEFAULT_WORKBOOK = (_REPO.parent / "Burt Costing Model" / "ICB business process"
                    / "ENTERPRISE PLANNING - 2026.xlsx")

# All icb_mes tables — one-shot TRUNCATE target (Q-Ph2D-03).
_MES_TABLES = [
    "production_jobs", "work_orders", "tasks", "sign_offs", "photos", "rework_tickets",
    "planning_slots", "planning_acks", "stock_counts", "discrepancies", "po_suggestions",
    "demand_lines", "mes_materials", "stock_positions", "suppliers",
]

# JOBS sheet — PLANNED block column indices (0-based; header row 2, data row 3+).
_J_JOB, _J_CUST, _J_DESC, _J_CHASSIS_RX, _J_VIN = 10, 11, 12, 13, 14
_J_VACUUM, _J_ASSY_COMP, _J_INVOICED, _J_LEFT, _J_PRICE = 18, 22, 23, 24, 25


# ── value helpers ──────────────────────────────────────────────────────────────
def _is_dt(v):
    return isinstance(v, datetime)


def _aware(v):
    """openpyxl datetimes are naive; the timestamp columns are tz-aware (UTC)."""
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return None


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _iso_week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (ValueError, TypeError):
        return None


def _str(v):
    if v is None:
        return None
    s = str(v).strip()
    return s if s and s.upper() != "#N/A" else None


def _job_str(v):
    if isinstance(v, (int, float)):
        return str(int(v))
    return _str(v)


def _date_iso(s):
    return date.fromisoformat(str(s)[:10]) if s else None


def _dt_iso(s):
    if not s:
        return None
    s = str(s).replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        d = datetime.fromisoformat(s[:10] + "T00:00:00+00:00")
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ── DB helpers ───────────────────────────────────────────────────────────────
def _truncate(db):
    db.execute(sa_text(
        "TRUNCATE " + ", ".join(f"icb_mes.{t}" for t in _MES_TABLES)
        + " RESTART IDENTITY CASCADE"))


def _reset_sequences(db):
    for t in ("production_jobs", "planning_slots", "demand_lines",
              "mes_materials", "stock_positions", "suppliers"):
        db.execute(sa_text(
            f"SELECT setval('icb_mes.{t}_id_seq', "
            f"(SELECT COALESCE(MAX(id), 1) FROM icb_mes.{t}))"))


def _ref_maps(db):
    customers = {}
    for cid, name in db.query(Customer.id, Customer.name).all():
        if name:
            customers.setdefault(name.strip().lower(), cid)
    sap = set()
    for (code,) in db.query(SapItemCode.item_code).all():
        if code:
            sap.add(str(code).strip().lower())
    return customers, sap


# ── 1. production_jobs from JOBS PLANNED ──────────────────────────────────────
def _load_jobs(db, ws, today, cutoff, customers_map, report):
    jhb = db.query(Branch).filter_by(code="JHB").first()
    branch_id = jhb.id if jhb else None
    jobs = []           # (job_number, pj, vacuum_date|None, status)
    seen = set()
    skipped = matched_cust = 0
    for r in ws.iter_rows(min_row=3, values_only=True):
        if r is None or len(r) <= _J_LEFT:
            continue
        job_number = _job_str(r[_J_JOB])
        if not job_number or job_number.upper() == "JOB" or job_number in seen:
            continue
        seen.add(job_number)
        inv, left = r[_J_INVOICED], r[_J_LEFT]
        invoiced, left_dt = _is_dt(inv), _is_dt(left)
        # Active filter (§0.2/§0.8): drop only jobs invoiced AND left > 30 days ago.
        if invoiced and left_dt and left.date() < cutoff:
            skipped += 1
            continue
        vacuum = r[_J_VACUUM] if _is_dt(r[_J_VACUUM]) else None
        if left_dt:
            status = "completed"
        elif vacuum is not None:
            status = "in_production"     # scheduled -> gets a planning slot
        else:
            status = "planning"          # unscheduled pool
        cust = _str(r[_J_CUST])
        if cust and cust.strip().lower() in customers_map:
            matched_cust += 1
        vin = _str(r[_J_VIN])
        pj = ProductionJob(
            calculation_record_id=None, source="workbook", branch_id=branch_id,
            job_number=job_number, status=status,
            customer_name=cust, description=_str(r[_J_DESC]),
            selling_zar=_num(r[_J_PRICE]),
            chassis_received_at=_aware(r[_J_CHASSIS_RX]),
            chassis_data_json=(json.dumps({"vin": vin}) if vin else None),
            planned_start_date=_aware(vacuum),
            completed_at=(_aware(left) if left_dt else _aware(r[_J_ASSY_COMP])),
        )
        db.add(pj)
        jobs.append((job_number, pj, vacuum, status))
    db.flush()          # assign pj.id
    report["production_jobs"] = len(jobs)
    report["jobs_skipped_30d"] = skipped
    report["customer_name_match"] = f"{matched_cust}/{len(jobs)} match icb_costings.customers"
    report["_note_rep"] = ("JOBS PLANNED block has no REP/assignee column (rep lives in the "
                           "deferred PIPELINE block + DDM's), so no user-name resolution was "
                           "required for this MVP load.")
    return jobs


# ── 2. planning_slots (MVP derivation, §0.4) ──────────────────────────────────
def _load_slots(db, jobs, report):
    by_week = defaultdict(list)
    for job_number, pj, vacuum, status in jobs:
        if status == "completed" or vacuum is None:
            continue
        by_week[_monday(vacuum.date())].append(pj)
    n = 0
    for monday, pjs in by_week.items():
        for pos, pj in enumerate(sorted(pjs, key=lambda p: p.job_number), start=1):
            db.add(PlanningSlot(
                production_job_id=pj.id, week=monday,
                bay=f"Bay-{pos}", lane="vacuum", slot_position=pos, status="scheduled"))
            n += 1
    report["planning_slots"] = n
    report["planning_unscheduled_pool"] = sum(1 for *_, s in jobs if s == "planning")


# ── 3. demand_lines from MATERIAL PLANNING (melt, §0.5) ───────────────────────
def _load_demand(db, ws, jobs, sap_set, report):
    week_by_job, pj_by_job = {}, {}
    for job_number, pj, vacuum, status in jobs:
        pj_by_job[job_number] = pj
        if vacuum is not None:
            week_by_job[job_number] = _iso_week(_monday(vacuum.date()))

    header = next(ws.iter_rows(min_row=3, max_row=3, values_only=True))
    job_cols = {}       # column index -> job_number
    for i, h in enumerate(header):
        if i < 3 or h is None:
            continue
        if isinstance(h, str) and h.strip().upper() in ("APPLICABLE", "TOTAL"):
            continue
        jn = _job_str(h)
        if jn and jn.isdigit():
            job_cols[i] = jn

    n = 0
    codes_seen, codes_hit, unmatched_jobs = set(), set(), set()
    for r in ws.iter_rows(min_row=4, values_only=True):
        code = _str(r[1]) if len(r) > 1 else None
        if not code:
            continue
        codes_seen.add(code.lower())
        if code.lower() in sap_set:
            codes_hit.add(code.lower())
        for ci, jn in job_cols.items():
            if ci >= len(r):
                continue
            qty = _num(r[ci])
            if not qty or qty <= 0:
                continue
            pj = pj_by_job.get(jn)
            if pj is None:
                unmatched_jobs.add(jn)
            db.add(DemandLine(
                sap_code=code, qty=qty, job_ref=jn,
                production_job_id=(pj.id if pj else None),
                week_bucket=week_by_job.get(jn)))
            n += 1
    report["demand_lines"] = n
    report["demand_job_columns"] = len(job_cols)
    report["demand_unmatched_jobs"] = (
        f"{len(unmatched_jobs)} job column(s) not in production_jobs: "
        f"{sorted(unmatched_jobs)[:10]}" if unmatched_jobs else "0")
    hit = (100 * len(codes_hit) / len(codes_seen)) if codes_seen else 0
    report["sap_enrichment_hit_rate"] = (
        f"{len(codes_hit)}/{len(codes_seen)} distinct ITEM CODEs match "
        f"icb_costings.sap_item_codes ({hit:.0f}%)")


# ── 4. Materials/Buying/Stores re-seed from the mockup (§0.6-A) ────────────────
def _reseed_materials(db, report):
    mats = json.loads((_DATA / "icb_materials_data.json").read_text(encoding="utf-8"))
    for m in mats.get("materials", []):
        db.add(MesMaterial(
            sap_code=m.get("sap_code"), description=m.get("description"),
            supplier=m.get("supplier"), lead_days=m.get("lead_days"),
            last_price=m.get("last_price"), abc_class=m.get("abc_class"), dept=m.get("dept")))
    for s in mats.get("stock_positions", []):
        db.add(StockPosition(
            sap_code=s.get("sap_code"), sap_stock=s.get("sap_stock"),
            allocated=s.get("allocated"), free=s.get("free"),
            open_po_qty=s.get("open_po_qty"), open_po_eta=_date_iso(s.get("open_po_eta")),
            last_refreshed=_dt_iso(s.get("last_refreshed"))))
    for sup in mats.get("suppliers", []):
        db.add(Supplier(
            name=sup.get("name"), contact_person=sup.get("contact_person"),
            payment_terms=sup.get("payment_terms"), phone=sup.get("phone")))
    report["mes_materials"] = len(mats.get("materials", []))
    report["stock_positions"] = len(mats.get("stock_positions", []))
    report["suppliers"] = len(mats.get("suppliers", []))


def run(workbook: Path, today: date) -> dict:
    cutoff = today - timedelta(days=30)
    report = {"workbook": str(workbook), "today": today.isoformat(),
              "active_cutoff": cutoff.isoformat()}
    wb = openpyxl.load_workbook(workbook, read_only=True, data_only=True)
    db = SessionLocal()
    try:
        _truncate(db)
        customers_map, sap_set = _ref_maps(db)
        jobs = _load_jobs(db, wb["JOBS"], today, cutoff, customers_map, report)
        _load_slots(db, jobs, report)
        _load_demand(db, wb["MATERIAL PLANNING"], jobs, sap_set, report)
        _reseed_materials(db, report)
        db.commit()
        _reset_sequences(db)
        db.commit()
        return report
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        wb.close()


def main():
    ap = argparse.ArgumentParser(description="WO v4.21 — ENTERPRISE PLANNING workbook ETL.")
    ap.add_argument("--workbook", default=str(DEFAULT_WORKBOOK), help="path to the .xlsx")
    ap.add_argument("--today", default=None, help="YYYY-MM-DD override for the active-job cutoff")
    args = ap.parse_args()
    wb_path = Path(args.workbook)
    if not wb_path.exists():
        sys.exit(f"[import_workbook] workbook not found: {wb_path}")
    today = date.fromisoformat(args.today) if args.today else date.today()
    report = run(wb_path, today)
    print("\n[import_workbook] Complete. Load report:")
    for k, v in report.items():
        if not k.startswith("_"):
            print(f"  {k:<26} {v}")
    print(f"  {'note':<26} {report.get('_note_rep', '')}")


if __name__ == "__main__":
    main()
