/* ── Trailer Costing System — Shared JS ─────────────────────────────────── */

// ── Toast ─────────────────────────────────────────────────────────────────
function toast(msg, type = 'info', duration = 3800) {
  let c = document.getElementById('toast-container');
  if (!c) {
    c = document.createElement('div');
    c.id = 'toast-container';
    document.body.appendChild(c);
  }
  const t = document.createElement('div');
  t.className = `toast toast-${type}`;
  const icons = { success: '✓', error: '✕', info: 'ℹ', warn: '⚠' };
  const safeMsg = String(msg).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  t.innerHTML =
    `<span class="toast-icon">${icons[type] || '•'}</span>` +
    `<span class="toast-msg">${safeMsg}</span>` +
    `<button class="toast-close" aria-label="Dismiss">×</button>`;
  c.appendChild(t);
  const dismiss = () => {
    t.classList.add('toast-leaving');
    setTimeout(() => t.remove(), 200);
  };
  t.querySelector('.toast-close').addEventListener('click', dismiss);
  if (duration > 0) setTimeout(dismiss, duration);
  return t;
}

// ── Flash: persist a toast message across a page navigation ───────────────
// Usage: flash('Saved!', 'success'); location.href = '/somewhere';
function flash(msg, type = 'info') {
  try { sessionStorage.setItem('_flash', JSON.stringify({ msg, type, ts: Date.now() })); }
  catch (_) {}
}
function _consumeFlash() {
  try {
    const raw = sessionStorage.getItem('_flash');
    if (!raw) return;
    sessionStorage.removeItem('_flash');
    const f = JSON.parse(raw);
    if (f && f.msg && (Date.now() - (f.ts || 0)) < 10000) toast(f.msg, f.type || 'info');
  } catch (_) {}
}
document.addEventListener('DOMContentLoaded', _consumeFlash);

// ── Button busy/loading state ─────────────────────────────────────────────
function showBusy(btn, label = 'Working…') {
  if (!btn) return () => {};
  btn._origHTML = btn.innerHTML;
  btn._origDisabled = btn.disabled;
  btn.disabled = true;
  btn.classList.add('is-busy');
  btn.innerHTML = `<span class="spinner spinner-sm"></span>${label}`;
  return () => hideBusy(btn);
}
function hideBusy(btn) {
  if (!btn || btn._origHTML === undefined) return;
  btn.innerHTML = btn._origHTML;
  btn.disabled = btn._origDisabled;
  btn.classList.remove('is-busy');
  delete btn._origHTML;
  delete btn._origDisabled;
}

// ── Skeleton loader rows ──────────────────────────────────────────────────
// Returns HTML string of placeholder rows for a table while data loads
function skeletonRows(colCount, rowCount = 6) {
  let html = '';
  for (let r = 0; r < rowCount; r++) {
    html += '<tr class="skeleton-row">';
    for (let c = 0; c < colCount; c++) {
      const w = (45 + Math.random() * 50).toFixed(0);
      html += `<td><div class="skeleton-bar" style="width:${w}%"></div></td>`;
    }
    html += '</tr>';
  }
  return html;
}

// ── Sortable table column headers ─────────────────────────────────────────
// Marks <th data-sort="key"> as clickable; calls onSort(key, dir) on click.
function initSortableHeaders(tableEl, onSort) {
  if (!tableEl) return;
  let curKey = null, curDir = 'asc';
  tableEl.querySelectorAll('thead th[data-sort]').forEach(th => {
    th.classList.add('sortable');
    th.style.cursor = 'pointer';
    th.addEventListener('click', () => {
      const key = th.dataset.sort;
      curDir = (curKey === key && curDir === 'asc') ? 'desc' : 'asc';
      curKey = key;
      tableEl.querySelectorAll('thead th[data-sort]').forEach(h =>
        h.classList.remove('sort-asc', 'sort-desc'));
      th.classList.add(curDir === 'asc' ? 'sort-asc' : 'sort-desc');
      onSort(curKey, curDir);
    });
  });
}

// ── Global loading overlay ────────────────────────────────────────────────
let _loadingDepth = 0;
function showLoadingOverlay(label = 'Working…') {
  const el = document.getElementById('global-loading-overlay');
  if (!el) return () => {};
  _loadingDepth++;
  const lbl = el.querySelector('.loading-label');
  if (lbl) lbl.textContent = label;
  el.classList.remove('hidden');
  return () => {
    _loadingDepth = Math.max(0, _loadingDepth - 1);
    if (_loadingDepth === 0) el.classList.add('hidden');
  };
}

