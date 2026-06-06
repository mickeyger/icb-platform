"""WO v4.25 — the database-backed BOM rules engine (Phase 3 §4.1).

Replaces the v4.24 spike's hand-ported geometry with rules loaded from icb_mes.bom_rules,
evaluated by an AST-safe evaluator, resolved to SAP codes via icb_mes.bom_rule_lookups, and
priced via icb_mes.material_price_overrides → icb_sap.OITM. The spike's geometry.py stays the
parity oracle (tests/test_v4_25_rules_engine_parity.py).
"""
from .evaluator import EvaluationError, evaluate

__all__ = ["evaluate", "EvaluationError"]
