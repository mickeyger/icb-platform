"""WO v4.24 spike — geometry unit tests + job 32735 replay validation.

The fixture (job_32735_vacuum.json) is the workbook's own computed ground truth, extracted
once by app.spikes.v4_24.extract_fixture (provenance there). Tests are CI-safe:
  * geometry + code-resolution are pure (no DB / no workbook);
  * the QTY replay compares against the fixture's 2026-BOM panel lines (no DB);
  * the pipeline test injects the workbook's own prices (monkeypatch) to prove the engine math
    is exact — isolating the *price-source* divergence (OITM vs Table15) documented in the report;
  * the OITM unit_price + endpoint smoke tests use only the mock-seeded GRP-MPS-A-0077.
"""
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.spikes.v4_24 import bom_generator, code_lookup, geometry, pricing
from app.spikes.v4_24.models import JobSpec, PanelSpec

_FIX = json.loads((Path(__file__).parent / "fixtures" / "job_32735_vacuum.json").read_text(encoding="utf-8"))

# Panel-count SAP codes (the spike slice), in workbook 2026-BOM order.
_PANEL_CODES = ["GRP-MPS-A-0077", "GRP-MPS-A-0077", "GRP-POL-A-0158", "GRP-POL-A-0158",
                "GRP-PUS-A-0031", "GRP-TIM-A-0005", "GRP-TIM-A-0007", "GRP-TIM-A-0007",
                "GRP-TIM-A-0008"]


def _spec() -> JobSpec:
    """Job 32735 resolved Freezer spec (source: fixture specs / 2026 COSTINGS D* via VACUUM ORDERS AF)."""
    return JobSpec(
        job=32735, body_type="Freezer", length_mm=5400, width_mm=2300, height_mm=2300,
        roof=PanelSpec(thickness_mm=76, material="EPS 24DV"),
        sides=PanelSpec(thickness_mm=56, material="PU 32DV", skin="4mm plywood"),
        floor=PanelSpec(thickness_mm=76, material="EPS 24DV", skin="12mm finn"),
        front=PanelSpec(thickness_mm=56, material="PU 32DV", skin="4mm plywood"),
        rear=PanelSpec(thickness_mm=60, material="PU 32DV", skin="6mm plywood"),
        reveal_top_mm=81, reveal_side_mm=65, reveal_rear_mm=93, reveal_partition_mm=56,
    )


def _wb_panel_lines():
    """The 9 panel-count lines from the workbook's 2026 BOM (the §0.6 replay target), in order."""
    out, used = [], []
    for b in _FIX["bom_vacuum"]:
        if b["code"] in set(_PANEL_CODES):
            out.append(b)
            used.append(b["code"])
        if len(out) == 9:
            break
    return out


# ── geometry unit tests (§3.3 / §3.8) — each formula vs the workbook cut-list ──
def test_geometry_panel_counts():
    assert geometry.roof_foam_qty(5400) == 5
    assert geometry.floor_foam_qty(5400) == 5
    assert geometry.sides_foam_qty(5400) == 10
    assert geometry.front_foam_qty(2300, 65) == 2
    assert geometry.rear_foam_qty(2300, 65) == 2
    assert geometry.floor_skin_qty(5400, 2300) == 5
    assert geometry.sides_skin_qty(5400, 2300, 81, floor_present=True) == 10
    assert geometry.front_skin_qty(2300, 2300, 65, 81, floor_present=True) == 2
    assert geometry.rear_skin_qty(2300, 65) == 2


def test_geometry_matches_fixture_cutlist():
    # Cross-check against the workbook-computed cut-list rows (qty per active panel).
    by_panel = {(c["panel"], c["thickness"]): c["qty"] for c in _FIX["cutlist"] if c["qty"] is not None}
    assert by_panel[("Roof", 76)] == 5
    assert by_panel[("Sides", 56)] == 10
    assert by_panel[("Floor", 12)] == 5      # birch skin
    assert by_panel[("Sides", 4)] == 10      # ply skin


def test_code_lookup_resolves():
    assert code_lookup.resolve("EPS 24DV", 76) == ("076mm EPS 2440x1220mm 24 DV", "GRP-MPS-A-0077")
    assert code_lookup.resolve("pu 32dv", 60)[1] == "GRP-PUS-A-0031"     # case-insensitive
    assert code_lookup.resolve("EPS 24DV", 999) == (None, None)          # unmapped
    assert code_lookup.skin_material("12mm finn") == ("FINN PLY", 12)
    assert code_lookup.skin_material("4mm plywood") == ("PLY", 4)
    assert code_lookup.skin_material(None) == (None, None)


# ── §0.6 replay: quantities line-by-line vs the workbook (no DB) ──
def test_replay_quantities_match_workbook(monkeypatch):
    monkeypatch.setattr(pricing, "unit_price", lambda db, code: None)  # qty-only; ignore pricing
    out = bom_generator.generate_bom(_spec(), db=None)
    wb = _wb_panel_lines()
    assert len(out.lines) == 9 == len(wb)
    for line, wbln in zip(out.lines, wb):
        assert line.sap_code == wbln["code"]
        assert abs(float(line.qty) - float(wbln["qty"])) <= 0.001, f"qty delta on {line.sap_code}"


# ── engine correctness: fed the workbook's own prices, line totals replay exactly ──
def test_pipeline_matches_workbook_with_workbook_prices(monkeypatch):
    price_by_code = {}
    for b in _FIX["bom_vacuum"]:
        if b["code"] and b["code"] not in price_by_code and b["unit_price"] is not None:
            price_by_code[b["code"]] = Decimal(str(b["unit_price"]))
    monkeypatch.setattr(pricing, "unit_price", lambda db, code: price_by_code.get(code))
    out = bom_generator.generate_bom(_spec(), db=None)
    wb = _wb_panel_lines()
    for line, wbln in zip(out.lines, wb):
        exp = Decimal(str(wbln["line_total"]))
        assert abs((line.line_total or Decimal(0)) - exp) <= Decimal("0.01"), f"total delta on {line.sap_code}"
    wb_total = sum(Decimal(str(b["line_total"])) for b in wb)
    assert abs(out.grand_total - wb_total) <= Decimal("0.01")


# ── OITM unit_price (§3.8) — GRP-MPS-A-0077 is in the mock seed ──
def test_unit_price_from_oitm():
    from app.database import SessionLocal
    with SessionLocal() as db:
        assert pricing.unit_price(db, "GRP-MPS-A-0077") is not None
        assert pricing.unit_price(db, "NOPE-NOT-A-CODE") is None


# ── endpoint smoke (§3.8) — auth injected (host-scoped cookie won't carry, as v4.14) ──
@pytest.fixture
def api():
    import app.main as m
    from app.database import SessionLocal, User
    from app.deps import require_user
    from starlette.testclient import TestClient
    with TestClient(m.app) as c:          # entering the client triggers startup → seeds admin (CI fresh DB)
        with SessionLocal() as db:
            user = db.query(User).filter_by(username="admin").first()
        m.app.dependency_overrides[require_user] = lambda: user
        yield c
    m.app.dependency_overrides.pop(require_user, None)


def test_generate_endpoint_smoke(api):
    body = _spec().model_dump()
    r = api.post("/api/bom/generate", json=body)
    assert r.status_code == 200
    data = r.json()
    assert len(data["lines"]) == 9
    assert {ln["sap_code"] for ln in data["lines"]} == set(_PANEL_CODES)
    assert "grand_total" in data and "unpriced_codes" in data
