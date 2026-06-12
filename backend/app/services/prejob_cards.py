"""WO v4.33 §3.4/§3.5 — Pre-Job Card lifecycle service (the 3-role workflow, §0.3).

Internal Sales creates a DRAFT prefilled from costing + template + chassis; Submit-for-Check
(§0.8-gated on Body Gap populated-or-waived) flips it to sent_for_check AND drives the legacy
production_jobs pre_job_sent transition (§0.21 — prejob_cards is the source of truth; the
job's legacy signoff columns are NEVER written by this flow). Sign-off/reject land in §3.5.

Template suggestion (§0.6): active templates only, ranked body_type match > size match >
rhinorange_2_0 > rhinorange_legacy > standard, so "Rhinorange 2.0 first when both exist"
falls out of the ordering.
"""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import CalculationRecord, User
from app.models.mes import ChassisRecord, PrejobCard, PrejobTemplate, ProductionJob

_LINE_RANK = {"rhinorange_2_0": 0, "rhinorange_legacy": 1, "standard": 2}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _size_token(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"(\d{1,2}\.\d)\s*m", text.lower())
    return f"{m.group(1)}m" if m else None


def list_active_templates(db: Session, body_type: Optional[str] = None,
                          size_hint: Optional[str] = None) -> list[dict]:
    """Active templates, suggestion-ranked (§0.6). Returns dicts with a `suggested` flag on
    the single top match so the modal can pre-select it."""
    rows = db.execute(
        select(PrejobTemplate).where(PrejobTemplate.is_active.is_(True))
    ).scalars().all()

    def rank(t: PrejobTemplate):
        return (
            0 if (body_type and t.body_type == body_type) else 1,
            0 if (size_hint and t.size_category == size_hint) else 1,
            _LINE_RANK.get(t.product_line, 3),
            t.name,
        )

    rows.sort(key=rank)
    out = []
    for i, t in enumerate(rows):
        out.append({
            "id": t.id, "name": t.name, "body_type": t.body_type,
            "size_category": t.size_category, "product_line": t.product_line,
            "suggested": bool(rows) and i == 0 and body_type is not None
                         and t.body_type == body_type,
        })
    return out


def list_user_options(db: Session, kind: str) -> list[dict]:
    """Dropdown options. sales -> sales-role users; planner -> planner + admin (§0.3/Q4 —
    Burt backs Simeon up; production is deliberately excluded)."""
    roles = {"sales": ("sales",), "planner": ("planner", "admin")}.get(kind)
    if roles is None:
        raise HTTPException(status_code=422, detail="kind must be 'sales' or 'planner'")
    rows = db.execute(select(User).where(User.role.in_(roles))
                      .order_by(User.role, User.username)).scalars().all()
    return [{"id": u.id, "username": u.username, "role": u.role} for u in rows]


def _job_for_calc(db: Session, calculation_id: int) -> Optional[ProductionJob]:
    return db.execute(select(ProductionJob)
                      .where(ProductionJob.calculation_record_id == calculation_id)
                      ).scalar_one_or_none()


def _chassis_for_job(db: Session, job: Optional[ProductionJob]) -> Optional[ChassisRecord]:
    if job is None or not job.chassis_record_id:
        return None
    return db.get(ChassisRecord, job.chassis_record_id)


def get_for_calculation(db: Session, calculation_id: int) -> Optional[PrejobCard]:
    return db.execute(select(PrejobCard)
                      .where(PrejobCard.calculation_id == calculation_id)
                      .order_by(PrejobCard.id.desc())).scalars().first()


