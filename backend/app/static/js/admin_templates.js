let currentTTId = null;
let allMats = [];      // full material list
let filteredMats = []; // filtered for BOM picker
let trailerMap = {};   // id -> trailer object
let currentTTView = localStorage.getItem('tt-view') || 'list';

function setTTView(view) {
  currentTTView = view;
  localStorage.setItem('tt-view', view);
  document.querySelectorAll('.tt-view-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.view === view));
  renderTrailerList(Object.values(trailerMap));
}

function renderTrailerList(tts) {
  const list = document.getElementById('trailer-list');
  if (!tts.length) {
    list.style.padding = '8px';
    list.innerHTML = '<div style="color:var(--text-dim);padding:12px;font-size:12px">No trailer types</div>';
    return;
  }
  if (currentTTView === 'tiles') {
    list.style.padding = '8px';
    list.innerHTML = `<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px">${
      tts.map(t => `
        <div class="tt-tile" id="tt-${t.id}" onclick="selectTrailer(${t.id})"
          style="padding:10px 6px;border-radius:6px;cursor:pointer;border:1px solid var(--border);background:var(--bg-panel);text-align:center">
          <div style="width:34px;height:34px;border-radius:50%;background:var(--blue);color:#fff;
            font-size:13px;font-weight:700;display:flex;align-items:center;justify-content:center;margin:0 auto 6px">
            ${escHtml(t.name.trim()[0].toUpperCase())}
          </div>
          <div style="font-size:11px;font-weight:600;line-height:1.3;word-break:break-word">${escHtml(t.name)}</div>
          ${t.markup_percentage != null ? `<div style="font-size:10px;color:var(--text-dim);margin-top:2px">${(t.markup_percentage*100).toFixed(0)}% markup</div>` : ''}
        </div>`).join('')
    }</div>`;
  } else if (currentTTView === 'details') {
    list.style.padding = '0';
    list.innerHTML = `<table style="width:100%;border-collapse:collapse;font-size:11px">
      <thead>
        <tr style="background:var(--bg-panel);border-bottom:2px solid var(--border)">
          <th style="padding:6px 10px;text-align:left;color:var(--text-dim);font-weight:600;white-space:nowrap">Name</th>
          <th style="padding:6px 8px;text-align:right;color:var(--text-dim);font-weight:600;white-space:nowrap">Markup</th>
        </tr>
      </thead>
      <tbody>${
        tts.map(t => `
          <tr class="tt-details-row" id="tt-${t.id}" onclick="selectTrailer(${t.id})" style="cursor:pointer;border-bottom:1px solid var(--border)">
            <td style="padding:8px 10px">
              <div style="font-weight:600;font-size:12px">${escHtml(t.name)}</div>
              ${t.description ? `<div style="color:var(--text-dim);font-size:10px">${escHtml(t.description)}</div>` : ''}
            </td>
            <td style="padding:8px;text-align:right;color:var(--text-dim)">${
              t.markup_percentage != null ? (t.markup_percentage*100).toFixed(0)+'%' : '—'
            }</td>
          </tr>`).join('')
      }</tbody>
    </table>`;
  } else {
    // List view (default)
    list.style.padding = '8px';
    list.innerHTML = tts.map(t => `
      <div class="part-item" id="tt-${t.id}" onclick="selectTrailer(${t.id})">
        <span class="part-dot"></span>
        <div>
          <div style="font-size:13px">${escHtml(t.name)}</div>
          <div style="font-size:10px;color:var(--text-dim)">${escHtml(t.description||'')}</div>
        </div>
      </div>`).join('');
  }
  // Restore selection highlight
  if (currentTTId && trailerMap[currentTTId]) {
    document.getElementById(`tt-${currentTTId}`)?.classList.add('selected');
  }
}

// ── Load all materials for BOM picker ──────────────────
async function loadAllMats() {
  try {
    allMats = await api('GET', '/api/materials');
    filteredMats = allMats;
    renderBomMatSelect(allMats);
  } catch(e) { toast('Failed to load materials: ' + e.message, 'error'); }
}

// ── Load trailer types ─────────────────────────────────
async function loadTrailers() {
  try {
    const tts = await api('GET', '/api/trailers');
    trailerMap = {};
    tts.forEach(t => trailerMap[t.id] = t);
    document.getElementById('tt-count').textContent = tts.length;
    renderTrailerList(tts);
    // Auto-select whichever trailer the user last focused on the calculator
    // (or here). Only on initial load, when nothing is selected yet.
    if (!currentTTId) {
      const focused = parseInt(sessionStorage.getItem('focusedTrailerId') || '', 10);
      if (focused && trailerMap[focused]) {
        selectTrailer(focused);
        document.getElementById(`tt-${focused}`)?.scrollIntoView({block: 'center', behavior: 'smooth'});
      }
    }
  } catch(e) { toast('Failed to load trailers: ' + e.message, 'error'); }
}

function selectTrailer(id) {
  document.querySelectorAll('.part-item, .tt-tile, .tt-details-row').forEach(el => el.classList.remove('selected'));
  document.getElementById(`tt-${id}`)?.classList.add('selected');
  sortedBOMCats.clear();
  collapsedSections.clear();
  currentTTId = id;
  try { sessionStorage.setItem('focusedTrailerId', String(id)); } catch(_) {}
  const t = trailerMap[id];
  document.getElementById('bom-title').textContent = t ? t.name : 'Trailer';
  ['btn-rename','btn-dup','btn-del','btn-add-bom','btn-bom-sort','btn-collapse-all'].forEach(b =>
    document.getElementById(b).classList.remove('hidden'));

  // Populate default dimension fields
  const bar = document.getElementById('dims-bar');
  bar.classList.remove('hidden');
  document.getElementById('tt-length').value  = t && t.default_length    != null ? t.default_length    : '';
  document.getElementById('tt-width').value   = t && t.default_width     != null ? t.default_width     : '';
  document.getElementById('tt-height').value  = t && t.default_height    != null ? t.default_height    : '';
  document.getElementById('tt-markup').value  = t && t.markup_percentage != null ? (t.markup_percentage * 100).toFixed(1) : '';
  const cfgv2 = document.getElementById('tt-cfgv2');
  if (cfgv2) cfgv2.checked = !!(t && t.configurator_v2);
  const cfgv2Label = document.getElementById('tt-cfgv2-label');
  if (cfgv2Label) cfgv2Label.style.color = (t && t.configurator_v2) ? 'var(--blue-hi)' : 'var(--text-dim)';
  document.getElementById('dims-saved').style.opacity = '0';

  loadBOM(id);
}

async function saveConfiguratorV2() {
  if (!currentTTId) return;
  const next = !!document.getElementById('tt-cfgv2').checked;
  // Guard against accidental disable — turning OFF v2 hides the configurator
  // panel on the costings page for everyone using this trailer type.
  if (!next) {
    const ok = await confirmModal('This will hide the body-options tree on the costings page and revert to the legacy flat panel.', { title: 'Disable Configurator v2?', okText: 'Disable', danger: true });
    if (!ok) {
      // Revert the checkbox without saving
      document.getElementById('tt-cfgv2').checked = true;
      return;
    }
  }
  try {
    await api('PUT', `/api/trailers/${currentTTId}`, { configurator_v2: next });
    if (trailerMap[currentTTId]) trailerMap[currentTTId].configurator_v2 = next;
    const lbl = document.getElementById('tt-cfgv2-label');
    if (lbl) lbl.style.color = next ? 'var(--blue-hi)' : 'var(--text-dim)';
    const saved = document.getElementById('dims-saved');
    saved.style.opacity = '1';
    setTimeout(() => { saved.style.opacity = '0'; }, 800);
  } catch (e) {
    // Revert UI if the save failed
    document.getElementById('tt-cfgv2').checked = !next;
  }
}

async function saveDimensions() {
  if (!currentTTId) return;
  const length  = parseFloat(document.getElementById('tt-length').value)  || null;
  const width   = parseFloat(document.getElementById('tt-width').value)   || null;
  const height  = parseFloat(document.getElementById('tt-height').value)  || null;
  const markupPct = parseFloat(document.getElementById('tt-markup').value);
  const markup  = isNaN(markupPct) ? null : markupPct / 100;
  try {
    await api('PUT', `/api/trailers/${currentTTId}`, {
      default_length:    length,
      default_width:     width,
      default_height:    height,
      markup_percentage: markup,
    });
    // Update local cache
    if (trailerMap[currentTTId]) {
      trailerMap[currentTTId].default_length    = length;
      trailerMap[currentTTId].default_width     = width;
      trailerMap[currentTTId].default_height    = height;
      trailerMap[currentTTId].markup_percentage = markup;
    }
    const saved = document.getElementById('dims-saved');
    saved.style.opacity = '1';
    setTimeout(() => { saved.style.opacity = '0'; }, 2000);
  } catch(e) { toast(e.message, 'error'); }
}


// ── BOM editor ─────────────────────────────────────────
let _cachedBOM = []; // last-fetched BOM items — re-render without re-fetching for sort/filter
// Cached pending formula-link suggestions for the current trailer, keyed by bom_id.
// Empty when no scan has been run, or after suggestions have been applied.
let _pendingFormulaLinks = {};

async function loadBOM(id) {
  const wrap = document.getElementById('bom-wrap');
  wrap.innerHTML = '<div style="padding:20px;text-align:center"><span class="spinner"></span></div>';
  try {
    const [bom, pending] = await Promise.all([
      api('GET', `/api/trailers/${id}/bom`),
      _fetchPendingFormulaLinks(id),
    ]);
    _cachedBOM = bom;
    _pendingFormulaLinks = pending;
    renderBOM(_cachedBOM);
    _applyFocusedSection();
  } catch(e) {
    wrap.innerHTML = `<div style="padding:16px;color:var(--red)">${e.message}</div>`;
  }
}

async function _fetchPendingFormulaLinks(trailerId) {
  // Soft fetch — never break BOM loading if this endpoint is unavailable.
  try {
    const r = await api('GET', `/api/admin/formula-scan/pending/${trailerId}`);
    return r && r.items ? r.items : {};
  } catch(_) {
    return {};
  }
}

// Right-click on a BOM row.
//   • No selection (or click landed on this row alone) → open Edit modal
//     (matches the original behaviour).
//   • One or more rows ticked via the checkboxes → custom context menu
//     with the bulk Inclusion-mode actions.
// Falls through to the native browser menu when the click landed on a
// control (button/input/link) so users can still copy text or use the
// checkbox.
function _bomRowContextMenu(event, bomId) {
  if (event.target.closest('button, input, textarea, select, a')) return true;
  event.preventDefault();
  if (selectedBOMIds.size > 0) {
    _showBomBulkContextMenu(event.clientX, event.clientY);
  } else {
    openEditBOM(bomId);
  }
  return false;
}

// ── Custom context menu for bulk Inclusion-mode actions ───────────
function _showBomBulkContextMenu(x, y) {
  // Tear down any previous instance
  document.getElementById('bom-bulk-ctx')?.remove();

  // Pick a sensible default for the radio group name: if any selected
  // rows already share a body_option_subgroup, reuse that; otherwise
  // fall back to the most common section name across the selection.
  const selRows = _cachedBOM.filter(r => selectedBOMIds.has(r.id));
  const sectionCounts = {};
  selRows.forEach(r => {
    const k = r.bom_section || r.category || '';
    if (k) sectionCounts[k] = (sectionCounts[k] || 0) + 1;
  });
  const dominantSection = Object.entries(sectionCounts)
    .sort((a, b) => b[1] - a[1])[0]?.[0] || '';
  const existingGroups = [...new Set(
    selRows.map(r => r.selection_group || r.body_option_subgroup).filter(Boolean)
  )];
  const defaultGroup = existingGroups[0] || dominantSection;

  const n = selectedBOMIds.size;
  const menu = document.createElement('div');
  menu.id = 'bom-bulk-ctx';
  menu.style.cssText = `
    position:fixed; z-index:9999; min-width:240px;
    background:var(--bg-panel); border:1px solid var(--border);
    border-radius:6px; box-shadow:0 6px 20px rgba(0,0,0,.5);
    padding:4px 0; font-size:13px; user-select:none;
  `;
  menu.innerHTML = `
    <div style="padding:6px 14px;color:var(--text-dim);font-size:11px;
      letter-spacing:.5px;text-transform:uppercase;border-bottom:1px solid var(--border)">
      ${n} row${n === 1 ? '' : 's'} selected
    </div>
    <div class="bom-ctx-item" data-action="single"
      style="padding:8px 14px;cursor:pointer;color:var(--text)">
      ◉ Mark as radio choices…
    </div>
    <div class="bom-ctx-item" data-action="multi"
      style="padding:8px 14px;cursor:pointer;color:var(--text)">
      ☑ Mark as tick box choices
    </div>
    <div style="height:1px;background:var(--border);margin:4px 0"></div>
    <div class="bom-ctx-item" data-action="always"
      style="padding:8px 14px;cursor:pointer;color:var(--text-dim)">
      ↺ Reset to always include
    </div>
  `;
  document.body.appendChild(menu);
  // Position, then nudge if off-screen
  const w = window.innerWidth, h = window.innerHeight;
  const r = menu.getBoundingClientRect();
  menu.style.left = (x + r.width  > w ? w - r.width  - 6 : x) + 'px';
  menu.style.top  = (y + r.height > h ? h - r.height - 6 : y) + 'px';

  menu.querySelectorAll('.bom-ctx-item').forEach(el => {
    el.addEventListener('mouseenter', () => el.style.background = 'var(--bg-input)');
    el.addEventListener('mouseleave', () => el.style.background = '');
    el.addEventListener('click', () => {
      const action = el.dataset.action;
      menu.remove();
      _applyBulkSelectionMode(action, defaultGroup);
    });
  });
  // Tear down on any outside click or Escape
  const tearDown = (ev) => {
    if (!menu.contains(ev.target)) {
      menu.remove();
      document.removeEventListener('mousedown', tearDown, true);
      document.removeEventListener('keydown', escDown, true);
    }
  };
  const escDown = (ev) => {
    if (ev.key === 'Escape') {
      menu.remove();
      document.removeEventListener('mousedown', tearDown, true);
      document.removeEventListener('keydown', escDown, true);
    }
  };
  setTimeout(() => {
    document.addEventListener('mousedown', tearDown, true);
    document.addEventListener('keydown', escDown, true);
  }, 0);
}

async function _applyBulkSelectionMode(mode, defaultGroup) {
  if (!selectedBOMIds.size) return;
  const ids = [...selectedBOMIds];
  let selection_group = null;
  if (mode === 'single') {
    if (ids.length < 2) {
      toast('Select at least 2 rows to make a radio group', 'error');
      return;
    }
    // No prompt — auto-use the section name (or any existing subgroup
    // already on the selected rows). User can rename later via the
    // existing pencil ✎ on the body-options group header in the
    // calculator.
    selection_group = (defaultGroup || 'CHOICE GROUP').trim().toUpperCase();
  }
  try {
    const r = await api('POST', '/api/bom/bulk-selection-mode', {
      ids, mode, selection_group,
    });
    const labels = { always: 'Always include', single: 'Radio choices', multi: 'Tick box choices' };
    let msg = `${r.updated} row${r.updated === 1 ? '' : 's'} → ${labels[mode]}`;
    if (mode === 'single') msg += ` (group: "${selection_group}")`;
    toast(msg, 'success');
    selectedBOMIds.clear();
    await loadBOM(currentTTId);
  } catch (e) {
    toast('Failed: ' + (e.message || e), 'error', 5000);
  }
}

// Right-click on a section header → opens the "Link Section to Body Option"
// dialog. Same fall-through rule as the row handler so right-click on the
// rename ✎, multiplier ×N, sort A↕Z, etc. still works.
function _bomSectionContextMenu(event, sectionName) {
  if (event.target.closest('button, input, textarea, select, a')) return true;
  event.preventDefault();
  openLinkSectionToOption(sectionName);
  return false;
}

// ── Link Section to Body Option ────────────────────────────────────
let _linkSecState = { section: '', items: 0 };

function openLinkSectionToOption(sectionName) {
  const itemsInSec = _cachedBOM.filter(it => it.category === sectionName);
  const linkable = itemsInSec.filter(it => !it.is_body_option);
  if (!linkable.length) {
    alertModal(`Section "${sectionName}" has no regular items to link.`);
    return;
  }
  _linkSecState = { section: sectionName, items: linkable.length };
  document.getElementById('link-sec-name').textContent = sectionName;
  document.getElementById('link-sec-count').textContent = linkable.length;
  document.getElementById('link-sec-new-name').value = sectionName;
  document.getElementById('link-sec-new-group').textContent = sectionName.toUpperCase();
  document.getElementById('link-sec-new-default').checked = true;

  // Populate existing-options dropdown from the cached BOM
  const sel = document.getElementById('link-sec-existing');
  const existingOptions = _cachedBOM
    .filter(it => it.is_body_option)
    .sort((a, b) => (a.body_option_group || '').localeCompare(b.body_option_group || '')
                || a.material_name.localeCompare(b.material_name));
  if (!existingOptions.length) {
    sel.innerHTML = '<option value="">— no body options on this trailer yet —</option>';
    sel.disabled = true;
    document.getElementById('link-sec-mode-new').checked = true;
    document.getElementById('link-sec-mode-existing').disabled = true;
  } else {
    sel.disabled = false;
    document.getElementById('link-sec-mode-existing').disabled = false;
    document.getElementById('link-sec-mode-existing').checked = true;
    sel.innerHTML = '<option value="">— select an option —</option>' +
      existingOptions.map(o => {
        const grp = o.body_option_group ? `[${escHtml(o.body_option_group)}] ` : '';
        return `<option value="${o.id}">${grp}${escHtml(o.material_name)}</option>`;
      }).join('');
  }
  onLinkSecModeChange();
  openModal('modal-link-section-to-option');
}

function onLinkSecModeChange() {
  const useExisting = document.getElementById('link-sec-mode-existing').checked;
  document.getElementById('link-sec-existing').disabled = !useExisting;
  document.getElementById('link-sec-new-fields').style.display = useExisting ? 'none' : '';
}

async function confirmLinkSectionToOption() {
  const useExisting = document.getElementById('link-sec-mode-existing').checked;
  const payload = { section: _linkSecState.section };
  if (useExisting) {
    const id = parseInt(document.getElementById('link-sec-existing').value) || 0;
    if (!id) { alertModal('Pick an existing body option, or switch to "Create a new body option".'); return; }
    payload.existing_option_id = id;
  } else {
    const name = (document.getElementById('link-sec-new-name').value || '').trim();
    if (!name) { alertModal('Enter a name for the new body option.'); return; }
    payload.new_option = {
      name: name,
      default_selected: document.getElementById('link-sec-new-default').checked,
      group: _linkSecState.section,
    };
  }

  const btn = document.getElementById('link-sec-confirm-btn');
  btn.disabled = true;
  try {
    const r = await api('POST', `/api/trailers/${currentTTId}/bom/link-section-to-option`, payload);
    closeModal('modal-link-section-to-option');
    await loadBOM(currentTTId);
    _showLinkSectionResult(r);
  } catch (e) {
    toast('Link failed: ' + (e.message || e), 'error', 5000);
  } finally {
    btn.disabled = false;
  }
}

function _showLinkSectionResult(r) {
  const skipped = r.skipped || [];
  const linked  = r.linked  || 0;
  const optName = (r.option && r.option.name) || '';
  const isNew   = !!(r.option && r.option.is_new);

  // Title reflects outcome: green checkmark when nothing was skipped,
  // amber warning when some were.
  const titleEl = document.getElementById('link-result-title');
  if (skipped.length === 0) {
    titleEl.innerHTML = '<span style="color:var(--green)">✓</span> Section linked';
  } else if (linked === 0) {
    titleEl.innerHTML = '<span style="color:var(--orange,#f0a500)">⚠</span> Nothing to link';
  } else {
    titleEl.innerHTML = '<span style="color:var(--orange,#f0a500)">⚠</span> Section linked with skips';
  }

  const summary = document.getElementById('link-result-summary');
  const newTag  = isNew
    ? ` <span style="font-size:10px;background:#0a1f15;color:#3d9970;border:1px solid #2d7a57;
        border-radius:3px;padding:1px 6px;margin-left:6px;letter-spacing:.3px">new option created</span>`
    : '';
  summary.innerHTML = `Linked <b>${linked}</b> item${linked === 1 ? '' : 's'} ` +
    `to <b>${escHtml(optName)}</b>${newTag}.`;

  const wrap = document.getElementById('link-result-skipped-wrap');
  if (skipped.length) {
    document.getElementById('link-result-skip-count').textContent = skipped.length;
    document.getElementById('link-result-skipped').innerHTML =
      skipped.map(s =>
        `<div style="padding:3px 0">
           <span style="color:var(--text)">${escHtml(s.name || '?')}</span>
           <span style="color:var(--text-dim)"> — ${escHtml(s.reason || '')}</span>
         </div>`).join('');
    wrap.style.display = '';
  } else {
    wrap.style.display = 'none';
  }
  openModal('modal-link-section-result');
}

function _applyFocusedSection() {
  let sec;
  try { sec = sessionStorage.getItem('focusedBomSection'); } catch(_) { return; }
  if (!sec) return;
  try { sessionStorage.removeItem('focusedBomSection'); } catch(_) {}
  if (!collapsedSections.has(sec)) return; // already expanded
  collapsedSections.delete(sec);
  _saveBomCollapseState();
  renderBOM(_cachedBOM);
  requestAnimationFrame(() => {
    const hdr = document.querySelector(`[data-section-name="${CSS.escape(sec)}"]`);
    hdr?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  });
}

const selectedBOMIds = new Set();
let bomSorted = localStorage.getItem('bom-sorted') === '1';
const sortedBOMCats = new Set();    // sections with per-section A-Z on
const collapsedSections = new Set(); // sections currently collapsed
let _bomLoadedForTT = null;         // trailer id of the last BOM that was rendered

function toggleCatSort(cat) {
  if (sortedBOMCats.has(cat)) sortedBOMCats.delete(cat);
  else sortedBOMCats.add(cat);
  renderBOM(_cachedBOM);
}

function toggleSectionCollapse(cat) {
  if (collapsedSections.has(cat)) collapsedSections.delete(cat);
  else collapsedSections.add(cat);
  _saveBomCollapseState();
  renderBOM(_cachedBOM);
}

function toggleCollapseAll() {
  const groups = {};
  _cachedBOM.forEach(it => { groups[it.category] = true; });
  const allCollapsed = Object.keys(groups).every(c => collapsedSections.has(c));
  if (allCollapsed) {
    collapsedSections.clear();
  } else {
    Object.keys(groups).forEach(c => collapsedSections.add(c));
  }
  _saveBomCollapseState();
  renderBOM(_cachedBOM);
}

let bomSectionMap = {}; // name -> {id, multiplier}

async function createBOMSection(targetSelectId) {
  const name = await promptModal(
    'Enter a new BOM section name (e.g. "INT FALSE BULKHEAD").',
    '',
    { title: 'New BOM section', okText: 'Create' }
  );
  if (!name) return;
  const trimmed = name.trim();
  if (!trimmed) return;
  try {
    const r = await api('POST', '/api/bom-sections', { name: trimmed });
    await loadBOMSections();
    const sel = document.getElementById(targetSelectId);
    if (sel) sel.value = r.name;
    toast(r.created ? `Section "${r.name}" created` : `Section "${r.name}" already existed`, 'success');
  } catch(e) { toast('Failed: ' + e.message, 'error'); }
}

async function loadBOMSections() {
  try {
    const sections = await api('GET', '/api/bom-sections');
    bomSectionMap = {};
    sections.forEach(s => { bomSectionMap[s.name] = s; });
    const sorted = [...sections].sort(
      (a, b) => a.name.localeCompare(b.name, undefined, {sensitivity: 'base'}));
    const opts = '<option value="">— pick a section —</option>' +
      sorted.map(s => {
        // Optional sections (EXTRAS / OPTIONAL EXTRAS): red text + tooltip so
        // the admin knows these behave as non-standard opt-in items on the
        // costing pages. Native <select> styling support is uneven across
        // browsers but this works well enough in Firefox + the open list on
        // Chromium.
        const isOpt = !!s.is_optional;
        const style = isOpt ? ' style="color:var(--red,#e35d6a)"' : '';
        const title = isOpt ? ' title="Non Standard items"' : '';
        return `<option value="${escHtml(s.name)}"${style}${title}>${escHtml(s.name)}</option>`;
      }).join('');
    ['bom-section', 'edit-bom-section'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = opts;
    });
  } catch(e) { /* non-fatal */ }
}

