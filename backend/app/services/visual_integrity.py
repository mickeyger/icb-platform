"""WO v4.36b §3.1 — Visual Integrity flag-derivation service.

THE single read-only source of truth for every visual-integrity flag. Flags are DERIVED at request
time from already-persisted data (§0.1 no new business rules, §0.2 no new tables) — never written.
Each flag traces to an existing validator/field (see docs/audit/v4_36b_S3_0_visual_integrity_discovery.md).

Design (per ratified §3.0 decisions):
  * D1 — "chassis received" reuses production_jobs.chassis_received() (the chassis_slipped KPI's own
         definition) so the ETA flags never diverge from the KPI. NO fourth definition.
  * D2 — bay_ready_to_merge_stale ages from the latest panels_arrived_in_bay.created_at (the canonical
         "ready since" event).
  * §0.6 — per-flag age bands live on FlagSpec.bands; the §0.6 default ramp (green<=2 / amber 3-4 /
         red>=5) is only the DEFAULT for a generic ageing pill — §1 overrides are explicit here.
  * §0.10 — batched: the aggregate loads chassis/jobs/bays/events ONCE and derives in memory (no N+1,
         no materialized columns). _all_*_flags() are the batched cores; the per-entity public functions
         filter them.

Severity model: each FlagSpec carries `bands` = ascending ((gt_days, severity), ...). A flag FIRES when
its CONDITION holds AND age_days exceeds the lowest band's gt; the resolved severity is the highest band
whose gt is exceeded. `pulse=True` marks a flag whose first-render-per-user gets the 24h sky pulse
(§0.7) — handled frontend-side by useSeenFlags/FlagPulse; the backend reports the STEADY severity.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select

from app.models.mes import (
    AssemblyBay, ChassisLifecycleEvent, ChassisRecord, PrejobCard, ProductionJob,
    ProductionJobBayEvent,
)
from app.services import chassis as chassis_svc
from app.services import production_jobs as pj_svc
from app.services.chassis_integrity import VIN_RE, normalize_vin

# In-flight job statuses worth flagging (mirror pj_svc.IN_FLIGHT_STATUSES intent without importing a
# private constant; ETA flags only matter while a job is live in the pipeline).
_FLAGGABLE_JOB_STATUSES = ("pre_job_sent", "pre_job_confirmed", "planning", "in_production")


# ── flag registry ────────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class FlagSpec:
    flag: str
    domain: str          # 'chassis' | 'jobs' | 'bays' — which drill-through list endpoint surfaces it
    group: str           # Health Check section (§0.9): Chassis | Jobs | Bays | Sign-offs | Stale Reviews
    label: str           # short badge label
    remediation: str     # operator-facing "what to do"
    bands: tuple         # ((gt_days, severity), ...) ascending; severity in {'sky','amber','red'}
    pulse: bool = False  # eligible for the §0.7 first-seen 24h sky pulse


# §0.6 per-flag thresholds are the `bands`. Default ramp (green<=2/amber3-4/red>=5) applies only to a
# generic ageing pill; the overrides below are explicit (e.g. post_attached red>5, awaiting_qa red>7).
FLAG_SPECS: dict[str, FlagSpec] = {
    # ── Chassis domain ──
    "chassis_no_vin": FlagSpec(
        "chassis_no_vin", "chassis", "Chassis", "No VIN",
        "Open the Chassis Edit modal → capture VIN", ((0, "red"),)),
    "chassis_no_customer": FlagSpec(
        "chassis_no_customer", "chassis", "Chassis", "No customer",
        "Auto-populate from the linked job in the Edit modal", ((-1, "red"),)),
    "chassis_no_production_job": FlagSpec(
        "chassis_no_production_job", "chassis", "Chassis", "No job",
        "Use Find Orphan → adopt to a job", ((1, "amber"), (2, "red")), pulse=True),
    "chassis_vin_format_legacy": FlagSpec(
        "chassis_vin_format_legacy", "chassis", "Chassis", "Legacy VIN",
        "Edit Chassis modal → correct the VIN to ISO-3779", ((-1, "amber"),)),
    "chassis_no_make_model": FlagSpec(
        "chassis_no_make_model", "chassis", "Chassis", "No make/model",
        "Edit Chassis modal → fill in make/model", ((0, "amber"),)),
    "awaiting_qa_stale": FlagSpec(      # entity is a chassis (off the bay, in QA) but it's the Bays flow
        "awaiting_qa_stale", "chassis", "Bays", "QA overdue",
        "Kenny inspection priority (v4.36c)", ((3, "amber"), (7, "red"))),
    # ── Jobs domain ──
    "job_eta_overdue": FlagSpec(
        "job_eta_overdue", "jobs", "Jobs", "ETA overdue",
        "Update ETA in Planning Ack or contact the dealer", ((0, "red"),), pulse=True),
    "job_eta_missing": FlagSpec(
        "job_eta_missing", "jobs", "Jobs", "ETA missing",
        "Planning Ack → stamp the chassis ETA", ((0, "amber"),)),
    "prejob_sent_stale": FlagSpec(
        "prejob_sent_stale", "jobs", "Stale Reviews", "Pre-Job stale",
        "Chase sign-offs via Outstanding Sign-offs admin", ((5, "amber"),), pulse=True),
    "signoff_pending_long": FlagSpec(
        "signoff_pending_long", "jobs", "Sign-offs", "Sign-off pending",
        "Outstanding Sign-offs admin → nudge or override", ((7, "amber"),)),
    "signoff_role_pending_5days": FlagSpec(
        "signoff_role_pending_5days", "jobs", "Sign-offs", "Role pending",
        "Outstanding Sign-offs admin → nudge the named role", ((5, "amber"),), pulse=True),
    # ── Bays domain ──
    "bay_ready_to_merge_stale": FlagSpec(
        "bay_ready_to_merge_stale", "bays", "Bays", "Ready to merge",
        "Foreman intervention — start the merge or move the panels", ((1, "amber"),), pulse=True),
    "bay_post_attached_stale": FlagSpec(
        "bay_post_attached_stale", "bays", "Bays", "Post-attach idle",
        "Drag to Awaiting QA", ((3, "amber"), (5, "red"))),
}

# WO v4.36b §3.5 — role-based flag visibility (§0.11). Implemented as a service-layer FILTER over the flag
# GROUP, NOT as flag.read.* permission keys: this codebase has no `.read` permission keys (the §3.1
# require_user deviation, BA-ratified on §3.1 review), and a new permissions migration would collide with
# CA4's held 0027. This matrix is a CODE CONSTANT BY DESIGN until Phase 2+ asks for an admin-editable matrix
# (which would then add a flag_permissions table). admin/planner/production see everything; workshop + sales
# are scoped. An unknown/blank role falls through to ALL (flags are advisory; require_user already gates).
_GROUP_ORDER = ("Chassis", "Jobs", "Bays", "Sign-offs", "Stale Reviews")
_ALL_GROUPS = set(_GROUP_ORDER)
_ROLE_GROUPS: dict[str, set] = {
    "admin": _ALL_GROUPS,
    "planner": _ALL_GROUPS,
    "production": _ALL_GROUPS,
    "workshop": {"Jobs", "Bays"},
    "sales": {"Chassis", "Sign-offs", "Stale Reviews"},   # pre-job chassis + sign-off/review
}


def _visible_groups(role: Optional[str]) -> set:
    """The flag GROUPS `role` may see (§0.11). Unknown/None → all (advisory flags; require_user gates access)."""
    return _ROLE_GROUPS.get((role or "").strip().lower(), _ALL_GROUPS)


def flag_catalog(role: Optional[str] = None) -> dict:
    """The flag-registry metadata, filtered to the groups `role` may see (§3.5) — drives the Health Check
    dashboard so a restricted role's hidden group cards don't render at all."""
    visible = _visible_groups(role)
    return {k: s for k, s in FLAG_SPECS.items() if s.group in visible}


# ── helpers ────────────────────────────────────────────────────────────────────────────────────────
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _age_days(now: datetime, basis) -> Optional[int]:
    """Whole 24h periods elapsed since `basis` (a date or datetime). A Date is anchored at UTC midnight."""
    if basis is None:
        return None
    if isinstance(basis, datetime):
        b = _aware(basis)
    elif isinstance(basis, date):
        b = datetime(basis.year, basis.month, basis.day, tzinfo=timezone.utc)
    else:
        return None
    return (now - b).days


def _resolve(spec: FlagSpec, age_days: Optional[int]) -> Optional[str]:
    """Highest band whose gt is exceeded by age_days → severity, or None if the flag doesn't fire.
    age_days is always >=0 for a real record; a band gt=-1 means 'fires immediately' (no age gate)."""
    if age_days is None:
        return None
    sev = None
    for gt, severity in spec.bands:
        if age_days > gt:
            sev = severity
    return sev


def _hit(spec: FlagSpec, severity: str, age_days: Optional[int]) -> dict:
    """One flag instance, as rendered: enum + resolved severity + age + display metadata."""
    return {
        "flag": spec.flag,
        "severity": severity,
        "age_days": age_days,
        "label": spec.label,
        "remediation": spec.remediation,
        "group": spec.group,
        "domain": spec.domain,
        "pulse": spec.pulse,
    }


# ── batched cores ────────────────────────────────────────────────────────────────────────────────
def _all_chassis_flags(db, *, now: Optional[datetime] = None) -> dict[int, list[dict]]:
    """{chassis_id: [flag, ...]} for every live chassis. One pass; back-ref job/card membership and the
    moved_to_awaiting_qa dates are batch-loaded (no N+1)."""
    now = now or _now()
    rows = db.execute(
        select(ChassisRecord).where(ChassisRecord.deleted_at.is_(None))).scalars().all()
    if not rows:
        return {}
    ids = [c.id for c in rows]
    # back-ref membership (the link lives on the job/card side — no production_job_id column on chassis)
    jobbed = {cid for (cid,) in db.execute(
        select(ProductionJob.chassis_record_id)
        .where(ProductionJob.chassis_record_id.in_(ids))).all() if cid is not None}
    carded = {cid for (cid,) in db.execute(
        select(PrejobCard.chassis_record_id)
        .where(PrejobCard.chassis_record_id.in_(ids))).all() if cid is not None}
    # awaiting_qa transition dates (batch) for the QA-stale age basis
    qa_ids = [c.id for c in rows if c.status == "awaiting_qa"]
    qa_dates: dict[int, date] = {}
    if qa_ids:
        for cid, ev_date in db.execute(
            select(ChassisLifecycleEvent.chassis_record_id, ChassisLifecycleEvent.event_date)
            .where(ChassisLifecycleEvent.chassis_record_id.in_(qa_ids),
                   ChassisLifecycleEvent.event_type == "moved_to_awaiting_qa")
            .order_by(ChassisLifecycleEvent.chassis_record_id, ChassisLifecycleEvent.id.desc())
        ).all():
            qa_dates.setdefault(cid, ev_date)

    out: dict[int, list[dict]] = {}
    for c in rows:
        age = _age_days(now, c.created_at)
        hits: list[dict] = []

        def add(flag_key: str, *, basis_age: Optional[int] = age, condition: bool = True):
            if not condition:
                return
            spec = FLAG_SPECS[flag_key]
            sev = _resolve(spec, basis_age)
            if sev is not None:
                hits.append(_hit(spec, sev, basis_age))

        vin = normalize_vin(c.vin)
        add("chassis_no_vin", condition=vin is None)
        add("chassis_vin_format_legacy", condition=vin is not None and not VIN_RE.match(vin))
        add("chassis_no_customer",
            condition=(c.id in jobbed) and not (c.customer_name or "").strip())
        add("chassis_no_production_job",
            condition=(c.id not in jobbed) and (c.id not in carded)
            and c.status in ("expected", "expected_orphaned"))
        add("chassis_no_make_model",
            condition=c.status in ("expected", "expected_orphaned")
            and not (c.make or "").strip())
        if c.status == "awaiting_qa":
            add("awaiting_qa_stale", basis_age=_age_days(now, qa_dates.get(c.id)))

        if hits:
            out[c.id] = hits
    return out


def _all_job_flags(db, *, now: Optional[datetime] = None) -> dict[int, list[dict]]:
    """{job_id: [flag, ...]} for flaggable in-flight jobs, plus the card-derived sign-off/stale flags
    mapped onto their job (a Pre-Job Card maps to its calc's job)."""
    now = now or _now()
    today = now.date()
    jobs = db.execute(
        select(ProductionJob).where(ProductionJob.status.in_(_FLAGGABLE_JOB_STATUSES))).scalars().all()
    ch_status = pj_svc._chassis_status_map(db, jobs)        # D1 reuse: feeds chassis_received()
    by_calc: dict[int, ProductionJob] = {j.calculation_record_id: j for j in jobs
                                         if j.calculation_record_id is not None}
    out: dict[int, list[dict]] = {}

    def add(job_id: int, flag_key: str, age_days: Optional[int]):
        spec = FLAG_SPECS[flag_key]
        sev = _resolve(spec, age_days)
        if sev is not None:
            out.setdefault(job_id, []).append(_hit(spec, sev, age_days))

    for j in jobs:
        received = pj_svc.chassis_received(j, ch_status.get(j.chassis_record_id))
        eta = _aware(j.chassis_eta)
        if eta is not None and eta.date() < today and not received:
            add(j.id, "job_eta_overdue", (today - eta.date()).days)
        elif (j.status == "planning" and j.chassis_eta is None and not received):
            add(j.id, "job_eta_missing", _age_days(now, j.planning_acknowledged_at))

    # card-derived flags → mapped onto the card's job (anchor created at submit). Jobless cards are rare
    # (submit anchors a job) and simply don't surface a job-keyed flag.
    cards = db.execute(
        select(PrejobCard).where(PrejobCard.status == "sent_for_check")).scalars().all()
    for card in cards:
        job = by_calc.get(card.calculation_id)
        if job is None:
            continue
        sent_age = _age_days(now, card.sent_for_check_at)
        add(job.id, "prejob_sent_stale", sent_age)
        add(job.id, "signoff_pending_long", sent_age)
        role_pending = card.sales_rep_signoff_at is None or card.planner_signoff_at is None
        if role_pending:
            add(job.id, "signoff_role_pending_5days", sent_age)
    return out


def _bay_panels_arrived_at(db, bay_ids: list[int]) -> dict[int, datetime]:
    """{bay_id: latest panels_arrived_in_bay.created_at} (D2 — the 'ready since' timestamp), batched."""
    if not bay_ids:
        return {}
    out: dict[int, datetime] = {}
    for bay_id, created in db.execute(
        select(ProductionJobBayEvent.bay_id, ProductionJobBayEvent.created_at)
        .where(ProductionJobBayEvent.bay_id.in_(bay_ids),
               ProductionJobBayEvent.event_type == "panels_arrived_in_bay")
        .order_by(ProductionJobBayEvent.bay_id, ProductionJobBayEvent.id.desc())
    ).all():
        out.setdefault(bay_id, created)
    return out


def _all_bay_flags(db, *, now: Optional[datetime] = None) -> dict[int, list[dict]]:
    """{bay_id: [flag, ...]} for the assembly bays. Bay state via the single-source readiness machine;
    occupants batched once; panels-arrived timestamps batched once."""
    now = now or _now()
    today = now.date()
    bays = chassis_svc.list_assembly_bays(db)
    occupants = chassis_svc.current_occupants(db)          # batched once, passed per-bay
    panels_at = _bay_panels_arrived_at(db, [b.id for b in bays])
    out: dict[int, list[dict]] = {}

    def add(bay_id: int, flag_key: str, age_days: Optional[int]):
        spec = FLAG_SPECS[flag_key]
        sev = _resolve(spec, age_days)
        if sev is not None:
            out.setdefault(bay_id, []).append(_hit(spec, sev, age_days))

    for bay in bays:
        r = chassis_svc.compute_bay_merge_readiness(db, bay.id, occupants=occupants)
        if r["state"] == "ready_to_merge":
            add(bay.id, "bay_ready_to_merge_stale", _age_days(now, panels_at.get(bay.id)))
        elif r["state"] == "post_attached":
            att = r["body_attached_on"]                    # a date
            add(bay.id, "bay_post_attached_stale", (today - att).days if att else None)
    return out


# ── per-entity public API (§0.3) ───────────────────────────────────────────────────────────────────
def compute_chassis_flags(db, chassis_id: int, *, now: Optional[datetime] = None) -> list[dict]:
    return _all_chassis_flags(db, now=now).get(chassis_id, [])


def compute_job_flags(db, job_id: int, *, now: Optional[datetime] = None) -> list[dict]:
    return _all_job_flags(db, now=now).get(job_id, [])


def compute_bay_flags(db, bay_id: int, *, now: Optional[datetime] = None) -> list[dict]:
    return _all_bay_flags(db, now=now).get(bay_id, [])


# ── aggregate + drill-through (§0.3 / §0.4) ──────────────────────────────────────────────────────────
def compute_planning_board_flags(db, *, role: Optional[str] = None, now: Optional[datetime] = None) -> dict:
    """Aggregate counts for the Health Check dashboard + the nav badge (§0.4 summary), filtered to the
    groups `role` may see (§3.5/§0.11). ONE batched computation across chassis/jobs/bays. Counts are flag
    INSTANCES (an entity with two visible flags counts twice); `entities` counts distinct entities with
    >=1 VISIBLE flag (the nav 'N attention items' badge)."""
    now = now or _now()
    visible = _visible_groups(role)
    ch = _all_chassis_flags(db, now=now)
    jb = _all_job_flags(db, now=now)
    by = _all_bay_flags(db, now=now)

    by_flag: dict[str, int] = {}
    by_group: dict[str, int] = {g: 0 for g in _GROUP_ORDER if g in visible}
    by_severity = {"red": 0, "amber": 0, "sky": 0}
    entities = 0
    for bucket in (ch, jb, by):
        for hits in bucket.values():
            vis = [h for h in hits if h["group"] in visible]
            if vis:
                entities += 1
            for h in vis:
                by_flag[h["flag"]] = by_flag.get(h["flag"], 0) + 1
                by_group[h["group"]] = by_group.get(h["group"], 0) + 1
                by_severity[h["severity"]] = by_severity.get(h["severity"], 0) + 1
    total = sum(by_flag.values())
    return {
        "total": total,
        "entities": entities,
        "by_flag": by_flag,
        "by_group": by_group,
        "by_severity": by_severity,
    }


def list_flagged_chassis(db, flag: Optional[str] = None, *, role: Optional[str] = None,
                         now: Optional[datetime] = None) -> list[dict]:
    """Chassis carrying >=1 flag visible to `role` (or the given `flag`), with identity fields for the
    drill-through list."""
    visible = _visible_groups(role)
    flags = _all_chassis_flags(db, now=now)

    def _vis(hits):
        return [h for h in hits if (flag is None or h["flag"] == flag) and h["group"] in visible]
    ids = [cid for cid, hits in flags.items() if _vis(hits)]
    if not ids:
        return []
    rows = {c.id: c for c in db.execute(
        select(ChassisRecord).where(ChassisRecord.id.in_(ids))).scalars().all()}
    out = []
    for cid in ids:
        c = rows.get(cid)
        if c is None:
            continue
        out.append({"chassis_id": cid, "vin": c.vin, "make": c.make, "model": c.model,
                    "customer_name": c.customer_name, "status": c.status, "flags": _vis(flags[cid])})
    return out


def list_flagged_jobs(db, flag: Optional[str] = None, *, role: Optional[str] = None,
                      now: Optional[datetime] = None) -> list[dict]:
    visible = _visible_groups(role)
    flags = _all_job_flags(db, now=now)

    def _vis(hits):
        return [h for h in hits if (flag is None or h["flag"] == flag) and h["group"] in visible]
    ids = [jid for jid, hits in flags.items() if _vis(hits)]
    if not ids:
        return []
    rows = {j.id: j for j in db.execute(
        select(ProductionJob).where(ProductionJob.id.in_(ids))).scalars().all()}
    out = []
    for jid in ids:
        j = rows.get(jid)
        if j is None:
            continue
        out.append({"job_id": jid, "job_number": j.job_number, "customer_name": j.customer_name,
                    "status": j.status,
                    "chassis_eta": j.chassis_eta.date().isoformat() if j.chassis_eta else None,
                    "flags": _vis(flags[jid])})
    return out


def list_flagged_bays(db, flag: Optional[str] = None, *, role: Optional[str] = None,
                      now: Optional[datetime] = None) -> list[dict]:
    visible = _visible_groups(role)
    flags = _all_bay_flags(db, now=now)

    def _vis(hits):
        return [h for h in hits if (flag is None or h["flag"] == flag) and h["group"] in visible]
    ids = [bid for bid, hits in flags.items() if _vis(hits)]
    if not ids:
        return []
    rows = {b.id: b for b in db.execute(
        select(AssemblyBay).where(AssemblyBay.id.in_(ids))).scalars().all()}
    out = []
    for bid in ids:
        b = rows.get(bid)
        if b is None:
            continue
        out.append({"bay_id": bid, "code": b.code, "label": b.label, "flags": _vis(flags[bid])})
    return out
