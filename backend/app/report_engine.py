"""
HTML/Jinja2 + WeasyPrint reporting engine.

Designed to replace the cumbersome overlay-on-PDF workflow for quote-style
documents. Each report type is a single HTML file under app/templates/reports/
with Jinja2 placeholders, rendered against company data + a costing record.

Add a new report type by:
  1. Drop a new template in app/templates/reports/<name>.html
  2. Add a build_<name>_context() builder here that returns the dict
  3. Wire an endpoint that calls render_report("<name>", context)
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

APP_DIR     = os.path.dirname(__file__)
REPORTS_DIR = os.path.join(APP_DIR, "templates", "reports")
STATIC_DIR  = os.path.join(APP_DIR, "static")

_env = Environment(
    loader=FileSystemLoader(REPORTS_DIR),
    autoescape=select_autoescape(["html"]),
)


def _file_url(path: str) -> str:
    """Return a file:// URL for WeasyPrint to resolve local images/css."""
    return "file:///" + os.path.abspath(path).replace("\\", "/")


def _fmt_mm(metres: Optional[float]) -> str:
    """2.4 (m) -> '2 400mm'. None/0 -> '0 000mm' (matches PDF placeholder style)."""
    try:
        mm = int(round(float(metres or 0) * 1000))
    except (TypeError, ValueError):
        mm = 0
    s = f"{mm:,}".replace(",", " ")
    return f"{s}mm"


def _fmt_money_zar(value: Optional[float]) -> str:
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        v = 0.0
    s = f"{v:,.2f}".replace(",", " ")
    return f"R {s}"


def _fmt_date_human(dt: Optional[datetime]) -> str:
    dt = dt or datetime.now()
    import platform
    fmt = "%#d %B %Y" if platform.system() == "Windows" else "%-d %B %Y"
    return dt.strftime(fmt)


def build_explosive_quote_context(
    *,
    record_id: int,
    customer: Optional[Dict[str, Any]],
    dimensions: Dict[str, Any],
    result: Dict[str, Any],
    created_at: Optional[datetime] = None,
    quote_number: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the context dict for explosive_quote.html from a CalculationRecord."""
    customer = customer or {}
    customer_name = (customer.get("name") or "").strip() or "Client Name"

    price_value = result.get("selling_price") or result.get("grand_total") or 0

    sarda_path_fs = os.path.join(STATIC_DIR, "sarda-logo.png")
    logo_path_fs  = os.path.join(STATIC_DIR, "IceCold-Logo.png")
    css_path_fs   = os.path.join(STATIC_DIR, "css", "report.css")

    return {
        "ref_no":        (quote_number or str(record_id)),
        "date":          _fmt_date_human(created_at),
        "customer_name": customer_name.upper() if customer_name else "Client Name",
        "attention":     (customer.get("name") or "").strip() or "",
        "tel_no":        (customer.get("telephone") or "").strip() or "",
        "email":         (customer.get("email") or "").strip() or "",
        "length_mm":     _fmt_mm(dimensions.get("length")),
        "width_mm":      _fmt_mm(dimensions.get("width")),
        "height_mm":     _fmt_mm(dimensions.get("height")),
        "price":         _fmt_money_zar(price_value),
        "logo_path":     _file_url(logo_path_fs)  if os.path.exists(logo_path_fs)  else "",
        "sarda_path":    _file_url(sarda_path_fs) if os.path.exists(sarda_path_fs) else "",
        "css_path":      _file_url(css_path_fs),
        "is_repair":     bool(result.get("is_repair")),
    }


def render_report(template_name: str, context: Dict[str, Any]) -> bytes:
    """Render a report template to PDF bytes via WeasyPrint."""
    try:
        from weasyprint import HTML
    except ImportError as e:
        raise RuntimeError(
            "WeasyPrint is not installed. Add 'weasyprint' to requirements and pip install."
        ) from e

    template = _env.get_template(template_name)
    html_str = template.render(**context)

    base_url = STATIC_DIR  # for relative asset resolution if needed
    pdf_bytes = HTML(string=html_str, base_url=base_url).write_pdf()
    return pdf_bytes


def render_by_slug(
    *,
    slug: str,
    record_id: int,
    customer: Optional[Dict[str, Any]],
    dimensions: Dict[str, Any],
    result: Dict[str, Any],
    created_at: Optional[datetime] = None,
    quote_number: Optional[str] = None,
) -> bytes:
    """Render a report by its slug. Looks for a slug-specific context builder
    in CONTEXT_BUILDERS; falls back to the explosive-quote builder, which
    covers the common quote variables (date, ref_no, contact, dims, price)
    so simple variants of the same template work without new code."""
    builder = CONTEXT_BUILDERS.get(slug, build_explosive_quote_context)
    ctx = builder(
        record_id=record_id,
        customer=customer,
        dimensions=dimensions,
        result=result,
        created_at=created_at,
        quote_number=quote_number,
    )
    return render_report(f"{slug}.html", ctx)


def render_explosive_quote(
    *,
    record_id: int,
    customer: Optional[Dict[str, Any]],
    dimensions: Dict[str, Any],
    result: Dict[str, Any],
    created_at: Optional[datetime] = None,
) -> bytes:
    ctx = build_explosive_quote_context(
        record_id=record_id,
        customer=customer,
        dimensions=dimensions,
        result=result,
        created_at=created_at,
    )
    return render_report("explosive_quote.html", ctx)


# Slug → context builder. Add new entries when a template needs different vars.
# FREEZER currently uses the same vars as EXPLOSIVE; swap to a dedicated
# builder when the FREEZER layout starts diverging.
CONTEXT_BUILDERS = {
    "explosive_quote":    build_explosive_quote_context,
    "freezer_quote":      build_explosive_quote_context,
    "rhinorange_quote":   build_explosive_quote_context,
    "meathanger_quote":   build_explosive_quote_context,
    "dry_freight_quote":  build_explosive_quote_context,
}
