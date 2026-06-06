"""WO v4.24 spike — hand-ported VACUUM ORDERS panel-count geometry (Freezer-resolved).

Each function is a faithful port of one VACUUM ORDERS qty formula, with the body-type
branches collapsed to the Freezer path (the spike slice). `dryfreight`/`icecream`/
`insulated` branches are noted in the docstrings but resolved out — porting them is a
follow-on WO. Cross-sheet refs (`'New Prep'!AO8`) are resolved to the 32735 value
(panel_length_mm, default 2440) — a documented generalisation risk (§7).

Verified against job 32735's workbook-computed cut-list (see tests/spikes + the fixture).
"""
import math

# Standard EPS/PU/ply sheet footprint (VACUUM ORDERS D/E columns for the Freezer path).
PANEL_WIDTH_MM = 1220


def _roundup(x: float) -> int:
    """Excel ROUNDUP(x, 0) for non-negative x (round away from zero to a whole number).
    The 1e-9 epsilon prevents float noise from bumping an exact integer up a panel."""
    return math.ceil(x - 1e-9)


# ── Foam panels (VACUUM ORDERS rows 5-12) ─────────────────────────────────────

def roof_foam_qty(length_mm: int) -> int:
    """Roof EPS/PU foam panel count.  Workbook: VACUUM ORDERS F5 = ROUNDUP((AF4-275)/1220,0).
    AF4 = external length. 275 mm = front+rear frame allowance; 1220 mm = panel width.
    Panels run across the length."""
    return _roundup((length_mm - 275) / PANEL_WIDTH_MM)


def floor_foam_qty(length_mm: int) -> int:
    """Floor foam panel count.  Workbook: VACUUM ORDERS F7 = IF(dryfreight,"- -",F5).
    Freezer path ⇒ equals the roof count (the dryfreight branch is resolved out)."""
    return roof_foam_qty(length_mm)


def sides_foam_qty(length_mm: int) -> int:
    """Both side walls' foam panel count.  Workbook: VACUUM ORDERS F8 =
    IF(D8=1000, ROUNDUP(AF4/500,0), F5*IF(icecream,4,2)).  Freezer path: side width D8=1220
    (not the 1000 thin-wall case) and the multiplier is 2 (icecream→4 resolved out) ⇒
    roof_count × 2 (two side walls)."""
    return roof_foam_qty(length_mm) * 2


def front_foam_qty(width_mm: int, reveal_side_mm: int) -> int:
    """Front wall foam panel count.  Workbook: VACUUM ORDERS F9 =
    ROUNDUP((AF5-(AF14*2)-100)/1220,0) * IF(icecream,2,1).  Freezer multiplier = 1.
    AF5 = width, AF14 = side reveal, 100 mm = clearance."""
    return _roundup((width_mm - reveal_side_mm * 2 - 100) / PANEL_WIDTH_MM)


def rear_foam_qty(width_mm: int, reveal_side_mm: int) -> int:
    """Rear wall foam panel count.  Workbook: VACUUM ORDERS F11 =
    ROUNDUP((AF5-(AF14*2)-99)/1220,0) * IF(icecream,2,1).  Freezer multiplier = 1.
    (99 mm clearance vs the front's 100 mm — a workbook quirk, ported verbatim.)"""
    return _roundup((width_mm - reveal_side_mm * 2 - 99) / PANEL_WIDTH_MM)


# ── Plywood inner skins (VACUUM ORDERS rows 15-19) — area-based ────────────────
# Each skin panel = ROUNDUP(face_area / sheet_area). face_area in m²; sheet = 1220×2440 mm.

def _area_panels(face_w_mm: float, face_h_mm: float, sheet_len_mm: int) -> int:
    """ROUNDUP( ((w+50)/1000 * (h+50)/1000) / ((1220/1000)*(sheet_len/1000)), 0 ).
    The +50 mm is the workbook's per-edge overlap allowance."""
    face_area = ((face_w_mm + 50) / 1000) * ((face_h_mm + 50) / 1000)
    sheet_area = (PANEL_WIDTH_MM / 1000) * (sheet_len_mm / 1000)
    return _roundup(face_area / sheet_area)


def floor_skin_qty(length_mm: int, width_mm: int, panel_length_mm: int = 2440) -> int:
    """Floor plywood skin count.  Workbook: VACUUM ORDERS F16 (Freezer path) =
    ROUNDUP(((AF4+50)/1000*(AF5+50)/1000)/((D16/1000)*(E16/1000)),0).  Special cases
    (24 mm wisa @ 7200 len ⇒ 6; len 2900-3300 ⇒ 3) are non-Freezer-32735 and resolved out."""
    return _area_panels(length_mm, width_mm, panel_length_mm)


def sides_skin_qty(length_mm: int, height_mm: int, reveal_top_mm: int,
                   floor_present: bool, panel_length_mm: int = 2440) -> int:
    """Both side walls' plywood skin count.  Workbook: VACUUM ORDERS F17 (B17≠21 path) =
    ROUNDUP(((AF4+50)/1000*((AF6-AF13-(IF(AF9="- -",0,AF13)))+50)/1000)/((D17/1000)*(E17/1000)),0)*2.
    Inner height subtracts the top reveal once, and again if a floor panel exists. ×2 = two walls."""
    inner_h = height_mm - reveal_top_mm - (reveal_top_mm if floor_present else 0)
    return _area_panels(length_mm, inner_h, panel_length_mm) * 2


def front_skin_qty(width_mm: int, height_mm: int, reveal_side_mm: int, reveal_top_mm: int,
                   floor_present: bool, panel_length_mm: int = 2440) -> int:
    """Front wall plywood skin count.  Workbook: VACUUM ORDERS F18 =
    ROUNDUP((((AF5-(AF14*2))+50)/1000*((AF6-AF13-(IF(AF9="- -",0,AF13)))+50)/1000)/((D18/1000)*(E18/1000)),0).
    Inner width subtracts both side reveals; inner height as per the sides skin."""
    inner_w = width_mm - reveal_side_mm * 2
    inner_h = height_mm - reveal_top_mm - (reveal_top_mm if floor_present else 0)
    return _area_panels(inner_w, inner_h, panel_length_mm)


def rear_skin_qty(width_mm: int, reveal_side_mm: int) -> int:
    """Rear wall plywood skin count.  Workbook: VACUUM ORDERS F19 =
    ROUNDUP((AF5-(AF14*2)-99)/1220,0).  (Panel-width based, like the rear foam — not area-based.)"""
    return _roundup((width_mm - reveal_side_mm * 2 - 99) / PANEL_WIDTH_MM)
