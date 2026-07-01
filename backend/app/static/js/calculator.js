let lastRecordId = null;
let lastResult = null;
let lastCalcPayload = null;  // stored for approve

// ── AI Help action handlers (registered for the chat widget) ───────────────
// The help widget calls window.helpActionHandlers[<type>] when the user clicks
// an AI-suggested action button. We register highlight_bom_lines here because
// it needs page-specific DOM knowledge (the BOM result row markup).
window.helpActionHandlers = window.helpActionHandlers || {};
window.helpActionHandlers.highlight_bom_lines = function(params) {
  const area = document.getElementById('bom-area');
  if (!area) return false;
  const norm = s => String(s || '').toLowerCase()
    .replace(/[^a-z0-9 ]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  const wantMats = (params.materials || []).map(norm).filter(Boolean);
  const wantCats = (params.categories || []).map(norm).filter(Boolean);
  if (!wantMats.length && !wantCats.length) return false;

  // The calculator has TWO render paths with different markup:
  //   1. Cost Calculator results table (after a calc runs):
  //      tr.calc-grp-row[data-material-name], grouped by
  //      tr.calc-grp-hdr[data-cat-name][data-cat-id], rows tagged
  //      data-cat-group=<gid>.
  //   2. Admin Body Templates / BOM editor list:
  //      .assembly-item[data-material-name] inside .parts-group >
  //      .parts-group-body, with title .parts-group-title.
  // We query both so highlight works on whichever view is currently rendered.

  // Collect rows from both layouts
  const calcRows  = Array.from(area.querySelectorAll('tr.calc-grp-row[data-material-name]'));
  const adminRows = Array.from(area.querySelectorAll('.assembly-item[data-material-name]'));
  const allRows = calcRows.concat(adminRows);
  const availableMaterials = allRows.map(r => norm(r.getAttribute('data-material-name')));

  // Collect categories: pair (normalised name → list of rows it covers).
  // Calculator: header row has data-cat-name + data-cat-id, body rows share
  // data-cat-group=<id>.
  const catBuckets = [];  // [{ name, rows: [] }]
  area.querySelectorAll('tr.calc-grp-hdr[data-cat-name][data-cat-id]').forEach(hdr => {
    const name = norm(hdr.getAttribute('data-cat-name'));
    const gid  = hdr.getAttribute('data-cat-id');
    if (!name || !gid) return;
    const rows = Array.from(area.querySelectorAll('tr.calc-grp-row[data-cat-group="' + CSS.escape(gid) + '"]'));
    catBuckets.push({ name, rows });
  });
  area.querySelectorAll('.parts-group').forEach(g => {
    const name = norm(g.querySelector('.parts-group-title')?.textContent);
    if (!name) return;
    const rows = Array.from(g.querySelectorAll('.assembly-item'));
    catBuckets.push({ name, rows });
  });
  const availableCats = catBuckets.map(b => b.name);

  const matched = new Set();

  if (wantMats.length) {
    allRows.forEach((row, i) => {
      const name = availableMaterials[i];
      if (!name) return;
      if (wantMats.some(w => {
        if (!w) return false;
        if (name === w || name.includes(w) || w.includes(name)) return true;
        const a = new Set(name.split(' ').filter(t => t.length >= 3));
        const b = (w.split(' ').filter(t => t.length >= 3));
        return b.filter(t => a.has(t)).length >= 2;
      })) matched.add(row);
    });
  }
  if (wantCats.length) {
    catBuckets.forEach(bucket => {
      if (wantCats.some(w => w && (bucket.name.includes(w) || w.includes(bucket.name)))) {
        bucket.rows.forEach(r => matched.add(r));
      }
    });
  }

  if (!matched.size) {
    try {
      console.warn('[helpActions] highlight_bom_lines: no matches', {
        wantedMaterials: wantMats, wantedCategories: wantCats,
        availableMaterials, availableCategories: availableCats,
      });
    } catch (_) {}
    if (window.toast) {
      if (!allRows.length) toast('No BOM is loaded yet — pick a body and run the calc, then click this again.', 'warn');
      else toast('Could not find those specific lines.', 'warn');
    }
    return true;
  }

  const matchedArr = Array.from(matched);
  // Expand any collapsed parent containers so the rows are actually visible.
  matchedArr.forEach(row => {
    const adminBody = row.closest && row.closest('.parts-group-body');
    if (adminBody && adminBody.style.display === 'none') adminBody.style.display = '';
    // Calc-side: rows may have inline style="display:none" when their header
    // is collapsed. Unhide and also flip the header chevron if needed.
    if (row.tagName === 'TR' && row.style.display === 'none') {
      row.style.display = '';
      const gid = row.getAttribute('data-cat-group');
      const hdr = gid ? area.querySelector('tr.calc-grp-hdr[data-cat-id="' + CSS.escape(gid) + '"]') : null;
      if (hdr) hdr.classList.remove('collapsed');
    }
  });
  matchedArr[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
  matchedArr.forEach(r => {
    r.classList.add('help-flash');
    setTimeout(() => r.classList.remove('help-flash'), 5100);
  });
  return true;
};

// ── AI Help context publishing ─────────────────────────────────────────────
// The Help chat widget reads window.helpContext on send so the assistant sees
// the actual live BOM (incl. unsaved drafts). Called from every place that
// updates lastResult.
function _publishHelpContext(result) {
  try {
    const sel = document.getElementById('trailer-select');
    const bodyName = sel ? (sel.selectedOptions[0]?.textContent || '').trim() : '';
    const prevBody = window.helpContext ? window.helpContext.body : null;
    window.helpContext = {
      page: 'calculator',
      body: bodyName || null,
      trailer_type_id: sel ? +sel.value || null : null,
      liveResult: result || null,
    };
    // Fire an event the AI audit panel listens for. `bodyChanged` lets it
    // decide whether to re-pick the sheet vs just re-run with the same one.
    try {
      window.dispatchEvent(new CustomEvent('helpcontext:updated', {
        detail: { body: bodyName || null, bodyChanged: (prevBody !== (bodyName || null)) },
      }));
    } catch (_) { /* CustomEvent unsupported — silent fallback */ }
  } catch (_) { /* never let this break the calculator */ }
}
let _singleSideMode = false; // admin-only: view one-side cost by clicking × N badge
let bomData = [];
// v2 trailers: cached configurator tree (groups + options + sections + flag
// groups) used to render the body-options panel as a tree instead of a flat
// list. Loaded once per trailer alongside the BOM; null on non-v2 trailers.
let configuratorTree = null;
// Tracks which trailer id we've already applied the configurator's persisted
// user state (cfg_user_state_<tid>) to. The override is a *seed* — applied
// once per trailer load. Re-rendering the tree (e.g. after a click) must NOT
// re-override, otherwise the user's clicks get clobbered back to the
// configurator's saved state on the next render and the tick boxes appear
// unresponsive.
let _cfgStateSeededForTrailer = null;
let _scrollToBomId = null;  // set before runCalc() to scroll to a specific BOM row after render
let lastBodyVars = {};        // {NAME_UPPER: value} — body variable values from last calculation
let lastFormulaLib = {};      // {name_lower: resolved_value} — formula library values
let lastGlobalVars = {};      // {Name: value} — global constants (e.g. Waste)
let trailerDefaults = {};
let allCustomers = [];
let calcTimer = null;
let priceOverrides = {};  // bomId (string) → { newPrice, originalPrice, materialId }
const OVERRIDE_SESSION_KEY = 'bom_price_overrides';
// MIRROR-TO-MES: needs-review — edit-mode block (this comment + editCalculation/
// rebuildOverridesFromSaved/showEditBanner/cancelEdit/editSaveAction + the
// approveCosting & _doApprove edit branches). Port with calculator.html banner+modal.
// ── Edit mode: set when /calculator?edit=<id> loads a PENDING costing for
// re-editing. While these are set, the Save button asks the user to overwrite
// the original record or save a new revision instead of creating a fresh quote.
let editingRecordId    = null;
let editingVersion     = 1;
let editingQuoteNumber = null;
// While editing, pins the quote's body-variable values (insulation EPS/PU
// thicknesses, by material name) so the recompute reproduces the saved figures
// even if a global EPS/PU copy-on-switch changed the BOM since the quote saved.
let editBodyVarOverrides = null;
// Edit-replay (legacy records with no UI snapshot): forces the recompute to
// reproduce the saved result exactly — include only the saved-included rows with
// their saved formulas + prices. { userExcluded:[], formulaOverrides:{},
// savedPrices:{}, optionalEnabled:[] }. Null = normal/snapshot editing.
let editReplay = null;
let bodyOptionSelections = {};  // bomId (string) → boolean
let drdSrdEnabled = {};         // groupName → boolean; master ON/OFF toggle for DRD / SRD
// Settings-page draft flag states (v2 trailers only).
// keyed by flagBindingName/label → bool. Populated from localStorage draft
// visual-body-configurator-ui:{tid} when the trailer has a settings draft.
let draftFlagState = {};
let _draftFlagStateTrailer = null;  // which tid draftFlagState is seeded for
// Selected category-radio per parent folder. Used to track masterless category
// radios (those whose section has no resolvable owner master on this trailer
// — e.g. a section that exists in the global pool but no body-option master
// references it locally). For those, server-side gating is impossible by ID;
// we fall back to excluded_categories (section-name based) and use this map
// to know which sibling is the "selected" one in each radio group.
let draftCategoryRadioState = {};
let draftMasterlessCatState = {}; // sourceCategoryKey → boolean for masterless tickbox categories
let draftFolderState = {};   // nodeId → boolean for radio/tickbox folders
const _DRDSR_TOGGLE_GROUPS = ['DRD', 'SRD'];

function _boSelKey(tid)    { return `body_opt_sel_${tid}`; }
function _drdSrdKey(tid)   { return `drd_srd_${tid}`; }

function saveBodyOptSel() {
  const tid = document.getElementById('trailer-select')?.value;
  if (!tid || !Object.keys(bodyOptionSelections).length) return;
  try { localStorage.setItem(_boSelKey(tid), JSON.stringify(bodyOptionSelections)); } catch(_) {}
}

function loadBodyOptSel(tid) {
  try {
    const raw = localStorage.getItem(_boSelKey(tid));
    if (!raw) return;
    const saved = JSON.parse(raw);
    // Pre-populate bodyOptionSelections; renderBodyOptions will only seed items not already present
    Object.assign(bodyOptionSelections, saved);
  } catch(_) {}
}

function saveDrdSrdEnabled() {
  const tid = document.getElementById('trailer-select')?.value;
  if (!tid) return;
  try { localStorage.setItem(_drdSrdKey(tid), JSON.stringify(drdSrdEnabled)); } catch(_) {}
}

function loadDrdSrdEnabled(tid) {
  try {
    const raw = localStorage.getItem(_drdSrdKey(tid));
    if (raw) Object.assign(drdSrdEnabled, JSON.parse(raw));
  } catch(_) {}
}

// ── Last-session persistence ───────────────────────────────────────────────────
// Saves the full costing state so that returning to /calculator restores where
// the user left off, regardless of which page they visited in between.

const LAST_SESSION_KEY = 'last_costing_session';

function saveLastSession() {
  const tid = document.getElementById('trailer-select')?.value;
  if (!tid) return;

  const _v = id => document.getElementById(id)?.value ?? '';
  const chOn = document.getElementById('f-chassis-on')?.checked || false;

  try {
    localStorage.setItem(LAST_SESSION_KEY, JSON.stringify({
      trailer_type_id: tid,
      dims: {
        length:               +_v('f-length')      || 0,
        width:                +_v('f-width')       || 0,
        height:               +_v('f-height')      || 0,
        floor_thickness:      +_v('f-floor-thick') || 0,
        panel_thickness:      +_v('f-panel-thick') || 0,
        insulation_thickness: +_v('f-insul-thick') || 0,
        num_axles:            +_v('f-axles')       || 0,
        num_doors:            +_v('f-doors')       || 0,
      },
      margin:      +_v('f-margin') || 0,
      ratio:       _v('f-ratio'),
      customer_id: _v('cust-select') || null,
      chassis_on:  chOn,
      chassis: chOn ? {
        length:        +_v('f-ch-length')     || 0,
        axle_count:    +_v('f-ch-axles')      || 0,
        lift_count:    +_v('f-ch-lift-count') || 0,
        tyre_style:    _v('f-ch-tyre-style')  || 'dual',
        suspension_id: +_v('f-ch-suspension') || null,
        lift_type_id:  +_v('f-ch-lift-type')  || null,
        brake_id:      +_v('f-ch-brake')      || null,
        tyre_id:       +_v('f-ch-tyre')       || null,
        rim_id:        +_v('f-ch-rim')        || null,
      } : null,
      body_options: { ...bodyOptionSelections },
      drd_srd:     { ...drdSrdEnabled },
      discount_kind:  discountKind,
      discount_input: discountInput,
    }));
  } catch(_) {}
}

async function restoreLastSession() {
  let session;
  try {
    const raw = localStorage.getItem(LAST_SESSION_KEY);
    if (!raw) return false;
    session = JSON.parse(raw);
  } catch(_) { return false; }

  if (!session?.trailer_type_id) return false;

  const sel = document.getElementById('trailer-select');
  if (!sel.querySelector(`option[value="${session.trailer_type_id}"]`)) return false;

  // Pre-populate selections before loadBOM so preserveInputs:true keeps them.
  // v2 trailers always start from configurator defaults — skip restoring stale
  // session body-option selections that may reference masters now hidden from
  // the panel (e.g. legacy "BODY OPTIONS" / DRD / SRD groups). Without this,
  // a stale `bodyOptionSelections["<legacy_master_id>"] = true` would keep
  // bom_conditions firing and items appearing that the configurator excludes.
  const _isV2 = !!(trailerDefaults[session.trailer_type_id] && trailerDefaults[session.trailer_type_id].configurator_v2);
  if (!_isV2) {
    if (session.body_options) Object.assign(bodyOptionSelections, session.body_options);
    if (session.drd_srd)      Object.assign(drdSrdEnabled,        session.drd_srd);
  }

  sel.value = session.trailer_type_id;
  await loadBOM({ preserveInputs: true });

  // Restore dimension + config fields
  const _set = (id, val) => {
    const el = document.getElementById(id);
    if (el && val != null && val !== 0) el.value = val;
  };
  const d = session.dims || {};
  _set('f-length',      d.length);
  _set('f-width',       d.width);
  _set('f-height',      d.height);
  _set('f-floor-thick', d.floor_thickness);
  _set('f-panel-thick', d.panel_thickness);
  _set('f-insul-thick', d.insulation_thickness);
  _set('f-axles',       d.num_axles);
  _set('f-doors',       d.num_doors);
  _set('f-margin',      session.margin);
  updateGeo();

  // Restore ratio (loadBOM already populated the options)
  if (session.ratio) {
    const ratioSel = document.getElementById('f-ratio');
    if (ratioSel?.querySelector(`option[value="${session.ratio}"]`))
      ratioSel.value = session.ratio;
  }

  // Restore discount (renderSummary reads these globals on the runCalc below)
  discountKind  = (session.discount_kind === 'percent' || session.discount_kind === 'amount')
                  ? session.discount_kind : null;
  discountInput = discountKind ? (+session.discount_input || 0) : 0;

  // Restore customer
  if (session.customer_id) setCustomer(session.customer_id);

  // Restore chassis if it was enabled
  if (session.chassis_on && session.chassis) {
    const chOn = document.getElementById('f-chassis-on');
    const wrap  = document.getElementById('chassis-fields');
    if (chOn) chOn.checked = true;
    if (wrap) wrap.style.display = '';
    await _loadChassisOptions();
    const ch = session.chassis;
    _set('f-ch-length',     ch.length);
    _set('f-ch-axles',      ch.axle_count);
    _set('f-ch-tyre-style', ch.tyre_style);
    _refreshChassisDropdowns();
    _set('f-ch-suspension', ch.suspension_id);
    _set('f-ch-brake',      ch.brake_id);
    _set('f-ch-tyre',       ch.tyre_id);
    _set('f-ch-rim',        ch.rim_id);
    _set('f-ch-lift-type',  ch.lift_type_id);
    _set('f-ch-lift-count', ch.lift_count);
    _updateChassisCounts();
    if (ch.length) {
      const chLenEl = document.getElementById('f-ch-length');
      if (chLenEl) chLenEl.dataset.userTouched = '1';
    }
  }

  await runCalc();
  return true;
}

// Master ON/OFF toggle for a DRD/SRD group — mutually exclusive with each other
async function onDrdSrdToggle(grp, checked) {
  // Door active before this change (for carrying the rear-door thickness across).
  const prevGrp = _DRDSR_TOGGLE_GROUPS.find(g => drdSrdEnabled[g]);
  if (checked) {
    _DRDSR_TOGGLE_GROUPS.forEach(g => {
      drdSrdEnabled[g] = (g === grp);
      if (g !== grp) _clearDrdSrdSelections(g);  // deactivate the other group
    });
    // Carry the rear-door insulation thickness onto the newly-selected door,
    // zero the other. Default 0.06 m when nothing is set yet.
    await _carryRearDoorThickness(grp, (prevGrp && prevGrp !== grp) ? prevGrp : null);
  } else {
    drdSrdEnabled[grp] = false;
    _clearDrdSrdSelections(grp);
    // No rear door selected → zero this door's insulation so it neither warns
    // nor leaks a deduction into the {SRD …} formulas.
    const pair = _doorInsulationPair(grp);
    if (pair) {
      for (const row of [pair.eps, pair.pu]) {
        if ((Number(row.variable_value) || 0) !== 0) {
          row.variable_value = 0;
          try { await api('PUT', `/api/bom/${row.id}`, { variable_value: 0 }); } catch (e) { /* non-fatal */ }
        }
      }
    }
  }
  saveDrdSrdEnabled();
  renderBodyOptions(bomData);
  refreshBomDisplay();
  scheduleCalc();
}

// Seed drdSrdEnabled from body_option_default only when no localStorage state was found.
// Called once after BOM loads; groups already in drdSrdEnabled (from localStorage) are skipped.
function _seedDrdSrdFromDefaults(items) {
  _DRDSR_TOGGLE_GROUPS.forEach(grp => {
    if (grp in drdSrdEnabled) return;  // localStorage value takes precedence
    drdSrdEnabled[grp] = items.some(
      it => it.is_body_option && it.body_option_group === grp && it.body_option_default
    );
  });
  // Enforce mutual exclusion: if both defaulted to ON, keep only the first
  const bothOn = _DRDSR_TOGGLE_GROUPS.filter(g => drdSrdEnabled[g]);
  if (bothOn.length > 1) {
    bothOn.slice(1).forEach(g => { drdSrdEnabled[g] = false; });
  }
}

function _clearDrdSrdSelections(grp) {
  bomData.forEach(it => {
    if (it.is_body_option && it.body_option_group === grp)
      bodyOptionSelections[String(it.id)] = false;
  });
}

// ── Body-option sub-group helpers ─────────────────────────────────────────────
// A "sub-group" is the body_option_subgroup field on each BOM item.
// Items sharing the same group+subgroup are treated as a radio set (pick one).
// Items with no subgroup, or alone in their subgroup, are independent toggles.

function _boSubgroupKey(it) {
  return it.body_option_group + '|' + (it.body_option_subgroup || '');
}

// --- Insulation EPS/PU pairing -------------------------------------------
// Each insulation location (DRD, FRONT, …) is an EPS/PU pair: two body-option
// masters sharing body_option_group + body_option_subgroup, one named …EPS,
// the other …PU. Each carries a thickness in variable_value.

// Given a body-option master id, return { eps, pu } when its subgroup contains
// exactly one EPS row and one PU row, else null. Identity is structural
// (group+subgroup + name), so no hardcoded location names.
function _insulationPairFor(masterId) {
  const row = bomData.find(r => String(r.id) === String(masterId));
  if (!row || !row.is_body_option) return null;
  const key = _boSubgroupKey(row);
  const sibs = bomData.filter(r => r.is_body_option && _boSubgroupKey(r) === key);
  if (sibs.length !== 2) return null;
  const eps = sibs.find(r => (r.material_name || '').toUpperCase().includes('EPS'));
  const pu  = sibs.find(r => (r.material_name || '').toUpperCase().includes('PU'));
  if (!eps || !pu || eps.id === pu.id) return null;
  return { eps, pu };
}

// ── Rear-door (DRD/SRD) insulation carry ─────────────────────────────────
// A body is quoted as EITHER double rear doors (DRD) OR a single rear door
// (SRD), never both. There is one rear-door insulation thickness that follows
// the user's door-type choice: only the selected door carries it; the other
// door is zeroed. All BOM skin formulas read {SRD EPS}/{SRD PU} (none read
// {DRD …}), so a DRD quote (SRD = 0) deducts no rear-door insulation while an
// SRD quote does — this is the intended costing.
const DEFAULT_REAR_DOOR_THICKNESS_M = 0.06;

// The EPS/PU insulation pair under a DRD/SRD door group, or null.
function _doorInsulationPair(grp) {
  const sibs = bomData.filter(r => r.is_body_option
    && r.body_option_group === grp
    && (r.body_option_subgroup || '').toUpperCase() === 'INSULATION'
    && /EPS|PU/i.test(r.material_name || ''));
  const eps = sibs.find(r => /EPS/i.test(r.material_name || ''));
  const pu  = sibs.find(r => /PU/i.test(r.material_name || '') && !/EPS/i.test(r.material_name || ''));
  return (eps && pu) ? { eps, pu } : null;
}

// The active thickness + side carried by a pair, or null when both are zero.
function _doorActiveCell(pair) {
  if (!pair) return null;
  const e = Number(pair.eps.variable_value) || 0;
  const u = Number(pair.pu.variable_value)  || 0;
  if (e > 0) return { T: e, side: 'EPS' };
  if (u > 0) return { T: u, side: 'PU' };
  return null;
}

// Carry the rear-door thickness onto the newly-selected door's matching side
// and zero the other door entirely. Thickness + side follow the previous door
// (so EPS stays EPS, PU stays PU across the switch); default 0.06 m when no
// value exists yet. Persists each change to the body template via PUT /api/bom,
// mirroring the EPS/PU copy-on-switch flow.
async function _carryRearDoorThickness(newGrp, oldGrp) {
  const newPair = _doorInsulationPair(newGrp);
  if (!newPair) return;                       // door has no insulation pair
  const oldPair = oldGrp ? _doorInsulationPair(oldGrp) : null;
  const active = _doorActiveCell(oldPair) || _doorActiveCell(newPair)
              || { T: DEFAULT_REAR_DOOR_THICKNESS_M, side: 'EPS' };
  const { T, side } = active;
  const writes = [];
  const setVal = (row, v) => {
    v = Number(v) || 0;
    if ((Number(row.variable_value) || 0) !== v) { row.variable_value = v; writes.push([row.id, v]); }
  };
  setVal(newPair.eps, side === 'EPS' ? T : 0);
  setVal(newPair.pu,  side === 'PU'  ? T : 0);
  bodyOptionSelections[String(newPair.eps.id)] = (side === 'EPS');
  bodyOptionSelections[String(newPair.pu.id)]  = (side === 'PU');
  if (oldPair) {
    setVal(oldPair.eps, 0);
    setVal(oldPair.pu,  0);
    bodyOptionSelections[String(oldPair.eps.id)] = false;
    bodyOptionSelections[String(oldPair.pu.id)]  = false;
  }
  for (const [id, v] of writes) {
    try { await api('PUT', `/api/bom/${id}`, { variable_value: v }); } catch (e) { /* non-fatal */ }
  }
  if (writes.length) {
    try { toast(`Rear-door insulation → ${side} ${T.toFixed(3)} m on ${newGrp}  ·  Body Template updated`, 'success'); } catch (e) {}
  }
}

// Map a door-type SELECTOR's name/label to its rear-door group. Matches the
// door-type radio ("DRD"/"SRD") or the folder label ("DOUBLE/SINGLE DOORS"),
// but NOT the insulation rows ("DRD EPS", "SRD PU") or door fittings.
function _doorFromSelectorName(name) {
  const n = (name || '').toUpperCase().trim();
  if (n.includes('DOUBLE')) return 'DRD';
  if (n.includes('SINGLE')) return 'SRD';
  if (n === 'DRD') return 'DRD';
  if (n === 'SRD') return 'SRD';
  return null;
}

// Which rear door is currently selected, independent of configurator layout:
// prefer the checked DOOR TYPE selector (category-radio bodies keep both DRD/SRD
// gates enabled), else fall back to a solely-enabled DRD/SRD gate (folder bodies).
function _selectedRearDoor() {
  for (const it of bomData) {
    if (!it.is_body_option) continue;
    const d = _doorFromSelectorName(it.material_name);
    if (d && bodyOptionSelections[String(it.id)]) return d;
  }
  const on = _DRDSR_TOGGLE_GROUPS.filter(g => drdSrdEnabled[g]);
  return on.length === 1 ? on[0] : null;
}

// Copy-on-switch: when an insulation radio is newly selected, carry the
// sibling's thickness onto the selected row and zero the sibling. Persists
// both to the body template via PUT /api/bom (same flow as manual bv-edit).
async function _applyInsulationCopyZero(selectedMasterId) {
  const pair = _insulationPairFor(selectedMasterId);
  if (!pair) return;
  // Only thickness-bearing pairs participate.
  if (pair.eps.variable_value == null && pair.pu.variable_value == null) return;
  const selected = String(pair.eps.id) === String(selectedMasterId) ? pair.eps : pair.pu;
  const other    = selected === pair.eps ? pair.pu : pair.eps;
  const carry = Number(other.variable_value) || 0;
  if (carry <= 0) return; // nothing to carry over — both-zero guard will flag it
  selected.variable_value = carry;
  other.variable_value = 0;
  try {
    await api('PUT', `/api/bom/${selected.id}`, { variable_value: carry });
    await api('PUT', `/api/bom/${other.id}`,    { variable_value: 0 });
    toast(`{${selected.material_name}} → ${carry.toFixed(3)} m  ·  Body Template updated`, 'success');
  } catch (e) {
    toast('Save failed: ' + e.message, 'error');
  }
}

// Both-zero guard: turn both bv-edit value spans red and show an inline
// warning when an insulation pair has zero thickness on both sides. DOM-scan
// based, so it is idempotent and re-applies correctly after any re-render.
function validateInsulationPairs() {
  const list = document.getElementById('body-options-list');
  if (!list) return;
  // Clear prior state.
  list.querySelectorAll('.ins-warn').forEach(w => w.remove());
  list.querySelectorAll('span.bv-edit.ins-zero-bad').forEach(s => {
    s.classList.remove('ins-zero-bad');
    s.style.color = '#58a6ff';
    s.style.borderBottom = '1px dotted #388bfd';
  });
  // Group rendered bv-edit spans by their row's insulation subgroup.
  const groups = {};
  list.querySelectorAll('span.bv-edit[data-bom-id]').forEach(span => {
    const row = bomData.find(r => String(r.id) === String(span.dataset.bomId));
    if (!row || !row.is_body_option) return;
    const key = _boSubgroupKey(row);
    (groups[key] = groups[key] || []).push(span);
  });
  Object.values(groups).forEach(spans => {
    if (spans.length !== 2) return;
    const pair = _insulationPairFor(spans[0].dataset.bomId);
    if (!pair) return;
    // Suppress the both-zero warning for a DRD/SRD door type that isn't
    // selected — the non-quoted rear door is legitimately 0/0 (only the chosen
    // door carries thickness). The selected door is auto-populated, so it
    // won't be 0/0 anyway.
    const _doorGrp = pair.eps.body_option_group;
    if (_DRDSR_TOGGLE_GROUPS.includes(_doorGrp)) {
      const _selDoor = _selectedRearDoor();
      if (_selDoor && _doorGrp !== _selDoor) return;
    }
    const bothZero = (Number(pair.eps.variable_value) || 0) <= 0
                  && (Number(pair.pu.variable_value)  || 0) <= 0;
    if (!bothZero) return;
    spans.forEach(s => {
      s.classList.add('ins-zero-bad');
      s.style.color = '#ff6b6b';
      s.style.borderBottom = '1px dotted #ff6b6b';
    });
    const lastSpan = spans[spans.length - 1];
    const label = lastSpan.closest('label');
    const anchor = label || lastSpan;
    const warn = document.createElement('div');
    warn.className = 'ins-warn';
    warn.innerHTML = `<span style="font-size:11px">⚠</span>&nbsp;<span>Both ${escHtml(pair.eps.material_name)} and ${escHtml(pair.pu.material_name)} can't be zero</span>`;
    warn.style.cssText = 'margin:1px 0 6px 24px;font-size:9px;font-weight:700;color:#ff6b6b;letter-spacing:.5px;background:#2a0d0d;border:1px solid #b03030;border-radius:3px;padding:2px 6px;white-space:nowrap;display:inline-flex;align-items:center;gap:2px';
    anchor.insertAdjacentElement('afterend', warn);
  });
}

// Called when a radio-style sub-group item is clicked
async function onBodyOptRadioChange(bid, groupKey) {
  // Deselect all siblings in the same sub-group, select the clicked one
  bomData.forEach(it => {
    if (it.is_body_option && _boSubgroupKey(it) === groupKey) {
      bodyOptionSelections[String(it.id)] = false;
    }
  });
  bodyOptionSelections[bid] = true;

  const changedItem = bomData.find(it => String(it.id) === bid);

  // If this is an EPS/PU insulation switch, carry the thickness onto the
  // selected side then offer to apply the type switch globally.
  if (changedItem && changedItem.body_option_subgroup === 'INSULATION') {
    const nameUp = (changedItem.material_name || '').toUpperCase();
    const isPU  = nameUp.includes('PU');
    const isEPS = nameUp.includes('EPS');
    if (isPU || isEPS) {
      const targetType = isPU ? 'PU' : 'EPS';
      const otherType  = isPU ? 'EPS' : 'PU';
      await _applyInsulationCopyZero(bid);
      _showInsulationSwitchModal(otherType, targetType);
      return;   // modal's Yes/No will complete the save + render
    }
  }

  saveBodyOptSel();
  renderBodyOptions(bomData);
  refreshBomDisplay();
  scheduleCalc();
}

function _showInsulationSwitchModal(fromType, toType) {
  const icon = toType === 'PU' ? '🔵' : '🟡';
  document.getElementById('insulation-switch-title').innerHTML =
    `${icon} Switch Insulation to ${toType}`;
  document.getElementById('insulation-switch-body').textContent =
    `Switch ALL insulation categories from ${fromType} to ${toType}?`;

  const yesBtn = document.getElementById('insulation-switch-yes');
  // Clone to remove previous listener
  const fresh = yesBtn.cloneNode(true);
  yesBtn.parentNode.replaceChild(fresh, yesBtn);
  fresh.addEventListener('click', async () => {
    closeModal('modal-insulation-switch');
    const selectedToType = []; // master ids now selected (the toType side of each pair)
    bomData.forEach(it => {
      if (!it.is_body_option || it.body_option_subgroup !== 'INSULATION') return;
      const n = (it.material_name || '').toUpperCase();
      if (!n.includes('EPS') && !n.includes('PU')) return;
      const on = n.includes(toType);
      bodyOptionSelections[String(it.id)] = on;
      if (on) selectedToType.push(it.id);
    });
    saveBodyOptSel();
    // Carry each location's thickness onto its newly-selected side.
    for (const mid of selectedToType) await _applyInsulationCopyZero(mid);
    renderBodyOptions(bomData);
    refreshBomDisplay();
    scheduleCalc();
  });

  // No button / close just saves what was already selected
  const noBtn = document.querySelector('#modal-insulation-switch .btn-outline');
  const freshNo = noBtn.cloneNode(true);
  noBtn.parentNode.replaceChild(freshNo, noBtn);
  freshNo.addEventListener('click', () => {
    closeModal('modal-insulation-switch');
    saveBodyOptSel();
    renderBodyOptions(bomData);
    refreshBomDisplay();
    scheduleCalc();
  });

  openModal('modal-insulation-switch');
}

// Called when a standalone toggle item is clicked
async function editBodyVariable(span) {
  const bomId = span.dataset.bomId;
  const name  = span.dataset.name;
  if (!bomId) return;
  const current = (span.textContent.match(/[-0-9.]+/) || [''])[0];
  // Replace the span with an inline input
  const inp = document.createElement('input');
  inp.type = 'number';
  inp.step = '0.001';
  inp.min  = '0';
  inp.value = current;
  inp.style.cssText = 'width:60px;font-size:10px;padding:1px 4px;background:#0d2140;color:#58a6ff;border:1px solid #388bfd;border-radius:3px;font-family:var(--font-mono)';
  inp.title = name;
  span.replaceWith(inp);
  inp.focus();
  inp.select();

  let restored = false;
  const restore = (newDisplay, newVal) => {
    if (restored) return; restored = true;
    const fresh = document.createElement('span');
    fresh.className = 'bv-edit';
    fresh.dataset.bomId = bomId;
    fresh.dataset.name  = name;
    fresh.style.cssText = 'color:#58a6ff;font-size:10px;cursor:pointer;border-bottom:1px dotted #388bfd';
    fresh.title = `Click to edit — referenced in formulas as {${name}}`;
    fresh.onclick = e => { e.preventDefault(); e.stopPropagation(); editBodyVariable(fresh); };
    fresh.textContent = newDisplay;
    inp.replaceWith(fresh);
    // Update the cached BOM so subsequent renders/calcs use the new value
    if (newVal != null) {
      const r = (typeof bomData !== 'undefined' ? bomData : []).find(b => String(b.id) === String(bomId));
      if (r) r.variable_value = newVal;
    }
  };

  inp.addEventListener('keydown', e => {
    if (e.key === 'Enter') inp.blur();
    if (e.key === 'Escape') restore(`(${Number(current).toFixed(3)} m)`, null);
  });
  inp.addEventListener('blur', async () => {
    const v = parseFloat(inp.value);
    if (isNaN(v) || v < 0) { restore(`(${Number(current).toFixed(3)} m)`, null); return; }
    if (v === parseFloat(current)) { restore(`(${v.toFixed(3)} m)`, v); return; }
    try {
      await api('PUT', `/api/bom/${bomId}`, { variable_value: v });
      restore(`(${v.toFixed(3)} m)`, v);
      toast(`{${name}} → ${v.toFixed(3)} m  ·  Body Template updated`, 'success');
      // Show a persistent warning beneath the row. Placing it as a sibling of
      // the <label> (rather than inside it) avoids wrapping and lets the
      // warning span the full width of the panel without disturbing the row.
      const fresh = document.querySelector(`#body-options-list span.bv-edit[data-bom-id="${bomId}"]`);
      if (fresh) {
        const label = fresh.closest('label');
        // Remove any existing warning for this bom_id
        document.querySelectorAll(`#body-options-list .bv-warn[data-bom-id="${bomId}"]`).forEach(w => w.remove());
        const warn = document.createElement('div');
        warn.className = 'bv-warn';
        warn.dataset.bomId = bomId;
        warn.title = 'This change updates the body template — all other costings using this template will see the new value';
        warn.innerHTML = '<span style="font-size:11px">⚠</span>&nbsp;<span>TEMPLATE UPDATED</span>';
        warn.style.cssText = 'margin:1px 0 6px 24px;font-size:9px;font-weight:700;color:#f0a500;letter-spacing:.5px;background:#1a1200;border:1px solid #b07800;border-radius:3px;padding:2px 6px;white-space:nowrap;display:inline-flex;align-items:center;gap:2px';
        label.insertAdjacentElement('afterend', warn);
      }
      // Flag an insulation pair that now has zero thickness on both sides.
      validateInsulationPairs();
      // Re-run the calculation if we have results — the new value affects formulas
      if (typeof lastResult !== 'undefined' && lastResult && typeof runCalc === 'function') {
        runCalc();
      }
    } catch(e) {
      toast('Save failed: ' + e.message, 'error');
      restore(`(${Number(current).toFixed(3)} m)`, null);
    }
  });
}

// Admin-only: rename a body-option group on this trailer.
// The pencil ✎ next to a group header in the Body Options panel calls this.
// Opens modal-rename-body-option-group; confirmRenameBodyOptionGroup commits.
let _renameBogState = { oldName: '', displayName: '', trailerId: 0 };

function renameBodyOptionGroup(spanEl) {
  // oldName may be empty when the user is renaming the synthetic 'MISC'
  // placeholder — those rows have body_option_group IS NULL/''. The backend
  // handles the empty case explicitly.
  const oldName     = spanEl?.dataset?.oldName ?? '';
  const displayName = spanEl?.dataset?.displayName || oldName || 'MISC';
  const tt = parseInt(document.getElementById('trailer-select')?.value || '0') || 0;
  if (!tt) { alertModal('Open a trailer first'); return; }
  _renameBogState = { oldName, displayName, trailerId: tt };
  document.getElementById('rename-bog-current').textContent = displayName;
  const input = document.getElementById('rename-bog-input');
  input.value = oldName || '';      // don't prefill the 'MISC' placeholder
  document.getElementById('rename-bog-confirm').disabled = false;
  openModal('modal-rename-body-option-group');
  // Focus + select after the modal becomes visible
  setTimeout(() => { input.focus(); input.select(); }, 50);
}

async function confirmRenameBodyOptionGroup() {
  const { oldName, trailerId } = _renameBogState;
  const newName = (document.getElementById('rename-bog-input').value || '').trim();
  if (!newName) {
    document.getElementById('rename-bog-input').focus();
    return;
  }
  if (oldName && newName.toUpperCase() === oldName.toUpperCase()) {
    closeModal('modal-rename-body-option-group');
    return;
  }
  const btn = document.getElementById('rename-bog-confirm');
  btn.disabled = true;
  try {
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
    const r = await fetch(`/api/trailers/${trailerId}/body-option-groups/rename`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
      body: JSON.stringify({old_name: oldName, new_name: newName}),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || 'Rename failed');
    closeModal('modal-rename-body-option-group');
    // loadBOM() reads from #trailer-select and re-renders Body Options.
    if (typeof loadBOM === 'function') await loadBOM();
    else window.location.reload();
  } catch (e) {
    alertModal('Rename failed: ' + (e.message || e), { title: 'Rename failed', danger: true });
    btn.disabled = false;
  }
}

function onBodyOptToggleChange(input) {
  const bid = input.dataset.bomId;
  bodyOptionSelections[bid] = input.checked;

  const changedItem = bomData.find(it => String(it.id) === bid);
  let needsRerender = false;

  if (changedItem) {
    const nameUp = (changedItem.material_name || '').toUpperCase();

    // Ticking RICE GRAIN FLOOR auto-selects 1ST ROW KICKPLATES
    if (input.checked && nameUp.includes('RICE GRAIN')) {
      const kickplate = bomData.find(it =>
        it.is_body_option &&
        (it.material_name || '').toUpperCase().includes('1ST ROW') &&
        (it.material_name || '').toUpperCase().includes('KICK'));
      if (kickplate && !bodyOptionSelections[String(kickplate.id)]) {
        bodyOptionSelections[String(kickplate.id)] = true;
        needsRerender = true;
      }
    }

    // Unticking RICE GRAIN FLOOR auto-deselects 1ST ROW KICKPLATES
    if (!input.checked && nameUp.includes('RICE GRAIN')) {
      const kickplate = bomData.find(it =>
        it.is_body_option &&
        (it.material_name || '').toUpperCase().includes('1ST ROW') &&
        (it.material_name || '').toUpperCase().includes('KICK'));
      if (kickplate && bodyOptionSelections[String(kickplate.id)]) {
        bodyOptionSelections[String(kickplate.id)] = false;
        needsRerender = true;
      }
    }

    // Unticking 1ST ROW KICKPLATES while RICE GRAIN FLOOR is active → warn
    if (!input.checked && nameUp.includes('1ST ROW') && nameUp.includes('KICK')) {
      const riceGrainOn = bomData.some(it =>
        it.is_body_option &&
        bodyOptionSelections[String(it.id)] &&
        (it.material_name || '').toUpperCase().includes('RICE GRAIN'));
      if (riceGrainOn) {
        openModal('modal-kickplate-warning');
      }
    }
  }

  saveBodyOptSel();
  if (needsRerender) renderBodyOptions(bomData);
  refreshBomDisplay();
  scheduleCalc();
}
const RECENT_DAYS = 7;
const OUTDATED_DAYS = 90;

// Returns the formatted update date string if within RECENT_DAYS, else null.
function recentUpdateLabel(lastUpdatedStr) {
  if (!lastUpdatedStr) return null;
  const d = new Date(lastUpdatedStr);
  if (isNaN(d)) return null;
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - RECENT_DAYS);
  if (d < cutoff) return null;
  return 'Price updated ' + d.toLocaleDateString('en-ZA', { day:'numeric', month:'short', year:'numeric' });
}
// Legacy alias kept for any callers
function isPriceRecentlyUpdated(lastUpdatedStr) { return !!recentUpdateLabel(lastUpdatedStr); }

function outdatedUpdateLabel(lastUpdatedStr) {
  if (!lastUpdatedStr) return null;
  const d = new Date(lastUpdatedStr);
  if (isNaN(d)) return null;
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - OUTDATED_DAYS);
  if (d >= cutoff) return null;
  return 'Outdated price from ' + d.toLocaleDateString('en-ZA', { day:'numeric', month:'short', year:'numeric' });
}

