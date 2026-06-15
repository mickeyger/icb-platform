"""Seed the icb_mes schema (and its icb_costings anchors) from the mockup JSON.

WO v4.13 (Phase 2A). Run from the repo root:

    python -m backend.scripts.seed_from_mockup [--reset]

Behaviour:
  * First run (icb_mes empty): seeds the anchors (customers + calculations in
    icb_costings, only if those tables are empty) then all the icb_mes tables.
  * Re-run with data present: prompts "Re-seed? [Y/N]" (interactive). --reset
    skips the prompt (for CI) and TRUNCATEs the icb_mes tables first.
  * Never TRUNCATEs icb_costings. The anchors are inserted only when empty, so a
    re-seed re-links production_jobs to the existing calculations by quote_number.
  * Preserves the mockup integer IDs for stock_counts (1-10), discrepancies
    (1-3) and po_suggestions (1-8); assigns surrogate IDs elsewhere and keeps the
    business key (quote_number, job_number, sap_code) in its own column.

Sources (frontend/src/data): icb_costings_data.json (costings -> calculations +
production_jobs), icb_materials_data.json (stock/PO/demand/discrepancy),
icb_mock_data.json (planning_board -> planning_slots, rework_tickets).
"""
import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = Path(__file__).resolve().parents[2]
_DATA = _REPO / "frontend" / "src" / "data"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import text as sa_text  # noqa: E402

from app.database import Branch, CalculationRecord, Customer, SessionLocal  # noqa: E402
from app.models.mes import (  # noqa: E402
    Discrepancy, DemandLine, MesMaterial, PlanningSlot, POSuggestion, ProductionJob,
    ReworkTicket, StockCount, StockPosition, Supplier,
)
from app.models.sap import OITM, OITW, OWHS  # noqa: E402

_SAP_WHS_CODE = "HEIDEL"
_SAP_WHS_NAME = "Heidelberg (JHB main)"

_MES_TABLES = [
    "production_jobs", "work_orders", "tasks", "sign_offs", "photos", "rework_tickets",
    "planning_slots", "planning_acks", "stock_counts", "discrepancies", "po_suggestions",
    "demand_lines", "mes_materials", "stock_positions", "suppliers",
]
_SITE_TO_BRANCH = {"JHB": "JHB", "CT": "CPT", "CENT": "CEN", "CPT": "CPT", "CEN": "CEN"}
_CALC_STATUS = {
    "Pending": "pending", "Accepted": "accepted", "Pre-Job Sent": "pre_job_sent",
    "Pre-Job Confirmed": "pre_job_confirmed", "Rejected": "declined",
    "Repair": "accepted", "Planning": "pre_job_confirmed",
}
_PJ_STATUS = {
    "Accepted": "accepted", "Pre-Job Sent": "pre_job_sent",
    "Pre-Job Confirmed": "pre_job_confirmed", "Planning": "planning", "Repair": "accepted",
}
_LANE = {"V": "vacuum", "P": "panelshop", "D": "doors", "G": "grp", "A": "assy"}


def _load(name):
    return json.loads((_DATA / name).read_text(encoding="utf-8"))


def _dt(s):
    """Parse an ISO timestamp or date string to an aware UTC datetime, or None."""
    if not s:
        return None
    s = str(s).replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        d = datetime.fromisoformat(s[:10] + "T00:00:00+00:00")
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _date(s):
    return date.fromisoformat(str(s)[:10]) if s else None


def _job_num(quote):
    # WO v4.34 §0.7 — the NUMERIC core (A32744/06/2026 → 32744), matching
    # production_jobs._job_number_from_quote so a reseed never reintroduces the full quote.
    if not quote:
        return None
    m = re.search(r"\d+", quote)
    return m.group(0) if m else None


def _setval(db, schema_table):
    db.execute(sa_text(
        f"SELECT setval('{schema_table}_id_seq', "
        f"(SELECT COALESCE(MAX(id), 1) FROM {schema_table}))"
    ))


def _icb_sap_present(db) -> bool:
    """icb_sap exists only after migration 0008 (WO v4.23). Guard the SAP-mock seed so
    seeding still works on a DB that hasn't applied 0008 yet."""
    return db.execute(sa_text(
        "SELECT 1 FROM information_schema.schemata WHERE schema_name = 'icb_sap'"
    )).first() is not None


