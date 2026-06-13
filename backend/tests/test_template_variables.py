"""WO v4.33 scope addition — substitution engine + normalizer + fridge DDM tests.

Engine semantics (BA-locked): absent key → token stays visible; present-but-empty → "Pending"
for vin, blank otherwise; lengths format `5 400`; metres→mm conversion (the REAL
dimensions_json source — the spec's calculations.length_mm columns don't exist). Normalizer:
content-keyed o/a-(l|w|h) + dash patterns on representative strings. Fridge: seed idempotent
(30 Drawing-A rows), options endpoint active-only. P433F markers where DB rows are made.
"""
import pytest


# ── engine ────────────────────────────────────────────────────────────────────
def test_substitute_semantics():
    from app.services.template_variables import substitute_text
    ctx = {"external_length": "5 400", "vin": None, "fridge_make": ""}
    assert substitute_text("{{external_length}}mm o/a (l)", ctx) == "5 400mm o/a (l)"
    assert substitute_text("VIN Nr: {{vin}}", ctx) == "VIN Nr: Pending"      # empty vin -> Pending
    assert substitute_text("Provision for {{fridge_make}} fridge", ctx) == \
        "Provision for  fridge"                                              # empty other -> blank
    assert substitute_text("x {{unknown_token}} y", ctx) == "x {{unknown_token}} y"  # absent -> visible


def test_format_mm_metres_and_mm():
    from app.services.template_variables import format_mm
    assert format_mm(7.5) == "7 500"          # dimensions_json metres
    assert format_mm(2.6) == "2 600"
    assert format_mm(1250) == "1 250"         # already mm (fridge cutouts)
    assert format_mm(None) == ""


def test_substitute_sections_deep():
    from app.services.template_variables import substitute_sections
    sections = [{"name": "GRP SECTION", "items": [
        {"text": "{{external_length}}mm x {{external_width}}mm",
         "note": "VIN {{vin}}", "sub_items": ["cutout {{fridge_cutout_width}}"]}]}]
    out = substitute_sections(sections, {"external_length": "7 500", "external_width": "2 600",
                                         "vin": "ABC123", "fridge_cutout_width": "1 250"})
    item = out[0]["items"][0]
    assert item["text"] == "7 500mm x 2 600mm"
    assert item["note"] == "VIN ABC123"
    assert item["sub_items"] == ["cutout 1 250"]
    assert sections[0]["items"][0]["text"].startswith("{{")    # input untouched (deep copy)


def test_build_context_from_real_shapes():
    """Context reads dimensions_json {length,width,height} in METRES (the §3.0-style catch)."""
    from app.database import SessionLocal, CalculationRecord
    from app.services.template_variables import build_context
    with SessionLocal() as db:
        calc = (db.query(CalculationRecord)
                .filter(CalculationRecord.dimensions_json.isnot(None))
                .order_by(CalculationRecord.id).first())
        if calc is None:
            pytest.skip("no calc with dimensions on this DB")
        ctx = build_context(db, None, calc=calc)
    import json
    dims = json.loads(calc.dimensions_json or "{}")
    if "length" in dims:
        assert ctx["external_length"].replace(" ", "").isdigit()
        assert int(ctx["external_length"].replace(" ", "")) == int(round(dims["length"] * 1000))


# ── §3.6 token fallback: chassis_make_model "Pending — to be confirmed" ──────────
def test_chassis_make_model_pending_when_empty():
    from app.services.template_variables import substitute_text
    # vin keeps "Pending"; chassis_make_model gets its own placeholder (§0.10)
    assert substitute_text("Chassis: {{chassis_make_model}}", {"chassis_make_model": None}) == \
        "Chassis: Pending — to be confirmed"
    assert substitute_text("Chassis: {{chassis_make_model}}", {"chassis_make_model": "  "}) == \
        "Chassis: Pending — to be confirmed"
    assert substitute_text("VIN {{vin}}", {"vin": None}) == "VIN Pending"          # unchanged
    assert substitute_text("Chassis: {{chassis_make_model}}",
                           {"chassis_make_model": "FAW 28.330"}) == "Chassis: FAW 28.330"  # real value wins


