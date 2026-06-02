"""Permission-aware redaction for help-assistant payloads.

Used in two places:
- Page-context preprocessing (frontend may pass costing totals etc.)
- Tool-result post-processing (DB rows fed back to Claude)

Strips price / cost / total fields when the caller lacks the matching
permission. Keys are matched case-insensitively against a small set of
sensitive substrings.
"""

from typing import Any

from ..deps import user_can
from ..database import User

PRICE_KEY_HINTS = ("price", "cost", "total", "subtotal", "markup", "margin")


def _has_price_hint(key: str) -> bool:
    k = key.lower()
    return any(h in k for h in PRICE_KEY_HINTS)


def redact(obj: Any, user: User) -> Any:
    """Recursively walk obj and blank out price-ish keys when the user lacks
    the matching permission. Mutates dicts in-place and returns the same obj
    for convenience; lists are walked element-by-element.
    """
    can_prices = user_can(user, "bom.view_prices")
    can_totals = user_can(user, "bom.view_full_cost")
    if can_prices and can_totals:
        return obj
    return _walk(obj, can_prices, can_totals)


def _walk(obj: Any, can_prices: bool, can_totals: bool) -> Any:
    if isinstance(obj, dict):
        for k in list(obj.keys()):
            v = obj[k]
            if _has_price_hint(k):
                # Total/grand-total style fields need bom.view_full_cost
                lk = k.lower()
                if ("total" in lk or "subtotal" in lk or "grand" in lk) and not can_totals:
                    obj[k] = None
                elif not can_prices:
                    obj[k] = None
                else:
                    obj[k] = _walk(v, can_prices, can_totals)
            else:
                obj[k] = _walk(v, can_prices, can_totals)
        return obj
    if isinstance(obj, list):
        return [_walk(x, can_prices, can_totals) for x in obj]
    return obj