async function renameSection(sectionName) {
  const sec = bomSectionMap[sectionName];
  if (!sec) return toast('Section not found', 'error');
  const newName = await promptModal(
    `Rename "${sectionName}" to:`,
    sectionName,
    { title: `Rename section`, okText: 'Rename' }
  );
  if (newName === null) return;
  const trimmed = (newName || '').trim();
  if (!trimmed || trimmed === sectionName) return;
  try {
    await api('PUT', `/api/bom-sections/${sec.id}`, { name: trimmed });
    toast(`Renamed "${sectionName}" → "${trimmed}"`, 'success');
    await loadBOMSections();
    await loadBOM(currentTTId);
  } catch(e) {
    toast('Rename failed: ' + e.message, 'error');
  }
}

async function setSectionMultiplier(sectionName, currentMult) {
  const input = await promptModal(
    `Enter a multiplier for "${sectionName}" (e.g. 2 for two sides, 1 for default).`,
    currentMult,
    { title: `Multiplier — ${sectionName}`, okText: 'Apply' }
  );
  if (input === null) return; // cancelled
  const val = parseFloat(input);
  if (isNaN(val) || val < 0) { toast('Invalid multiplier — enter a positive number', 'error'); return; }
  const sec = bomSectionMap[sectionName];
  if (!sec) { toast('Section not found in registry', 'error'); return; }
  try {
    await api('PUT', `/api/bom-sections/${sec.id}`, { multiplier: val });
    sec.multiplier = val;
    toast(`Multiplier for "${sectionName}" set to ${val}`);
    renderBOM(_cachedBOM);
  } catch(e) { toast(e.message, 'error'); }
}

