import json
from datetime import datetime, timezone, timedelta
from io import BytesIO

from fastapi import Request, APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db, CalculationRecord, TrailerType
from ..deps import get_current_user, user_can, active_branch, assert_calc_access
from ..services import resolve_report_template, strip_excluded_items

router = APIRouter()


@router.get("/results/{record_id}/export/excel")
async def export_excel(
    record_id: int,
    request: Request,
    db: Session = Depends(get_db),
    highlight: int = 0,
    branch=Depends(active_branch),
):
    """Export costing to Excel. highlight=1 → colour-code price changes."""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401)
    if not user_can(user, "export.excel", db):
        raise HTTPException(status_code=403, detail="Permission denied: export.excel")

    rec = db.query(CalculationRecord).filter_by(id=record_id).first()
    if not rec:
        raise HTTPException(status_code=404)
    assert_calc_access(rec.branch_id, user, branch)  # WO v4.37 §3.1 D-3

    dims = json.loads(rec.dimensions_json)
    result = json.loads(rec.result_json)
    result = strip_excluded_items(result)  # only selected items on exports
    tt = db.query(TrailerType).filter_by(id=rec.trailer_type_id).first()
    trailer_name = tt.name if tt else "Trailer"
    is_repair = bool(rec.is_repair)
    customer_name = rec.customer.name if rec.customer else ""

    override_materials: set = set()
    recently_updated_mats: set = set()
    if highlight:
        override_materials = set((result.get("overrides_by_name") or {}).keys())
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        for item in result.get("items", []):
            lu = item.get("last_updated")
            if lu and item["material"] not in override_materials:
                try:
                    lu_dt = datetime.fromisoformat(lu)
                    if lu_dt.tzinfo is None:
                        lu_dt = lu_dt.replace(tzinfo=timezone.utc)
                    if lu_dt >= cutoff:
                        recently_updated_mats.add(item["material"])
                except Exception:
                    pass

    import openpyxl
    import io
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Cost Breakdown"

    hdr_fill = PatternFill("solid", fgColor="1C2333")
    cat_fill = PatternFill("solid", fgColor="1F3A5F")
    total_fill = PatternFill("solid", fgColor="0D4A8A")
    grand_fill = PatternFill("solid", fgColor="388BFD")
    thin = Border(
        bottom=Side(style="thin", color="30363D"),
        right=Side(style="thin", color="30363D"),
    )

    def hdr(ws, row, col, text, bold=True, fill=None, align="left", num_fmt=None):
        cell = ws.cell(row=row, column=col, value=text)
        cell.font = Font(bold=bold, color="E6EDF3" if fill else "8B949E", name="Calibri")
        if fill:
            cell.fill = fill
        cell.alignment = Alignment(horizontal=align, vertical="center")
        cell.border = thin
        if num_fmt:
            cell.number_format = num_fmt
        return cell

    ws.merge_cells("A1:I1")
    t = ws["A1"]
    t.value = ("REPAIR QUOTE  —  TRAILER MANUFACTURING COST REPORT"
               if is_repair else "TRAILER MANUFACTURING COST REPORT")
    t.font = Font(bold=True, size=14, name="Calibri",
                  color="E02424" if is_repair else "58A6FF")
    t.fill = PatternFill("solid", fgColor="0D1117")
    t.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    ws.merge_cells("A2:I2")
    s = ws["A2"]
    s.value = f"{trailer_name}  |  Report #{record_id}  |  {rec.created_at.strftime('%d %B %Y')}"
    s.font = Font(size=11, color="8B949E", name="Calibri")
    s.fill = PatternFill("solid", fgColor="161B22")
    s.alignment = Alignment(horizontal="center")

    if customer_name:
        ws.merge_cells("A3:I3")
        c3 = ws["A3"]
        c3.value = f"Client:  {customer_name}"
        c3.font = Font(bold=True, size=11, color="0D1117", name="Calibri")
        c3.alignment = Alignment(horizontal="center")

    ws["A4"] = "DIMENSIONS"
    ws["A4"].font = Font(bold=True, color="388BFD", name="Calibri")
    dim_row1 = [
        ("Length (m)", dims.get("length")),
        ("Width (m)", dims.get("width")),
        ("Height (m)", dims.get("height")),
        ("Num Axles", dims.get("num_axles")),
    ]
    dim_row2 = [
        ("Num Doors", dims.get("num_doors")),
        ("Insulation Thickness (m)", dims.get("insulation_thickness")),
    ]
    for i, (lbl, val) in enumerate(dim_row1):
        ws.cell(row=5, column=i * 2 + 1, value=lbl).font = Font(color="444444", name="Calibri")
        ws.cell(row=5, column=i * 2 + 2, value=val).font = Font(bold=True, color="000000", name="Calibri")
    for i, (lbl, val) in enumerate(dim_row2):
        ws.cell(row=6, column=i * 2 + 1, value=lbl).font = Font(color="444444", name="Calibri")
        ws.cell(row=6, column=i * 2 + 2, value=val).font = Font(bold=True, color="000000", name="Calibri")

    row = 8
    cols = ["Category", "Material", "SAP Code", "Formula", "Quantity", "Unit", "Unit Price (R)", "Waste %", "Line Cost (R)"]
    for c, col in enumerate(cols, 1):
        cell = ws.cell(row=row, column=c, value=col)
        cell.font = Font(bold=True, color="E6EDF3", name="Calibri")
        cell.fill = hdr_fill
        cell.alignment = Alignment(horizontal="center" if c > 4 else "left", vertical="center")
        cell.border = thin
    ws.row_dimensions[row].height = 18
    row += 1

    # Categories belonging to is_optional BOM sections (e.g. OPTIONAL EXTRAS)
    # render in red — mirrors the on-screen results page and live calculator.
    optional_cats = {
        it["category"] for it in result.get("items", [])
        if it.get("section_is_optional")
    }
    current_cat = None
    # Track each section's header row + its detail-row span so we can add a
    # collapsible outline after all rows are written. Spans are derived
    # dynamically (item counts vary per report) — never hard-coded.
    sections: list[dict] = []
    current_section = None
    for item in result.get("items", []):
        cat = item["category"]
        if cat != current_cat:
            if current_section is not None:
                current_section["last"] = row - 1
                sections.append(current_section)
            ws.merge_cells(f"A{row}:H{row}")   # leave column I free for the section total
            _is_opt_cat = cat in optional_cats
            c = ws.cell(row=row, column=1, value=cat.upper())
            c.font = Font(bold=True,
                          color=("F85149" if _is_opt_cat else "58A6FF"),
                          name="Calibri")
            c.fill = cat_fill
            c.alignment = Alignment(horizontal="left", vertical="center")
            ws.row_dimensions[row].height = 16
            current_section = {"header": row, "first": row + 1, "last": None,
                               "kind": "body", "cat": cat, "optional": _is_opt_cat}
            row += 1
            current_cat = cat

        mat_name = item["material"]
        if highlight and mat_name in override_materials:
            price_colour = "CC0000"
            row_tint = "FFF5F5"
        elif highlight and mat_name in recently_updated_mats:
            price_colour = "1A6FBF"
            row_tint = "F0F6FF"
        else:
            price_colour = "000000"
            row_tint = None

        cells_data = [
            ("", "left"), (item["material"], "left"), (item["material_code"], "left"),
            (item["formula"], "left"),
            (item["quantity"], "right"), (item["unit"], "center"),
            (item["unit_price"], "right"), (item["waste_pct"], "right"),
            (item["line_cost"], "right"),
        ]
        for c, (val, align) in enumerate(cells_data, 1):
            cell = ws.cell(row=row, column=c, value=val)
            if c == 7:
                cell.font = Font(color=price_colour, name="Calibri", size=10,
                                 bold=(price_colour != "000000"))
            else:
                cell.font = Font(color="000000", name="Calibri", size=10)
            if row_tint and c != 7:
                cell.fill = PatternFill("solid", fgColor=row_tint)
            cell.alignment = Alignment(horizontal=align, vertical="center")
            cell.border = thin
            if c in (7, 9) and isinstance(val, (int, float)):
                cell.number_format = "#,##0.00"
            if c == 8 and isinstance(val, (int, float)) and val:
                cell.value = f"{val}%"
        ws.row_dimensions[row].height = 15
        row += 1

    if current_section is not None:
        current_section["last"] = row - 1
        sections.append(current_section)
        current_section = None

    chassis = result.get("chassis") or {}
    if chassis.get("items"):
        ws.merge_cells(f"A{row}:I{row}")
        c = ws.cell(
            row=row,
            column=1,
            value=(
                f"CHASSIS  ({chassis.get('axle_count')}-axle · "
                f"{chassis.get('tyre_style')} · "
                f"{chassis.get('tyre_count')} tyres · {chassis.get('length')} m)"
            ),
        )
        c.font = Font(bold=True, color="58A6FF", name="Calibri")
        c.fill = cat_fill
        c.alignment = Alignment(horizontal="left", vertical="center")
        ws.row_dimensions[row].height = 16
        ch_header = row
        row += 1
        ch_first = row
        for it in chassis["items"]:
            cells_data = [
                (it.get("kind", ""), "left"), (it.get("label", ""), "left"), ("", "left"),
                ("", "left"),
                (it.get("qty", 0), "right"), ("ea", "center"),
                (it.get("unit_price", 0), "right"), ("", "right"),
                (it.get("line_cost", 0), "right"),
            ]
            for cn, (val, align) in enumerate(cells_data, 1):
                cell = ws.cell(row=row, column=cn, value=val)
                cell.font = Font(color="000000", name="Calibri", size=10)
                cell.alignment = Alignment(horizontal=align, vertical="center")
                cell.border = thin
                if cn in (5, 7, 9) and isinstance(val, (int, float)):
                    cell.number_format = "#,##0.00"
            ws.row_dimensions[row].height = 15
            row += 1
        if row > ch_first:
            sections.append({"header": ch_header, "first": ch_first, "last": row - 1, "kind": "chassis"})
        ws.merge_cells(f"A{row}:H{row}")
        lc = ws.cell(row=row, column=1, value="CHASSIS SUBTOTAL")
        lc.font = Font(bold=True, color="C9D1D9", name="Calibri")
        lc.fill = total_fill
        lc.alignment = Alignment(horizontal="right", vertical="center")
        vc = ws.cell(row=row, column=9, value=chassis.get("subtotal", 0))
        vc.font = Font(bold=True, color="58A6FF", name="Calibri")
        vc.fill = total_fill
        vc.number_format = "#,##0.00"
        vc.alignment = Alignment(horizontal="right", vertical="center")
        ws.row_dimensions[row].height = 18
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="CATEGORY TOTALS").font = Font(bold=True, color="000000", name="Calibri")
    row += 1
    for cat, total in result.get("category_totals", {}).items():
        _opt = cat in optional_cats
        ws.cell(row=row, column=1, value=cat).font = Font(
            color=("F85149" if _opt else "444444"), name="Calibri",
            bold=_opt,
        )
        cell = ws.cell(row=row, column=9, value=total)
        cell.font = Font(bold=True, color=("F85149" if _opt else "000000"), name="Calibri")
        cell.number_format = "#,##0.00"
        cell.alignment = Alignment(horizontal="right")
        row += 1

    row += 1
    summary_rows = [("Cost per m²", result.get("cost_per_sqm", 0))]
    if chassis.get("items"):
        summary_rows.insert(0, ("Body Materials Subtotal", result.get("materials_total", 0)))
        summary_rows.insert(1, ("Chassis Subtotal", chassis.get("subtotal", 0)))
    summary_rows.append(("Total Manufacturing", result.get("grand_total", 0)))
    if result.get("profit_amount"):
        summary_rows.append(
            (f"Profit Margin ({result.get('profit_margin', 0)}%)", result.get("profit_amount", 0))
        )
    if result.get("ratio_amount"):
        summary_rows.append(
            (f"Ratio ({result.get('ratio_label') or ''})", result.get("ratio_amount", 0))
        )
    if result.get("selling_price"):
        summary_rows.append(("SELLING PRICE", result.get("selling_price", 0)))
    else:
        summary_rows.append(("TOTAL MANUFACTURING COST", result.get("grand_total", 0)))
    _disc_amt = float(result.get("discount_amount") or 0)
    if _disc_amt > 0:
        _dlabel = (f"Discount ({result.get('discount_input'):g}%)"
                   if result.get("discount_kind") == "percent" else "Discount")
        summary_rows.append((_dlabel, -_disc_amt))
        summary_rows.append(("NET TOTAL", float(result.get("net_total") or 0)))

    for label, val in summary_rows:
        is_grand = label in ("TOTAL MANUFACTURING COST", "SELLING PRICE", "NET TOTAL")
        ws.merge_cells(f"A{row}:H{row}")
        lc = ws.cell(row=row, column=1, value=label)
        lc.font = Font(
            bold=True,
            color="E6EDF3" if is_grand else "C9D1D9",
            size=12 if is_grand else 11,
            name="Calibri",
        )
        lc.fill = grand_fill if is_grand else total_fill
        lc.alignment = Alignment(horizontal="right", vertical="center")
        vc = ws.cell(row=row, column=9, value=val)
        vc.font = Font(
            bold=True,
            color="FFFFFF" if is_grand else "58A6FF",
            size=13 if is_grand else 11,
            name="Calibri",
        )
        vc.fill = grand_fill if is_grand else total_fill
        vc.number_format = "#,##0.00"
        vc.alignment = Alignment(horizontal="right", vertical="center")
        ws.row_dimensions[row].height = 22 if is_grand else 18
        row += 1

    widths = [14, 42, 18, 32, 12, 8, 14, 9, 14]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    if highlight and (override_materials or recently_updated_mats):
        wl = wb.create_sheet("Legend")
        wl.column_dimensions["A"].width = 18
        wl.column_dimensions["B"].width = 52
        wl.column_dimensions["C"].width = 22

        wl.merge_cells("A1:C1")
        lt = wl["A1"]
        lt.value = "PRICE HIGHLIGHT LEGEND"
        lt.font = Font(bold=True, size=13, color="58A6FF", name="Calibri")
        lt.fill = PatternFill("solid", fgColor="0D1117")
        lt.alignment = Alignment(horizontal="center", vertical="center")
        wl.row_dimensions[1].height = 24

        for col, (lbl, clr) in enumerate([("Sample Price", "58A6FF"), ("Meaning", "8B949E"), ("Applies to", "8B949E")], 1):
            hc = wl.cell(row=2, column=col, value=lbl)
            hc.font = Font(bold=True, color=clr, name="Calibri")
            hc.fill = PatternFill("solid", fgColor="1C2333")
            hc.border = thin
            hc.alignment = Alignment(horizontal="center")
        wl.row_dimensions[2].height = 16

        leg_data = []
        if recently_updated_mats:
            leg_data.append((
                "1A6FBF", "F0F6FF", "R 123.45",
                "Price permanently updated in the material database (within last 7 days)",
                ", ".join(sorted(recently_updated_mats)[:5]) +
                (f" + {len(recently_updated_mats)-5} more" if len(recently_updated_mats) > 5 else ""),
            ))
        if override_materials:
            leg_data.append((
                "CC0000", "FFF5F5", "R 99.00",
                "Quote-only price override — not saved to database, applies to this quote only",
                ", ".join(sorted(override_materials)[:5]) +
                (f" + {len(override_materials)-5} more" if len(override_materials) > 5 else ""),
            ))

        for i, (fc, bg, sample, meaning, mats) in enumerate(leg_data, 3):
            wl.cell(row=i, column=1, value=sample).font = Font(bold=True, color=fc, name="Calibri", size=11)
            wl.cell(row=i, column=1).fill = PatternFill("solid", fgColor=bg)
            wl.cell(row=i, column=1).border = thin
            wl.cell(row=i, column=1).alignment = Alignment(horizontal="center", vertical="center")
            wl.cell(row=i, column=2, value=meaning).font = Font(color="111111", name="Calibri", size=10)
            wl.cell(row=i, column=2).fill = PatternFill("solid", fgColor=bg)
            wl.cell(row=i, column=2).border = thin
            wl.cell(row=i, column=2).alignment = Alignment(wrap_text=True, vertical="center")
            wl.cell(row=i, column=3, value=mats).font = Font(color="555555", name="Calibri", size=9, italic=True)
            wl.cell(row=i, column=3).fill = PatternFill("solid", fgColor=bg)
            wl.cell(row=i, column=3).border = thin
            wl.cell(row=i, column=3).alignment = Alignment(wrap_text=True, vertical="center")
            wl.row_dimensions[i].height = 36

        ws["A2"].value = (ws["A2"].value or "") + "  |  ⬤ Highlighted: price changes colour-coded  →  see Legend tab"

    # ── Collapsible row grouping (outline) — opens EXPANDED ───────────────────
    # Each section's detail rows form an outline group under its always-visible
    # header (summaryBelow=False → the +/- sits beside the header). The sheet
    # opens fully expanded; the user collapses on demand. Headers, the CATEGORY
    # TOTALS block and the pricing rows are never grouped. Each body-section
    # header also carries =SUM of its Line Cost column (col I) so a collapsed
    # section still shows its total (SUM spans hidden rows, so it shows either way).
    if ws.sheet_properties.outlinePr is None:
        from openpyxl.worksheet.properties import Outline
        ws.sheet_properties.outlinePr = Outline()
    ws.sheet_properties.outlinePr.summaryBelow = False
    ws.sheet_properties.outlinePr.applyStyles = False
    ws.sheet_view.showOutlineSymbols = True
    for sec in sections:
        first, last, header = sec["first"], sec.get("last"), sec["header"]
        empty = last is None or last < first
        if not empty:
            for r in range(first, last + 1):
                ws.row_dimensions[r].outline_level = 1   # detail rows only; never hidden
        if sec.get("kind") == "body":
            tot = ws.cell(row=header, column=9,
                          value=(f"=SUM(I{first}:I{last})" if not empty else 0))
            tot.font = Font(bold=True,
                            color=("F85149" if sec.get("optional") else "58A6FF"),
                            name="Calibri")
            tot.fill = cat_fill
            tot.number_format = "#,##0.00"
            tot.alignment = Alignment(horizontal="right", vertical="center")
            tot.border = thin

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    username = rec.user.username if rec.user else "unknown"
    filename = f"Costing_{trailer_name.replace(' ', '_')}_{record_id}_{username}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/results/{record_id}/export/pdf")