def _bom_rules_present(db) -> bool:
    """icb_mes.bom_rules exists only after migration 0009 (WO v4.25)."""
    return db.execute(sa_text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'icb_mes' AND table_name = 'bom_rules'"
    )).first() is not None


def _bom_spec_options_present(db) -> bool:
    """icb_mes.bom_spec_options exists only after migration 0010 (WO v4.26)."""
    return db.execute(sa_text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'icb_mes' AND table_name = 'bom_spec_options'"
    )).first() is not None


def _chassis_records_present(db) -> bool:
    """icb_mes.chassis_records exists only after migration 0012 (WO v4.28)."""
    return db.execute(sa_text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'icb_mes' AND table_name = 'chassis_records'"
    )).first() is not None


def _truncate_mes(db):
    # WO v4.34.4 §3.2 — the destructive vector. HARD-refuse unless DATABASE_URL is an isolated *_test DB,
    # so a re-seed can never TRUNCATE the shared dev DB again. (Fresh-empty seeding never reaches here.)
    from scripts._environment_guard import require_test_db
    require_test_db("seed_from_mockup (TRUNCATE icb_mes + icb_sap landing)")
    db.execute(sa_text(
        "TRUNCATE " + ", ".join(f"icb_mes.{t}" for t in _MES_TABLES)
        + " RESTART IDENTITY CASCADE"
    ))
    if _icb_sap_present(db):   # WO v4.23 — clear the SAP-mock landing zone too (independent of icb_mes)
        db.execute(sa_text('TRUNCATE icb_sap."OITW", icb_sap."OITM", icb_sap."OWHS" CASCADE'))
    db.commit()