function populateSectionDatalist() { /* kept for compat — no-op */ }

function toggleBOMSort() {
  bomSorted = !bomSorted;
  localStorage.setItem('bom-sorted', bomSorted ? '1' : '0');
  document.getElementById('btn-bom-sort')?.classList.toggle('active', bomSorted);
  renderBOM(_cachedBOM);
}

function updateBulkDeleteBar() {
  const btn   = document.getElementById('btn-del-selected');
  const count = document.getElementById('sel-count');
  const radio = document.getElementById('btn-mark-radio');
  const multi = document.getElementById('btn-mark-checkbox');
  const reset = document.getElementById('btn-mark-always');
  const hasSel = selectedBOMIds.size > 0;
  if (hasSel) {
    btn.style.display   = '';
    count.textContent   = selectedBOMIds.size;
    if (multi) multi.style.display = '';
    if (reset) reset.style.display = '';
    // Radio needs at least 2 rows to be meaningful
    if (radio) radio.style.display = (selectedBOMIds.size >= 2) ? '' : 'none';
  } else {
    btn.style.display = 'none';
    if (radio) radio.style.display = 'none';
    if (multi) multi.style.display = 'none';
    if (reset) reset.style.display = 'none';
  }
  // Sync select-all checkbox state
  const allCbs = document.querySelectorAll('.bom-cb');
  const selAll = document.getElementById('bom-sel-all');
  if (selAll) {
    selAll.checked = allCbs.length > 0 && allCbs.length === selectedBOMIds.size;
    selAll.indeterminate = selectedBOMIds.size > 0 && selectedBOMIds.size < allCbs.length;
  }
}

function _bulkInclusionDefaultGroup() {
  // Mirrors the auto-default logic from the right-click context menu so
  // the toolbar buttons land at the same place.
  const selRows = _cachedBOM.filter(r => selectedBOMIds.has(r.id));
  const sectionCounts = {};
  selRows.forEach(r => {
    const k = r.bom_section || r.category || '';
    if (k) sectionCounts[k] = (sectionCounts[k] || 0) + 1;
  });
  const dominantSection = Object.entries(sectionCounts)
    .sort((a, b) => b[1] - a[1])[0]?.[0] || '';
  const existingGroups = [...new Set(
    selRows.map(r => r.selection_group || r.body_option_subgroup).filter(Boolean)
  )];
  return existingGroups[0] || dominantSection;
}

function markSelectedBOMRadio()    { _applyBulkSelectionMode('single', _bulkInclusionDefaultGroup()); }
function markSelectedBOMMulti()    { _applyBulkSelectionMode('multi',  _bulkInclusionDefaultGroup()); }
function markSelectedBOMAlways()   { _applyBulkSelectionMode('always', _bulkInclusionDefaultGroup()); }

function toggleBOMItem(id, checked) {
  if (checked) selectedBOMIds.add(id);
  else selectedBOMIds.delete(id);
  updateBulkDeleteBar();
}

function toggleAllBOM(checked) {
  document.querySelectorAll('.bom-cb').forEach(cb => {
    cb.checked = checked;
    const id = +cb.dataset.id;
    if (checked) selectedBOMIds.add(id);
    else selectedBOMIds.delete(id);
  });
  updateBulkDeleteBar();
}

async function deleteSelectedBOM() {
  if (!selectedBOMIds.size) return;
  if (!await confirmModal(`Delete ${selectedBOMIds.size} selected item(s)? This cannot be undone.`, { title: 'Delete items', okText: 'Delete', danger: true })) return;
  try {
    await api('POST', '/api/bom/bulk-delete', { ids: [...selectedBOMIds] });
    toast(`${selectedBOMIds.size} item(s) deleted`);
    selectedBOMIds.clear();
    updateBulkDeleteBar();
    await loadBOM(currentTTId);
  } catch(e) {
    toast(e.message, 'error');
  }
}

function _saveBomCollapseState() {
  if (!currentTTId) return;
  try { localStorage.setItem(`burtcost.bom_collapse_${currentTTId}`, JSON.stringify([...collapsedSections])); } catch(_) {}
}

// Section-header "exclude from Calculator 2" toggle — bulk-sets
// calc2_default_excluded on every BOM row in the section, then re-renders.
async function toggleSectionCalc2Default(cat, checked) {
  const rows = _cachedBOM.filter(r => r.category === cat);
  const ids = rows.map(r => r.id);
  if (!ids.length) return;
  try {
    await api('POST', '/api/bom/bulk-calc2-default', { ids, excluded: checked });
    rows.forEach(r => { r.calc2_default_excluded = checked; });
    renderBOM(_cachedBOM);
    toast(`${ids.length} item${ids.length === 1 ? '' : 's'} ${checked ? 'excluded from' : 'included in'} Calculator 2 by default`, 'success');
  } catch (e) {
    toast(e.message, 'error');
    renderBOM(_cachedBOM);
  }
}