def create_card(db: Session, calculation_id: int, template_id: int, user) -> PrejobCard:
    """Stage A — Internal Sales drafts from a template (§3.4 step 1-2 prefill)."""
    calc = db.get(CalculationRecord, calculation_id)
    if calc is None:
        raise HTTPException(status_code=404, detail="calculation not found")
    if get_for_calculation(db, calculation_id) is not None:
        raise HTTPException(status_code=409,
                            detail="a Pre-Job Card already exists for this costing")
    tpl = db.get(PrejobTemplate, template_id)
    if tpl is None or not tpl.is_active:
        raise HTTPException(status_code=422, detail="template not found or not approved")

    job = _job_for_calc(db, calculation_id)
    chassis = _chassis_for_job(db, job)

    # body description: template header with the costing's body_type/size woven in when the
    # template carries placeholders; else the raw header line (editable in the modal anyway).
    dims = {}
    try:
        dims = json.loads(calc.dimensions_json or "{}") or {}
    except (ValueError, TypeError):
        dims = {}
    body_description = (tpl.header_format or tpl.name)

    chassis_make_model = None
    vin = None
    body_gap = None
    if chassis is not None:
        chassis_make_model = " ".join(x for x in (chassis.make, chassis.model) if x) or None
        vin = chassis.vin
        body_gap = chassis.body_gap_mm
    if not chassis_make_model:
        # planning-ack chassis_data (v4.29 D2) is the soft fallback
        try:
            cd = json.loads(job.chassis_data_json or "{}") if job else {}
            chassis_make_model = cd.get("chassis_model") or None
            vin = vin or cd.get("chassis_vin") or None
        except (ValueError, TypeError):
            pass

    card = PrejobCard(
        calculation_id=calculation_id,
        template_id=tpl.id,
        body_description=body_description,
        chassis_make_model=chassis_make_model,
        vin_number=vin,
        body_gap_mm=body_gap,
        body_gap_pending=body_gap is None,
        sections=copy.deepcopy(tpl.sections),
        fridge_ordering_mode=None,
        customer_notes=None,
        created_by_user_id=getattr(user, "id", None),
        # §0.13 — quote-time capture defaults the dropdown; calc owner is the soft fallback.
        sales_rep_user_id=calc.sales_rep_user_id or calc.user_id,
        status="draft",
    )
    # Scope addition — bake the CORE tokens at creation ("substitutions become invisible at
    # modal-open"): dims from the costing, vin/chassis, customer. Fridge tokens stay visible
    # until the dropdown selects a unit (the modal live-substitutes them with the same
    # semantics). Unknown tokens stay as-is by design.
    from app.services.template_variables import build_context, substitute_sections, substitute_text
    ctx = build_context(db, card, calc=calc, chassis=chassis)
    ctx.pop("fridge_make", None)                       # not known at creation — keep visible
    card.sections = substitute_sections(card.sections, ctx)
    card.body_description = substitute_text(card.body_description, ctx) or card.body_description
    db.add(card)
    db.commit()
    db.refresh(card)
    return card


_DRAFT_EDITABLE = {
    "body_description", "chassis_make_model", "vin_number", "body_gap_mm",
    "sections", "fridge_ordering_mode", "fridge_model", "customer_notes",
    "sales_rep_user_id", "planner_user_id", "template_id", "cc_recipients",
}


def update_card(db: Session, card_id: int, data: dict, user) -> PrejobCard:
    card = db.get(PrejobCard, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="pre-job card not found")
    if card.status != "draft":
        raise HTTPException(status_code=409,
                            detail=f"card is '{card.status}' — only drafts are editable")
    unknown = set(data) - _DRAFT_EDITABLE
    if unknown:
        raise HTTPException(status_code=422, detail=f"not editable: {', '.join(sorted(unknown))}")
    if "template_id" in data and data["template_id"] is not None:
        tpl = db.get(PrejobTemplate, data["template_id"])
        if tpl is None or not tpl.is_active:
            raise HTTPException(status_code=422, detail="template not found or not approved")
        # switching template re-seeds the sections from it (the modal confirms first)
        card.sections = copy.deepcopy(tpl.sections)
        card.body_description = tpl.header_format or tpl.name
    for k, v in data.items():
        if k != "template_id":
            setattr(card, k, v)
    if "body_gap_mm" in data:
        card.body_gap_pending = data["body_gap_mm"] is None
    card.version = (card.version or 1) + 1
    db.commit()
    db.refresh(card)
    return card


