"""WO v4.36c §3.4 — customer collection note PDF (reportlab — the house PDF path, mirrors prejob_pdf.py).

Generated ON DEMAND from the immutable qc_signoff (no stored bytes — §3.0 §3e). CUSTOMER-FACING (§0.8):
chassis + body identity, inspection date + inspector, ONE "Inspection passed" verdict line, and a
collection signature block. Deliberately EXCLUDES the per-category breakdown, defect notes, and the
inspector's role — defect detail is an internal QC concern, and the category taxonomy is admin-editable
(it must not leak into a customer document as an implied commitment).
"""
from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_styles = getSampleStyleSheet()
_S = {
    "title": ParagraphStyle("cc_title", parent=_styles["Heading2"], fontName="Helvetica-Bold",
                            fontSize=14, spaceAfter=2),
    "sub": ParagraphStyle("cc_sub", parent=_styles["Normal"], fontSize=9, spaceAfter=12,
                          textColor=colors.HexColor("#555555")),
    "label": ParagraphStyle("cc_label", parent=_styles["Normal"], fontSize=9,
                            textColor=colors.HexColor("#555555")),
    "value": ParagraphStyle("cc_value", parent=_styles["Normal"], fontSize=10, fontName="Helvetica-Bold"),
    "verdict": ParagraphStyle("cc_verdict", parent=_styles["Normal"], fontSize=11, fontName="Helvetica-Bold",
                              textColor=colors.HexColor("#16A34A"), spaceBefore=14, spaceAfter=10),
    "sign": ParagraphStyle("cc_sign", parent=_styles["Normal"], fontSize=9, spaceBefore=6, leading=22),
    "foot": ParagraphStyle("cc_foot", parent=_styles["Normal"], fontSize=7.5, spaceBefore=18,
                           textColor=colors.HexColor("#777777")),
}


def _esc(text) -> str:
    return (str(text) if text is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_date(d) -> str:
    try:
        return d.strftime("%d %b %Y") if d else "—"
    except Exception:
        return "—"


def render_collection_note(*, vin, customer_name, make, model, description,
                           inspection_date, inspector_name) -> bytes:
    """Return the collection-note PDF bytes. All args are plain values (no model coupling)."""
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20 * mm, bottomMargin=18 * mm,
                            leftMargin=20 * mm, rightMargin=20 * mm,
                            title=f"Collection Note {vin or ''}".strip())
    body_desc = " ".join(p for p in [make, model] if p) or "—"
    rows = [("Customer", customer_name or "—"), ("Chassis VIN", vin or "—"), ("Body", body_desc)]
    if description:
        rows.append(("Details", description))
    rows.append(("Inspection date", _fmt_date(inspection_date)))
    rows.append(("Inspected by", inspector_name or "—"))

    info = Table([[Paragraph(_esc(l), _S["label"]), Paragraph(_esc(v), _S["value"])] for l, v in rows],
                 colWidths=[42 * mm, 118 * mm])
    info.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))

    story = [
        Paragraph("Icecold Bodies — Customer Collection Note", _S["title"]),
        Paragraph("Quality inspection completed — vehicle body ready for collection.", _S["sub"]),
        info,
        Paragraph("&#10003; Inspection passed — released for customer collection.", _S["verdict"]),
        Spacer(1, 22 * mm),
        Paragraph("Collected by (customer): ____________________________________", _S["sign"]),
        Paragraph("Signature: ____________________________________     Date: ____________________", _S["sign"]),
        Paragraph("This note certifies the body passed Icecold Bodies' quality inspection on the date shown. "
                  "Detailed inspection records are retained internally by Icecold Bodies.", _S["foot"]),
    ]
    doc.build(story)
    return buf.getvalue()