function saveOverridesToSession() {
  const tid = document.getElementById('trailer-select')?.value;
  if (!tid || !Object.keys(priceOverrides).length) {
    sessionStorage.removeItem(OVERRIDE_SESSION_KEY);
    return;
  }
  sessionStorage.setItem(OVERRIDE_SESSION_KEY, JSON.stringify({
    trailer_id: String(tid),
    user_id: CURRENT_USER_ID,
    overrides: priceOverrides
  }));
}

function restoreOverridesFromSession(tid) {
  // Only restore on the explicit return-trip from a permanent-price edit.
  // This prevents overrides from leaking into new quotes or to other users.
  const returnFlag = sessionStorage.getItem('_calc_return');
  if (!returnFlag) return 0;
  sessionStorage.removeItem('_calc_return');
  try {
    const raw = sessionStorage.getItem(OVERRIDE_SESSION_KEY);
    if (!raw) return 0;
    const data = JSON.parse(raw);
    if (String(data.trailer_id) !== String(tid)) return 0;
    if (data.user_id !== undefined && data.user_id !== CURRENT_USER_ID) return 0;
    const entries = Object.entries(data.overrides || {});
    if (!entries.length) return 0;
    priceOverrides = data.overrides;
    return entries.length;
  } catch(e) { return 0; }
}

function clearOverrideSession() {
  sessionStorage.removeItem(OVERRIDE_SESSION_KEY);
  priceOverrides = {};
}

// ── Context menu ──────────────────────────────────────
function showCtxMenu(e, materialId, materialName, originalPrice, bomId, formula) {
  e.preventDefault();
  const menu = document.getElementById('bom-ctx-menu');
  document.getElementById('ctx-menu-mat').textContent = materialName;
  menu.dataset.materialId    = materialId;
  menu.dataset.materialName  = materialName;
  menu.dataset.originalPrice = originalPrice;
  menu.dataset.bomId         = bomId || '';
  menu.dataset.formula       = formula || '';
  // When already overridden, show the existing override price in the modal
  const ovKey = String(bomId || '');
  if (priceOverrides[ovKey]) {
    menu.dataset.originalPrice = priceOverrides[ovKey].originalPrice;
  }
  // Show/hide formula option only when we have a BOM record to edit
  document.getElementById('ctx-edit-formula-item').style.display = bomId ? 'flex' : 'none';
  // Render off-screen first so we can measure the real height, then position.
  menu.style.left    = '-9999px';
  menu.style.top     = '-9999px';
  menu.style.display = 'block';

  const mw  = menu.offsetWidth  || 240;
  const mh  = menu.offsetHeight || 160;
  const W   = window.innerWidth;
  const H   = window.innerHeight;
  const GAP = 4;

  // Default: open below-right of cursor; flip sides if it would clip the viewport.
  let x = e.clientX;
  let y = e.clientY + GAP;
  if (x + mw > W) x = e.clientX - mw;
  if (y + mh > H) y = e.clientY - mh - GAP;

  menu.style.left = Math.max(0, x) + 'px';
  menu.style.top  = Math.max(0, y) + 'px';
}

function hideCtxMenu() {
  document.getElementById('bom-ctx-menu').style.display = 'none';
}

function ctxEditQuoteOnly() {
  const menu = document.getElementById('bom-ctx-menu');
  const { materialId, materialName, originalPrice, bomId } = menu.dataset;
  hideCtxMenu();
  openQuotePriceModal(bomId, materialId, materialName, parseFloat(originalPrice));
}

function ctxEditPermanentSection() {
  const menu = document.getElementById('bom-ctx-menu');
  const { bomId, materialName, materialId } = menu.dataset;
  console.log('[ctxEditPermanentSection]', { bomId, materialId, materialName, bomDataLen: bomData.length, sampleBom: bomData[0] });
  hideCtxMenu();
  if (!bomId) {
    // Last-ditch fallback: single unambiguous match by materialId
    const matches = bomData.filter(b => String(b.material_id) === String(materialId));
    console.log('[ctxEditPermanentSection] fallback matches:', matches.length, matches.map(m => ({id:m.id, sect:m.bom_section})));
    if (matches.length === 1) {
      return _openSectionPriceModal(matches[0], materialName);
    }
    toast(`BOM row not identified (mid=${materialId}, matches=${matches.length})`, 'warn');
    return;
  }
  const row = bomData.find(b => String(b.id) === String(bomId));
  if (!row) { toast('BOM row not found in memory', 'warn'); return; }
  _openSectionPriceModal(row, materialName);
}

async function _openSectionPriceModal(row, materialName) {
  const isSkin   = !!row.skin_formula_id;
  const isTaping = !!row.taping_block_id;
  const isFloor  = !!row.floor_plate_id;
  const isCleat  = !!row.mounting_cleat_id;
  const isComputed = isSkin || isTaping || isFloor || isCleat;

  document.getElementById('sprice-mat-name').textContent = materialName || row.material_name || '';
  document.getElementById('sprice-section').textContent  = 'Section: ' + (row.bom_section || row.category || '—');

  // Computed-priced row — show appropriate notice, hide editor
  document.getElementById('sprice-skin-notice').style.display   = isSkin   ? '' : 'none';
  document.getElementById('sprice-taping-notice').style.display = isTaping ? '' : 'none';
  document.getElementById('sprice-floor-notice').style.display  = isFloor  ? '' : 'none';
  document.getElementById('sprice-cleat-notice').style.display  = isCleat  ? '' : 'none';
  document.getElementById('sprice-edit-panel').style.display    = isComputed ? 'none' : '';
  document.getElementById('sprice-clear-btn').style.display     = isComputed ? 'none' : '';
  document.getElementById('sprice-save-btn').style.display      = isComputed ? 'none' : '';
  document.getElementById('sprice-cancel-btn').textContent      = isComputed ? 'Close' : 'Cancel';

  document.getElementById('sprice-skin-edit-btn-wrap').style.display   = (isSkin   && canEditRecipes) ? '' : 'none';
  document.getElementById('sprice-taping-edit-btn-wrap').style.display = (isTaping && canEditRecipes) ? '' : 'none';

  if (isSkin) {
    document.getElementById('sprice-skin-name').textContent = row.skin_formula_name || 'Skin Formula';
  } else if (isTaping) {
    document.getElementById('sprice-taping-name').textContent = row.taping_block_name || 'Taping Block';
  } else if (isFloor) {
    document.getElementById('sprice-floor-name').textContent = row.floor_plate_name || 'Floor Plate';
  } else if (isCleat) {
    document.getElementById('sprice-cleat-name').textContent = row.mounting_cleat_name || 'Mounting Cleat';
  } else {
    const matPrice      = row.material_price ?? row.price;
    const hasOverride   = row.unit_price_override != null;
    document.getElementById('sprice-material').textContent      = fmt(matPrice);
    document.getElementById('sprice-original-price').textContent = fmt(matPrice);
    document.getElementById('sprice-override-banner').style.display   = hasOverride ? '' : 'none';
    document.getElementById('sprice-nooverride-line').style.display   = hasOverride ? 'none' : '';
    const clearBtn = document.getElementById('sprice-clear-btn');
    if (clearBtn) {
      clearBtn.textContent = hasOverride
        ? `↩ Restore to ${fmt(matPrice)}`
        : 'Clear override';
    }
    const inp = document.getElementById('sprice-input');
    inp.value = hasOverride ? row.unit_price_override : (row.price ?? '');
    setTimeout(() => inp.select(), 80);
  }

  const modal = document.getElementById('modal-section-price');
  modal.dataset.bomId = String(row.id);
  modal.dataset.ttId  = document.getElementById('trailer-select')?.value || '';
  modal.classList.remove('hidden');

  // ── Shared body-types list ────────────────────────────────────────────────
  const usageWrap = document.getElementById('sprice-usage-wrap');
  const usageList = document.getElementById('sprice-usage-list');
  usageWrap.style.display = 'none';
  usageList.innerHTML = '';
  const matId = row.material_id;
  if (matId) {
    usageList.innerHTML = '<span style="color:var(--text-dim);font-size:11px">Loading…</span>';
    try {
      const usage = await api('GET', `/api/materials/${matId}/trailer-usage`);
      const currentTid = String(modal.dataset.ttId || '');
      // Exclude the currently open trailer so the list only shows OTHER body types.
      const others = usage.filter(u => String(u.trailer_id) !== currentTid);
      if (others.length) {
        usageWrap.style.display = '';
        usageList.innerHTML = others.map(u => {
          const catLabel = u.bom_section ? `<span style="display:block;font-size:10px;color:var(--text-dim);margin-top:1px">${escHtml(u.bom_section)}</span>` : '';
          const priceBlock = u.has_override
            ? `<span style="color:var(--blue-hi)">R ${Number(u.effective_price).toFixed(2)}<span style="margin-left:4px;font-size:9px;font-weight:700;letter-spacing:.4px">⊞OVR</span></span><span style="display:block;font-size:10px;color:var(--text-dim);text-decoration:line-through">R ${Number(u.base_price).toFixed(2)}</span>`
            : `<span style="color:var(--text-dim)">R ${Number(u.effective_price).toFixed(2)}</span>`;
          return `<div style="display:flex;justify-content:space-between;align-items:flex-start;padding:3px 0;border-bottom:1px solid var(--border)">
            <span style="color:var(--text)">${escHtml(u.trailer_name)}${catLabel}</span>
            <span style="font-family:var(--font-mono);text-align:right;white-space:nowrap;padding-left:8px">${priceBlock}</span>
          </div>`;
        }).join('');
      }
    } catch(_) {
      usageList.innerHTML = '';
    }
  }
}

async function saveSectionPrice() {
  const modal = document.getElementById('modal-section-price');
  const bomId = modal.dataset.bomId;
  const newPrice = parseFloat(document.getElementById('sprice-input').value);
  if (isNaN(newPrice) || newPrice < 0) { toast('Enter a valid price', 'warn'); return; }
  try {
    await api('PUT', `/api/bom/${bomId}`, { unit_price_override: newPrice });
    closeModal('modal-section-price');
    toast('Section price saved', 'success');
    // Drop any in-session override for this row so the new permanent price shows
    delete priceOverrides[String(bomId)];
    saveOverridesToSession();
    await loadBOM({ preserveInputs: true });
  } catch(e) {
    toast('Save failed: ' + e.message, 'error');
  }
}

async function clearSectionPrice() {
  const modal = document.getElementById('modal-section-price');
  const bomId = modal.dataset.bomId;
  try {
    await api('PUT', `/api/bom/${bomId}`, { unit_price_override: null });
    closeModal('modal-section-price');
    toast('Override cleared', 'success');
    await loadBOM({ preserveInputs: true });
  } catch(e) {
    toast('Clear failed: ' + e.message, 'error');
  }
}

function ctxEditPermanent() {
  const menu = document.getElementById('bom-ctx-menu');
  const { materialId, bomId, materialName } = menu.dataset;
  hideCtxMenu();

  // Check if this row is skin-formula, taping-block, floor-plate or mounting-cleat priced
  const row      = bomData.find(b => String(b.id) === String(bomId));
  const isSkin   = !!(row?.skin_formula_id);
  const isTaping = !!(row?.taping_block_id);
  const isFloor  = !!(row?.floor_plate_id);
  const isCleat  = !!(row?.mounting_cleat_id);

  saveOverridesToSession();
  sessionStorage.setItem('_calc_return', '1');
  const tid = document.getElementById('trailer-select').value;
  const returnUrl = encodeURIComponent(`/calculator${tid ? '?trailer=' + tid : ''}`);
  const destUrl = `/admin/materials?edit=${materialId}&return=${returnUrl}`;

  if (isSkin) {
    document.getElementById('skinwarn-mat-name').textContent     = materialName || row?.material_name || '';
    document.getElementById('skinwarn-formula-name').textContent = row.skin_formula_name || 'Skin Formula';
    const warn = document.getElementById('modal-skin-perm-warning');
    warn.dataset.destUrl = destUrl;
    warn.dataset.ttId    = tid || '';
    warn.classList.remove('hidden');
    return;
  }

  if (isTaping) {
    document.getElementById('tapingwarn-mat-name').textContent  = materialName || row?.material_name || '';
    document.getElementById('tapingwarn-block-name').textContent = row.taping_block_name || 'Taping Block';
    const warn = document.getElementById('modal-taping-perm-warning');
    warn.dataset.destUrl = destUrl;
    warn.classList.remove('hidden');
    return;
  }

  if (isFloor) {
    document.getElementById('floorwarn-mat-name').textContent   = materialName || row?.material_name || '';
    document.getElementById('floorwarn-plate-name').textContent = row.floor_plate_name || 'Floor Plate';
    const warn = document.getElementById('modal-floor-perm-warning');
    warn.dataset.destUrl = destUrl;
    warn.dataset.ttId    = tid || '';
    warn.classList.remove('hidden');
    return;
  }

  if (isCleat) {
    document.getElementById('cleatwarn-mat-name').textContent   = materialName || row?.material_name || '';
    document.getElementById('cleatwarn-cleat-name').textContent = row.mounting_cleat_name || 'Mounting Cleat';
    const warn = document.getElementById('modal-cleat-perm-warning');
    warn.dataset.destUrl = destUrl;
    warn.dataset.ttId    = tid || '';
    warn.classList.remove('hidden');
    return;
  }

  window.location.href = destUrl;
}

function proceedToMaterialEdit() {
  const warn = document.getElementById('modal-skin-perm-warning');
  const destUrl = warn.dataset.destUrl;
  closeModal('modal-skin-perm-warning');
  window.location.href = destUrl;
}

function showMeHowSkinUnlink() {
  const warn = document.getElementById('modal-skin-perm-warning');
  const ttId  = warn.dataset.ttId || '';
  const back  = encodeURIComponent(window.location.href);
  closeModal('modal-skin-perm-warning');
  window.location.href = `/admin/templates?tour=skin-unlink&tt=${ttId}&type=skin&back=${back}`;
}

function showMeHowFromSpriceModal() {
  const modal  = document.getElementById('modal-section-price');
  const ttId   = modal.dataset.ttId || '';
  const back   = encodeURIComponent(window.location.href);
  const isTaping = document.getElementById('sprice-taping-notice')?.style.display !== 'none';
  const isFloor  = document.getElementById('sprice-floor-notice')?.style.display !== 'none';
  const isCleat  = document.getElementById('sprice-cleat-notice')?.style.display !== 'none';
  const type   = isTaping ? 'taping' : isFloor ? 'floor' : isCleat ? 'cleat' : 'skin';
  closeModal('modal-section-price');
  window.location.href = `/admin/templates?tour=skin-unlink&tt=${ttId}&type=${type}&back=${back}`;
}

function proceedToMaterialEditFromFloor() {
  const warn = document.getElementById('modal-floor-perm-warning');
  const destUrl = warn.dataset.destUrl;
  closeModal('modal-floor-perm-warning');
  window.location.href = destUrl;
}

function showMeHowFloorUnlink() {
  const warn = document.getElementById('modal-floor-perm-warning');
  const ttId  = warn.dataset.ttId || '';
  const back  = encodeURIComponent(window.location.href);
  closeModal('modal-floor-perm-warning');
  window.location.href = `/admin/templates?tour=skin-unlink&tt=${ttId}&type=floor&back=${back}`;
}

function proceedToMaterialEditFromCleat() {
  const warn = document.getElementById('modal-cleat-perm-warning');
  const destUrl = warn.dataset.destUrl;
  closeModal('modal-cleat-perm-warning');
  window.location.href = destUrl;
}

function showMeHowCleatUnlink() {
  const warn = document.getElementById('modal-cleat-perm-warning');
  const ttId  = warn.dataset.ttId || '';
  const back  = encodeURIComponent(window.location.href);
  closeModal('modal-cleat-perm-warning');
  window.location.href = `/admin/templates?tour=skin-unlink&tt=${ttId}&type=cleat&back=${back}`;
}

function proceedToMaterialEditFromTaping() {
  const warn = document.getElementById('modal-taping-perm-warning');
  const destUrl = warn.dataset.destUrl;
  closeModal('modal-taping-perm-warning');
  window.location.href = destUrl;
}

let _formulaLibraryCache = null;

async function _loadFormulaLibrary() {
  const sel = document.getElementById('formula-library-select');
  const status = document.getElementById('formula-library-status');
  if (_formulaLibraryCache) {
    _populateFormulaLibrarySelect(_formulaLibraryCache);
    return;
  }
  status.textContent = 'loading…';
  try {
    _formulaLibraryCache = await api('GET', '/api/formulas');
    _populateFormulaLibrarySelect(_formulaLibraryCache);
    status.textContent = '';
  } catch(e) {
    status.textContent = 'could not load library';
  }
}

function _populateFormulaLibrarySelect(formulas) {
  const sel = document.getElementById('formula-library-select');
  sel.innerHTML = '<option value="">— select a saved formula —</option>';
  formulas.forEach(f => {
    const opt = document.createElement('option');
    opt.value = f.expression;
    opt.dataset.desc = f.description || '';
    opt.textContent = f.name + (f.description ? '  —  ' + f.description : '');
    sel.appendChild(opt);
  });
}

function applyLibraryFormula(sel) {
  const expr = sel.value;
  const desc = sel.selectedOptions[0]?.dataset.desc || '';
  document.getElementById('formula-library-desc').textContent = expr ? desc : '';
  if (!expr) return;
  formulaInsert(expr);
  sel.value = '';  // reset picker so user can re-pick same formula if needed
  document.getElementById('formula-library-desc').textContent = '';
  _updateResolvedFormulaVars();
}

function ctxEditFormula() {
  const menu = document.getElementById('bom-ctx-menu');
  const { bomId, formula, materialName } = menu.dataset;
  hideCtxMenu();
  if (!bomId) return;
  document.getElementById('formula-edit-mat-name').textContent = materialName;
  const inp = document.getElementById('formula-edit-input');
  inp.value = formula || '';
  document.getElementById('formula-library-desc').textContent = '';
  const modal = document.getElementById('modal-formula-edit');
  modal.dataset.bomId = bomId;
  modal.dataset.materialName = materialName;
  modal.classList.remove('hidden');
  _loadFormulaLibrary();
  // Pull global variables in if we haven't already (modal can be opened
  // before any /api/calculate has populated lastGlobalVars).
  _ensureGlobalVarsLoaded().then(() => {
    _renderFormulaBodyVariableChips();
    _updateResolvedFormulaVars();
  });
  _renderFormulaBodyVariableChips();
  _updateResolvedFormulaVars();
  setTimeout(() => { inp.focus(); inp.select(); }, 80);
}

function _bodyVariablesFromBom() {
  // Collect Body Variables from bomData (calculator's cached BOM)
  const out = [];
  (typeof bomData !== 'undefined' ? bomData : []).forEach(b => {
    if (b.is_body_option && b.variable_value != null && b.material_name) {
      out.push({ name: b.material_name, value: Number(b.variable_value) });
    }
  });
  // De-dupe by name (multiple templates could share names but we're per-trailer here)
  const seen = new Set();
  return out.filter(v => seen.has(v.name) ? false : seen.add(v.name));
}

function _renderFormulaBodyVariableChips() {
  const wrap = document.getElementById('formula-edit-bv-section');
  const list = document.getElementById('formula-edit-bv-chips');
  if (!wrap || !list) return;
  const vars = _bodyVariablesFromBom();
  const globals = Object.entries(lastGlobalVars || {})
    .map(([name, value]) => ({name, value: Number(value)}))
    .sort((a, b) => a.name.localeCompare(b.name));
  if (!vars.length && !globals.length) { wrap.style.display = 'none'; return; }
  wrap.style.display = 'block';
  const chip = (v, opts) => {
    const tok = `{${v.name}}`;
    const safeTok = tok.replace(/'/g, "\\'");
    const unit = opts.unitSuffix || '';
    return `<button type="button" class="btn btn-outline btn-sm"
      ondblclick='formulaInsertVariable(${JSON.stringify(safeTok)})'
      onclick='formulaInsertVariable(${JSON.stringify(safeTok)})'
      title="${escHtml(tok)} = ${v.value.toFixed(3)}${unit}  ·  ${opts.tooltipLabel}"
      style="font-family:var(--font-mono);font-size:11px;padding:3px 8px;border-color:${opts.borderColor};color:${opts.textColor};background:transparent">
      ${escHtml(tok)} <span style="opacity:.65;margin-left:3px;font-size:10px">${v.value.toFixed(3)}</span>
    </button>`;
  };
  // Body variables (blue) followed by globals (purple) so the user can see both.
  list.innerHTML = [
    ...vars.map(v => chip(v, {borderColor:'#388bfd', textColor:'#58a6ff', unitSuffix:' m', tooltipLabel:'body variable — click to insert'})),
    ...globals.map(g => chip(g, {borderColor:'#a371f7', textColor:'#a371f7', unitSuffix:'', tooltipLabel:'global variable — click to insert'})),
  ].join('');
}

// Lazy-fetch global variables when the formula edit modal opens before any
// /api/calculate has run (so lastGlobalVars is still empty). Best-effort —
// any failure leaves lastGlobalVars empty and {Waste}-style tokens fall back
// to 0 ⚠ in the resolver.
async function _ensureGlobalVarsLoaded() {
  if (lastGlobalVars && Object.keys(lastGlobalVars).length) return;
  try {
    const res = await fetch('/api/global-variables', { credentials: 'same-origin' });
    if (!res.ok) return;
    const arr = await res.json();
    if (Array.isArray(arr)) {
      lastGlobalVars = {};
      arr.forEach(g => { if (g && g.name != null) lastGlobalVars[g.name] = Number(g.value) || 0; });
    }
  } catch(_) {}
}

function formulaInsertVariable(token) {
  formulaInsert(token);
  _updateResolvedFormulaVars();
}

function _buildFormulaContextJs() {
  const L = parseFloat(document.getElementById('f-length')?.value) || 0;
  const W = parseFloat(document.getElementById('f-width')?.value)  || 0;
  const H = parseFloat(document.getElementById('f-height')?.value) || 0;
  const wall_area = L * H * 2;
  const roof_area = L * W;
  const floor_area = L * W;
  const front_rear_area = W * H * 2;
  return {
    length: L, width: W, height: H,
    wall_area, roof_area, floor_area, front_rear_area,
    surface_area: wall_area + roof_area + floor_area + front_rear_area,
    total_panel_area: wall_area + roof_area + front_rear_area,
    volume: L * W * H,
    floor_thickness: 0, panel_thickness: 0, insulation_thickness: 0,
    num_doors: 1, num_axles: 2,
  };
}

function _evalFormulaJs(expr, ctx) {
  // Tiny shunting-yard evaluator — CSP-safe (no eval / new Function).
  // Grammar: numbers, identifiers, () [ ], operators + - * / **, unary -,
  // and the whitelisted functions abs/round/min/max/sqrt/ceil/floor with
  // comma-separated args.
  const FUNCS = {
    abs: Math.abs, round: Math.round, min: Math.min, max: Math.max,
    sqrt: Math.sqrt, ceil: Math.ceil, floor: Math.floor,
  };
  const PREC = { '+': 1, '-': 1, '*': 2, '/': 2, '**': 3, 'u-': 4 };
  const RIGHT = { '**': true, 'u-': true };

  // Tokenize
  const tokens = [];
  let i = 0;
  while (i < expr.length) {
    const ch = expr[i];
    if (/\s/.test(ch)) { i++; continue; }
    if (/[0-9.]/.test(ch)) {
      let j = i;
      while (j < expr.length && /[0-9.]/.test(expr[j])) j++;
      tokens.push({ t: 'num', v: parseFloat(expr.slice(i, j)) });
      i = j; continue;
    }
    if (/[a-zA-Z_]/.test(ch)) {
      let j = i;
      while (j < expr.length && /[a-zA-Z0-9_]/.test(expr[j])) j++;
      tokens.push({ t: 'id', v: expr.slice(i, j) });
      i = j; continue;
    }
    if (ch === '*' && expr[i+1] === '*') { tokens.push({ t: 'op', v: '**' }); i += 2; continue; }
    if ('+-*/'.includes(ch)) { tokens.push({ t: 'op', v: ch }); i++; continue; }
    if (ch === '(' || ch === ')' || ch === ',') { tokens.push({ t: ch }); i++; continue; }
    return null; // unknown character
  }

  // Shunting-yard → RPN, with unary-minus detection
  const out = [], ops = [];
  let prev = null;
  for (const tok of tokens) {
    if (tok.t === 'num') { out.push(tok); }
    else if (tok.t === 'id') { ops.push(tok); }
    else if (tok.t === ',') {
      while (ops.length && ops[ops.length-1].t !== '(') out.push(ops.pop());
      if (!ops.length) return null;
    }
    else if (tok.t === 'op') {
      // Unary minus if at start, after another op, or after '('
      let opv = tok.v;
      if (opv === '-' && (!prev || prev.t === 'op' || prev.t === '(' || prev.t === ',')) opv = 'u-';
      const p = PREC[opv];
      while (ops.length) {
        const top = ops[ops.length-1];
        if (top.t === '(') break;
        if (top.t === 'id') { out.push(ops.pop()); continue; }
        const tp = PREC[top.v];
        if (tp == null) break;
        if (tp > p || (tp === p && !RIGHT[opv])) out.push(ops.pop());
        else break;
      }
      ops.push({ t: 'op', v: opv });
    }
    else if (tok.t === '(') { ops.push(tok); }
    else if (tok.t === ')') {
      while (ops.length && ops[ops.length-1].t !== '(') out.push(ops.pop());
      if (!ops.length) return null;
      ops.pop(); // discard '('
      if (ops.length && ops[ops.length-1].t === 'id') out.push(ops.pop());
    }
    prev = tok;
  }
  while (ops.length) {
    const t = ops.pop();
    if (t.t === '(' || t.t === ')') return null;
    out.push(t);
  }

  // Evaluate RPN
  try {
    const stack = [];
    for (const tok of out) {
      if (tok.t === 'num') stack.push(tok.v);
      else if (tok.t === 'op') {
        if (tok.v === 'u-') stack.push(-stack.pop());
        else {
          const b = stack.pop(), a = stack.pop();
          switch (tok.v) {
            case '+': stack.push(a + b); break;
            case '-': stack.push(a - b); break;
            case '*': stack.push(a * b); break;
            case '/': stack.push(a / b); break;
            case '**': stack.push(a ** b); break;
            default: return null;
          }
        }
      }
      else if (tok.t === 'id') {
        // Identifier could be a variable or a function applied to top of stack
        if (FUNCS[tok.v]) {
          // Pop args until we find the matching '(' marker — tracked via arg count
          // Simpler: peek how many args via the next part of the stack — we treat
          // single-arg by default; for multi-arg (min/max) the user can use
          // them but min(a,b) compiles to two pushes followed by id(min).
          // We support 1- or 2-arg forms by checking how many numbers the
          // stack has — naive but works for our whitelisted fns.
          const fn = FUNCS[tok.v];
          if (fn.length === 0) { stack.push(fn()); }
          else if (fn.length === 1 || (tok.v !== 'min' && tok.v !== 'max')) {
            stack.push(fn(stack.pop()));
          } else {
            const b = stack.pop(), a = stack.pop();
            stack.push(fn(a, b));
          }
        } else if (ctx && ctx[tok.v] != null) {
          stack.push(ctx[tok.v]);
        } else {
          return null; // unknown identifier
        }
      }
    }
    if (stack.length !== 1) return null;
    const v = stack[0];
    return (typeof v === 'number' && isFinite(v)) ? v : null;
  } catch(_) { return null; }
}

function _updateResolvedFormulaVars() {
  const inp = document.getElementById('formula-edit-input');
  const wrap = document.getElementById('formula-edit-resolved');
  const list = document.getElementById('formula-edit-resolved-list');
  const result = document.getElementById('formula-edit-result');
  if (!inp || !wrap || !list) return;
  const rawExpr = inp.value || '';
  const tokens = [...new Set((rawExpr.match(/\{([^{}]+)\}/g) || []))];

  // Merge body variables AND global variables into the lookup — same precedence
  // rule as the server's calculate_bom (body vars win on a name collision). The
  // editor used to look at body vars only, which made tokens like {Waste} resolve
  // to 0 with a warning even though Waste is a defined global.
  const vars = _bodyVariablesFromBom();
  const lookup = {};
  Object.entries(lastGlobalVars || {}).forEach(([n, v]) => {
    if (n) lookup[n.toUpperCase()] = { name: n, value: Number(v), source: 'global' };
  });
  vars.forEach(v => { lookup[v.name.toUpperCase()] = { ...v, source: 'body' }; });

  // Substitute {NAME} tokens with literal numbers, then eval against geometry context
  let expr = rawExpr;
  tokens.forEach(tok => {
    const inner = tok.slice(1, -1).trim().toUpperCase();
    const v = lookup[inner];
    expr = expr.split(tok).join(`(${v ? v.value : 0})`);
  });
  const total = _evalFormulaJs(expr, _buildFormulaContextJs());

  // Show panel if there are tokens OR the formula has any content (so users always see the result)
  if (!tokens.length && !rawExpr.trim()) { wrap.style.display = 'none'; return; }

  list.innerHTML = tokens.length ? tokens.map(tok => {
    const inner = tok.slice(1, -1).trim();
    const v = lookup[inner.toUpperCase()];
    if (v) {
      const unit = v.source === 'global' ? '' : ' m';
      const colour = v.source === 'global' ? '#a371f7' : '#58a6ff';
      return `<span style="display:inline-block;margin-right:12px"><span style="color:${colour}">${escHtml(tok)}</span> = <span style="color:var(--text)">${v.value.toFixed(3)}${unit}</span></span>`;
    } else {
      return `<span style="display:inline-block;margin-right:12px;color:#f0a500" title="No matching Body or Global Variable — will resolve to 0">${escHtml(tok)} = <span style="color:#f0a500">0 ⚠</span></span>`;
    }
  }).join('') : `<span style="opacity:.6">No body variables in this formula</span>`;

  if (result) {
    result.textContent = total != null ? `= ${total.toFixed(4)}` : '= —';
    result.style.color = total != null ? 'var(--text-head)' : 'var(--red, #c0392b)';
    result.title = total != null ? 'Live result with current dimensions and body variable values' : 'Formula could not be evaluated';
  }
  wrap.style.display = 'block';
}

function formulaInsert(token) {
  const inp = document.getElementById('formula-edit-input');
  const start = inp.selectionStart, end = inp.selectionEnd;
  const before = inp.value.slice(0, start), after = inp.value.slice(end);
  inp.value = before + token + after;
  inp.focus();
  inp.setSelectionRange(start + token.length, start + token.length);
}

async function saveFormulaEdit() {
  const modal = document.getElementById('modal-formula-edit');
  const bomId = modal.dataset.bomId;
  const newFormula = document.getElementById('formula-edit-input').value.trim();
  if (!bomId) return;
  try {
    await api('PUT', `/api/bom/${bomId}`, { formula_expression: newFormula });
    // Update bomData in memory so the formula sub-line reflects the change immediately
    const bItem = bomData.find(b => String(b.id) === String(bomId));
    if (bItem) bItem.formula = newFormula;
    closeModal('modal-formula-edit');
    toast('Formula updated', 'success');
    // Re-calculate; after render, scroll back to this BOM row
    _scrollToBomId = bomId;
    if (bomData.length) runCalc();
  } catch(err) {
    toast('Failed to save formula', 'error');
  }
}

function openQuotePriceModal(bomId, materialId, materialName, originalPrice) {
  const row      = bomData.find(b => String(b.id) === String(bomId));
  const isSkin   = !!(row?.skin_formula_id);
  const isTaping = !!(row?.taping_block_id);
  const hasOverride = !!priceOverrides[bomId];

  document.getElementById('qprice-mat-name').textContent = materialName;
  document.getElementById('qprice-current').textContent  = fmt(originalPrice);

  // Taping block notice
  document.getElementById('qprice-taping-notice').style.display = isTaping ? '' : 'none';
  if (isTaping) {
    document.getElementById('qprice-taping-name').textContent = row.taping_block_name || 'Taping Block';
  }

  // Skin formula notice
  document.getElementById('qprice-skin-notice').style.display = isSkin ? '' : 'none';
  if (isSkin) {
    document.getElementById('qprice-skin-name').textContent = row.skin_formula_name || 'Skin Formula';
  }

  // Revert button — only show when skin/taping row already has an active override
  document.getElementById('qprice-revert-row').style.display = ((isSkin || isTaping) && hasOverride) ? '' : 'none';

  const inp = document.getElementById('qprice-input');
  inp.value = priceOverrides[bomId]?.newPrice ?? originalPrice;
  const reasonEl = document.getElementById('qprice-reason');
  reasonEl.value = priceOverrides[bomId]?.reason ?? '';
  reasonEl.classList.remove('input-error');
  document.getElementById('qprice-reason-hint').style.color = '';
  const modal = document.getElementById('modal-quote-price');
  modal.dataset.bomId         = bomId;
  modal.dataset.materialId    = materialId;
  modal.dataset.originalPrice = originalPrice;
  modal.dataset.isSkin        = isSkin ? '1' : '';
  modal.classList.remove('hidden');
  setTimeout(() => inp.select(), 80);
}

function revertToSkinPrice() {
  const modal = document.getElementById('modal-quote-price');
  const bomId = modal.dataset.bomId;
  delete priceOverrides[bomId];
  closeModal('modal-quote-price');
  saveOverridesToSession();
  toast('Reverted to skin formula price', 'success');
  if (bomData.length) runCalc();
}

function saveQuotePrice() {
  const modal        = document.getElementById('modal-quote-price');
  const bomId        = modal.dataset.bomId;
  const materialId   = modal.dataset.materialId;
  const originalPrice = parseFloat(modal.dataset.originalPrice);
  const newPrice      = parseFloat(document.getElementById('qprice-input').value);
  const reasonEl     = document.getElementById('qprice-reason');
  const reason       = (reasonEl.value || '').trim();
  const reasonHint   = document.getElementById('qprice-reason-hint');
  if (!bomId) { toast('BOM row not identified', 'warn'); return; }
  if (isNaN(newPrice) || newPrice < 0) { toast('Enter a valid price', 'warn'); return; }

  const isClearing = Math.abs(newPrice - originalPrice) < 0.001;
  if (!isClearing && reason.length < 5) {
    reasonEl.classList.add('input-error');
    reasonHint.style.color = 'var(--red)';
    reasonHint.textContent = 'Reason is required (minimum 5 characters).';
    reasonEl.focus();
    return;
  }

  if (isClearing) {
    delete priceOverrides[bomId];
  } else {
    priceOverrides[bomId] = { newPrice, originalPrice, materialId, reason };
  }
  closeModal('modal-quote-price');
  saveOverridesToSession();
  if (bomData.length) runCalc();
}

// Dismiss context menu on outside click / Escape
document.addEventListener('click', hideCtxMenu);
document.addEventListener('keydown', e => { if (e.key === 'Escape') hideCtxMenu(); });

// Admin single-side mode: reset when clicking outside the summary panel
document.addEventListener('mousedown', e => {
  if (!_singleSideMode) return;
  const summaryPanel = document.querySelector('.calc-panel--summary');
  if (summaryPanel && !summaryPanel.contains(e.target)) {
    _singleSideMode = false;
    if (lastResult) { renderSummary(lastResult); renderBOMWithCosts(lastResult.items, bomData); }
  }
});

// Right-click delegation on #bom-area
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('bom-area').addEventListener('contextmenu', e => {
    const row = e.target.closest('[data-material-id]');
    if (!row) return;
    let bomId = row.dataset.bomId || '';
    // Fallback: resolve bom_id from materialId + section header text of the enclosing group.
    // Protects against stale cached result_json or older renders missing data-bom-id.
    if (!bomId) {
      const mid = row.dataset.materialId;
      // Post-calc row: sibling calc-grp-hdr preceding this row in the same tbody
      let sectionName = '';
      const gid = row.dataset.catGroup;
      if (gid) {
        const hdr = document.querySelector(`.calc-grp-hdr[data-cat-id="${gid}"]`);
        if (hdr) sectionName = (hdr.textContent || '').trim();
      }
      // Pre-calc row: ancestor .parts-group > .parts-group-title
      if (!sectionName) {
        const grp = row.closest('.parts-group');
        if (grp) sectionName = (grp.querySelector('.parts-group-title')?.textContent || '').trim();
      }
      const match = bomData.find(b =>
        String(b.material_id) === String(mid) &&
        sectionName.includes(String(b.bom_section || b.category || ''))
      );
      if (match) bomId = String(match.id);
    }
    showCtxMenu(e,
      row.dataset.materialId,
      row.dataset.materialName,
      parseFloat(row.dataset.unitPrice || row.dataset.price || 0),
      bomId,
      row.dataset.formula || ''
    );
  });

  // Enter key in quote-price modal
  document.getElementById('qprice-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') saveQuotePrice();
  });

  // Ctrl+Enter saves formula (Enter alone is a newline in the textarea)
  const _fei = document.getElementById('formula-edit-input');
  _fei.addEventListener('keydown', e => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) saveFormulaEdit();
  });
  // Live-update resolved Body Variables as the user types
  _fei.addEventListener('input', _updateResolvedFormulaVars);
});

