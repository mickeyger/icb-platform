"""Read-only tools exposed to the Claude help assistant.

Each tool function:
  - takes (user, db, **args)
  - checks the matching `user_can` permission FIRST
  - runs a small read-only query
  - returns a JSON-serialisable dict
  - is permission-aware: prices/totals are redacted via redact.redact()

The dispatcher (`dispatch`) is the only entry point Claude can call. The TOOLS
dict is an explicit allowlist — there is no fallback to dynamic table access,
so the auth/permission tables (users, user_sessions, etc.) are unreachable by
construction.
"""

from __future__ import annotations

from typing import Any
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import (
    User,
    Material,
    MaterialCategory,
    TrailerType,
    BillOfMaterial,
    BOMSection,
    ChassisOption,
    Formula,
    Customer,
    ReportTemplate,
    CalculationRecord,
)
from ..deps import user_can
from .redact import redact

ROW_CAP = 50  # max rows returned by any tool

# ── Tool definitions sent to Claude ────────────────────────────────────────────
# IMPORTANT: keep names in sync with the TOOLS dict below.
TOOL_SCHEMAS: list[dict] = [
    {
        "name": "lookup_material",
        "description": "Search the master materials list by name, SAP code, or material code. Returns up to 50 matches with unit, supplier, category, and price (price omitted if the user lacks bom.view_prices). Requires menu.materials.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Free-text fragment to match against material name, sap_code, or material_code."}
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_materials",
        "description": "List materials, optionally filtered by category name. Returns up to 50 rows. Requires menu.materials.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Category name fragment (optional)."},
                "limit": {"type": "integer", "description": "Max rows (1-50). Default 20."},
            },
        },
    },
    {
        "name": "lookup_body_template",
        "description": "Search body templates (trailer types) by name. Returns matching bodies with default dimensions, markup %, configurator_v2 flag, and BOM section names. Requires menu.body_templates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Name fragment."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "lookup_chassis",
        "description": "Search chassis options. Returns name, axles, base cost (if visible), and supplier. Requires menu.chassis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Name fragment."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_formula",
        "description": "Look up a named formula from the BOM formula library by exact name. Returns the formula expression and description. Requires menu.body_templates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Exact formula name (case-insensitive)."},
            },
            "required": ["name"],
        },
    },
    {
        "name": "lookup_customer",
        "description": "Search customers by name or email. Requires menu.customers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Name or email fragment."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "lookup_quote_template",
        "description": "Search quote/report templates by name. Requires menu.templates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Name fragment."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_costing",
        "description": "Fetch a saved costing by its ID. Returns customer, body, chassis, status, quote number, and totals (totals omitted if the user lacks bom.view_full_cost). Requires menu.dashboard OR menu.calculator.",
        "input_schema": {
            "type": "object",
            "properties": {
                "costing_id": {"type": "integer", "description": "CalculationRecord.id"},
            },
            "required": ["costing_id"],
        },
    },
    {
        "name": "propose_actions",
        "description": (
            "Offer the user 1-4 compact action buttons that, when clicked, "
            "manipulate the page on the user's behalf (scroll/highlight/navigate). "
            "ONLY call this when the page_context contains \"suggest_actions\": true — "
            "the user has explicitly opted in. Each action MUST be one of the "
            "allowlisted types below; any other type is rejected. After calling this "
            "tool no further reply is expected — the buttons appear under your last "
            "text message. The button labels are user-facing, so keep them short, "
            "imperative, and friendly (e.g. \"Show me the R0 lines\", \"Open Materials\")."
            "\n\nAllowlisted action types and their params:\n"
            "- highlight_bom_lines: {materials?: string[], categories?: string[]} — "
            "flashes a coloured border around BOM result rows matching ANY of the given "
            "material names or section/category labels. Use this to point out specific "
            "problem lines (e.g. R0 rows).\n"
            "- highlight_element: {target: string} — flashes a UI element. target must "
            "be one of: 'bom-area', 'chassis-dropdown', 'body-dropdown', "
            "'dimensions-section', 'totals-section', 'save-button', 'quote-pdf-button', "
            "'help-attach-button'.\n"
            "- scroll_to: {target: string} — same target enum as highlight_element, "
            "but scrolls without flashing.\n"
            "- navigate: {path: string} — sends the user to another page. Path must "
            "be one of: '/', '/calculator', '/calculator2', '/admin/materials', "
            "'/admin/templates', '/admin/chassis', '/admin/customers', '/admin/formulas', "
            "'/admin/permissions', '/admin/users', '/admin/themes'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "intro": {
                    "type": "string",
                    "description": "Optional short label above the buttons (e.g. 'Want me to:').",
                },
                "actions": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 4,
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string", "description": "Button text, <40 chars."},
                            "type":  {"type": "string"},
                            "params": {"type": "object"},
                        },
                        "required": ["label", "type"],
                    },
                },
            },
            "required": ["actions"],
        },
    },
]