def seed(reset: bool = False) -> None:
    costings = _load("icb_costings_data.json")["costings"]
    materials = _load("icb_materials_data.json")
    mock = _load("icb_mock_data.json")

    db = SessionLocal()
    try:
        mes_has_data = db.query(ProductionJob).first() or db.query(POSuggestion).first()
        if mes_has_data:
            if not reset:
                ans = input("icb_mes already contains data. Re-seed? [Y/N] ").strip().lower()
                if ans != "y":
                    print("[seed] Aborted — no changes made.")
                    return
            print("[seed] Clearing icb_mes tables (TRUNCATE ... RESTART IDENTITY CASCADE)")
            _truncate_mes(db)
            db.expunge_all()  # drop identity-map rows loaded by the mes_has_data probe

        branch_by_code = {b.code: b.id for b in db.query(Branch).all()}

        def branch_for(site):
            return branch_by_code.get(_SITE_TO_BRANCH.get(site or "JHB", "JHB"))

        counts = {}

        # ── 1. customers (icb_costings anchor) — only when empty ──────────────
        if db.query(Customer).count() == 0:
            seen = {}
            for c in costings:
                cid = c.get("customer_id")
                if cid and cid not in seen:
                    seen[cid] = True
                    db.add(Customer(id=cid, name=c.get("customer_name") or f"Customer {cid}",
                                    branch_id=branch_for(c.get("site"))))
            db.flush()
            _setval(db, "icb_costings.customers")
            counts["customers (icb_costings)"] = len(seen)
        else:
            counts["customers (icb_costings)"] = "skipped (not empty)"

        # ── 2. calculations (icb_costings anchor) — only when empty ───────────
        if db.query(CalculationRecord).count() == 0:
            for c in costings:
                db.add(CalculationRecord(
                    quote_number=c["quote_number"],
                    customer_id=c.get("customer_id"),
                    branch_id=branch_for(c.get("site")),
                    status=_CALC_STATUS.get(c.get("status"), "pending"),
                    is_repair=(c.get("quote_type") == "Repair"),
                    created_at=_dt(c.get("created_at")),
                    approved_at=_dt(c.get("accepted_at")),
                    decline_reason=c.get("rejection_reason"),
                    dimensions_json=json.dumps({
                        "body_type": c.get("body_type"), "body_category": c.get("body_category"),
                        "requires_chassis": c.get("requires_chassis"),
                        "chassis_supplied_by": c.get("chassis_supplied_by"),
                    }),
                    result_json=json.dumps({k: c.get(k) for k in (
                        "cost_zar", "selling_zar", "gross_profit_zar", "markup_pct",
                        "extras_count", "extras_list")}),
                ))
            db.flush()
            _setval(db, "icb_costings.calculations")
            counts["calculations (icb_costings)"] = len(costings)
        else:
            counts["calculations (icb_costings)"] = "skipped (not empty)"

        calc_by_quote = {c.quote_number: c.id for c in db.query(CalculationRecord).all()}

        # ── 3. production_jobs — one per progressed (accepted) costing ────────
        pj = 0
        for c in costings:
            if not c.get("accepted_at"):
                continue
            calc_id = calc_by_quote.get(c["quote_number"])
            if not calc_id:
                continue
            db.add(ProductionJob(
                calculation_record_id=calc_id,
                branch_id=branch_for(c.get("site")),
                job_number=c.get("job_number_assigned") or _job_num(c["quote_number"]),
                status=_PJ_STATUS.get(c.get("status"), "accepted"),
                accepted_at=_dt(c.get("accepted_at")),
                pre_job_sent_at=_dt(c.get("pre_job_sent_at")),
                pre_job_confirmed_at=_dt(c.get("pre_job_confirmed_at")),
                job_number_assigned=c.get("job_number_assigned"),
                repair_phases_json=(json.dumps({"scope": c.get("repair_scope"),
                                                "phase_entry": c.get("repair_phase_entry")})
                                    if c.get("quote_type") == "Repair" else None),
                pre_job_signoff_sales_at=_dt(c.get("pre_job_signoff_sales_at")),
                pre_job_signoff_sales_by=c.get("pre_job_signoff_sales_by"),
                pre_job_signoff_production_at=_dt(c.get("pre_job_signoff_production_at")),
                pre_job_signoff_production_by=c.get("pre_job_signoff_production_by"),
                planning_acknowledged_at=_dt(c.get("planning_acknowledged_at")),
                planning_acknowledged_by=c.get("planning_acknowledged_by"),
                chassis_eta=_dt(c.get("chassis_eta")),
                chassis_eta_captured_at=_dt(c.get("chassis_eta_captured_at")),
                chassis_eta_captured_by=c.get("chassis_eta_captured_by"),
                chassis_data_json=(json.dumps(c["chassis_data"]) if c.get("chassis_data") else None),
                chassis_received_at=_dt(c.get("chassis_received_at")),
                chassis_received_by=c.get("chassis_received_by"),
            ))
            pj += 1
        db.flush()
        counts["production_jobs"] = pj
        pj_by_num = {p.job_number: p.id for p in db.query(ProductionJob).all()}

        # ── 4. planning_slots — from the planning board ───────────────────────
        pb = mock.get("planning_board", {})
        week_start = {w["week"]: _date(w.get("start")) for w in pb.get("weeks", [])}
        ps = 0
        for s in pb.get("slot_assignments", []):
            slot = s.get("slot", "")
            prefix, _, pos = slot.partition("-")
            db.add(PlanningSlot(
                production_job_id=pj_by_num.get(s.get("job_number")),
                week=week_start.get(s.get("week")),
                bay=slot, lane=_LANE.get(prefix.upper(), prefix.lower() or None),
                slot_position=int(pos) if pos.isdigit() else None,
                status="scheduled",
            ))
            ps += 1
        counts["planning_slots"] = ps

        # ── 5. rework_tickets ─────────────────────────────────────────────────
        rt = 0
        for t in mock.get("rework_tickets", []):
            db.add(ReworkTicket(
                ticket_code=t.get("ticket"), routed_to_bay=t.get("to_bay"),
                status=t.get("status"), notes=t.get("reason"),
                created_at=_dt(t.get("opened_at")),
            ))
            rt += 1
        counts["rework_tickets"] = rt

        # ── 6. stock_counts (preserve ids 1-10) ───────────────────────────────
        scs = materials.get("stock_counts", [])
        for s in scs:
            db.add(StockCount(
                id=s["id"], sap_code=s.get("sap_code"), bin=s.get("bin"),
                sap_stock_at_count=s.get("sap_stock_at_count"),
                physical_count=s.get("physical_count"),
                counted_by_name=s.get("counted_by"), counted_at=_dt(s.get("counted_at")),
                status=s.get("status"),
                branch_id=branch_by_code.get("JHB"),  # WO v4.16: stock_counts carry a branch (NOT NULL in 0005)
            ))
        db.flush()
        _setval(db, "icb_mes.stock_counts")
        counts["stock_counts"] = len(scs)

        # ── 7. discrepancies (preserve ids; FK -> stock_counts) ───────────────
        ds = materials.get("discrepancies", [])
        for d in ds:
            db.add(Discrepancy(
                id=d["id"], stock_count_id=d.get("stock_count_id"),
                raised_at=_dt(d.get("raised_at")), raised_to_buyer_name=d.get("raised_to_buyer"),
                notes=d.get("notes"), resolved_at=_dt(d.get("resolved_at")),
            ))
        db.flush()
        _setval(db, "icb_mes.discrepancies")
        counts["discrepancies"] = len(ds)

        # ── 8. po_suggestions (preserve ids 1-8) ──────────────────────────────
        pos_rows = materials.get("po_suggestions", [])
        for p in pos_rows:
            db.add(POSuggestion(
                id=p["id"], sap_code=p.get("sap_code"), qty=p.get("qty"),
                suggested_supplier=p.get("suggested_supplier"), last_price=p.get("last_price"),
                total=p.get("total"), need_by=_date(p.get("need_by")),
                urgency=p.get("urgency"), status=p.get("status"),
                created_at=_dt(p.get("created_at")), jobs_impacted=p.get("jobs_impacted"),
            ))
        db.flush()
        _setval(db, "icb_mes.po_suggestions")
        counts["po_suggestions"] = len(pos_rows)

        # ── 9. demand_lines (new ids; preserve job_id in job_ref) ─────────────
        dls = materials.get("demand_lines", [])
        for dl in dls:
            db.add(DemandLine(
                sap_code=dl.get("sap_code"), qty=dl.get("qty"), need_by=_date(dl.get("need_by")),
                job_ref=dl.get("job_id"), week_bucket=dl.get("week_bucket"),
            ))
        counts["demand_lines"] = len(dls)

        # ── 10. materials — MES catalogue master data (WO v4.15, Q1) ──────────
        mats = materials.get("materials", [])
        for m in mats:
            db.add(MesMaterial(
                sap_code=m.get("sap_code"), description=m.get("description"),
                supplier=m.get("supplier"), lead_days=m.get("lead_days"),
                last_price=m.get("last_price"), abc_class=m.get("abc_class"),
                dept=m.get("dept"),
            ))
        counts["materials"] = len(mats)

        # ── 11. stock_positions — current SAP stock per material (WO v4.15) ───
        sps = materials.get("stock_positions", [])
        for s in sps:
            db.add(StockPosition(
                sap_code=s.get("sap_code"), sap_stock=s.get("sap_stock"),
                allocated=s.get("allocated"), free=s.get("free"),
                open_po_qty=s.get("open_po_qty"), open_po_eta=_date(s.get("open_po_eta")),
                last_refreshed=_dt(s.get("last_refreshed")),
            ))
        counts["stock_positions"] = len(sps)

        # ── 11b. icb_sap (SAP-mock) — mirror the mock stock into OITM/OITW/OWHS (WO v4.23,
        #         ADR 0013). /api/materials + the cycle-count baseline now read icb_sap.OITW,
        #         so CI/dev — where the real Inventory ETL can't run — needs SAP stock seeded
        #         here. The real loader (import_inventory_to_sap_mock.py) replaces these with
        #         the live ~5485 items. Available is GENERATED (OnHand-IsCommited+OnOrder).
        if _icb_sap_present(db):
            db.add(OWHS(WhsCode=_SAP_WHS_CODE, WhsName=_SAP_WHS_NAME, Inactive="N"))
            db.flush()
            for m in mats:
                db.add(OITM(ItemCode=m.get("sap_code"), ItemName=m.get("description"),
                            InvntryUom="EA", U_LastPurchasePrice=m.get("last_price"), validFor="Y"))
            db.flush()
            oitm_codes = {m.get("sap_code") for m in mats}
            n_oitw = 0
            for s in sps:
                if s.get("sap_code") not in oitm_codes:   # OITW.ItemCode FK -> OITM; skip unmatched
                    continue
                db.add(OITW(ItemCode=s.get("sap_code"), WhsCode=_SAP_WHS_CODE,
                            OnHand=s.get("sap_stock") or 0, IsCommited=s.get("allocated") or 0,
                            OnOrder=s.get("open_po_qty") or 0))
                n_oitw += 1
            db.flush()
            counts["icb_sap OWHS/OITM/OITW"] = f"1 / {len(mats)} / {n_oitw}"
        else:
            counts["icb_sap (skipped)"] = "schema absent — apply migration 0008 then re-seed"

        # ── 11c. bom_rules + lookups (WO v4.25) — rules-engine substrate, seeded from the
        #         v4.24 spike geometry so CI/dev have rules for /api/bom/generate + the parity test.
        if _bom_rules_present(db):
            from scripts.seed_v4_25_rules import seed_rules
            rc = seed_rules(db)
            counts["bom_rules / lookups"] = f"{rc['bom_rules']} / {rc['bom_rule_lookups']}"
            # WO v4.27 §3.2 — per-body-type Vacuum geometry for the 7 non-Freezer bodies.
            from scripts.seed_v4_27_body_geometry import seed_body_geometry
            bg = seed_body_geometry(db)
            counts["body_geometry (v4.27)"] = f"{sum(bg.values())} rules / {len(bg)} body types"
        else:
            counts["bom_rules (skipped)"] = "tables absent — apply migration 0009 then re-seed"

        # ── 11d. bom_spec_options (WO v4.26) — DDM dropdown catalogue / early-binding, so CI/dev
        #         have spec options for the DDM resolver + per-body-type parity tests.
        if _bom_spec_options_present(db):
            from scripts.seed_v4_26_spec_options import seed_spec_options
            so = seed_spec_options(db)
            counts["bom_spec_options"] = so["total"]
        else:
            counts["bom_spec_options (skipped)"] = "table absent — apply migration 0010 then re-seed"

        # ── 11e. chassis (WO v4.28) — synthetic chassis_records + lifecycle events so CI / fresh
        #         dev DBs have data for the chassis list + the Playwright chassis journey (real
        #         records come from translate_chassis_register against the Truck Register workbook).
        if _chassis_records_present(db):
            from scripts.seed_v4_28_chassis_mock import seed_chassis_mock
            cm = seed_chassis_mock(db)
            counts["chassis_records (mock)"] = f"{cm['chassis_records']} records / {cm['lifecycle_events']} events"
        else:
            counts["chassis_records (skipped)"] = "table absent — apply migration 0012 then re-seed"

        # ── 12. suppliers — supplier master (WO v4.15; no icb_costings.suppliers) ─
        sups = materials.get("suppliers", [])
        for sup in sups:
            db.add(Supplier(
                name=sup.get("name"), contact_person=sup.get("contact_person"),
                payment_terms=sup.get("payment_terms"), phone=sup.get("phone"),
            ))
        counts["suppliers"] = len(sups)

        # WO v4.34.2 — a re-seed TRUNCATEs production_jobs but NOT prejob_cards, which orphans any
        # surviving (user-created) card from its job and makes confirmed cards invisible to Planning.
        # Re-anchor: ensure every sent_for_check/confirmed card's calc has a job in the matching status.
        from scripts.backfill_prejob_job_anchor import ensure_jobs_for_carded_calcs
        anchor = ensure_jobs_for_carded_calcs(db, commit=False)
        counts["prejob job re-anchor"] = f"{anchor['created']} created / {anchor['checked']} cards checked"

        db.commit()

        print("\n[seed] Complete. Row counts:")
        for k, v in counts.items():
            print(f"  {k:<28} {v}")
        print("  work_orders/tasks/sign_offs/photos/planning_acks  0 (no JSON source; "
              "populated via UI/API in later phases)")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main():
    ap = argparse.ArgumentParser(description="Seed icb_mes from the mockup JSON.")
    ap.add_argument("--reset", action="store_true",
                    help="Non-interactive re-seed (TRUNCATE icb_mes first). For CI.")
    args = ap.parse_args()
    seed(reset=args.reset)


if __name__ == "__main__":
    main()