function scheduleCalc() {
  clearTimeout(calcTimer);
  calcTimer = setTimeout(() => { if (bomData.length) runCalc(); }, 700);
}

function triggerLiveRecalc(options = {}) {
  if (options.updateGeo) updateGeo();
  if (!bomData.length) return;
  scheduleCalc();
}

function bindLiveCalcControl(id, options = {}) {
  const el = document.getElementById(id);
  if (!el) return;
  const events = options.events || ['input', 'change'];
  events.forEach(eventName => {
    el.addEventListener(eventName, () => triggerLiveRecalc(options));
  });
}

async function loadCustomers() {
  try {
    allCustomers = await api('GET', '/api/customers');
    renderCustomerList(allCustomers.filter(c => c.is_active));
    return allCustomers;
  } catch(e) { /* non-fatal */ }
  return [];
}

function filterCustomers() {
  const q = document.getElementById('cust-search').value.toLowerCase();
  const filtered = allCustomers.filter(c => c.is_active &&
    (c.name.toLowerCase().includes(q) || c.bp_code.toLowerCase().includes(q)));
  renderCustomerList(filtered);
}

function renderCustomerList(custs) {
  const sel = document.getElementById('cust-select');
  const prev = sel.value;
  sel.innerHTML = '<option value="">— No customer —</option>' +
    custs.map(c => `<option value="${c.id}">${escHtml(c.name)}${c.bp_code ? ' ['+escHtml(c.bp_code)+']' : ''}</option>`).join('');
  if (prev && sel.querySelector(`option[value="${prev}"]`)) sel.value = prev;
}

function setCustomer(customerId) {
  const sel = document.getElementById('cust-select');
  if (!customerId) {
    sel.value = '';
    return;
  }
  const target = String(customerId);
  if (sel.querySelector(`option[value="${target}"]`)) sel.value = target;
}

function applyCalculationInputs(payload) {
  const dims = payload.dimensions || {};
  document.getElementById('f-length').value = dims.length ?? document.getElementById('f-length').value;
  document.getElementById('f-width').value = dims.width ?? document.getElementById('f-width').value;
  document.getElementById('f-height').value = dims.height ?? document.getElementById('f-height').value;
  document.getElementById('f-floor-thick').value = dims.floor_thickness ?? document.getElementById('f-floor-thick').value;
  document.getElementById('f-panel-thick').value = dims.panel_thickness ?? document.getElementById('f-panel-thick').value;
  document.getElementById('f-insul-thick').value = dims.insulation_thickness ?? document.getElementById('f-insul-thick').value;
  document.getElementById('f-axles').value = dims.num_axles ?? document.getElementById('f-axles').value;
  document.getElementById('f-doors').value = dims.num_doors ?? document.getElementById('f-doors').value;
  document.getElementById('f-margin').value = payload.profit_margin ?? 0;
  setCustomer(payload.customer_id);
  // Restore body-option selections from saved calculation
  if (payload.body_option_selections && typeof payload.body_option_selections === 'object') {
    Object.assign(bodyOptionSelections, payload.body_option_selections);
    renderBodyOptions(bomData);
    refreshBomDisplay();
  }
  updateGeo();
}

async function prefillCalculation(recordId) {
  const doneLoading = showLoadingOverlay(`Loading calculation #${recordId}...`);
  try {
    const payload = await api('GET', `/api/calculations/${recordId}`);
    if (!payload.trailer_type_id) throw new Error('Stored calculation has no trailer type');

    clearOverrideSession();  // copied quote always starts with clean prices
    document.getElementById('trailer-select').value = payload.trailer_type_id;
    await loadBOM({ preserveInputs: true });
    applyCalculationInputs(payload);
    // WO v4.30 — a copy keeps the SOURCE ratio (applyCalculationInputs doesn't set it); reuse the
    // edit-ratio restorer so copy matches edit and never falls through to the 55% new-costing default.
    restoreEditRatio(payload.ratio_value, (payload.ui_snapshot || {}).ratio);
    lastRecordId = null;
    document.getElementById('print-btn').disabled = true;
    document.getElementById('view-btn').disabled = true;
    await runCalc();
    toast(`Prefilled from calculation #${recordId}`, 'info');
  } catch (e) {
    toast('Failed to load saved calculation: ' + e.message, 'error');
  } finally {
    doneLoading();
  }
}

// Rebuild the in-memory priceOverrides map from a saved record's overrides.
// The saved record stores { bomId: newPrice } + reasons; the original price and
// material id are looked up from the freshly loaded bomData so the override
// pills, struck-through originals and revert-detection all behave normally.
function rebuildOverridesFromSaved(overrides, reasons) {
  priceOverrides = {};
  if (!overrides || typeof overrides !== 'object') return 0;
  let n = 0;
  Object.entries(overrides).forEach(([bid, price]) => {
    const key = String(bid);
    const row = bomData.find(r => String(r.id) === key);
    priceOverrides[key] = {
      newPrice:      +price,
      originalPrice: row ? +(row.price ?? price) : +price,
      materialId:    row ? row.material_id : null,
      reason:        (reasons && reasons[bid]) || '',
    };
    n++;
  });
  return n;
}

// Open a saved PENDING costing for real editing (prices, dimensions, options),
// remembering the source record so Save can overwrite it or branch a revision.
// Anything other than 'pending' falls back to the safe copy-into-new-quote flow.
async function editCalculation(recordId) {
  const doneLoading = showLoadingOverlay(`Loading costing #${recordId} for editing…`);
  try {
    const payload = await api('GET', `/api/calculations/${recordId}`);
    if (!payload.trailer_type_id) throw new Error('Stored calculation has no trailer type');

    const status = payload.status || 'pending';
    if (status !== 'pending') {
      // Not editable — degrade gracefully to a copy so the user still gets a
      // usable starting point rather than an error.
      toast(`Only pending costings can be edited — “${payload.quote_number || ('#'+recordId)}” is ${status}. Opening a copy instead.`, 'warn');
      clearOverrideSession();
      document.getElementById('trailer-select').value = payload.trailer_type_id;
      await loadBOM({ preserveInputs: true });
      applyCalculationInputs(payload);
      lastRecordId = null;
      await runCalc();
      return;
    }

    const snap  = payload.ui_snapshot || {};
    const saved = payload.saved_result || null;
    const tid   = +payload.trailer_type_id;

    clearOverrideSession();
    document.getElementById('trailer-select').value = payload.trailer_type_id;

    // 1) Pre-seed per-trailer localStorage + in-memory selection stores BEFORE
    //    loadBOM so preserveInputs:true keeps the quote's selections instead of
    //    seeding the trailer's current configurator defaults.
    try {
      const bos = snap.body_option_selections || payload.body_option_selections;
      if (bos) localStorage.setItem(`body_opt_sel_${tid}`, JSON.stringify(bos));
      if (snap.drd_srd) localStorage.setItem(`drd_srd_${tid}`, JSON.stringify(snap.drd_srd));
    } catch (_) {}
    if (window.OptionalSections) {
      window.OptionalSections.saveEnabled(tid,
        new Set((snap.optional_sections_enabled || payload.optional_sections_enabled || []).map(Number).filter(Number.isFinite)));
      window.OptionalSections.saveRowExcl(tid, 'c1',
        new Set((snap.optional_row_excl || payload.user_excluded_bom_ids || []).map(Number).filter(Number.isFinite)));
    }
    bodyOptionSelections = { ...(snap.body_option_selections || payload.body_option_selections || {}) };
    drdSrdEnabled        = { ...(snap.drd_srd || {}) };

    await loadBOM({ preserveInputs: true });
    applyCalculationInputs(payload);             // dims, margin, customer, body options

    // 2) Hard-restore ALL configurator draft stores AFTER loadBOM's one-time
    //    seed, and pin the trailer so runCalc's payload build uses these exact
    //    values — these drive excluded_categories + flag_overrides server-side.
    _draftFlagStateTrailer = tid;
    if (snap.draft_flag_state)       draftFlagState          = { ...snap.draft_flag_state };
    else if (payload.flag_overrides) Object.assign(draftFlagState, payload.flag_overrides);
    if (snap.draft_category_radio)   draftCategoryRadioState = { ...snap.draft_category_radio };
    if (snap.draft_masterless_cat)   draftMasterlessCatState = { ...snap.draft_masterless_cat };
    if (snap.draft_folder)           draftFolderState        = { ...snap.draft_folder };
    if (snap.body_option_selections) bodyOptionSelections    = { ...snap.body_option_selections };
    if (snap.drd_srd)                drdSrdEnabled           = { ...snap.drd_srd };
    // Pin the saved body-variable values (EPS/PU thicknesses, by name) so the
    // recompute reproduces them regardless of later global copy-on-switches.
    editBodyVarOverrides = (saved && saved.body_variables && Object.keys(saved.body_variables).length)
      ? { ...saved.body_variables } : null;
    // Legacy records (no UI snapshot) can't have their configurator state
    // reconstructed reliably — replay the saved result exactly instead. Records
    // that DO carry a snapshot keep full, interactive editing.
    const _hasSnapshot = !!(snap && snap.body_option_selections
                            && Object.keys(snap.body_option_selections).length);
    editReplay = _hasSnapshot ? null : buildEditReplay(saved && saved.items);

    // Restore the saved discount so the Net Total reproduces on edit.
    discountKind  = (payload.discount_kind === 'percent' || payload.discount_kind === 'amount')
                    ? payload.discount_kind : null;
    discountInput = discountKind ? (+payload.discount_input || 0) : 0;

    // 3) Price overrides — prefer the full snapshot (carries originalPrice +
    //    reason); else rebuild from the saved by-bom map.
    if (snap.price_overrides && Object.keys(snap.price_overrides).length) {
      priceOverrides = JSON.parse(JSON.stringify(snap.price_overrides));
    } else {
      rebuildOverridesFromSaved(payload.overrides, payload.override_reasons);
    }
    saveOverridesToSession();

    // 4) Profit ratio + chassis selection.
    restoreEditRatio(payload.ratio_value, snap.ratio);
    await restoreChassisSelection(snap.chassis || payload.chassis);

    // 4b) Reconstruct EXTRAS (optional sections) from the SAVED RESULT — the
    //     ground truth for what was actually included. This makes extras
    //     re-balance even for quotes saved before the UI snapshot existed.
    restoreOptionalSectionsFromResult(tid, saved && saved.items);

    // 5) Reflect every restored selection in the body-options panel + BOM table.
    try { renderBodyOptions(bomData); } catch (_) {}
    refreshBomDisplay();

    editingRecordId    = recordId;
    editingVersion     = payload.version || 1;
    editingQuoteNumber = payload.quote_number || null;
    showEditBanner(payload);

    // 6) Recompute from the fully-restored state, then prove it balances with
    //    the saved quote (acceptance gate — any drift is surfaced, never silent).
    await runCalc();
    verifyEditBalance(saved);

    toast(`Editing ${editingQuoteNumber || ('#'+recordId)} · Rev${editingVersion}`, 'info');
  } catch (e) {
    toast('Failed to load costing for editing: ' + e.message, 'error');
  } finally {
    doneLoading();
  }
}

// Show / refresh the sticky "you are editing" banner at the top of the calculator.
function showEditBanner(payload) {
  const bar = document.getElementById('edit-mode-banner');
  if (!bar) return;
  const custName = (payload && payload.customer_id && allCustomers.length)
    ? (allCustomers.find(c => String(c.id) === String(payload.customer_id))?.name || '')
    : '';
  const idLabel = editingQuoteNumber || ('#' + editingRecordId);
  document.getElementById('edit-banner-text').innerHTML =
    `✏️ Editing <strong>${escHtml(idLabel)}</strong> · Rev${editingVersion}` +
    (custName ? ` · ${escHtml(custName)}` : '') +
    ` <span style="color:var(--text-dim)">— saving will ask to overwrite the original or save a new revision</span>`;
  bar.classList.remove('hidden');
}

// Leave edit mode and start a clean calculation.
function cancelEdit() {
  editingRecordId = null;
  editReplay = null;
  editBodyVarOverrides = null;
  window.location.href = '/calculator';
}

// Restore the saved profit-ratio dropdown selection. Prefer the exact saved
// option value; fall back to a numeric match on ratio_value.
function restoreEditRatio(ratioValue, snapRatio) {
  const sel = document.getElementById('f-ratio');
  if (!sel) return;
  if (snapRatio != null && snapRatio !== '' &&
      [...sel.options].some(o => o.value === String(snapRatio))) {
    sel.value = String(snapRatio);
    return;
  }
  if (ratioValue != null) {
    const m = [...sel.options].find(o => o.value !== '' &&
      Math.abs(parseFloat(o.value) - Number(ratioValue)) < 1e-6);
    if (m) sel.value = m.value;
  }
}

// WO v4.30 — a brand-new costing opens with the ratio defaulted to 55%. Edit (?edit=) restores the saved
// ratio and copy (?from=) restores the source ratio (both via restoreEditRatio), so neither uses this.
// Guarded on an empty selection so a restored last-session draft keeps the ratio already chosen.
function defaultNewRatio() {
  const sel = document.getElementById('f-ratio');
  if (sel && !sel.value) sel.value = '0.55';   // 0.55 = the "55%" option
}

// Re-open the chassis panel and restore every chassis dropdown from the saved
// selection (mirrors restoreLastSession's chassis block).
async function restoreChassisSelection(ch) {
  if (!ch || !ch.enabled) return;
  const chOn = document.getElementById('f-chassis-on');
  const wrap = document.getElementById('chassis-fields');
  if (chOn) chOn.checked = true;
  if (wrap) wrap.style.display = '';
  try { await _loadChassisOptions(); } catch (_) {}
  const setv = (id, val) => {
    const el = document.getElementById(id);
    if (el && val != null && val !== '') el.value = val;
  };
  setv('f-ch-length',     ch.length);
  setv('f-ch-axles',      ch.axle_count);
  setv('f-ch-tyre-style', ch.tyre_style);
  try { _refreshChassisDropdowns(); } catch (_) {}
  setv('f-ch-suspension', ch.suspension_id);
  setv('f-ch-brake',      ch.brake_id);
  setv('f-ch-tyre',       ch.tyre_id);
  setv('f-ch-rim',        ch.rim_id);
  setv('f-ch-lift-type',  ch.lift_type_id);
  setv('f-ch-lift-count', ch.lift_count);
  try { _updateChassisCounts(); } catch (_) {}
}

// Reconstruct the EXTRAS / OPTIONAL EXTRAS state from a saved result's items —
// the ground truth for what was included. A section is ON if it has any included
// item; items left out inside an ON section become per-row exclusions. Sections
// with nothing included stay off (the backend default-excludes them). Works with
// or without a UI snapshot, so saved extras always re-balance on edit.
function restoreOptionalSectionsFromResult(tid, items) {
  if (!window.OptionalSections || !Array.isArray(items) || !tid) return;
  const enabled = new Set();
  items.forEach(it => {
    if (it && it.section_is_optional && !it.excluded && it.bom_section_id != null) {
      enabled.add(+it.bom_section_id);
    }
  });
  const rowExcl = new Set();
  items.forEach(it => {
    if (!it || !it.section_is_optional || it.bom_section_id == null) return;
    const bid = it.bom_id != null ? it.bom_id : it.id;
    if (bid == null) return;
    if (enabled.has(+it.bom_section_id) && it.excluded) rowExcl.add(+bid);
  });
  window.OptionalSections.saveEnabled(+tid, enabled);
  window.OptionalSections.saveRowExcl(+tid, 'c1', rowExcl);
}

// Build an edit-replay descriptor from a saved result so a legacy (snapshot-less)
// costing recomputes to exactly its saved figures: include ONLY the saved-included
// rows (force-exclude every other BOM row), pinning each line's saved formula and
// unit price. This sidesteps reverse-engineering configurator gating and survives
// global drift — body-option changes, EPS/PU copy-on-switch (which rewrites BOM
// formulas), and price changes — by replaying the frozen result.
function buildEditReplay(savedItems) {
  if (!Array.isArray(savedItems) || !Array.isArray(bomData)) return null;
  const inclIds = new Set();
  savedItems.forEach(it => {
    if (it && !it.excluded) {
      const b = it.bom_id != null ? it.bom_id : it.id;
      if (b != null) inclIds.add(+b);
    }
  });
  const userExcluded = bomData.map(r => r.id).filter(id => !inclIds.has(+id));
  const formulaOverrides = {}, savedPrices = {}, optionalEnabled = new Set();
  savedItems.forEach(it => {
    const b = it && (it.bom_id != null ? it.bom_id : it.id);
    if (b == null || it.excluded) return;
    if (it.formula != null)    formulaOverrides[String(b)] = it.formula;
    if (it.unit_price != null) savedPrices[String(b)]      = it.unit_price;
    if (it.section_is_optional && it.bom_section_id != null) optionalEnabled.add(+it.bom_section_id);
  });
  return { userExcluded, formulaOverrides, savedPrices, optionalEnabled: [...optionalEnabled] };
}

// Build the complete UI snapshot persisted with a saved costing so a later edit
// can reconstruct the calculator exactly. Captures every store that feeds the
// /api/approve payload, plus body-variable values for drift detection.
function _buildUiSnapshot() {
  // Legacy replay edits intentionally stay snapshot-less: the live stores weren't
  // reconstructed (we replay the saved result instead), so a snapshot would be
  // misleading. Keeping it null means the next edit replays the new result too.
  if (editReplay) return null;
  const tidVal = document.getElementById('trailer-select')?.value;
  if (!tidVal) return null;
  const tid = +tidVal;
  const bodyVars = {};
  (bomData || []).forEach(r => {
    if (r && r.variable_value != null) bodyVars[String(r.id)] = Number(r.variable_value);
  });
  return {
    body_option_selections:    { ...bodyOptionSelections },
    drd_srd:                   { ...drdSrdEnabled },
    draft_flag_state:          { ...draftFlagState },
    draft_category_radio:      { ...draftCategoryRadioState },
    draft_masterless_cat:      { ...draftMasterlessCatState },
    draft_folder:              { ...draftFolderState },
    optional_sections_enabled: window.OptionalSections ? [...window.OptionalSections.loadEnabled(tid)] : [],
    optional_row_excl:         window.OptionalSections ? [...window.OptionalSections.loadRowExcl(tid, 'c1')] : [],
    price_overrides:           JSON.parse(JSON.stringify(priceOverrides || {})),
    ratio:                     document.getElementById('f-ratio')?.value || '',
    chassis:                   getChassisSelection(),
    body_variables:            bodyVars,
  };
}

// Acceptance gate: confirm the freshly-recomputed edit matches the saved quote.
// Compares both the selling price AND the manufacturing (pre-ratio) total. If
// anything drifts, the original figures are restored to the panel and a clear
// warning is shown — so the user always sees a balanced load and is told when
// re-costing moved a number (e.g. a global price or insulation-thickness change
// since the quote was saved).
function verifyEditBalance(saved) {
  const banner = document.getElementById('edit-banner-balance');
  if (!saved || typeof lastResult === 'undefined' || !lastResult) {
    if (banner) banner.innerHTML = '';
    return;
  }
  const num = v => Number(v) || 0;
  // /api/calculate returns selling_price PRE-ratio (the summary panel applies the
  // profit ratio client-side), whereas the saved record stores it POST-ratio. So
  // derive the selling price the SAME way for both — (manufacturing + margin) ÷
  // ratio — instead of trusting the stored field, else we'd compare unlike values.
  const ratio = parseFloat(document.getElementById('f-ratio')?.value);
  const useRatio = !isNaN(ratio) && ratio > 0;
  const sellOf = r => {
    const withMargin = num(r.grand_total) + num(r.profit_amount);
    return useRatio ? withMargin / ratio : withMargin;
  };
  const savedSell = sellOf(saved);
  const liveSell  = sellOf(lastResult);
  const savedMfg  = num(saved.grand_total);
  const liveMfg   = num(lastResult.grand_total);
  const TOL = 1.0;  // 1 currency unit — absorbs cent-level rounding only
  const balanced = Math.abs(savedSell - liveSell) <= TOL &&
                   Math.abs(savedMfg  - liveMfg)  <= TOL;
  if (!banner) return;
  if (balanced) {
    banner.innerHTML =
      `<span style="color:#4ade80">✓ Balanced with the saved quote — Total ${fmt(savedSell)}` +
      (savedMfg ? ` · Mfg ${fmt(savedMfg)}` : '') + `</span>`;
    return;
  }
  // Drift — restore the saved figures so the displayed load matches the quote,
  // and explain precisely what re-costing changed.
  lastResult = saved;
  try { renderSummary(saved); } catch (_) {}
  try { if (saved.items) renderBOMWithCosts(saved.items, bomData); } catch (_) {}
  const dSell = liveSell - savedSell;
  const sign  = dSell >= 0 ? '+' : '−';
  banner.innerHTML =
    `<span style="color:#ffb340">⚠ Re-costing with current prices/formulas would change the total by ` +
    `${sign}${fmt(Math.abs(dSell))} (saved ${fmt(savedSell)} → now ${fmt(liveSell)}). ` +
    `Showing the saved figures; your next edit switches to the updated ones.</span>`;
}

// Load trailer defaults then pre-select from URL param
let _calcTapingBlocks = [];
let _calcFloorPlates  = [];
let _calcCleats       = [];
window.addEventListener('DOMContentLoaded', async () => {
  try {
    const trailers = await api('GET', '/api/trailers');
    trailers.forEach(t => { trailerDefaults[t.id] = t; });
  } catch(e) { /* non-fatal */ }

  try {
    _calcTapingBlocks = await api('GET', '/api/taping-blocks');
  } catch(e) { /* non-fatal */ }

  try {
    _calcFloorPlates = await api('GET', '/api/floor-plates');
  } catch(e) { /* non-fatal */ }

  try {
    _calcCleats = await api('GET', '/api/mounting-cleats');
  } catch(e) { /* non-fatal */ }

  await loadCustomers();

  window.addEventListener('beforeunload', saveLastSession);

  const params = new URLSearchParams(location.search);
  const editId = params.get('edit');
  const fromId = params.get('from');
  const tid = params.get('trailer');
  if (editId) {
    await editCalculation(editId);
  } else if (fromId) {
    await prefillCalculation(fromId);
  } else if (tid) {
    document.getElementById('trailer-select').value = tid;
    loadBOM();
    defaultNewRatio();              // WO v4.30 — new costing for a trailer: default ratio 55%
  } else {
    await restoreLastSession();
    defaultNewRatio();              // WO v4.30 — new costing: default ratio 55% (kept only if none restored)
  }
  updateGeo();

  registerPageShortcuts({
    search: () => {
      const input = document.getElementById('cust-search');
      input?.focus();
      input?.select?.();
    },
    save: () => {
      if (!document.getElementById('approve-btn').disabled) approveCosting();
    },
    new: () => {
      window.location.href = '/calculator';
    },
  });

  ['f-length','f-width','f-height','f-floor-thick','f-panel-thick','f-insul-thick','f-axles','f-doors']
    .forEach(id => bindLiveCalcControl(id, { updateGeo: true }));
  bindLiveCalcControl('f-margin', { updateGeo: true });
  bindLiveCalcControl('f-ratio', { events: ['change'] });
});

const VALIDATED_FIELDS = [
  { id: 'f-length',     errId: 'err-length',     label: 'Length',               min: 0.01 },
  { id: 'f-width',      errId: 'err-width',       label: 'Width',                min: 0.01 },
  { id: 'f-height',     errId: 'err-height',      label: 'Height',               min: 0.01 },
  { id: 'f-floor-thick',errId: 'err-floor-thick', label: 'Floor thickness',      min: 0.001 },
  { id: 'f-panel-thick',errId: 'err-panel-thick', label: 'Panel thickness',      min: 0.001 },
  { id: 'f-insul-thick',errId: 'err-insul-thick', label: 'Insulation thickness', min: 0.001 },
];

function validateDims() {
  let valid = true;
  VALIDATED_FIELDS.forEach(({ id, errId, label, min }) => {
    const el  = document.getElementById(id);
    const err = document.getElementById(errId);
    const val = parseFloat(el.value);
    const bad = isNaN(val) || val < min;
    el.classList.toggle('is-invalid', bad);
    if (err) {
      err.textContent = bad ? `${label} must be greater than 0` : '';
      err.classList.toggle('visible', bad);
    }
    if (bad) valid = false;
  });
  return valid;
}

function clearValidation() {
  VALIDATED_FIELDS.forEach(({ id, errId }) => {
    document.getElementById(id)?.classList.remove('is-invalid');
    const err = document.getElementById(errId);
    if (err) { err.textContent = ''; err.classList.remove('visible'); }
  });
}

function getDims() {
  return {
    length: +document.getElementById('f-length').value || 0,
    width:  +document.getElementById('f-width').value  || 0,
    height: +document.getElementById('f-height').value || 0,
    floor_thickness:      +document.getElementById('f-floor-thick').value  || 0,
    panel_thickness:      +document.getElementById('f-panel-thick').value  || 0,
    insulation_thickness: +document.getElementById('f-insul-thick').value  || 0,
    num_axles: +document.getElementById('f-axles').value || 2,
    num_doors: +document.getElementById('f-doors').value || 2,
  };
}

function updateGeo() {
  const d = getDims();
  const wallA = (d.length * d.height * 2).toFixed(2);
  const roofA = (d.length * d.width).toFixed(2);
  const floorA = (d.length * d.width).toFixed(2);
  const frontA = (d.width * d.height * 2).toFixed(2);
  const total = (+wallA + +roofA + +floorA + +frontA).toFixed(2);
  document.getElementById('geo-summary').innerHTML =
    `Wall: ${wallA} m²&nbsp; Roof: ${roofA} m²<br>` +
    `Floor: ${floorA} m²&nbsp; Front/Rear: ${frontA} m²<br>` +
    `<strong style="color:var(--blue-hi)">Total: ${total} m²</strong>`;
}

function updateTopbarTitle(bodyName) {
  const el = document.getElementById('topbar-title');
  if (!el) return;
  const def = el.dataset.default || el.textContent;
  if (bodyName) {
    el.innerHTML = `Now costing body type : <span style="color:#f0a500;font-weight:800;font-size:14px;letter-spacing:.5px">${escHtml(bodyName)}</span>`;
  } else {
    el.textContent = def;
  }
}

async function loadBOM(options = {}) {
  const preserveInputs = !!options.preserveInputs;
  const sel = document.getElementById('trailer-select');
  const tid = sel.value;
  const area = document.getElementById('bom-area');
  const counter = document.getElementById('bom-count');
  updateTopbarTitle(tid ? sel.selectedOptions[0]?.text : null);
  if (!tid) {
    area.innerHTML = '<div style="color:var(--text-dim);font-size:13px;padding:20px 0;text-align:center">Select a body type</div>';
    counter.textContent = '';
    bomData = [];
    clearOverrideSession();
    const bos = document.getElementById('body-options-section');
    if (bos) bos.style.display = 'none';
    return;
  }
  // Remember the focused trailer so the Body Templates page can auto-select it
  try { sessionStorage.setItem('focusedTrailerId', String(tid)); } catch(_) {}
  // Clear overrides and body option selections when the user picks a different trailer
  if (!preserveInputs) {
    priceOverrides = {};
    bodyOptionSelections = {};
    drdSrdEnabled = {};
    editBodyVarOverrides = null;   // pinned thicknesses only apply within an edit
    editReplay = null;             // replay state only applies within an edit
    discountKind = null; discountInput = 0;   // discount is per-costing, reset on a fresh trailer
    // Force the next renderBodyOptionsTree call to re-seed from
    // cfg_user_state_<tid>, since we just cleared bodyOptionSelections.
    _cfgStateSeededForTrailer = null;
    // Force re-seed of settings-page draft flags on next renderBodyOptionsFromDraft call.
    _draftFlagStateTrailer = null;
    draftCategoryRadioState = {};
    draftMasterlessCatState = {};
    draftFolderState = {};
    // v2 trailers: skip localStorage restore so the costing page always starts
    // from the configurator's defaults. The user is auditing the configurator
    // against the legacy Excel sheet — stale prior selections would corrupt the
    // test. Manual toggles within the session still work; they just don't survive
    // reloads while v2 is on.
    const _isV2 = !!(trailerDefaults[+tid] && trailerDefaults[+tid].configurator_v2);
    if (!_isV2) {
      loadBodyOptSel(tid);
      loadDrdSrdEnabled(tid);
    }
  }

  // Apply default dimensions and markup from the trailer's saved values
  const t = trailerDefaults[+tid];
  if (t && !preserveInputs) {
    if (t.default_length    != null) document.getElementById('f-length').value = t.default_length;
    if (t.default_width     != null) document.getElementById('f-width').value  = t.default_width;
    if (t.default_height    != null) document.getElementById('f-height').value = t.default_height;
    if (t.markup_percentage != null && t.markup_percentage > 0)
      document.getElementById('f-margin').value = (t.markup_percentage * 100).toFixed(1);
    updateGeo();
  }

  area.innerHTML = '<div style="padding:20px;text-align:center"><span class="spinner"></span></div>';
  try {
    bomData = await api('GET', `/api/trailers/${tid}/bom`);
    // Restore any temp overrides saved before a permanent-edit navigation
    const restoredCount = restoreOverridesFromSession(tid);
    if (restoredCount) toast(`${restoredCount} temporary price override${restoredCount !== 1 ? 's' : ''} restored`, 'info');
    // Seed DRD/SRD toggles from Excel defaults when no localStorage state exists
    _seedDrdSrdFromDefaults(bomData);
    // v2 trailers: also fetch the configurator's tree shape so the body-options
    // panel can render as the same nested tree the user sees in the admin
    // configurator. Non-fatal if it errors (we fall back to the flat panel).
    const _v2 = !!(trailerDefaults[+tid] && trailerDefaults[+tid].configurator_v2);
    if (_v2) {
      try { configuratorTree = await api('GET', `/api/configurator/trailers/${tid}/tree`); }
      catch(_) { configuratorTree = null; }
    } else {
      configuratorTree = null;
    }
    // Load the server-persisted configurator draft (settings-page tree) so the
    // body-options panel reflects the saved config on any browser/device.
    try {
      const _d = await api('GET', `/api/configurator/trailers/${tid}/draft`);
      _serverDraftCache[tid] = (_d && _d.draft) || null;
    } catch(_) { _serverDraftCache[tid] = undefined; }
    renderBodyOptions(bomData);
    refreshBomDisplay();
    scheduleCalc();  // auto-calculate once BOM is loaded
  } catch(e) {
    area.innerHTML = `<div style="color:var(--red);padding:20px">${e.message}</div>`;
  }
}

// ── BOM sort mode ─────────────────────────────────────────────────────────
const BOM_SORT_KEY = 'bom_sort_mode';
function getBomSortMode() {
  return localStorage.getItem(BOM_SORT_KEY) || 'sheet';
}
function sortedGroupEntries(groups, firstIdx, itemNameKey) {
  const mode = getBomSortMode();
  const entries = Object.entries(groups);
  if (mode === 'alpha') {
    entries.sort((a, b) => a[0].localeCompare(b[0]));
    const key = itemNameKey || 'material_name';
    entries.forEach(([, its]) => {
      its.sort((a, b) => String(a[key] || '').localeCompare(String(b[key] || '')));
    });
  } else {
    // Sheet-upload order: sections ordered by the lowest sort_order they contain,
    // items ordered by their own sort_order within the section.
    entries.sort((a, b) => (firstIdx[a[0]] ?? 0) - (firstIdx[b[0]] ?? 0));
    entries.forEach(([, its]) => {
      its.sort((a, b) => (a.__sortOrder ?? 0) - (b.__sortOrder ?? 0));
    });
  }
  return entries;
}
function onBomSortChange() {
  const mode = document.getElementById('bom-sort-mode').value;
  localStorage.setItem(BOM_SORT_KEY, mode);
  if (bomData && bomData.length) refreshBomDisplay();
  scheduleCalc();  // re-render the post-calc table too
}

/** Render BOM panel with currently-selected body options merged in, and update item count. */
function refreshBomDisplay() {
  const visible = getBomWithSelectedOptions(bomData);
  const counter = document.getElementById('bom-count');
  if (counter) counter.textContent = `${visible.length} items`;
  renderBOM(visible);
}
// Initialise control from localStorage once DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  const sel = document.getElementById('bom-sort-mode');
  if (sel) sel.value = getBomSortMode();
});

// ── Configuration panel resize handle ───────────────────────────────────────
// Mirrors the configurator's drag-to-resize behaviour: drag the right edge of
// the .calc-panel--config column to widen or narrow it; width persists in
// localStorage so the user's choice survives reloads.
const _CALC_CFG_W_KEY = 'calc_cfg_w';
function _applyCalcCfgWidth(px) {
  const shell = document.querySelector('.calc-shell');
  if (!shell) return;
  const clamped = Math.max(240, Math.min(720, px));
  shell.style.gridTemplateColumns = `${clamped}px 1fr 300px`;
}
document.addEventListener('DOMContentLoaded', () => {
  const shell = document.querySelector('.calc-shell');
  const cfg = document.querySelector('.calc-panel--config');
  if (!shell || !cfg) return;
  try {
    const saved = parseFloat(localStorage.getItem(_CALC_CFG_W_KEY));
    if (Number.isFinite(saved) && saved >= 240) _applyCalcCfgWidth(saved);
  } catch(_) {}
  // Inject the handle as a thin vertical strip on the config panel's right
  // edge. Absolute-positioned so it doesn't affect existing layout.
  const handle = document.createElement('div');
  handle.setAttribute('aria-label', 'Resize configuration panel');
  handle.style.cssText = 'position:absolute;top:0;right:-6px;bottom:0;width:12px;cursor:col-resize;z-index:5';
  // Visible 2px slot in the middle of the wider hit area
  const slot = document.createElement('div');
  slot.style.cssText = 'position:absolute;top:0;bottom:0;left:5px;width:2px;background:var(--border);transition:background .1s';
  handle.appendChild(slot);
  cfg.style.position = cfg.style.position || 'relative';
  cfg.appendChild(handle);
  handle.addEventListener('mouseenter', () => slot.style.background = 'var(--blue)');
  handle.addEventListener('mouseleave', () => { if (!handle.classList.contains('dragging')) slot.style.background = 'var(--border)'; });
  handle.addEventListener('mousedown', (e) => {
    e.preventDefault();
    handle.classList.add('dragging');
    slot.style.background = 'var(--blue)';
    document.body.style.cursor = 'col-resize';
    const startX = e.clientX;
    const startW = cfg.getBoundingClientRect().width;
    const onMove = (ev) => {
      _applyCalcCfgWidth(startW + (ev.clientX - startX));
    };
    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.body.style.cursor = '';
      handle.classList.remove('dragging');
      slot.style.background = 'var(--border)';
      const w = cfg.getBoundingClientRect().width;
      try { localStorage.setItem(_CALC_CFG_W_KEY, String(Math.round(w))); } catch(_) {}
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });
});

