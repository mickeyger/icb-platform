"""WO v4.25/§0.8 v4.26 — BOM generation endpoint (rules-engine-backed).

`POST /api/bom/generate` accepts EITHER a resolved `JobSpec` (v4.25 shape, default) OR — when the
body carries `"mode": "raw"` — a `JobSpecRaw` of dropdown labels, which the DDM resolver turns into
a resolved JobSpec (early-binding) before the rules engine runs. Both reach the same engine.

Admin CRUD for the master-data tables lives under app/routers/admin/* (WO v4.26).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..database import User, get_db
from ..deps import require_user
from ..schemas.bom import BomOutput, JobSpec, JobSpecRaw
from ..services.rules_engine.ddm_resolver import SpecResolutionError, resolve_jobspec_raw
from ..services.rules_engine.engine import RulesEngine

router = APIRouter(tags=["bom"])


@router.post("/api/bom/generate", response_model=BomOutput)
async def generate_bom(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Generate the Vacuum-Materials panel BOM. Send a resolved JobSpec, or `{"mode":"raw", ...}`
    with dropdown labels for the early-binding (DDM-resolved) path."""
    body = await request.json()
    try:
        if isinstance(body, dict) and body.get("mode") == "raw":
            spec = resolve_jobspec_raw(db, JobSpecRaw.model_validate(body))
        else:
            spec = JobSpec.model_validate(body)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())
    except SpecResolutionError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return RulesEngine(db).generate_bom(spec)
