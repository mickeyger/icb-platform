"""WO v4.36a §3.6 — admin chassis merge / restore service.

Merge = re-point every FK that references the LOSER chassis to the WINNER, then SOFT-DELETE the loser
(deleted_at + merged_into_id), NEVER hard-delete (the production_jobs FK is ON DELETE RESTRICT; lifecycle
events are CASCADE — a hard delete would be blocked / would destroy history). Lifecycle-event collisions on
uq_chassis_events_record_cycle_type (chassis_record_id, cycle_number, event_type) are resolved by
renumbering the loser's cycles ABOVE the winner's max (history preserved, photos ride the event FK).

STEP 5 ships preview_merge (read-only dry-run). merge_chassis (STEP 6) + restore_chassis (STEP 7) land next.
"""
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.mes import ChassisLifecycleEvent, ChassisRecord, PrejobCard, ProductionJob
from app.services import chassis_integrity as ci

_LARGE_EVENT_DELTA = 4


def _event_count(db: Session, chassis_id: int) -> int:
    return db.execute(select(func.count(ChassisLifecycleEvent.id))
                      .where(ChassisLifecycleEvent.chassis_record_id == chassis_id)).scalar() or 0


def _summary(chassis: ChassisRecord, event_count: int) -> dict:
    return {"id": chassis.id, "vin": chassis.vin, "make": chassis.make, "status": chassis.status,
            "customer_name": chassis.customer_name, "event_count": event_count}


def renumber_plan(db: Session, loser_id: int, winner_id: int):
    """How the loser's lifecycle cycles must shift to avoid uq_chassis_events_record_cycle_type on the
    winner. If ANY loser (cycle, event_type) collides with the winner, shift EVERY loser cycle to
    winner_max + cycle (guarantees the loser's cycles are distinct and above the winner's range — no
    collision with the winner nor among themselves). Returns (collisions, cycle_map):
      • collisions = [{cycle_number, event_type, new_cycle_number}] for the actually-colliding loser events
      • cycle_map  = {old_cycle: new_cycle} applied to ALL loser cycles (empty when no shift is needed)."""
    winner_events = db.execute(
        select(ChassisLifecycleEvent.cycle_number, ChassisLifecycleEvent.event_type)
        .where(ChassisLifecycleEvent.chassis_record_id == winner_id)).all()
    winner_keys = {(c, t) for c, t in winner_events}
    winner_max = max((c for c, _ in winner_events), default=0)
    loser_events = db.execute(
        select(ChassisLifecycleEvent.cycle_number, ChassisLifecycleEvent.event_type)
        .where(ChassisLifecycleEvent.chassis_record_id == loser_id)).all()
    if not any((c, t) in winner_keys for c, t in loser_events):
        return [], {}
    cycle_map = {c: winner_max + c for c in sorted({c for c, _ in loser_events})}
    collisions = [{"cycle_number": c, "event_type": t, "new_cycle_number": cycle_map[c]}
                  for c, t in loser_events if (c, t) in winner_keys]
    return collisions, cycle_map


def preview_merge(db: Session, loser_id: int, winner_id: int) -> dict:
    """WO v4.36a §3.6 STEP 5 — read-only dry-run behind the blocking confirm modal. NO mutation.
    `blocking` = the merge can't proceed (same chassis / a deleted side); `warnings` = non-blocking
    advisories the admin should weigh; `event_collisions` shows the proposed cycle renumbering."""
    loser = db.get(ChassisRecord, loser_id)
    winner = db.get(ChassisRecord, winner_id)
    if loser is None or winner is None:
        raise HTTPException(status_code=404, detail="chassis record not found")
    warnings: list[str] = []
    blocking = False
    if loser_id == winner_id:
        warnings.append("Winner and loser are the same chassis — pick two different records.")
        blocking = True
    if loser.deleted_at is not None:
        warnings.append("Loser is already deleted (a tombstone).")
        blocking = True
    if winner.deleted_at is not None:
        warnings.append("Winner is deleted — restore it before merging into it.")
        blocking = True
    jobs = db.execute(select(func.count(ProductionJob.id))
                      .where(ProductionJob.chassis_record_id == loser_id)).scalar() or 0
    cards = db.execute(select(func.count(PrejobCard.id))
                       .where(PrejobCard.chassis_record_id == loser_id)).scalar() or 0
    loser_events = _event_count(db, loser_id)
    winner_events = _event_count(db, winner_id)
    collisions, _ = renumber_plan(db, loser_id, winner_id)
    if collisions:
        warnings.append(f"{len(collisions)} lifecycle event(s) collide on cycle/type — the loser's cycles "
                        "will be renumbered above the winner's to preserve both histories.")
    vin_conflict = bool(loser.vin and winner.vin and ci.normalize_vin(loser.vin) != ci.normalize_vin(winner.vin))
    if vin_conflict:
        warnings.append(f"VINs differ: loser {loser.vin} vs winner {winner.vin}. The loser VIN stays on the "
                        "tombstone (uniqueness holds; it's never re-adopted).")
    if (loser.customer_name and winner.customer_name
            and loser.customer_name.casefold() != winner.customer_name.casefold()):
        warnings.append(f"Customer differs: loser '{loser.customer_name}' vs winner '{winner.customer_name}'.")
    if (loser.make and winner.make
            and loser.make.strip().casefold() != winner.make.strip().casefold()):
        warnings.append(f"Make/model differs: '{loser.make}' vs '{winner.make}' — confirm these are the "
                        "same physical chassis.")
    if abs(loser_events - winner_events) >= _LARGE_EVENT_DELTA:
        warnings.append("Large lifecycle-history difference between the two chassis — double-check "
                        "they're the same unit.")
    return {
        "loser": _summary(loser, loser_events),
        "winner": _summary(winner, winner_events),
        "repoint_counts": {"production_jobs": jobs, "prejob_cards": cards, "lifecycle_events": loser_events},
        "event_collisions": collisions,
        "vin_conflict": vin_conflict,
        "warnings": warnings,
        "blocking": blocking,
    }