function renderBOM(items) {
  const area = document.getElementById('bom-area');
  if (!items.length) {
    area.innerHTML = '<div style="color:var(--text-dim);font-size:13px;padding:20px 0;text-align:center">No BOM items — add items in Admin → Trailer Templates</div>';
    return;
  }

  // Group by category
  const groups = {};
  const firstIdx = {};  // first appearance order per category (for sheet-order sort)
  items.forEach((it, i) => {
    const cat = it.category || 'Uncategorised';
    it.__sortOrder = (it.sort_order != null ? it.sort_order : i);
    if (!groups[cat]) { groups[cat] = []; firstIdx[cat] = it.__sortOrder; }
    else if (it.__sortOrder < firstIdx[cat]) firstIdx[cat] = it.__sortOrder;
    groups[cat].push(it);
  });
  const sortedEntries = sortedGroupEntries(groups, firstIdx);

  const preState = JSON.parse(localStorage.getItem(_bomCollapseKey()) || '{}');
  let html = '';
  let gIdx = 0;
  for (const [cat, its] of sortedEntries) {
    const gid       = 'pg' + gIdx++;
    const collapsed = !!preState[gid];
    const fc = { skin: 0, tape: 0, floor: 0, cleat: 0 };
    its.forEach(it => {
      if (it.skin_formula_id)   fc.skin++;
      if (it.taping_block_id)   fc.tape++;
      if (it.floor_plate_id)    fc.floor++;
      if (it.mounting_cleat_id) fc.cleat++;
    });
    const fdot = (color, label, n) => n > 0
      ? `<span title="${n} ${label} ${n===1?'item':'items'} in this section"
          style="display:inline-block;width:8px;height:8px;border-radius:50%;
            background:${color};margin-left:4px;vertical-align:middle"></span>` : '';
    const formulaDots = fdot('#58a6ff', 'skin formula', fc.skin)
                      + fdot('#f0a500', 'taping block', fc.tape)
                      + fdot('#3d9970', 'floor plate', fc.floor)
                      + fdot('#4a90d9', 'mounting cleat', fc.cleat);
    html += `<div class="parts-group">
      <div class="parts-group-title" onclick="toggleGroup(this,'${gid}')" title="Click to collapse / expand">
        <span class="grp-chevron">${collapsed ? '▶' : '▼'}</span> ${catTagPlain(cat)} ${cat}${formulaDots}
        <span style="margin-left:auto;color:var(--text-dim)">${its.length}</span>
      </div>
      <div class="parts-group-body"${collapsed ? ' style="display:none"' : ''}>`;
    its.forEach(it => {
      const mid          = it.material_id ?? '';
      const bid          = it.id ?? '';
      const ov           = priceOverrides[String(bid)];
      const outdatedLabel = !ov ? outdatedUpdateLabel(it.last_updated) : null;
      const recentLabel  = !ov ? recentUpdateLabel(it.last_updated) : null;
      const displayPrice = ov ? ov.newPrice : it.price;
      const priceClass   = ov ? 'price-override-cell' : (outdatedLabel ? 'price-outdated-cell' : (recentLabel ? 'price-recent-cell' : ''));
      const ovTooltip    = ov && ov.reason ? `Reason: ${ov.reason}` : (ov ? 'Quote-only price override' : null);
      const tooltipText  = ovTooltip || outdatedLabel || recentLabel;
      const tooltip      = tooltipText ? ` data-tooltip="${escHtml(tooltipText)}" title="${escHtml(tooltipText)}"` : '';
      const badge        = ov ? '<span class="override-badge">*</span>' : '';
      html += `<div class="assembly-item" data-id="${bid}"
          data-bom-id="${bid}"
          data-material-id="${mid}"
          data-material-name="${escHtml(it.material_name)}"
          data-price="${it.price}">
        <div class="assembly-row">
          <div>
            <div class="assembly-name">${escHtml(it.material_name)}</div>
            <div class="assembly-cat">${it.unit} · ${it.formula}</div>
          </div>
          <div style="text-align:right;min-width:90px">
            <div class="assembly-qty ${priceClass}"${tooltip} style="font-size:11px">@ ${fmt(displayPrice)}${badge}</div>
            <div class="assembly-qty" style="font-size:11px;color:var(--text-dim)">formula-based</div>
          </div>
        </div>
      </div>`;
    });
    html += `</div></div>`;
  }
  area.innerHTML = html;
  const lbl2 = document.getElementById('bom-collapse-lbl');
  if (lbl2) lbl2.style.display = 'flex';
  const sortLbl = document.getElementById('bom-sort-lbl');
  if (sortLbl) sortLbl.style.display = 'inline-flex';
}

// ── Body Options ──────────────────────────────────────────────────────────────

/** Returns items visible given the current body-option selections.
 *  DRD/SRD gating is controlled by the master drdSrdEnabled toggle, not by radio state.
 *  Rules:
 *  1. Body-option items: always hidden (shown in the Body Options panel instead).
 *  2. Section items with body_option_linked:
 *       - linked to a DRD/SRD group name (e.g. "DRD")  → shown when that group's toggle is ON
 *       - linked to a specific variant (e.g. "DRD EPS") → shown when that variant's radio is selected AND the group toggle is ON
 *  3. Items in DRD/SRD sections with no explicit link → shown when that group's toggle is ON.
 *  4. All other section items: always shown.
 */
function getBomWithSelectedOptions(items) {
  // When configurator_v2 is on, the configurator's gating rules (section
  // ownership via body_option_master_id, per-item bom_conditions, archived_at)
  // are authoritative — the legacy DRD/SRD prefix filter and per-row
  // body_option_linked filter below would double-filter and hide items the
  // configurator says should appear. Skip ALL legacy filtering in v2.
  const tidVal = document.getElementById('trailer-select')?.value;
  const trailerInfo = tidVal ? trailerDefaults[+tidVal] : null;
  const useV2 = !!(trailerInfo && trailerInfo.configurator_v2);

  if (useV2) {
    // v2: only filter out body-option master rows themselves (those still live
    // in the Body Options panel, not the BOM). Everything else passes here;
    // the server's _build_bom_items handles the real gating during /api/calculate.
    return items.filter(it => !it.is_body_option);
  }

  // Only count radio selections from groups whose master toggle is ON
  const selectedNames = new Set();
  items.forEach(it => {
    if (it.is_body_option && bodyOptionSelections[String(it.id)]) {
      const grp = it.body_option_group;
      if (_DRDSR_TOGGLE_GROUPS.includes(grp) && !drdSrdEnabled[grp]) return;
      selectedNames.add(it.material_name);
    }
  });

  return items.filter(it => {
    if (it.is_body_option) return false;

    // Section-level DRD/SRD pre-filter (runs BEFORE per-line gates):
    // when a row lives in a "DRD …" or "SRD …" section, the section's
    // master toggle must be ON regardless of any per-line
    // body_option_linked. Otherwise an SRD-section line gated by a
    // shared option (e.g. BAKERY BODY) would leak into the BOM when DRD
    // is selected — the workbook semantics require BOTH section-master
    // AND per-line gates to be true.
    if (it.bom_section) {
      const s = it.bom_section.toUpperCase();
      for (const grp of _DRDSR_TOGGLE_GROUPS) {
        if (s.startsWith(grp) && !drdSrdEnabled[grp]) return false;
      }
    }

    if (it.body_option_linked) {
      // Group-level link (e.g. "DRD"): show when toggle is ON
      if (_DRDSR_TOGGLE_GROUPS.includes(it.body_option_linked))
        return !!drdSrdEnabled[it.body_option_linked];
      // Variant-level link (e.g. "DRD EPS"): show when that radio is selected (toggle already gates selectedNames)
      return selectedNames.has(it.body_option_linked);
    }
    // Implicit gate: items in DRD/SRD sections without an explicit link
    // (also covered by the pre-filter above, but kept for clarity)
    if (it.bom_section) {
      const s = it.bom_section.toUpperCase();
      for (const grp of _DRDSR_TOGGLE_GROUPS) {
        if (s.startsWith(grp)) return !!drdSrdEnabled[grp];
      }
    }
    return true;
  });
}

// ── v2 tree-shaped body options panel ────────────────────────────────────────
// Persisted collapse state per trailer so the user's open/closed pattern
// survives reloads. Keyed by trailer id + node path string.
function _bomTreeCollapseKey(tid) { return `body_opt_tree_collapse_${tid}`; }
function _loadTreeCollapsed(tid) {
  try {
    const raw = localStorage.getItem(_bomTreeCollapseKey(tid));
    if (!raw) return null;  // null = unseen (collapse-all default)
    return new Set(JSON.parse(raw));
  } catch(_) { return null; }
}
function _saveTreeCollapsed(tid, set) {
  try { localStorage.setItem(_bomTreeCollapseKey(tid), JSON.stringify([...set])); } catch(_) {}
}

function _treeMasterIdFromOpt(opt) {
  const m = /^(?:opt-m|flag-m)(\d+)$/.exec(opt.id || '');
  return m ? parseInt(m[1], 10) : null;
}

// Map a tree-node master id back to the costing bomData row (so we can read
// price, formula, and read/write bodyOptionSelections by bom_id).
function _bomRowForMaster(masterId) {
  if (masterId == null) return null;
  return bomData.find(r => r.id === masterId && r.is_body_option);
}

// ── Settings-page draft body-options panel ───────────────────────────────────
// Reads the visual body configurator's localStorage draft and renders the full
// draft tree (folders + categories + flags) as the body-options panel.
// Categories inside radio/tickbox folders become radio buttons or checkboxes
// linked to bodyOptionSelections (master IDs). Flags become flag-name–keyed
// checkboxes linked to draftFlagState. Only used for v2 trailers with a draft.

// Server-persisted configurator drafts, fetched per trailer in loadBOM and
// cached here. The server is the source of truth; localStorage is only a
// fallback (transient fetch failure, or pre-migration data).
let _serverDraftCache = {};

function _readSettingsDraft(tid) {
  const cached = _serverDraftCache[tid];
  if (cached) return cached;
  try {
    const raw = localStorage.getItem(`visual-body-configurator-ui:${tid}`);
    return raw ? JSON.parse(raw) : null;
  } catch(_) { return null; }
}

function _saveDraftFlagState(tid) {
  try {
    localStorage.setItem(`cfg_user_state_${tid}`, JSON.stringify({ flags: draftFlagState, choice: {} }));
  } catch(_) {}
}