function renderBOM(items) {
  const wrap = document.getElementById('bom-wrap');
  selectedBOMIds.clear();
  updateBulkDeleteBar();
  if (!items.length) {
    wrap.innerHTML = '<div style="padding:20px;color:var(--text-dim);font-size:13px;text-align:center">No items yet — click "+ Add Item"</div>';
    return;
  }

  // On first render for a new trailer: restore saved state or default to all collapsed
  if (_bomLoadedForTT !== currentTTId) {
    _bomLoadedForTT = currentTTId;
    const saved = localStorage.getItem(`burtcost.bom_collapse_${currentTTId}`);
    collapsedSections.clear();
    if (saved) {
      try { JSON.parse(saved).forEach(c => collapsedSections.add(c)); } catch(_) {}
    } else {
      items.forEach(it => { if (it.category) collapsedSections.add(it.category); });
    }
  }

  let html = `<table style="width:100%;font-size:13px;border-collapse:collapse">
    <thead><tr style="background:var(--bg-panel)">
      <th style="padding:8px 12px;width:32px">
        <input type="checkbox" id="bom-sel-all" onchange="toggleAllBOM(this.checked)"
          title="Select all" style="cursor:pointer">
      </th>
      <th style="padding:8px 12px;text-align:left;color:var(--text-dim);font-size:10px;letter-spacing:1px">Material</th>
      <th style="padding:8px 12px;text-align:left;color:var(--text-dim);font-size:10px">Category</th>
      <th style="padding:8px 12px;text-align:left;color:var(--text-dim);font-size:10px">Formula</th>
      <th style="padding:8px 12px;text-align:center;color:var(--text-dim);font-size:10px">Waste%</th>
      <th style="padding:8px 12px;text-align:right;color:var(--text-dim);font-size:10px">Unit Price</th>
      <th style="padding:8px 12px"></th>
    </tr></thead><tbody>`;

  // Group by category
  const groups = {};
  items.forEach(it => {
    if (!groups[it.category]) groups[it.category] = [];
    groups[it.category].push(it);
  });


  for (const [cat, its] of Object.entries(groups)) {
    const catSorted = bomSorted || sortedBOMCats.has(cat);
    const sortedIts = catSorted ? [...its].sort((a, b) => a.material_name.localeCompare(b.material_name)) : its;
    const sortIcon = sortedBOMCats.has(cat) && !bomSorted
      ? ' <span style="opacity:.7;font-size:9px">A↑Z</span>'
      : ' <span style="opacity:.3;font-size:9px">A↕Z</span>';

    // Multiplier badge — shown in red when != 1
    // Use single-quoted onclick attrs so JSON.stringify's double quotes don't break the HTML
    const secInfo = bomSectionMap[cat];
    const mult = secInfo ? (secInfo.multiplier || 1) : 1;
    const catJson = JSON.stringify(cat);
    const collapsed = collapsedSections.has(cat);
    const chevron = collapsed ? '▶' : '▼';

    const multBadge = mult !== 1
      ? ` <span onclick='event.stopPropagation();setSectionMultiplier(${catJson},${mult})'
            title="× ${mult} multiplier active — click to change"
            style="margin-left:8px;background:#3a1a1a;color:#ff6b6b;border:1px solid #f44336;
              border-radius:4px;padding:1px 6px;font-size:10px;letter-spacing:.5px;cursor:pointer">
            × ${mult}
          </span>`
      : ` <span onclick='event.stopPropagation();setSectionMultiplier(${catJson},1)'
            title="Click to set a multiplier for this section"
            style="margin-left:6px;opacity:.25;font-size:10px;cursor:pointer">× 1</span>`;

    // Sort icon is now its own click target (stopPropagation so header click stays for collapse)
    const sortIconEl = catSorted && !bomSorted
      ? ` <span onclick='event.stopPropagation();toggleCatSort(${catJson})'
            title="Sorted A–Z — click to restore original order"
            style="margin-left:6px;opacity:.8;font-size:9px;cursor:pointer">A↑Z</span>`
      : ` <span onclick='event.stopPropagation();toggleCatSort(${catJson})'
            title="Click to sort this section A–Z"
            style="margin-left:4px;opacity:.25;font-size:9px;cursor:pointer">A↕Z</span>`;

    const itemCount = its.length;

    // Formula-presence dots: one dot per distinct formula type linked in this section
    const counts = { skin: 0, tape: 0, floor: 0, cleat: 0 };
    let pendingCount = 0, reviewCount = 0, mismatchCount = 0;
    its.forEach(x => {
      if (x.skin_formula_id) counts.skin++;
      if (x.taping_block_id) counts.tape++;
      if (x.floor_plate_id) counts.floor++;
      if (x.mounting_cleat_id) counts.cleat++;
      // Pending/review counts mirror the row-level pill logic so a
      // collapsed section header shows the same totals the user would
      // count if they expanded it.
      const p = _pendingFormulaLinks[String(x.id)];
      if (!p) return;
      const fkMap = {
        'skin_formulas':   x.skin_formula_id,
        'taping_blocks':   x.taping_block_id,
        'floor_plates':    x.floor_plate_id,
        'mounting_cleats': x.mounting_cleat_id,
      };
      const currentFk = p.target_table ? fkMap[p.target_table] : null;
      const stillNeedsAction = p.status === 'unknown_ref'
        ? !(x.skin_formula_id || x.taping_block_id || x.floor_plate_id || x.mounting_cleat_id)
        : !currentFk;
      if (!stillNeedsAction) return;
      if (p.status === 'unknown_ref') reviewCount++;
      else if (p.status === 'overwrite') mismatchCount++;
      else pendingCount++;
    });
    const dot = (color, label, n) => n > 0
      ? `<span title="${n} ${label} ${n===1?'item':'items'} in this section"
          style="display:inline-block;width:8px;height:8px;border-radius:50%;
            background:${color};margin-left:4px;vertical-align:middle"></span>`
      : '';
    const formulaDots = dot('#58a6ff', 'skin formula', counts.skin)
                      + dot('#f0a500', 'taping block', counts.tape)
                      + dot('#3d9970', 'floor plate', counts.floor)
                      + dot('#4a90d9', 'mounting cleat', counts.cleat);
    const sectionBadge = (bg, fg, border, label, count, tipLabel) =>
      count > 0
        ? ` <span title="${count} ${tipLabel} item${count===1?'':'s'} in this section"
              style="font-size:9px;background:${bg};color:${fg};border:1px solid ${border};
                border-radius:3px;padding:1px 5px;margin-left:6px;letter-spacing:.3px;
                white-space:nowrap;font-weight:600">⚠ ${count} ${label}</span>`
        : '';
    const formulaActionBadges =
        sectionBadge('#3a2400', '#f0a500', '#b07800', 'pending',  pendingCount,  'pending-link')
      + sectionBadge('#3a1010', '#ff6b6b', '#b03030', 'mismatch', mismatchCount, 'mismatched')
      + sectionBadge('#1f1530', '#a371f7', '#6b3fb5', 'review',   reviewCount,   'manual-review');

    const renameBtn = secInfo
      ? ` <span onclick='event.stopPropagation();renameSection(${catJson})'
            title="Rename section"
            style="margin-left:6px;opacity:.4;font-size:11px;cursor:pointer">✎</span>`
      : '';

    // Section-level "exclude from Calculator 2" toggle. State is derived from
    // the rows: checked = all excluded, indeterminate = some, unchecked = none.
    const _c2Total = its.length;
    const _c2Excl  = its.filter(x => x.calc2_default_excluded).length;
    const _c2All   = _c2Total > 0 && _c2Excl === _c2Total;
    const _c2Some  = _c2Excl > 0 && !_c2All;
    const calc2Toggle = ` <label onclick="event.stopPropagation()"
        title="Exclude every item in this section from Calculator 2 by default"
        style="margin-left:8px;font-size:9px;font-weight:400;letter-spacing:.3px;text-transform:none;cursor:pointer;color:var(--text-dim);white-space:nowrap">
        <input type="checkbox" class="sec-calc2-tick"${_c2All ? ' checked' : ''}${_c2Some ? ' data-indeterminate="1"' : ''}
          onchange='toggleSectionCalc2Default(${catJson}, this.checked)'
          style="cursor:pointer;width:12px;height:12px;vertical-align:middle;accent-color:var(--red)"> excl. Calc 2</label>`;
    const _secMeta = bomSectionMap[cat];
    const _isOpt   = !!(_secMeta && _secMeta.is_optional);
    const _hdrColor = _isOpt ? 'var(--red,#e35d6a)' : 'var(--blue-hi)';
    const _hdrTitleBase = `${collapsed ? 'Expand' : 'Collapse'} section · right-click for options`;
    const _hdrTitle = _isOpt ? `Non Standard items · ${_hdrTitleBase}` : _hdrTitleBase;
    html += `<tr style="background:var(--bg-panel);cursor:pointer;user-select:none"
      data-section-name="${escHtml(cat)}"
      onclick='toggleSectionCollapse(${catJson})'
      oncontextmenu='return _bomSectionContextMenu(event, ${catJson})'
      title="${_hdrTitle}"
      onmouseover="this.style.background='var(--bg-input)'"
      onmouseout="this.style.background='var(--bg-panel)'">
      <td></td>
      <td colspan="6" style="padding:6px 12px;font-family:var(--font-mono);font-size:10px;
        color:${_hdrColor};letter-spacing:1.2px;text-transform:uppercase">
        <span style="margin-right:6px;font-size:9px;opacity:.6">${chevron}</span>${escHtml(cat)}
        <span style="opacity:.4;font-size:9px;font-weight:400;letter-spacing:0;text-transform:none;margin-left:4px">(${itemCount})</span>
        ${formulaDots}${formulaActionBadges}${renameBtn}${multBadge}${sortIconEl}${calc2Toggle}
      </td>
    </tr>`;

    if (!collapsed) sortedIts.forEach(it => {
      const subgroupBadge = it.is_body_option && it.body_option_subgroup
        ? ` <span title="Sub-group: ${escHtml(it.body_option_subgroup)}"
              style="font-size:9px;background:var(--bg-input);color:var(--blue-hi);
                border:1px solid var(--border);border-radius:3px;padding:1px 5px;
                letter-spacing:.3px;white-space:nowrap">${escHtml(it.body_option_subgroup)}</span>`
        : (it.is_body_option
            ? `<span style="font-size:9px;color:var(--text-dim);opacity:.5">no subgroup</span>`
            : '');
      // Link-count badge: only on body-option rows. Red when 0 = orphan option (selecting it on the calculator does nothing).
      let linkedBadge = '';
      if (it.is_body_option) {
        const linkedRows = items.filter(x => !x.is_body_option && x.body_option_linked === it.material_name);
        if (linkedRows.length === 0) {
          linkedBadge = ` <span title="No BOM rows are linked to this body option — selecting it on the calculator will not change the BOM. Edit a regular row and set its 'Linked Body Option' to '${escHtml(it.material_name)}'."
              style="font-size:9px;background:#3a1a1a;color:#ff6b6b;border:1px solid #f44336;
                border-radius:3px;padding:1px 5px;letter-spacing:.3px;white-space:nowrap">&#x26A0; 0 linked</span>`;
        } else {
          const names = linkedRows.map(x => x.material_name).join(', ');
          linkedBadge = ` <span title="${escHtml(names)}"
              style="font-size:9px;background:#0a1f15;color:#3d9970;border:1px solid #2d7a57;
                border-radius:3px;padding:1px 5px;letter-spacing:.3px;white-space:nowrap">&#x1F517; ${linkedRows.length}</span>`;
        }
      }
      const skinBadge = it.skin_formula_id
        ? ` <span title="Price from skin formula: ${escHtml(it.skin_formula_name||'')}"
              style="font-size:9px;background:#0d2140;color:#58a6ff;border:1px solid #388bfd;
                border-radius:3px;padding:1px 5px;letter-spacing:.3px;white-space:nowrap">◎ SKIN</span>` : '';
      const tapingBadge = it.taping_block_id
        ? ` <span title="Price from taping block: ${escHtml(it.taping_block_name||'')}"
              style="font-size:9px;background:#1a1200;color:#f0a500;border:1px solid #b07800;
                border-radius:3px;padding:1px 5px;letter-spacing:.3px;white-space:nowrap">⊡ TAPING</span>` : '';
      const floorBadge = it.floor_plate_id
        ? ` <span title="Price from floor plate: ${escHtml(it.floor_plate_name||'')}"
              style="font-size:9px;background:#0a1f15;color:#3d9970;border:1px solid #2d7a57;
                border-radius:3px;padding:1px 5px;letter-spacing:.3px;white-space:nowrap">⊞ FLOOR</span>` : '';
      const cleatBadge = it.mounting_cleat_id
        ? ` <span title="Price from mounting cleat: ${escHtml(it.mounting_cleat_name||'')}"
              style="font-size:9px;background:#0a1825;color:#4a90d9;border:1px solid #2a6db5;
                border-radius:3px;padding:1px 5px;letter-spacing:.3px;white-space:nowrap">⊟ CLEAT</span>` : '';
      // Pill driven by the most recent formula-scan output for rows the user
      // still needs to act on. Three flavours:
      //   • set         orange  — clean suggestion, FK currently null
      //   • overwrite   red     — existing FK mismatches the suggestion
      //   • unknown_ref purple  — chain touches FORMULAS 2018 but the cell
      //                           isn't auto-mappable (e.g. col-N alt-price);
      //                           manual link required on this row
      let pendingBadge = '';
      const pending = _pendingFormulaLinks[String(it.id)];
      if (pending) {
        const fkMap = {
          'skin_formulas':   it.skin_formula_id,
          'taping_blocks':   it.taping_block_id,
          'floor_plates':    it.floor_plate_id,
          'mounting_cleats': it.mounting_cleat_id,
        };
        // Hide the pill once the relevant FK gets set — but only when the
        // scan actually pointed at a specific table. unknown_ref has no
        // target table, so the pill stays until the row is reviewed.
        const currentFk = pending.target_table ? fkMap[pending.target_table] : null;
        const stillNeedsAction = pending.status === 'unknown_ref'
          ? !(it.skin_formula_id || it.taping_block_id || it.floor_plate_id || it.mounting_cleat_id)
          : !currentFk;
        if (stillNeedsAction) {
          const tableTag = ({skin_formulas:'SKIN', taping_blocks:'TAPING',
                             floor_plates:'FLOOR', mounting_cleats:'CLEAT'})[pending.target_table] || '?';
          const ref = (pending.ref_sheet || pending.ref_cell)
            ? `${pending.ref_sheet||''}!${pending.ref_cell||''}` : '';
          if (pending.status === 'unknown_ref') {
            const tip = `Price-formula item — manual review needed. Excel chain: ${ref}.\n` +
                        `The scan can't auto-map this cell (e.g. alternate-price column N/P/I). ` +
                        `Open this row and link it to the right skin/taping/floor/cleat by hand.`;
            pendingBadge = ` <span title="${escHtml(tip)}"
                style="font-size:9px;background:#1f1530;color:#a371f7;border:1px solid #6b3fb5;
                  border-radius:3px;padding:1px 5px;letter-spacing:.3px;white-space:nowrap">⚠ REVIEW</span>`;
          } else if (pending.status === 'overwrite') {
            const tip = `Mismatch — scan suggests ${pending.target_option_name||''} (${tableTag.toLowerCase()}). Currently linked to a different option.`;
            pendingBadge = ` <span title="${escHtml(tip)}"
                style="font-size:9px;background:#3a1010;color:#ff6b6b;border:1px solid #b03030;
                  border-radius:3px;padding:1px 5px;letter-spacing:.3px;white-space:nowrap">⚠ ${tableTag} mismatch</span>`;
          } else {
            const tip = `Pending link: ${pending.target_option_name||''} (${tableTag.toLowerCase()})`;
            pendingBadge = ` <span title="${escHtml(tip)}"
                style="font-size:9px;background:#3a2400;color:#f0a500;border:1px solid #b07800;
                  border-radius:3px;padding:1px 5px;letter-spacing:.3px;white-space:nowrap">⚠ ${tableTag} pending</span>`;
          }
        }
      }
      const rowBg = it.taping_block_id ? ';background:rgba(240,165,0,.04)'
                  : it.floor_plate_id  ? ';background:rgba(61,153,112,.04)'
                  : it.mounting_cleat_id ? ';background:rgba(74,144,217,.04)' : '';
      const rowClasses = [
        it.skin_formula_id   ? 'bom-skin-row'   : '',
        it.taping_block_id   ? 'bom-taping-row' : '',
        it.floor_plate_id    ? 'bom-floor-row'  : '',
        it.mounting_cleat_id ? 'bom-cleat-row'  : '',
      ].filter(Boolean).join(' ');
      const skinData = (it.skin_formula_id && it.skin_formula_items)
        ? ` data-skin-name="${escHtml(it.skin_formula_name||'')}" data-skin-region="${escHtml(it.skin_formula_region||'standard')}" data-skin-items='${JSON.stringify(it.skin_formula_items).replace(/'/g,"&#39;")}'` : '';
      const tapingData = it.taping_block_id ? ` data-taping-id="${it.taping_block_id}"` : '';
      const floorData  = it.floor_plate_id  ? ` data-floor-id="${it.floor_plate_id}"`   : '';
      const cleatData  = it.mounting_cleat_id ? ` data-cleat-id="${it.mounting_cleat_id}"` : '';
      html += `<tr class="${rowClasses}" style="border-bottom:1px solid rgba(48,54,61,.5)${rowBg}"${skinData}${tapingData}${floorData}${cleatData}
        oncontextmenu="return _bomRowContextMenu(event, ${it.id})"
        title="Right-click to edit">
        <td style="padding:8px 12px">
          <input type="checkbox" class="bom-cb" data-id="${it.id}"
            onchange="toggleBOMItem(${it.id}, this.checked)" style="cursor:pointer">
        </td>
        <td style="padding:8px 12px">
          ${escHtml(it.material_name)}
          ${subgroupBadge}${linkedBadge}${skinBadge}${tapingBadge}${floorBadge}${cleatBadge}${pendingBadge}
        </td>
        <td style="padding:8px 12px"><span style="font-size:10px;color:var(--text-dim)">${escHtml(it.unit)}</span></td>
        <td style="padding:8px 12px">
          <code style="font-size:11px;background:var(--bg-input);padding:2px 6px;
            border-radius:3px">${escHtml(it.formula)}</code>
        </td>
        <td style="padding:8px 12px;text-align:center;color:var(--text-dim);font-size:12px">
          ${it.waste_pct || 0}%
        </td>
        <td style="padding:8px 12px;text-align:right;font-family:var(--font-mono);font-size:12px"
            title="${it.is_body_option ? 'Body variable — not a price. Reference in formulas as {' + escHtml(it.material_name) + '}' : ''}">
          ${it.is_body_option
            ? `<span style="color:#58a6ff">${it.variable_value != null ? Number(it.variable_value).toFixed(3) : '—'} m</span>`
            : `R ${Number(it.price).toFixed(2)}`}
        </td>
        <td style="padding:8px 12px;white-space:nowrap;display:flex;gap:4px">
          <button class="btn btn-outline btn-sm" onclick="openEditBOM(${it.id})" title="Edit">Edit</button>
          <button class="btn btn-outline btn-sm" onclick="duplicateBOMItem(${it.id})"
            title="Duplicate this item" style="padding:3px 7px;font-size:13px">⧉</button>
          ${_isCrossBodyCopyName(it.material_name) ? `
          <button class="btn btn-outline btn-sm" onclick="openCopyBOMToTrailer(${it.id})"
            title="Copy to another body type" style="padding:3px 7px;font-size:13px">⧉→</button>
          ` : ''}
        </td>
      </tr>`;
    });
  }
  html += '</tbody></table>';
  wrap.innerHTML = html;
  // Section "exclude from Calc 2" checkboxes — apply the partial (indeterminate)
  // state, since HTML has no attribute for it.
  wrap.querySelectorAll('.sec-calc2-tick[data-indeterminate="1"]').forEach(cb => { cb.indeterminate = true; });

  // Keep Collapse All / Expand All label in sync
  const collapseBtn = document.getElementById('btn-collapse-all');
  if (collapseBtn) {
    const allCollapsed = Object.keys(groups).every(c => collapsedSections.has(c));
    collapseBtn.textContent = allCollapsed ? 'Expand All' : 'Collapse All';
  }

  _saveBomCollapseState();
}

