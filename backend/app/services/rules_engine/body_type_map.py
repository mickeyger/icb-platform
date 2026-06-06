"""WO v4.27 — map the 39 catalogue trailer_types to the 8 DDM body types.

Locked map (docs/v4.27-trailer-type-body-type-mapping.md, BA-signed-off). A keyword matcher on the
uppercased trailer_type name — resilient to size variants ("4.9 & UP CHILLER…") and the [deleted-N]
retired rows (which keep their semantic name). Unmapped (MANNI / ADVANTICA / ADV VACUUM PANELS /
TAUT LINER) → None → the accept hook persists an 'incomplete' BOM (BA-locked discipline).
"""
from typing import Optional

# Ordered (keyword, body_type) — first containing match wins. Explosive first, defensively.
_KEYWORD_MAP = [
    ("EXPLOSIVE", "Explosive"),
    ("FREEZER", "Freezer"),
    ("CHILLER", "Chiller"),
    ("ICECREAM", "Icecream"),
    ("DRY FREIGHT", "Dryfreight"),
    ("DRYFREIGHT", "Dryfreight"),
    ("MEAT", "Carcass"),
    ("GRP", "Insulated Trailer"),
    ("RHINORANGE", "Insulated Trailer"),
]


def map_trailer_type(name: Optional[str]) -> Optional[str]:
    """Catalogue trailer_type name → one of the 8 DDM body types, or None if unmapped."""
    if not name:
        return None
    up = str(name).upper()
    for kw, body in _KEYWORD_MAP:
        if kw in up:
            return body
    return None
