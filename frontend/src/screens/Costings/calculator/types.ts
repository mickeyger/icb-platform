// WO v4.37 §3.2 — types for the native React Cost Calculator (replaces the
// /mes/calculator iframe). Mirrors the EXISTING native backend contracts in
// backend/app/routers/calculator.py + trailers.py — no new endpoints.

export interface TrailerType {
  id: number
  name: string
  description?: string | null
  default_length?: number | null
  default_width?: number | null
  default_height?: number | null
  markup_percentage?: number | null
  /** configurator-v2 trailers use the heavier gated UI — MVP renders them flat
   *  (the backend still gates server-side from the inputs we send). */
  configurator_v2?: boolean
}

/** One BOM row from GET /api/trailers/{id}/bom — the source for the whole form. */
export interface BomRow {
  id: number
  material_id: number
  material_name: string
  sap_code?: string | null
  unit?: string | null
  category?: string | null
  bom_section?: string | null
  bom_section_id?: number | null
  sort_order?: number | null
  price?: number | null
  unit_price_override?: number | null
  formula?: string | null
  waste_pct?: number | null
  // Body-option flags (drive the toggles + insulation panels).
  is_body_option: boolean
  body_option_group?: string | null
  body_option_subgroup?: string | null
  body_option_default?: boolean
  selection_mode?: 'always' | 'single' | 'multi' | null
  // Insulation thickness in metres (EPS/PU panels), or null.
  variable_value?: number | null
}

export interface Dimensions {
  length: number
  width: number
  height: number
  floor_thickness: number
  panel_thickness: number
  insulation_thickness: number
  num_axles: number
  num_doors: number
}

/** Body-option selection map: BOM row id (string) → selected. */
export type BodyOptionSelections = Record<string, boolean>

export interface CalcRequest {
  trailer_type_id: number
  dimensions: Dimensions
  profit_margin: number
  overrides?: Record<string, number>
  override_reasons?: Record<string, string>
  chassis?: { enabled: boolean }
  body_option_selections?: BodyOptionSelections
  body_variable_overrides?: Record<string, number>   // material_name → insulation thickness (m)
  excluded_categories?: string[]
  user_excluded_bom_ids?: number[]
  optional_sections_enabled?: number[]
  ratio_value?: number | null
  ratio_label?: string | null
  discount_kind?: 'percent' | 'amount' | null
  discount_input?: number | null
}

export interface CalcItem {
  category: string
  bom_id: number
  bom_section_id?: number | null
  section_is_optional?: boolean
  material: string
  material_code?: string
  unit?: string
  formula?: string
  quantity: number
  unit_price: number
  waste_pct?: number
  line_cost: number
  section_multiplier?: number
  formula_error?: boolean
  excluded?: boolean
  excluded_reason?: string | null
}

export interface CalcResult {
  items: CalcItem[]
  category_totals: Record<string, number>
  grand_total: number
  cost_per_sqm?: number
  geometry?: Record<string, number>
  materials_total?: number
  profit_amount?: number
  profit_margin?: number
  selling_price?: number
  ratio_value?: number | null
  ratio_label?: string | null
  ratio_amount?: number
  discount_kind?: 'percent' | 'amount' | null
  discount_input?: number | null
  discount_amount?: number
  net_total?: number
  trailer_name?: string
  // version: WO v4.37 D-2 — backend stores 1-based; the React layer maps the
  // DISPLAY to original (no badge) → ver1 → ver2 (see revisionLabel()).
  version?: number | null
  // /api/approve response extras
  record_id?: number
  quote_number?: string | null
  customer_name?: string | null
  // GET /api/calculations/{id} optimistic-lock token (WO v4.37 §3.1 D-4)
  etag?: string
}

export interface CustomerLite {
  id: number
  bp_code?: string | null
  name: string
  is_dealer?: boolean
}

export interface DuplicateRecord {
  id: number
  version: number
  trailer: string
  saved_at: string
  quote_number: string | null
}

export interface DuplicateCheck {
  has_duplicate: boolean
  count: number
  next_version: number
  max_version?: number
  parent_quote_number?: string | null
  records?: DuplicateRecord[]
}

export interface ApproveExtras {
  customer_id: number | null
  version_action: 'replace' | 'new_version' | 'overwrite' | null
  next_version?: number
  reuse_quote_number?: boolean
  edit_record_id?: number | null
  is_repair?: boolean
  /** WO v4.37 §3.1 D-4 — the etag the editor loaded; backend 412s on mismatch. */
  base_etag?: string
}

// ── WO v4.37 D-2 — version DISPLAY mapping (backend stays 1-based) ─────────────
// First costing = no badge ("Original"); revisions = ver1, ver2 … Overwrite keeps
// the current version. Read with ?? (never ||) so a genuine 0 is never coerced.
export function revisionLabel(version: number | null | undefined): string {
  const v = version ?? 1
  return v > 1 ? `ver${v - 1}` : ''
}