// ── Keyboard shortcuts ────────────────────────────────────────────────────
const pageShortcuts = { search: null, save: null, new: null };
function registerPageShortcuts(shortcuts = {}) {
  pageShortcuts.search = shortcuts.search || null;
  pageShortcuts.save   = shortcuts.save   || null;
  pageShortcuts.new    = shortcuts.new    || null;
}
function _isTyping(t) {
  if (!t) return false;
  if (t.isContentEditable) return true;
  return ['input','textarea','select'].includes((t.tagName||'').toLowerCase());
}
function _invokeShortcut(h, e) {
  if (!h) return false;
  if (typeof h === 'function') { h(e); return true; }
  const el = document.querySelector(h);
  if (!el) return false;
  el.click?.() || el.focus?.();
  return true;
}
function _focusSearch() {
  for (const sel of ['[data-global-search]','#search','#cust-search','input[type="search"]']) {
    const el = document.querySelector(sel);
    if (el && !el.disabled && el.offsetParent !== null) { el.focus(); el.select?.(); return; }
  }
}
document.addEventListener('keydown', ev => {
  const k = ev.key.toLowerCase(), mod = ev.ctrlKey || ev.metaKey;
  if (!mod && k === '?' && !_isTyping(ev.target)) { ev.preventDefault(); openModal('modal-shortcuts'); return; }
  if (!mod) return;
  if (k === 'k') { ev.preventDefault(); if (!_invokeShortcut(pageShortcuts.search, ev)) _focusSearch(); }
  if (k === 's' && pageShortcuts.save) { ev.preventDefault(); _invokeShortcut(pageShortcuts.save, ev); }
  if (k === 'n' && pageShortcuts.new)  { ev.preventDefault(); _invokeShortcut(pageShortcuts.new, ev); }
});

// ── Format currency ───────────────────────────────────────────────────────
function fmt(n) {
  if (n === null || n === undefined) return '—';
  // U+00A0 NBSP between R and number so they never split across lines
  return 'R ' + Number(n).toLocaleString('en-ZA', {
    minimumFractionDigits: 2, maximumFractionDigits: 2
  });
}

function fmtNum(n, dp = 4) {
  return Number(n).toLocaleString('en-ZA', {
    minimumFractionDigits: 0, maximumFractionDigits: dp
  });
}

// ── API helpers ───────────────────────────────────────────────────────────
const _csrfToken = () =>
  document.querySelector('meta[name="csrf-token"]')?.content || '';

async function api(method, url, body) {
  const opts = {
    method,
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': _csrfToken(),
    },
  };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(url, opts);
  if (res.type === 'opaqueredirect' || (res.status >= 300 && res.status < 400)) {
    throw new Error('Session expired — please reload the page');
  }
  if (!res.ok) {
    const txt = await res.text();
    let msg;
    try { msg = JSON.parse(txt).detail || txt; } catch (_) { msg = txt; }
    throw new Error(msg || `HTTP ${res.status}`);
  }
  return res.json();
}

// ── Modal helpers ─────────────────────────────────────────────────────────
function openModal(id) {
  document.getElementById(id)?.classList.remove('hidden');
}
function closeModal(id) {
  document.getElementById(id)?.classList.add('hidden');
}
function closeAllModals() {
  document.querySelectorAll('.modal-backdrop').forEach(m => m.classList.add('hidden'));
}

// ── Styled prompt dialog (replacement for window.prompt) ──────────────────
let _promptPromiseResolve = null;
function _promptModalResolve(value) {
  const modal = document.getElementById('modal-prompt');
  if (modal) modal.classList.add('hidden');
  if (_promptPromiseResolve) {
    const r = _promptPromiseResolve;
    _promptPromiseResolve = null;
    r(value);
  }
}
function promptModal(message, defaultValue = '', opts = {}) {
  const { title = 'Enter value', okText = 'OK' } = opts;
  const modal = document.getElementById('modal-prompt');
  if (!modal) return Promise.resolve(window.prompt(message, defaultValue));
  document.getElementById('prompt-title').textContent = title;
  document.getElementById('prompt-message').textContent = message;
  const inp = document.getElementById('prompt-input');
  inp.value = defaultValue == null ? '' : String(defaultValue);
  modal.classList.remove('hidden');
  setTimeout(() => { inp.focus(); inp.select(); }, 50);
  return new Promise(resolve => { _promptPromiseResolve = resolve; });
}

