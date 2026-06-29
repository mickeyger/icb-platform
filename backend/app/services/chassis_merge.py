"""WO v4.36a §3.6 — admin chassis merge / restore service.

Merge = re-point every FK that references the LOSER chassis to the WINNER, then SOFT-DELETE the loser
(deleted_at + merged_into_id), NEVER hard-delete (the production_jobs FK is ON DELETE RESTRICT; lifecycle
events are CASCADE — a hard delete would be blocked / would destroy history). Lifecycle-event collisions on
uq_chassis_events_record_cycle_type (chassis_record_id, cycle_number, event_type) are resolved by
renumbering the loser's cycles ABOVE the winner's max (history preserved, photos ride the event FK).

STEP 5 ships preview_merge (read-only dry-run). merge_chassis (STEP 6) + restore_chassis (STEP 7) land next.
"""
from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.mes import AssemblyBay, ChassisLifecycleEvent, ChassisRecord, PrejobCard, ProductionJob
from app.services import chassis_integrity as ci

_LARGE_EVENT_DELTA = 4


def _double_bay_codes(db: Session, loser: ChassisRecord, winner: ChassisRecord):
    """WO v4.36a §3.8 — if BOTH chassis are CURRENTLY on (different) assembly bays, return their bay codes
    (loser_code, winner_code); else None. Merging two on-bay chassis would re-point the loser's
    assembly_assigned event onto the winner, leaving it owning TWO bays — and the second bay would read
    silently EMPTY (the assign_assembly_bay occupancy guard merge would otherwise bypass). So we refuse."""
    from app.services.chassis import _current_assembly_bay_id
    lb = _current_assembly_bay_id(db, loser.id) if loser.status == "in_assembly" else None
    wb = _current_assembly_bay_id(db, winner.id) if winner.status == "in_assembly" else None
    if lb is not None and wb is not None and lb != wb:
        def code(bid):
            b = db.get(AssemblyBay, bid)
            return b.code if b and b.code else f"#{bid}"
        return code(lb), code(wb)
    return None


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
    # Rank-based shift (sign-robust): loser cycles → winner_max+1, +2, … in order. Above the winner's
    # range AND sequential, so it can't re-collide even if a loser cycle is 0/negative (winner_max+c could).
    loser_cycles = sorted({c for c, _ in loser_events})
    cycle_map = {c: winner_max + i + 1 for i, c in enumerate(loser_cycles)}
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
    collisions, cycle_map = renumber_plan(db, loser_id, winner_id)
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
    double_bay = _double_bay_codes(db, loser, winner)
    if double_bay:                                          # §3.8 — can't merge two on-bay chassis (silent empty bay)
        warnings.append(f"Both chassis are on assembly bays ({double_bay[0]} and {double_bay[1]}) — "
                        "dispatch or clear one before merging.")
        blocking = True
    return {
        "loser": _summary(loser, loser_events),
        "winner": _summary(winner, winner_events),
        "repoint_counts": {"production_jobs": jobs, "prejob_cards": cards, "lifecycle_events": loser_events},
        "event_collisions": collisions,
        # full cycle remap (not just the colliding events) so the preview shows exactly what the merge applies
        "cycles_renumbered": [{"from": c, "to": n} for c, n in sorted(cycle_map.items())],
        "vin_conflict": vin_conflict,
        "warnings": warnings,
        "blocking": blocking,
    }


