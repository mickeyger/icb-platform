"""WO v4.26 §3.7/§3.8/§3.9 — extended evaluator adversarial vectors, DDM resolution per body type,
admin CRUD, validation + role-gating, and the early-binding raw endpoint path.

Rules + lookups + spec options are seeded idempotently in a fixture so tests are self-contained.
"""
import pytest

from app.database import SessionLocal

# ── job 32735 raw (dropdown labels) — source: COSTING MODULE DDM + v4.24 fixture ──
RAW_32735 = dict(
    job=32735, body_type="Freezer", length_mm=5400, width_mm=2300, height_mm=2300,
    roof=dict(material="EPS 24DV", thickness="76", skin="None"),
    sides=dict(material="PU 32DV", thickness="56", skin="4mm Plywood"),
    floor=dict(material="EPS 24DV", thickness="76", skin="12mm Finn"),
    front=dict(material="PU 32DV", thickness="56", skin="4mm Plywood"),
    rear=dict(material="PU 32DV", thickness="60", skin="6mm Plywood"),
)


@pytest.fixture(scope="module")
def seeded():
    from scripts.seed_v4_25_rules import seed_rules
    from scripts.seed_v4_26_spec_options import seed_spec_options
    with SessionLocal() as db:
        seed_rules(db)
        seed_spec_options(db)
        db.commit()
    yield


# ── §3.7 extended evaluator adversarial vectors (whitelist NOT widened; these reject) ──
@pytest.mark.parametrize("expr", [
    "f'len is {length_mm}'",        # f-string (ast.JoinedStr)
    "(x := length_mm)",              # walrus (ast.NamedExpr)
    "max(*[1, 2, 3])",               # starred (ast.Starred)
    "sum(x for x in range(3))",      # generator expression (ast.GeneratorExp)
])
def test_rejects_extended_adversarial(expr):
    from app.services.rules_engine.evaluator import EvaluationError, evaluate, validate_expression
    with pytest.raises(EvaluationError):
        evaluate(expr, {"length_mm": 5400})
    with pytest.raises(EvaluationError):
        validate_expression(expr)   # parse-only path (admin create/update) also rejects


# ── §3.3 DDM resolver ──
def test_resolver_exact_fallback_and_miss(seeded):
    from app.services.rules_engine.ddm_resolver import resolve_spec, SpecResolutionError
    with SessionLocal() as db:
        # options are seeded body_type='*' → exact Freezer miss falls back to '*'
        assert resolve_spec(db, "roof_material", "Freezer", "EPS 24DV").spec_value == "EPS 24DV"
        assert resolve_spec(db, "roof_material", "Chiller", "PU 32DV").spec_value == "PU 32DV"
        with pytest.raises(SpecResolutionError):
            resolve_spec(db, "roof_material", "Freezer", "UNOBTANIUM")


def test_freezer_raw_resolves_to_full_bom(seeded):
    """Early-binding end-to-end: raw dropdowns → resolved JobSpec → engine → 9 lines, correct codes."""
    from app.schemas.bom import JobSpecRaw
    from app.services.rules_engine.ddm_resolver import resolve_jobspec_raw
    from app.services.rules_engine.engine import RulesEngine
    from collections import Counter
    with SessionLocal() as db:
        spec = resolve_jobspec_raw(db, JobSpecRaw.model_validate(RAW_32735))
        assert spec.roof.thickness_mm == 76 and spec.roof.material == "EPS 24DV"
        out = RulesEngine(db).generate_bom(spec)
    codes = Counter(ln.sap_code for ln in out.lines)
    assert len(out.lines) == 9
    assert codes == {"GRP-MPS-A-0077": 2, "GRP-POL-A-0158": 2, "GRP-PUS-A-0031": 1,
                     "GRP-TIM-A-0005": 1, "GRP-TIM-A-0007": 2, "GRP-TIM-A-0008": 1}


