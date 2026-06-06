"""WO v4.24 spike — POST /api/bom/generate (stateless BOM rule-engine, §0.5).

EXPLORATORY SPIKE endpoint. Generates a Vacuum-Materials panel BOM from a resolved JobSpec
and prices it from icb_sap.OITM (read-only, ADR 0013). No persistence, not wired into the MES.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...database import User, get_db
from ...deps import require_user
from .bom_generator import generate_bom
from .models import BomOutput, JobSpec

router = APIRouter(prefix="/api/bom", tags=["bom-spike-v4.24"])


@router.post("/generate", response_model=BomOutput)
def generate(spec: JobSpec, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Generate the Vacuum-Materials panel BOM for a resolved Freezer job spec (spike)."""
    return generate_bom(spec, db)
