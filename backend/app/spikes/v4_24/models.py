"""WO v4.24 spike — Pydantic schemas for the BOM rule-engine (Vacuum × Freezer).

JobSpec carries the *resolved* per-panel specs (the post-dropdown values the workbook's
VACUUM ORDERS `AF`/`AG`/`AH` block reads from `2026 COSTINGS!D*`). The spike ports the
geometry from these resolved specs; the upstream DDM dropdown→spec resolution layer is a
separate downstream WO (the §7 spec-resolution boundary). See the spike report.
"""
from datetime import datetime
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class PanelSpec(BaseModel):
    """One panel face's resolved spec. thickness_mm None ⇒ the panel is absent
    (e.g. partition on a body with no partition)."""
    thickness_mm: Optional[int] = None      # VACUUM ORDERS AF7..AF12
    material: Optional[str] = None           # VACUUM ORDERS AG7..AG12 (e.g. "EPS 24DV", "PU 32DV")
    skin: Optional[str] = None               # VACUUM ORDERS AH7..AH11 inner skin (e.g. "12mm finn", "4mm plywood")


class JobSpec(BaseModel):
    """Resolved Freezer job spec for the Vacuum Materials slice (spike scope)."""
    job: Optional[int] = None
    body_type: Literal["Freezer"]            # spike scope (§0.1)
    length_mm: int                           # VACUUM ORDERS AF4  ('2026 COSTINGS'!D14)
    width_mm: int                            # AF5  (D15)
    height_mm: int                           # AF6  (D16)

    roof: PanelSpec                          # AF7/AG7/AH7
    sides: PanelSpec                         # AF8/AG8/AH8
    floor: PanelSpec                         # AF9/AG9/AH9
    front: PanelSpec                         # AF10/AG10/AH10
    rear: PanelSpec                          # AF11/AG11/AH11
    partition: PanelSpec = PanelSpec()       # AF12/AG12 (absent for the 32735 Freezer)

    # Reveal / frame allowances (VACUUM ORDERS AF13..AF16, resolved from 2026 COSTINGS)
    reveal_top_mm: int = 81                  # AF13
    reveal_side_mm: int = 65                 # AF14
    reveal_rear_mm: int = 93                 # AF15
    reveal_partition_mm: int = 56            # AF16
    # Cross-sheet dependency: 'New Prep'!AO8 drives panel LENGTH (2440 vs 2630). Resolved to
    # the 32735 value for the spike; a documented risk for generalisation (§7).
    panel_length_mm: int = 2440


class BomLine(BaseModel):
    material_description: str
    sap_code: Optional[str] = None
    qty: Decimal
    unit_price: Optional[Decimal] = None
    line_total: Optional[Decimal] = None
    section: str = "Vacuum Materials"
    mechanism: str = "panel-count"           # spike covers the panel-count mechanism (§7)


class BomOutput(BaseModel):
    job_spec_echo: JobSpec
    lines: List[BomLine] = Field(default_factory=list)
    grand_total: Optional[Decimal] = None    # sum of priced panel-count lines (spike scope)
    unpriced_codes: List[str] = Field(default_factory=list)
    generated_at: datetime
    # Spike provenance / scope flags (so callers + the report are unambiguous)
    scope_note: str = ("SPIKE: Vacuum Materials panel-count mechanism only (foam + plywood "
                       "skins). Excludes GRP-area, resin/glue-weight, LVL-count mechanisms in "
                       "the same section — see docs/spikes/v4.24-bom-rule-engine-spike.md.")