# ── Permission gate helper ────────────────────────────────────────────────────
def _deny(perm: str) -> dict:
    return {"error": "permission_denied", "permission": perm,
            "message": f"You don't have the '{perm}' permission. Ask an admin to grant it."}


# ── Tool implementations ──────────────────────────────────────────────────────

def lookup_material(user: User, db: Session, query: str = "") -> dict:
    if not user_can(user, "menu.materials", db):
        return _deny("menu.materials")
    q = (query or "").strip()
    if not q:
        return {"results": [], "note": "Provide a query string."}
    like = f"%{q}%"
    rows = (db.query(Material)
              .filter(or_(Material.name.ilike(like),
                          Material.sap_code.ilike(like),
                          Material.material_code.ilike(like)))
              .filter(Material.is_active == True)  # noqa: E712
              .limit(ROW_CAP).all())
    results = [{
        "id": m.id,
        "name": m.name,
        "category": m.category.name if m.category else None,
        "unit": m.unit_of_measure,
        "price_per_unit": m.price_per_unit,
        "supplier": m.supplier,
        "sap_code": m.sap_code,
        "material_code": m.material_code,
        "size": m.size,
    } for m in rows]
    return redact({"results": results, "count": len(results)}, user)


def list_materials(user: User, db: Session, category: str | None = None, limit: int = 20) -> dict:
    if not user_can(user, "menu.materials", db):
        return _deny("menu.materials")
    limit = max(1, min(int(limit or 20), ROW_CAP))
    q = db.query(Material).filter(Material.is_active == True)  # noqa: E712
    if category:
        q = q.join(MaterialCategory).filter(MaterialCategory.name.ilike(f"%{category}%"))
    rows = q.order_by(Material.name).limit(limit).all()
    results = [{
        "id": m.id, "name": m.name,
        "category": m.category.name if m.category else None,
        "unit": m.unit_of_measure,
        "price_per_unit": m.price_per_unit,
    } for m in rows]
    return redact({"results": results, "count": len(results)}, user)


def lookup_body_template(user: User, db: Session, query: str = "") -> dict:
    if not user_can(user, "menu.body_templates", db):
        return _deny("menu.body_templates")
    q = (query or "").strip()
    if not q:
        return {"results": []}
    like = f"%{q}%"
    rows = (db.query(TrailerType)
              .filter(TrailerType.name.ilike(like))
              .filter(TrailerType.is_active == True)  # noqa: E712
              .limit(ROW_CAP).all())
    results = []
    for t in rows:
        # BOMSection rows are shared across trailers; collect the sections
        # this body actually references via its BOM rows.
        section_names = [
            s.name for s in (
                db.query(BOMSection)
                  .join(BillOfMaterial, BillOfMaterial.bom_section_id == BOMSection.id)
                  .filter(BillOfMaterial.trailer_type_id == t.id)
                  .order_by(BOMSection.sort_order)
                  .distinct()
                  .limit(50).all()
            )
        ]
        results.append({
            "id": t.id, "name": t.name, "description": t.description,
            "default_length": t.default_length,
            "default_width": t.default_width,
            "default_height": t.default_height,
            "markup_percentage": t.markup_percentage,
            "configurator_v2": bool(t.configurator_v2),
            "protect_overrides": bool(t.protect_overrides),
            "bom_section_names": section_names,
        })
    return redact({"results": results, "count": len(results)}, user)