// ── Material picker for BOM ────────────────────────────
function filterBomMats() {
  const catId = +document.getElementById('bom-cat-filter').value || null;
  const q = document.getElementById('bom-mat-search').value.toLowerCase().trim();
  filteredMats = allMats.filter(m => {
    if (catId && m.category_id !== catId) return false;
    if (q && !m.name.toLowerCase().includes(q) &&
        !(m.sap_code||'').toLowerCase().includes(q)) return false;
    return true;
  });
  renderBomMatSelect(filteredMats);
}

function renderBomMatSelect(mats) {
  const sel = document.getElementById('bom-mat-select');
  sel.innerHTML = mats.map(m =>
    `<option value="${m.id}">${escHtml(m.name)} [${escHtml(m.category)}] — R ${Number(m.price).toFixed(2)} / ${m.unit}</option>`
  ).join('');
  updateSelectedInfo();
}

function onMatSelected() { updateSelectedInfo(); }

function updateSelectedInfo() {
  const sel = document.getElementById('bom-mat-select');
  const info = document.getElementById('selected-mat-info');
  if (!sel.value) { info.textContent = ''; return; }
  const m = allMats.find(x => x.id === +sel.value);
  if (m) info.textContent = `${m.category}  ·  ${m.unit}  ·  R ${Number(m.price).toFixed(2)}  ·  ${m.sap_code||''}`;
}

function openAddBOM() {
  if (!currentTTId) { toast('Select a trailer type first', 'error'); return; }
  document.getElementById('bom-formula').value = '1';
  document.getElementById('bom-waste').value = '0';
  document.getElementById('bom-notes').value = '';
  document.getElementById('bom-section').value = '';
  document.getElementById('bom-mat-search').value = '';
  document.getElementById('bom-cat-filter').value = '';
  filterBomMats();
  openModal('modal-add-bom');
}

async function addBOMItem() {
  const sel = document.getElementById('bom-mat-select');
  if (!sel.value) { toast('Select a material first', 'error'); return; }
  const body = {
    material_id: +sel.value,
    formula_expression: document.getElementById('bom-formula').value.trim() || '1',
    waste_percentage: +document.getElementById('bom-waste').value || 0,
    notes: document.getElementById('bom-notes').value.trim(),
    bom_section: document.getElementById('bom-section').value,
  };
  try {
    await api('POST', `/api/trailers/${currentTTId}/bom`, body);
    closeModal('modal-add-bom');
    toast('Item added to BOM', 'success');
    loadBOM(currentTTId);
  } catch(e) { toast(e.message, 'error'); }
}

// ── Edit existing BOM item ─────────────────────────────
let bomMap = {};

// Set by openEditBOM — whether the row currently in the modal is a body-option
// master. Body-option status is defined in the Body Configurator, not here;
// this is read only to gate the variable_value field on save.
let _editBomIsOption = false;

// ── Skin formula helpers ───────────────────────────────
let _skinFormulas = [];

async function _ensureSkinFormulas() {
  if (_skinFormulas.length) return;
  _skinFormulas = await api('GET', '/api/skin-formulas');
  const sel = document.getElementById('edit-bom-skin-formula-id');
  const sorted = [..._skinFormulas].sort(
    (a, b) => a.name.localeCompare(b.name, undefined, {sensitivity: 'base'}));
  sel.innerHTML = '<option value="">— select a skin formula —</option>' +
    sorted.map(f =>
      `<option value="${f.id}">${escHtml(f.name)}</option>`
    ).join('');
}

function onSkinFormulaToggle(on) {
  document.getElementById('edit-bom-skin-fields').style.display = on ? '' : 'none';
  if (on) {
    _ensureSkinFormulas().then(onSkinFormulaChange);
    // Turning on skin formula turns off other computed types
    document.getElementById('edit-bom-taping-toggle').checked = false;
    onTapingBlockToggle(false);
    document.getElementById('edit-bom-floor-toggle').checked = false;
    onFloorPlateToggle(false);
    document.getElementById('edit-bom-cleat-toggle').checked = false;
    onMountingCleatToggle(false);
  } else {
    document.getElementById('edit-bom-skin-cost').textContent = '';
  }
}

function onSkinFormulaChange() {
  const fid    = parseInt(document.getElementById('edit-bom-skin-formula-id').value) || 0;
  const region = document.getElementById('edit-bom-skin-region').value;
  const f      = _skinFormulas.find(x => x.id === fid);
  const el     = document.getElementById('edit-bom-skin-cost');
  if (f) {
    const cost = region === 'sap'
      ? (f.cost_sap || 0)
      : region === 'kzn'
        ? f.cost_kzn
        : f.cost_standard;
    const label = region === 'sap' ? 'SAP' : region === 'kzn' ? 'KZN' : 'Standard';
    el.textContent = `Cost per m²: R ${cost.toFixed(4)} (${label})`;
  } else {
    el.textContent = '';
  }
}

// ── Taping block helpers ───────────────────────────────
let _tapingBlocks = [];

async function _ensureTapingBlocks() {
  if (_tapingBlocks.length) return;
  _tapingBlocks = await api('GET', '/api/taping-blocks');
  const sel = document.getElementById('edit-bom-taping-block-id');
  const sorted = [..._tapingBlocks].sort(
    (a, b) => a.name.localeCompare(b.name, undefined, {sensitivity: 'base'}));
  sel.innerHTML = '<option value="">— select a taping block —</option>' +
    sorted.map(b =>
      `<option value="${b.id}">${escHtml(b.name)}</option>`
    ).join('');
}

function onTapingBlockToggle(on) {
  document.getElementById('edit-bom-taping-fields').style.display = on ? '' : 'none';
  if (on) {
    _ensureTapingBlocks().then(onTapingBlockChange);
    // Turning on taping block turns off other computed types
    document.getElementById('edit-bom-skin-toggle').checked = false;
    onSkinFormulaToggle(false);
    document.getElementById('edit-bom-floor-toggle').checked = false;
    onFloorPlateToggle(false);
    document.getElementById('edit-bom-cleat-toggle').checked = false;
    onMountingCleatToggle(false);
  } else {
    document.getElementById('edit-bom-taping-cost').textContent = '';
  }
}

function onTapingBlockChange() {
  const bid = parseInt(document.getElementById('edit-bom-taping-block-id').value) || 0;
  const b   = _tapingBlocks.find(x => x.id === bid);
  const el  = document.getElementById('edit-bom-taping-cost');
  el.textContent = b ? `Cost per block: R ${b.cost.toFixed(4)}` : '';
}

// ── Floor plate helpers ────────────────────────────────
let _floorPlates = [];

async function _ensureFloorPlates() {
  if (_floorPlates.length) return;
  _floorPlates = await api('GET', '/api/floor-plates');
  const sel = document.getElementById('edit-bom-floor-plate-id');
  // Group by substring so names with prefixes like "58MM PLYBEAM …" still
  // land in the Plybeam group. Will be replaced by an explicit
  // floor_plates.group column once the admin Floor Plates page gains a
  // group selector (TODO: see "+ Add Assembly" workflow).
  // Alphabetic within each group (case-insensitive, locale-aware).
  const byName = (a, b) => a.name.localeCompare(b.name, undefined, {sensitivity: 'base'});
  const plybeam    = _floorPlates.filter(p =>  p.name.toUpperCase().includes('PLYBEAM')).sort(byName);
  const structural = _floorPlates.filter(p => !p.name.toUpperCase().includes('PLYBEAM')).sort(byName);
  // Mirror the admin Floor Plates page: when a price formula is active
  // and the post-formula price differs from the raw assembly cost, show
  // both. The "ƒ" marker matches the admin page so users get the same
  // visual cue ('formula applied') in either context.
  const fmtOpt = (p) => {
    const post = p.cost.toFixed(2);
    if (p.price_formula && Math.abs(p.cost - p.raw_cost) > 0.01) {
      return `${p.name} — R ${post}  (raw R ${p.raw_cost.toFixed(2)} ƒ)`;
    }
    return `${p.name} — R ${post}`;
  };
  const toOpts = arr => arr.map(p => `<option value="${p.id}">${escHtml(fmtOpt(p))}</option>`).join('');
  sel.innerHTML =
    '<option value="">— select a floor plate —</option>' +
    (structural.length ? `<optgroup label="Structural Plate / Hardware">${toOpts(structural)}</optgroup>` : '') +
    (plybeam.length    ? `<optgroup label="Plybeam Picture Frame">${toOpts(plybeam)}</optgroup>`         : '');
}

function onFloorPlateToggle(on) {
  document.getElementById('edit-bom-floor-fields').style.display = on ? '' : 'none';
  if (on) {
    _ensureFloorPlates().then(onFloorPlateChange);
    // Turning on floor plate turns off the other computed types
    document.getElementById('edit-bom-skin-toggle').checked = false;
    onSkinFormulaToggle(false);
    document.getElementById('edit-bom-taping-toggle').checked = false;
    onTapingBlockToggle(false);
    document.getElementById('edit-bom-cleat-toggle').checked = false;
    onMountingCleatToggle(false);
  } else {
    document.getElementById('edit-bom-floor-cost').textContent = '';
  }
}

