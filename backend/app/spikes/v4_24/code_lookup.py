"""WO v4.24 spike — the (material, thickness) → description → SAP code resolution.

This is the SECOND hop the workbook does (2026 BOM `C = VLOOKUP(description, Table15, 2)`),
ported here as a DATA map for the Freezer Vacuum-Materials subset. It's deliberately a small
hardcoded table sourced from job 32735's workbook (cut-list descriptions + 2026 BOM codes) —
NOT a reconstruction of the brittle description template (note the "24 DV" vs "32DV" spacing
quirk). **Scaling signal (§7):** every section/material-family the rule engine touches needs
its own description→code map ported — this map-as-data is a core hand-port-vs-rules-table input.

Provenance: COSTING MODULE 2026.xlsx, job 32735, VACUUM ORDERS cut-list + 2026 BOM.
"""
from typing import Optional, Tuple

# (material, thickness_mm) -> (workbook material description, SAP ItemCode in icb_sap.OITM)
_VACUUM_CODE_MAP = {
    ("EPS 24DV", 76): ("076mm EPS 2440x1220mm 24 DV", "GRP-MPS-A-0077"),
    ("PU 32DV", 56):  ("056mm PU 2440x1220mm 32DV", "GRP-POL-A-0158"),
    ("PU 32DV", 60):  ("060mm PU 2440x1220mm 32DV", "GRP-PUS-A-0031"),
    ("FINN PLY", 12): ("Birch Plywood Uncoated 12mm 2440x1220mm S/BB", "GRP-TIM-A-0005"),
    ("PLY", 4):       ("Pine Plywood BC 2440x1220x04mm", "GRP-TIM-A-0007"),
    ("PLY", 6):       ("Pine Plywood BC 2440x1220x06mm", "GRP-TIM-A-0008"),
}

# Inner-skin spec string (VACUUM ORDERS AH*) -> (resolved material, thickness_mm).
# Ports the row 16-19 B/C-column IF-chains for the Freezer skins present in job 32735.
_SKIN_SPEC = {
    "12mm finn": ("FINN PLY", 12),
    "4mm plywood": ("PLY", 4),
    "6mm plywood": ("PLY", 6),
}


def resolve(material: Optional[str], thickness_mm: Optional[int]) -> Tuple[Optional[str], Optional[str]]:
    """(material, thickness) -> (description, sap_code), or (None, None) if not in the
    ported Freezer-vacuum subset. Material match is case-insensitive + whitespace-trimmed."""
    if material is None or thickness_mm is None:
        return None, None
    key = (material.strip().upper(), int(thickness_mm))
    for (mat, thk), (desc, code) in _VACUUM_CODE_MAP.items():
        if (mat.upper(), thk) == key:
            return desc, code
    return None, None


def skin_material(skin_spec: Optional[str]) -> Tuple[Optional[str], Optional[int]]:
    """Inner-skin spec (e.g. '12mm finn') -> (material, thickness_mm), or (None, None)
    when there is no skin / it's an unported variant."""
    if not skin_spec:
        return None, None
    return _SKIN_SPEC.get(skin_spec.strip().lower(), (None, None))
