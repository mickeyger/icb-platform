"""WO v4.27 §3.3 — per-body-type parity (structural).

Freezer keeps its line-by-line gate (test_v4_25_rules_engine_parity). Here the 7 new body types
are checked STRUCTURALLY against the job-32735 spec (body_type swapped), per §0.2 — numeric
line-by-line validation for the 6 follows once Nadie's oracle snapshots land (v4.27.1):

  * Chiller / Carcass / Insulated Trailer / Hatchery — identical Vacuum geometry to Freezer
    (no body-type branch in VACUUM ORDERS rows 5-20) → output must EQUAL Freezer's.
  * Dryfreight — no insulated floor foam (F7) → strictly less total qty than Freezer.
  * Icecream — double walls (sides x4, front/rear x2; F8/F9/F11) → strictly more than Freezer.
  * Explosive — NOT AVAILABLE (§0.1) → intentionally empty BOM.
"""
import pytest

from app.database import SessionLocal

# Job 32735 resolved spec (same source as the v4.25 Freezer parity test).
SPEC_KW = dict(job=32735, length_mm=5400, width_mm=2300, height_mm=2300)
PANELS = dict(
    roof=dict(thickness_mm=76, material="EPS 24DV"),
    sides=dict(thickness_mm=56, material="PU 32DV", skin="4mm plywood"),
    floor=dict(thickness_mm=76, material="EPS 24DV", skin="12mm finn"),
    front=dict(thickness_mm=56, material="PU 32DV", skin="4mm plywood"),
    rear=dict(thickness_mm=60, material="PU 32DV", skin="6mm plywood"),
)
SAME_AS_FREEZER = ["Chiller", "Carcass", "Insulated Trailer", "Hatchery"]
ALL_NEW = SAME_AS_FREEZER + ["Dryfreight", "Icecream", "Explosive"]


@pytest.fixture(scope="module")
def seeded():
    from scripts.seed_v4_25_rules import seed_rules
    from scripts.seed_v4_27_body_geometry import seed_body_geometry
    with SessionLocal() as db:
        seed_rules(db)
        seed_body_geometry(db)
        db.commit()
    yield


def _spec(body_type):
    from app.schemas.bom import JobSpec, PanelSpec
    return JobSpec(**{**SPEC_KW, "body_type": body_type},
                   **{k: PanelSpec(**v) for k, v in PANELS.items()})


def _bom(db, body_type):
    from app.services.rules_engine.engine import RulesEngine
    return RulesEngine(db).generate_bom(_spec(body_type))


def _codeqty(out):
    return sorted((ln.sap_code, round(float(ln.qty), 3)) for ln in out.lines)


def _total_qty(out):
    return sum(float(ln.qty) for ln in out.lines)


def test_all_new_body_types_resolve_without_error(seeded):
    """Every body type generates a BOM (non-error). Empty only for Explosive (by design)."""
    with SessionLocal() as db:
        for bt in ALL_NEW:
            out = _bom(db, bt)
            if bt == "Explosive":
                assert len(out.lines) == 0, "Explosive is NOT AVAILABLE → empty BOM"
            else:
                assert len(out.lines) > 0, f"{bt} should produce a non-empty BOM"
                assert out.grand_total is not None


def test_same_geometry_bodies_equal_freezer(seeded):
    """Chiller/Carcass/Insulated/Hatchery share Freezer's Vacuum geometry → identical output."""
    with SessionLocal() as db:
        frz = _codeqty(_bom(db, "Freezer"))
        assert len(frz) == 9, "Freezer baseline should be the 9-line job-32735 BOM"
        for bt in SAME_AS_FREEZER:
            assert _codeqty(_bom(db, bt)) == frz, f"{bt} must match Freezer geometry line-for-line"


def test_dryfreight_has_less_than_freezer(seeded):
    """Dryfreight drops the insulated floor foam (F7) → strictly less total qty than Freezer."""
    with SessionLocal() as db:
        frz, dry = _bom(db, "Freezer"), _bom(db, "Dryfreight")
    assert len(dry.lines) > 0
    assert _total_qty(dry) < _total_qty(frz), "dryfreight should drop floor foam"


def test_icecream_has_more_than_freezer(seeded):
    """Icecream double walls (sides x4, front/rear x2) → strictly more total qty than Freezer."""
    with SessionLocal() as db:
        frz, ice = _bom(db, "Freezer"), _bom(db, "Icecream")
    assert len(ice.lines) > 0
    assert _total_qty(ice) > _total_qty(frz), "icecream double-wall should add foam qty"