// ── Styled confirm dialog (replacement for window.confirm) ────────────────
let _confirmPromiseResolve = null;
function _confirmModalResolve(value) {
  const modal = document.getElementById('modal-confirm');
  if (modal) modal.classList.add('hidden');
  if (_confirmPromiseResolve) {
    const r = _confirmPromiseResolve;
    _confirmPromiseResolve = null;
    r(value);
  }
}
function confirmModal(message, opts = {}) {
  const {
    title = 'Confirm',
    okText = 'OK',
    cancelText = 'Cancel',
    danger = false,
  } = opts;
  const modal = document.getElementById('modal-confirm');
  if (!modal) return Promise.resolve(window.confirm(message));
  document.getElementById('confirm-title').textContent = title;
  document.getElementById('confirm-message').textContent = message;
  const ok = document.getElementById('confirm-ok');
  ok.textContent = okText;
  ok.className = 'btn ' + (danger ? 'btn-danger' : 'btn-primary');
  document.getElementById('confirm-cancel').textContent = cancelText;
  modal.classList.remove('hidden');
  setTimeout(() => ok.focus(), 50);
  return new Promise(resolve => { _confirmPromiseResolve = resolve; });
}
function alertModal(message, opts = {}) {
  const { title = 'Notice', okText = 'OK', danger = false } = opts;
  const modal = document.getElementById('modal-confirm');
  if (!modal) { window.alert(message); return Promise.resolve(); }
  document.getElementById('confirm-title').textContent = title;
  document.getElementById('confirm-message').textContent = message;
  const ok = document.getElementById('confirm-ok');
  ok.textContent = okText;
  ok.className = 'btn ' + (danger ? 'btn-danger' : 'btn-primary');
  const cancel = document.getElementById('confirm-cancel');
  const prevDisplay = cancel.style.display;
  cancel.style.display = 'none';
  modal.classList.remove('hidden');
  setTimeout(() => ok.focus(), 50);
  return new Promise(resolve => {
    _confirmPromiseResolve = (v) => { cancel.style.display = prevDisplay; resolve(v); };
  });
}
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeAllModals();
});
document.addEventListener('click', e => {
  if (e.target.classList.contains('modal-backdrop')) closeAllModals();
});

// ── Category tag colour ───────────────────────────────────────────────────
function catTag(cat) {
  const map = {
    'Steel': 'steel', 'Stainless Steel': 'steel',
    'Aluminium': 'alu',
    'Resins & Adhesives': 'grp', 'Plywood & Timber': 'grp',
    'Rubber': 'rubber',
    'Paint & Consumables': 'paint',
    'Electrical': 'elec',
  };
  const cls = map[cat] || 'default';
  return `<span class="tag tag-${cls}">${cat}</span>`;
}

// ── Collapsible category blocks ───────────────────────────────────────────
function initCollapsibles() {
  document.querySelectorAll('.category-heading').forEach(h => {
    const target = h.nextElementSibling;
    if (!target) return;
    const arrow = h.querySelector('.collapse-arrow');
    h.addEventListener('click', () => {
      const open = target.style.display !== 'none';
      target.style.display = open ? 'none' : '';
      if (arrow) arrow.textContent = open ? '▶' : '▼';
    });
  });
}

// ── Inline cell editing ───────────────────────────────────────────────────
function makeEditable(cell, onSave) {
  cell.style.cursor = 'pointer';
  cell.addEventListener('dblclick', () => {
    const orig = cell.textContent.trim();
    cell.innerHTML = `<input class="inline-edit" value="${orig}" />`;
    const inp = cell.querySelector('input');
    inp.focus(); inp.select();
    const done = async () => {
      const val = inp.value.trim();
      cell.textContent = val;
      try { await onSave(val); }
      catch (err) { cell.textContent = orig; toast(err.message, 'error'); }
    };
    inp.addEventListener('blur', done);
    inp.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); inp.blur(); }
      if (e.key === 'Escape') { cell.textContent = orig; }
    });
  });
}

// ── Mouse-wheel scrolling on <select> elements ────────────────────────────────
// Hovering over any <select> and rolling the mouse wheel moves the selection
// up/down without the user needing to click first to open the dropdown.
document.addEventListener('wheel', function(e) {
  const el = e.target;
  if (!el || el.tagName.toLowerCase() !== 'select') return;
  if (el.disabled || el.size <= 1) return;   // skip collapsed single-line selects (they open a native popup)
  e.preventDefault();
  const dir   = e.deltaY > 0 ? 1 : -1;
  const opts  = el.options;
  const newIdx = Math.max(0, Math.min(opts.length - 1, el.selectedIndex + dir));
  if (newIdx !== el.selectedIndex) {
    el.selectedIndex = newIdx;
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }
}, { passive: false });
