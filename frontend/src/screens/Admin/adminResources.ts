/** WO v4.26 §3.6 — config for the 4 admin CRUD sub-screens (driven by AdminCrudTable). */
export type FieldType = 'text' | 'number' | 'bool' | 'textarea' | 'date'

export interface FieldDef {
  name: string
  label: string
  type?: FieldType
  required?: boolean
  default?: string | number | boolean
  validateFormula?: boolean   // formula_expression — live parse-check via the backend
  oitmAutocomplete?: boolean  // sap_code — typeahead from /api/admin/oitm-search
}

export interface ResourceConfig {
  key: string
  title: string
  basePath: string                          // e.g. /api/admin/bom-rules
  columns: { key: string; label: string }[] // table display columns
  fields: FieldDef[]                          // create/edit form fields
  custom?: boolean                            // WO v4.33 — rendered by a dedicated component, not AdminCrudTable
}

export const ADMIN_RESOURCES: Record<string, ResourceConfig> = {
  'spec-options': {
    key: 'spec-options',
    title: 'Spec options (DDM dropdowns)',
    basePath: '/api/admin/bom-spec-options',
    columns: [
      { key: 'spec_field_type', label: 'Field' }, { key: 'body_type', label: 'Body' },
      { key: 'option_label', label: 'Label' }, { key: 'spec_value', label: 'Value' },
      { key: 'sap_code', label: 'SAP code' }, { key: 'active', label: 'Active' },
      { key: 'priority', label: 'Prio' },
    ],
    fields: [
      { name: 'spec_field_type', label: 'Spec field type', required: true },
      { name: 'body_type', label: 'Body type', default: '*' },
      { name: 'section', label: 'Section', default: 'Vacuum Materials' },
      { name: 'option_label', label: 'Option label', required: true },
      { name: 'spec_value', label: 'Spec value', required: true },
      { name: 'sap_code', label: 'SAP code', oitmAutocomplete: true },
      { name: 'is_default', label: 'Default', type: 'bool', default: false },
      { name: 'priority', label: 'Priority', type: 'number', default: 100 },
      { name: 'active', label: 'Active', type: 'bool', default: true },
      { name: 'notes', label: 'Notes', type: 'textarea' },
    ],
  },
  rules: {
    key: 'rules',
    title: 'BOM rules',
    basePath: '/api/admin/bom-rules',
    columns: [
      { key: 'body_type', label: 'Body' }, { key: 'section', label: 'Section' },
      { key: 'panel', label: 'Panel' }, { key: 'output_field', label: 'Output' },
      { key: 'formula_expression', label: 'Formula' }, { key: 'priority', label: 'Prio' },
    ],
    fields: [
      { name: 'body_type', label: 'Body type', required: true },
      { name: 'section', label: 'Section', default: 'Vacuum Materials' },
      { name: 'panel', label: 'Panel', required: true },
      { name: 'output_field', label: 'Output field', default: 'qty' },
      { name: 'formula_expression', label: 'Formula', type: 'textarea', required: true, validateFormula: true },
      { name: 'priority', label: 'Priority', type: 'number', default: 100 },
      { name: 'notes', label: 'Notes', type: 'textarea' },
    ],
  },
  lookups: {
    key: 'lookups',
    title: 'Rule lookups (spec → SAP code)',
    basePath: '/api/admin/bom-rule-lookups',
    columns: [
      { key: 'body_type', label: 'Body' }, { key: 'section', label: 'Section' },
      { key: 'lookup_type', label: 'Type' }, { key: 'lookup_key', label: 'Key' },
      { key: 'lookup_value', label: 'Value' },
    ],
    fields: [
      { name: 'body_type', label: 'Body type', required: true },
      { name: 'section', label: 'Section', default: 'Vacuum Materials' },
      { name: 'lookup_type', label: 'Lookup type', default: 'spec_to_sap_code' },
      { name: 'lookup_key', label: 'Lookup key', required: true },
      { name: 'lookup_value', label: 'Lookup value (SAP code)', required: true, oitmAutocomplete: true },
      { name: 'notes', label: 'Notes', type: 'textarea' },
    ],
  },
  'price-overrides': {
    key: 'price-overrides',
    title: 'Price overrides',
    basePath: '/api/admin/material-price-overrides',
    columns: [
      { key: 'sap_code', label: 'SAP code' }, { key: 'override_price', label: 'Override' },
      { key: 'valid_from', label: 'From' }, { key: 'valid_to', label: 'To' },
      { key: 'reason', label: 'Reason' },
    ],
    fields: [
      { name: 'sap_code', label: 'SAP code', required: true, oitmAutocomplete: true },
      { name: 'override_price', label: 'Override price', type: 'number', required: true },
      { name: 'valid_from', label: 'Valid from', type: 'date' },
      { name: 'valid_to', label: 'Valid to', type: 'date' },
      { name: 'reason', label: 'Reason', type: 'textarea' },
    ],
  },
  // WO v4.33 §3.3 — Nadie's Pre-Job Card template library (nested section editor, so a
  // dedicated screen renders instead of the generic AdminCrudTable; see PrejobTemplatesAdmin).
  'prejob-templates': {
    key: 'prejob-templates',
    title: 'Pre-Job templates',
    basePath: '/api/admin/prejob-templates',
    columns: [],
    fields: [],
    custom: true,
  },
}

export const ADMIN_ORDER = ['spec-options', 'rules', 'lookups', 'price-overrides', 'prejob-templates']
