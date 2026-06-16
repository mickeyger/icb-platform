"""WO v4.36a §0.13 — the single chassis-integrity validation library.

Called from EVERY chassis-mutation path (Pre-Job auto-create, Planning ack, Add-Chassis, admin
merge/retrofit) so the three capture paths share ONE definition of "valid" and cannot drift (the v4.34.2
chokepoint pattern, applied to validation). Functions raise ChassisIntegrityError — a ServiceError carrying
an HTTP status (422 pre-condition / 409 conflict) + remediation text — mapped to a JSON response by the app
exception handler (main.py).

VIN format is enforced WRITE-TIME-ONLY on a non-NULL VIN (NULL/blank = unknown, exempt — 'expected' chassis
legitimately carry NULL). Existing non-conforming rows are NEVER re-validated (§3.0 ruling D-VIN); the strict
17-char ISO-3779 rule applies only to a VIN being freshly written.
"""
from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services.production_jobs import ServiceError

# ISO-3779: exactly 17 chars, uppercase letters + digits, excluding I, O and Q.
VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


class ChassisIntegrityError(ServiceError):
    """A chassis-integrity validation failure (WO v4.36a). `status_code` is 422 (bad input / pre-condition)
    or 409 (conflict with existing state). Mapped to {"detail": message} by the app exception handler."""

    def __init__(self, message: str, *, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def normalize_vin(vin: Optional[str]) -> Optional[str]:
    """Trim + uppercase a VIN; None / blank → None (unknown)."""
    if vin is None:
        return None
    v = vin.strip().upper()
    return v or None


def validate_vin_format(vin: Optional[str]) -> Optional[str]:
    """Return the normalized VIN (or None when unknown), or raise ChassisIntegrityError(422). NULL/blank is
    EXEMPT (unknown VIN). A non-NULL VIN must be strict 17-char ISO-3779 (no I, O, Q)."""
    v = normalize_vin(vin)
    if v is None:
        return None
    if not VIN_RE.match(v):
        raise ChassisIntegrityError(
            f"VIN must be 17 characters — letters and digits only, no I, O or Q (ISO-3779). "
            f"Got {len(v)} character(s): {v!r}.", status_code=422)
    return v


def resolve_existing_chassis(db: Session, vin: Optional[str]):
    """The LIVE chassis_records row carrying this VIN, or None — drives the §0.8 auto-adopt. NULL → None.
    Excludes soft-deleted (merged) rows so a tombstoned loser never re-adopts."""
    from app.models.mes import ChassisRecord
    v = normalize_vin(vin)
    if v is None:
        return None
    return db.execute(
        select(ChassisRecord).where(
            ChassisRecord.vin == v, ChassisRecord.deleted_at.is_(None))).scalars().first()


def validate_vin_uniqueness(db: Session, vin: Optional[str], *, exclude_id: Optional[int] = None) -> None:
    """Raise ChassisIntegrityError(409) if another LIVE chassis already carries this VIN (NULL is exempt —
    Postgres keeps NULLs out of uq_chassis_records_vin natively)."""
    existing = resolve_existing_chassis(db, vin)
    if existing is not None and existing.id != exclude_id:
        raise ChassisIntegrityError(
            f"VIN {normalize_vin(vin)} is already on chassis {existing.id} "
            f"(customer {existing.customer_name or '—'}). Use Merge Chassis to swap the chassis.",
            status_code=409)


def validate_job_link(db: Session, job_id: Optional[int]):
    """Return the ProductionJob for job_id, or None when job_id is None. Raise 422 if the id is unknown."""
    if job_id is None:
        return None
    from app.models.mes import ProductionJob
    job = db.get(ProductionJob, job_id)
    if job is None:
        raise ChassisIntegrityError(f"production job {job_id} not found", status_code=422)
    return job


def validate_dealer(db: Session, dealer_id) -> Optional[int]:
    """Validate dealer_id refers to a customer flagged is_dealer=true. None/blank → None. Raise 422 if the
    id is non-numeric, unknown, or not a dealer (§0.5 — closes the AJ unvalidated-dealer gap)."""
    if dealer_id in (None, ""):
        return None
    try:
        did = int(dealer_id)
    except (TypeError, ValueError):
        raise ChassisIntegrityError(f"dealer_id {dealer_id!r} is not a valid id", status_code=422)
    from app.database import Customer
    cust = db.get(Customer, did)
    if cust is None or not bool(getattr(cust, "is_dealer", False)):
        raise ChassisIntegrityError(
            f"Customer {did} is not flagged as a dealer — pick a dealer, or set is_dealer in Admin.",
            status_code=422)
    return did


def validate_customer_consistency(chassis_customer_name: Optional[str],
                                  job_customer_name: Optional[str]) -> None:
    """§0.9 — if BOTH the job's customer and the chassis's customer are known and differ, raise 409.
    Best-effort, case/whitespace-insensitive name comparison; a blank on either side skips the check (e.g.
    Burt's Toyota Rustenburg = both customer AND dealer is one customer_id → same name → no conflict)."""
    a = (chassis_customer_name or "").strip().casefold()
    b = (job_customer_name or "").strip().casefold()
    if a and b and a != b:
        raise ChassisIntegrityError(
            f"Job customer ({job_customer_name}) does not match chassis customer ({chassis_customer_name}). "
            "Use Merge Chassis if these are the same entity, or capture under the correct customer.",
            status_code=409)
