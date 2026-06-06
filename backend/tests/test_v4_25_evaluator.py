"""WO v4.25 §3.2/§3.8 — AST-safe evaluator: positive + adversarial (security) tests.

Pure (no DB). The evaluator is the foundational correctness + security layer under the rules
engine: valid formulas evaluate correctly; every non-whitelisted construct raises immediately.
"""
import pytest

from app.services.rules_engine.evaluator import EvaluationError, evaluate

CTX = {"length_mm": 5400, "width_mm": 2300, "height_mm": 2300, "reveal_side_mm": 65,
       "reveal_top_mm": 81, "panel_length_mm": 2440, "floor_present": True}


# ── positive cases ──
def test_arithmetic_and_ceil():
    assert evaluate("ceil((length_mm - 275) / 1220)", CTX) == 5
    assert evaluate("ceil((length_mm - 275) / 1220) * 2", CTX) == 10
    assert evaluate("ceil((width_mm - reveal_side_mm * 2 - 100) / 1220)", CTX) == 2


def test_ceil_is_epsilon_aware():
    # the 1e-9 epsilon mirrors the spike's _roundup: exact integers stay, genuine remainders
    # round up, and sub-epsilon float noise is absorbed (won't bump a panel boundary).
    assert evaluate("ceil(4.0)", {}) == 4                       # exact integer stays
    assert evaluate("ceil(4.2)", {}) == 5                       # genuine remainder rounds up
    assert evaluate("ceil(4 + 0.0000000001)", {}) == 4         # 1e-10 noise (< 1e-9) absorbed -> 4
    assert evaluate("floor(5 - 0.0000000001)", {}) == 5        # 1e-10 noise absorbed -> 5


def test_ternary_and_floor_present():
    assert evaluate("reveal_top_mm if floor_present else 0", CTX) == 81
    assert evaluate("reveal_top_mm if (length_mm > 99999) else 0", CTX) == 0


def test_min_max_abs_round():
    assert evaluate("min(3, 5)", {}) == 3
    assert evaluate("max(3, 5)", {}) == 5
    assert evaluate("abs(0 - 7)", {}) == 7
    assert evaluate("round(4.5)", {}) in (4, 5)  # banker's rounding tolerated


# ── adversarial cases — MUST raise EvaluationError ──
@pytest.mark.parametrize("expr", [
    "__import__('os').system('echo hi')",   # import via dunder
    "length_mm.__class__",                   # attribute access
    "open('/etc/passwd')",                   # disallowed call
    "eval('1+1')",                           # disallowed call
    "exec('x=1')",                           # disallowed call
    "(lambda: 1)()",                         # lambda
    "[x for x in range(3)]",                 # comprehension
    "length_mm[0]",                          # subscript
    "{'a': 1}",                              # dict literal
    "globals()",                             # disallowed call
    "length_mm; width_mm",                   # multiple statements (parse fails in eval mode)
])
def test_rejects_non_whitelisted(expr):
    with pytest.raises(EvaluationError):
        evaluate(expr, CTX)


def test_unknown_variable_raises():
    with pytest.raises(EvaluationError):
        evaluate("not_a_field + 1", CTX)


def test_div_by_zero_raises_evaluation_error():
    with pytest.raises(EvaluationError):
        evaluate("length_mm / 0", CTX)