// Renders the settings-page draft tree into the body-options panel.
// Mirrors the Explorer hierarchy 1:1 — folders are headers (with optional toggle
// when folderMode != 'container'); categories with selectionMode='radio'/'tickbox'
// render as radio/checkbox inputs; flags with flagMode='radio'/'tickbox' likewise.
// Radio grouping: siblings that share the same parent AND the same mode form one group.
// Returns true if anything was rendered; false to fall back to legacy tree render.
function renderBodyOptionsFromDraft(draft, tid) {
  const section = document.getElementById('body-options-section');
  const list    = document.getElementById('body-options-list');
  if (!section || !list || !draft || !draft.rootIds || !draft.rootIds.length) return false;

  const nodes = draft.nodes || {};
  const hasContent = Object.values(nodes).some(n => n && (n.type === 'folder' || n.type === 'flag' || n.type === 'category'));
  if (!hasContent) return false;

  // Lookup: material_name.toUpperCase() → array of BOM master row ids.
  // A trailer can have multiple body_option masters with the same name (e.g. one in
  // the BODY OPTIONS group and another that owns the matching section). Toggling the
  // radio must flip ALL of them together so v2 section-ownership gating sees the
  // section's actual owner as selected.
  const masterIdsByName = {};
  bomData.forEach(r => {
    if (!r.is_body_option) return;
    const k = (r.material_name || '').toUpperCase();
    if (!masterIdsByName[k]) masterIdsByName[k] = [];
    masterIdsByName[k].push(r.id);
  });

  // Rename-safe lookup: SECTION_NAME.toUpperCase() → array of owner master row ids.
  // The settings-page draft stores categories by their SECTION name (sourceCategoryKey).
  // If the admin later renames the underlying MATERIAL, masterIdsByName[section_name]
  // misses (because the masters now carry the new material name). This lookup keys
  // off the section's own name and resolves to whichever master(s) own the section
  // via body_option_master_id — ID-based, so a material rename does not break it.
  const masterIdsBySectionName = {};
  if (configuratorTree && configuratorTree.groups) {
    const visitOption = (opt) => {
      // opt.id is like "opt-m1234" — the trailing id is the owning master row id.
      const m = /^opt-m(\d+)$/.exec(opt.id || '');
      const ownerId = m ? Number(m[1]) : null;
      (opt.sections || []).forEach(s => {
        const k = (s.name || '').toUpperCase();
        if (!k || ownerId == null) return;
        if (!masterIdsBySectionName[k]) masterIdsBySectionName[k] = [];
        if (!masterIdsBySectionName[k].includes(ownerId)) masterIdsBySectionName[k].push(ownerId);
      });
      (opt.linkedFlagGroups || []).forEach(fg => (fg.options || []).forEach(visitOption));
    };
    configuratorTree.groups.forEach(g => {
      (g.options || []).forEach(visitOption);
      // Group-level sections too (always-include and similar).
      (g.sections || []).forEach(s => {
        const k = (s.name || '').toUpperCase();
        // For group-level sections, the section may still have an owning master id
        // stored as bodyOptionMasterId.
        const ownerId = s.bodyOptionMasterId != null ? Number(s.bodyOptionMasterId) : null;
        if (!k || ownerId == null) return;
        if (!masterIdsBySectionName[k]) masterIdsBySectionName[k] = [];
        if (!masterIdsBySectionName[k].includes(ownerId)) masterIdsBySectionName[k].push(ownerId);
      });
    });
  }

  // Combined lookup for category nodes. Prefer the section-name path (rename-safe)
  // and fall back to material-name matching for trailers without a configurator
  // tree (or sections that have no owning master).
  function midsForCategory(node) {
    const key = (node.sourceCategoryKey || '').toUpperCase();
    if (!key) return [];
    const bySection = masterIdsBySectionName[key] || [];
    const byMaterial = masterIdsByName[key] || [];
    // Union, deduped. ID-keyed master rows from either source are equally valid —
    // we toggle them all in lockstep.
    const merged = [];
    [...bySection, ...byMaterial].forEach(id => { if (!merged.includes(id)) merged.push(id); });
    return merged;
  }

  // Helper: group siblings by parent+mode for radio constraint.
  function radioSiblings(node, modeField, modeValue) {
    const pid = node.parentId || null;
    return Object.values(nodes).filter(n =>
      n && n.type === node.type &&
      (n.parentId || null) === pid &&
      (n[modeField] || (modeField === 'flagMode' ? 'tickbox' : 'container')) === modeValue
    );
  }

  // Resolve a flag node's bound master row IDs. Identity is by ID (flagBindingId)
  // first — the admin-picked link can't drift when names are renamed. The flag
  // toggles ONLY its bound master, never any same-named siblings: those (e.g.
  // section-owner masters) are controlled by the category radio separately, so
  // the flag can mark a per-item condition off without dropping the whole section.
  function midsForFlag(node) {
    if (!node) return [];
    if (node.flagBindingId) {
      const seedRow = bomData.find(r => r.id === Number(node.flagBindingId));
      if (seedRow) return [seedRow.id];
      return [];
    }
    // No ID — fall back to the first master matching the bound name (or label).
    const nm = (node.flagBindingName || node.label || '').toUpperCase();
    const arr = masterIdsByName[nm];
    return arr && arr.length ? [arr[0]] : [];
  }

  // Helper: get all master IDs for a category node. Routes through midsForCategory,
  // which prefers the section-name → owner-master path (rename-safe) and falls back
  // to material-name matching.
  const midsFor = (n) => midsForCategory(n);

  // Returns all BOM master IDs reachable under a folder node (recursively).
  // Used to zero-out selections when a radio/tickbox folder is turned off.
  function _folderDescendantMids(nodeId) {
    const result = [];
    function walk(id) {
      const n = nodes[id];
      if (!n) return;
      if (n.type === 'category') midsForCategory(n).forEach(m => result.push(m));
      if (n.type === 'flag')     midsForFlag(n).forEach(m => result.push(m));
      (n.childIds || []).forEach(walk);
    }
    (nodes[nodeId]?.childIds || []).forEach(walk);
    return result;
  }

  // Re-seeds bodyOptionSelections / draftFlagState for every descendant of a
  // folder that just turned ON, using each node's draft-saved default values.
  // Also enforces radio constraint within any radio category groups in the branch.
  // Called when a radio/tickbox folder becomes active so BOM sections reappear.
  function _restoreFolderBranch(nodeId) {
    function walk(id) {
      const n = nodes[id];
      if (!n) return;
      if (n.type === 'folder') {
        // Recurse into sub-folders only if they are container OR currently on.
        const subMode = n.folderMode || 'container';
        if (subMode === 'container' || !!draftFolderState[n.id]) {
          (n.childIds || []).forEach(walk);
        }
        return;
      }
      if (n.type === 'category') {
        const mids = midsForCategory(n);
        if (mids.length) {
          // Default all category masters to ON when restoring an activated folder.
          // The radio-constraint pass below enforces mutex within radio groups.
          mids.forEach(m => { bodyOptionSelections[String(m)] = true; });
        }
      } else if (n.type === 'flag') {
        const mids = midsForFlag(n);
        if (mids.length) {
          mids.forEach(m => { bodyOptionSelections[String(m)] = Number(n.flagValue) === 1; });
        } else {
          const name = n.flagBindingName || n.label || '';
          draftFlagState[name] = Number(n.flagValue) === 1;
        }
      }
      (n.childIds || []).forEach(walk);
    }
    (nodes[nodeId]?.childIds || []).forEach(walk);

    // Enforce radio constraint for any radio category groups inside this branch.
    const radioGroups = new Map();
    function collectRadio(id) {
      const n = nodes[id];
      if (!n || n.type === 'folder') return;
      if (n.type === 'category' && (n.selectionMode || 'container') === 'radio') {
        const pid = String(n.parentId || 'root');
        if (!radioGroups.has(pid)) radioGroups.set(pid, []);
        radioGroups.get(pid).push(n);
      }
      (n.childIds || []).forEach(collectRadio);
    }
    (nodes[nodeId]?.childIds || []).forEach(collectRadio);
    radioGroups.forEach(group => {
      let onIdx = group.findIndex(n => midsForCategory(n).some(m => bodyOptionSelections[String(m)]));
      if (onIdx < 0) onIdx = group.findIndex(n => Number(n.selectionValue) === 1);
      if (onIdx < 0) onIdx = 0;
      group.forEach((n, i) => {
        const v = (i === onIdx);
        midsForCategory(n).forEach(m => { bodyOptionSelections[String(m)] = v; });
      });
      const sel = group[onIdx];
      if (sel?.sourceCategoryKey) draftCategoryRadioState[String(sel.parentId || 'root')] = sel.sourceCategoryKey;
    });
  }

  // Syncs drdSrdEnabled for each legacy DRD/SRD group from the current draft
  // folder + category state. Bridges the folder radio UI to the hard BOM gate
  // in runCalc/filterItems that checks drdSrdEnabled['DRD'] / ['SRD'].
  // Must be called after any folder toggle or DRD/SRD category change.
  function _syncDrdSrdFromDraft() {
    _DRDSR_TOGGLE_GROUPS.forEach(grp => {
      const matchingCats = Object.values(nodes).filter(n =>
        n && n.type === 'category' &&
        (n.sourceCategoryKey || '').toUpperCase() === grp
      );
      if (!matchingCats.length) return; // group not present in this draft — leave untouched

      const enabled = matchingCats.some(cat => {
        // Walk ancestor chain — if any selectable folder is OFF, this branch is dead.
        let pid = cat.parentId;
        while (pid) {
          const par = nodes[pid];
          if (!par) break;
          if (par.type === 'folder') {
            const m = par.folderMode || 'container';
            if ((m === 'radio' || m === 'tickbox') && !draftFolderState[par.id]) return false;
          }
          pid = par.parentId;
        }
        // Category is reachable through active folders — the group IS enabled.
        // We do NOT check bodyOptionSelections: the folder being active is the
        // sole gate for DRD/SRD sections; individual category selection is secondary.
        return true;
      });

      drdSrdEnabled[grp] = enabled;
    });
  }

  // Sync the DRD/SRD gate, and when the active rear door actually changed,
  // carry the rear-door insulation thickness onto the chosen door (zeroing the
  // other) so the {SRD …} formulas deduct correctly and the both-zero warning
  // doesn't fire on the freshly-selected door. Awaited by the v2 configurator
  // handlers so the PUT lands before the recalc.
  async function _syncDoorAndCarry(clickedDoor) {
    const _prevDoor = _DRDSR_TOGGLE_GROUPS.find(g => drdSrdEnabled[g]);
    _syncDrdSrdFromDraft();
    // Newly-active rear door: prefer an explicitly-clicked DRD/SRD selector
    // (category-radio bodies keep BOTH gates enabled, so the gate never flips),
    // else the gate that just turned on (folder-gated bodies).
    const _gate = _DRDSR_TOGGLE_GROUPS.find(g => drdSrdEnabled[g]);
    const newDoor = clickedDoor || (_gate && _gate !== _prevDoor ? _gate : null);
    if (newDoor) {
      const oldDoor = newDoor === 'DRD' ? 'SRD' : 'DRD';
      await _carryRearDoorThickness(newDoor, oldDoor);
      // Handlers toggle visibility without re-rendering, so refresh the panel to
      // show the carried thickness, EPS/PU selection + clear the warning.
      renderBodyOptions(bomData);
    }
  }

  // Seed state once per trailer load.
  if (_draftFlagStateTrailer !== tid) {
    _draftFlagStateTrailer = tid;

    // 1) Seed draftFlagState (only for flags WITHOUT a master binding) from draft flagValue.
    //    Bound flags flow through bodyOptionSelections (see step 6) — keyed by master ID.
    draftFlagState = {};
    Object.values(nodes).filter(n => n && n.type === 'flag').forEach(n => {
      if (midsForFlag(n).length) return;
      const name = n.flagBindingName || n.label || '';
      draftFlagState[name] = Number(n.flagValue) === 1;
    });

    // 2) Override draftFlagState from saved cfg_user_state if present.
    try {
      const rawCfg = localStorage.getItem(`cfg_user_state_${tid}`);
      if (rawCfg) {
        const cfgState = JSON.parse(rawCfg);
        Object.entries(cfgState.flags || {}).forEach(([name, on]) => {
          if (name in draftFlagState) draftFlagState[name] = !!on;
        });
      }
    } catch(_) {}

    // 4) Seed bodyOptionSelections from draft selectionValue, falling back to body_option_default.
    //    Apply the same on/off to ALL master rows sharing the name (handles trailers with
    //    duplicate masters where one owns the section).
    Object.values(nodes).filter(n => n && n.type === 'category').forEach(n => {
      const mids = midsFor(n);
      if (!mids.length) return;
      // Skip if any of the masters is already explicitly tracked.
      if (mids.some(mid => String(mid) in bodyOptionSelections)) return;
      let on;
      const catSelMode = n.selectionMode || 'container';
      if (Number(n.selectionValue) === 1) {
        on = true;
      } else if (catSelMode === 'container') {
        // Container mode = "always-included" (no user toggle in the UI).
        // Force ON so the BOM section and any linked items always appear.
        on = true;
      } else {
        // radio / tickbox: honour body_option_default as the initial pick.
        on = mids.some(mid => {
          const row = bomData.find(r => r.id === mid);
          return row && row.body_option_default;
        });
      }
      mids.forEach(mid => { bodyOptionSelections[String(mid)] = on; });
    });

    // 5) Enforce radio constraint on category siblings (selectionMode='radio').
    //    Tracks ALL siblings (master-bearing AND masterless) — the radio group
    //    in the DOM spans both kinds, so seeding must too.
    draftCategoryRadioState = {};
    const catRadioGroups = new Map();
    Object.values(nodes)
      .filter(n => n && n.type === 'category' && (n.selectionMode || 'container') === 'radio')
      .forEach(n => {
        const key = `${n.parentId || 'root'}`;
        if (!catRadioGroups.has(key)) catRadioGroups.set(key, []);
        catRadioGroups.get(key).push(n);
      });
    catRadioGroups.forEach((group, parentKey) => {
      const allMids = group.map(n => midsFor(n));
      // Find which member is currently "on": either a master is selected, or
      // selectionValue=1 wins. Default to the first in draft order.
      let onIndex = allMids.findIndex(mids => mids.some(mid => bodyOptionSelections[String(mid)]));
      if (onIndex < 0) onIndex = group.findIndex(n => Number(n.selectionValue) === 1);
      if (onIndex < 0) onIndex = 0;
      // Apply: master-bearing siblings get their masters set; the selected
      // member's sourceCategoryKey is recorded for masterless tracking.
      allMids.forEach((mids, i) => {
        const v = (i === onIndex);
        mids.forEach(mid => { bodyOptionSelections[String(mid)] = v; });
      });
      const selectedNode = group[onIndex];
      if (selectedNode && selectedNode.sourceCategoryKey) {
        draftCategoryRadioState[String(parentKey)] = selectedNode.sourceCategoryKey;
      }
    });

    // 5b) Seed draftMasterlessCatState for masterless TICKBOX categories.
    //     These have no body-option master to track via bodyOptionSelections, so
    //     their on/off state lives in a dedicated map keyed by sourceCategoryKey.
    draftMasterlessCatState = {};
    Object.values(nodes)
      .filter(n => n && n.type === 'category' && (n.selectionMode || 'container') === 'tickbox')
      .forEach(n => {
        const mids = midsFor(n);
        if (mids.length) return; // master-bearing tickboxes use bodyOptionSelections
        if (!n.sourceCategoryKey) return;
        draftMasterlessCatState[n.sourceCategoryKey] = Number(n.selectionValue) === 1;
      });

    // 6) Seed bodyOptionSelections for BOUND flags (ID-keyed). Each bound flag
    //    toggles ALL masters sharing its bound master's material name (lockstep
    //    flip so the section-owner master is in sync with the BODY-OPTIONS master).
    Object.values(nodes).filter(n => n && n.type === 'flag').forEach(n => {
      const mids = midsForFlag(n);
      if (!mids.length) return;
      // Skip if any of the masters is already tracked (user state takes precedence).
      if (mids.some(mid => String(mid) in bodyOptionSelections)) return;
      const on = Number(n.flagValue) === 1;
      mids.forEach(mid => { bodyOptionSelections[String(mid)] = on; });
    });

    // 7) Enforce radio constraint across ALL flag siblings (bound + unbound) in
    //    the same parent. They share one UI radio group so only one may be on.
    const flagRadioGroups = new Map();
    Object.values(nodes)
      .filter(n => n && n.type === 'flag' && (n.flagMode || 'tickbox') === 'radio')
      .forEach(n => {
        const key = `${n.parentId || 'root'}`;
        if (!flagRadioGroups.has(key)) flagRadioGroups.set(key, []);
        flagRadioGroups.get(key).push(n);
      });
    function isFlagOn(n) {
      const mids = midsForFlag(n);
      if (mids.length) return mids.some(mid => !!bodyOptionSelections[String(mid)]);
      const name = n.flagBindingName || n.label || '';
      return !!draftFlagState[name];
    }
    function setFlag(n, v) {
      const mids = midsForFlag(n);
      if (mids.length) {
        mids.forEach(mid => { bodyOptionSelections[String(mid)] = !!v; });
      } else {
        const name = n.flagBindingName || n.label || '';
        draftFlagState[name] = !!v;
      }
    }
    flagRadioGroups.forEach(group => {
      // The draft is authoritative for radio groups on load: the flag with
      // flagValue=1 is selected, all others off. All-off is allowed — a radio
      // group is "at most one", not "exactly one". Applied unconditionally so a
      // stale per-costing selection can't override the configured default, and
      // so a deliberately all-off group is not force-set to its first flag.
      const onIdx = group.findIndex(n => Number(n.flagValue) === 1);
      group.forEach((n, i) => setFlag(n, i === onIdx));
    });

    // 8) Seed draftFolderState for radio/tickbox folders from node.folderValue.
    draftFolderState = {};
    Object.values(nodes).filter(n => n && n.type === 'folder').forEach(n => {
      const mode = n.folderMode || 'container';
      if (mode === 'radio' || mode === 'tickbox') {
        draftFolderState[n.id] = Number(n.folderValue) === 1;
      }
    });
    // Enforce radio constraint: among sibling radio folders, exactly one is on.
    // Default to the first if none is marked on.
    const _folderRadioGroups = new Map();
    Object.values(nodes)
      .filter(n => n && n.type === 'folder' && (n.folderMode || 'container') === 'radio')
      .forEach(n => {
        const key = String(n.parentId || 'root');
        if (!_folderRadioGroups.has(key)) _folderRadioGroups.set(key, []);
        _folderRadioGroups.get(key).push(n);
      });
    _folderRadioGroups.forEach(group => {
      let onIndex = group.findIndex(n => draftFolderState[n.id]);
      if (onIndex < 0) onIndex = 0;   // default: first folder in group
      group.forEach((n, i) => { draftFolderState[n.id] = (i === onIndex); });
    });

    // 9) For folders that are OFF (radio/tickbox), zero out their descendants'
    //    bodyOptionSelections so they're excluded from the initial calculation.
    Object.values(nodes).filter(n => n && n.type === 'folder').forEach(n => {
      const mode = n.folderMode || 'container';
      if ((mode === 'radio' || mode === 'tickbox') && !draftFolderState[n.id]) {
        _folderDescendantMids(n.id).forEach(mid => { bodyOptionSelections[String(mid)] = false; });
      }
    });

    // 10) Sync drdSrdEnabled from the draft's initial folder/category state so
    //     the first BOM render respects which door group is active.
    _syncDrdSrdFromDraft();
  }

  // Colour palette — one colour per nesting depth, cycling if deeper.
  const DEPTH_COLORS = ['#f0922a', '#56b08a', '#c49a3c', '#9b72cf', '#d4706a'];

  const S = {
    lbl:     'display:flex;align-items:center;gap:6px;cursor:pointer;user-select:none;margin-bottom:4px;font-size:12px;line-height:1.4',
    inp:     'accent-color:var(--blue);width:13px;height:13px;cursor:pointer;flex-shrink:0',
    lblDim:  'display:flex;align-items:center;gap:6px;cursor:pointer;user-select:none;margin-bottom:4px;font-size:12px;line-height:1.4;opacity:0.7',
  };

  // Returns a depth-shaded left-border child block style.
  function childBlock(depth) {
    const c = DEPTH_COLORS[depth % DEPTH_COLORS.length];
    return `padding-left:12px;margin-left:5px;border-left:2px solid ${c}44;padding-top:3px;margin-top:2px`;
  }

  // Folder header: bold, coloured, uppercase with a small chevron prefix.
  function folderHeaderStyle(depth) {
    const c = DEPTH_COLORS[depth % DEPTH_COLORS.length];
    const mt = depth === 0 ? '14px' : '10px';
    const fs = depth === 0 ? '10px' : '9px';
    return `margin-top:${mt};margin-bottom:6px;font-size:${fs};font-weight:700;letter-spacing:.7px;color:${c};text-transform:uppercase;display:flex;align-items:center;gap:4px`;
  }

  // Returns a click-to-edit bv-edit span if any of the given master IDs has a
  // variable_value set on its BOM row, otherwise returns ''. Mirrors optLabel()
  // in the legacy renderer so both layouts show the editable metric suffix.
  function bvEditSpan(mids) {
    for (const mid of mids) {
      const row = bomData.find(r => r.id === mid);
      if (row && row.variable_value != null) {
        const nm = escHtml(row.material_name || '');
        return ` <span class="bv-edit" data-bom-id="${row.id}" data-name="${nm}"` +
          ` style="color:#58a6ff;font-size:10px;cursor:pointer;border-bottom:1px dotted #388bfd"` +
          ` title="Click to edit — referenced in formulas as {${nm}}"` +
          ` onclick="event.preventDefault();event.stopPropagation();editBodyVariable(this)">(${Number(row.variable_value).toFixed(3)} m)</span>`;
      }
    }
    return '';
  }

  // Recursive renderer.
  function renderNode(nodeId, depth) {
    const node = nodes[nodeId];
    if (!node) return '';

    if (node.type === 'folder') {
      const c    = DEPTH_COLORS[depth % DEPTH_COLORS.length];
      const mode = node.folderMode || 'container';
      const kids = node.childIds || [];

      if (mode === 'radio' || mode === 'tickbox') {
        // Selectable folder — renders with a radio/checkbox so the user can
        // pick one branch (radio) or toggle an entire branch on/off (tickbox).
        const isRadio = mode === 'radio';
        const pid     = node.parentId || 'root';
        const type    = isRadio ? 'radio' : 'checkbox';
        const grpAttr = isRadio ? ` name="dff-${pid}"` : '';
        const on      = !!draftFolderState[nodeId];
        let h = `<label style="${folderHeaderStyle(depth)}"><input type="${type}"${grpAttr} data-draft-folder="${nodeId}" ${on ? 'checked' : ''} style="${S.inp}"><span style="color:${c}">${node.label}</span></label>`;
        if (kids.length) {
          const inner = kids.map(cid => renderNode(cid, depth + 1)).join('');
          h += `<div data-folder-children="${nodeId}" style="${childBlock(depth)}${on ? '' : ';display:none'}">${inner}</div>`;
        }
        return h;
      }

      // Container (default): plain coloured header, no toggle.
      // data-jump-folder lets the click handler scroll to the first child BOM section.
      let h = `<div style="${folderHeaderStyle(depth)};cursor:pointer" data-jump-folder="${nodeId}"><span style="color:${c};font-size:8px">&#9658;</span>${node.label}</div>`;
      if (kids.length) {
        const inner = kids.map(cid => renderNode(cid, depth + 1)).join('');
        h += `<div style="${childBlock(depth)}">${inner}</div>`;
      }
      return h;
    }

    if (node.type === 'flag') {
      const name    = node.flagBindingName || node.label || '';
      const mode    = node.flagMode || 'tickbox';
      const isRadio = mode === 'radio';
      const type    = isRadio ? 'radio' : 'checkbox';
      const pid     = node.parentId || 'root';
      const grpAttr = isRadio ? ` name="dff-${pid}"` : '';
      const esc     = name.replace(/&/g, '&amp;').replace(/"/g, '&quot;');
      const mids    = midsForFlag(node);
      const lblStyle = depth > 1 ? S.lblDim : S.lbl;
      // Resolve parent category key so clicking the flag label also jumps to its BOM section.
      const parentNode = node.parentId ? nodes[node.parentId] : null;
      const flagJumpKey = parentNode && parentNode.type === 'category'
        ? (parentNode.sourceCategoryKey || parentNode.label || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;')
        : '';
      const flagJumpAttr = flagJumpKey ? ` data-jump-cat="${flagJumpKey}"` : '';
      if (mids.length) {
        // Bound flag → toggles BOM masters by ID. UI shows the flag label but state
        // lives in bodyOptionSelections, keyed by master row id.
        const on = mids.some(mid => !!bodyOptionSelections[String(mid)]);
        return `<label style="${lblStyle}"><input type="${type}"${grpAttr} data-draft-flag-mids="${mids.join(',')}" data-draft-flag-name="${esc}" ${on ? 'checked' : ''} style="${S.inp}"><span${flagJumpAttr}>${node.label}${bvEditSpan(mids)}</span></label>`;
      }
      // Unbound flag → name-only fallback via flag_overrides.
      const on = !!draftFlagState[name];
      return `<label style="${lblStyle}"><input type="${type}"${grpAttr} data-draft-flag="${esc}" ${on ? 'checked' : ''} style="${S.inp}"><span${flagJumpAttr}>${node.label}</span></label>`;
    }

    if (node.type === 'category') {
      const mids = midsForCategory(node);
      const mode = node.selectionMode || 'container';
      const isRadio = mode === 'radio';
      const isTickbox = mode === 'tickbox';
      let selfHtml;
      const keyEscCat = (node.sourceCategoryKey || node.label || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;');
      // container mode → always-included; show static label (no toggle).
      if (!isRadio && !isTickbox) {
        selfHtml = `<label style="${S.lbl}"><span style="display:inline-block;width:13px;color:var(--text-dim);text-align:center">•</span><span data-jump-cat="${keyEscCat}" style="cursor:pointer;color:#5b9bd5;font-weight:600" title="Jump to ${escHtml(node.label)} in BOM">${node.label}${bvEditSpan(mids)}</span></label>`;
      } else {
        const pid     = node.parentId || 'root';
        const grpAttr = isRadio ? ` name="dfc-${pid}"` : '';
        const type    = isRadio ? 'radio' : 'checkbox';
        const keyEsc  = keyEscCat;
        if (mids.length) {
          // Master-bearing category → toggle the local master row(s) directly.
          const on = mids.some(mid => !!bodyOptionSelections[String(mid)]);
          const allAttr = ` data-draft-cat-all="${mids.join(',')}"`;
          selfHtml = `<label style="${S.lbl}"><input type="${type}"${grpAttr} data-draft-cat="${mids[0]}"${allAttr} data-draft-cat-key="${keyEsc}" ${on ? 'checked' : ''} style="${S.inp}"><span data-jump-cat="${keyEsc}" title="Jump to ${escHtml(node.label)} in BOM">${node.label}${bvEditSpan(mids)}</span></label>`;
        } else {
          // Masterless category: still render the toggle. State is tracked by
          // sourceCategoryKey in draftCategoryRadioState; server-side inclusion is
          // driven by excluded_categories (section name) which already handles the
          // ungated-section case correctly.
          const on = isRadio
            ? (draftCategoryRadioState[String(pid)] === node.sourceCategoryKey)
            : !!draftMasterlessCatState[node.sourceCategoryKey]; // tickbox: tracked in draftMasterlessCatState
          selfHtml = `<label style="${S.lbl}"><input type="${type}"${grpAttr} data-draft-cat-key="${keyEsc}" data-draft-cat-masterless="1" ${on ? 'checked' : ''} style="${S.inp}"><span data-jump-cat="${keyEsc}" title="Jump to ${escHtml(node.label)} in BOM">${node.label}</span></label>`;
        }
      }
      // Render any flag/condition children nested under this category.
      const kids = (node.childIds || []).filter(cid => nodes[cid]);
      if (kids.length) {
        const inner = kids.map(cid => renderNode(cid, depth + 1)).join('');
        selfHtml += `<div style="${childBlock(depth)}">${inner}</div>`;
      }
      return selfHtml;
    }

    return '';
  }

  const html = (draft.rootIds || []).map(id => renderNode(id, 0)).join('');
  if (!html.trim()) return false;

  list.innerHTML = html;
  section.style.display = '';

  // Re-sync every input's `checked` state from current bodyOptionSelections /
  // draftFlagState. Lets a single toggle propagate visually to every other input
  // that references the same underlying master IDs (e.g. a flag click clearing
  // the masters that a sibling category radio shows).
  function syncInputs() {
    list.querySelectorAll('[data-draft-cat-all]').forEach(el => {
      const mids = (el.dataset.draftCatAll || '').split(',').filter(Boolean);
      el.checked = mids.some(mid => !!bodyOptionSelections[String(mid)]);
    });
    // Masterless categories: radios tracked by draftCategoryRadioState; tickboxes by draftMasterlessCatState.
    list.querySelectorAll('[data-draft-cat-masterless]').forEach(el => {
      if (el.type === 'radio') {
        const name = el.name || ''; // dfc-<parentId>
        const pid = name.startsWith('dfc-') ? name.slice(4) : '';
        el.checked = !!(pid && draftCategoryRadioState[pid] === el.dataset.draftCatKey);
      } else {
        el.checked = !!draftMasterlessCatState[el.dataset.draftCatKey];
      }
    });
    list.querySelectorAll('[data-draft-flag-mids]').forEach(el => {
      const mids = (el.dataset.draftFlagMids || '').split(',').filter(Boolean);
      el.checked = mids.some(mid => !!bodyOptionSelections[String(mid)]);
    });
    list.querySelectorAll('[data-draft-flag]').forEach(el => {
      el.checked = !!draftFlagState[el.dataset.draftFlag];
    });
    // Sync selectable folder inputs and their children visibility.
    list.querySelectorAll('[data-draft-folder]').forEach(el => {
      const on = !!draftFolderState[el.dataset.draftFolder];
      el.checked = on;
      const childDiv = list.querySelector(`[data-folder-children="${el.dataset.draftFolder}"]`);
      if (childDiv) childDiv.style.display = on ? '' : 'none';
    });
  }

  // Clear all sibling flags in the same radio group, regardless of store.
  function clearFlagRadioGroup(name) {
    list.querySelectorAll(`input[name="${name}"][data-draft-flag-mids]`).forEach(s => {
      (s.dataset.draftFlagMids || '').split(',').filter(Boolean)
        .forEach(mid => { bodyOptionSelections[String(mid)] = false; });
    });
    list.querySelectorAll(`input[name="${name}"][data-draft-flag]`).forEach(s => {
      draftFlagState[s.dataset.draftFlag] = false;
    });
  }

  // Wire bound-flag handlers — toggle BOM masters by ID via bodyOptionSelections.
  list.querySelectorAll('[data-draft-flag-mids]').forEach(el => {
    el.addEventListener('change', async () => {
      const myMids = (el.dataset.draftFlagMids || '').split(',').filter(Boolean);
      if (el.type === 'radio' && el.name) {
        clearFlagRadioGroup(el.name);
        myMids.forEach(mid => { bodyOptionSelections[String(mid)] = true; });
      } else {
        myMids.forEach(mid => { bodyOptionSelections[String(mid)] = el.checked; });
      }
      saveBodyOptSel();
      _saveDraftFlagState(tid);
      // Insulation EPS/PU radio switch → carry thickness to the selected side.
      if (el.type === 'radio' && myMids.length) {
        await _applyInsulationCopyZero(myMids[0]);
        renderBodyOptions(bomData); // refresh bv-edit text + re-run guard
        scheduleCalc();
        return;
      }
      syncInputs();
      scheduleCalc();
    });
  });

  // Wire unbound-flag handlers (legacy text-based via flag_overrides).
  list.querySelectorAll('[data-draft-flag]').forEach(el => {
    el.addEventListener('change', () => {
      if (el.type === 'radio' && el.name) {
        clearFlagRadioGroup(el.name);
      }
      draftFlagState[el.dataset.draftFlag] = el.checked;
      _saveDraftFlagState(tid);
      saveBodyOptSel();
      syncInputs();
      scheduleCalc();
    });
  });

  // Helper: clear all master selections for every sibling in a category radio
  // group (regardless of master-bearing vs masterless), and also wipe the
  // group's masterless selection slot.
  function clearCategoryRadioGroup(radioName) {
    const pid = radioName.startsWith('dfc-') ? radioName.slice(4) : '';
    list.querySelectorAll(`input[name="${radioName}"][data-draft-cat]`).forEach(s => {
      const siblingMids = (s.dataset.draftCatAll || s.dataset.draftCat).split(',').filter(Boolean);
      siblingMids.forEach(mid => { bodyOptionSelections[String(mid)] = false; });
    });
    if (pid) delete draftCategoryRadioState[pid];
  }

  // Wire master-bearing category handlers.
  list.querySelectorAll('[data-draft-cat]').forEach(el => {
    el.addEventListener('change', async () => {
      const myMids = (el.dataset.draftCatAll || el.dataset.draftCat).split(',').filter(Boolean);
      if (el.type === 'radio' && el.name) {
        clearCategoryRadioGroup(el.name);
        myMids.forEach(mid => { bodyOptionSelections[String(mid)] = true; });
        // Also remember this group's selected key — keeps draftCategoryRadioState
        // consistent for excluded_categories computation in runCalc.
        const pid = el.name.startsWith('dfc-') ? el.name.slice(4) : '';
        if (pid && el.dataset.draftCatKey) draftCategoryRadioState[pid] = el.dataset.draftCatKey;
      } else {
        myMids.forEach(mid => { bodyOptionSelections[String(mid)] = el.checked; });
      }
      await _syncDoorAndCarry(_doorFromSelectorName(el.closest('label')?.textContent || '')); // door-type change carries rear-door thickness
      saveBodyOptSel();
      // Insulation EPS/PU radio switch → carry thickness to the selected side.
      if (el.type === 'radio' && myMids.length) {
        await _applyInsulationCopyZero(myMids[0]);
        renderBodyOptions(bomData); // refresh bv-edit text + re-run guard
        scheduleCalc();
        return;
      }
      syncInputs();
      scheduleCalc();
    });
  });

  // Wire MASTERLESS category handlers (no local master to toggle — selection
  // is tracked by sourceCategoryKey and the server gates the section via the
  // excluded_categories name list).
  list.querySelectorAll('[data-draft-cat-masterless]').forEach(el => {
    el.addEventListener('change', async () => {
      if (el.type === 'radio' && el.name) {
        clearCategoryRadioGroup(el.name);
        const pid = el.name.startsWith('dfc-') ? el.name.slice(4) : '';
        if (pid && el.dataset.draftCatKey) draftCategoryRadioState[pid] = el.dataset.draftCatKey;
      } else if (el.type === 'checkbox' && el.dataset.draftCatKey) {
        // Masterless tickbox: persist toggle state so syncInputs() and
        // draftExcludedSections can read it correctly.
        draftMasterlessCatState[el.dataset.draftCatKey] = el.checked;
      }
      await _syncDoorAndCarry(_doorFromSelectorName(el.closest('label')?.textContent || '')); // door-type change carries rear-door thickness
      saveBodyOptSel();
      syncInputs();
      scheduleCalc();
    });
  });

  // Wire selectable folder (radio/tickbox) handlers.
  list.querySelectorAll('[data-draft-folder]').forEach(el => {
    el.addEventListener('change', async () => {
      const nodeId = el.dataset.draftFolder;
      const node   = nodes[nodeId];
      if (!node) return;
      const mode = node.folderMode || 'container';

      if (mode === 'radio' && el.name) {
        // Turn off every sibling radio folder in the same name group.
        list.querySelectorAll(`input[name="${el.name}"][data-draft-folder]`).forEach(sib => {
          const sibId = sib.dataset.draftFolder;
          if (sibId === nodeId) return;
          draftFolderState[sibId] = false;
          const sibDiv = list.querySelector(`[data-folder-children="${sibId}"]`);
          if (sibDiv) sibDiv.style.display = 'none';
          // Zero out the deactivated sibling branch so it's excluded from calc.
          _folderDescendantMids(sibId).forEach(mid => { bodyOptionSelections[String(mid)] = false; });
        });
      }

      draftFolderState[nodeId] = el.checked;
      const myDiv = list.querySelector(`[data-folder-children="${nodeId}"]`);
      if (myDiv) myDiv.style.display = el.checked ? '' : 'none';

      if (el.checked) {
        // Folder turned on — re-seed its branch from draft defaults so BOM
        // sections reappear. (They were zeroed during initial seeding when the
        // folder was off, so we must restore them explicitly here.)
        _restoreFolderBranch(nodeId);
      } else {
        // Folder turned off — exclude its whole branch from the calculation.
        _folderDescendantMids(nodeId).forEach(mid => { bodyOptionSelections[String(mid)] = false; });
      }

      // Sync the legacy drdSrdEnabled gate so SRD/DRD BOM sections
      // appear/disappear correctly when door-type folders are toggled, and
      // carry the rear-door insulation thickness onto the chosen door.
      await _syncDoorAndCarry(_doorFromSelectorName(el.closest('label')?.textContent || ''));
      saveBodyOptSel();
      syncInputs();
      scheduleCalc();
    });
  });

  // Click on a category label or folder header → jump to matching BOM section.
  list.addEventListener('click', e => {
    const catSpan   = e.target.closest('[data-jump-cat]');
    const folderDiv = !catSpan && e.target.closest('[data-jump-folder]');

    let targetKey = null;
    if (catSpan) {
      targetKey = catSpan.dataset.jumpCat;
    } else if (folderDiv) {
      // Find the first child category of this folder node and use its section key.
      const fid = folderDiv.dataset.jumpFolder;
      const folderNode = nodes[fid];
      if (folderNode) {
        for (const cid of (folderNode.childIds || [])) {
          const child = nodes[cid];
          if (child && child.type === 'category' && child.sourceCategoryKey) {
            targetKey = child.sourceCategoryKey;
            break;
          }
        }
      }
    }

    if (!targetKey) return;
    const normKey = targetKey.toUpperCase().trim();

    // Locate the matching BOM group header row.
    let targetRow = null;
    document.querySelectorAll('.calc-grp-hdr').forEach(row => {
      if ((row.dataset.catName || '').toUpperCase().trim() === normKey) targetRow = row;
    });
    if (!targetRow) return;

    // Collapse every section, then open only the target.
    calcBomCollapseAll(true);
    const gid = targetRow.dataset.catId;
    if (gid) toggleCalcGroup(gid);   // expand the target (it was just collapsed above)

    // Scroll so the header sits at the top of the BOM area, then flash it.
    targetRow.scrollIntoView({ behavior: 'smooth', block: 'start' });
    targetRow.style.outline = '2px solid #5b9bd5';
    targetRow.style.outlineOffset = '-2px';
    setTimeout(() => { targetRow.style.outline = ''; targetRow.style.outlineOffset = ''; }, 1400);
  });

  return true;
}

function renderBodyOptionsTree(tree) {
  // Build the v2 tree HTML for the body-options panel on the costings page.
  // Mirrors the configurator's structure 1:1 but render-only (selections
  // flow through bodyOptionSelections, the same dict used by /api/calculate).
  const section = document.getElementById('body-options-section');
  const list    = document.getElementById('body-options-list');
  if (!section || !list) return;
  if (!tree || !tree.groups || !tree.groups.length) {
    section.style.display = 'none';
    return;
  }
  const tid = +document.getElementById('trailer-select').value;
  // First-load defaults to all-collapsed; subsequent loads honour saved state.
  let collapsed = _loadTreeCollapsed(tid);
  if (collapsed === null) {
    collapsed = new Set();
    tree.groups.forEach(g => collapsed.add(g.id));
    _saveTreeCollapsed(tid, collapsed);
  }
  // Seed every master's selection from body_option_default, but only when
  // the master isn't already present in bodyOptionSelections (so user toggles
  // and prior session state aren't clobbered).
  const allMasters = [];
  const visitGroup = (g) => {
    (g.options || []).forEach(o => {
      const mid = _treeMasterIdFromOpt(o);
      if (mid != null) allMasters.push({ masterId: mid, name: o.name });
      (o.linkedFlagGroups || []).forEach(visitGroup);
      (o.sections || []).forEach(s => (s.flags || []).forEach(f => {
        const fmid = _treeMasterIdFromOpt(f);
        if (fmid != null) allMasters.push({ masterId: fmid, name: f.name });
      }));
    });
    (g.bundles || []).forEach(b => (b.options || []).forEach(o => {
      const mid = _treeMasterIdFromOpt(o);
      if (mid != null) allMasters.push({ masterId: mid, name: o.name });
    }));
  };
  tree.groups.forEach(visitGroup);
  allMasters.forEach(({masterId}) => {
    if (!(String(masterId) in bodyOptionSelections)) {
      const row = _bomRowForMaster(masterId);
      // Match the configurator's seeding behaviour exactly:
      //   - Single-mode masters (gate radios + bundle picks): honour
      //     body_option_default — that's the radio that should start on.
      //   - Multi-mode masters (independent flag tick boxes): start OFF.
      //     The configurator preview doesn't auto-tick from body_option_default,
      //     so the costings page must match — anything else creates the
      //     "ticked here but not there" mismatch the user surfaced.
      // The configurator's persisted user state (cfg_user_state_<tid>) is
      // applied immediately below and overrides this seed when the user has
      // explicitly clicked something.
      const isSingleMode = row && (row.selection_mode || '').toLowerCase() === 'single';
      bodyOptionSelections[String(masterId)] = isSingleMode
        ? !!(row && row.body_option_default)
        : false;
    }
  });
  // Apply the configurator's persisted user state on top of the per-master
  // defaults — but ONLY on the first render per trailer load. After the user
  // starts clicking ticks on this page, re-rendering must NOT overwrite their
  // clicks with the stale configurator state (otherwise tick boxes appear
  // unresponsive). When the trailer changes we re-seed.
  if (_cfgStateSeededForTrailer !== tid) {
    try {
      const rawCfg = localStorage.getItem(`cfg_user_state_${tid}`);
      if (rawCfg) {
        const cfgState = JSON.parse(rawCfg);
        // 1) Flag ticks: keyed by flag NAME. Translate name → master id via allMasters list.
        const masterIdByName = {};
        allMasters.forEach(({masterId, name}) => { masterIdByName[name] = masterId; });
        Object.entries(cfgState.flags || {}).forEach(([name, on]) => {
          const mid = masterIdByName[name];
          if (mid != null) bodyOptionSelections[String(mid)] = !!on;
        });
        // 2) Choice gate radios: keyed by group id (e.g. "gate-24") → optId ("opt-m<mid>").
        Object.entries(cfgState.choice || {}).forEach(([grpId, optId]) => {
          const g = tree.groups.find(x => x.id === grpId && x.kind === 'choice');
          if (!g) return;
          const m = /^opt-m(\d+)$/.exec(optId);
          if (!m) return;
          const winnerMid = parseInt(m[1], 10);
          // Force this radio on, all other options in the gate off.
          (g.options || []).forEach(o => {
            const omid = _treeMasterIdFromOpt(o);
            if (omid != null) bodyOptionSelections[String(omid)] = (omid === winnerMid);
          });
        });
      }
    } catch(_) {}
    _cfgStateSeededForTrailer = tid;
  }
  // Mirror the configurator's default-active behaviour exactly:
  //   - Choice gates: when no option in a gate is on, force the gate's
  //     defaultId (which falls back to the first option if no master carries
  //     body_option_default=true) so the user starts on a valid radio state.
  //   - Bundles inside flag groups: same rule — at least one must be on.
  //   - Independent flags (tick): leave off by default — matches configurator.
  // Skips gates / bundles that already have a selection (user's prior state).
  const _ensureOneOn = (options, defaultId) => {
    const ids = options.map(o => _treeMasterIdFromOpt(o)).filter(x => x != null);
    if (!ids.length) return;
    const anyOn = ids.some(mid => bodyOptionSelections[String(mid)]);
    if (anyOn) return;
    const targetOpt = options.find(o => o.id === defaultId) || options[0];
    const targetMid = targetOpt ? _treeMasterIdFromOpt(targetOpt) : null;
    if (targetMid == null) return;
    // Set the target on; ensure all siblings are off (mutex).
    ids.forEach(mid => { bodyOptionSelections[String(mid)] = (mid === targetMid); });
  };
  tree.groups.forEach(g => {
    if (g.kind === 'choice') {
      _ensureOneOn(g.options || [], g.defaultId);
      // Linked flag groups under whichever option is active also need their
      // bundles seeded so the same defaults render in costings.
      (g.options || []).forEach(o => {
        (o.linkedFlagGroups || []).forEach(lg => {
          (lg.bundles || []).forEach(b => _ensureOneOn(b.options || [], b.defaultId));
        });
      });
    } else if (g.kind === 'flags') {
      (g.bundles || []).forEach(b => _ensureOneOn(b.options || [], b.defaultId));
    }
  });

  // ── Markup helpers ────────────────────────────────────────────────────────
  const esc = (s) => String(s || '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const chev = (k) => collapsed.has(k) ? '▶' : '▼';

  function renderOption(grp, opt, isActiveRadio) {
    const mid = _treeMasterIdFromOpt(opt);
    const sel = mid != null ? !!bodyOptionSelections[String(mid)] : false;
    // For choice gates, the option is a radio. Use mid for selection tracking.
    const indicator = `<span class="cfg-tree-radio ${sel ? 'on' : ''}"
      style="width:12px;height:12px;border-radius:50%;border:1px solid var(--border);display:inline-flex;align-items:center;justify-content:center;flex-shrink:0">
      ${sel ? '<span style="width:6px;height:6px;border-radius:50%;background:var(--blue);display:inline-block"></span>' : ''}
    </span>`;
    const row = _bomRowForMaster(mid);
    const priceTail = (row && row.price > 0)
      ? ` <span style="color:var(--text-dim);font-size:10px">(${fmt(row.price)})</span>`
      : '';
    const star = (opt.id === grp.defaultId) ? ` <span style="color:#f0a500;font-size:10px;margin-left:4px">★</span>` : '';
    return `<div class="bot-opt-row" data-kind="choice" data-grp="${esc(grp.id)}" data-opt="${esc(opt.id)}" data-mid="${mid ?? ''}"
      style="display:flex;align-items:center;gap:6px;padding:3px 8px 3px 24px;cursor:pointer;font-size:12px;
        color:${sel ? 'var(--text)':'var(--text-dim)'};font-weight:${sel ? 600:400}">
      ${indicator}<span>${esc(opt.name)}${priceTail}${star}</span>
    </div>`;
  }

  function renderFlagBundleOpt(bundle, opt) {
    const mid = _treeMasterIdFromOpt(opt);
    const sel = mid != null ? !!bodyOptionSelections[String(mid)] : false;
    const indicator = `<span class="cfg-tree-radio ${sel ? 'on' : ''}"
      style="width:12px;height:12px;border-radius:50%;border:1px solid var(--border);display:inline-flex;align-items:center;justify-content:center;flex-shrink:0">
      ${sel ? '<span style="width:6px;height:6px;border-radius:50%;background:#a371f7;display:inline-block"></span>' : ''}
    </span>`;
    const row = _bomRowForMaster(mid);
    const priceTail = (row && row.price > 0)
      ? ` <span style="color:var(--text-dim);font-size:10px">(${fmt(row.price)})</span>`
      : '';
    return `<div class="bot-opt-row" data-kind="bundle" data-bundle="${esc(bundle.id)}" data-opt="${esc(opt.id)}" data-mid="${mid ?? ''}"
      style="display:flex;align-items:center;gap:6px;padding:3px 8px 3px 36px;cursor:pointer;font-size:12px;
        color:${sel ? 'var(--text)':'var(--text-dim)'};font-weight:${sel ? 600:400}">
      ${indicator}<span>${esc(opt.name)}${priceTail}</span>
    </div>`;
  }

  function renderFlagTick(opt) {
    const mid = _treeMasterIdFromOpt(opt);
    const sel = mid != null ? !!bodyOptionSelections[String(mid)] : false;
    const isRadio = (opt.style || 'tick') === 'radio';
    const box = isRadio
      ? `<span class="cfg-tree-radio ${sel ? 'on' : ''}"
           style="width:12px;height:12px;border-radius:50%;border:1px solid var(--border);display:inline-flex;align-items:center;justify-content:center;flex-shrink:0">
           ${sel ? '<span style="width:6px;height:6px;border-radius:50%;background:#a371f7;display:inline-block"></span>' : ''}
         </span>`
      : `<span style="width:13px;height:13px;border:1px solid ${sel ? '#a371f7' : 'var(--border)'};background:${sel ? '#a371f7' : 'transparent'};border-radius:3px;display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;color:#fff;font-size:11px">${sel ? '✓' : ''}</span>`;
    const row = _bomRowForMaster(mid);
    const priceTail = (row && row.price > 0)
      ? ` <span style="color:var(--text-dim);font-size:10px">(${fmt(row.price)})</span>`
      : '';
    return `<div class="bot-opt-row" data-kind="flag" data-opt="${esc(opt.id)}" data-mid="${mid ?? ''}" data-style="${isRadio ? 'radio' : 'tick'}"
      style="display:flex;align-items:center;gap:6px;padding:3px 8px 3px 28px;cursor:pointer;font-size:12px;
        color:${sel ? 'var(--text)':'var(--text-dim)'};font-weight:${sel ? 500:400}">
      ${box}<span>${esc(opt.name)}${priceTail}</span>
    </div>`;
  }

  function renderFlagGroupBody(fg) {
    let h = '';
    (fg.options || []).forEach(o => { h += renderFlagTick(o); });
    (fg.bundles || []).forEach(b => {
      h += `<div style="padding:4px 8px 4px 24px;font-size:10px;color:var(--text-dim);letter-spacing:.5px;text-transform:uppercase">${esc(b.label)} <span style="background:rgba(240,165,0,.15);color:#f0a500;padding:1px 6px;border-radius:8px;margin-left:4px;text-transform:none">pick one</span></div>`;
      (b.options || []).forEach(o => { h += renderFlagBundleOpt(b, o); });
    });
    return h;
  }

  function renderSection(sec) {
    // Renders a section's flags inline (sec.flags = section-bound flag masters).
    // BOM items themselves aren't shown here — the user sees those in the BOM
    // table below. The section row is just a label so flags grouped by section
    // are visible.
    if (!(sec.flags || []).length) return '';
    let h = `<div style="padding:4px 8px 4px 20px;font-size:10px;color:var(--text-dim);letter-spacing:.5px;text-transform:uppercase">▸ ${esc(sec.name)}</div>`;
    (sec.flags || []).forEach(f => { h += renderFlagTick(f); });
    return h;
  }

  function renderGroup(g) {
    const isCollapsed = collapsed.has(g.id);
    const badge = g.kind === 'choice'
      ? '<span style="background:rgba(240,165,0,.15);color:#f0a500;font-size:9px;padding:1px 6px;border-radius:8px;margin-left:6px">pick one</span>'
      : g.kind === 'flags'
      ? '<span style="background:rgba(163,113,247,.18);color:#a371f7;font-size:9px;padding:1px 6px;border-radius:8px;margin-left:6px">flags</span>'
      : '';
    let h = `<div class="bot-grp" data-grp="${esc(g.id)}" style="margin-bottom:6px">
      <div class="bot-grp-hdr" data-grp-toggle="${esc(g.id)}"
        style="display:flex;align-items:center;gap:6px;padding:4px 6px;cursor:pointer;font-size:10px;color:var(--text-dim);
          letter-spacing:1px;text-transform:uppercase;user-select:none;border-radius:4px">
        <span style="width:10px;opacity:.6">${chev(g.id)}</span>
        <span>${esc(g.label)}</span>${badge}
      </div>`;
    if (!isCollapsed) {
      h += `<div style="margin-top:2px">`;
      if (g.kind === 'always') {
        // Always-include sections — items render in the BOM, but section-bound
        // flags belong here.
        (g.sections || []).forEach(s => { h += renderSection(s); });
      } else if (g.kind === 'choice') {
        (g.options || []).forEach(o => {
          h += renderOption(g, o);
          // Linked flag groups nested under the option (only show when option is the active radio)
          const optSel = !!bodyOptionSelections[String(_treeMasterIdFromOpt(o))];
          if (optSel) {
            (o.linkedFlagGroups || []).forEach(lg => {
              const lk = `${g.id}/${o.id}/${lg.id}`;
              const lgCollapsed = collapsed.has(lk);
              h += `<div class="bot-grp" data-grp="${esc(lk)}" style="margin:2px 0 4px 28px;border-left:2px solid rgba(163,113,247,.35);padding-left:8px">
                <div class="bot-grp-hdr" data-grp-toggle="${esc(lk)}"
                  style="display:flex;align-items:center;gap:6px;padding:3px 4px;cursor:pointer;font-size:10px;color:var(--text-dim);
                    letter-spacing:1px;text-transform:uppercase;user-select:none;border-radius:4px">
                  <span style="width:10px;opacity:.6">${chev(lk)}</span>
                  <span>${esc(lg.label)}</span>
                  <span style="background:rgba(163,113,247,.18);color:#a371f7;font-size:9px;padding:1px 6px;border-radius:8px;margin-left:6px">flags</span>
                </div>`;
              if (!lgCollapsed) h += `<div>${renderFlagGroupBody(lg)}</div>`;
              h += `</div>`;
            });
            // Sections under the option carrying section-bound flags
            (o.sections || []).forEach(s => { h += renderSection(s); });
          }
        });
      } else if (g.kind === 'flags') {
        h += renderFlagGroupBody(g);
      }
      h += `</div>`;
    }
    h += `</div>`;
    return h;
  }

  let html = '';
  tree.groups.forEach(g => { html += renderGroup(g); });
  list.innerHTML = html;
  section.style.display = '';
  _bindTreeHandlers(tree, tid, collapsed);
}

function _bindTreeHandlers(tree, tid, collapsed) {
  const list = document.getElementById('body-options-list');
  if (!list) return;
  // Group toggle (chevron click anywhere on header)
  list.querySelectorAll('[data-grp-toggle]').forEach(el => {
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      const key = el.getAttribute('data-grp-toggle');
      if (collapsed.has(key)) collapsed.delete(key); else collapsed.add(key);
      _saveTreeCollapsed(tid, collapsed);
      renderBodyOptionsTree(tree);
    });
  });
  // Choice option radio click (sets gate selection + unsets siblings)
  list.querySelectorAll('[data-kind="choice"]').forEach(el => {
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      const grpId = el.getAttribute('data-grp');
      const optId = el.getAttribute('data-opt');
      const grp = tree.groups.find(g => g.id === grpId);
      if (!grp) return;
      // Set this option master to true, every other option in the gate to false.
      grp.options.forEach(o => {
        const mid = _treeMasterIdFromOpt(o);
        if (mid != null) bodyOptionSelections[String(mid)] = (o.id === optId);
      });
      saveBodyOptSel();
      saveLastSession();
      renderBodyOptionsTree(tree);
      scheduleCalc();
    });
  });
  // Bundle option radio click (within a flag-group bundle: mutex within the bundle)
  list.querySelectorAll('[data-kind="bundle"]').forEach(el => {
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      const bundleId = el.getAttribute('data-bundle');
      const optId = el.getAttribute('data-opt');
      // Find the bundle in any group (top-level or nested under linkedFlagGroups)
      let bundle = null;
      const findBundle = (g) => {
        if (!g) return;
        (g.bundles || []).forEach(b => { if (b.id === bundleId) bundle = b; });
        (g.options || []).forEach(o => (o.linkedFlagGroups || []).forEach(findBundle));
      };
      tree.groups.forEach(findBundle);
      if (!bundle) return;
      bundle.options.forEach(o => {
        const mid = _treeMasterIdFromOpt(o);
        if (mid != null) bodyOptionSelections[String(mid)] = (o.id === optId);
      });
      saveBodyOptSel();
      saveLastSession();
      renderBodyOptionsTree(tree);
      scheduleCalc();
    });
  });
  // Flag click — tick toggles, radio sets-only-one within its containing flag-group
  list.querySelectorAll('[data-kind="flag"]').forEach(el => {
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      const optId = el.getAttribute('data-opt');
      const style = el.getAttribute('data-style');
      const mid = parseInt(el.getAttribute('data-mid'), 10);
      if (!Number.isFinite(mid)) return;
      if (style === 'radio') {
        // Find the containing flag group so we can mutex its sibling radios.
        let fg = null;
        const findFG = (g) => {
          if (!g) return;
          if (g.kind === 'flags' && (g.options || []).some(o => o.id === optId)) { fg = g; return; }
          (g.options || []).forEach(o => (o.linkedFlagGroups || []).forEach(findFG));
        };
        tree.groups.forEach(findFG);
        if (fg) {
          fg.options.forEach(o => {
            if ((o.style || 'tick') !== 'radio') return;
            const omid = _treeMasterIdFromOpt(o);
            if (omid != null) bodyOptionSelections[String(omid)] = (o.id === optId);
          });
        } else {
          bodyOptionSelections[String(mid)] = true;
        }
      } else {
        bodyOptionSelections[String(mid)] = !bodyOptionSelections[String(mid)];
      }
      saveBodyOptSel();
      saveLastSession();
      renderBodyOptionsTree(tree);
      scheduleCalc();
    });
  });
}

// Public entry point — renders the panel (any of the three paths) and then
// re-applies the insulation both-zero guard so red highlight + warning persist
// across every re-render (radio switches, folder toggles, recalcs).
function renderBodyOptions(bomItems) {
  _renderBodyOptionsInner(bomItems);
  validateInsulationPairs();
}

