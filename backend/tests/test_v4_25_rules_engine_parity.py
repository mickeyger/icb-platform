"""WO v4.25 §3.6/§3.8 — the binary parity gate + pricing + admin tests.

Parity (§0.3): the rules engine's Vacuum × Freezer × job 32735 output must match the v4.24
spike's geometry line-by-line (SAP code + qty, tol ≤ 0.001). The spike's bom_generator is the
oracle (pricing neutralised on both sides — parity is on qty). Rules are seeded idempotently in
a fixture so the test is self-contained regardless of seed order.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.database import SessionLocal

# Job 32735 resolved Freezer spec (source: tests/spikes/fixtures/job_32735_vacuum.json).
SPEC_KW = dict(job=32735, body_type="Freezer", length_mm=5400, width_mm=2300, height_mm=2300)
PANELS = dict(
    roof=dict(thickness_mm=76, material="EPS 24DV"),
    sides=dict(thickness_mm=56, material="PU 32DV", skin="4mm plywood"),
    floor=dict(thickness_mm=76, material="EPS 24DV", skin="12mm finn"),
    front=dict(thickness_mm=56, material="PU 32DV", skin="4mm plywood"),
    rear=dict(thickness_mm=60, material="PU 32DV", skin="6mm plywood"),
)


@pytest.fixture(scope="module")
def seeded():
    from scripts.seed_v4_25_rules import seed_rules
    with SessionLocal() as db:
        seed_rules(db)
        db.commit()
    yield


def _prod_spec():
    from app.schemas.bom import JobSpec, PanelSpec
    return JobSpec(**SPEC_KW, **{k: PanelSpec(**v) for k, v in PANELS.items()})


def _spike_spec():
    from app.spikes.v4_24.models import JobSpec, PanelSpec
    return JobSpec(**SPEC_KW, **{k: PanelSpec(**v) for k, v in PANELS.items()})


def test_vacuum_freezer_32735_parity_with_spike(seeded, monkeypatch):
    """BINARY GATE — rules engine output == spike geometry.py output (code + qty)."""
    from app.services.rules_engine.engine import RulesEngine
    from app.spikes.v4_24 import bom_generator as spike, pricing as spike_pricing

    monkeypatch.setattr(spike_pricing, "unit_price", lambda db, code: None)  # qty parity only
    spike_out = spike.generate_bom(_spike_spec(), db=None)
    with SessionLocal() as db:
        eng_out = RulesEngine(db).generate_bom(_prod_spec())

    assert len(eng_out.lines) == len(spike_out.lines) == 9, "line count must match the spike"
    eng = sorted((ln.sap_code, float(ln.qty)) for ln in eng_out.lines)
    spk = sorted((ln.sap_code, float(ln.qty)) for ln in spike_out.lines)
    for (ec, eq), (sc, sq) in zip(eng, spk):
        assert ec == sc, f"sap_code mismatch: engine {ec} vs spike {sc}"
        assert abs(eq - sq) <= 0.001, f"qty delta on {ec}: {eq} vs {sq}"


def test_pricing_override_takes_precedence_over_sap():
    from app.models.mes import MaterialPriceOverride
    from app.services.rules_engine.pricing import get_price
    code = "GRP-MPS-A-0077"  # present in both the mock seed + real OITM
    with SessionLocal() as db:
        price, source = get_price(db, code)
        assert source == "sap" and price is not None        # SAP fallback
        db.add(MaterialPriceOverride(sap_code=code, override_price=Decimal("999.0000"),
                                     valid_from=date.today()))
        db.flush()
        p2, s2 = get_price(db, code)
        assert s2 == "override" and float(p2) == 999.0       # override wins
        db.rollback()                                        # leave no override behind


def test_pricing_unknown_code_returns_none():
    from app.services.rules_engine.pricing import get_price
    with SessionLocal() as db:
        assert get_price(db, "NOPE-NOT-A-CODE") == (None, None)


# ── admin inspection endpoints (§3.7) ──
@pytest.fixture
def admin_api():
    import app.main as m
    from app.database import SessionLocal as SL, User
    from app.deps import require_admin, require_user
    from starlette.testclient import TestClient
    with TestClient(m.app) as c:
        with SL() as db:
            admin = db.query(User).filter_by(username="admin").first()
        m.app.dependency_overrides[require_user] = lambda: admin
        m.app.dependency_overrides[require_admin] = lambda: admin
        yield c
    m.app.dependency_overrides.pop(require_user, None)
    m.app.dependency_overrides.pop(require_admin, None)


def test_admin_endpoints_return_seeded(seeded, admin_api):
    rules = admin_api.get("/api/admin/bom-rules?body_type=Freezer&section=Vacuum Materials").json()
    assert len(rules) == 9 and all("formula_expression" in r for r in rules)
    lookups = admin_api.get("/api/admin/bom-rule-lookups?body_type=Freezer").json()
    assert len(lookups) == 6 and all(lk["lookup_type"] == "spec_to_sap_code" for lk in lookups)
    ov = admin_api.get("/api/admin/material-price-overrides")
    assert ov.status_code == 200 and isinstance(ov.json(), list)


def test_admin_endpoints_are_gated():
    import app.main as m
    from starlette.testclient import TestClient
    with TestClient(m.app) as c:                              # no auth → require_admin blocks
        assert c.get("/api/admin/bom-rules").status_code in (401, 403)
