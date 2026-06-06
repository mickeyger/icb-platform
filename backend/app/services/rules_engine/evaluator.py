"""WO v4.25 §3.2 — AST-safe expression evaluator for BOM rule formulas.

SECURITY-CRITICAL (§0.2 / §2): rule formulas are data executed against real specs. The
evaluator parses an expression to an AST and rejects ANY node type or function call not on
the whitelist — immediately, no "harden later". No imports, no attribute access, no
subscripting, no comprehensions, no lambdas, no calls except the whitelisted math helpers.

`ceil`/`floor` are epsilon-aware to bit-match the v4.24 spike's `_roundup`
(`ceil(x - 1e-9)`), so float noise can't bump an exact integer across a panel boundary —
this is what guarantees the binary parity gate (§0.3).
"""
import ast
import math
from typing import Mapping

__all__ = ["evaluate", "EvaluationError"]


class EvaluationError(ValueError):
    """Raised on any disallowed construct, unknown name, or runtime error in a rule formula."""


def _ceil(x):
    return math.ceil(x - 1e-9)


def _floor(x):
    return math.floor(x + 1e-9)


# Whitelisted callables (names only — no attribute access to reach them).
ALLOWED_FUNCTIONS = {
    "ceil": _ceil, "floor": _floor, "round": round,
    "min": min, "max": max, "abs": abs,
}

# Whitelisted AST node types. Anything else → EvaluationError.
ALLOWED_NODES = {
    ast.Expression, ast.Constant, ast.Name, ast.Load,
    ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.UnaryOp, ast.USub, ast.UAdd, ast.Not,
    ast.BoolOp, ast.And, ast.Or,
    ast.Compare, ast.Lt, ast.Gt, ast.LtE, ast.GtE, ast.Eq, ast.NotEq,
    ast.IfExp,
    ast.Call,  # only with a whitelisted Name func + positional args
}


def _validate(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if type(node) not in ALLOWED_NODES:
            raise EvaluationError(f"disallowed expression construct: {type(node).__name__}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_FUNCTIONS:
                fn = getattr(node.func, "id", type(node.func).__name__)
                raise EvaluationError(f"disallowed function call: {fn}")
            if node.keywords:
                raise EvaluationError("keyword arguments are not allowed in rule formulas")


def _eval(node: ast.AST, ctx: Mapping):
    if isinstance(node, ast.Expression):
        return _eval(node.body, ctx)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, bool)):
            return node.value
        raise EvaluationError(f"disallowed constant type: {type(node.value).__name__}")
    if isinstance(node, ast.Name):
        if node.id in ctx:
            return ctx[node.id]
        raise EvaluationError(f"unknown variable in formula: {node.id!r}")
    if isinstance(node, ast.BinOp):
        a, b = _eval(node.left, ctx), _eval(node.right, ctx)
        op = type(node.op)
        if op is ast.Add:
            return a + b
        if op is ast.Sub:
            return a - b
        if op is ast.Mult:
            return a * b
        if op is ast.Div:
            return a / b
        if op is ast.FloorDiv:
            return a // b
        if op is ast.Mod:
            return a % b
        if op is ast.Pow:
            return a ** b
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, ctx)
        op = type(node.op)
        if op is ast.USub:
            return -v
        if op is ast.UAdd:
            return +v
        if op is ast.Not:
            return not v
    if isinstance(node, ast.BoolOp):
        vals = [_eval(v, ctx) for v in node.values]
        if isinstance(node.op, ast.And):
            return all(vals)
        return any(vals)
    if isinstance(node, ast.IfExp):
        return _eval(node.body, ctx) if _eval(node.test, ctx) else _eval(node.orelse, ctx)
    if isinstance(node, ast.Compare):
        left = _eval(node.left, ctx)
        for op, comp in zip(node.ops, node.comparators):
            right = _eval(comp, ctx)
            ok = {
                ast.Lt: left < right, ast.Gt: left > right, ast.LtE: left <= right,
                ast.GtE: left >= right, ast.Eq: left == right, ast.NotEq: left != right,
            }[type(op)]
            if not ok:
                return False
            left = right
        return True
    if isinstance(node, ast.Call):
        args = [_eval(a, ctx) for a in node.args]
        return ALLOWED_FUNCTIONS[node.func.id](*args)
    raise EvaluationError(f"disallowed expression construct: {type(node).__name__}")


def validate_expression(expression: str) -> None:
    """Parse + whitelist-check a formula WITHOUT executing it (WO v4.26 §0.7). Raises
    EvaluationError on a syntax error or any disallowed construct. Used by admin create/update
    + the POST /api/admin/bom-rules/validate-formula endpoint."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise EvaluationError(f"invalid formula syntax: {e}") from e
    _validate(tree)


def evaluate(expression: str, context: Mapping) -> float:
    """Evaluate a rule expression against a flat spec context. Raises EvaluationError on
    any non-whitelisted construct, unknown variable, or runtime error (e.g. div-by-zero)."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise EvaluationError(f"invalid formula syntax: {e}") from e
    _validate(tree)
    try:
        return _eval(tree, context)
    except EvaluationError:
        raise
    except Exception as e:  # ZeroDivisionError, TypeError on bad spec values, etc.
        raise EvaluationError(f"formula evaluation failed: {e}") from e