function _renderBodyOptionsInner(bomItems) {
  const section = document.getElementById('body-options-section');
  const list    = document.getElementById('body-options-list');
  if (!section || !list) return;

  // v2 tree path: prefer the settings-page draft (visual-body-configurator-ui)
  // when one exists for this trailer, then fall back to the server-backed old
  // configurator tree. Legacy flat renderer runs for non-v2 trailers.
  const tidVal0 = document.getElementById('trailer-select')?.value;
  const trailerInfo0 = tidVal0 ? trailerDefaults[+tidVal0] : null;
  if (trailerInfo0 && trailerInfo0.configurator_v2) {
    const _settingsDraft = _readSettingsDraft(+tidVal0);
    if (_settingsDraft && renderBodyOptionsFromDraft(_settingsDraft, +tidVal0)) return;
    if (configuratorTree) { renderBodyOptionsTree(configuratorTree); return; }
  }

  let opts = bomItems.filter(it => it.is_body_option);
  if (!opts.length) { section.style.display = 'none'; return; }

  // v2 dedup: when a body type is on configurator_v2, the configurator has
  // (or will have) reorganised masters into gates + bundles. The legacy
  // BODY OPTIONS group often still has stale duplicates of the same material
  // (e.g. "24MM WISA TRANS FLOOR" lives both as a legacy flag AND as a
  // FLOOR TYPE gate option). Hide the dead legacy copies — keep the one with
  // selection_group set (= it's in a real gate/bundle).
  const tidVal = document.getElementById('trailer-select')?.value;
  const trailerInfo = tidVal ? trailerDefaults[+tidVal] : null;
  if (trailerInfo && trailerInfo.configurator_v2) {
    // v2: drop legacy "BODY OPTIONS" / DRD / SRD groups entirely — only show
    // masters that live in a user-created configurator gate. The configurator
    // is authoritative for v2 trailers; legacy import buckets and DRD/SRD
    // toggles are pre-v2 mechanisms that no longer apply.
    const isLegacyGroup = (it) => {
      const grp = (it.body_option_group || '').toUpperCase();
      return grp === 'BODY OPTIONS' || grp === 'DRD' || grp === 'SRD' || grp === 'MISC' || grp === '';
    };
    opts = opts.filter(it => !isLegacyGroup(it));
    // Dedup any remaining duplicate names (shouldn't happen post-filter, but safe).
    const byName = new Map();
    opts.forEach(it => {
      const existing = byName.get(it.material_name);
      if (!existing) byName.set(it.material_name, it);
    });
    opts = [...byName.values()];
  }

  // ── Seed + group ─────────────────────────────────────────────────────────
  const groups     = {};
  const groupOrder = [];
  const subgroupOrders = {};

  // Track which display labels came from the synthetic 'MISC' fallback so
  // the rename pencil can pass an empty old_name (meaning IS NULL OR '').
  const groupRawValue = {};   // display label -> raw body_option_group value (or '' for placeholder)
  opts.forEach(it => {
    const raw = it.body_option_group || '';
    const grp = raw || 'MISC';
    if (!(grp in groupRawValue)) groupRawValue[grp] = raw;
    const sub = it.body_option_subgroup || '';
    if (!groups[grp]) { groups[grp] = {}; groupOrder.push(grp); subgroupOrders[grp] = []; }
    if (!groups[grp][sub]) { groups[grp][sub] = []; subgroupOrders[grp].push(sub); }
    groups[grp][sub].push(it);
    if (!(String(it.id) in bodyOptionSelections)) {
      bodyOptionSelections[String(it.id)] = !!it.body_option_default;
    }
  });

  // Purge any stale true-values for DRD/SRD groups that are currently toggled OFF
  // (can happen when restoring from localStorage with a different toggle state)
  _DRDSR_TOGGLE_GROUPS.forEach(grp => {
    if (!drdSrdEnabled[grp] && groups[grp]) {
      Object.values(groups[grp]).flat().forEach(it => {
        bodyOptionSelections[String(it.id)] = false;
      });
    }
  });

  // ── Enforce radio constraint within each sub-group (only when group is ON) ─
  // Items with no subgroup (sub === '') are independent checkboxes — skip enforcement.
  // For v2 trailers the source of truth is selection_mode / selection_group on
  // each master, NOT the legacy subgroup STRING. Treat a subgroup as a real
  // mutex radio set only when every master in it is selection_mode='single'.
  // Mixed (tick + radio) or all-tick subgroups stay independent ticks — no
  // auto-select, no forcing-one-on.
  const _isV2trailer = !!(trailerInfo && trailerInfo.configurator_v2);
  groupOrder.forEach(grp => {
    const grpOn = _DRDSR_TOGGLE_GROUPS.includes(grp) ? !!drdSrdEnabled[grp] : true;
    subgroupOrders[grp].forEach(sub => {
      if (!sub) return;  // no subgroup → independent checkboxes, no radio constraint
      const its = groups[grp][sub];
      if (its.length <= 1) return;
      if (_isV2trailer) {
        const allSingle = its.every(it => (it.selection_mode || '').toLowerCase() === 'single');
        if (!allSingle) return;  // tick / mixed → independent, skip mutex enforcement
      }
      let found = false;
      its.forEach(it => {
        if (bodyOptionSelections[String(it.id)]) {
          if (found) bodyOptionSelections[String(it.id)] = false;
          else found = true;
        }
      });
      // Seed a default only when group is active (toggle ON); don't auto-select when OFF
      if (!found && grpOn) bodyOptionSelections[String(its[0].id)] = true;
    });
  });

  // ── Render ────────────────────────────────────────────────────────────────
  const chkStyle = 'accent-color:var(--blue);width:13px;height:13px;cursor:pointer';
  const lblStyle = 'display:flex;align-items:center;gap:6px;cursor:pointer;user-select:none;margin-bottom:3px;font-size:12px';

  // Inline-switch pill CSS
  const swStyle = [
    'position:relative;display:inline-block;width:36px;height:20px;flex-shrink:0',
    'input{opacity:0;width:0;height:0;position:absolute}',
  ].join('');
  const sliderBase = 'position:absolute;inset:0;border-radius:20px;transition:background .2s;cursor:pointer';

  function optLabel(it, inputHtml, extraLabelStyle) {
    // Body-option rows are now Body Variables — show their metric value, not a price.
    // The value is click-to-edit; saves via PUT /api/bom/{id}.
    const tail = it.variable_value != null
      ? ` <span class="bv-edit" data-bom-id="${it.id}" data-name="${escHtml(it.material_name)}"
          style="color:#58a6ff;font-size:10px;cursor:pointer;border-bottom:1px dotted #388bfd"
          title="Click to edit — referenced in formulas as {${escHtml(it.material_name)}}"
          onclick="event.preventDefault();event.stopPropagation();editBodyVariable(this)">(${Number(it.variable_value).toFixed(3)} m)</span>`
      : (it.price > 0 ? ` <span style="color:var(--text-dim);font-size:10px">(${fmt(it.price)})</span>` : '');
    return `<label style="${lblStyle}${extraLabelStyle || ''}">${inputHtml}<span>${escHtml(it.material_name)}${tail}</span></label>`;
  }

  let html = '';
  groupOrder.forEach(grp => {
    const isDrdSrd = _DRDSR_TOGGLE_GROUPS.includes(grp);
    const grpOn    = isDrdSrd ? !!drdSrdEnabled[grp] : true;
    const grpId    = `drd-srd-${grp}`;

    html += `<div style="margin-bottom:12px">`;

    if (isDrdSrd) {
      // ── Master ON/OFF toggle pill ──
      const bg     = grpOn ? 'var(--blue)' : '#888';
      const thumbX = grpOn ? '18px' : '2px';
      const renameDrdSrd = (typeof isAdmin !== 'undefined' && isAdmin)
        ? ` <span class="bo-grp-edit"
              data-old-name="${escHtml(groupRawValue[grp] || '')}"
              data-display-name="${escHtml(grp)}"
              title="Rename this group on this trailer"
              onclick="event.preventDefault();event.stopPropagation();renameBodyOptionGroup(this)"
              style="margin-left:6px;opacity:.4;font-size:11px;cursor:pointer">✎</span>`
        : '';
      html += `<label style="display:flex;align-items:center;gap:8px;cursor:pointer;user-select:none;margin-bottom:6px">
        <span style="${swStyle}">
          <input type="checkbox" id="${grpId}" ${grpOn ? 'checked' : ''}
            onchange="onDrdSrdToggle('${grp}', this.checked)" />
          <span style="${sliderBase};background:${bg}">
            <span style="position:absolute;top:2px;left:${thumbX};width:16px;height:16px;border-radius:50%;background:#fff;transition:left .2s;pointer-events:none"></span>
          </span>
        </span>
        <span style="font-size:12px;font-weight:600;letter-spacing:0.5px">${escHtml(grp)}${renameDrdSrd}</span>
      </label>`;

      if (!grpOn) {
        html += `</div>`;
        return;   // don't render EPS/PU options when toggle is OFF
      }
    } else {
      const renameBtn = (typeof isAdmin !== 'undefined' && isAdmin)
        ? ` <span class="bo-grp-edit"
              data-old-name="${escHtml(groupRawValue[grp] || '')}"
              data-display-name="${escHtml(grp)}"
              title="Rename this group on this trailer"
              onclick="event.preventDefault();event.stopPropagation();renameBodyOptionGroup(this)"
              style="margin-left:6px;opacity:.5;font-size:11px;cursor:pointer">✎</span>`
        : '';
      html += `<div style="font-size:10px;color:var(--text-dim);letter-spacing:0.5px;margin-bottom:4px;text-transform:uppercase">${escHtml(grp)}${renameBtn}</div>`;
    }

    subgroupOrders[grp].forEach(sub => {
      const its     = groups[grp][sub];
      const isRadio = its.length > 1 && !!sub;  // no subgroup → always checkboxes
      const gkey    = escHtml(_boSubgroupKey(its[0]));

      if (sub) {
        html += `<div style="margin-top:5px;font-size:10px;color:var(--text-dim);margin-bottom:2px">${escHtml(sub)}</div>`;
      }

      its.forEach(it => {
        // Skip the body-option row that IS the DRD/SRD master toggle —
        // the pill above already represents it, so rendering it again as
        // a child checkbox is redundant. Only fires when the row's
        // material_name matches the group name (DRD or SRD), so any
        // actual variants under those groups would still render.
        // We also keep bodyOptionSelections in sync with the pill state
        // here — without the visible checkbox, this is the only place
        // the master row's selection state stays current. The server's
        // filter at /api/calculate reads body_option_selections to build
        // selected_opt_groups, which in turn drives the section-level
        // gate; if these drift, DRD-section items disappear even when
        // the pill is on.
        if (isDrdSrd && it.material_name === grp) {
          bodyOptionSelections[String(it.id)] = !!drdSrdEnabled[grp];
          return;
        }
        const bid    = String(it.id);
        const sel    = bodyOptionSelections[bid] ? 'checked' : '';
        const isEps  = (it.material_name || '').toUpperCase().includes('EPS');
        const accent = isEps ? 'var(--orange)' : 'var(--blue)';
        const iStyle = `accent-color:${accent};width:13px;height:13px;cursor:pointer`;
        if (isRadio) {
          html += optLabel(it,
            `<input type="radio" name="bo-radio-${escHtml(grp)}-${escHtml(sub)}"
               data-bom-id="${bid}" data-group-key="${gkey}"
               style="${iStyle}" ${sel}
               onchange="onBodyOptRadioChange('${bid}','${gkey}')" />`
          );
        } else {
          html += optLabel(it,
            `<input type="checkbox" data-bom-id="${bid}"
               style="${iStyle}" ${sel}
               onchange="onBodyOptToggleChange(this)" />`
          );
        }
      });
    });

    html += `</div>`;
  });

  list.innerHTML = html;
  section.style.display = '';
}

// ── Collapse-all helpers ──────────────────────────────────────────────────────
function _calcSyncCheckbox() {
  const chk = document.getElementById('bom-collapse-all-chk');
  if (!chk) return;
  // Works for both pre-calc (.parts-group-title) and post-calc (.calc-grp-hdr)
  const hdrs = document.querySelectorAll('.calc-grp-hdr');
  if (hdrs.length) {
    const allCollapsed = [...hdrs].every(h => h.classList.contains('collapsed'));
    chk.checked = allCollapsed;
  }
}

function calcBomCollapseAll(collapse) {
  // Post-calc table groups
  const calcKey   = _calcCollapseKey();
  const calcState = {};
  document.querySelectorAll('.calc-grp-hdr').forEach(hdr => {
    const id     = hdr.dataset.catId;
    const rows   = document.querySelectorAll(`.calc-grp-row[data-cat-group="${id}"]`);
    const arrow  = hdr.querySelector('.grp-chevron');
    const hdrsub = hdr.querySelector('.calc-hdr-sub');
    hdr.classList.toggle('collapsed', collapse);
    arrow.textContent = collapse ? '▶' : '▼';
    rows.forEach(r => r.style.display = collapse ? 'none' : '');
    hdrsub.style.display = collapse ? '' : 'none';
    calcState[id] = collapse;
  });
  localStorage.setItem(calcKey, JSON.stringify(calcState));

  // Pre-calc card groups
  const preKey   = _bomCollapseKey();
  const preState = {};
  document.querySelectorAll('.parts-group-title').forEach((title, i) => {
    const gid  = 'pg' + i;
    const body = title.nextElementSibling;
    const arrow = title.querySelector('.grp-chevron');
    if (body) body.style.display = collapse ? 'none' : '';
    if (arrow) arrow.textContent = collapse ? '▶' : '▼';
    preState[gid] = collapse;
  });
  localStorage.setItem(preKey, JSON.stringify(preState));
}

// ── Pre-calc BOM panel collapse ───────────────────────────────────────────────
function _bomCollapseKey() {
  const tid = document.getElementById('trailer-select')?.value || '0';
  return 'bom-pre-collapse-' + tid;
}
function toggleGroup(el, catId) {
  const body  = el.nextElementSibling;
  const arrow = el.querySelector('.grp-chevron');
  const open  = body.style.display !== 'none';
  body.style.display = open ? 'none' : '';
  arrow.textContent  = open ? '▶' : '▼';
  if (catId !== undefined) {
    const state = JSON.parse(localStorage.getItem(_bomCollapseKey()) || '{}');
    state[catId] = open;   // true = collapsed
    localStorage.setItem(_bomCollapseKey(), JSON.stringify(state));
  }
}

// ── Post-calc BOM table collapse ──────────────────────────────────────────────
function _calcCollapseKey() {
  const tid = document.getElementById('trailer-select')?.value || '0';
  return 'bom-calc-collapse-' + tid;
}
function toggleCalcGroup(id) {
  const hdr    = document.querySelector(`.calc-grp-hdr[data-cat-id="${id}"]`);
  const rows   = document.querySelectorAll(`.calc-grp-row[data-cat-group="${id}"]`);
  const arrow  = hdr.querySelector('.grp-chevron');
  const hdrsub = hdr.querySelector('.calc-hdr-sub');
  const collapse = !hdr.classList.contains('collapsed');

  hdr.classList.toggle('collapsed', collapse);
  arrow.textContent = collapse ? '▶' : '▼';
  rows.forEach(r => r.style.display = collapse ? 'none' : '');
  hdrsub.style.display = collapse ? '' : 'none';

  if (!collapse) {
    const catName = hdr.dataset.catName;
    if (catName) try { sessionStorage.setItem('focusedBomSection', catName); } catch(_) {}
  }

  const state = JSON.parse(localStorage.getItem(_calcCollapseKey()) || '{}');
  state[id] = collapse;
  localStorage.setItem(_calcCollapseKey(), JSON.stringify(state));
  _calcSyncCheckbox();
}

function catTagPlain(cat) {
  const map = {
    'Steel': '🔩', 'Stainless Steel': '🔩', 'Aluminium': '⬡',
    'Resins & Adhesives': '🧴', 'Plywood & Timber': '🪵',
    'Rubber': '⬤', 'Paint & Consumables': '🎨',
    'Electrical': '⚡', 'Hardware & Fittings': '🔧',
    'Axles & Suspension': '⚙', 'Tyres & Rims': '○',
  };
  return map[cat] || '◆';
}

async function runCalc() {
  const tid = document.getElementById('trailer-select').value;
  if (!tid) return;
  if (!validateDims()) {
    toast('Fix the highlighted fields before calculating', 'warn');
    return;
  }
  clearValidation();

  // Build overrides as { "bomId": newPrice }; reasons sent in parallel map.
  const overridesPayload = {};
  const reasonsPayload   = {};
  Object.entries(priceOverrides).forEach(([bid, o]) => {
    overridesPayload[bid] = o.newPrice;
    if (o.reason) reasonsPayload[bid] = o.reason;
  });

  // Build excluded BOM sections from radio-category selections in the settings draft.
  // Per the rules doc, category radio behavior is driven by category.selectionMode === 'radio'.
  // For each parent containing radio-mode categories, unselected siblings are excluded.
  // The category → owner-master resolution uses BOTH the section-name path (via the
  // configurator tree, rename-safe) AND the material-name path (legacy fallback) so
  // renaming a material doesn't strand the category.
  const draftExcludedSections = [];
  if (_draftFlagStateTrailer === +tid) {
    const _draft = _readSettingsDraft(+tid);
    if (_draft && _draft.nodes) {
      // Material-name fallback table.
      const midsByMaterialName = {};
      bomData.forEach(r => {
        if (!r.is_body_option) return;
        const k = (r.material_name || '').toUpperCase();
        if (!midsByMaterialName[k]) midsByMaterialName[k] = [];
        midsByMaterialName[k].push(String(r.id));
      });
      // Section-name → owner-master table from the configurator tree.
      const midsBySectionName = {};
      if (configuratorTree && configuratorTree.groups) {
        const visitOption = (opt) => {
          const m = /^opt-m(\d+)$/.exec(opt.id || '');
          const ownerId = m ? m[1] : null;
          (opt.sections || []).forEach(s => {
            const k = (s.name || '').toUpperCase();
            if (!k || !ownerId) return;
            if (!midsBySectionName[k]) midsBySectionName[k] = [];
            if (!midsBySectionName[k].includes(ownerId)) midsBySectionName[k].push(ownerId);
          });
          (opt.linkedFlagGroups || []).forEach(fg => (fg.options || []).forEach(visitOption));
        };
        configuratorTree.groups.forEach(g => {
          (g.options || []).forEach(visitOption);
          (g.sections || []).forEach(s => {
            const k = (s.name || '').toUpperCase();
            const ownerId = s.bodyOptionMasterId != null ? String(s.bodyOptionMasterId) : null;
            if (!k || !ownerId) return;
            if (!midsBySectionName[k]) midsBySectionName[k] = [];
            if (!midsBySectionName[k].includes(ownerId)) midsBySectionName[k].push(ownerId);
          });
        });
      }
      // Group radio-mode categories by parent (so siblings form a radio group).
      const radioGroups = new Map();
      Object.values(_draft.nodes)
        .filter(n => n && n.type === 'category' && (n.selectionMode || 'container') === 'radio')
        .forEach(cat => {
          const key = String(cat.parentId || 'root');
          if (!radioGroups.has(key)) radioGroups.set(key, []);
          radioGroups.get(key).push(cat);
        });
      radioGroups.forEach((group, parentKey) => {
        const selectedMasterlessKey = draftCategoryRadioState[parentKey];
        group.forEach(cat => {
          if (!cat.sourceCategoryKey) return;
          const key = (cat.sourceCategoryKey || '').toUpperCase();
          const mids = [];
          (midsBySectionName[key] || []).forEach(m => { if (!mids.includes(m)) mids.push(m); });
          (midsByMaterialName[key] || []).forEach(m => { if (!mids.includes(m)) mids.push(m); });
          // "on" if any matching master is selected OR if this category is the
          // group's masterless-radio winner (tracked by sourceCategoryKey).
          let isOn = mids.some(mid => !!bodyOptionSelections[mid]);
          if (!isOn && !mids.length && selectedMasterlessKey === cat.sourceCategoryKey) {
            isOn = true;
          }
          if (!isOn) draftExcludedSections.push(cat.sourceCategoryKey);
        });
      });

      // Masterless TICKBOX categories: when off, their section must be excluded.
      // (Master-bearing tickboxes are already covered via bodyOptionSelections above.)
      Object.values(_draft.nodes)
        .filter(n => n && n.type === 'category' && (n.selectionMode || 'container') === 'tickbox')
        .forEach(cat => {
          if (!cat.sourceCategoryKey) return;
          const key = (cat.sourceCategoryKey || '').toUpperCase();
          const hasMaster = (midsBySectionName[key] || []).length > 0 ||
                            (midsByMaterialName[key] || []).length > 0;
          if (hasMaster) return; // master-bearing: bodyOptionSelections already gates it
          // Masterless tickbox: excluded when draftMasterlessCatState says off.
          if (!draftMasterlessCatState[cat.sourceCategoryKey]) {
            draftExcludedSections.push(cat.sourceCategoryKey);
          }
        });

      // Categories sitting inside an OFF radio/tickbox FOLDER: exclude their
      // section. The radio/tickbox passes above only catch categories whose
      // OWN selectionMode is radio/tickbox — a plain 'container' category
      // inside an off radio folder (e.g. the DRD DOORS / SRD DOORS door-type
      // folders) is otherwise missed: an off folder only zeroes
      // bodyOptionSelections for master-BEARING descendants, and these door
      // sections have no owning master.
      const _folderActive = (f) => (f.id in draftFolderState)
        ? !!draftFolderState[f.id]
        : Number(f.folderValue) === 1;
      Object.values(_draft.nodes)
        .filter(n => n && n.type === 'category' && n.sourceCategoryKey)
        .forEach(cat => {
          let pid = cat.parentId;
          while (pid) {
            const par = _draft.nodes[pid];
            if (!par) break;
            if (par.type === 'folder') {
              const m = par.folderMode || 'container';
              if ((m === 'radio' || m === 'tickbox') && !_folderActive(par)) {
                draftExcludedSections.push(cat.sourceCategoryKey);
                break;
              }
            }
            pid = par.parentId;
          }
        });
    }
  }
  const excludedCats = draftExcludedSections.length ? draftExcludedSections : undefined;

  // Build flag_overrides as a UNION of every alias each ON flag could be
  // referenced by in a per-item condition: label, flagBindingName, and the
  // bound master's current material name. This way a condition written against
  // any one of those names (e.g. "18MM = Y" against a flag labelled 18MM but
  // bound to a master named "18 MM WISA TRANS FLOOR") still resolves.
  // Mirrors the user's design rule: the rule lives on the item; toggling the
  // flag flips that item regardless of which alias the rule names.
  const flagOverridesPayload = {};
  if (_draftFlagStateTrailer === +tid) {
    const _draft = _readSettingsDraft(+tid);
    if (_draft && _draft.nodes) {
      Object.values(_draft.nodes).filter(n => n && n.type === 'flag').forEach(n => {
        const aliases = new Set();
        if (n.label) aliases.add(String(n.label));
        if (n.flagBindingName) aliases.add(String(n.flagBindingName));
        if (n.flagBindingId) {
          const row = bomData.find(r => r.id === Number(n.flagBindingId));
          if (row && row.material_name) aliases.add(String(row.material_name));
        }
        // Determine on/off: bound flags via bodyOptionSelections, unbound via draftFlagState.
        let on = false;
        if (n.flagBindingId) {
          on = !!bodyOptionSelections[String(n.flagBindingId)];
        } else {
          const k = n.flagBindingName || n.label || '';
          on = !!draftFlagState[k];
        }
        aliases.forEach(name => {
          // Don't downgrade an existing "on" to "off" if another alias already set it on.
          if (on) flagOverridesPayload[name] = true;
          else if (!(name in flagOverridesPayload)) flagOverridesPayload[name] = false;
        });
      });
    }
    // Also fold in any names from draftFlagState that we didn't already cover
    // (defensive: keeps legacy unbound-only flows working).
    Object.entries(draftFlagState).forEach(([name, on]) => {
      if (on && !(name in flagOverridesPayload)) flagOverridesPayload[name] = true;
    });
  }

  // Optional-section exclusions (EXTRAS / OPTIONAL EXTRAS). The per-row excl
  // set is keyed by trailer_id in localStorage so it survives body-type
  // switches — read it directly rather than filtering through lastResult.items,
  // which would be wrong (or stale) after the user changes body types.
  // The backend default-excludes any optional section whose id is NOT in
  // optional_sections_enabled, so we don't need to expand section-disabled
  // rows into user_excluded_bom_ids here.
  const _optExcl = (window.OptionalSections && tid)
    ? [...window.OptionalSections.loadRowExcl(+tid, 'c1')]
    : [];
  const _optEnabledIds = (window.OptionalSections && tid)
    ? [...window.OptionalSections.loadEnabled(+tid)]
    : [];

  lastCalcPayload = {
    trailer_type_id: +tid,
    dimensions: getDims(),
    profit_margin: +document.getElementById('f-margin').value || 0,
    overrides: overridesPayload,
    override_reasons: reasonsPayload,
    chassis: getChassisSelection(),
    body_option_selections: Object.keys(bodyOptionSelections).length ? bodyOptionSelections : undefined,
    excluded_categories: excludedCats,
    flag_overrides: Object.keys(flagOverridesPayload).length ? flagOverridesPayload : undefined,
    user_excluded_bom_ids: _optExcl,
    optional_sections_enabled: _optEnabledIds,
    body_variable_overrides: (editBodyVarOverrides && Object.keys(editBodyVarOverrides).length) ? editBodyVarOverrides : undefined,
  };

  // Edit-replay (legacy records with no snapshot): reproduce the saved result
  // exactly — include only the saved-included rows with their saved formulas, and
  // use the saved unit prices as the baseline with any user price edits on top.
  if (editReplay) {
    lastCalcPayload.include_all_items        = true;
    lastCalcPayload.user_excluded_bom_ids    = editReplay.userExcluded;
    lastCalcPayload.optional_sections_enabled = editReplay.optionalEnabled;
    lastCalcPayload.formula_overrides        = editReplay.formulaOverrides;
    lastCalcPayload.excluded_categories      = undefined;
    lastCalcPayload.body_option_selections   = undefined;
    lastCalcPayload.flag_overrides           = undefined;
    lastCalcPayload.overrides                = { ...editReplay.savedPrices, ...overridesPayload };
  }

  const status = document.getElementById('calc-status');
  document.getElementById('approve-btn').disabled = true;
  status.innerHTML = '<span class="spinner spinner-sm"></span> Calculating…';
  try {
    const result = await api('POST', '/api/calculate', lastCalcPayload);
    lastResult = result;
    lastBodyVars   = result.body_variables           || {};
    lastFormulaLib = result.formula_library_resolved || {};
    lastGlobalVars = result.global_variables         || {};
    _publishHelpContext(result);  // exposes liveResult + body for the AI Help chat
    renderSummary(result);
    renderBOMWithCosts(result.items, bomData);
    document.getElementById('approve-btn').disabled = false;
    status.textContent = '';
    saveLastSession();
    // Scroll back to a specific BOM row if requested (e.g. after formula edit)
    if (_scrollToBomId) {
      const target = document.querySelector(`[data-bom-id="${_scrollToBomId}"]`);
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'center' });
      _scrollToBomId = null;
    }
  } catch(e) {
    status.textContent = '';
    toast('Calculation failed: ' + e.message, 'error');
  }
}

let _pendingApproveBase = null;   // base payload waiting on user's dup choice
let _pendingNextVersion  = 2;

async function approveCosting() {
  if (!lastCalcPayload) { toast('Nothing to approve — select a trailer first', 'error'); return; }
  const customerId = document.getElementById('cust-select').value || null;

  _pendingApproveBase = {
    ...lastCalcPayload,
    customer_id: customerId ? +customerId : null,
  };

  // Editing an existing pending costing → ask whether to overwrite the original
  // record or save a new revision (the "validate the save" step). This replaces
  // the new-quote duplicate flow below.
  if (editingRecordId) {
    _pendingApproveBase.edit_record_id = editingRecordId;
    _pendingNextVersion = (editingVersion || 1) + 1;
    const idLabel = editingQuoteNumber || ('#' + editingRecordId);
    document.getElementById('edit-save-summary').innerHTML =
      `You are editing <strong style="color:var(--text-head)">${escHtml(idLabel)}</strong> · Rev${editingVersion}` +
      (_pendingApproveBase.customer_id ? '' : ' <span style="color:var(--text-dim)">(no customer linked)</span>');
    document.getElementById('edit-overwrite-ver').textContent = editingVersion;
    document.getElementById('edit-newver-ver').textContent    = _pendingNextVersion;
    const reuseWrap = document.getElementById('edit-reuse-qno-wrap');
    const reuseBox  = document.getElementById('edit-reuse-qno');
    const reuseVal  = document.getElementById('edit-reuse-qno-val');
    if (reuseBox) reuseBox.checked = true;            // default: keep the same quote number
    if (editingQuoteNumber && reuseWrap && reuseVal) {
      reuseVal.textContent = editingQuoteNumber;
      reuseWrap.style.display = '';
    } else if (reuseWrap) {
      reuseWrap.style.display = 'none';
    }
    document.getElementById('modal-edit-save').classList.remove('hidden');
    return;
  }

  // No customer → warn before saving
  if (!customerId) {
    document.getElementById('modal-no-customer').classList.remove('hidden');
    return;
  }

  // Check for existing costings for this customer + trailer (all-time)
  try {
    const trailerId = _pendingApproveBase.trailer_type_id;
    const dup = await api('GET', `/api/check-duplicate?customer_id=${customerId}&trailer_type_id=${trailerId}`);
    if (dup.has_duplicate) {
      const custName = allCustomers.find(c => String(c.id) === String(customerId))?.name || 'this customer';
      document.getElementById('dup-message').innerHTML =
        `<strong style="color:var(--text-head)">${escHtml(custName)}</strong> already has
         ${dup.count} costing${dup.count !== 1 ? 's' : ''} saved for this body type:`;
      document.getElementById('dup-version-list').innerHTML = dup.records
        .map(r => `<span style="color:var(--blue-hi)">Rev${r.version}</span> &nbsp;·&nbsp; ${escHtml(r.trailer)} &nbsp;·&nbsp; saved ${r.saved_at}`).join('<br>');
      document.getElementById('dup-next-ver').textContent = dup.next_version;
      _pendingNextVersion = dup.next_version;
      const reuseWrap = document.getElementById('dup-reuse-qno-wrap');
      const reuseBox  = document.getElementById('dup-reuse-qno');
      const reuseVal  = document.getElementById('dup-reuse-qno-val');
      if (reuseBox) reuseBox.checked = false;
      if (dup.parent_quote_number && reuseWrap && reuseVal) {
        reuseVal.textContent = dup.parent_quote_number;
        reuseWrap.style.display = '';
      } else if (reuseWrap) {
        reuseWrap.style.display = 'none';
      }
      document.getElementById('modal-duplicate').classList.remove('hidden');
      return;
    }
  } catch(e) { /* non-fatal — proceed */ }

  await _doApprove(null, null);
}

async function approveWithAction(action) {
  const reuseQno = action === 'new_version'
    && !!document.getElementById('dup-reuse-qno')?.checked;
  closeModal('modal-duplicate');
  await _doApprove(action, action === 'new_version' ? _pendingNextVersion : null, reuseQno);
}

// Edit-mode Save: 'overwrite' updates the original record in place; 'new_version'
// branches a fresh revision (reusing the quote number if the box is ticked).
async function editSaveAction(action) {
  const reuseQno = action === 'new_version'
    && !!document.getElementById('edit-reuse-qno')?.checked;
  closeModal('modal-edit-save');
  await _doApprove(action, action === 'new_version' ? _pendingNextVersion : null, reuseQno);
}

async function _doApprove(versionAction, nextVersion, reuseQno) {
  const btn      = document.getElementById('approve-btn');
  const doneBusy = showBusy(btn, 'Saving...');
  // Capture ratio at save time so the stored selling_price matches the calc panel total.
  const _ratioRaw = parseFloat(document.getElementById('f-ratio')?.value);
  const _ratioLbl = document.getElementById('f-ratio')?.selectedOptions?.[0]?.text || '';
  try {
    const result = await api('POST', '/api/approve', {
      ..._pendingApproveBase,
      version_action: versionAction,
      next_version:   nextVersion,
      reuse_quote_number: versionAction === 'new_version' ? !!reuseQno : false,
      ratio_value: (!isNaN(_ratioRaw) && _ratioRaw > 0) ? _ratioRaw : null,
      ratio_label: _ratioLbl || null,
      ui_snapshot: _buildUiSnapshot(),
      discount_kind:  discountKind,
      discount_input: discountKind ? discountInput : null,
    });
    lastRecordId   = result.record_id;
    lastResult     = result;
    lastBodyVars   = result.body_variables           || {};
    lastFormulaLib = result.formula_library_resolved || {};
    lastGlobalVars = result.global_variables         || {};
    _publishHelpContext(result);  // exposes liveResult + body for the AI Help chat
    renderSummary(result);
    document.getElementById('print-btn').disabled = false;
    document.getElementById('view-btn').disabled  = false;
    clearOverrideSession();
    const custName    = result.customer_name ? ` for ${result.customer_name}` : '';
    const verLabel    = result.version && result.version > 1 ? ` · Rev${result.version}` : '';
    const wasEditing  = !!_pendingApproveBase?.edit_record_id;
    if (wasEditing) {
      // Keep editing the saved record so a follow-up Save overwrites the right
      // revision (overwrite → same id; new_version → the freshly created one).
      editingRecordId    = result.record_id;
      editingVersion     = result.version || editingVersion;
      editingQuoteNumber = result.quote_number || editingQuoteNumber;
      showEditBanner({ customer_id: result.customer_id ?? _pendingApproveBase.customer_id });
      const verbed = versionAction === 'overwrite' ? 'Overwrote' : 'Saved new revision';
      toast(`${verbed} ${editingQuoteNumber || ('#'+result.record_id)}${custName}${verLabel}`, 'success');
    } else {
      toast(`Costing approved${custName}${verLabel} — saved as #${result.record_id}`, 'success');
    }
  } catch(e) {
    toast('Approve failed: ' + e.message, 'error');
    btn.disabled = false;
  } finally {
    doneBusy();
  }
}

// Per-section "show hidden lines" toggle state, keyed by trailer id. Tracks
// which sections currently show their soft-excluded (condition-failed) rows.
function _calcHiddenKey(tid) { return `bom_show_hidden_${tid}`; }
function _loadShowHidden(tid) {
  try {
    const raw = localStorage.getItem(_calcHiddenKey(tid));
    return new Set(raw ? JSON.parse(raw) : []);
  } catch(_) { return new Set(); }
}
function _saveShowHidden(tid, set) {
  try { localStorage.setItem(_calcHiddenKey(tid), JSON.stringify([...set])); } catch(_) {}
}
window.toggleShowHidden = function(cat) {
  const tidVal = document.getElementById('trailer-select')?.value;
  if (!tidVal) return;
  const tid = +tidVal;
  const set = _loadShowHidden(tid);
  if (set.has(cat)) set.delete(cat); else set.add(cat);
  _saveShowHidden(tid, set);
  if (typeof lastResult !== 'undefined' && lastResult) {
    renderBOMWithCosts(lastResult.items, bomData);
  }
};

// Local re-render of the BOM table from the cached lastResult so checkbox
// state cascades visually without waiting for the ~700ms scheduleCalc
// debounce + server roundtrip. Totals refresh on the subsequent recalc.
function _rerenderBOMLocal() {
  if (typeof lastResult !== 'undefined' && lastResult && lastResult.items) {
    renderBOMWithCosts(lastResult.items, bomData);
  }
}

// Costings 1: master toggle for an EXTRAS / OPTIONAL EXTRAS section. Flips
// the section into the optional-enabled set, clears any per-row exclusions
// inside it, then re-runs the cost calc so totals reflect the change.
window.toggleOptionalSectionCalc1 = function (cb) {
  const tidVal = document.getElementById('trailer-select')?.value;
  if (!tidVal || !window.OptionalSections) return;
  const tid = +tidVal;
  const sectionId = +cb.dataset.sectionId;
  let ids = [];
  try { ids = JSON.parse(decodeURIComponent(cb.dataset.bomIds || '[]')); } catch (_) { ids = []; }
  window.OptionalSections.toggleSection(tid, 'c1', sectionId, ids, !cb.checked);
  _rerenderBOMLocal();
  if (typeof scheduleCalc === 'function') scheduleCalc();
  else if (typeof calculate === 'function') calculate();
};

// Costings 1: per-row tick inside an enabled optional section.
window.toggleOptionalRowCalc1 = function (bomId, excluded, sectionId) {
  const tidVal = document.getElementById('trailer-select')?.value;
  if (!tidVal || !window.OptionalSections) return;
  const tid = +tidVal;
  const hdrTick = sectionId != null
    ? document.querySelector(`.calc-grp-hdr[data-section-id="${sectionId}"] .opt-sec-tick`)
    : null;
  let ids = [];
  try { ids = JSON.parse(decodeURIComponent(hdrTick?.dataset?.bomIds || '[]')); } catch (_) { ids = []; }
  window.OptionalSections.toggleRow(tid, 'c1', sectionId, ids, +bomId, !!excluded);
  _rerenderBOMLocal();
  if (typeof scheduleCalc === 'function') scheduleCalc();
  else if (typeof calculate === 'function') calculate();
};

// Costings 1: bulk select/deselect every row in an optional section.
window.bulkOptionalRowsCalc1 = function (ev, sectionId, idsAttr, selectAll) {
  if (ev) ev.stopPropagation();
  const tidVal = document.getElementById('trailer-select')?.value;
  if (!tidVal || !window.OptionalSections) return;
  let ids = [];
  try { ids = JSON.parse(decodeURIComponent(idsAttr || '[]')); } catch (_) { ids = []; }
  window.OptionalSections.bulkRows(+tidVal, 'c1', sectionId, ids, !!selectAll);
  _rerenderBOMLocal();
  if (typeof scheduleCalc === 'function') scheduleCalc();
  else if (typeof calculate === 'function') calculate();
};

// Costings 1: click-target version for the X / ✓ section badge (replaces
// the native checkbox UI). Takes an explicit enable flag.
window.setOptionalSectionCalc1 = function (ev, sectionId, idsAttr, enable) {
  if (ev) ev.stopPropagation();
  const tidVal = document.getElementById('trailer-select')?.value;
  if (!tidVal || !window.OptionalSections) return;
  let ids = [];
  try { ids = JSON.parse(decodeURIComponent(idsAttr || '[]')); } catch (_) { ids = []; }
  window.OptionalSections.toggleSection(+tidVal, 'c1', +sectionId, ids, !!enable);
  _rerenderBOMLocal();
  if (typeof scheduleCalc === 'function') scheduleCalc();
  else if (typeof calculate === 'function') calculate();
};