def test_build_context_always_sets_chassis_make_model():
    from types import SimpleNamespace
    from app.services.template_variables import build_context, substitute_text
    # card with no make → key PRESENT (not omitted) so it resolves to the placeholder, not the raw token
    card = SimpleNamespace(vin_number=None, body_description=None, fridge_model=None,
                           chassis_make_model=None)
    ctx = build_context(None, card)
    assert "chassis_make_model" in ctx and ctx["chassis_make_model"] is None
    assert substitute_text("Chassis: {{chassis_make_model}}", ctx) == "Chassis: Pending — to be confirmed"
    assert "chassis_make_model" in build_context(None, None)    # even calc-only / no-card renders


def test_build_context_chassis_make_model_precedence():
    from types import SimpleNamespace
    from app.services.template_variables import build_context
    card = SimpleNamespace(vin_number=None, body_description=None, fridge_model=None,
                           chassis_make_model="Card Make")
    chassis = SimpleNamespace(vin="V1", make="Chassis", model="Make")
    assert build_context(None, card, chassis=chassis)["chassis_make_model"] == "Chassis Make"  # chassis overrides
    bare = SimpleNamespace(vin="V1", make=None, model=None)
    assert build_context(None, card, chassis=bare)["chassis_make_model"] == "Card Make"         # card value kept


# ── normalizer ────────────────────────────────────────────────────────────────
def test_normalize_item_patterns():
    from scripts.normalize_template_tokens import normalize_header, normalize_item_text
    t, fixes = normalize_item_text(
        "External dimensions – 0 000mm o/a (l) x 0 000mm o/a (w) x 0 000mm o/a (h)")
    assert t == ("External dimensions – {{external_length}}mm o/a (l) x "
                 "{{external_width}}mm o/a (w) x {{external_height}}mm o/a (h)")
    # sized templates tokenize too (values come back from the costing at card creation)
    t2, _ = normalize_item_text("External dimensions – 5 400mm o/a (l) x 2 300mm o/a (w)")
    assert "{{external_length}}mm o/a (l)" in t2 and "{{external_width}}mm o/a (w)" in t2
    t3, fixes3 = normalize_item_text("Provision for ------ fridge unit – cut out.")
    assert t3 == "Provision for {{fridge_make}} fridge unit – cut out."
    t4, fixes4 = normalize_item_text("Floor 93mm – 76 EPS, 24 density")   # no false positives
    assert t4 == "Floor 93mm – 76 EPS, 24 density" and fixes4 == []
    h, hfix = normalize_header("0 000mm G.R.P Explosive Body Chassis:  ------- VIN Nr:")
    assert "{{external_length}}mm" in h and "{{chassis_make_model}}" in h and h.endswith("{{vin}}")


# ── fridge DDM ────────────────────────────────────────────────────────────────
def test_seed_fridge_units_idempotent():
    from scripts.seed_fridge_units import seed, DRAWING_A_ROWS
    r1 = seed()
    r2 = seed()
    assert r1["total"] == len(DRAWING_A_ROWS) == 30
    assert r2["created"] == 0 and r2["skipped"] == 30          # second run skips everything


def test_fridge_options_endpoint_active_only():
    import app.main as m
    from app.database import SessionLocal, User
    from app.deps import require_user
    from app.models.mes import FridgeUnit
    from starlette.testclient import TestClient
    with SessionLocal() as db:
        admin = db.query(User).filter_by(username="admin").first()
        bench = FridgeUnit(manufacturer="P433F", model="X", display_name="P433F X",
                           mounting_drawing="A", is_active=False, created_by="t")
        db.add(bench)
        db.commit()
        bid = bench.id
    m.app.dependency_overrides[require_user] = lambda: admin
    try:
        with TestClient(m.app) as c:
            rows = c.get("/api/prejob-cards/fridge-options").json()
            names = {r["display_name"] for r in rows}
            assert "Transfrig KV 760i" in names                 # Drawing-A seed present
            assert "P433F X" not in names                       # inactive hidden
            kv = next(r for r in rows if r["display_name"] == "Transfrig KV 760i")
            assert kv["cutout_width_mm"] == 1250 and kv["cutout_height_mm"] == 325
    finally:
        m.app.dependency_overrides.pop(require_user, None)
        with SessionLocal() as db:
            row = db.get(FridgeUnit, bid)
            if row:
                db.delete(row)
                db.commit()
