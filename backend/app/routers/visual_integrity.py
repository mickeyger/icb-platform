"""WO v4.36b §3.1 — `/api/visual-integrity/*` flag endpoints.

Thin read-only handlers over services/visual_integrity.py (the single derivation source). Every flag is
DERIVED at request time from existing data — no writes, no new tables (§0.1/§0.2).

Permission (§0.4 + §3.1 note): the WO names `production.read`, but this codebase has no `.read`
permission keys — read endpoints gate on an authenticated user (`require_user`), the established
convention (see chassis_records bays/awaiting-qa). The finer per-role flag visibility (§0.11) and the
`flag.read.*` keys land in §3.5; until then any authenticated user may read the flag surface.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import User, get_db
from ..deps import require_user
from ..services import visual_integrity as svc

router = APIRouter(prefix="/api/visual-integrity", tags=["visual-integrity"])


@router.get("/flags/summary")
def flags_summary(db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Aggregate flag counts for the Health Check dashboard + the nav 'N attention items' badge,
    filtered to the caller's role (§3.5/§0.11)."""
    return svc.compute_planning_board_flags(db, role=getattr(user, "role", None))


@router.get("/flags/chassis")
def flags_chassis(flag: Optional[str] = Query(None, description="Filter to one flag enum"),
                  db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Drill-through: chassis carrying >=1 flag (or the given `flag`), filtered to the caller's role."""
    return svc.list_flagged_chassis(db, flag, role=getattr(user, "role", None))


@router.get("/flags/jobs")
def flags_jobs(flag: Optional[str] = Query(None, description="Filter to one flag enum"),
               db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Drill-through: production jobs carrying >=1 flag (incl. card-derived sign-off/stale flags),
    filtered to the caller's role."""
    return svc.list_flagged_jobs(db, flag, role=getattr(user, "role", None))


@router.get("/flags/bays")
def flags_bays(flag: Optional[str] = Query(None, description="Filter to one flag enum"),
               db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Drill-through: assembly bays carrying >=1 flag, filtered to the caller's role."""
    return svc.list_flagged_bays(db, flag, role=getattr(user, "role", None))


@router.get("/flags/catalog")
def flags_catalog(user: User = Depends(require_user)):
    """The flag registry metadata (label, group, domain, remediation, age bands, pulse) — filtered to the
    groups the caller's role may see (§3.5), so the Health Check dashboard hides a restricted role's group
    cards. Drives the AgeingPill (§0.6) thresholds + tooltips. Static; no DB read."""
    return {
        key: {
            "flag": s.flag, "domain": s.domain, "group": s.group, "label": s.label,
            "remediation": s.remediation, "pulse": s.pulse,
            "bands": [{"gt_days": gt, "severity": sev} for gt, sev in s.bands],
        }
        for key, s in svc.flag_catalog(getattr(user, "role", None)).items()
    }