function renderBOMWithCosts(items, bomRef) {
  const area = document.getElementById('bom-area');
  if (!items.length) return;

  const tidVal = document.getElementById('trailer-select')?.value;
  const tidNum = tidVal ? +tidVal : 0;
  const showHiddenSet = _loadShowHidden(tidNum);

  const groups = {};
  const firstIdx = {};
  items.forEach((it, i) => {
    const cat = it.category || 'Uncategorised';
    // Look up the BOM row by bom_id (authoritative, per-section) — never by name
    const ref = it.bom_id != null
      ? (bomRef || []).find(b => String(b.id) === String(it.bom_id))
      : null;
    it.__sortOrder = ref && ref.sort_order != null ? ref.sort_order : i;
    if (!groups[cat]) { groups[cat] = []; firstIdx[cat] = it.__sortOrder; }
    else if (it.__sortOrder < firstIdx[cat]) firstIdx[cat] = it.__sortOrder;
    groups[cat].push(it);
  });
  const sortedEntries = sortedGroupEntries(groups, firstIdx, 'material');

  const calcState = JSON.parse(localStorage.getItem(_calcCollapseKey()) || '{}');

  let html = '<table style="width:100%;font-size:12px;border-collapse:collapse">';
  html += `<thead><tr style="background:var(--bg-panel)">
    <th style="padding:6px 8px;text-align:left;color:var(--text-dim);font-size:10px">Material</th>
    <th style="padding:6px 8px;text-align:right;color:var(--text-dim);font-size:10px">Qty</th>
    <th style="padding:6px 8px;text-align:right;color:var(--text-dim);font-size:10px">Unit Price</th>
    <th style="padding:6px 8px;text-align:right;color:var(--text-dim);font-size:10px">Cost</th>
  </tr></thead><tbody>`;

  // Costings 1 optional-section state — read once per render so every
  // section header / row references the same snapshot.
  const _optEnabled = (window.OptionalSections && tidNum)
    ? window.OptionalSections.loadEnabled(tidNum) : new Set();
  const _optRowExcl = (window.OptionalSections && tidNum)
    ? window.OptionalSections.loadRowExcl(tidNum, 'c1') : new Set();

  let gIdx = 0;
  for (const [cat, its] of sortedEntries) {
    const gid        = 'cg' + gIdx++;
    const collapsed  = !!calcState[gid];
    // Optional section flag carried on every item in the group (server-side).
    const _secOptional = its.some(x => x.section_is_optional);
    const _secId       = _secOptional ? (its.find(x => x.bom_section_id != null) || {}).bom_section_id : null;
    const _secEnabled  = _secOptional && _secId != null && _optEnabled.has(+_secId);
    const _catTotal   = its.reduce((s, it) => {
      const mult = (_singleSideMode && it.section_multiplier > 1) ? it.section_multiplier : 1;
      return s + (it.line_cost || 0) / mult;
    }, 0);
    const catTotal    = _catTotal;
    const subtotalTxt = hasFullCostAccess ? fmt(catTotal) : '••••';

    // Formula-presence dots: count items in this section linked to each formula type
    const fc = { skin: 0, tape: 0, floor: 0, cleat: 0 };
    its.forEach(it => {
      const ref = it.bom_id != null ? (bomRef || []).find(b => String(b.id) === String(it.bom_id)) : null;
      if (!ref) return;
      if (ref.skin_formula_name)   fc.skin++;
      if (ref.taping_block_name)   fc.tape++;
      if (ref.floor_plate_name)    fc.floor++;
      if (ref.mounting_cleat_name) fc.cleat++;
    });
    const fdot = (color, label, n) => n > 0
      ? `<span title="${n} ${label} ${n===1?'item':'items'} in this section"
          style="display:inline-block;width:8px;height:8px;border-radius:50%;
            background:${color};margin-left:4px;vertical-align:middle"></span>` : '';
    const formulaDots = fdot('#58a6ff', 'skin formula', fc.skin)
                      + fdot('#f0a500', 'taping block', fc.tape)
                      + fdot('#3d9970', 'floor plate', fc.floor)
                      + fdot('#4a90d9', 'mounting cleat', fc.cleat);
    const hasFormulaError = its.some(i => i.formula_error);
    const formulaErrorBadge = hasFormulaError
      ? `<span style="margin-left:8px;font-size:10px;font-weight:700;color:#e53935;letter-spacing:.3px">&#x26A0; Calculation Error on an Item ?</span>`
      : '';

    // Show-hidden eye toggle: per-section, off by default. When ON, soft-
    // excluded rows render struck-through under the section.
    const excludedCount = its.filter(x => x.excluded).length;
    const showHidden = showHiddenSet.has(cat);
    const eyeTitle = excludedCount === 0
      ? 'No hidden items in this section'
      : (showHidden ? `Hide the ${excludedCount} excluded line${excludedCount===1?'':'s'}` : `Show ${excludedCount} excluded line${excludedCount===1?'':'s'}`);
    const eyeBtn = excludedCount > 0
      ? `<span onclick="event.stopPropagation();toggleShowHidden(${JSON.stringify(cat).replace(/"/g,'&quot;')})"
            title="${escHtml(eyeTitle)}"
            style="margin-left:8px;cursor:pointer;font-size:11px;color:${showHidden ? '#a371f7' : 'rgba(230,237,243,.45)'};user-select:none">${showHidden ? '👁' : '👁‍🗨'} ${excludedCount}</span>`
      : '';

    // Optional section header: tick to enable, red text + tooltip. The
    // checkbox stops propagation so the row click still toggles collapse.
    const _optBomIds   = its.map(x => x.bom_id).filter(id => id != null);
    const _optIdsAttr  = encodeURIComponent(JSON.stringify(_optBomIds));
    const _hdrColor    = _secOptional ? 'var(--red,#e35d6a)' : 'var(--blue-hi)';
    const _hdrTitle    = _secOptional ? 'Non Standard items — tick to include in costing' : 'Click to collapse / expand';
    // Section toggle for optional sections — same native red checkbox
    // as SRD/DRD (calc2-cat-tick style). Checked (red filled X) means
    // EXCLUDED, unchecked (empty box) means included.
    const _optExcludedCount = _optBomIds.filter(id => !_secEnabled || _optRowExcl.has(+id)).length;
    const _optAll = _optBomIds.length > 0 && _optExcludedCount === _optBomIds.length;
    const _optSome = _optExcludedCount > 0 && !_optAll;
    const _optToggle   = _secOptional
      ? ` <input type="checkbox" class="opt-sec-tick" data-section-id="${_secId}" data-bom-ids="${_optIdsAttr}"
            ${_optAll ? 'checked' : ''}
            ${_optSome ? 'data-indeterminate="1"' : ''}
            onclick="event.stopPropagation()"
            onchange="toggleOptionalSectionCalc1(this)"
            title="${_optAll ? 'Untick to include every item in this section' : 'Tick to exclude every item in this section'}"
            style="cursor:pointer;width:14px;height:14px;vertical-align:middle;margin-right:6px;accent-color:var(--red)">`
      : '';
    // One pill-style bulk toggle — it flips between "Select all" and
    // "Deselect all" based on whether every row in the section is currently in.
    const _allRowsIncluded = _optBomIds.length > 0 && _secEnabled && _optBomIds.every(id => !_optRowExcl.has(+id));
    const _bulkSelectAll = !_allRowsIncluded;
    const _bulkBtn = _secOptional
      ? ` <button type="button"
            class="calc-bulk-pill-btn"
            onclick="bulkOptionalRowsCalc1(event, ${_secId}, '${_optIdsAttr}', ${_bulkSelectAll}); return false"
            title="${_bulkSelectAll ? 'Tick every item in this section' : 'Untick every item in this section'}"><span class="costing-state-pill calc-bulk-pill state-declined">${_bulkSelectAll ? '✓ Select all' : '✗ Deselect all'}</span></button>`
      : '';
    html += `<tr class="calc-grp-hdr${collapsed ? ' collapsed' : ''}${_secOptional ? ' opt-sec-hdr' : ''}${_secOptional && !_secEnabled ? ' opt-sec-disabled' : ''}" data-cat-id="${gid}" data-cat-name="${escHtml(cat)}" data-section-id="${_secId != null ? _secId : ''}"
        onclick="toggleCalcGroup('${gid}')"
        title="${escHtml(_hdrTitle)}"
        style="cursor:pointer;user-select:none">
      <td colspan="4" style="padding:6px 8px;background:var(--bg-panel)">
        ${_optToggle}<span class="grp-chevron" style="font-size:10px;margin-right:5px;color:var(--text-dim)">${collapsed ? '▶' : '▼'}</span>
        <span style="font-family:var(--font-mono);font-size:10px;color:${_hdrColor};letter-spacing:1px;text-transform:uppercase">${escHtml(cat)}</span><span style="font-family:var(--font-sans);font-size:10px;color:rgba(230,237,243,.55);margin-left:8px;letter-spacing:.2px;text-transform:none">— click on item for detail</span>${_bulkBtn}${formulaDots}${formulaErrorBadge}${eyeBtn}
        <span class="calc-hdr-sub" style="float:right;font-family:var(--font-mono);font-size:11px;color:${_hdrColor};font-weight:600;${collapsed ? '' : 'display:none'}">${subtotalTxt}</span>
      </td></tr>`;

    its.forEach(it => {
      // Soft-excluded rows: only render if the section's eye toggle is ON.
      // When rendered, the row is struck-through and dimmed; qty/price/cost
      // columns are muted so it's visually obvious nothing was counted.
      // Exception — items in optional sections always render so the user can
      // see and tick them. They're greyed when section disabled / unticked.
      if (it.excluded && !showHidden && !it.section_is_optional) return;
      // bom_id is authoritative — unique per section, set by the server.
      // Only match by id; do NOT fall back to name match (ambiguous across sections).
      const bid         = it.bom_id != null ? String(it.bom_id) : '';
      const bRef        = bid ? bomData.find(b => String(b.id) === bid) : null;
      const mid         = bRef ? String(bRef.material_id) : '';
      const ov          = bid ? priceOverrides[bid] : null;
      const isOv        = !!ov;
      const outdatedLabel = !isOv ? outdatedUpdateLabel(bRef?.last_updated) : null;
      const recentLabel = !isOv ? recentUpdateLabel(bRef?.last_updated) : null;
      // Bulk-updated within last 30 days → amber tint + tooltip
      const bulkAt = bRef?.last_bulk_update_at;
      const isBulk = !isOv && bulkAt && (Date.now() - new Date(bulkAt).getTime()) < 30*864e5;
      const bulkTip = isBulk ? `Items price updated by group: ${bRef.last_bulk_update_note || ''}` : null;
      const priceCls    = isOv ? 'price-override-cell' : (isBulk ? 'price-bulk-cell' : (outdatedLabel ? 'price-outdated-cell' : (recentLabel ? 'price-recent-cell' : '')));
      const ovTooltip   = isOv && ov.reason ? `Reason: ${ov.reason}` : (isOv ? 'Quote-only price override' : null);
      const tooltipText = ovTooltip || bulkTip || outdatedLabel || recentLabel;
      const tooltipAttr = tooltipText ? ` data-tooltip="${escHtml(tooltipText)}" title="${escHtml(tooltipText)}"` : '';
      const priceCell   = priceCls ? `class="${priceCls}"${tooltipAttr}` : (tooltipAttr ? tooltipAttr : '');
      const badge       = isOv ? '<span class="override-badge">*</span>' : '';
      const skinName    = bRef?.skin_formula_name;
      const skinRegion  = bRef?.skin_formula_region || 'standard';
      const skinItems   = bRef?.skin_formula_items || null;
      const skinBadge   = skinName ? `<span style="display:inline-block;margin-left:4px;font-size:9px;background:var(--blue);color:#fff;border-radius:3px;padding:1px 5px;vertical-align:middle;font-family:var(--font-sans);letter-spacing:.3px">◎ SKIN</span>` : '';
      const tapingName  = bRef?.taping_block_name;
      const tapingBadge = tapingName ? `<span title="Price from taping block: ${escHtml(tapingName)}" style="display:inline-block;margin-left:4px;font-size:9px;background:#1a1200;color:#f0a500;border:1px solid #b07800;border-radius:3px;padding:1px 5px;vertical-align:middle;font-family:var(--font-sans);letter-spacing:.3px">⊡ TAPING</span>` : '';
      const floorName   = bRef?.floor_plate_name;
      const floorBadge  = floorName ? `<span title="Price from floor plate: ${escHtml(floorName)}" style="display:inline-block;margin-left:4px;font-size:9px;background:#0a1f15;color:#3d9970;border:1px solid #2d7a57;border-radius:3px;padding:1px 5px;vertical-align:middle;font-family:var(--font-sans);letter-spacing:.3px">⊞ FLOOR</span>` : '';
      const cleatName   = bRef?.mounting_cleat_name;
      const cleatBadge  = cleatName ? `<span title="Price from mounting cleat: ${escHtml(cleatName)}" style="display:inline-block;margin-left:4px;font-size:9px;background:#0a1825;color:#4a90d9;border:1px solid #2a6db5;border-radius:3px;padding:1px 5px;vertical-align:middle;font-family:var(--font-sans);letter-spacing:.3px">⊟ CLEAT</span>` : '';
      const adjLineCost = (_singleSideMode && it.section_multiplier > 1) ? it.line_cost / it.section_multiplier : it.line_cost;
      const unitPrice   = hasFullCostAccess ? (fmt(it.unit_price) + badge + skinBadge + tapingBadge + floorBadge + cleatBadge) : '••••';
      const lineCost    = hasFullCostAccess ? fmt(adjLineCost) : '••••';
      const bomRowId    = bid;  // authoritative from server, already per-section
      const bomFormula  = bRef ? (bRef.formula || it.formula || '') : (it.formula || '');
      const skinSubtitle = skinName
        ? `<div style="font-size:10px;color:var(--blue);font-family:var(--font-mono);margin-top:1px">◎ ${escHtml(skinName)} · ${skinRegion.toUpperCase()}</div>`
        : '';
      const tapingSubtitle = tapingName
        ? `<div style="font-size:10px;color:#f0a500;font-family:var(--font-mono);margin-top:1px">⊡ ${escHtml(tapingName)}</div>`
        : '';
      const floorSubtitle = floorName
        ? `<div style="font-size:10px;color:#3d9970;font-family:var(--font-mono);margin-top:1px">⊞ ${escHtml(floorName)}</div>`
        : '';
      const cleatSubtitle = cleatName
        ? `<div style="font-size:10px;color:#4a90d9;font-family:var(--font-mono);margin-top:1px">⊟ ${escHtml(cleatName)}</div>`
        : '';
      const skinData   = (skinName && skinItems) ? ` data-skin-name="${escHtml(skinName)}" data-skin-region="${escHtml(skinRegion)}" data-skin-items='${JSON.stringify(skinItems).replace(/'/g,"&#39;")}'` : '';
      const tapingData = tapingName ? ` data-taping-id="${bRef.taping_block_id}"` : '';
      const floorData  = floorName  ? ` data-floor-id="${bRef.floor_plate_id}"` : '';
      const cleatData  = cleatName  ? ` data-cleat-id="${bRef.mounting_cleat_id}"` : '';
      // Excluded rows render struck-through + dimmed, with a tooltip showing
      // which condition kept them out.
      const excludedStyle = it.excluded
        ? 'text-decoration:line-through;opacity:.5;'
        : '';
      const excludedRowTooltip = it.excluded && it.excluded_reason
        ? ` title="Excluded — condition: ${escHtml(it.excluded_reason)}"`
        : (it.condition_summary
            ? ` title="Conditional row — rule: ${escHtml(it.condition_summary)}"`
            : '');
      // Condition chip: always shown when the row has any rule. Excluded form
      // reads "excluded · …" (purple, struck-through); included form reads
      // "when …" (same purple) so the user sees which lines are conditional
      // even before toggling a flag.
      const excludedBadge = it.excluded && it.excluded_reason
        ? ` <span style="display:inline-block;margin-left:6px;font-size:9px;background:rgba(163,113,247,.18);color:#a371f7;border-radius:3px;padding:1px 5px;font-family:var(--font-sans);letter-spacing:.3px;text-decoration:none">excluded · ${escHtml(it.excluded_reason)}</span>`
        : (it.condition_summary
            ? ` <span style="display:inline-block;margin-left:6px;font-size:9px;background:rgba(163,113,247,.18);color:#a371f7;border-radius:3px;padding:1px 5px;font-family:var(--font-sans);letter-spacing:.3px;text-decoration:none">when ${escHtml(it.condition_summary)}</span>`
            : '');
      // Optional-section per-row checkbox: rendered for every item in an
      // optional section so the row reflects ✓ included / ✗ excluded state
      // visually whether the section is enabled or not. When the section
      // is disabled, every item shows unchecked (X) and the checkbox is
      // disabled — the user must tick the section header first.
      const _rowOptional = !!it.section_is_optional;
      const _rowEnabled  = _rowOptional && _secEnabled;
      const _rowExcluded = _rowOptional && it.bom_id != null && _optRowExcl.has(+it.bom_id);
      const _rowIncluded = _rowOptional && _rowEnabled && !_rowExcluded;
      // Per-item tick — native red checkbox matching the SRD-style.
      // Checked (red filled X) = EXCLUDED, unchecked (empty box) = included.
      const _rowTick = _rowOptional
        ? `<input type="checkbox" class="opt-row-tick" data-bom-id="${bomRowId}"
              ${_rowIncluded ? '' : 'checked'}
              onclick="event.stopPropagation()"
              onchange="toggleOptionalRowCalc1(${bomRowId}, this.checked, ${_secId})"
              title="${_rowIncluded ? 'Tick to exclude this item' : 'Untick to include this item'}"
              style="cursor:pointer;width:13px;height:13px;vertical-align:middle;margin-right:6px;accent-color:var(--red,#e35d6a)">`
        : '';
      const _optStyle = _rowOptional && (!_rowIncluded) ? 'text-decoration:line-through;opacity:.5;' : '';
      html += `<tr class="calc-grp-row${skinName ? ' bom-skin-row' : ''}${tapingName ? ' bom-taping-row' : ''}${floorName ? ' bom-floor-row' : ''}${cleatName ? ' bom-cleat-row' : ''}${it.excluded ? ' bom-excluded-row' : ''}${_rowOptional ? ' opt-sec-row' : ''}" data-cat-group="${gid}"
          data-material-id="${mid}"
          data-bom-id="${bomRowId}"
          data-formula="${escHtml(bomFormula)}"
          data-qty="${it.quantity}"
          data-unit="${escHtml(it.unit || '')}"
          data-material-name="${escHtml(it.material)}"
          data-unit-price="${bRef ? bRef.price : it.unit_price}"${skinData}${tapingData}${floorData}${cleatData}${excludedRowTooltip}
          style="border-bottom:1px solid rgba(48,54,61,.4);${collapsed ? 'display:none;' : ''}${excludedStyle}${_optStyle}">
        <td style="padding:5px 8px">
          <div style="font-size:12px">${_rowTick}${escHtml(it.material)}${excludedBadge}</div>
          <div style="font-size:10px;color:var(--text-dim);font-family:var(--font-mono)">${it.formula}</div>
          ${it.formula_error ? `<div style="font-size:10px;font-weight:700;color:#e53935;margin-top:2px" title="${it.formula_unknown_vars && it.formula_unknown_vars.length ? 'Unknown token(s): {' + it.formula_unknown_vars.join('}, {') + '}' : 'Formula could not be evaluated'}">&#x26A0; Calculation Error ?${it.formula_unknown_vars && it.formula_unknown_vars.length ? ' — unknown: {' + escHtml(it.formula_unknown_vars.join('}, {')) + '}' : ''}</div>` : ''}
          ${skinSubtitle}${tapingSubtitle}${floorSubtitle}${cleatSubtitle}
        </td>
        <td style="padding:5px 8px;text-align:right;font-family:var(--font-mono);color:${it.formula_error ? '#e53935' : 'var(--text-dim)'};white-space:nowrap">${it.formula_error ? '— err —' : fmtNum(it.quantity,3) + ' ' + it.unit}</td>
        <td ${priceCell} style="padding:5px 8px;text-align:right;font-family:var(--font-mono);white-space:nowrap">${unitPrice}</td>
        <td style="padding:5px 8px;text-align:right;font-family:var(--font-mono);color:${isOv ? 'var(--red)' : 'var(--text-head)'};font-weight:600;white-space:nowrap">${it.excluded ? '<span style="color:var(--text-dim)">—</span>' : lineCost}</td>
      </tr>`;
    });
  }
  // ── Chassis breakdown (if enabled) ──────────────────────
  const _ch = (typeof lastResult !== 'undefined' && lastResult) ? lastResult.chassis : null;
  if (_ch && _ch.items && _ch.items.length) {
    const SELECTED_KINDS = new Set(['Suspension', 'Brake kit', 'Lifting axle', 'Tyre', 'Rim']);
    const selected  = _ch.items.filter(it => SELECTED_KINDS.has(it.kind));
    const constants = _ch.items.filter(it => !SELECTED_KINDS.has(it.kind));

    // Distinct chassis palette — amber/orange so it's clearly separate from the blue body sections
    const CH_ACCENT = '#FFB454';   // bright amber for headers
    const CH_DIVIDER_BG = 'linear-gradient(90deg,#3a2410 0%,#5a3415 50%,#3a2410 100%)';
    const CH_HDR_BG = '#2a1d0d';   // dark amber-tinged panel for sub-headers

    const renderChassisGroup = (title, rows, opts = {}) => {
      if (!rows.length) return '';
      const gid       = 'cg' + gIdx++;
      const collapsed = !!calcState[gid];
      const subtotal  = rows.reduce((s, r) => s + (r.line_cost || 0), 0);
      const subTxt    = hasFullCostAccess ? fmt(subtotal) : '••••';
      const accent    = opts.accent || CH_ACCENT;
      const bg        = opts.bg || CH_HDR_BG;
      const fontSize  = opts.fontSize || '10px';
      const indent    = opts.indent ? 'padding-left:22px;' : '';
      let h = `<tr class="calc-grp-hdr${collapsed ? ' collapsed' : ''}" data-cat-id="${gid}" data-cat-name="${escHtml(title)}"
          onclick="toggleCalcGroup('${gid}')"
          title="Click to collapse / expand"
          style="cursor:pointer;user-select:none">
        <td colspan="4" style="padding:6px 8px;background:${bg};${indent}">
          <span class="grp-chevron" style="font-size:10px;margin-right:5px;color:${accent}">${collapsed ? '▶' : '▼'}</span>
          <span style="font-family:var(--font-mono);font-size:${fontSize};color:${accent};letter-spacing:1px;text-transform:uppercase;font-weight:700">${escHtml(title)}</span>
          <span class="calc-hdr-sub" style="float:right;font-family:var(--font-mono);font-size:11px;color:${accent};font-weight:700;${collapsed ? '' : 'display:none'}">${subTxt}</span>
        </td></tr>`;
      rows.forEach(it => {
        const unitPrice = hasFullCostAccess ? fmt(it.unit_price) : '••••';
        const lineCost  = hasFullCostAccess ? fmt(it.line_cost)  : '••••';
        h += `<tr class="calc-grp-row" data-cat-group="${gid}"
            style="border-bottom:1px solid rgba(48,54,61,.4);${collapsed ? 'display:none' : ''}">
          <td style="padding:5px 8px">
            <div style="font-size:12px">${escHtml(it.label)}</div>
            <div style="font-size:10px;color:var(--text-dim);font-family:var(--font-mono)">${escHtml(it.kind)}</div>
          </td>
          <td style="padding:5px 8px;text-align:right;font-family:var(--font-mono);color:var(--text-dim)">${fmtNum(it.qty,2)} ea</td>
          <td style="padding:5px 8px;text-align:right;font-family:var(--font-mono)">${unitPrice}</td>
          <td style="padding:5px 8px;text-align:right;font-family:var(--font-mono);color:var(--text-head);font-weight:600">${lineCost}</td>
        </tr>`;
      });
      return h;
    };

    // Divider banner that visually separates chassis from body BOM
    const chTotal = hasFullCostAccess ? fmt(_ch.subtotal) : '••••';
    html += `<tr><td colspan="4" style="padding:0">
      <div style="background:${CH_DIVIDER_BG};
                  padding:10px 12px;margin-top:6px;display:flex;justify-content:space-between;align-items:center">
        <span style="font-family:var(--font-mono);font-size:13px;letter-spacing:2px;color:${CH_ACCENT};text-transform:uppercase">
          ▼▼  CHASSIS  ▼▼
        </span>
        <span style="font-family:var(--font-mono);font-size:13px;color:${CH_ACCENT}">${chTotal}</span>
      </div>
    </td></tr>`;

    // Selected components (suspension / brakes / tyres / rims / lifting axles)
    html += renderChassisGroup(
      `Selected — Axles · Brakes · Tyres`,
      selected,
      { accent: '#FFB454', bg: '#2a1d0d' }
    );

    // Constants — sub-divided by kind (running_gear, steel, etc.) with a different accent
    if (constants.length) {
      const byKind = {};
      constants.forEach(it => {
        const k = it.kind || 'other';
        (byKind[k] = byKind[k] || []).push(it);
      });
      // Constants section banner (lighter amber so the sub-groups under it stand apart)
      html += `<tr><td colspan="4" style="padding:6px 12px;background:#1f1608">
        <span style="font-family:var(--font-mono);font-size:11px;letter-spacing:1.5px;color:#FFD27A;text-transform:uppercase">
          Chassis Constants
        </span>
      </td></tr>`;
      // Stable, predictable order
      const ORDER = ['running_gear', 'steel', 'aluminium', 'electrical', 'paint', 'other'];
      const kinds = Object.keys(byKind).sort((a, b) => {
        const ai = ORDER.indexOf(a); const bi = ORDER.indexOf(b);
        return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
      });
      // Sub-groups share the Chassis Constants accent
      kinds.forEach(k => {
        const pretty = k.replace(/_/g, ' ');
        html += renderChassisGroup(
          `${pretty}`,
          byKind[k],
          { accent: '#FFD27A', bg: '#161b22', fontSize: '10px', indent: true }
        );
      });
    }
  }

  html += '</tbody></table>';
  area.innerHTML = html;
  area.querySelectorAll('.opt-sec-tick[data-indeterminate="1"]').forEach(cb => { cb.indeterminate = true; });
  const _chassisCount = (_ch && _ch.items) ? _ch.items.length : 0;
  document.getElementById('bom-count').textContent = `${items.length}${_chassisCount ? ' + ' + _chassisCount + ' chassis' : ''} items`;
  const lbl = document.getElementById('bom-collapse-lbl');
  if (lbl) lbl.style.display = 'flex';
  _calcSyncCheckbox();
}

function renderSummary(result) {
  const area = document.getElementById('summary-area');
  const grand = document.getElementById('grand-total');

  // ── Admin single-side mode: scale down categories that have a ×N multiplier ──
  const _isAdmin = typeof isAdmin !== 'undefined' && isAdmin;
  const mults = result.category_multipliers || {};
  let displayTotals = result.category_totals;
  let grandAdjust = 1; // ratio to apply to grand_total / matsTotal when in single-side mode
  if (_singleSideMode && _isAdmin) {
    displayTotals = {};
    let origSum = 0, adjSum = 0;
    for (const [cat, total] of Object.entries(result.category_totals)) {
      const m = mults[cat] || 1;
      displayTotals[cat] = total / m;
      origSum += total;
      adjSum  += total / m;
    }
    grandAdjust = origSum > 0 ? adjSum / origSum : 1;
  }

  // ── Category breakdown (detail rows) ──────────────────
  // Build a set of optional section names from items so the summary row
  // for any is_optional section (e.g. OPTIONAL EXTRAS) renders in red.
  const _optionalCats = new Set();
  (result.items || []).forEach(it => {
    if (it.section_is_optional) _optionalCats.add(it.bom_section || it.category || '');
  });
  let html = '<div class="summary-box">';
  if (_singleSideMode && _isAdmin) {
    html += `<div style="text-align:center;font-size:10px;color:#FFB454;font-weight:700;
        letter-spacing:.05em;padding:3px 0 5px;border-bottom:1px dashed var(--border);margin-bottom:4px">
      ½ ONE SIDE VIEW — click elsewhere to reset
    </div>`;
  }
  if (hasFullCostAccess) {
    for (const [cat, total] of Object.entries(displayTotals)) {
      const mult = mults[cat];
      let badge = '';
      if (mult && mult !== 1) {
        if (_singleSideMode && _isAdmin) {
          badge = ` <span title="Showing 1 side (click to restore × ${mult})"
              onclick="_singleSideMode=false;renderSummary(lastResult);renderBOMWithCosts(lastResult.items,bomData)"
              style="margin-left:5px;background:#1a2a1a;color:#4caf50;border:1px solid #4caf50;
              border-radius:4px;padding:0 5px;font-size:9px;font-weight:700;cursor:pointer">× 1</span>`;
        } else {
          const clickAttr = _isAdmin
            ? `onclick="_singleSideMode=true;renderSummary(lastResult);renderBOMWithCosts(lastResult.items,bomData)" style="margin-left:5px;background:#3a1a1a;color:#ff6b6b;border:1px solid #f44336;border-radius:4px;padding:0 5px;font-size:9px;font-weight:700;cursor:pointer" title="Click to view one-side cost"`
            : `style="margin-left:5px;background:#3a1a1a;color:#ff6b6b;border:1px solid #f44336;border-radius:4px;padding:0 5px;font-size:9px;font-weight:700" title="× ${mult} multiplier"`;
          badge = ` <span ${clickAttr}>× ${mult}</span>`;
        }
      }
      const _rowColor = _optionalCats.has(cat) ? 'var(--red,#e35d6a)' : 'var(--text-dim)';
      html += `<div class="summary-row">
        <span class="s-label" style="font-size:11px;color:${_rowColor}">${cat}${badge}</span>
        <span class="s-val" style="font-size:11px;color:${_rowColor}">${fmt(total)}</span>
      </div>`;
    }
  }

  // ── Materials Cost subtotal ────────────────────────────
  const matsRaw = result.materials_total != null ? result.materials_total : result.grand_total;
  const matsTotal = matsRaw * grandAdjust;
  html += `<div class="summary-row" style="border-top:2px solid var(--border);margin-top:4px;padding-top:6px">
    <span class="s-label" style="font-weight:600">Materials Cost</span>
    <span class="s-val" style="font-weight:600">${fmt(matsTotal)}</span>
  </div>`;

  // ── Chassis subtotal (if enabled) ──────────────────────
  const adjGrand = result.grand_total * grandAdjust;
  if (result.chassis && hasFullCostAccess) {
    const ch = result.chassis;
    html += `<div class="summary-row">
      <span class="s-label" style="font-size:11px;color:#FFB454">Chassis (${ch.axle_count}-axle · ${ch.tyre_count} tyres)</span>
      <span class="s-val" style="font-size:11px;color:#FFB454">${fmt(ch.subtotal)}</span>
    </div>`;
    html += `<div class="summary-row" style="border-top:1px dashed var(--border);margin-top:4px;padding-top:6px">
      <span class="s-label" style="font-weight:600">Body + Chassis</span>
      <span class="s-val" style="font-weight:600">${fmt(adjGrand)}</span>
    </div>`;
  }

  // Cost per m² (small detail)
  html += `<div class="summary-row" style="margin-bottom:8px">
    <span class="s-label" style="font-size:10px;color:var(--text-dim)">Cost / m²</span>
    <span class="s-val" style="font-size:10px;color:var(--text-dim)">${fmt(result.cost_per_sqm * grandAdjust)}</span>
  </div>`;

  // ── Additions ─────────────────────────────────────────
  // withMargin = pre-ratio total (manufacturing + margin). DO NOT use
  // result.selling_price here — after /api/approve, selling_price already
  // includes the ratio division, so re-dividing here would double-apply it.
  const marginAmount = (result.profit_amount || 0) * grandAdjust;
  const withMargin = (result.grand_total + (result.profit_amount || 0)) * grandAdjust;

  let totalCost = adjGrand;

  // Margin
  if (marginAmount > 0) {
    totalCost += marginAmount;
    html += `<div class="summary-row highlight-green">
      <span class="s-label">Margin (${result.profit_margin}%)</span>
      <span class="s-val">+ ${fmt(marginAmount)}</span>
    </div>`;
  }

  // Ratio — applied to (materials + margin), not materials alone
  const ratioVal = parseFloat(document.getElementById('f-ratio').value);
  if (!isNaN(ratioVal) && ratioVal > 0) {
    const ratioLabel = document.getElementById('f-ratio').selectedOptions[0]?.text || '';
    const ratioAddition = withMargin / ratioVal - withMargin;
    totalCost = withMargin + ratioAddition;
    html += `<div class="summary-row highlight-green">
      <span class="s-label">Ratio (${ratioLabel})</span>
      <span class="s-val">+ ${fmt(ratioAddition)}</span>
    </div>`;
  }

  // ── Total Cost ─────────────────────────────────────────
  html += `<div class="summary-row total" style="margin-top:4px">
    <span>TOTAL COST</span>
    <span class="s-val">${fmt(totalCost)}</span>
  </div>`;

  // ── Discount → Net Total rows (always rendered; hidden when no discount).
  //    They carry stable IDs so the discount handlers update them IN PLACE —
  //    typing in the inputs must never re-render the <input> (that resets the
  //    caret to the start and reverses the digits). ──
  html += `<div class="summary-row highlight-green" id="disc-row" style="display:none">
    <span class="s-label" id="disc-label">Discount</span>
    <span class="s-val" id="disc-val">− ${fmt(0)}</span>
  </div>
  <div class="summary-row total" id="net-row" style="color:var(--blue-hi);display:none">
    <span>NET TOTAL</span>
    <span class="s-val" id="net-val">${fmt(0)}</span>
  </div>`;
  html += '</div>';

  if (hasFullCostAccess) {
    // ── Discount entry (% OR amount — entering one zeroes the other) ─────────
    const _pctVal = (discountKind === 'percent' && discountInput) ? (+discountInput) : '';
    const _amtVal = (discountKind === 'amount'  && discountInput) ? (+discountInput) : '';
    html += `<div style="margin-top:14px;padding:10px 12px;border:1px solid var(--border);border-radius:var(--radius);background:var(--bg-panel)">
      <div style="font-size:10px;letter-spacing:1px;text-transform:uppercase;color:var(--text-dim);margin-bottom:6px">Discount</div>
      <div style="display:flex;gap:8px">
        <div style="flex:1">
          <label for="disc-pct" style="font-size:10px;color:var(--text-dim)">Percent %</label>
          <input id="disc-pct" type="number" min="0" max="100" step="0.1" class="form-control" placeholder="0"
                 value="${_pctVal}" oninput="applyDiscountInput('percent', this)"
                 style="font-size:12px;padding:4px 6px;width:100%">
        </div>
        <div style="flex:1">
          <label for="disc-amt" style="font-size:10px;color:var(--text-dim)">Amount R</label>
          <input id="disc-amt" type="number" min="0" step="0.01" class="form-control" placeholder="0"
                 value="${_amtVal}" oninput="applyDiscountInput('amount', this)"
                 style="font-size:12px;padding:4px 6px;width:100%">
        </div>
      </div>
    </div>`;

    // ── Geometry grid — two paired boxes ───────────────────
    const g = result.geometry;
    html += `<div class="geo-grid" style="margin-top:14px">
      <div class="geo-item"><div class="geo-label">Floor / Surface Area</div>
        <div class="geo-value">${fmtNum(g.floor_area,1)} / ${fmtNum(g.surface_area,1)} m²</div></div>
      <div class="geo-item"><div class="geo-label">Wall / Roof Area</div>
        <div class="geo-value">${fmtNum(g.wall_area,1)} / ${fmtNum(g.roof_area,1)} m²</div></div>
    </div>`;
  }

  area.innerHTML = html;

  // Remember the gross total + default sub-line so the discount handlers can
  // refresh the display without a full re-render.
  lastGrossTotal = totalCost;
  const ratioValFinal = parseFloat(document.getElementById('f-ratio').value);
  if (!isNaN(ratioValFinal) && ratioValFinal > 0) _defaultSubText = `Selling Price: ${fmt(withMargin / ratioValFinal)}`;
  else if (result.cost_per_sqm)                   _defaultSubText = `${fmt(result.cost_per_sqm)} / m²`;
  else                                            _defaultSubText = '';

  refreshDiscountDisplay();   // sets grand-total + sub + disc/net rows from the globals
}

// ── Discount state (entered in the Cost Summary, applied to the Total Cost) ───
let discountKind   = null;   // 'percent' | 'amount' | null
let discountInput  = 0;      // raw value the user typed
let lastGrossTotal = 0;      // last rendered gross Total Cost (for in-place refresh)
let _defaultSubText = '';    // non-discount sub-line text

// Compute the discount + net for a given gross total, honouring the clamps the
// server also applies (percent 0–100, amount ≤ total). Pure — reads the globals.
function computeDiscount(base) {
  base = +base || 0;
  let amount = 0;
  if (discountKind === 'percent' && discountInput > 0) {
    amount = base * Math.min(Math.max(discountInput, 0), 100) / 100;
  } else if (discountKind === 'amount' && discountInput > 0) {
    amount = Math.min(discountInput, base);
  }
  amount = Math.round(amount * 100) / 100;
  return { amount, net: Math.round((base - amount) * 100) / 100 };
}

// Update the Discount / Net Total rows, the headline and the sub-line IN PLACE
// (no innerHTML re-render), so the discount inputs keep their caret while typing.
function refreshDiscountDisplay() {
  const d = computeDiscount(lastGrossTotal);
  const show = d.amount > 0;
  const discRow = document.getElementById('disc-row');
  const netRow  = document.getElementById('net-row');
  const grand   = document.getElementById('grand-total');
  const sub     = document.getElementById('grand-total-sub');
  if (discRow) {
    discRow.style.display = show ? '' : 'none';
    const lbl = document.getElementById('disc-label');
    if (lbl) lbl.textContent = discountKind === 'percent' ? `Discount (${+discountInput}%)` : 'Discount';
    const dv = document.getElementById('disc-val');
    if (dv) dv.textContent = `− ${fmt(d.amount)}`;
  }
  if (netRow) {
    netRow.style.display = show ? '' : 'none';
    const nv = document.getElementById('net-val');
    if (nv) nv.textContent = fmt(d.net);
  }
  if (grand) grand.textContent = fmt(show ? d.net : lastGrossTotal);
  if (sub) sub.textContent = show ? `Was ${fmt(lastGrossTotal)} · less ${fmt(d.amount)} discount` : _defaultSubText;
}

// Typing in either discount box: entering a value in one zeroes the other. Only
// the OTHER input is touched (cleared) — never the one being typed in — and the
// figures refresh in place, so the caret and digit order are preserved.
function applyDiscountInput(kind, el) {
  const v = parseFloat(el.value);
  if (isNaN(v) || v <= 0) {
    if (discountKind === kind) { discountKind = null; discountInput = 0; }
  } else {
    discountKind = kind;
    discountInput = v;
    const other = document.getElementById(kind === 'percent' ? 'disc-amt' : 'disc-pct');
    if (other) other.value = '';
  }
  refreshDiscountDisplay();
  try { saveLastSession(); } catch (_) {}
}

function viewFullResults() {
  if (!lastRecordId) {
    toast('Approve and save the costing first', 'warn');
    return;
  }
  window.open(`/results/${lastRecordId}`, '_blank');
}

function printResults() {
  if (!lastRecordId) {
    toast('Approve and save the costing first', 'warn');
    return;
  }
  window.print();
}

