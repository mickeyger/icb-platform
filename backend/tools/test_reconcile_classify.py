"""
tools/test_reconcile_classify.py

Unit tests for the line-total root-cause classifier added to the AI Excel
Audit (app/help/reconcile.py):

  • _round_half_up  — Excel ROUND() semantics (half-away-from-zero) vs Python's
                      built-in banker's rounding.
  • _classify_line  — labels a matched line's total difference as
                      price / formula / rounding / unexplained / match.

Runnable two ways:
    pytest tools/test_reconcile_classify.py
    python tools/test_reconcile_classify.py      # prints PASS/FAIL summary
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make `app` importable when running from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.help.reconcile import _round_half_up, _classify_line


# ── _round_half_up ──────────────────────────────────────────────────────────

def test_round_half_up_diverges_from_bankers():
    # The classic split: 0.125 → Excel rounds up to 0.13, Python rounds to even
    # (0.12). This divergence is exactly what the "rounding" cause detects.
    assert _round_half_up(0.125, 2) == 0.13
    assert round(0.125, 2) == 0.12


def test_round_half_up_uses_decimal_string_not_float_artifact():
    # 1.005 as a float is really 1.00499999…; str() preserves the intended
    # value so half-up gives 1.01 (Excel's answer), not 1.00.
    assert _round_half_up(1.005, 2) == 1.01


def test_round_half_up_zero_places():
    assert _round_half_up(2.5, 0) == 3.0
    assert _round_half_up(-2.5, 0) == -3.0   # away from zero, both directions


# ── _classify_line ──────────────────────────────────────────────────────────

def _row(qty, unit, total):
    return {"qty": qty, "unit_price": unit, "total": total}


def test_classify_match():
    res = _classify_line(_row(2, 10.0, 20.0), _row(2, 10.0, 20.0))
    assert res["cause"] == "match"
    assert res["rounding_drift"] == 0.0


def test_classify_price_driven():
    # Same qty, unit price 1250 → 1285. Cause is the price, not the formula.
    res = _classify_line(_row(1, 1250.0, 1250.0), _row(1, 1285.0, 1285.0))
    assert res["cause"] == "price"


def test_classify_formula_driven():
    # Same unit price, qty 12 → 14 (the qty-driving formula diverges).
    res = _classify_line(_row(12, 70.0, 840.0), _row(14, 70.0, 980.0))
    assert res["cause"] == "formula"


def test_classify_rounding_only():
    # qty & unit price agree; the total drifts by a single cent → rounding noise.
    res = _classify_line(_row(3, 1.0, 3.00), _row(3, 1.0, 3.01))
    assert res["cause"] == "rounding"
    assert res["rounding_drift"] == 0.01


def test_classify_unexplained():
    # qty & unit price agree but the total gap is far too large to be rounding.
    res = _classify_line(_row(2, 10.0, 20.0), _row(2, 10.0, 25.0))
    assert res["cause"] == "unexplained"
    assert res["rounding_drift"] is None


def test_classify_missing_total():
    res = _classify_line(_row(2, 10.0, None), _row(2, 10.0, 20.0))
    assert res["cause"] == "unknown"


# ── Direct-run harness ──────────────────────────────────────────────────────

if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {t.__name__}: {e!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
