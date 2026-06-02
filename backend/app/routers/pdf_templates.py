import json
import os
from io import BytesIO
from datetime import datetime
from typing import Optional

from fastapi import Request, APIRouter, Depends, HTTPException, Query, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db, PDFTemplate, TrailerType
from ..deps import get_current_user
from ..templates_config import templates

router = APIRouter()


@router.get("/admin/pdf-template-builder", response_class=HTMLResponse)
async def admin_pdf_template_builder(
    request: Request,
    template_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse(url="/login")

    trailers = db.query(TrailerType).filter_by(is_active=True).order_by(TrailerType.name).all()
    trailer_list = [{"id": t.id, "name": t.name} for t in trailers]

    existing_template = None
    if template_id:
        tmpl = db.query(PDFTemplate).filter_by(id=template_id, is_active=True).first()
        if tmpl:
            config = json.loads(tmpl.template_data)
            existing_template = {
                "id": tmpl.id,
                "name": tmpl.name,
                "template": config,
                "trailer_type_ids": config.get("trailer_type_ids") or (
                    [tmpl.trailer_type_id] if tmpl.trailer_type_id else []
                ),
            }

    return templates.TemplateResponse("admin_pdf_template_builder.html", {
        "request": request,
        "user": user,
        "trailers": trailer_list,
        "existing_template": existing_template,
    })


@router.get("/admin/pdf-templates", response_class=HTMLResponse)
async def admin_pdf_templates(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse(url="/login")

    trailers = db.query(TrailerType).filter_by(is_active=True).order_by(TrailerType.name).all()
    trailer_list = [{"id": t.id, "name": t.name} for t in trailers]

    pdf_tmpls = db.query(PDFTemplate).filter_by(is_active=True).all()
    template_configs = {}
    for tmpl in pdf_tmpls:
        config = json.loads(tmpl.template_data)
        linked_trailer_ids = config.get("trailer_type_ids") or (
            [tmpl.trailer_type_id] if tmpl.trailer_type_id else []
        )
        linked_trailers = []
        if linked_trailer_ids:
            linked_trailers = [
                t.name
                for t in db.query(TrailerType)
                .filter(TrailerType.id.in_(linked_trailer_ids))
                .order_by(TrailerType.name)
                .all()
            ]
        template_configs[tmpl.name] = config
        template_configs[tmpl.name]["id"] = tmpl.id
        template_configs[tmpl.name]["trailer_type"] = tmpl.trailer_type.name if tmpl.trailer_type else None
        template_configs[tmpl.name]["linked_trailers"] = linked_trailers

    return templates.TemplateResponse("admin_pdf_templates.html", {
        "request": request,
        "user": user,
        "trailers": trailer_list,
        "template_configs": template_configs,
    })


@router.post("/api/pdf-templates/builder/save")
async def save_pdf_template_from_builder(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        form_data = await request.form()
        name = form_data.get("name", "").strip().upper()
        pdf_file = form_data.get("pdf_file")
        field_positions_str = form_data.get("field_positions", "{}")
        static_text_str = form_data.get("static_text", "[]")
        trailer_type_ids_str = form_data.get("trailer_type_ids", "[]")
        overwrite = str(form_data.get("overwrite", "false")).lower() == "true"
        template_id_raw = form_data.get("template_id")
        template_id = int(template_id_raw) if template_id_raw else None

        if not name:
            raise HTTPException(status_code=400, detail="Template name is required")

        try:
            field_positions = json.loads(field_positions_str)
            trailer_type_ids = json.loads(trailer_type_ids_str)
            static_text = json.loads(static_text_str)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON in field positions, static text, or trailer type IDs")
        if not isinstance(static_text, list):
            static_text = []

        if not isinstance(trailer_type_ids, list) or len(trailer_type_ids) == 0:
            raise HTTPException(status_code=400, detail="At least one trailer type must be selected")

        if (not isinstance(field_positions, dict) or not field_positions) and not static_text:
            raise HTTPException(status_code=400, detail="Add at least one field or static text overlay")

        target_template = None
        if template_id:
            target_template = db.query(PDFTemplate).filter_by(id=template_id).first()
            if not target_template:
                raise HTTPException(status_code=404, detail="Template to edit was not found")

        existing_name_template = db.query(PDFTemplate).filter_by(name=name).first()
        if existing_name_template and (not target_template or existing_name_template.id != target_template.id) and not overwrite:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": f"Template '{name}' already exists. Overwrite it?",
                    "existing_template_id": existing_name_template.id,
                },
            )

        if existing_name_template and (not target_template) and overwrite:
            target_template = existing_name_template

        pdf_dir = os.path.join(os.path.dirname(__file__), "..", "pdf_templates", "uploads")
        os.makedirs(pdf_dir, exist_ok=True)

        pdf_path = None
        if pdf_file and getattr(pdf_file, "filename", None):
            pdf_filename = f"{name.lower().replace(' ', '_')}_template.pdf"
            pdf_path = os.path.join(pdf_dir, pdf_filename)
            pdf_content = await pdf_file.read()
            with open(pdf_path, "wb") as f:
                f.write(pdf_content)
        elif target_template:
            current_config = json.loads(target_template.template_data)
            pdf_path = current_config.get("background_pdf")

        if not pdf_path:
            raise HTTPException(status_code=400, detail="PDF file is required for new templates")

        if not os.path.exists(pdf_path):
            raise HTTPException(status_code=400, detail="Configured PDF file could not be found")

        valid_trailer_ids = []
        for tid in trailer_type_ids:
            tt = db.query(TrailerType).filter_by(id=tid, is_active=True).first()
            if tt:
                valid_trailer_ids.append(tt.id)

        if not valid_trailer_ids:
            raise HTTPException(status_code=400, detail="No valid trailer types were linked")

        conflict_templates = []
        active_templates = db.query(PDFTemplate).filter_by(is_active=True).all()
        for candidate in active_templates:
            if target_template and candidate.id == target_template.id:
                continue
            candidate_config = json.loads(candidate.template_data)
            candidate_ids = candidate_config.get("trailer_type_ids") or (
                [candidate.trailer_type_id] if candidate.trailer_type_id else []
            )
            if set(candidate_ids) & set(valid_trailer_ids):
                conflict_templates.append(candidate)

        if conflict_templates and not overwrite:
            conflict_info = [f"{tpl.name} (id={tpl.id})" for tpl in conflict_templates]
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "One or more selected trailer types are already linked to another active template. Overwrite those links?",
                    "conflicts": conflict_info,
                },
            )

        if conflict_templates and overwrite:
            for candidate in conflict_templates:
                candidate.is_active = False

        template_data = {
            "template": "generated.html",
            "use_overlay": True,
            "background_pdf": pdf_path,
            "overlay_positions": field_positions,
            "static_text": static_text,
            "trailer_type_ids": valid_trailer_ids,
            "builder_created": True,
        }

        if target_template:
            target_template.name = name
            target_template.trailer_type_id = valid_trailer_ids[0]
            target_template.template_data = json.dumps(template_data)
            target_template.is_active = True
            pdf_template = target_template
        else:
            pdf_template = PDFTemplate(
                name=name,
                trailer_type_id=valid_trailer_ids[0],
                template_data=json.dumps(template_data),
                is_active=True,
            )
            db.add(pdf_template)

        db.commit()
        db.refresh(pdf_template)

        return {
            "status": "success",
            "template_id": pdf_template.id,
            "templates_created": [name],
            "message": f"Template saved for {len(valid_trailer_ids)} trailer type(s)",
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error saving template: {str(e)}")


@router.get("/api/pdf-templates")
async def get_pdf_templates(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or user.role != "admin":
        raise HTTPException(status_code=403)

    pdf_tmpls = db.query(PDFTemplate).filter_by(is_active=True).all()
    result = {}
    for tmpl in pdf_tmpls:
        result[tmpl.name] = json.loads(tmpl.template_data)
        result[tmpl.name]["id"] = tmpl.id
        result[tmpl.name]["trailer_type"] = tmpl.trailer_type.name if tmpl.trailer_type else None

    return {"templates": result}


@router.get("/api/pdf-templates/{template_id}/test")
async def test_pdf_template(template_id: int, request: Request, db: Session = Depends(get_db)):
    from datetime import timezone

    user = get_current_user(request, db)
    if not user or user.role != "admin":
        raise HTTPException(status_code=403)

    tmpl = db.query(PDFTemplate).filter_by(id=template_id, is_active=True).first()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")

    template_config = json.loads(tmpl.template_data)
    linked_trailer_ids = template_config.get("trailer_type_ids") or (
        [tmpl.trailer_type_id] if tmpl.trailer_type_id else []
    )
    sample_trailer = None
    if linked_trailer_ids:
        sample_trailer = (
            db.query(TrailerType)
            .filter(TrailerType.id.in_(linked_trailer_ids))
            .order_by(TrailerType.name)
            .first()
        )

    trailer_name = sample_trailer.name if sample_trailer else (
        tmpl.trailer_type.name if tmpl.trailer_type else tmpl.name
    )
    sample_dimensions = {
        "length": getattr(sample_trailer, "default_length", None) or 13.6,
        "width": getattr(sample_trailer, "default_width", None) or 2.6,
        "height": getattr(sample_trailer, "default_height", None) or 2.8,
        "num_axles": 3,
        "num_doors": 2,
        "insulation_thickness": 0.06,
    }
    sample_result = {
        "grand_total": 987654.32,
        "subtotal": 812345.67,
        "material_cost": 812345.67,
        "labor_cost": 75432.10,
        "overhead": 99876.55,
        "profit_margin": 12.5,
        "items": [],
        "category_totals": {},
        "customer_name": "Test Customer",
        "customer_email": "test.customer@example.com",
        "customer_telephone": "012 345 6789",
    }
    sample_customer = {
        "name": "Test Customer",
        "email": "test.customer@example.com",
        "telephone": "012 345 6789",
    }

    from ..pdf_generator import PDFGenerator

    generator = PDFGenerator(db_session=db)
    pdf_bytes = generator.generate_pdf_from_config(
        template_config.get("template", "default.html"),
        template_config,
        {
            "trailer_name": trailer_name,
            "record_id": 0,
            "dimensions": sample_dimensions,
            "result": sample_result,
            "customer": sample_customer,
            "created_at": datetime.now(timezone.utc),
            "user": user,
        },
    )

    filename = f"test_template_{template_id}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/api/pdf-templates/{template_id}/source-pdf")
async def get_pdf_template_source_pdf(template_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or user.role != "admin":
        raise HTTPException(status_code=403)

    tmpl = db.query(PDFTemplate).filter_by(id=template_id, is_active=True).first()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")

    config = json.loads(tmpl.template_data)
    pdf_path = config.get("background_pdf")
    if not pdf_path or not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="Template PDF file not found")

    with open(pdf_path, "rb") as f:
        data = f.read()

    filename = os.path.basename(pdf_path)
    return StreamingResponse(
        BytesIO(data),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/api/pdf-templates")
async def create_pdf_template(
    request: Request,
    name: str = Form(...),
    trailer_type_id: int = Form(...),
    template_file: str = Form(...),
    use_overlay: bool = Form(False),
    background_pdf: Optional[str] = Form(None),
    fields: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user or user.role != "admin":
        raise HTTPException(status_code=403)

    existing = db.query(PDFTemplate).filter_by(name=name).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Template with name '{name}' already exists")

    trailer_type = db.query(TrailerType).filter_by(id=trailer_type_id).first()
    if not trailer_type:
        raise HTTPException(status_code=400, detail="Invalid trailer type")

    for candidate in db.query(PDFTemplate).filter_by(is_active=True).all():
        candidate_config = json.loads(candidate.template_data)
        candidate_ids = candidate_config.get("trailer_type_ids") or (
            [candidate.trailer_type_id] if candidate.trailer_type_id else []
        )
        if trailer_type_id in candidate_ids:
            raise HTTPException(
                status_code=400,
                detail=f"Trailer type '{trailer_type.name}' is already linked to active template '{candidate.name}'",
            )

    from pathlib import Path as _Path

    template_path = _Path("templates/pdf_templates") / template_file
    if not template_path.exists():
        raise HTTPException(status_code=400, detail=f"Template file {template_file} does not exist")

    if background_pdf and not _Path(background_pdf).exists():
        raise HTTPException(status_code=400, detail=f"Background PDF file does not exist: {background_pdf}")

    field_data = json.loads(fields) if fields else {}

    template_data = {
        "template": template_file,
        "use_overlay": use_overlay,
        "background_pdf": background_pdf,
        "fields": field_data,
    }

    pdf_template = PDFTemplate(
        name=name,
        trailer_type_id=trailer_type_id,
        template_data=json.dumps(template_data),
    )
    db.add(pdf_template)
    db.commit()
    db.refresh(pdf_template)

    return {
        "success": True,
        "message": f"Template '{name}' created successfully",
        "template": {
            "id": pdf_template.id,
            "name": name,
            "trailer_type": trailer_type.name,
            "template": template_file,
            "use_overlay": use_overlay,
            "background_pdf": background_pdf,
            "fields": field_data,
        },
    }


@router.put("/api/pdf-templates/{template_id}")
async def update_pdf_template(
    template_id: int,
    request: Request,
    name: Optional[str] = Form(None),
    trailer_type_id: Optional[int] = Form(None),
    template_file: Optional[str] = Form(None),
    use_overlay: Optional[bool] = Form(None),
    background_pdf: Optional[str] = Form(None),
    fields: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user or user.role != "admin":
        raise HTTPException(status_code=403)

    tmpl = db.query(PDFTemplate).filter_by(id=template_id).first()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")

    if name and name != tmpl.name:
        existing = db.query(PDFTemplate).filter_by(name=name).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Template with name '{name}' already exists")

    if trailer_type_id:
        trailer_type = db.query(TrailerType).filter_by(id=trailer_type_id).first()
        if not trailer_type:
            raise HTTPException(status_code=400, detail="Invalid trailer type")

        for candidate in db.query(PDFTemplate).filter_by(is_active=True).all():
            if candidate.id == tmpl.id:
                continue
            candidate_config = json.loads(candidate.template_data)
            candidate_ids = candidate_config.get("trailer_type_ids") or (
                [candidate.trailer_type_id] if candidate.trailer_type_id else []
            )
            if trailer_type_id in candidate_ids:
                raise HTTPException(
                    status_code=400,
                    detail=f"Trailer type '{trailer_type.name}' is already linked to active template '{candidate.name}'",
                )

    from pathlib import Path as _Path

    if template_file:
        template_path = _Path("templates/pdf_templates") / template_file
        if not template_path.exists():
            raise HTTPException(status_code=400, detail=f"Template file {template_file} does not exist")

    if background_pdf and not _Path(background_pdf).exists():
        raise HTTPException(status_code=400, detail=f"Background PDF file does not exist: {background_pdf}")

    current_data = json.loads(tmpl.template_data)

    if name is not None:
        tmpl.name = name
    if trailer_type_id is not None:
        tmpl.trailer_type_id = trailer_type_id
    if template_file is not None:
        current_data["template"] = template_file
    if use_overlay is not None:
        current_data["use_overlay"] = use_overlay
    if background_pdf is not None:
        current_data["background_pdf"] = background_pdf
    if fields is not None:
        current_data["fields"] = json.loads(fields)

    tmpl.template_data = json.dumps(current_data)
    db.commit()

    return {
        "success": True,
        "message": f"Template '{tmpl.name}' updated successfully",
        "template": {
            "id": tmpl.id,
            "name": tmpl.name,
            "trailer_type": tmpl.trailer_type.name if tmpl.trailer_type else None,
            **current_data,
        },
    }


@router.delete("/api/pdf-templates/{template_id}")
async def delete_pdf_template(template_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or user.role != "admin":
        raise HTTPException(status_code=403)

    tmpl = db.query(PDFTemplate).filter_by(id=template_id).first()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")

    template_name = tmpl.name
    tmpl.is_active = False
    db.commit()

    return {"success": True, "message": f"Template '{template_name}' deleted successfully"}
