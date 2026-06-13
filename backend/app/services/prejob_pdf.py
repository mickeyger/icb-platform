"""WO v4.33 §3.6 — Pre-Job Card PDF renderer (reportlab — the house PDF path; no weasyprint).

ONE renderer, two consumers (BA-locked): the modal's "Preview PDF" button and the
Submit-for-Check records snapshot / email "Download PDF" helper — both call render_prejob_pdf
so preview and attachment can never diverge. Layout mirrors Nadie's Word originals: header
line, numbered sections (notes italic, sub-items bulleted), fridge + customer notes, the
two-check sign-off block.
"""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_styles = getSampleStyleSheet()
_S = {
    "title": ParagraphStyle("pj_title", parent=_styles["Heading2"], fontName="Helvetica-Bold",
                            fontSize=12, spaceAfter=2),
    "meta": ParagraphStyle("pj_meta", parent=_styles["Normal"], fontSize=8.5,
                           textColor=colors.HexColor("#555555"), spaceAfter=6),
    "section": ParagraphStyle("pj_section", parent=_styles["Heading4"],
                              fontName="Helvetica-Bold", fontSize=10, spaceBefore=8,
                              spaceAfter=3),
    "item": ParagraphStyle("pj_item", parent=_styles["Normal"], fontSize=9, leftIndent=14,
                           firstLineIndent=-14, spaceAfter=1.5, leading=12),
    "note": ParagraphStyle("pj_note", parent=_styles["Normal"], fontSize=8,
                           fontName="Helvetica-Oblique", leftIndent=18, spaceAfter=1.5,
                           textColor=colors.HexColor("#444444")),
    "sub": ParagraphStyle("pj_sub", parent=_styles["Normal"], fontSize=8.5, leftIndent=26,
                          firstLineIndent=-8, spaceAfter=1, leading=11),
    "foot": ParagraphStyle("pj_foot", parent=_styles["Normal"], fontSize=7.5,
                           textColor=colors.HexColor("#777777"), spaceBefore=10),
}


def _esc(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_prejob_pdf(card, *, quote_number: str | None, customer_name: str | None,
                      sales_rep: str | None, planner: str | None) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=16 * mm, bottomMargin=14 * mm,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            title=f"Pre-Job Card {quote_number or card.id}")
    story = []
    story.append(Paragraph(_esc(card.body_description or "Pre-Job Card"), _S["title"]))
    gap = (f"{card.body_gap_mm}mm" if card.body_gap_mm is not None
           else "PENDING — awaiting chassis VCL")
    story.append(Paragraph(
        _esc(f"Costing {quote_number or '—'} · {customer_name or '—'} · "
             f"Chassis: {card.chassis_make_model or '—'} · VIN: {card.vin_number or 'TBD'} · "
             f"Body gap: {gap}"), _S["meta"]))

    for section in (card.sections or []):
        story.append(Paragraph(_esc(section.get("name", "")), _S["section"]))
        for i, item in enumerate(section.get("items", []), start=1):
            story.append(Paragraph(f"{i}&nbsp;&nbsp;{_esc(item.get('text', ''))}", _S["item"]))
            if item.get("note"):
                story.append(Paragraph(f"Note: {_esc(item['note'])}", _S["note"]))
            for sub in (item.get("sub_items") or []):
                story.append(Paragraph(f"•&nbsp;{_esc(sub)}", _S["sub"]))

    fridge = {"icb_orders": f"ICB orders — {card.fridge_model or 'model TBC'}",
              "customer_supplies": "Customer supplies own unit",
              "none": "No fridge unit (cut-out provision only)"}.get(
        card.fridge_ordering_mode or "", "—")
    story.append(Paragraph("FRIDGE", _S["section"]))
    story.append(Paragraph(_esc(fridge), _S["item"]))
    if card.customer_notes:
        story.append(Paragraph("CUSTOMER NOTES", _S["section"]))
        story.append(Paragraph(_esc(card.customer_notes), _S["item"]))

    def _check(label: str, who: str | None, at) -> list[str]:
        if at:
            stamp = at.strftime("%d %b %Y %H:%M") if hasattr(at, "strftime") else str(at)
            return [label, f"SIGNED — {who or '—'}", stamp]
        return [label, f"awaiting sign-off ({who or 'unassigned'})", ""]

    story.append(Spacer(1, 6 * mm))
    tbl = Table([_check("Sales Rep check", sales_rep, card.sales_rep_signoff_at),
                 _check("Planner check", planner, card.planner_signoff_at)],
                colWidths=[45 * mm, 85 * mm, 40 * mm])
    tbl.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(tbl)
    story.append(Paragraph(
        f"Generated by ICB MES (WO v4.33) · internal sign-off document — the customer never "
        f"receives the Pre-Job Card (§0.2) · status: {card.status} · "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", _S["foot"]))
    doc.build(story)
    return buf.getvalue()