function escHtml(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Chassis add-on ─────────────────────────────────────────────────────────
let _chassisOptions = null;  // { suspension:[], brake:[], tyre:[], rim:[], lifting_axle:[] }
let _chassisLoaded  = false;

async function _loadChassisOptions() {
  if (_chassisLoaded) return _chassisOptions;
  try {
    const r = await api('GET', '/api/chassis/options');
    _chassisOptions = r.by_kind || r;  // tolerate either shape
    _chassisLoaded = true;
  } catch (e) {
    toast('Failed to load chassis options: ' + e.message, 'error');
    _chassisOptions = { suspension:[], brake:[], tyre:[], rim:[], lifting_axle:[] };
  }
  return _chassisOptions;
}

function _fillSelect(sel, items, { placeholder } = {}) {
  if (!sel) return;
  const prev = sel.value;
  let html = placeholder ? `<option value="">${placeholder}</option>` : '';
  html += items.map(o => {
    const price = (o.price || 0).toFixed(2);
    return `<option value="${o.id}">${escHtml(o.label)} — R ${price}</option>`;
  }).join('');
  sel.innerHTML = html;
  if (prev && sel.querySelector(`option[value="${prev}"]`)) sel.value = prev;
}

function switchCfgTab(tab) {
  const isBody    = tab === 'body';
  document.getElementById('cfg-pane-body').style.display    = isBody ? '' : 'none';
  document.getElementById('cfg-pane-chassis').style.display = isBody ? 'none' : '';

  const tBody    = document.getElementById('cfg-tab-body');
  const tChassis = document.getElementById('cfg-tab-chassis');

  tBody.style.borderBottomColor = isBody ? 'var(--blue)' : 'transparent';
  tBody.style.color             = isBody ? 'var(--blue)' : 'var(--text-dim)';
  tBody.style.fontWeight        = isBody ? '600' : 'normal';

  tChassis.style.borderBottomColor = !isBody ? 'var(--blue)' : 'transparent';
  tChassis.style.color             = !isBody ? 'var(--blue)' : 'var(--text-dim)';
  tChassis.style.fontWeight        = !isBody ? '600' : 'normal';

  try { localStorage.setItem('cfg_tab', tab); } catch(_) {}
}

async function onChassisToggle() {
  const on = document.getElementById('f-chassis-on').checked;
  const wrap = document.getElementById('chassis-fields');
  wrap.style.display = on ? '' : 'none';
  if (!on) return;

  // Default chassis length to body length on first enable
  const chLen = document.getElementById('f-ch-length');
  const bodyLen = document.getElementById('f-length').value;
  if (chLen && bodyLen && !chLen.dataset.userTouched) {
    chLen.value = bodyLen;
  }

  await _loadChassisOptions();
  _refreshChassisDropdowns();
}

function _refreshChassisDropdowns() {
  if (!_chassisOptions) return;
  const axles = +document.getElementById('f-ch-axles').value || 3;
  const style = document.getElementById('f-ch-tyre-style').value || 'dual';

  const suspensions = (_chassisOptions.suspension || []).filter(o =>
    o.is_active && (o.axle_count == null || o.axle_count === axles));
  _fillSelect(document.getElementById('f-ch-suspension'), suspensions, { placeholder: '— Select suspension —' });

  const brakes = (_chassisOptions.brake || []).filter(o =>
    o.is_active && (o.axle_count == null || o.axle_count === axles));
  _fillSelect(document.getElementById('f-ch-brake'), brakes, { placeholder: '— Select brake kit —' });

  const tyres = (_chassisOptions.tyre || []).filter(o =>
    o.is_active && (!o.tyre_style || o.tyre_style === style));
  _fillSelect(document.getElementById('f-ch-tyre'), tyres, { placeholder: '— Select tyre —' });

  const rims = (_chassisOptions.rim || []).filter(o =>
    o.is_active && (!o.tyre_style || o.tyre_style === style));
  _fillSelect(document.getElementById('f-ch-rim'), rims, { placeholder: '— Select rim —' });

  const liftSel  = document.getElementById('f-ch-lift-type');
  const liftCnt  = document.getElementById('f-ch-lift-count');
  const liftHint = document.getElementById('ch-lift-hint');
  if (axles === 3) {
    const lifts = (_chassisOptions.lifting_axle || []).filter(o => o.is_active);
    _fillSelect(liftSel, lifts, { placeholder: '— None —' });
    liftSel.disabled = false;
    liftCnt.disabled = false;
    if (liftHint) liftHint.style.display = 'none';
  } else {
    liftSel.innerHTML = '<option value="">— 3-axle only —</option>';
    liftSel.disabled = true;
    liftCnt.value = '0';
    liftCnt.disabled = true;
    if (liftHint) liftHint.style.display = '';
  }

  _updateChassisCounts();
}

function _updateChassisCounts() {
  const axles = +document.getElementById('f-ch-axles').value || 0;
  const lift  = +document.getElementById('f-ch-lift-count').value || 0;
  const style = document.getElementById('f-ch-tyre-style').value;
  const perAxle = style === 'super_single' ? 2 : 4;
  const total = (axles + lift) * perAxle;
  document.getElementById('ch-tyre-count').textContent = total;
  document.getElementById('ch-rim-count').textContent  = total;
}

function onChassisAxleChange() { _refreshChassisDropdowns(); scheduleCalc(); }
function onChassisTyreStyleChange() { _refreshChassisDropdowns(); scheduleCalc(); }

function getChassisSelection() {
  const on = document.getElementById('f-chassis-on')?.checked;
  if (!on) return { enabled: false };
  const v = id => document.getElementById(id)?.value || '';
  return {
    enabled: true,
    length: +v('f-ch-length') || 0,
    axle_count: +v('f-ch-axles') || 0,
    lift_count: +v('f-ch-lift-count') || 0,
    tyre_style: v('f-ch-tyre-style') || 'dual',
    suspension_id: +v('f-ch-suspension') || null,
    lift_type_id:  +v('f-ch-lift-type')  || null,
    brake_id:      +v('f-ch-brake')      || null,
    tyre_id:       +v('f-ch-tyre')       || null,
    rim_id:        +v('f-ch-rim')        || null,
  };
}

// ── Formula hover tooltip ─────────────────────────────────────────────────────

// Geometry variable names sorted longest-first so longer names match before shorter ones
// (e.g. "floor_thickness" before a hypothetical "floor").
const _GEO_KEYS = [
  'insulation_thickness','floor_thickness','panel_thickness',
  'total_panel_area','front_rear_area','surface_area',
  'wall_area','roof_area','floor_area',
  'num_axles','num_doors','volume',
  'length','width','height',
];

function _resolveFormulaForTooltip(formula) {
  if (!formula || /^\s*\d+(\.\d+)?\s*$/.test(formula) || formula.trim() === '1') return null;
  const geo = (lastResult && lastResult.geometry) ? lastResult.geometry : {};
  let s = formula;

  // 1. Replace {VAR} tokens
  s = s.replace(/\{([^}]+)\}/g, (match, name) => {
    const key = name.trim();
    const keyUp = key.toUpperCase();
    if (Object.prototype.hasOwnProperty.call(lastBodyVars, keyUp)) {
      return lastBodyVars[keyUp].toFixed(3);
    }
    const keyLo = key.toLowerCase();
    if (Object.prototype.hasOwnProperty.call(lastFormulaLib, keyLo)) {
      return lastFormulaLib[keyLo].toFixed(4);
    }
    const gv = Object.entries(lastGlobalVars).find(([k]) => k.toUpperCase() === keyUp);
    if (gv) return parseFloat(gv[1].toFixed(6)).toString();
    return '?';
  });

  // 2. Replace geometry variable names with their numeric values
  _GEO_KEYS.forEach(k => {
    if (!Object.prototype.hasOwnProperty.call(geo, k)) return;
    const val = geo[k];
    // Use word-boundary regex so "floor_area" doesn't eat "floor" inside another token
    s = s.replace(new RegExp('\\b' + k + '\\b', 'g'), parseFloat(val.toFixed(3)));
  });

  return s;
}

function _rawFormulaHtml(formula) {
  // Render raw formula with {VAR} tokens styled in amber
  return escHtml(formula).replace(/\{([^}]+)\}/g,
    (m, n) => `<span style="color:#b45309">{${escHtml(n)}}</span>`);
}

function _buildFormulaTooltipHtml(formula, qty, unit) {
  const resolved = _resolveFormulaForTooltip(formula);

  // Collect unique {VAR} tokens and their resolved values for the legend
  const tokens = [...new Set((formula.match(/\{([^}]+)\}/g) || []))];
  const geo = (lastResult && lastResult.geometry) ? lastResult.geometry : {};

  const legendRows = tokens.map(tok => {
    const key = tok.slice(1, -1).trim();
    const keyUp = key.toUpperCase();
    const keyLo = key.toLowerCase();
    let val, type;
    if (Object.prototype.hasOwnProperty.call(lastBodyVars, keyUp)) {
      val = lastBodyVars[keyUp].toFixed(3);
      type = 'body';
    } else if (Object.prototype.hasOwnProperty.call(lastFormulaLib, keyLo)) {
      val = lastFormulaLib[keyLo].toFixed(4);
      type = 'lib';
    } else {
      const gv = Object.entries(lastGlobalVars).find(([k]) => k.toUpperCase() === keyUp);
      if (gv) { val = parseFloat(gv[1].toFixed(6)).toString(); type = 'global'; }
      else     { val = '?'; type = 'unknown'; }
    }
    const color = type === 'body' ? '#b45309' : type === 'lib' ? '#7c3aed' : type === 'global' ? '#a16207' : '#dc2626';
    const label = type === 'global' ? ' <span style="font-size:9px;opacity:.6">(global)</span>' : '';
    return `<span style="display:inline-block;margin:2px 10px 2px 0;white-space:nowrap">
      <span style="color:${color};font-family:var(--font-mono)">${escHtml(tok)}</span>
      <span style="color:var(--text-dim)"> = </span>
      <span style="color:var(--text)">${escHtml(val)}</span>${label}
    </span>`;
  }).join('');

  // Also show any geometry vars used, if the formula references them
  const geoUsed = _GEO_KEYS.filter(k => {
    return Object.prototype.hasOwnProperty.call(geo, k) &&
           new RegExp('\\b' + k + '\\b').test(formula);
  });
  const geoRows = geoUsed.map(k => {
    const val = parseFloat(geo[k].toFixed(3));
    return `<span style="display:inline-block;margin:2px 10px 2px 0;white-space:nowrap">
      <span style="color:#2563eb;font-family:var(--font-mono)">${escHtml(k)}</span>
      <span style="color:var(--text-dim)"> = </span>
      <span style="color:var(--text)">${val}</span>
    </span>`;
  }).join('');

  const unitLabel = unit && unit !== 'each' ? ` ${escHtml(unit)}` : '';

  let html = `<div style="font-size:10px;letter-spacing:.8px;text-transform:uppercase;color:var(--text-dim);margin-bottom:6px">Formula</div>`;
  html += `<div style="font-family:var(--font-mono);font-size:11px;color:var(--text-dim);word-break:break-all;line-height:1.6">${_rawFormulaHtml(formula)}</div>`;

  if (resolved) {
    html += `<div style="margin:5px 0;color:var(--text-dim);font-size:10px">↓ substituted</div>`;
    html += `<div style="font-family:var(--font-mono);font-size:12px;color:#15803d;word-break:break-all;line-height:1.6">${escHtml(resolved)}</div>`;
  }

  html += `<div style="margin-top:7px;font-family:var(--font-mono);font-size:12px">
    <span style="color:var(--text-dim)">Qty: </span>
    <strong style="color:var(--text-head)">${fmtNum(qty, 4)}${unitLabel}</strong>
  </div>`;

  if (legendRows || geoRows) {
    html += `<div style="margin-top:8px;padding-top:7px;border-top:1px solid var(--border);font-size:11px;line-height:1.8">${legendRows}${geoRows}</div>`;
  }

  return html;
}

function _showFormulaTooltip(e, row) {
  const formula = row.getAttribute('data-formula') || '';
  const qty     = parseFloat(row.getAttribute('data-qty') || '0');
  const unit    = row.getAttribute('data-unit') || '';
  if (!formula || formula === '1') return;

  const tt = document.getElementById('formula-tooltip');
  if (!tt) return;
  tt.innerHTML = _buildFormulaTooltipHtml(formula, qty, unit);
  tt.style.display = 'block';
  _positionFormulaTooltip(e, tt);
}

function _hideFormulaTooltip() {
  const tt = document.getElementById('formula-tooltip');
  if (tt) tt.style.display = 'none';
}

function _positionFormulaTooltip(e, tt) {
  const vw = window.innerWidth, vh = window.innerHeight;
  const tw = Math.min(460, vw * 0.9);
  let x = e.clientX + 18, y = e.clientY + 14;
  if (x + tw > vw - 8) x = vw - tw - 8;
  const th = tt.offsetHeight || 200;
  if (y + th > vh - 8) y = Math.max(8, vh - th - 8);
  tt.style.left = x + 'px';
  tt.style.top  = y + 'px';
  tt.style.maxWidth = tw + 'px';
}

// Global BOM tooltip state — clicking any row is a page-level toggle
// 'on'         — all tooltips active; pricing rows show breakdown
// 'on-formula' — all tooltips active; pricing rows show formula qty instead
// 'off'        — no tooltips anywhere
// Plain row click:   on → off → on
// Pricing row click: on → on-formula → off → on
const _PRICING_ROW_CLASSES    = ['bom-skin-row','bom-taping-row','bom-floor-row','bom-cleat-row'];
let   _globalTooltipState     = 'on';
let   _suppressPricingTooltip = false;  // set before document handlers fire (bubble order)

function _isPricingRow(row) {
  return _PRICING_ROW_CLASSES.some(c => row.classList.contains(c));
}
function _hidePricingTooltips() {
  const s = document.getElementById('skin-tip');
  if (s) s.classList.remove('visible');
  ['taping-tip','floor-tip','cleat-tip'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });
}

function _initFormulaTooltip() {
  const area = document.getElementById('bom-area');
  if (!area) return;

  area.addEventListener('mouseover', e => {
    const row = e.target.closest('tr.calc-grp-row');
    if (!row) { _hideFormulaTooltip(); _suppressPricingTooltip = false; return; }

    if (_globalTooltipState === 'off') {
      _suppressPricingTooltip = true; _hideFormulaTooltip(); return;
    }
    if (_isPricingRow(row)) {
      if (_globalTooltipState === 'on-formula') {
        _suppressPricingTooltip = true; _showFormulaTooltip(e, row);
      } else {
        _suppressPricingTooltip = false; _hideFormulaTooltip();
      }
    } else {
      _suppressPricingTooltip = false; _showFormulaTooltip(e, row);
    }
  });

  area.addEventListener('mousemove', e => {
    const tt = document.getElementById('formula-tooltip');
    if (!tt || tt.style.display === 'none') return;
    const row = e.target.closest('tr.calc-grp-row');
    if (!row) return;
    _positionFormulaTooltip(e, tt);
  });

  area.addEventListener('mouseout', e => {
    const row = e.target.closest('tr.calc-grp-row');
    if (!row) return;
    if (row.contains(e.relatedTarget)) return;
    _hideFormulaTooltip();
    _suppressPricingTooltip = false;
  });

  // Each click advances the page-level tooltip state
  area.addEventListener('click', e => {
    const row = e.target.closest('tr.calc-grp-row');
    if (!row) return;

    if (_globalTooltipState === 'off') {
      _globalTooltipState = 'on';
    } else if (_globalTooltipState === 'on-formula') {
      _globalTooltipState = 'off';
      _hideFormulaTooltip(); _hidePricingTooltips();
    } else { // 'on'
      if (_isPricingRow(row)) {
        _globalTooltipState = 'on-formula';
        _hidePricingTooltips(); _showFormulaTooltip(e, row);
      } else {
        _globalTooltipState = 'off';
        _hideFormulaTooltip();
      }
    }
  });
}

document.addEventListener('DOMContentLoaded', _initFormulaTooltip);

// ── Chassis config panel ──────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  const chLen = document.getElementById('f-ch-length');
  if (chLen) chLen.addEventListener('input', () => { chLen.dataset.userTouched = '1'; scheduleCalc(); });
  const liftCnt = document.getElementById('f-ch-lift-count');
  if (liftCnt) liftCnt.addEventListener('change', () => { _updateChassisCounts(); scheduleCalc(); });
  ['f-ch-suspension','f-ch-lift-type','f-ch-brake','f-ch-tyre','f-ch-rim'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('change', scheduleCalc);
  });

  // Restore last active config tab
  const savedTab = localStorage.getItem('cfg_tab') || 'body';
  switchCfgTab(savedTab);

  // ── Inline recipe edit ────────────────────────────────────────────
  let _inlineSkinItems   = [];  // [{ing_id, name, qty, price_std, price_kzn}]
  let _inlineTapingBlock = null;  // full block object from _calcTapingBlocks

  window.openInlineSkinEdit = function() {
    const modal = document.getElementById('modal-section-price');
    const bomId = modal.dataset.bomId;
    const row   = bomData.find(b => String(b.id) === String(bomId));
    if (!row?.skin_formula_items) return;
    _inlineSkinItems = row.skin_formula_items.map(it => ({ ...it }));
    document.getElementById('inline-skin-formula-name').textContent =
      '◎ ' + (row.skin_formula_name || 'Skin Formula') + ' · ' + (row.skin_formula_region || 'standard').toUpperCase();
    const tbody = document.getElementById('inline-skin-tbody');
    tbody.innerHTML = _inlineSkinItems.map((it, i) => `
      <tr style="border-bottom:1px solid rgba(48,54,61,.4)">
        <td style="padding:6px 8px 6px 0;color:var(--text-dim)">${escHtml(it.name)}</td>
        <td style="padding:6px 8px;text-align:right;font-family:var(--font-mono);color:var(--text-dim)">${it.qty.toFixed(4)}</td>
        <td style="padding:6px 8px;text-align:right">
          <input type="number" step="0.01" min="0" value="${it.price_std}"
            style="width:90px;font-family:var(--font-mono);font-size:12px;text-align:right;background:var(--bg-input);border:1px solid var(--border);border-radius:4px;padding:3px 6px;color:var(--text)"
            data-idx="${i}" data-field="price_std" oninput="updateInlineSkinRow(this)"/>
        </td>
        <td style="padding:6px 8px;text-align:right">
          <input type="number" step="0.01" min="0" value="${it.price_kzn}"
            style="width:90px;font-family:var(--font-mono);font-size:12px;text-align:right;background:var(--bg-input);border:1px solid var(--border);border-radius:4px;padding:3px 6px;color:var(--text)"
            data-idx="${i}" data-field="price_kzn" oninput="updateInlineSkinRow(this)"/>
        </td>
      </tr>`).join('');
    document.getElementById('modal-inline-skin-edit').classList.remove('hidden');
  };

  window.updateInlineSkinRow = function(input) {
    const idx   = parseInt(input.dataset.idx);
    const field = input.dataset.field;
    _inlineSkinItems[idx][field] = parseFloat(input.value) || 0;
  };

  window.saveInlineSkinEdit = async function() {
    try {
      await Promise.all(_inlineSkinItems.map(it =>
        api('PUT', `/api/skin-formula-ingredients/${it.ing_id}/inline-price`, {
          price_standard: it.price_std,
          price_kzn:      it.price_kzn,
        })
      ));
      closeModal('modal-inline-skin-edit');
      closeModal('modal-section-price');
      toast('Skin formula prices saved', 'success');
      await loadBOM({ preserveInputs: true });
      if (bomData.length) runCalc();
    } catch(e) {
      toast('Save failed: ' + e.message, 'error');
    }
  };

  window.openInlineTapingEdit = function() {
    const modal = document.getElementById('modal-section-price');
    const bomId = modal.dataset.bomId;
    const row   = bomData.find(b => String(b.id) === String(bomId));
    if (!row?.taping_block_id) return;
    _inlineTapingBlock = _calcTapingBlocks.find(b => b.id === row.taping_block_id);
    if (!_inlineTapingBlock) return;
    document.getElementById('inline-taping-block-name').textContent =
      '⊡ ' + _inlineTapingBlock.name;
    const tbody = document.getElementById('inline-taping-tbody');
    tbody.innerHTML = _inlineTapingBlock.items.map((it, i) => {
      const price = it.price_source === 'sap' && it.price_sap != null ? it.price_sap : it.price_per_unit;
      const line  = it.m2 * price * it.quantity;
      const isSap = it.price_source === 'sap';
      return `<tr style="border-bottom:1px solid rgba(48,54,61,.4)">
        <td style="padding:6px 8px 6px 0;color:var(--text-dim)">${escHtml(it.item_name)}</td>
        <td style="padding:6px 8px;text-align:right;font-family:var(--font-mono);color:var(--text-dim)">${it.m2.toFixed(4)}</td>
        <td style="padding:6px 8px;text-align:right">
          <input type="number" step="1" min="0" value="${it.quantity}"
            style="width:60px;font-family:var(--font-mono);font-size:12px;text-align:right;background:var(--bg-input);border:1px solid var(--border);border-radius:4px;padding:3px 6px;color:var(--text)"
            data-item-id="${it.id}" data-field="quantity" oninput="updateInlineTapingRow(this)"/>
        </td>
        <td style="padding:6px 8px;text-align:right">
          ${isSap
            ? `<span style="font-family:var(--font-mono);font-size:12px;color:var(--text-dim)" title="SAP priced — edit via Taping Blocks admin">R ${price.toFixed(2)} (SAP)</span>`
            : `<input type="number" step="0.01" min="0" value="${it.price_per_unit}"
                style="width:90px;font-family:var(--font-mono);font-size:12px;text-align:right;background:var(--bg-input);border:1px solid var(--border);border-radius:4px;padding:3px 6px;color:var(--text)"
                data-item-id="${it.id}" data-field="price_per_unit" oninput="updateInlineTapingRow(this)"/>`}
        </td>
        <td style="padding:6px 0;text-align:right;font-family:var(--font-mono);color:var(--text-dim)" id="inline-tap-line-${it.id}">R ${line.toFixed(4)}</td>
      </tr>`;
    }).join('');
    document.getElementById('modal-inline-taping-edit').classList.remove('hidden');
  };

  window.updateInlineTapingRow = function(input) {
    const itemId = parseInt(input.dataset.itemId);
    const field  = input.dataset.field;
    const it = _inlineTapingBlock.items.find(x => x.id === itemId);
    if (!it) return;
    it[field] = parseFloat(input.value) || 0;
    const price = it.price_source === 'sap' && it.price_sap != null ? it.price_sap : it.price_per_unit;
    const line  = it.m2 * price * it.quantity;
    const el = document.getElementById(`inline-tap-line-${itemId}`);
    if (el) el.textContent = 'R ' + line.toFixed(4);
  };

  window.saveInlineTapingEdit = async function() {
    const editableItems = _inlineTapingBlock.items;
    try {
      await Promise.all(editableItems.map(it =>
        api('PUT', `/api/taping-block-items/${it.id}/inline-price`, {
          price_per_unit: it.price_per_unit,
          quantity:       it.quantity,
        })
      ));
      // Refresh cached taping blocks so the tooltip updates too
      try { _calcTapingBlocks = await api('GET', '/api/taping-blocks'); } catch(e) {}
      closeModal('modal-inline-taping-edit');
      closeModal('modal-section-price');
      toast('Taping block prices saved', 'success');
      await loadBOM({ preserveInputs: true });
      if (bomData.length) runCalc();
    } catch(e) {
      toast('Save failed: ' + e.message, 'error');
    }
  };

  // ── Skin formula row tooltip ──────────────────────────────────────
  const skinTip = document.createElement('div');
  skinTip.id = 'skin-tip';
  document.body.appendChild(skinTip);

  function buildSkinTip(name, region, items) {
    const useKzn = region === 'kzn';
    const useSap = region === 'sap';
    let total = 0;
    let anySap = false;
    const rows = items.map(it => {
      // Mirror app/services.py:_compute_skin_formula_cost
      let price, usingSap;
      if (useSap) {
        usingSap = it.price_sap != null;
        price = usingSap ? it.price_sap : it.price_std;
      } else {
        usingSap = it.price_source === 'sap' && it.price_sap != null;
        price = usingSap ? it.price_sap : (useKzn ? it.price_kzn : it.price_std);
      }
      if (usingSap) anySap = true;
      const line  = price * it.qty;
      total += line;
      const tag = usingSap && !useSap
        ? ' <span style="font-size:9px;color:#f0a500;letter-spacing:.4px" title="Using SAP price">SAP</span>'
        : '';
      return `<tr>
        <td>${escHtml(it.name)}${tag}</td>
        <td>${it.qty.toFixed(4)}</td>
        <td>R ${price.toFixed(2)}</td>
        <td>R ${line.toFixed(4)}</td>
      </tr>`;
    }).join('');
    const priceCol = useSap ? 'SAP Price' : useKzn ? 'KZN Price' : 'Std Price';
    const sapNote = useSap
      ? '<div style="font-size:10px;color:var(--text-dim);margin-top:6px">All ingredients priced from SAP last purchase price.</div>'
      : anySap
      ? '<div style="font-size:10px;color:var(--text-dim);margin-top:6px">Some ingredients use SAP price (overrides regional).</div>'
      : '';
    return `
      <div class="tip-title">◎ SKIN &nbsp;·&nbsp; ${escHtml(name)} &nbsp;·&nbsp; ${region.toUpperCase()}</div>
      <table>
        <thead><tr>
          <th>Ingredient</th><th>Qty/m²</th><th>${priceCol}</th><th>Line</th>
        </tr></thead>
        <tbody>${rows}</tbody>
        <tfoot><tr>
          <td colspan="3">Total per m²</td>
          <td>R ${total.toFixed(4)}</td>
        </tr></tfoot>
      </table>${sapNote}`;
  }

  let _skinTipTarget = null;
  document.addEventListener('mouseover', e => {
    const row = e.target.closest('tr.bom-skin-row');
    if (!row || !row.dataset.skinItems) return;
    if (_suppressPricingTooltip) return;
    if (row === _skinTipTarget) return;
    _skinTipTarget = row;
    try {
      const items  = JSON.parse(row.dataset.skinItems);
      const name   = row.dataset.skinName   || '';
      const region = row.dataset.skinRegion || 'standard';
      skinTip.innerHTML = buildSkinTip(name, region, items);
      skinTip.classList.add('visible');
    } catch(e) {}
  });

  document.addEventListener('mousemove', e => {
    if (!skinTip.classList.contains('visible')) return;
    const vw = window.innerWidth, vh = window.innerHeight;
    const tw = skinTip.offsetWidth + 16, th = skinTip.offsetHeight + 16;
    const x = e.clientX + 16 + tw > vw ? e.clientX - tw : e.clientX + 16;
    const y = e.clientY + 16 + th > vh ? e.clientY - th - 8 : e.clientY + 16;
    skinTip.style.left = x + 'px';
    skinTip.style.top  = y + 'px';
  });

  document.addEventListener('mouseout', e => {
    const row = e.target.closest('tr.bom-skin-row');
    if (row && !row.contains(e.relatedTarget)) {
      skinTip.classList.remove('visible');
      _skinTipTarget = null;
    }
  });

  // ── Taping block row tooltip ──────────────────────────────────────
  const tapingTip = document.createElement('div');
  tapingTip.id = 'taping-tip';
  tapingTip.style.display = 'none';
  document.body.appendChild(tapingTip);

  function buildTapingTip(block) {
    if (!block) return '';
    let total = 0;
    const rows = block.items.map(it => {
      const price = it.price_source === 'sap' && it.price_sap != null
        ? it.price_sap : it.price_per_unit;
      const line = it.m2 * price * (it.quantity || 0);
      total += line;
      return `<tr>
        <td style="padding:2px 8px 2px 0">${escHtml(it.item_name)}</td>
        <td style="padding:2px 8px;text-align:right;font-family:var(--font-mono)">${it.m2.toFixed(4)}</td>
        <td style="padding:2px 8px;text-align:right;font-family:var(--font-mono)">${it.quantity}</td>
        <td style="padding:2px 8px;text-align:right;font-family:var(--font-mono)">R ${price.toFixed(2)}</td>
        <td style="padding:2px 0;text-align:right;font-family:var(--font-mono)">R ${line.toFixed(4)}</td>
      </tr>`;
    }).join('');
    return `
      <div style="font-weight:700;color:#f0a500;margin-bottom:8px;letter-spacing:.3px">⊡ TAPING &nbsp;·&nbsp; ${escHtml(block.name)}</div>
      <table style="width:100%;border-collapse:collapse;color:var(--text)">
        <thead><tr style="color:var(--text-dim);font-size:11px;border-bottom:1px solid rgba(240,165,0,.3)">
          <th style="padding:2px 8px 4px 0;text-align:left">Item</th>
          <th style="padding:2px 8px 4px;text-align:right">M²</th>
          <th style="padding:2px 8px 4px;text-align:right">Qty</th>
          <th style="padding:2px 8px 4px;text-align:right">Price/m²</th>
          <th style="padding:2px 0 4px;text-align:right">Line</th>
        </tr></thead>
        <tbody>${rows}</tbody>
        <tfoot><tr style="border-top:1px solid rgba(240,165,0,.3);font-weight:600;color:#f0a500">
          <td colspan="4" style="padding:4px 8px 0 0">Total per block</td>
          <td style="padding:4px 0 0;text-align:right;font-family:var(--font-mono)">R ${total.toFixed(4)}</td>
        </tr></tfoot>
      </table>`;
  }

  let _tapingTipTarget = null;
  document.addEventListener('mouseover', e => {
    const row = e.target.closest('tr.bom-taping-row');
    if (!row || !row.dataset.tapingId) return;
    if (_suppressPricingTooltip) return;
    if (row === _tapingTipTarget) return;
    _tapingTipTarget = row;
    const block = _calcTapingBlocks.find(b => String(b.id) === row.dataset.tapingId);
    if (!block) return;
    tapingTip.innerHTML = buildTapingTip(block);
    tapingTip.style.display = 'block';
  });

  document.addEventListener('mousemove', e => {
    if (tapingTip.style.display === 'none') return;
    const vw = window.innerWidth, vh = window.innerHeight;
    const tw = tapingTip.offsetWidth + 16, th = tapingTip.offsetHeight + 16;
    const x = e.clientX + 16 + tw > vw ? e.clientX - tw : e.clientX + 16;
    const y = e.clientY + 16 + th > vh ? e.clientY - th - 8 : e.clientY + 16;
    tapingTip.style.left = x + 'px';
    tapingTip.style.top  = y + 'px';
  });

  document.addEventListener('mouseout', e => {
    const row = e.target.closest('tr.bom-taping-row');
    if (row && !row.contains(e.relatedTarget)) {
      tapingTip.style.display = 'none';
      _tapingTipTarget = null;
    }
  });

  // ── Floor plate row tooltip ───────────────────────────────────────
  const floorTip = document.createElement('div');
  floorTip.id = 'floor-tip';
  floorTip.style.display = 'none';
  document.body.appendChild(floorTip);

  function buildFloorTip(plate) {
    if (!plate) return '';
    let rawTotal = 0;
    const rows = plate.items.map(it => {
      const price = it.price_source === 'sap' && it.price_sap != null
        ? it.price_sap : it.price_per_unit;
      const line = it.m2 * price * (it.quantity || 0);
      rawTotal += line;
      return `<tr>
        <td style="padding:2px 8px 2px 0">${escHtml(it.item_name)}</td>
        <td style="padding:2px 8px;text-align:right;font-family:var(--font-mono)">${it.m2.toFixed(4)}</td>
        <td style="padding:2px 8px;text-align:right;font-family:var(--font-mono)">${it.quantity}</td>
        <td style="padding:2px 8px;text-align:right;font-family:var(--font-mono)">R ${price.toFixed(2)}</td>
        <td style="padding:2px 0;text-align:right;font-family:var(--font-mono)">R ${line.toFixed(4)}</td>
      </tr>`;
    }).join('');

    // Build formula row if present
    let formulaHtml = '';
    if (plate.price_formula) {
      try {
        const steps = JSON.parse(plate.price_formula);
        let result = rawTotal;
        let expr = `R ${rawTotal.toFixed(2)}`;
        for (const s of steps) {
          const v = parseFloat(s.val);
          if (!v) continue;
          if (s.op === '/') { result /= v; expr += ` ÷ ${v}`; }
          else               { result *= v; expr += ` × ${v}`; }
        }
        formulaHtml = `
          <tr style="border-top:1px solid rgba(61,153,112,.2)">
            <td colspan="4" style="padding:3px 8px 2px 0;font-size:11px;color:var(--text-dim)">Formula</td>
            <td style="padding:3px 0 2px;text-align:right;font-family:var(--font-mono);font-size:11px;color:var(--text-dim)">${expr.replace(/R [0-9.]+/, '')}</td>
          </tr>
          <tr style="font-weight:700">
            <td colspan="4" style="padding:2px 8px 0 0;color:#3d9970">Effective price</td>
            <td style="padding:2px 0 0;text-align:right;font-family:var(--font-mono);color:#3d9970">R ${result.toFixed(4)}</td>
          </tr>`;
      } catch(e) {}
    }

    const totalLabel = plate.price_formula ? 'Raw total' : 'Total per assembly';
    return `
      <div style="font-weight:700;color:#3d9970;margin-bottom:8px;letter-spacing:.3px">⊞ FLOOR PLATE &nbsp;·&nbsp; ${escHtml(plate.name)}</div>
      <table style="width:100%;border-collapse:collapse;color:var(--text)">
        <thead><tr style="color:var(--text-dim);font-size:11px;border-bottom:1px solid rgba(61,153,112,.3)">
          <th style="padding:2px 8px 4px 0;text-align:left">Item</th>
          <th style="padding:2px 8px 4px;text-align:right">M²</th>
          <th style="padding:2px 8px 4px;text-align:right">Qty</th>
          <th style="padding:2px 8px 4px;text-align:right">Price/m²</th>
          <th style="padding:2px 0 4px;text-align:right">Line</th>
        </tr></thead>
        <tbody>${rows}</tbody>
        <tfoot>
          <tr style="border-top:1px solid rgba(61,153,112,.3);font-weight:600;color:#3d9970">
            <td colspan="4" style="padding:4px 8px 0 0">${totalLabel}</td>
            <td style="padding:4px 0 0;text-align:right;font-family:var(--font-mono)">R ${rawTotal.toFixed(4)}</td>
          </tr>
          ${formulaHtml}
        </tfoot>
      </table>`;
  }

  let _floorTipTarget = null;
  document.addEventListener('mouseover', e => {
    const row = e.target.closest('tr.bom-floor-row');
    if (!row || !row.dataset.floorId) return;
    if (_suppressPricingTooltip) return;
    if (row === _floorTipTarget) return;
    _floorTipTarget = row;
    const plate = _calcFloorPlates.find(p => String(p.id) === row.dataset.floorId);
    if (!plate) return;
    floorTip.innerHTML = buildFloorTip(plate);
    floorTip.style.display = 'block';
  });

  document.addEventListener('mousemove', e => {
    if (floorTip.style.display === 'none') return;
    const vw = window.innerWidth, vh = window.innerHeight;
    const tw = floorTip.offsetWidth + 16, th = floorTip.offsetHeight + 16;
    const x = e.clientX + 16 + tw > vw ? e.clientX - tw : e.clientX + 16;
    const y = e.clientY + 16 + th > vh ? e.clientY - th - 8 : e.clientY + 16;
    floorTip.style.left = x + 'px';
    floorTip.style.top  = y + 'px';
  });

  document.addEventListener('mouseout', e => {
    const row = e.target.closest('tr.bom-floor-row');
    if (row && !row.contains(e.relatedTarget)) {
      floorTip.style.display = 'none';
      _floorTipTarget = null;
    }
  });

  // ── Mounting cleat row tooltip ────────────────────────────────────
  const cleatTip = document.createElement('div');
  cleatTip.id = 'cleat-tip';
  cleatTip.style.display = 'none';
  document.body.appendChild(cleatTip);

  function buildCleatTip(cleat) {
    if (!cleat) return '';
    let total = 0;
    const rows = cleat.items.map(it => {
      const price = it.price_source === 'sap' && it.price_sap != null ? it.price_sap : it.price_per_unit;
      const line = it.m2 * price * (it.quantity || 0);
      total += line;
      return `<tr>
        <td style="padding:2px 8px 2px 0">${escHtml(it.item_name)}</td>
        <td style="padding:2px 8px;text-align:right;font-family:var(--font-mono)">${it.m2.toFixed(4)}</td>
        <td style="padding:2px 8px;text-align:right;font-family:var(--font-mono)">${it.quantity}</td>
        <td style="padding:2px 8px;text-align:right;font-family:var(--font-mono)">R ${price.toFixed(2)}</td>
        <td style="padding:2px 0;text-align:right;font-family:var(--font-mono)">R ${line.toFixed(4)}</td>
      </tr>`;
    }).join('');
    return `<div style="font-weight:700;color:#4a90d9;margin-bottom:8px;letter-spacing:.3px">⊟ MOUNTING CLEAT &nbsp;·&nbsp; ${escHtml(cleat.name)}</div>
      <table style="width:100%;border-collapse:collapse;color:var(--text)">
        <thead><tr style="color:var(--text-dim);font-size:11px;border-bottom:1px solid rgba(74,144,217,.3)">
          <th style="padding:2px 8px 4px 0;text-align:left">Item</th>
          <th style="padding:2px 8px 4px;text-align:right">M²</th>
          <th style="padding:2px 8px 4px;text-align:right">Qty</th>
          <th style="padding:2px 8px 4px;text-align:right">Price/m²</th>
          <th style="padding:2px 0 4px;text-align:right">Line</th>
        </tr></thead><tbody>${rows}</tbody>
        <tfoot><tr style="border-top:1px solid rgba(74,144,217,.3);font-weight:600;color:#4a90d9">
          <td colspan="4" style="padding:4px 8px 0 0">Total per cleat</td>
          <td style="padding:4px 0 0;text-align:right;font-family:var(--font-mono)">R ${total.toFixed(4)}</td>
        </tr></tfoot></table>`;
  }

  let _cleatTipTarget = null;
  document.addEventListener('mouseover', e => {
    const row = e.target.closest('tr.bom-cleat-row');
    if (!row || !row.dataset.cleatId) return;
    if (_suppressPricingTooltip) return;
    if (row === _cleatTipTarget) return;
    _cleatTipTarget = row;
    const cleat = _calcCleats.find(c => String(c.id) === row.dataset.cleatId);
    if (!cleat) return;
    cleatTip.innerHTML = buildCleatTip(cleat);
    cleatTip.style.display = 'block';
  });

  document.addEventListener('mousemove', e => {
    if (cleatTip.style.display === 'none') return;
    const vw = window.innerWidth, vh = window.innerHeight;
    const tw = cleatTip.offsetWidth + 16, th = cleatTip.offsetHeight + 16;
    const x = e.clientX + 16 + tw > vw ? e.clientX - tw : e.clientX + 16;
    const y = e.clientY + 16 + th > vh ? e.clientY - th - 8 : e.clientY + 16;
    cleatTip.style.left = x + 'px';
    cleatTip.style.top  = y + 'px';
  });

  document.addEventListener('mouseout', e => {
    const row = e.target.closest('tr.bom-cleat-row');
    if (row && !row.contains(e.relatedTarget)) {
      cleatTip.style.display = 'none';
      _cleatTipTarget = null;
    }
  });
});