function onFloorPlateChange() {
  const pid = parseInt(document.getElementById('edit-bom-floor-plate-id').value) || 0;
  const p   = _floorPlates.find(x => x.id === pid);
  const el  = document.getElementById('edit-bom-floor-cost');
  if (!p) { el.textContent = ''; return; }
  if (p.price_formula && Math.abs(p.cost - p.raw_cost) > 0.01) {
    el.innerHTML = `Assembly cost: <b>R ${p.cost.toFixed(4)}</b>` +
      ` <span style="color:var(--text-dim);font-size:11px">` +
      `(raw R ${p.raw_cost.toFixed(2)} · formula applied ƒ)</span>`;
  } else {
    el.textContent = `Assembly cost: R ${p.cost.toFixed(4)}`;
  }
}

// ── Mounting cleat helpers ─────────────────────────────
let _mountingCleats = [];
const _CLEAT_GROUPS = ['MOUNTING CLEATS', 'FISH PLATES', 'MOUNTING BRACKETS'];

async function _ensureMountingCleats() {
  if (_mountingCleats.length) return;
  _mountingCleats = await api('GET', '/api/mounting-cleats');
  const sel = document.getElementById('edit-bom-mounting-cleat-id');
  const byName = (a, b) => a.name.localeCompare(b.name, undefined, {sensitivity: 'base'});
  const toOpts = arr => arr.map(c => `<option value="${c.id}">${escHtml(c.name)} — R ${c.cost.toFixed(2)}</option>`).join('');
  let html = '<option value="">— select a mounting cleat —</option>';
  _CLEAT_GROUPS.forEach(grp => {
    const items = _mountingCleats.filter(c => c.group === grp).sort(byName);
    if (items.length) html += `<optgroup label="${escHtml(grp)}">${toOpts(items)}</optgroup>`;
  });
  sel.innerHTML = html;
}

function onMountingCleatToggle(on) {
  document.getElementById('edit-bom-cleat-fields').style.display = on ? '' : 'none';
  if (on) {
    _ensureMountingCleats().then(onMountingCleatChange);
    // Turning on mounting cleat turns off the other computed types
    document.getElementById('edit-bom-skin-toggle').checked = false;
    onSkinFormulaToggle(false);
    document.getElementById('edit-bom-taping-toggle').checked = false;
    onTapingBlockToggle(false);
    document.getElementById('edit-bom-floor-toggle').checked = false;
    onFloorPlateToggle(false);
  } else {
    document.getElementById('edit-bom-cleat-cost').textContent = '';
  }
}

function onMountingCleatChange() {
  const cid = parseInt(document.getElementById('edit-bom-mounting-cleat-id').value) || 0;
  const c   = _mountingCleats.find(x => x.id === cid);
  const el  = document.getElementById('edit-bom-cleat-cost');
  el.textContent = c ? `Assembly cost: R ${c.cost.toFixed(4)}` : '';
}

function _applyVariableModalMode(isBodyOpt, variableValue, materialName) {
  // When editing a Body Variable row, hide all the formula/skin/taping/floor/cleat
  // fields (they're irrelevant) and show an editable value input instead.
  const hide = document.querySelectorAll('#modal-edit-bom .js-hide-for-variable');
  const show = document.querySelectorAll('#modal-edit-bom .js-show-for-variable');
  hide.forEach(el => el.style.display = isBodyOpt ? 'none' : '');
  show.forEach(el => el.style.display = isBodyOpt ? '' : 'none');
  if (isBodyOpt) {
    const inp = document.getElementById('edit-bom-variable-value-input');
    if (inp) inp.value = variableValue != null ? Number(variableValue).toFixed(3) : '';
    const tok = document.getElementById('edit-bom-variable-token-display');
    if (tok) tok.textContent = '{' + (materialName || 'NAME') + '}';
  }
}