@pytest.mark.parametrize("body_type", ["Chiller", "Dryfreight", "Insulated Trailer"])
def test_per_body_type_resolution_structural(seeded, body_type):
    """Non-Freezer: DDM resolution is structurally correct (dropdowns→specs). Geometry rules are
    Freezer-only until v4.27, so generate_bom yields 0 lines for these — a documented distinction."""
    from app.schemas.bom import JobSpecRaw
    from app.services.rules_engine.ddm_resolver import resolve_jobspec_raw
    from app.services.rules_engine.engine import RulesEngine
    raw = {**RAW_32735, "body_type": body_type}
    with SessionLocal() as db:
        spec = resolve_jobspec_raw(db, JobSpecRaw.model_validate(raw))
        assert spec.roof.material == "EPS 24DV" and spec.sides.thickness_mm == 56  # resolved structurally
        out = RulesEngine(db).generate_bom(spec)
    assert out.lines == [] or len(out.lines) == 0  # no Freezer-specific rules for this body type yet


# ── §3.9 admin CRUD + validation + role-gating (auth injected) ──
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


def test_admin_rule_crud_cycle(seeded, admin_api):
    body = {"body_type": "ZZTEST", "section": "Vacuum Materials", "panel": "P", "output_field": "qty",
            "formula_expression": "ceil(length_mm/1220)"}
    r = admin_api.post("/api/admin/bom-rules", json=body)
    assert r.status_code == 201 and r.json()["created_by"] == "admin"
    rid = r.json()["id"]
    assert admin_api.post("/api/admin/bom-rules", json=body).status_code == 409          # dup UNIQUE
    assert admin_api.patch(f"/api/admin/bom-rules/{rid}", json={"priority": 7}).json()["priority"] == 7
    assert admin_api.post("/api/admin/bom-rules", json={**body, "panel": "Q", "formula_expression": "open('x')"}).status_code == 422
    assert admin_api.delete(f"/api/admin/bom-rules/{rid}").status_code == 204


def test_admin_validation_and_autocomplete(seeded, admin_api):
    # validate-formula
    assert admin_api.post("/api/admin/bom-rules/validate-formula",
                          json={"formula_expression": "ceil(length_mm/1220)"}).json()["valid"] is True
    assert admin_api.post("/api/admin/bom-rules/validate-formula",
                          json={"formula_expression": "__import__('os')"}).json()["valid"] is False
    # override: bad sap_code → 422; bad date range → 422
    assert admin_api.post("/api/admin/material-price-overrides",
                          json={"sap_code": "NOPE-XXX", "override_price": 1}).status_code == 422
    assert admin_api.post("/api/admin/material-price-overrides",
                          json={"sap_code": "GRP-MPS-A-0077", "override_price": 1,
                                "valid_from": "2026-06-01", "valid_to": "2026-05-01"}).status_code == 422
    # OITM autocomplete
    assert any(h["sap_code"] == "GRP-MPS-A-0077"
               for h in admin_api.get("/api/admin/oitm-search?q=GRP-MPS-A-0077").json())


def test_admin_endpoints_require_admin():
    import app.main as m
    from starlette.testclient import TestClient
    with TestClient(m.app) as c:
        assert c.post("/api/admin/bom-rules", json={}).status_code in (401, 403)
        assert c.get("/api/admin/bom-spec-options").status_code in (401, 403)


# ── §0.8 raw entry path on the public endpoint ──
def test_generate_endpoint_raw_mode(seeded):
    import app.main as m
    from app.database import SessionLocal as SL, User
    from app.deps import require_user
    from starlette.testclient import TestClient
    with TestClient(m.app) as c:
        with SL() as db:
            user = db.query(User).filter_by(username="admin").first()
        m.app.dependency_overrides[require_user] = lambda: user
        r = c.post("/api/bom/generate", json={**RAW_32735, "mode": "raw"})
        m.app.dependency_overrides.pop(require_user, None)
    assert r.status_code == 200 and len(r.json()["lines"]) == 9