def merge_chassis(db: Session, loser_id: int, winner_id: int, who: str) -> dict:
    """WO v4.36a §3.6 STEP 6 — merge the LOSER chassis INTO the WINNER, one transaction:
      1) renumber the loser's colliding lifecycle cycles (renumber_plan) + re-point its events to the winner;
      2) re-point the loser's production_jobs + prejob_cards to the winner (no UNIQUE on chassis_record_id —
         multi-cycle consolidation is the reality; calculation_record_id (1:1) is untouched, so its UNIQUE
         can't be violated);
      3) reconcile a blank winner.job_number from a surviving job (provenance only);
      4) SOFT-DELETE the loser (deleted_at + merged_into_id=winner) — NEVER hard-delete (production_jobs FK
         is RESTRICT; events are CASCADE — a hard delete would be blocked / would destroy history).
    Photos ride the lifecycle-event FK (no separate re-point). ChassisIntegrityError → 409 via the handler."""
    from sqlalchemy.exc import IntegrityError
    loser = db.get(ChassisRecord, loser_id)
    winner = db.get(ChassisRecord, winner_id)
    if loser is None or winner is None:
        raise HTTPException(status_code=404, detail="chassis record not found")
    if loser_id == winner_id:
        raise ci.ChassisIntegrityError("Winner and loser are the same chassis.", status_code=409)
    # Lock BOTH rows (ordered by id → deadlock-safe) then re-read, so two concurrent merges serialize and
    # the deleted-state guards re-check COMMITTED state (mirrors record_planning_ack's with_for_update). A
    # double-merge of the same loser, or A→B racing B→A, becomes a clean 409 instead of silent corruption.
    for cid in sorted({loser_id, winner_id}):
        db.execute(select(ChassisRecord.id).where(ChassisRecord.id == cid).with_for_update())
    db.refresh(loser)
    db.refresh(winner)
    if loser.deleted_at is not None:
        raise ci.ChassisIntegrityError("Loser is already deleted (a tombstone).", status_code=409)
    if winner.deleted_at is not None:
        raise ci.ChassisIntegrityError("Winner is deleted — restore it before merging into it.", status_code=409)
    double_bay = _double_bay_codes(db, loser, winner)       # §3.8 — refuse two on-bay chassis (would empty a bay)
    if double_bay:
        raise ci.ChassisIntegrityError(
            f"Both chassis are on assembly bays ({double_bay[0]} and {double_bay[1]}) — "
            "dispatch or clear one before merging.", status_code=409)
    try:
        # 1) renumber colliding loser cycles, then re-point its events to the winner. One ORM pass — each
        #    new (winner, cycle, event_type) is unique vs the winner and vs the still-on-loser rows, so the
        #    per-row UPDATEs never transiently violate uq_chassis_events_record_cycle_type.
        _, cycle_map = renumber_plan(db, loser_id, winner_id)
        events = db.execute(select(ChassisLifecycleEvent)
                            .where(ChassisLifecycleEvent.chassis_record_id == loser_id)).scalars().all()
        for ev in events:
            if cycle_map:
                ev.cycle_number = cycle_map.get(ev.cycle_number, ev.cycle_number)
            ev.chassis_record_id = winner_id
        db.flush()
        # 2) re-point jobs + cards (bulk; no uq on chassis_record_id — multi-job consolidation is allowed)
        jobs_n = db.execute(update(ProductionJob).where(ProductionJob.chassis_record_id == loser_id)
                            .values(chassis_record_id=winner_id)).rowcount
        cards_n = db.execute(update(PrejobCard).where(PrejobCard.chassis_record_id == loser_id)
                             .values(chassis_record_id=winner_id)).rowcount
        # 3) reconcile a blank winner.job_number from a surviving (now winner-linked) job — provenance only
        if not (winner.job_number or "").strip():
            sj = db.execute(select(ProductionJob).where(ProductionJob.chassis_record_id == winner_id)
                            .order_by(ProductionJob.id.desc())).scalars().first()
            if sj is not None and sj.job_number:
                winner.job_number = sj.job_number
        # 4) flatten any prior chain: tombstones that pointed at THIS loser now resolve straight to the
        #    winner (A→B then B→C ⇒ A→C), keeping merged_into_id always pointing at a live survivor.
        db.execute(update(ChassisRecord).where(ChassisRecord.merged_into_id == loser_id)
                   .values(merged_into_id=winner_id))
        # 5) soft-delete the loser (audit tombstone) — never hard-delete
        loser.deleted_at = func.now()
        loser.merged_into_id = winner_id
        loser.updated_by = who
        winner.updated_by = who
        # WO v4.36.5 §3.2 — trail the merge (source='merge') so "who merged this into what?" is answerable.
        from app.services.chassis import _audit_chassis     # lazy — chassis_merge is imported by chassis-side flows
        _audit_chassis(db, loser_id, "merged_into_id", None, winner_id, "merge", who)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ci.ChassisIntegrityError(
            "Merge conflicts with existing chassis lifecycle data — review the preview and retry.",
            status_code=409)
    db.refresh(winner)
    return {"winner_id": winner_id, "loser_id": loser_id, "merged_into_id": winner_id,
            "repointed": {"production_jobs": jobs_n, "prejob_cards": cards_n, "lifecycle_events": len(events)}}


def restore_chassis(db: Session, chassis_id: int, who: str) -> ChassisRecord:
    """WO v4.36a §3.6 STEP 7 — un-soft-delete a chassis: clear deleted_at + merged_into_id. Reverses a junk
    soft-delete (STEP 4) or an accidental merge (STEP 6). Does NOT auto-re-point FKs — a merge moved them to
    the winner, so the operator re-links/merges explicitly. Guards a VIN clash (a LIVE chassis may have
    taken the VIN since the soft-delete; rare under the all-rows uq, but the check keeps the contract)."""
    rec = db.get(ChassisRecord, chassis_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="chassis record not found")
    if rec.deleted_at is None:
        raise ci.ChassisIntegrityError("This chassis is not deleted — nothing to restore.", status_code=409)
    if rec.vin:
        ci.validate_vin_uniqueness(db, rec.vin, exclude_id=chassis_id)   # 409 if a live chassis now holds it
    prior = rec.deleted_at                               # §3.8 — audit the ACTUAL cleared timestamp as old_value
    rec.deleted_at = None
    rec.merged_into_id = None
    rec.updated_by = who
    # WO v4.36.5 §3.2/§3.8 — trail the restore (source='restore'); old_value = the timestamp it cleared.
    from app.services.chassis import _audit_chassis     # lazy
    _audit_chassis(db, chassis_id, "deleted_at", (prior.isoformat() if prior else None), None, "restore", who)
    db.commit()
    db.refresh(rec)
    return rec
