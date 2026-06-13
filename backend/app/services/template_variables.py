"""WO v4.33 scope addition — the template-variable substitution engine (ADR 0020 footnote 9).

ONE engine, every consumer (card creation, PDF render, the modal's live fridge substitution
mirrors these exact semantics): tokens never resolve differently in two places by design —
the parity-by-construction shape applied to templated text.

Semantics (BA-locked):
  * `{{token}}` placeholders replace from a context dict.
  * Key ABSENT from the context → token left AS-IS (visible in the UI/PDF so a missing
    binding is spottable, never silently blanked).
  * Key present but value None/empty → "Pending" for {{vin}}, blank otherwise.
  * Lengths format as `5 400` (space-separated thousands — the existing template
    convention); the unit suffix lives in the template text (`{{external_length}}mm`).

Token vocabulary (8 core + 3 fridge bonus):
  external_length / external_width / external_height   <- calculations.dimensions_json
      (NOTE — §3.0-style verification: the BA sketch said calculations.length_mm columns;
      the REAL source is dimensions_json {length, width, height} in METRES -> ×1000)
  fridge_make            <- prejob_cards.fridge_model (the DDM display_name)
  vin                    <- chassis vin ("Pending" when unknown)
  chassis_make_model     <- chassis make/model
  customer_name          <- the costing's customer
  body_description       <- template/card body description
  fridge_drawing / fridge_cutout_width / fridge_cutout_height  <- fridge_units row
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any, Optional

_TOKEN_RE = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
_PENDING_TOKENS = {"vin"}                                  # empty -> "Pending"


def format_mm(value: Any) -> str:
    """5400 -> '5 400' (space thousands). Accepts metres (<= 30 heuristically) or mm."""
    if value is None or value == "":
        return ""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if num <= 30:                                          # dimensions_json carries metres
        num *= 1000
    return f"{int(round(num)):,}".replace(",", " ")


def substitute_text(text: str, context: dict) -> str:
    def _repl(m: re.Match) -> str:
        key = m.group(1)
        if key not in context:
            return m.group(0)                              # absent -> leave visible
        val = context[key]
        if val is None or str(val).strip() == "":
            return "Pending" if key in _PENDING_TOKENS else ""
        return str(val)
    return _TOKEN_RE.sub(_repl, text or "")


def substitute_sections(sections: list, context: dict) -> list:
    """Deep-copies; replaces tokens in item text, notes and sub_items."""
    out = copy.deepcopy(sections or [])
    for section in out:
        for item in section.get("items", []):
            item["text"] = substitute_text(item.get("text", ""), context)
            if item.get("note"):
                item["note"] = substitute_text(item["note"], context)
            if item.get("sub_items"):
                item["sub_items"] = [substitute_text(s, context) for s in item["sub_items"]]
    return out


def build_context(db, card, calc=None, chassis=None,
                  fridge=None) -> dict:
    """Assemble the token context from the card + its costing/chassis/fridge. Keys are
    OMITTED (not blanked) when their source object is missing — leaving tokens visible."""
    ctx: dict[str, Optional[str]] = {}
    if calc is not None:
        dims = {}
        try:
            dims = json.loads(calc.dimensions_json or "{}") or {}
        except (ValueError, TypeError):
            dims = {}
        for token, key in (("external_length", "length"), ("external_width", "width"),
                           ("external_height", "height")):
            if key in dims:
                ctx[token] = format_mm(dims.get(key))
        if calc.customer_id:
            from app.database import Customer
            cust = db.get(Customer, calc.customer_id)
            if cust is not None:
                ctx["customer_name"] = cust.name
    if card is not None:
        ctx["vin"] = card.vin_number                      # None -> "Pending" via semantics
        if card.body_description:
            ctx["body_description"] = card.body_description
        if card.fridge_model:
            ctx["fridge_make"] = card.fridge_model
        if card.chassis_make_model:
            ctx["chassis_make_model"] = card.chassis_make_model
    if chassis is not None:
        ctx.setdefault("vin", chassis.vin)
        mm = " ".join(x for x in (chassis.make, chassis.model) if x)
        if mm:
            ctx["chassis_make_model"] = mm
    if fridge is not None:
        ctx["fridge_make"] = fridge.display_name
        if fridge.mounting_drawing:
            ctx["fridge_drawing"] = fridge.mounting_drawing
        if fridge.cutout_width_mm is not None:
            ctx["fridge_cutout_width"] = format_mm(fridge.cutout_width_mm)
        if fridge.cutout_height_mm is not None:
            ctx["fridge_cutout_height"] = format_mm(fridge.cutout_height_mm)
    return ctx