def submit_for_check(db: Session, card_id: int, user, waive_body_gap: bool = False) -> PrejobCard:
    """Stage A→B/C — §0.8 gate + §0.21 legacy status drive."""
    card = db.get(PrejobCard, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="pre-job card not found")
    if card.status != "draft":
        raise HTTPException(status_code=409, detail=f"card is already '{card.status}'")
    if card.sales_rep_user_id is None:
        raise HTTPException(status_code=422, detail="select a Sales Rep before submitting")
    if card.planner_user_id is None:
        raise HTTPException(status_code=422, detail="select a Planner before submitting")
    if card.body_gap_mm is None and not waive_body_gap:
        raise HTTPException(
            status_code=422,
            detail="Body Gap is pending (awaiting chassis VCL) — enter it or explicitly "
                   "waive to submit (§0.8)")
    card.status = "sent_for_check"
    card.sent_for_check_at = _now()
    card.reject_reason = None                          # §0.14 — re-submit clears the old reason

    # §3.6 — records-copy PDF snapshot (§0.11: the email attachment source). Rendered by the
    # SAME function the Preview button uses; failure here must never block the submit.
    try:
        card.pdf_file_id = _snapshot_pdf(db, card)
    except Exception:                                  # noqa: BLE001 — snapshot is best-effort
        card.pdf_file_id = None

    # §0.21 — drive the legacy production_jobs transition so Planning gating keeps working.
    job = _job_for_calc(db, card.calculation_id)
    if job is not None and job.status in ("accepted",):
        from app.services import production_jobs as pj
        try:
            pj.send_pre_job_card(db, job.id, user)     # sets pre_job_sent_at + status
        except Exception:                              # repair quotes 422 etc. — card still flips
            db.rollback()
            card = db.get(PrejobCard, card_id)
            card.status = "sent_for_check"
            card.sent_for_check_at = _now()
            card.reject_reason = None
    db.commit()
    db.refresh(card)
    return card


# ── §3.6 — PDF + email content (the §0.11 transitional mailto pattern) ───────
def _display_bits(db: Session, card: PrejobCard) -> dict:
    calc = db.get(CalculationRecord, card.calculation_id)
    quote = calc.quote_number if calc else None
    customer = None
    if calc is not None and calc.customer_id:
        from app.database import Customer
        cust = db.get(Customer, calc.customer_id)
        customer = cust.name if cust else None
    def uname(uid):
        u = db.get(User, uid) if uid else None
        return u.username if u else None
    return {"quote": quote, "customer": customer,
            "sales_rep": uname(card.sales_rep_user_id),
            "planner": uname(card.planner_user_id)}


def render_pdf(db: Session, card: PrejobCard) -> bytes:
    from app.models.mes import FridgeUnit
    from app.services.prejob_pdf import render_prejob_pdf
    from app.services.template_variables import build_context, substitute_sections
    bits = _display_bits(db, card)
    # Defensive substitution sweep: resolve any tokens still present (fridge picked after
    # creation, late VIN, etc.) so the PDF never ships a {{token}} that HAS a known value.
    fridge = None
    if card.fridge_model:
        fridge = db.execute(select(FridgeUnit)
                            .where(FridgeUnit.display_name == card.fridge_model)
                            ).scalars().first()
    job = _job_for_calc(db, card.calculation_id)
    ctx = build_context(db, card, calc=db.get(CalculationRecord, card.calculation_id),
                        chassis=_chassis_for_job(db, job), fridge=fridge)
    rendering = copy.copy(card)
    rendering.sections = substitute_sections(card.sections, ctx)
    return render_prejob_pdf(rendering, quote_number=bits["quote"],
                             customer_name=bits["customer"],
                             sales_rep=bits["sales_rep"], planner=bits["planner"])


def _snapshot_pdf(db: Session, card: PrejobCard) -> str:
    from app.services.file_store import save_prejob_pdf
    return save_prejob_pdf(card.id, render_pdf(db, card))


def build_email(db: Session, card: PrejobCard, base_url: str) -> dict:
    """§0.11 — subject + body with click-to-signoff links + a mailto: URL. The mailto carries
    NO attachment (the protocol cannot, reliably — BA-corrected §0.11): the user attaches the
    downloaded PDF manually. Recipients are blank — users carry no email column yet (v4.34
    notification config captures addresses); Nadie addresses it in her mail client."""
    from urllib.parse import quote as q
    base = base_url.rstrip("/")
    bits = _display_bits(db, card)
    subject = f"Pre-Job Card for check — {bits['quote'] or f'card {card.id}'} — {bits['customer'] or ''}".strip(" —")
    sales_link = f"{base}/mes-app/prejob/{card.id}/signoff/sales"
    planner_link = f"{base}/mes-app/prejob/{card.id}/signoff/planner"
    body = (
        f"Hi,\r\n\r\n"
        f"The Pre-Job Card for costing {bits['quote'] or card.id} ({bits['customer'] or '—'}) "
        f"is ready for check.\r\n\r\n"
        f"Sales Rep ({bits['sales_rep'] or 'unassigned'}) — review and sign off here:\r\n"
        f"{sales_link}\r\n\r\n"
        f"Planner ({bits['planner'] or 'unassigned'}) — review and sign off here:\r\n"
        f"{planner_link}\r\n\r\n"
        f"The PDF copy is attached for records (download it from the MES if missing).\r\n\r\n"
        f"Sent from ICB MES (internal document — not for the customer).\r\n"
    )
    # CC addition — store raw, but only email-shaped entries feed the &cc= param.
    cc_clean = ",".join(
        a.strip() for a in (card.cc_recipients or "").split(",")
        if "@" in a and "." in a.split("@")[-1])
    cc_part = f"cc={q(cc_clean)}&" if cc_clean else ""
    return {"subject": subject, "body": body,
            "sales_link": sales_link, "planner_link": planner_link,
            "cc": cc_clean or None,
            "mailto": f"mailto:?{cc_part}subject={q(subject)}&body={q(body)}"}


