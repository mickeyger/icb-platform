"""WO v4.34.4 §3.3 — service-layer state-machine invariants for the Pre-Job → Job → Chassis pipeline.

Three invariants, codifying the failure modes that produced the bad states we cleaned up in the
14–15 June session (orphaned confirmed cards, calc.status strays, anchorless 'expected' chassis):

  Invariant 1 — a CONFIRMED Pre-Job Card always anchors a production_job.
      `assert_confirmed_card_anchored` is a hard, transaction-rolling assertion wired into sign_off
      (after _ensure_anchor_job). A confirmed card with no job is invisible to Planning's ack pool
      (it needs production_job_id != null), so we fail the confirm LOUDLY rather than ship that state.

  Invariant 2 — calculations.status reflects what the lifecycle backs.
      A calc may sit at pre_job_sent / pre_job_confirmed (or beyond) ONLY while a Pre-Job Card or
      production_job in a matching-or-later state backs it. `derive_calc_status` is the single
      source-of-truth mapping; `reconcile_calc_status` advances forward (and, with allow_revert=True,
      walks a stray BACK down to what's actually backed — never below 'accepted', never 'declined').
      The forward path matches the flow setter (prejob_cards._sync_calc_status); the revert is the
      new capability (the real card-delete endpoint is deferred — ADR 0020 — so revert is exercised
      by the reconciler + tests, ready for when a delete path exists).

  Invariant 3 — no 'expected' chassis lingers anchorless and unseen.
      `find_anchorless_chassis` is a READ-ONLY detector for expected / expected_orphaned chassis with
      no live job or card link. This is a DETECT/RECONCILE health-check, NOT a creation block — the
      chassis_record_id FK stays ON DELETE RESTRICT (mig 0012) and creation is never gated.
      `reconcile_anchorless_chassis` only ever marks 'expected' → 'expected_orphaned' (forward,
      reversible); it NEVER deletes (recovery stays manual / BA-gated / snapshot-reversible).

`run_health_checks` aggregates all three as a read-only report — safe to run against ANY database
(it issues only SELECTs), which is what backend/scripts/health_check.py exposes for dev monitoring.

Self-contained (own query helpers) to avoid an import cycle with services.prejob_cards.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import CalculationRecord
from app.models.mes import ChassisRecord, PrejobCard, ProductionJob

# Pipeline lifecycle ordering (shared with scripts/backfill_prejob_calc_status). Forward = higher.
_RANK = {"pending": -1, "accepted": 0, "pre_job_sent": 1, "pre_job_confirmed": 2,
         "planning": 3, "in_production": 4, "completed": 5, "dispatched": 6}

# A Pre-Job Card's status → the lifecycle status it implies for its calc/job.
_CARD_TO_STATUS = {"sent_for_check": "pre_job_sent", "pre_job_confirmed": "pre_job_confirmed"}


def _rank(s: Optional[str]) -> int:
    return _RANK.get(s, -2)


def _job_for_calc(db: Session, calc_id: int) -> Optional[ProductionJob]:
    return db.execute(
        select(ProductionJob).where(ProductionJob.calculation_record_id == calc_id)
    ).scalars().first()


def _card_for_calc(db: Session, calc_id: int) -> Optional[PrejobCard]:
    return db.execute(
        select(PrejobCard).where(PrejobCard.calculation_id == calc_id)
        .order_by(PrejobCard.id.desc())
    ).scalars().first()


# ── Invariant 1 — a confirmed card always anchors a job ──────────────────────────
def assert_confirmed_card_anchored(db: Session, calc_id: int) -> None:
    """Raise (rolling back the caller's txn) if the calc's Pre-Job Card is pre_job_confirmed but no
    production_job backs it. Called from sign_off AFTER _ensure_anchor_job, so this only fires in the
    pathological case where the anchor could not be created (e.g. no branch resolvable) — turning a
    silent Planning-invisible confirm into a clean, atomic failure."""
    db.flush()   # SessionLocal is autoflush=False — flush so a just-added (pending) anchor job is visible
    card = _card_for_calc(db, calc_id)
    if card is None or card.status != "pre_job_confirmed":
        return
    if _job_for_calc(db, calc_id) is None:
        raise HTTPException(
            status_code=500,
            detail=(f"integrity invariant 1 violated: calc {calc_id} has a confirmed Pre-Job Card but "
                    f"no production job to anchor it (it would be invisible to Planning). No branch "
                    f"could be resolved to create the anchor job."))


# ── Invariant 2 — calc.status is backed by the lifecycle ─────────────────────────
def derive_calc_status(db: Session, calc_id: int) -> Optional[str]:
    """The status the calc SHOULD hold, given its backing Pre-Job Card + production job: the most
    advanced of the job's status and the card-implied status. None when nothing backs a pipeline
    status (caller treats that as the 'accepted' baseline)."""
    job = _job_for_calc(db, calc_id)
    card = _card_for_calc(db, calc_id)
    candidates: list[str] = []
    if job is not None and job.status:
        candidates.append(job.status)
    if card is not None:
        implied = _CARD_TO_STATUS.get(card.status)
        if implied:
            candidates.append(implied)
    if not candidates:
        return None
    return max(candidates, key=_rank)


def check_calc_status_backed(db: Session, calc_id: int) -> Optional[str]:
    """Return a human-readable violation message if calc.status claims a pipeline stage that no card/
    job backs, else None. Never flags 'declined' or anything at/below 'accepted' (nothing to back)."""
    calc = db.get(CalculationRecord, calc_id)
    if calc is None or calc.status == "declined" or _rank(calc.status) <= _RANK["accepted"]:
        return None
    derived = derive_calc_status(db, calc_id)
    if derived is None or _rank(derived) < _rank(calc.status):
        return (f"calc {calc_id} ({calc.quote_number}) status='{calc.status}' but the lifecycle backs "
                f"at most '{derived or 'accepted'}'")
    return None


def reconcile_calc_status(db: Session, calc_id: int, *, allow_revert: bool = False) -> Optional[str]:
    """Bring calc.status into line with the lifecycle. Forward-only by default (advance to the derived
    status). With allow_revert=True, ALSO walk a stray back DOWN to the derived status — never below
    'accepted', never touching 'declined'. Returns the new status if changed, else None. Runs in the
    caller's transaction (no commit)."""
    calc = db.get(CalculationRecord, calc_id)
    if calc is None or calc.status == "declined":
        return None
    derived = derive_calc_status(db, calc_id) or "accepted"
    if _rank(derived) < _RANK["accepted"]:
        derived = "accepted"                                   # revert floor — never below accepted
    advancing = _rank(derived) > _rank(calc.status)
    reverting = allow_revert and _rank(derived) < _rank(calc.status) and _rank(calc.status) > _RANK["accepted"]
    if (advancing or reverting) and derived != calc.status:
        calc.status = derived
        return derived
    return None


# ── Invariant 3 — no anchorless 'expected' chassis ───────────────────────────────
def find_anchorless_chassis(db: Session, *, statuses=("expected", "expected_orphaned")) -> list[dict]:
    """READ-ONLY. LIVE chassis (deleted_at IS NULL) with NO live link — no production_job and no
    prejob_card references them. Default scope = the 'expected'/'expected_orphaned' pipeline rows
    (Inv3 health-check / reconcile). Pass statuses=None for the WIDE §3.6 admin Find-Orphan view (ANY
    status — catches MICKEYTEST-class 'received' orphans the narrow scope misses). NOT a creation block."""
    stmt = select(ChassisRecord).where(ChassisRecord.deleted_at.is_(None))   # §3.6 STEP 1 — merged losers aren't orphans
    if statuses is not None:
        stmt = stmt.where(ChassisRecord.status.in_(statuses))
    rows = db.execute(stmt).scalars().all()
    out: list[dict] = []
    for ch in rows:
        has_job = db.execute(
            select(ProductionJob.id).where(ProductionJob.chassis_record_id == ch.id)).first()
        has_card = db.execute(
            select(PrejobCard.id).where(PrejobCard.chassis_record_id == ch.id)).first()
        if has_job is None and has_card is None:
            out.append({"id": ch.id, "vin": ch.vin, "make": ch.make, "status": ch.status,
                        "customer_name": ch.customer_name, "created_via": ch.created_via,
                        "created_source_ref": ch.created_source_ref})
    return out


def reconcile_anchorless_chassis(db: Session, *, apply: bool = False) -> dict:
    """Mark anchorless 'expected' chassis as 'expected_orphaned' (forward, reversible). NEVER deletes —
    the RESTRICT FK and manual/BA-gated recovery posture are preserved. apply=False = dry report.
    Runs in the caller's transaction (no commit)."""
    anchorless = find_anchorless_chassis(db)
    marked: list[int] = []
    if apply:
        for row in anchorless:
            if row["status"] == "expected":
                db.get(ChassisRecord, row["id"]).status = "expected_orphaned"
                marked.append(row["id"])
    return {"anchorless": [r["id"] for r in anchorless],
            "marked_orphaned": marked if apply else []}


# ── Aggregate read-only health-check ─────────────────────────────────────────────
def run_health_checks(db: Session) -> dict:
    """READ-ONLY aggregate of all three invariants (SELECTs only — safe on the shared dev DB).
    Returns the list of violations per invariant; empty lists ⇒ the pipeline is consistent."""
    confirmed_cards = db.execute(
        select(PrejobCard).where(PrejobCard.status == "pre_job_confirmed")).scalars().all()
    inv1 = [c.calculation_id for c in confirmed_cards if _job_for_calc(db, c.calculation_id) is None]

    inv2 = []
    for calc in db.execute(select(CalculationRecord)).scalars().all():
        msg = check_calc_status_backed(db, calc.id)
        if msg:
            inv2.append({"calc_id": calc.id, "status": calc.status, "detail": msg})

    inv3 = find_anchorless_chassis(db)

    return {
        "invariant_1_confirmed_cards_without_job": inv1,
        "invariant_2_calc_status_strays": inv2,
        "invariant_3_anchorless_chassis": inv3,
        "clean": not (inv1 or inv2 or inv3),
    }