async def export_pdf(record_id: int, request: Request, db: Session = Depends(get_db), branch=Depends(active_branch)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401)
    if not user_can(user, "export.pdf", db):
        raise HTTPException(status_code=403, detail="Permission denied: export.pdf")

    rec = db.query(CalculationRecord).filter_by(id=record_id).first()
    if not rec:
        raise HTTPException(status_code=404)
    assert_calc_access(rec.branch_id, user, branch)  # WO v4.37 §3.1 D-3

    dims = json.loads(rec.dimensions_json)
    result = json.loads(rec.result_json)
    result = strip_excluded_items(result)  # only selected items on exports
    tt = db.query(TrailerType).filter_by(id=rec.trailer_type_id).first()
    trailer_name = tt.name if tt else "Trailer"
    customer_info = None
    if rec.customer:
        customer_info = {
            "name": rec.customer.name or "",
            "email": rec.customer.email or "",
            "telephone": rec.customer.telephone or "",
        }

    try:
        from ..report_engine import _env
        try:
            from weasyprint import HTML
        except ImportError as e:
            raise RuntimeError("WeasyPrint is not installed.") from e

        # Categories belonging to is_optional BOM sections — flagged once so
        # the template can render their headers + totals in red, matching the
        # on-screen results page.
        _items = result.get("items", [])
        optional_cats = sorted({it["category"] for it in _items if it.get("section_is_optional")})

        ctx = {
            "trailer_name": trailer_name,
            "record_id": record_id,
            "created_at_human": rec.created_at.strftime("%d %B %Y") if rec.created_at else "",
            "generated_at": datetime.now().strftime("%d %b %Y %H:%M"),
            "customer_name": (customer_info or {}).get("name") or "",
            "is_repair": bool(rec.is_repair),
            "dims": dims,
            "items": _items,
            "category_totals": result.get("category_totals", {}) or {},
            "optional_cats": optional_cats,
            "cost_per_sqm": result.get("cost_per_sqm", 0),
            "profit_margin": result.get("profit_margin", 0),
            "profit_amount": result.get("profit_amount", 0),
            "ratio_value": result.get("ratio_value"),
            "ratio_label": result.get("ratio_label"),
            "ratio_amount": result.get("ratio_amount", 0),
            "selling_price": result.get("selling_price"),
            "grand_total": result.get("grand_total", 0),
            "chassis": result.get("chassis"),
            "materials_total": result.get("materials_total"),
            "discount_kind": result.get("discount_kind"),
            "discount_input": result.get("discount_input"),
            "discount_amount": result.get("discount_amount", 0),
            "net_total": result.get("net_total"),
        }

        html_str = _env.get_template("cost_breakdown.html").render(**ctx)
        pdf_bytes = HTML(string=html_str).write_pdf()

        username = user.username if user else "unknown"
        filename = f"Costing_{trailer_name.replace(' ', '_')}_{record_id}_{username}.pdf"

        return StreamingResponse(
            BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {exc}")


@router.get("/results/{record_id}/report")
async def report_for_record(record_id: int, request: Request, db: Session = Depends(get_db), branch=Depends(active_branch)):
    """Render the report PDF using the trailer's resolved ReportTemplate."""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401)
    if not user_can(user, "quote.generate", db):
        raise HTTPException(status_code=403, detail="Permission denied: quote.generate")

    rec = db.query(CalculationRecord).filter_by(id=record_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Costing record not found")
    assert_calc_access(rec.branch_id, user, branch)  # WO v4.37 §3.1 D-3

    tt = db.query(TrailerType).filter_by(id=rec.trailer_type_id).first()
    tmpl = resolve_report_template(tt)
    if not tmpl:
        raise HTTPException(status_code=400, detail="No report template is assigned to this trailer type.")

    dims = json.loads(rec.dimensions_json or "{}")
    result = json.loads(rec.result_json or "{}")
    result = strip_excluded_items(result)  # only selected items on the report
    customer = None
    if rec.customer:
        customer = {
            "name": rec.customer.name or "",
            "email": rec.customer.email or "",
            "telephone": rec.customer.telephone or "",
        }

    try:
        from ..report_engine import render_by_slug
        pdf_bytes = render_by_slug(
            slug=tmpl.slug,
            record_id=record_id,
            customer=customer,
            dimensions=dims,
            result=result,
            created_at=rec.created_at,
            quote_number=rec.quote_number,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Report generation failed: {e}")

    safe_customer = (
        "".join(ch for ch in (rec.customer.name if rec.customer else "Customer")
                if ch.isalnum() or ch in (" ", "_", "-"))
        .strip()
        .replace(" ", "_")
    ) or "Customer"
    safe_slug = tmpl.slug.replace("/", "_")
    filename = f"{safe_slug}_{record_id}_{safe_customer}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/results/{record_id}/report/explosive-quote")
async def report_explosive_quote_compat(record_id: int, request: Request, db: Session = Depends(get_db), branch=Depends(active_branch)):
    return await report_for_record(record_id=record_id, request=request, db=db, branch=branch)