# ── §3.5 — check sign-offs + reject (Stages B/C/D) ───────────────────────────
def sign_off(db: Session, card_id: int, role: str, attestation: str, user) -> PrejobCard:
    """§0.12 in-system digital sign-off. The {role}_user_id is overwritten with the ACTUAL
    signer (audit honesty — Burt signing as planner backup must show Burt, not Simeon). Both
    sign-offs present → status auto-flips to pre_job_confirmed AND drives the legacy
    production_jobs status/pre_job_confirmed_at (§0.21 — the job's signoff columns are NEVER
    written; pre_job_confirmed_at is a status timestamp, BA-sanctioned)."""
    if role not in ("sales", "planner"):
        raise HTTPException(status_code=422, detail="role must be 'sales' or 'planner'")
    if not (attestation or "").strip():
        raise HTTPException(status_code=422, detail="attestation text is required")
    card = db.get(PrejobCard, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="pre-job card not found")
    if card.status != "sent_for_check":
        raise HTTPException(status_code=409,
                            detail=f"card is '{card.status}' — sign-off needs sent_for_check")
    now = _now()
    if role == "sales":
        if card.sales_rep_signoff_at is not None:
            raise HTTPException(status_code=409, detail="Sales Rep has already signed off")
        card.sales_rep_user_id = getattr(user, "id", card.sales_rep_user_id)
        card.sales_rep_signoff_at = now
        card.sales_rep_attestation = attestation.strip()
    else:
        if card.planner_signoff_at is not None:
            raise HTTPException(status_code=409, detail="Planner has already signed off")
        card.planner_user_id = getattr(user, "id", card.planner_user_id)
        card.planner_signoff_at = now
        card.planner_attestation = attestation.strip()

    if card.sales_rep_signoff_at is not None and card.planner_signoff_at is not None:
        card.status = "pre_job_confirmed"              # Stage D — auto on the second sign-off
        job = _job_for_calc(db, card.calculation_id)
        if job is not None and job.status in ("accepted", "pre_job_sent"):
            job.status = "pre_job_confirmed"
            if job.pre_job_confirmed_at is None:
                job.pre_job_confirmed_at = now
    db.commit()
    db.refresh(card)
    return card


def reject(db: Session, card_id: int, role: str, reason: str, user) -> PrejobCard:
    """§0.14 — either checker can reject; status returns to draft with the reason captured
    (prefixed with who rejected). Existing sign-offs reset — the re-submitted card is
    re-checked by BOTH roles. The production job stays pre_job_sent (Planning still gates on
    pre_job_confirmed, so nothing downstream unlocks)."""
    if role not in ("sales", "planner"):
        raise HTTPException(status_code=422, detail="role must be 'sales' or 'planner'")
    if not (reason or "").strip():
        raise HTTPException(status_code=422, detail="a reject reason is required")
    card = db.get(PrejobCard, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="pre-job card not found")
    if card.status != "sent_for_check":
        raise HTTPException(status_code=409,
                            detail=f"card is '{card.status}' — reject needs sent_for_check")
    who = getattr(user, "username", "unknown")
    card.status = "draft"
    card.reject_reason = f"[{role} check — {who}] {reason.strip()}"
    card.sales_rep_signoff_at = None
    card.sales_rep_attestation = None
    card.planner_signoff_at = None
    card.planner_attestation = None
    card.sent_for_check_at = None
    db.commit()
    db.refresh(card)
    return card
