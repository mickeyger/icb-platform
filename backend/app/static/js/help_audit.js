/* Excel Audit Panel — loads the reconciliation report from /api/help/audit
   and renders an interactive, collapsible section-by-section comparison of
   the attached Excel costing sheet vs the live calculator. Click a section
   to scroll/flash the matching live section. Right-click for "Investigate
   section" which opens the chat with a pre-filled deep-dive prompt. */
(function () {
  'use strict';

  // Bail if no anchor (logged-out pages, error pages)
  if (!document.getElementById('help-launcher')) return;

  // ── Build panel DOM (deferred until first use) ──────────────────────────
  let panel = null;
  let launcher = null;
  let summaryEl = null;
  let warningsEl = null;
  let sectionsEl = null;
  let currentReport = null;
  let _lastSyncBody = null;
  let _syncDebounce = null;

  function buildPanel() {
    if (panel) return panel;
    panel = document.createElement('aside');
    panel.id = 'help-audit-panel';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Excel vs live costing audit');
    panel.innerHTML = `
      <div class="audit-header">
        <div>
          <div class="audit-title">Excel ↔ Live Costing Audit</div>
          <div class="audit-subtitle" id="audit-subtitle">Loading…</div>
        </div>
        <div class="audit-header-actions">
          <button class="help-icon-btn" id="audit-flip" title="Move panel to other side">⇄</button>
          <button class="help-icon-btn" id="audit-refresh" title="Re-run audit with current calculator state">⟲</button>
          <button class="help-icon-btn" id="audit-close" title="Close">✕</button>
        </div>
      </div>
      <div class="audit-summary" id="audit-summary"></div>
      <div class="audit-warnings" id="audit-warnings" style="display:none"></div>
      <div class="audit-sections" id="audit-sections"></div>
    `;
    document.body.appendChild(panel);
    summaryEl  = panel.querySelector('#audit-summary');
    warningsEl = panel.querySelector('#audit-warnings');
    sectionsEl = panel.querySelector('#audit-sections');
    panel.querySelector('#audit-close').addEventListener('click', closePanel);
    panel.querySelector('#audit-refresh').addEventListener('click', () => runAudit({ silent: false }));
    panel.querySelector('#audit-flip').addEventListener('click', flipSide);
    // Apply persisted side preference
    try {
      const side = localStorage.getItem('helpaudit:side:v1') || 'left';
      applySide(side);
    } catch (_) { applySide('left'); }
    return panel;
  }

  function applySide(side) {
    if (!panel) return;
    if (side === 'right') panel.classList.add('dock-right');
    else panel.classList.remove('dock-right');
    // Update flip-button glyph so it points at the side it'll move to.
    const flipBtn = panel.querySelector('#audit-flip');
    if (flipBtn) flipBtn.textContent = (side === 'right') ? '←' : '→';
  }
  function flipSide() {
    if (!panel) return;
    const newSide = panel.classList.contains('dock-right') ? 'left' : 'right';
    applySide(newSide);
    try { localStorage.setItem('helpaudit:side:v1', newSide); } catch (_) {}
  }

  function buildLauncher() {
    if (launcher) return launcher;
    launcher = document.createElement('button');
    launcher.id = 'help-audit-launcher';
    launcher.type = 'button';
    launcher.innerHTML = '<span>📊</span><span>Excel Audit</span>';
    launcher.addEventListener('click', openPanel);
    document.body.appendChild(launcher);
    return launcher;
  }

  function showLauncher() {
    buildLauncher();
    launcher.classList.add('visible');
  }
  function hideLauncher() {
    if (launcher) launcher.classList.remove('visible');
  }

  function openPanel() {
    buildPanel();
    panel.classList.add('open');
    // First-load sync: the chip's persisted sheet may be from a previous body.
    // Pick the best-matching sheet for the body currently on screen before
    // running the audit so the very first comparison is correct.
    _syncToCurrentBody({ silent: true });
    if (!currentReport) runAudit({ silent: false });
  }

  // Pick the best sheet for the body currently on the calculator (or
  // page_context) and update the chip if it differs. Returns true if a
  // switch happened. Safe to call any time — no-op if no attachment, no
  // body, or chip already on the right sheet.
  function _syncToCurrentBody(opts) {
    opts = opts || {};
    const att = window.helpChatGetAttachment ? window.helpChatGetAttachment() : null;
    if (!att) return false;
    const body = (window.helpContext && window.helpContext.body)
      || (function () {
        // Fallback: pull body name from the calculator's dropdown if helpContext
        // hasn't been published yet (e.g. user opens the audit before clicking
        // calculate). Both calc + calc2 use #trailer-select.
        const sel = document.getElementById('trailer-select');
        return sel ? (sel.selectedOptions[0]?.textContent || '').trim() || null : null;
      })();
    if (!body) return false;
    const best = _pickBestSheet(att.sheets || [], body);
    if (!best || best === att.sheet) return false;
    if (window.helpChatSetAttachmentSheet && window.helpChatSetAttachmentSheet(best)) {
      _lastSyncBody = body;
      if (!opts.silent && window.toast) toast('Audit synced to "' + best + '" for ' + body, 'info');
      return true;
    }
    return false;
  }
  function closePanel() {
    if (panel) panel.classList.remove('open');
    hideContextMenu();
  }

  // ── Audit run (talks to /api/help/audit) ────────────────────────────────
  function _csrf() {
    return document.querySelector('meta[name="csrf-token"]')?.content || '';
  }

  function _slimLiveResult(r) {
    if (!r || typeof r !== 'object') return r;
    const items = Array.isArray(r.items) ? r.items.map(it => ({
      category:   it.category,
      material:   it.material,
      quantity:   it.quantity,
      unit_price: it.unit_price,
      line_cost:  it.line_cost,
      excluded:   !!it.excluded,
    })) : [];
    return {
      items,
      category_totals:   r.category_totals || null,
      grand_total:       r.grand_total ?? null,
      cost_per_sqm:      r.cost_per_sqm ?? null,
      geometry:          r.geometry || null,
      markup_percentage: r.markup_percentage ?? null,
    };
  }

  async function runAudit(opts) {
    opts = opts || {};
    const att = window.helpChatGetAttachment ? window.helpChatGetAttachment() : null;
    if (!att) {
      if (!opts.silent && window.toast) toast('Attach an Excel workbook in the help chat first.', 'warn');
      return;
    }
    buildPanel();
    panel.querySelector('#audit-subtitle').textContent = 'Running audit…';
    sectionsEl.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-dim,#8b949e);font-size:12px">Running audit…</div>';

    const live = window.helpContext || {};
    const body = {
      upload_id:   att.upload_id,
      sheet:       att.sheet,
      live_result: _slimLiveResult(live.liveResult),
      live_body:   live.body || null,
    };

    try {
      const res = await fetch('/api/help/audit', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': _csrf(),
        },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        let detail = 'HTTP ' + res.status;
        try { const j = await res.json(); detail = j.detail || detail; } catch (_) {}
        sectionsEl.innerHTML = '<div style="padding:24px;color:#f85149;font-size:12px">' + escapeHtml(detail) + '</div>';
        panel.querySelector('#audit-subtitle').textContent = 'Failed';
        return;
      }
      const report = await res.json();
      currentReport = report;
      renderReport(report, att);
    } catch (err) {
      sectionsEl.innerHTML = '<div style="padding:24px;color:#f85149;font-size:12px">' + escapeHtml('Network error: ' + (err.message || err)) + '</div>';
      panel.querySelector('#audit-subtitle').textContent = 'Failed';
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────
  const fmt = n => (n == null ? '—' : 'R ' + Number(n).toLocaleString('en-ZA', {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  }));

  function deltaClass(delta, base) {
    if (delta == null) return 'delta-na';
    if (Math.abs(delta) < 1) return 'delta-zero';
    if (base && Math.abs(delta / base) < 0.05) return 'delta-small';  // <5% off
    if (Math.abs(delta) < 200) return 'delta-small';
    return 'delta-big';
  }

  function renderReport(report, att) {
    if (report.error) {
      sectionsEl.innerHTML = '<div style="padding:24px;color:#f85149;font-size:12px">'
        + escapeHtml(report.message || ('Audit error: ' + report.error)) + '</div>';
      panel.querySelector('#audit-subtitle').textContent = 'Error';
      return;
    }
    const sheetLabel = (att && att.sheet) || report.sheet_name || '';
    panel.querySelector('#audit-subtitle').textContent =
      'Sheet: ' + sheetLabel + (report.summary?.live_body ? ' · Body: ' + report.summary.live_body : '');

    // Summary
    const s = report.summary || {};
    const dClass = s.delta == null ? '' : (Math.abs(s.delta) < 1 ? 'delta-zero' : (s.delta > 0 ? 'delta-pos' : 'delta-neg'));
    const rdt = s.rounding_drift_total;
    const showRounding = rdt != null && Math.abs(rdt) >= 0.01;
    summaryEl.innerHTML = `
      <div>
        <div class="audit-stat-label">Excel total</div>
        <div class="audit-stat-value">${fmt(s.excel_grand_total)}</div>
      </div>
      <div>
        <div class="audit-stat-label">Live total</div>
        <div class="audit-stat-value">${fmt(s.live_grand_total)}</div>
      </div>
      <div>
        <div class="audit-stat-label">Delta</div>
        <div class="audit-stat-value ${dClass}">${s.delta == null ? '—' : (s.delta >= 0 ? '+' : '') + fmt(s.delta).replace('R ', 'R ')}</div>
      </div>
      ${showRounding ? `
      <div title="Portion of the delta that is pure half-up vs banker's rounding — not a real cost difference">
        <div class="audit-stat-label">of which rounding</div>
        <div class="audit-stat-value delta-rounding">${(rdt >= 0 ? '+' : '') + fmt(rdt).replace('R ', 'R ')}</div>
      </div>` : ''}
    `;

    // Warnings
    const warns = Array.isArray(report.warnings) ? report.warnings : [];
    if (warns.length) {
      warningsEl.style.display = '';
      const collapsed = localStorage.getItem('helpaudit:warns-collapsed:v1') === '1';
      if (collapsed) warningsEl.classList.add('collapsed');
      else warningsEl.classList.remove('collapsed');
      warningsEl.innerHTML =
        `<div class="audit-warnings-header" id="audit-warnings-hdr">` +
          `<strong>⚠ Warnings <span style="font-weight:400;opacity:.7">(${warns.length})</span></strong>` +
          `<button class="help-icon-btn audit-warnings-toggle" id="audit-warnings-toggle" title="${collapsed ? 'Expand warnings' : 'Collapse warnings'}">${collapsed ? '▼' : '▲'}</button>` +
        `</div>` +
        `<div class="audit-warnings-body"><ul>` +
          warns.map(w => '<li>' + escapeHtml(w) + '</li>').join('') +
        `</ul></div>`;
      warningsEl.querySelector('#audit-warnings-hdr').addEventListener('click', () => {
        const isNowCollapsed = warningsEl.classList.toggle('collapsed');
        const btn = warningsEl.querySelector('#audit-warnings-toggle');
        if (btn) { btn.textContent = isNowCollapsed ? '▼' : '▲'; btn.title = isNowCollapsed ? 'Expand warnings' : 'Collapse warnings'; }
        try { localStorage.setItem('helpaudit:warns-collapsed:v1', isNowCollapsed ? '1' : '0'); } catch (_) {}
      });
    } else {
      warningsEl.style.display = 'none';
    }

    // Sections (sorted by abs(delta) desc so biggest issues float)
    const bySection = Array.isArray(report.by_section) ? report.by_section.slice() : [];
    bySection.sort((a, b) => Math.abs((b.delta || 0)) - Math.abs((a.delta || 0)));

    sectionsEl.innerHTML = '';
    if (!bySection.length) {
      sectionsEl.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-dim,#8b949e);font-size:12px">No comparable sections — both sides are empty.</div>';
      return;
    }
    bySection.forEach((sec, idx) => sectionsEl.appendChild(renderSection(sec, idx)));
  }

  function renderSection(sec, idx) {
    const wrap = document.createElement('div');
    wrap.className = 'audit-section';
    const delta = sec.delta;
    const dCls = deltaClass(delta, sec.excel_total);
    const dStr = delta == null ? '—' : (delta >= 0 ? '+' : '') + fmt(delta).replace('R ', 'R ');

    const rd = sec.rounding_drift;
    const rdChip = (rd != null && Math.abs(rd) >= 0.01)
      ? `<span class="audit-cause-chip cause-rounding" title="R${fmt(rd).replace('R ', '')} of this section's delta is pure rounding noise">⊘ ${fmt(rd).replace('R ', 'R')}</span>`
      : '';

    const row = document.createElement('div');
    row.className = 'audit-section-row';
    row.innerHTML = `
      <span class="audit-chev"></span>
      <span class="audit-section-name" title="${escAttr(sec.section)}">${escapeHtml(sec.section)}${rdChip}</span>
      <span class="audit-section-total" title="Excel">${fmt(sec.excel_total)}</span>
      <span class="audit-section-total" title="Live">${fmt(sec.live_total)}</span>
      <span class="audit-section-delta ${dCls}" title="Live − Excel">${dStr}</span>
    `;
    wrap.appendChild(row);

    const detail = document.createElement('div');
    detail.className = 'audit-section-detail';
    detail.appendChild(renderLineTable(sec));
    wrap.appendChild(detail);

    // Click row: toggle expand AND scroll/flash the matching live section
    row.addEventListener('click', e => {
      // Don't toggle on right-click
      if (e.button === 2) return;
      wrap.classList.toggle('expanded');
      scrollToLiveSection(sec.section);
    });

    // Right-click → context menu
    row.addEventListener('contextmenu', e => {
      e.preventDefault();
      showContextMenu(e.pageX, e.pageY, sec);
    });

    return wrap;
  }

  function renderLineTable(sec) {
    const tbl = document.createElement('table');
    tbl.className = 'audit-line-table';
    tbl.innerHTML = `
      <thead>
        <tr>
          <th>Item</th>
          <th style="text-align:right">Qty</th>
          <th style="text-align:right">Unit R</th>
          <th style="text-align:right">Total R</th>
          <th style="text-align:right">Δ</th>
        </tr>
      </thead>
      <tbody></tbody>
    `;
    const tbody = tbl.querySelector('tbody');

    // Matched lines first (sorted by abs delta desc)
    const matched = (sec.matched || []).slice().sort((a, b) =>
      Math.abs((b.delta?.total || 0)) - Math.abs((a.delta?.total || 0))
    );
    matched.forEach(m => tbody.appendChild(renderMatchedRow(m)));

    // Only-in-excel
    (sec.only_in_excel || []).forEach(r => {
      const tr = document.createElement('tr');
      tr.className = 'audit-line diff-missing-live';
      tr.innerHTML = `
        <td><div class="audit-line-name">${escapeHtml(r.name)}</div>
            <div class="audit-line-side">Only in Excel</div></td>
        <td class="audit-line-num">${r.qty ?? '—'}</td>
        <td class="audit-line-num">${fmt(r.unit_price)}</td>
        <td class="audit-line-num">${fmt(r.total)}</td>
        <td class="audit-line-num delta-pos">missing live</td>
      `;
      tbody.appendChild(tr);
    });
    if ((sec.only_in_excel_truncated || 0) > 0) {
      tbody.appendChild(_truncRow('only_in_excel', sec.only_in_excel_truncated));
    }

    // Only-in-live
    (sec.only_in_live || []).forEach(r => {
      const tr = document.createElement('tr');
      tr.className = 'audit-line diff-missing-excel';
      tr.innerHTML = `
        <td><div class="audit-line-name">${escapeHtml(r.name)}</div>
            <div class="audit-line-side">Only in Live</div></td>
        <td class="audit-line-num">${r.qty ?? '—'}</td>
        <td class="audit-line-num">${fmt(r.unit_price)}</td>
        <td class="audit-line-num">${fmt(r.total)}</td>
        <td class="audit-line-num delta-neg">missing excel</td>
      `;
      tbody.appendChild(tr);
    });
    if ((sec.only_in_live_truncated || 0) > 0) {
      tbody.appendChild(_truncRow('only_in_live', sec.only_in_live_truncated));
    }
    if ((sec.matched_truncated || 0) > 0) {
      tbody.appendChild(_truncRow('matched', sec.matched_truncated));
    }
    return tbl;
  }

  function _truncRow(kind, n) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td colspan="5" style="text-align:center;color:var(--text-dim,#8b949e);font-style:italic;font-size:10px">…and ${n} more (truncated)</td>`;
    return tr;
  }

  // Small colour-coded chip naming the cause of a line-total difference.
  const CAUSE_LABELS = { price: 'price', formula: 'formula', rounding: 'rounding', unexplained: '?' };
  function causeChip(cause) {
    const c = cause && cause.cause;
    if (!c || c === 'match') return '';
    const label = CAUSE_LABELS[c] || c;
    return `<span class="audit-cause-chip cause-${c}" title="${escAttr(cause.note || '')}">${label}</span>`;
  }

  function renderMatchedRow(m) {
    const frag = document.createDocumentFragment();
    const tr = document.createElement('tr');
    tr.className = 'audit-line';
    const dTotal = m.delta?.total;
    const dQty   = m.delta?.qty;
    const dUnit  = m.delta?.unit_price;
    if (dTotal != null && Math.abs(dTotal) < 0.01) tr.classList.add('diff-balanced');
    else if (dQty   != null && Math.abs(dQty)   > 0.01) tr.classList.add('diff-qty-mismatch');
    else if (dUnit  != null && Math.abs(dUnit)  > 0.01) tr.classList.add('diff-price-mismatch');

    const dCell = (a, b, d) => {
      if (a == null && b == null) return '—';
      const same = d == null || Math.abs(d) < 0.01;
      const txt = same ? fmt(a) : `${fmt(a)}→${fmt(b)}`;
      return txt;
    };
    const dQtyCell = (a, b, d) => {
      if (a == null && b == null) return '—';
      const same = d == null || Math.abs(d) < 0.01;
      const txt = same ? (a ?? b ?? '—') : `${a ?? '—'}→${b ?? '—'}`;
      return txt;
    };

    const dCls = dTotal == null ? '' : (Math.abs(dTotal) < 0.01 ? 'delta-zero' : (dTotal > 0 ? 'delta-pos' : 'delta-neg'));

    // Expandable when there's a formula to show or a non-trivial cause.
    const cause = m.cause || {};
    const hasDetail = !!(m.excel_formula || m.app_formula || (cause.cause && cause.cause !== 'match'));
    if (hasDetail) tr.classList.add('audit-line-expandable');

    tr.innerHTML = `
      <td><div class="audit-line-name">${escapeHtml(m.name)}${hasDetail ? ' <span class="audit-line-caret">▸</span>' : ''}</div>
          <div class="audit-line-side">Excel → Live</div></td>
      <td class="audit-line-num">${dQtyCell(m.excel?.qty, m.live?.qty, dQty)}</td>
      <td class="audit-line-num">${dCell(m.excel?.unit_price, m.live?.unit_price, dUnit)}</td>
      <td class="audit-line-num">${dCell(m.excel?.total, m.live?.total, dTotal)}</td>
      <td class="audit-line-num ${dCls}">${dTotal == null ? '—' : (dTotal >= 0 ? '+' : '') + fmt(dTotal).replace('R ', 'R ')}${causeChip(cause)}</td>
    `;
    frag.appendChild(tr);

    if (hasDetail) {
      const detail = document.createElement('tr');
      detail.className = 'audit-line-detail';
      detail.style.display = 'none';
      detail.innerHTML = `
        <td colspan="5">
          <div class="audit-formula-block">
            ${cause.note ? `<div class="audit-formula-note">${escapeHtml(cause.note)}</div>` : ''}
            <div class="audit-formula-row"><span class="audit-formula-label">Excel ${escapeHtml(m.source_cell || '')}</span><code>${escapeHtml(m.excel_formula || (m.symbolic_formula ? 'qty = ' + m.symbolic_formula : '—'))}</code></div>
            <div class="audit-formula-row"><span class="audit-formula-label">App</span><code>${escapeHtml(m.app_formula != null ? 'qty = ' + m.app_formula : '—')}</code></div>
          </div>
        </td>`;
      frag.appendChild(detail);
      tr.addEventListener('click', (e) => {
        e.stopPropagation();
        const open = detail.style.display !== 'none';
        detail.style.display = open ? 'none' : '';
        const caret = tr.querySelector('.audit-line-caret');
        if (caret) caret.textContent = open ? '▸' : '▾';
      });
    }
    return frag;
  }

  // ── Live-section scroll/flash ───────────────────────────────────────────
  function scrollToLiveSection(sectionName) {
    if (!sectionName) return;
    const norm = s => String(s || '').toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim();
    const want = norm(sectionName);
    const area = document.getElementById('bom-area');
    if (!area) return;
    // Try calculator-table layout first
    const hdrs = Array.from(area.querySelectorAll('tr.calc-grp-hdr[data-cat-name]'));
    for (const h of hdrs) {
      if (norm(h.getAttribute('data-cat-name')) === want ||
          norm(h.getAttribute('data-cat-name')).includes(want) ||
          want.includes(norm(h.getAttribute('data-cat-name')))) {
        h.scrollIntoView({ behavior: 'smooth', block: 'center' });
        h.classList.add('help-flash');
        setTimeout(() => h.classList.remove('help-flash'), 5100);
        // Un-collapse + flash rows
        h.classList.remove('collapsed');
        const gid = h.getAttribute('data-cat-id');
        if (gid) {
          area.querySelectorAll('tr.calc-grp-row[data-cat-group="' + CSS.escape(gid) + '"]')
            .forEach(r => {
              if (r.style.display === 'none') r.style.display = '';
              r.classList.add('help-flash');
              setTimeout(() => r.classList.remove('help-flash'), 5100);
            });
        }
        return;
      }
    }
    // Admin/templates layout fallback
    const groups = Array.from(area.querySelectorAll('.parts-group'));
    for (const g of groups) {
      const t = norm(g.querySelector('.parts-group-title')?.textContent);
      if (t && (t === want || t.includes(want) || want.includes(t))) {
        g.scrollIntoView({ behavior: 'smooth', block: 'center' });
        g.classList.add('help-flash');
        setTimeout(() => g.classList.remove('help-flash'), 5100);
        return;
      }
    }
  }

  // ── Right-click context menu ────────────────────────────────────────────
  let ctxMenu = null;
  function hideContextMenu() {
    if (ctxMenu && ctxMenu.parentNode) ctxMenu.parentNode.removeChild(ctxMenu);
    ctxMenu = null;
  }
  document.addEventListener('click', hideContextMenu);

  function showContextMenu(x, y, section) {
    hideContextMenu();
    ctxMenu = document.createElement('div');
    ctxMenu.className = 'audit-ctxmenu';
    ctxMenu.style.left = x + 'px';
    ctxMenu.style.top  = y + 'px';
    ctxMenu.innerHTML = `
      <div class="audit-ctxmenu-item" data-act="investigate">🔍 Investigate this section</div>
      <div class="audit-ctxmenu-item" data-act="scroll">📍 Scroll to live section</div>
      <div class="audit-ctxmenu-item" data-act="expand">▼ Expand line-by-line</div>
    `;
    document.body.appendChild(ctxMenu);
    ctxMenu.addEventListener('click', e => {
      const act = e.target?.dataset?.act;
      if (act === 'investigate') investigateSection(section);
      else if (act === 'scroll')  scrollToLiveSection(section.section);
      else if (act === 'expand')  expandSection(section);
      hideContextMenu();
    });
  }

  function expandSection(section) {
    if (!sectionsEl) return;
    Array.from(sectionsEl.children).forEach(child => {
      const name = child.querySelector('.audit-section-name')?.getAttribute('title') || '';
      if (name === section.section) child.classList.add('expanded');
    });
  }

  // ── Send "Investigate" deep-dive to the chat ────────────────────────────
  function investigateSection(section) {
    if (!window.helpChatSend) {
      if (window.toast) toast('Open the help chat first.', 'warn');
      return;
    }
    // Build a structured user-turn the AI can act on without ambiguity.
    const lines = [];
    lines.push('Investigate the **' + section.section + '** section in detail.');
    lines.push('');
    lines.push('Below is the full reconciliation slice for this one section. ' +
      'Identify the top causes of the R ' + (section.delta || 0).toFixed(2) +
      ' variance between Excel and live, biggest contributors first, ' +
      'in plain English. Quote specific line names, qty differences, ' +
      'and unit-price differences from the data. If items are missing on one side, list them.');
    lines.push('');
    lines.push('```json');
    lines.push(JSON.stringify(section, null, 2).slice(0, 8000));
    lines.push('```');
    window.helpChatSend(lines.join('\n'), { showInChat: 'Investigate the ' + section.section + ' section' });
  }

  // ── Body-change auto-sync ───────────────────────────────────────────────
  // When the calculator's body dropdown changes, _publishHelpContext fires
  // `helpcontext:updated` with bodyChanged=true. If the audit panel is open
  // and an Excel attachment is loaded, fuzzy-match the new body name against
  // the workbook's sheet names, switch the chip's sheet to the best match,
  // and re-run the audit so the user sees the comparison sync automatically.
  window.addEventListener('helpcontext:updated', e => {
    const det = e && e.detail || {};
    if (!panel || !panel.classList.contains('open')) return;
    const att = window.helpChatGetAttachment ? window.helpChatGetAttachment() : null;
    if (!att) return;
    const newBody = det.body;
    if (!newBody) return;
    // De-bounce: the calculator can fire several context updates in a burst
    // when switching bodies (configurator tree load → BOM load → calc).
    // Wait until things settle before re-running.
    clearTimeout(_syncDebounce);
    _syncDebounce = setTimeout(() => {
      if (newBody === _lastSyncBody) {
        // Same body, just a refresh — re-run audit silently if it's the
        // body we already synced to (catches BOM edits without dropdown
        // change).
        if (det.bodyChanged === false) runAudit({ silent: true });
        return;
      }
      _lastSyncBody = newBody;
      const best = _pickBestSheet(att.sheets || [], newBody);
      if (best && best !== att.sheet) {
        // Switch the chip's sheet, then re-run.
        if (window.helpChatSetAttachmentSheet && window.helpChatSetAttachmentSheet(best)) {
          if (window.toast) toast('Audit synced to "' + best + '" for ' + newBody, 'info');
        }
      }
      runAudit({ silent: true });
    }, 250);
  });

  // Frontend mirror of reconcile.pick_sheet_for_body — same scoring logic so
  // user expectations match server behaviour. Returns the best sheet name
  // from `sheets` for `bodyName`, or null if there's no acceptable match.
  function _pickBestSheet(sheets, bodyName) {
    if (!Array.isArray(sheets) || !sheets.length) return null;
    if (!bodyName) return sheets[0];
    const normLocal = s => String(s || '').toUpperCase().replace(/\s+/g, ' ').trim();
    const want = normLocal(bodyName);
    let bestName = null;
    let bestScore = 0;
    for (const s of sheets) {
      const cand = normLocal(s);
      // Containment counts as a high-quality match
      if (!cand) continue;
      let score;
      if (cand === want)            score = 1.0;
      else if (cand.includes(want)) score = 0.85;
      else if (want.includes(cand)) score = 0.80;
      else                          score = _ratio(cand, want);
      if (score > bestScore) { bestScore = score; bestName = s; }
    }
    return bestScore >= 0.55 ? bestName : sheets[0];
  }
  // Cheap similarity score — Sorensen-Dice-ish on word tokens >=3 chars.
  function _ratio(a, b) {
    const A = new Set(a.split(' ').filter(t => t.length >= 3));
    const B = new Set(b.split(' ').filter(t => t.length >= 3));
    if (!A.size || !B.size) return 0;
    let common = 0;
    A.forEach(t => { if (B.has(t)) common++; });
    return (2 * common) / (A.size + B.size);
  }

  // ── Hooks for the chat widget to call ───────────────────────────────────
  // Exposed so chat (or any page) can open / refresh the audit programmatically.
  window.helpAuditOpen = function () { openPanel(); };
  window.helpAuditRefresh = function () {
    if (panel && panel.classList.contains('open')) runAudit({ silent: true });
  };
  window.helpAuditAttachmentChanged = function (hasAttachment) {
    if (hasAttachment) showLauncher();
    else { hideLauncher(); closePanel(); currentReport = null; }
  };

  // ── Utilities ───────────────────────────────────────────────────────────
  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }
  function escAttr(s) { return escapeHtml(s).replace(/"/g, '&quot;'); }

  // On first load: if the chat already has an attachment in localStorage,
  // show the launcher immediately.
  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => {
      const att = window.helpChatGetAttachment ? window.helpChatGetAttachment() : null;
      if (att) showLauncher();
    }, 100);
  });
})();