def lookup_chassis(user: User, db: Session, query: str = "") -> dict:
    if not user_can(user, "menu.chassis", db):
        return _deny("menu.chassis")
    q = (query or "").strip()
    if not q:
        return {"results": []}
    like = f"%{q}%"
    rows = (db.query(ChassisOption)
              .filter(ChassisOption.label.ilike(like))
              .filter(ChassisOption.is_active == True)  # noqa: E712
              .limit(ROW_CAP).all())
    results = [{
        "id": c.id,
        "label": c.label,
        "kind": c.kind,
        "axle_count": c.axle_count,
        "tyre_style": c.tyre_style,
        "price": c.price,
    } for c in rows]
    return redact({"results": results, "count": len(results)}, user)


def get_formula(user: User, db: Session, name: str = "") -> dict:
    if not user_can(user, "menu.body_templates", db):
        return _deny("menu.body_templates")
    n = (name or "").strip()
    if not n:
        return {"error": "missing_argument", "message": "Provide a formula name."}
    row = db.query(Formula).filter(Formula.name.ilike(n)).first()
    if not row:
        return {"found": False, "name": n}
    return {
        "found": True,
        "name": row.name,
        "expression": row.expression,
        "description": row.description,
    }


def lookup_customer(user: User, db: Session, query: str = "") -> dict:
    if not user_can(user, "menu.customers", db):
        return _deny("menu.customers")
    q = (query or "").strip()
    if not q:
        return {"results": []}
    like = f"%{q}%"
    rows = (db.query(Customer)
              .filter(or_(Customer.name.ilike(like),
                          Customer.email.ilike(like),
                          Customer.bp_code.ilike(like)))
              .filter(Customer.is_active == True)  # noqa: E712
              .limit(ROW_CAP).all())
    results = [{
        "id": c.id, "name": c.name,
        "bp_code": c.bp_code,
        "email": c.email,
        "telephone": c.telephone,
    } for c in rows]
    return {"results": results, "count": len(results)}


def lookup_quote_template(user: User, db: Session, query: str = "") -> dict:
    if not user_can(user, "menu.templates", db):
        return _deny("menu.templates")
    q = (query or "").strip()
    like = f"%{q}%" if q else "%"
    rows = (db.query(ReportTemplate)
              .filter(ReportTemplate.name.ilike(like))
              .limit(ROW_CAP).all())
    results = [{
        "id": t.id, "name": t.name,
        "kind": getattr(t, "kind", None),
        "pdf_template_id": getattr(t, "pdf_template_id", None),
    } for t in rows]
    return {"results": results, "count": len(results)}


def get_costing(user: User, db: Session, costing_id: int = 0) -> dict:
    if not (user_can(user, "menu.dashboard", db) or user_can(user, "menu.calculator", db)):
        return _deny("menu.dashboard")
    try:
        cid = int(costing_id)
    except (TypeError, ValueError):
        return {"error": "missing_argument", "message": "costing_id must be an integer."}
    rec = db.query(CalculationRecord).filter_by(id=cid).first()
    if not rec:
        return {"found": False, "costing_id": cid}
    body_name = None
    if getattr(rec, "trailer_type_id", None):
        t = db.query(TrailerType).filter_by(id=rec.trailer_type_id).first()
        if t:
            body_name = t.name
    customer_name = None
    if getattr(rec, "customer_id", None):
        c = db.query(Customer).filter_by(id=rec.customer_id).first()
        if c:
            customer_name = c.name
    # Totals live in result_json — pull just the headline summary, not the
    # full BOM (that can be 100+ KB).
    summary: dict[str, Any] = {}
    if rec.result_json:
        try:
            import json
            payload = json.loads(rec.result_json)
            if isinstance(payload, dict):
                for k in ("grand_total", "total_cost", "selling_price",
                          "markup_percentage", "cost_per_m2",
                          "chassis_cost", "body_cost", "subtotal"):
                    if k in payload:
                        summary[k] = payload[k]
        except (ValueError, TypeError):
            pass
    result = {
        "found": True,
        "id": rec.id,
        "body": body_name,
        "customer": customer_name,
        "status": rec.status,
        "quote_number": rec.quote_number,
        "is_repair": bool(rec.is_repair),
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "summary": summary,
    }
    return redact(result, user)