function _renderBodyVariableChips() {
  const wrap = document.getElementById('edit-bom-var-chips');
  const list = document.getElementById('edit-bom-var-chips-list');
  if (!wrap || !list) return;
  const vars = (_cachedBOM || []).filter(b => b.is_body_option && b.variable_value != null);
  if (!vars.length) { wrap.style.display = 'none'; return; }
  wrap.style.display = 'block';
  list.innerHTML = vars.map(v => {
    const tok = `{${v.material_name}}`;
    const safeTok = tok.replace(/'/g, "\\'");
    return `<button type="button" class="btn btn-outline btn-sm"
      onclick='insertVariableToken(${JSON.stringify(safeTok)},${Number(v.variable_value)})'
      title="Insert ${escHtml(tok)} = ${Number(v.variable_value).toFixed(3)} m"
      style="font-family:var(--font-mono);font-size:10px;padding:2px 8px;border-color:#388bfd;color:#58a6ff">
      ${escHtml(tok)} <span style="opacity:.6;margin-left:3px">${Number(v.variable_value).toFixed(3)}</span>
    </button>`;
  }).join('');
}

function insertVariableToken(token, value) {
  const inp = document.getElementById('edit-bom-formula');
  if (!inp) return;
  const start = inp.selectionStart, end = inp.selectionEnd;
  const v = inp.value;
  inp.value = v.slice(0, start) + token + v.slice(end);
  // Cursor after inserted token
  const pos = start + token.length;
  inp.setSelectionRange(pos, pos);
  inp.focus();
}

async function openEditBOM(id, opts = {}) {
  // Use cached BOM if available, otherwise fetch
  try {
    const bom = _cachedBOM.length ? _cachedBOM : await api('GET', `/api/trailers/${currentTTId}/bom`);
    const it = bom.find(x => x.id === id);
    if (!it) { toast('Item not found', 'error'); return; }
    document.getElementById('edit-bom-id').value = it.id;
    document.getElementById('edit-bom-mat-id').value = it.material_id;
    document.getElementById('edit-bom-title').textContent = opts.title || ('Edit: ' + it.material_name);
    const nameInp = document.getElementById('edit-bom-mat-name-input');
    nameInp.value = it.material_name;
    nameInp.dataset.original = it.material_name;
    document.getElementById('edit-bom-mat-info').textContent =
      `${it.unit}  ·  R ${Number(it.price).toFixed(2)}  ·  ${it.bom_section || it.category || ''}`;
    document.getElementById('edit-bom-section').value = it.bom_section || it.category || '';
    // Populate "Replace with" dropdown from same category, excluding current material
    const currentMat = allMats.find(m => m.id === it.material_id);
    const replaceSel = document.getElementById('edit-bom-replace-select');
    replaceSel.innerHTML = '<option value="">— keep current —</option>' +
      (currentMat ? allMats
        .filter(m => m.category_id === currentMat.category_id && m.id !== it.material_id)
        .sort((a, b) => a.name.localeCompare(b.name))
        .map(m => `<option value="${m.id}">${escHtml(m.name)}  ·  R ${Number(m.price).toFixed(2)}</option>`)
        .join('') : '');
    document.getElementById('edit-bom-formula').value = it.formula;
    document.getElementById('edit-bom-waste').value = it.waste_pct;
    document.getElementById('edit-bom-notes').value = it.notes || '';
    document.getElementById('edit-bom-calc2-excluded').checked = !!it.calc2_default_excluded;
    _renderBodyVariableChips();
    _applyVariableModalMode(!!it.is_body_option, it.variable_value, it.material_name);
    // Body-option rows: show the read-only "Linked items" panel.
    const isOpt  = !!it.is_body_option;
    _editBomIsOption = isOpt;
    document.getElementById('edit-bom-opt-fields').style.display = isOpt ? '' : 'none';
    if (isOpt) {
      // "Linked items" panel — read-only list of BOM rows still wired to this
      // option via the legacy body_option_linked field. Inclusion rules for
      // new work are managed in the Body Configurator, not here.
      const linkedList = document.getElementById('edit-bom-linked-from-list');
      if (linkedList) {
        const linkedRows = (_cachedBOM || []).filter(x => !x.is_body_option && x.body_option_linked === it.material_name);
        if (linkedRows.length === 0) {
          linkedList.innerHTML = `<span style="color:var(--text-dim)">No BOM rows are linked to this option. Inclusion rules are now managed in the Body Configurator.</span>`;
        } else {
          linkedList.innerHTML = linkedRows.map(r =>
            `<div style="padding:2px 0">
               <a href="javascript:void(0)" onclick="closeModal('modal-edit-bom');setTimeout(()=>openEditBOM(${r.id}),100)"
                  style="color:#3d9970;text-decoration:none;border-bottom:1px dotted #3d9970">${escHtml(r.material_name)}</a>
               <span style="color:var(--text-dim);margin-left:6px">— ${escHtml(r.category||'')}</span>
             </div>`
          ).join('');
        }
      }
    }
    // Skin formula
    const hasSkin = !!it.skin_formula_id;
    document.getElementById('edit-bom-skin-toggle').checked = hasSkin;
    document.getElementById('edit-bom-skin-fields').style.display = hasSkin ? '' : 'none';
    if (hasSkin) {
      await _ensureSkinFormulas();
      document.getElementById('edit-bom-skin-formula-id').value = it.skin_formula_id || '';
      document.getElementById('edit-bom-skin-region').value = it.skin_formula_region || 'standard';
      onSkinFormulaChange();
    } else {
      document.getElementById('edit-bom-skin-formula-id').value = '';
      document.getElementById('edit-bom-skin-region').value = 'standard';
      document.getElementById('edit-bom-skin-cost').textContent = '';
    }
    // Taping block
    const hasTaping = !!it.taping_block_id;
    document.getElementById('edit-bom-taping-toggle').checked = hasTaping;
    document.getElementById('edit-bom-taping-fields').style.display = hasTaping ? '' : 'none';
    if (hasTaping) {
      await _ensureTapingBlocks();
      document.getElementById('edit-bom-taping-block-id').value = it.taping_block_id || '';
      onTapingBlockChange();
    } else {
      document.getElementById('edit-bom-taping-block-id').value = '';
      document.getElementById('edit-bom-taping-cost').textContent = '';
    }
    // Floor plate
    const hasFloor = !!it.floor_plate_id;
    document.getElementById('edit-bom-floor-toggle').checked = hasFloor;
    document.getElementById('edit-bom-floor-fields').style.display = hasFloor ? '' : 'none';
    if (hasFloor) {
      await _ensureFloorPlates();
      document.getElementById('edit-bom-floor-plate-id').value = it.floor_plate_id || '';
      onFloorPlateChange();
    } else {
      document.getElementById('edit-bom-floor-plate-id').value = '';
      document.getElementById('edit-bom-floor-cost').textContent = '';
    }
    // Mounting cleat
    const hasCleat = !!it.mounting_cleat_id;
    document.getElementById('edit-bom-cleat-toggle').checked = hasCleat;
    document.getElementById('edit-bom-cleat-fields').style.display = hasCleat ? '' : 'none';
    if (hasCleat) {
      await _ensureMountingCleats();
      document.getElementById('edit-bom-mounting-cleat-id').value = it.mounting_cleat_id || '';
      onMountingCleatChange();
    } else {
      document.getElementById('edit-bom-mounting-cleat-id').value = '';
      document.getElementById('edit-bom-cleat-cost').textContent = '';
    }
    openModal('modal-edit-bom');
    if (opts.focusName) setTimeout(() => { nameInp.focus(); nameInp.select(); }, 100);
  } catch(e) { toast(e.message, 'error'); }
}

async function saveBOMItem() {
  const id    = document.getElementById('edit-bom-id').value;
  const matId = document.getElementById('edit-bom-mat-id').value;
  const nameInp = document.getElementById('edit-bom-mat-name-input');
  const newName = nameInp.value.trim();
  if (!newName) { toast('Material name cannot be empty', 'error'); return; }
  const body = {
    formula_expression: document.getElementById('edit-bom-formula').value.trim(),
    waste_percentage: +document.getElementById('edit-bom-waste').value || 0,
    notes: document.getElementById('edit-bom-notes').value.trim(),
    bom_section: document.getElementById('edit-bom-section').value,
    calc2_default_excluded: document.getElementById('edit-bom-calc2-excluded').checked,
  };
  // is_body_option / body_option_group are defined in the Body Configurator,
  // not here — they are deliberately NOT sent (PUT /api/bom preserves any
  // field omitted from the payload). variable_value still applies to
  // body-option (Body Variable) rows, so it is gated on the row's status.
  if (_editBomIsOption) {
    const vRaw = document.getElementById('edit-bom-variable-value-input').value;
    body.variable_value = vRaw === '' ? null : (parseFloat(vRaw) || 0);
  }
  const skinOn = document.getElementById('edit-bom-skin-toggle').checked;
  body.skin_formula_id     = skinOn ? (parseInt(document.getElementById('edit-bom-skin-formula-id').value) || null) : null;
  body.skin_formula_region = skinOn ? document.getElementById('edit-bom-skin-region').value : 'standard';
  const tapingOn = document.getElementById('edit-bom-taping-toggle').checked;
  body.taping_block_id     = tapingOn ? (parseInt(document.getElementById('edit-bom-taping-block-id').value) || null) : null;
  const floorOn = document.getElementById('edit-bom-floor-toggle').checked;
  body.floor_plate_id      = floorOn ? (parseInt(document.getElementById('edit-bom-floor-plate-id').value) || null) : null;
  const cleatOn = document.getElementById('edit-bom-cleat-toggle').checked;
  body.mounting_cleat_id   = cleatOn ? (parseInt(document.getElementById('edit-bom-mounting-cleat-id').value) || null) : null;
  const replaceMat = document.getElementById('edit-bom-replace-select').value;
  if (replaceMat) {
    body.material_id = +replaceMat;
  }
  try {
    // Save name if it changed (only when NOT replacing — replacing swaps the underlying material)
    if (!replaceMat && matId && newName !== nameInp.dataset.original) {
      await api('PUT', `/api/materials/${matId}`, { name: newName });
    }
    await api('PUT', `/api/bom/${id}`, body);
    closeModal('modal-edit-bom');
    toast('Updated', 'success');
    loadBOM(currentTTId);
  } catch(e) { toast(e.message, 'error'); }
}

function onBomReplaceSelect(sel) {
  const matId = sel.value;
  if (!matId) return;
  const m = allMats.find(x => x.id === +matId);
  if (!m) return;
  document.getElementById('edit-bom-mat-id').value = m.id;
  document.getElementById('edit-bom-mat-name-input').value = m.name;
  document.getElementById('edit-bom-mat-info').textContent =
    `${m.unit_of_measure || ''}  ·  R ${Number(m.price_per_unit || 0).toFixed(2)}  ·  ${m.category || ''}`;
}

async function deleteBOMItem() {
  const id = document.getElementById('edit-bom-id').value;
  if (!await confirmModal('Remove this item from the BOM?', { title: 'Remove item', okText: 'Remove', danger: true })) return;
  try {
    await api('DELETE', `/api/bom/${id}`);
    closeModal('modal-edit-bom');
    toast('Removed', 'success');
    loadBOM(currentTTId);
  } catch(e) { toast(e.message, 'error'); }
}

// ── Cross-body-type copy (restricted to a fixed list of materials) ──
const CROSS_BODY_COPY_NAMES = [
  'ALU EXTRUTION FLOOR',
  'RICE GRAIN ALU FLOOR',
  '1ST ROW ALU KICK PLATE',
  '2ND ROW ALU KICK PLATE',
];
function _isCrossBodyCopyName(name) {
  return CROSS_BODY_COPY_NAMES.includes((name || '').trim().toUpperCase());
}

let _copyBomSourceClickedId = null;

function openCopyBOMToTrailer(bomId) {
  _copyBomSourceClickedId = bomId;
  const clicked = (_cachedBOM || []).find(it => it.id === bomId);
  if (!clicked) { toast('Item not found', 'error'); return; }

  const eligible = (_cachedBOM || []).filter(it => _isCrossBodyCopyName(it.material_name));
  const list = document.getElementById('copy-bom-items-list');
  list.innerHTML = eligible.map(it => `
    <label style="display:flex;align-items:center;gap:8px;font-size:12px;cursor:pointer">
      <input type="checkbox" class="copy-bom-cb" data-bom-id="${it.id}"
        data-name="${escHtml((it.material_name||'').toUpperCase())}"
        ${it.id === bomId ? 'checked' : ''}>
      <span>${escHtml(it.material_name)}</span>
      <span class="copy-bom-conflict" data-name="${escHtml((it.material_name||'').toUpperCase())}"
        style="color:var(--red,#f85149);font-size:11px;margin-left:auto;display:none">already in target</span>
    </label>
  `).join('') || '<div style="font-size:12px;color:var(--text-dim)">No eligible items in this body type.</div>';

  const sel = document.getElementById('copy-bom-target');
  const others = Object.values(trailerMap)
    .filter(t => t.id !== currentTTId)
    .sort((a, b) => (a.name || '').localeCompare(b.name || ''));
  sel.innerHTML = '<option value="">— select a body type —</option>' +
    others.map(t => `<option value="${t.id}">${escHtml(t.name)}</option>`).join('');
  document.getElementById('copy-bom-target-hint').textContent = '';

  openModal('modal-copy-bom-to-trailer');
}

async function onCopyBOMTargetChanged() {
  const sel = document.getElementById('copy-bom-target');
  const hint = document.getElementById('copy-bom-target-hint');
  document.querySelectorAll('.copy-bom-conflict').forEach(el => el.style.display = 'none');
  document.querySelectorAll('.copy-bom-cb').forEach(cb => { cb.disabled = false; });
  if (!sel.value) { hint.textContent = ''; return; }
  hint.textContent = 'Checking target body type…';
  try {
    const targetBom = await api('GET', `/api/trailers/${sel.value}/bom`);
    const present = new Set(targetBom.map(it => (it.material_name || '').trim().toUpperCase()));
    let conflicts = 0;
    document.querySelectorAll('.copy-bom-cb').forEach(cb => {
      const name = cb.getAttribute('data-name');
      if (present.has(name)) {
        cb.checked = false;
        cb.disabled = true;
        conflicts++;
        const tag = document.querySelector(`.copy-bom-conflict[data-name="${name}"]`);
        if (tag) tag.style.display = '';
      }
    });
    hint.textContent = conflicts
      ? `${conflicts} item${conflicts === 1 ? '' : 's'} already exist${conflicts === 1 ? 's' : ''} in target — unchecked.`
      : 'No conflicts.';
  } catch (e) {
    hint.textContent = 'Could not load target BOM: ' + e.message;
  }
}

async function confirmCopyBOMToTrailer() {
  const targetId = +document.getElementById('copy-bom-target').value;
  if (!targetId) { toast('Pick a target body type', 'error'); return; }
  const ids = [...document.querySelectorAll('.copy-bom-cb')]
    .filter(cb => cb.checked && !cb.disabled)
    .map(cb => +cb.getAttribute('data-bom-id'));
  if (!ids.length) { toast('Select at least one item', 'error'); return; }

  const btn = document.getElementById('copy-bom-confirm-btn');
  btn.disabled = true;
  const originalText = btn.textContent;
  btn.textContent = 'Copying…';
  let ok = 0, fail = 0, lastErr = '';
  for (const bomId of ids) {
    try {
      await api('POST', `/api/bom/${bomId}/copy-to-trailer`, { target_tt_id: targetId });
      ok++;
    } catch (e) { fail++; lastErr = e.message; }
  }
  btn.disabled = false;
  btn.textContent = originalText;
  closeModal('modal-copy-bom-to-trailer');
  if (ok && !fail) toast(`Copied ${ok} item${ok === 1 ? '' : 's'}`, 'success');
  else if (ok && fail) toast(`Copied ${ok}, ${fail} failed: ${lastErr}`, 'error');
  else toast(`Copy failed: ${lastErr}`, 'error');
}

async function duplicateBOMItem(bomId) {
  try {
    const res = await api('POST', `/api/bom/${bomId}/duplicate`);
    toast(`Duplicated as "${res.material_name}" — rename and save`, 'success');
    // Reload BOM so _cachedBOM has the new item
    _cachedBOM = await api('GET', `/api/trailers/${currentTTId}/bom`);
    renderBOM(_cachedBOM);
    // Open edit modal for the copy, focused on the name field
    openEditBOM(res.bom_id, { title: 'Edit Copy: ' + res.material_name, focusName: true });
  } catch(e) { toast(e.message, 'error'); }
}

// ── Trailer type management ────────────────────────────
async function addTrailerType() {
  const body = {
    name: document.getElementById('new-tt-name').value.trim(),
    description: document.getElementById('new-tt-desc').value.trim(),
  };
  if (!body.name) { toast('Name required', 'error'); return; }
  try {
    await api('POST', '/api/trailers', body);
    closeModal('modal-add-trailer');
    toast('Trailer type created', 'success');
    await loadTrailers();
  } catch(e) { toast(e.message, 'error'); }
}

async function renameTrailer() {
  if (!currentTTId) { toast('Select a trailer type first', 'error'); return; }
  const current = trailerMap[currentTTId]?.name || '';
  const name = await promptModal('New name for this trailer type:', current, { title: 'Rename trailer type', okText: 'Rename' });
  if (!name || name.trim() === '' || name.trim() === current) return;
  try {
    await api('PUT', `/api/trailers/${currentTTId}`, { name: name.trim() });
    toast('Renamed', 'success');
    await loadTrailers();
    document.getElementById('bom-title').textContent = name.trim();
  } catch(e) { toast(e.message, 'error'); }
}

async function duplicateTrailer() {
  if (!currentTTId) { toast('Select a trailer type first', 'error'); return; }
  const src = trailerMap[currentTTId];
  const name = await promptModal('Name for the duplicate:', src ? src.name + ' (Copy)' : '', { title: 'Duplicate Body Type' });
  if (!name) return;
  try {
    const res = await api('POST', `/api/trailers/${currentTTId}/duplicate`, { name });
    toast(`Created "${res.name}"`, 'success');
    await loadTrailers();
  } catch(e) { toast(e.message, 'error'); }
}

async function deleteTrailer() {
  if (!currentTTId) { toast('Select a trailer type first', 'error'); return; }
  const title = document.getElementById('bom-title').textContent;
  if (!await confirmModal(`Delete trailer type "${title}" and all its BOM items?`, { title: 'Delete trailer type', okText: 'Delete', danger: true })) return;
  try {
    await api('DELETE', `/api/trailers/${currentTTId}`);
    toast('Deleted', 'success');
    currentTTId = null;
    document.getElementById('bom-title').textContent = 'Select a trailer type';
    document.getElementById('bom-wrap').innerHTML = '';
    ['btn-rename','btn-dup','btn-del','btn-add-bom','btn-bom-sort','btn-collapse-all'].forEach(b =>
      document.getElementById(b).classList.add('hidden'));
    await loadTrailers();
  } catch(e) { toast(e.message, 'error'); }
}

function escHtml(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Init ───────────────────────────────────────────────
// Mark the correct view toggle button as active on load
document.querySelectorAll('.tt-view-btn').forEach(b =>
  b.classList.toggle('active', b.dataset.view === currentTTView));
loadAllMats();
loadTrailers();
loadBOMSections();
document.getElementById('btn-bom-sort')?.classList.toggle('active', bomSorted);

// ── Excel Sheet Importer ────────────────────────────────────────────────────
let _importParsed = null;   // holds the last preview result

function closeImportModal() {
  closeModal('modal-import-sheet');
  showImportStep(1);
  _importParsed = null;
}

function showImportStep(n) {
  document.getElementById('import-step-1').style.display = n === 1 ? '' : 'none';
  document.getElementById('import-step-2').style.display = n === 2 ? '' : 'none';
  document.getElementById('import-action-btn').textContent = n === 1 ? 'Preview' : 'Import Now';
}

async function loadSheetList() {
  const path = document.getElementById('import-excel-path').value.trim();
  if (!path) { toast('Enter an Excel file path first', 'warn'); return; }
  try {
    const data = await api('GET', `/api/import/sheets?path=${encodeURIComponent(path)}`);
    const sel = document.getElementById('import-sheet-name');
    sel.innerHTML = data.sheets.map(s =>
      `<option value="${escHtml(s)}">${escHtml(s)}</option>`).join('');
    toast(`${data.sheets.length} sheets loaded`, 'success');
  } catch(e) { toast('Could not read file: ' + e.message, 'error'); }
}

async function runImportAction() {
  const btn = document.getElementById('import-action-btn');
  if (btn.textContent === 'Preview') {
    await doPreview();
  } else {
    await doImport();
  }
}

async function doPreview() {
  const path  = document.getElementById('import-excel-path').value.trim();
  const sheet = document.getElementById('import-sheet-name').value.trim();
  if (!path || !sheet) { toast('Provide both a file path and a sheet name', 'warn'); return; }

  const btn = document.getElementById('import-action-btn');
  btn.disabled = true; btn.textContent = 'Parsing…';
  try {
    const result = await api('POST', '/api/import/preview', {
      excel_path: path, sheet_name: sheet,
    });
    _importParsed = result;

    // Populate preview pane
    const ttName = document.getElementById('import-tt-name').value.trim() || result.trailer_name;
    document.getElementById('import-preview-title').textContent = ttName;
    const d = result.trailer_defaults || {};
    document.getElementById('import-dims').textContent =
      `L ${d.length ?? '?'} m · W ${d.width ?? '?'} m · H ${d.height ?? '?'} m`;
    const totalItems = result.sections.reduce((s, x) => s + x.items.length, 0);
    document.getElementById('import-sect-count').textContent = result.sections.length;
    document.getElementById('import-item-count').textContent = totalItems;
    document.getElementById('import-skipped').textContent =
      result.skipped_sections.join(', ') || 'none';

    // Build table
    let rows = '';
    result.sections.forEach(sect => {
      const multBadge = sect.multiplier && sect.multiplier !== 1
        ? ` <span style="background:#3a1a1a;color:#ff6b6b;border:1px solid #f44336;
            border-radius:3px;padding:0 4px;font-size:9px;margin-left:4px">× ${sect.multiplier}</span>`
        : '';
      rows += `<tr style="background:var(--bg-panel)">
        <td colspan="4" style="padding:5px 10px;font-family:var(--font-mono);font-size:10px;
          color:var(--blue-hi);letter-spacing:1px;text-transform:uppercase">
          ${escHtml(sect.name)}${multBadge}</td>
        <td style="padding:5px 10px;text-align:right;font-family:var(--font-mono);font-size:10px;
          color:var(--blue-hi)">${sect.section_total.toLocaleString('en-ZA',{minimumFractionDigits:2})}</td>
      </tr>`;
      sect.items.forEach(it => {
        rows += `<tr style="border-bottom:1px solid rgba(48,54,61,.3)">
          <td style="padding:4px 10px 4px 22px">${escHtml(it.material_name)}</td>
          <td style="padding:4px 10px;font-family:var(--font-mono);color:var(--text-dim);font-size:10px">
            ${escHtml(it.formula_expression)}</td>
          <td style="padding:4px 10px;text-align:right;font-family:var(--font-mono)">
            ${Number(it.price_per_unit).toFixed(2)}</td>
          <td style="padding:4px 10px;color:var(--text-dim)">${it.unit_of_measure}</td>
          <td></td>
        </tr>`;
      });
    });
    document.getElementById('import-preview-body').innerHTML = rows;

    showImportStep(2);
  } catch(e) {
    toast('Preview failed: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = _importParsed ? 'Import Now' : 'Preview';
  }
}

async function doImport() {
  if (!_importParsed) { toast('Run preview first', 'warn'); return; }
  const btn = document.getElementById('import-action-btn');
  btn.disabled = true; btn.textContent = 'Importing…';
  const ttOverride = document.getElementById('import-tt-name').value.trim();
  const replace    = document.getElementById('import-replace').checked;
  try {
    const res = await api('POST', '/api/import/execute', {
      parsed: _importParsed,
      trailer_name_override: ttOverride,
      replace_existing: replace,
    });
    toast(`Imported "${res.trailer_name}" — ${res.items_imported} items in ${res.sections_imported} sections`, 'success');
    closeImportModal();
    await loadTrailers();
    // Select the newly imported trailer
    selectTrailer(res.trailer_type_id);
  } catch(e) {
    toast('Import failed: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Import Now';
  }
}

// ── Formula tooltips on BOM rows (skin / taping / floor) ─────────────
let _atTapingBlocks = [];
let _atFloorPlates  = [];
let _atCleats       = [];

document.addEventListener('DOMContentLoaded', async () => {
  try { _atTapingBlocks = await api('GET', '/api/taping-blocks');   } catch(e) {}
  try { _atFloorPlates  = await api('GET', '/api/floor-plates');    } catch(e) {}
  try { _atCleats       = await api('GET', '/api/mounting-cleats'); } catch(e) {}

  const skinTip = document.createElement('div');
  skinTip.id = 'skin-tip';
  document.body.appendChild(skinTip);

  const tapingTip = document.createElement('div');
  tapingTip.id = 'taping-tip';
  tapingTip.style.display = 'none';
  document.body.appendChild(tapingTip);

  const floorTip = document.createElement('div');
  floorTip.id = 'floor-tip';
  floorTip.style.display = 'none';
  document.body.appendChild(floorTip);

  const cleatTip = document.createElement('div');
  cleatTip.id = 'cleat-tip';
  cleatTip.style.display = 'none';
  document.body.appendChild(cleatTip);

  function buildSkinTip(name, region, items) {
    const useKzn = region === 'kzn';
    let total = 0;
    const rows = items.map(it => {
      const price = useKzn ? it.price_kzn : it.price_std;
      const line  = price * it.qty;
      total += line;
      return `<tr><td>${escHtml(it.name)}</td><td>${it.qty.toFixed(4)}</td><td>R ${price.toFixed(2)}</td><td>R ${line.toFixed(4)}</td></tr>`;
    }).join('');
    return `<div class="tip-title">◎ SKIN &nbsp;·&nbsp; ${escHtml(name)} &nbsp;·&nbsp; ${region.toUpperCase()}</div>
      <table><thead><tr><th>Ingredient</th><th>Qty/m²</th><th>${useKzn ? 'KZN Price' : 'Std Price'}</th><th>Line</th></tr></thead>
      <tbody>${rows}</tbody>
      <tfoot><tr><td colspan="3">Total per m²</td><td>R ${total.toFixed(4)}</td></tr></tfoot></table>`;
  }

  function buildTapingTip(block) {
    if (!block) return '';
    let total = 0;
    const rows = block.items.map(it => {
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
    return `<div style="font-weight:700;color:#f0a500;margin-bottom:8px;letter-spacing:.3px">⊡ TAPING &nbsp;·&nbsp; ${escHtml(block.name)}</div>
      <table style="width:100%;border-collapse:collapse;color:var(--text)">
        <thead><tr style="color:var(--text-dim);font-size:11px;border-bottom:1px solid rgba(240,165,0,.3)">
          <th style="padding:2px 8px 4px 0;text-align:left">Item</th>
          <th style="padding:2px 8px 4px;text-align:right">M²</th>
          <th style="padding:2px 8px 4px;text-align:right">Qty</th>
          <th style="padding:2px 8px 4px;text-align:right">Price/m²</th>
          <th style="padding:2px 0 4px;text-align:right">Line</th>
        </tr></thead><tbody>${rows}</tbody>
        <tfoot><tr style="border-top:1px solid rgba(240,165,0,.3);font-weight:600;color:#f0a500">
          <td colspan="4" style="padding:4px 8px 0 0">Total per block</td>
          <td style="padding:4px 0 0;text-align:right;font-family:var(--font-mono)">R ${total.toFixed(4)}</td>
        </tr></tfoot></table>`;
  }

  function buildFloorTip(plate) {
    if (!plate) return '';
    let rawTotal = 0;
    const rows = plate.items.map(it => {
      const price = it.price_source === 'sap' && it.price_sap != null ? it.price_sap : it.price_per_unit;
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
    let formulaHtml = '';
    if (plate.price_formula) {
      try {
        const steps = JSON.parse(plate.price_formula);
        let result = rawTotal, expr = `R ${rawTotal.toFixed(2)}`;
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
    return `<div style="font-weight:700;color:#3d9970;margin-bottom:8px;letter-spacing:.3px">⊞ FLOOR PLATE &nbsp;·&nbsp; ${escHtml(plate.name)}</div>
      <table style="width:100%;border-collapse:collapse;color:var(--text)">
        <thead><tr style="color:var(--text-dim);font-size:11px;border-bottom:1px solid rgba(61,153,112,.3)">
          <th style="padding:2px 8px 4px 0;text-align:left">Item</th>
          <th style="padding:2px 8px 4px;text-align:right">M²</th>
          <th style="padding:2px 8px 4px;text-align:right">Qty</th>
          <th style="padding:2px 8px 4px;text-align:right">Price/m²</th>
          <th style="padding:2px 0 4px;text-align:right">Line</th>
        </tr></thead><tbody>${rows}</tbody>
        <tfoot>
          <tr style="border-top:1px solid rgba(61,153,112,.3);font-weight:600;color:#3d9970">
            <td colspan="4" style="padding:4px 8px 0 0">${totalLabel}</td>
            <td style="padding:4px 0 0;text-align:right;font-family:var(--font-mono)">R ${rawTotal.toFixed(4)}</td>
          </tr>
          ${formulaHtml}
        </tfoot></table>`;
  }

  function makeHoverHandler(rowSelector, tipEl, getHtml, useDisplay) {
    let _target = null;
    const show = useDisplay
      ? () => { tipEl.style.display = 'block'; }
      : () => { tipEl.classList.add('visible'); };
    const hide = useDisplay
      ? () => { tipEl.style.display = 'none'; }
      : () => { tipEl.classList.remove('visible'); };
    const isVisible = useDisplay
      ? () => tipEl.style.display !== 'none'
      : () => tipEl.classList.contains('visible');

    document.addEventListener('mouseover', e => {
      const row = e.target.closest(rowSelector);
      if (!row) return;
      if (row === _target) return;
      const html = getHtml(row);
      if (!html) return;
      _target = row;
      tipEl.innerHTML = html;
      show();
    });
    document.addEventListener('mousemove', e => {
      if (!isVisible()) return;
      const vw = window.innerWidth, vh = window.innerHeight;
      const tw = tipEl.offsetWidth + 16, th = tipEl.offsetHeight + 16;
      const x = e.clientX + 16 + tw > vw ? e.clientX - tw : e.clientX + 16;
      const y = e.clientY + 16 + th > vh ? e.clientY - th - 8 : e.clientY + 16;
      tipEl.style.left = x + 'px';
      tipEl.style.top  = y + 'px';
    });
    document.addEventListener('mouseout', e => {
      const row = e.target.closest(rowSelector);
      if (row && !row.contains(e.relatedTarget)) { hide(); _target = null; }
    });
  }

  makeHoverHandler('tr.bom-skin-row', skinTip, row => {
    if (!row.dataset.skinItems) return null;
    try {
      return buildSkinTip(row.dataset.skinName || '', row.dataset.skinRegion || 'standard', JSON.parse(row.dataset.skinItems));
    } catch(e) { return null; }
  }, false);

  makeHoverHandler('tr.bom-taping-row', tapingTip, row => {
    const block = _atTapingBlocks.find(b => String(b.id) === row.dataset.tapingId);
    return block ? buildTapingTip(block) : null;
  }, true);

  makeHoverHandler('tr.bom-floor-row', floorTip, row => {
    const plate = _atFloorPlates.find(p => String(p.id) === row.dataset.floorId);
    return plate ? buildFloorTip(plate) : null;
  }, true);

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

  makeHoverHandler('tr.bom-cleat-row', cleatTip, row => {
    const cleat = _atCleats.find(c => String(c.id) === row.dataset.cleatId);
    return cleat ? buildCleatTip(cleat) : null;
  }, true);
});