# ── UI actions (validated, then emitted to the browser as a separate event) ──

ALLOWED_ACTION_TYPES = {
    "highlight_bom_lines", "highlight_element", "scroll_to", "navigate",
}
ALLOWED_TARGETS = {
    "bom-area", "chassis-dropdown", "body-dropdown",
    "dimensions-section", "totals-section",
    "save-button", "quote-pdf-button", "help-attach-button",
}
ALLOWED_PATHS = {
    "/", "/calculator", "/calculator2",
    "/admin/materials", "/admin/templates", "/admin/chassis",
    "/admin/customers", "/admin/formulas", "/admin/permissions",
    "/admin/users", "/admin/themes",
}


def validate_actions(payload: dict) -> dict:
    """Strict allowlist validation. Returns either {ok: True, intro, actions}
    or {error, message}. Used by the router when Claude calls propose_actions;
    rejected actions never reach the browser."""
    if not isinstance(payload, dict):
        return {"error": "bad_payload", "message": "payload must be an object"}
    raw_actions = payload.get("actions")
    if not isinstance(raw_actions, list) or not raw_actions:
        return {"error": "no_actions", "message": "actions list missing or empty"}

    valid: list[dict] = []
    for i, a in enumerate(raw_actions[:4]):
        if not isinstance(a, dict):
            continue
        label = (a.get("label") or "").strip()[:40]
        atype = a.get("type")
        params = a.get("params") or {}
        if not label or atype not in ALLOWED_ACTION_TYPES:
            continue
        if not isinstance(params, dict):
            continue

        clean_params: dict[str, Any] = {}
        if atype == "highlight_bom_lines":
            mats = params.get("materials") or []
            cats = params.get("categories") or []
            if not isinstance(mats, list) and not isinstance(cats, list):
                continue
            clean_params["materials"]  = [str(x)[:200] for x in (mats or []) if isinstance(x, (str, int, float))][:30]
            clean_params["categories"] = [str(x)[:200] for x in (cats or []) if isinstance(x, (str, int, float))][:30]
            if not clean_params["materials"] and not clean_params["categories"]:
                continue
        elif atype in ("highlight_element", "scroll_to"):
            tgt = params.get("target")
            if tgt not in ALLOWED_TARGETS:
                continue
            clean_params["target"] = tgt
        elif atype == "navigate":
            path = params.get("path")
            if path not in ALLOWED_PATHS:
                continue
            clean_params["path"] = path

        valid.append({"label": label, "type": atype, "params": clean_params})

    if not valid:
        return {"error": "no_valid_actions", "message": "all actions failed validation"}

    intro = (payload.get("intro") or "").strip()[:80] or None
    return {"ok": True, "intro": intro, "actions": valid}


# ── Dispatcher (Claude's only entry point) ────────────────────────────────────

TOOLS = {
    "lookup_material":       lookup_material,
    "list_materials":        list_materials,
    "lookup_body_template":  lookup_body_template,
    "lookup_chassis":        lookup_chassis,
    "get_formula":           get_formula,
    "lookup_customer":       lookup_customer,
    "lookup_quote_template": lookup_quote_template,
    "get_costing":           get_costing,
}

# propose_actions is handled by the router directly (not the dispatcher) because
# it produces a side-channel event (`actions` SSE) rather than a tool_result the
# model needs to read. Keeping it out of TOOLS prevents the dispatcher from
# trying to invoke it as a regular tool.


def dispatch(tool_name: str, tool_input: dict, user: User, db: Session) -> dict:
    """Run a Claude tool call. Returns the dict that goes back to Claude as
    tool_result content. Never raises — all errors are returned as structured
    dicts so the model can relay them to the user."""
    fn = TOOLS.get(tool_name)
    if not fn:
        return {"error": "unknown_tool", "tool": tool_name}
    args = dict(tool_input or {})
    try:
        return fn(user=user, db=db, **args)
    except TypeError as e:
        return {"error": "bad_arguments", "tool": tool_name, "message": str(e)}
    except Exception as e:
        return {"error": "tool_failed", "tool": tool_name, "message": str(e)[:200]}
