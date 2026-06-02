/* ── AI Help Assistant ──────────────────────────────────────────────────── */
/* Floating launcher + chat panel. Streams replies from /api/help/chat over   */
/* fetch + ReadableStream (we manually parse SSE lines).                      */

(function () {
  'use strict';

  // Skip entirely if there's no logged-in user (no help button to render).
  // Server-side base.html only renders the markup for logged-in users; if
  // the elements aren't there, no-op.
  if (!document.getElementById('help-launcher')) return;

  const launcher  = document.getElementById('help-launcher');
  const panel     = document.getElementById('help-panel');
  const closeBtn  = document.getElementById('help-close');
  const clearBtn  = document.getElementById('help-clear');
  const msgsEl    = document.getElementById('help-messages');
  const suggEl    = document.getElementById('help-suggestions');
  const input     = document.getElementById('help-input');
  const sendBtn   = document.getElementById('help-send');
  const attachBtn = document.getElementById('help-attach');
  const fileInput = document.getElementById('help-file-input');
  const chipEl    = document.getElementById('help-attachment-chip');
  const suggestToggle = document.getElementById('help-suggest-toggle');

  // ── UI-action opt-in (persisted) ──────────────────────────────────────
  let suggestActions = false;
  try { suggestActions = localStorage.getItem('helpchat:suggest_actions:v1') === '1'; } catch (_) {}
  if (suggestToggle) {
    suggestToggle.checked = suggestActions;
    suggestToggle.addEventListener('change', () => {
      suggestActions = !!suggestToggle.checked;
      try { localStorage.setItem('helpchat:suggest_actions:v1', suggestActions ? '1' : '0'); } catch (_) {}
    });
  }

  // Conversation memory — text-only history sent back to the server each turn.
  // Persisted to localStorage so the conversation survives page reloads and
  // is shared across tabs in the same browser.
  const STORAGE_KEY = 'helpchat:history:v1';
  const ATTACH_KEY  = 'helpchat:attachment:v1';
  const HISTORY_CAP = 50;        // hard cap on stored messages
  const HISTORY_MAX_AGE_DAYS = 14;

  /** @type {{role:'user'|'assistant', content:string, ts:number}[]} */
  let history = loadHistory();
  /** @type {{upload_id:string, filename:string, sheets:string[], sheet:string} | null} */
  let attachment = loadAttachment();
  let streaming = false;

  function loadHistory() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      const cutoff = Date.now() - HISTORY_MAX_AGE_DAYS * 86400 * 1000;
      return parsed
        .filter(m => m && typeof m.content === 'string' && (m.role === 'user' || m.role === 'assistant'))
        .filter(m => !m.ts || m.ts >= cutoff)
        .slice(-HISTORY_CAP);
    } catch (_) { return []; }
  }
  function saveHistory() {
    try {
      const trimmed = history.slice(-HISTORY_CAP);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
    } catch (_) { /* quota or disabled — silent */ }
  }
  function clearHistory() {
    history.length = 0;
    try { localStorage.removeItem(STORAGE_KEY); } catch (_) {}
  }

  // ── Attachment state ────────────────────────────────────────────────────
  function loadAttachment() {
    try {
      const raw = localStorage.getItem(ATTACH_KEY);
      if (!raw) return null;
      const a = JSON.parse(raw);
      if (a && a.upload_id && a.filename && Array.isArray(a.sheets) && a.sheet) return a;
    } catch (_) {}
    return null;
  }
  function saveAttachment() {
    try {
      if (attachment) localStorage.setItem(ATTACH_KEY, JSON.stringify(attachment));
      else localStorage.removeItem(ATTACH_KEY);
    } catch (_) {}
    // Notify the audit panel (if loaded) so it can show / hide its launcher.
    if (window.helpAuditAttachmentChanged) {
      try { window.helpAuditAttachmentChanged(!!attachment); } catch (_) {}
    }
  }

  // Public helpers used by help_audit.js and other page scripts.
  function currentAttachmentRef() {
    return attachment ? { upload_id: attachment.upload_id, sheet: attachment.sheet,
                          filename: attachment.filename, sheets: attachment.sheets } : null;
  }
  window.helpChatGetAttachment = currentAttachmentRef;
  // Update the picked sheet on the current attachment. Used by the Excel
  // Audit panel when the user changes the body dropdown — we re-pick the
  // closest matching sheet without forcing the user to do it manually.
  // Returns true if updated, false if no current attachment or sheet not in
  // the attachment's sheet list.
  window.helpChatSetAttachmentSheet = function (sheetName) {
    if (!attachment || !sheetName) return false;
    if (!Array.isArray(attachment.sheets) || !attachment.sheets.includes(sheetName)) return false;
    if (attachment.sheet === sheetName) return true;
    attachment.sheet = sheetName;
    saveAttachment();
    renderChip();
    return true;
  };
  // Send a message into the chat programmatically. opts.showInChat lets the
  // caller display a friendlier short label in the chat UI (rendered as the
  // user bubble) instead of the full structured prompt.
  window.helpChatSend = function (text, opts) {
    opts = opts || {};
    if (!text) return;
    // Open the panel so the user sees the reply.
    panel.classList.add('open');
    if (opts.showInChat) {
      hideSuggestions();
      appendMsg('user', opts.showInChat);
      // Push the structured text into the input + send. The user-bubble has
      // already been appended manually so we don't want send() to duplicate
      // it — set a flag the send() path can read.
      _userBubblePrepainted = true;
    }
    input.value = text;
    send();
  };
  let _userBubblePrepainted = false;
  async function detachAttachment(serverDelete = true) {
    if (!attachment) { renderChip(); return; }
    const id = attachment.upload_id;
    attachment = null;
    saveAttachment();
    renderChip();
    if (serverDelete) {
      try {
        await fetch('/api/help/attachment/' + encodeURIComponent(id), {
          method: 'DELETE',
          credentials: 'same-origin',
          headers: { 'X-CSRF-Token': _csrf() },
        });
      } catch (_) { /* best-effort */ }
    }
  }
  function renderChip() {
    if (!chipEl) return;
    if (!attachment) {
      chipEl.innerHTML = '';
      chipEl.classList.add('hidden');
      return;
    }
    chipEl.classList.remove('hidden');
    // Build a small chip with the filename, sheet dropdown, and detach button.
    chipEl.innerHTML = '';
    const icon = document.createElement('span');
    icon.textContent = '📎';
    icon.className = 'help-chip-icon';
    chipEl.appendChild(icon);

    const name = document.createElement('span');
    name.className = 'help-chip-name';
    name.textContent = attachment.filename;
    name.title = attachment.filename;
    chipEl.appendChild(name);

    const sep = document.createElement('span');
    sep.textContent = 'sheet:';
    sep.className = 'help-chip-label';
    chipEl.appendChild(sep);

    const sel = document.createElement('select');
    sel.className = 'help-chip-select';
    attachment.sheets.forEach(s => {
      const opt = document.createElement('option');
      opt.value = s; opt.textContent = s;
      if (s === attachment.sheet) opt.selected = true;
      sel.appendChild(opt);
    });
    sel.addEventListener('change', () => {
      attachment.sheet = sel.value;
      saveAttachment();
    });
    chipEl.appendChild(sel);

    const x = document.createElement('button');
    x.type = 'button';
    x.className = 'help-chip-x';
    x.textContent = '✕';
    x.title = 'Detach workbook';
    x.addEventListener('click', () => detachAttachment(true));
    chipEl.appendChild(x);
  }

  // ── Configuration check on first open ───────────────────────────────────
  let configured = null;   // null = unchecked, true/false = result
  async function checkConfigured() {
    if (configured !== null) return configured;
    try {
      const r = await fetch('/api/help/health', { credentials: 'same-origin' });
      if (!r.ok) { configured = false; return false; }
      const data = await r.json();
      configured = !!data.configured;
    } catch (_) { configured = false; }
    if (!configured) launcher.classList.add('hidden');
    return configured;
  }

  // Hide the launcher until we confirm the server has an API key. This
  // avoids a button that's visible but errors on click.
  launcher.classList.add('hidden');
  checkConfigured().then(ok => {
    if (ok) launcher.classList.remove('hidden');
  });

  // ── Open / close panel ──────────────────────────────────────────────────
  function openPanel() {
    panel.classList.add('open');
    if (msgsEl.children.length === 0) {
      // First open this page-load — replay any saved conversation, then
      // show the suggestions only if there's nothing to replay.
      if (history.length === 0) {
        renderSuggestions();
      } else {
        replayHistory();
        hideSuggestions();
      }
    }
    setTimeout(() => input.focus(), 200);
  }
  function closePanel() { panel.classList.remove('open'); }
  launcher.addEventListener('click', openPanel);
  closeBtn.addEventListener('click', closePanel);
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && panel.classList.contains('open')) closePanel();
  });

  clearBtn.addEventListener('click', () => {
    clearHistory();
    detachAttachment(true);   // dropping chat also drops the workbook
    msgsEl.innerHTML = '';
    renderSuggestions();
  });

  function replayHistory() {
    for (const m of history) {
      const el = appendMsg(m.role === 'user' ? 'user' : 'assistant', m.content);
      // Re-render any action buttons that were attached to this message.
      if (m.role === 'assistant' && m.actions && Array.isArray(m.actions.actions)) {
        try { renderActions(el, m.actions); } catch (_) {}
      }
    }
  }

  // ── Suggested starter questions ─────────────────────────────────────────
  // Special-action suggestions (handler invoked instead of sending as a chat
  // message). Plain string suggestions are sent as questions.
  const SUGGESTIONS = [
    { label: '📊 Load costing sheet from Excel for comparison to live costing',
      action: 'load_excel_audit' },
    'How do I add BOM items to a body type?',
    'How do I update a price in a costing?',
    'How do I create a new body type?',
  ];
  function renderSuggestions() {
    suggEl.innerHTML = '';
    SUGGESTIONS.forEach(item => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'help-suggestion';
      if (typeof item === 'string') {
        b.textContent = item;
        b.addEventListener('click', () => { input.value = item; send(); });
      } else {
        b.textContent = item.label;
        if (item.action === 'load_excel_audit') {
          b.classList.add('help-suggestion-primary');
          b.addEventListener('click', startExcelAuditFlow);
        }
      }
      suggEl.appendChild(b);
    });
    suggEl.style.display = '';
  }
  function hideSuggestions() { suggEl.style.display = 'none'; }

  // Trigger the same flow as clicking the 📎 paperclip, then open the Audit
  // panel as soon as the file is parsed.
  function startExcelAuditFlow() {
    if (!fileInput) return;
    // One-shot listener: after the file is picked + attached, open the audit
    // panel. The fileInput change handler does the upload and persists the
    // attachment; we just need to react when that finishes.
    const once = setInterval(() => {
      const att = currentAttachmentRef();
      if (att) {
        clearInterval(once);
        if (window.helpAuditOpen) window.helpAuditOpen();
      }
    }, 300);
    // Safety timeout — give up watching after 60s.
    setTimeout(() => clearInterval(once), 60000);
    fileInput.click();
  }

  // ── Page context capture ────────────────────────────────────────────────
  function getPageContext() {
    // Base: server-rendered hint from the page (if any).
    let ctx = { page: window.location.pathname };
    const el = document.getElementById('help-page-context');
    if (el) {
      try { ctx = Object.assign(ctx, JSON.parse(el.textContent || '{}')); }
      catch (_) { /* keep defaults */ }
    }
    // Live overlay: the calculator publishes window.helpContext on every run.
    // Merge it in (live wins), so the AI sees the actual on-screen BOM.
    if (window.helpContext && typeof window.helpContext === 'object') {
      const overlay = Object.assign({}, window.helpContext);
      // The full calc result carries body_variables, formula_library_resolved,
      // global_variables, etc. that the reconciliation engine doesn't use and
      // that easily push the page-context payload past the server's size cap.
      // Slim to just what's needed.
      if (overlay.liveResult) overlay.liveResult = _slimLiveResult(overlay.liveResult);
      ctx = Object.assign(ctx, overlay);
    }
    // Opt-in flag for the AI's propose_actions tool. Persisted in localStorage
    // via the header toggle.
    ctx.suggest_actions = !!suggestActions;
    return ctx;
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
      items: items,
      category_totals:    r.category_totals || null,
      grand_total:        r.grand_total ?? null,
      cost_per_sqm:       r.cost_per_sqm ?? null,
      geometry:           r.geometry || null,
      markup_percentage:  r.markup_percentage ?? null,
    };
  }

  // ── Message rendering ───────────────────────────────────────────────────
  function appendMsg(role, text, opts) {
    const el = document.createElement('div');
    el.className = 'help-msg help-msg-' + role;
    if (opts && opts.streaming) el.classList.add('help-msg-streaming');
    if (opts && opts.tool)      el.classList.add('help-msg-tool');
    if (opts && opts.error)     el.classList.add('help-msg-error');
    el.textContent = text;
    msgsEl.appendChild(el);
    msgsEl.scrollTop = msgsEl.scrollHeight;
    return el;
  }

  function appendToolNote(name) {
    appendMsg('assistant', 'looking up: ' + name + '…', { tool: true });
  }

  function appendLoadingBubble() {
    const el = document.createElement('div');
    el.className = 'help-msg help-msg-assistant help-msg-loading';
    el.innerHTML =
      '<span class="help-spinner" aria-hidden="true"></span>' +
      '<span class="help-loading-label">Thinking…</span>';
    msgsEl.appendChild(el);
    msgsEl.scrollTop = msgsEl.scrollHeight;
    return el;
  }

  // ── UI-action buttons (rendered under an assistant message) ─────────────
  function renderActions(assistantEl, payload) {
    const actions = Array.isArray(payload.actions) ? payload.actions : [];
    if (!actions.length) return;
    const wrap = document.createElement('div');
    wrap.className = 'help-actions';
    if (payload.intro) {
      const intro = document.createElement('div');
      intro.className = 'help-actions-intro';
      intro.textContent = payload.intro;
      wrap.appendChild(intro);
    }
    const row = document.createElement('div');
    row.className = 'help-actions-row';
    actions.forEach(act => {
      if (!act || !act.type || !act.label) return;
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'help-action-btn';
      btn.textContent = act.label;
      btn.addEventListener('click', () => executeAction(act, btn));
      row.appendChild(btn);
    });
    wrap.appendChild(row);
    // Attach under the assistant message if there is one, else just append.
    const anchor = assistantEl || msgsEl.lastElementChild || msgsEl;
    if (anchor === msgsEl) msgsEl.appendChild(wrap);
    else if (anchor.parentNode) anchor.parentNode.insertBefore(wrap, anchor.nextSibling);
    msgsEl.scrollTop = msgsEl.scrollHeight;
  }

  function executeAction(act, btn) {
    const handlers = (window.helpActionHandlers || {});
    const params = act.params || {};
    let handled = false;
    let needsCalculator = false;
    try {
      if (act.type === 'navigate' && typeof params.path === 'string') {
        // Close the panel first so the user lands on the new page cleanly.
        if (panel) panel.classList.remove('open');
        window.location.assign(params.path);
        handled = true;
      } else if (typeof handlers[act.type] === 'function') {
        const r = handlers[act.type](params);
        handled = (r !== false);
        // highlight_bom_lines returns true even when no rows matched (so the
        // user gets the toast and console log) — but if the calculator isn't
        // on screen at all (#bom-area missing) we want to point them there.
        if (act.type === 'highlight_bom_lines' && !document.getElementById('bom-area')) {
          needsCalculator = true;
        }
      } else {
        // Built-in fallback for highlight_element / scroll_to using a shared
        // target → selector map (so it works on every page, not just calculator).
        if (act.type === 'highlight_element' || act.type === 'scroll_to') {
          const sel = _builtInTargets[params.target];
          const el = sel ? document.querySelector(sel) : null;
          if (el) {
            el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            if (act.type === 'highlight_element') _flash(el);
            handled = true;
          }
        }
      }
    } catch (_) { /* swallow */ }
    if (needsCalculator) {
      if (window.confirmModal) {
        confirmModal('You need a costing on screen for this. Open the Cost Calculator?', { okText: 'Open' })
          .then(ok => { if (ok) { if (panel) panel.classList.remove('open'); window.location.assign('/calculator'); } });
      } else if (window.toast) {
        toast('Open the Cost Calculator first, then click this again.', 'warn');
      }
    } else if (!handled && window.toast) {
      toast('That action only works on certain pages.', 'warn');
    }
    // Buttons stay enabled — the user may want to re-trigger after navigating
    // back, re-running a calc, etc. Just give a brief visual cue.
    if (btn) {
      btn.classList.add('help-action-clicked');
      setTimeout(() => btn.classList.remove('help-action-clicked'), 800);
    }
  }

  // Default target → selector mapping. Pages can override by registering
  // window.helpActionHandlers.highlight_element / scroll_to with custom logic.
  const _builtInTargets = {
    'bom-area':            '#bom-area, #bom-results, [data-help-target="bom-area"]',
    'chassis-dropdown':    '#chassis-select, [data-help-target="chassis-dropdown"]',
    'body-dropdown':       '#trailer-select, [data-help-target="body-dropdown"]',
    'dimensions-section':  '#dimensions-section, [data-help-target="dimensions-section"]',
    'totals-section':      '#totals-section, .grand-total-row, [data-help-target="totals-section"]',
    'save-button':         '#save-costing-btn, [data-help-target="save-button"]',
    'quote-pdf-button':    '#quote-pdf-btn, [data-help-target="quote-pdf-button"]',
    'help-attach-button':  '#help-attach',
  };

  function _flash(el) {
    if (!el || !el.classList) return;
    el.classList.add('help-flash');
    setTimeout(() => el.classList.remove('help-flash'), 5100);
  }

  // ── SSE consumer ────────────────────────────────────────────────────────
  function _csrf() {
    return document.querySelector('meta[name="csrf-token"]')?.content || '';
  }

  async function send() {
    if (streaming) return;
    const message = (input.value || '').trim();
    if (!message) return;

    if (!await checkConfigured()) {
      appendMsg('assistant', 'Help is not configured on this server.', { error: true });
      return;
    }

    hideSuggestions();
    // Skip the user bubble if helpChatSend() already painted a friendly label.
    if (!_userBubblePrepainted) appendMsg('user', message);
    _userBubblePrepainted = false;
    history.push({ role: 'user', content: message, ts: Date.now() });
    saveHistory();
    input.value = '';
    input.style.height = '';
    streaming = true;
    sendBtn.disabled = true;
    input.disabled = true;

    let assistantEl = null;
    let assistantText = '';
    let pendingActions = null;  // captured from `actions` SSE event for history persistence
    let loadingEl = appendLoadingBubble();
    const _clearLoading = () => {
      if (loadingEl && loadingEl.parentNode) loadingEl.parentNode.removeChild(loadingEl);
      loadingEl = null;
    };

    const pageCtx = getPageContext();

    try {
      const res = await fetch('/api/help/chat', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': _csrf(),
          'Accept': 'text/event-stream',
        },
        body: JSON.stringify({
          message: message,
          history: history.slice(0, -1),  // exclude the just-pushed message
          page_context: pageCtx,
          attachment: attachment ? { upload_id: attachment.upload_id, sheet: attachment.sheet } : null,
        }),
      });

      if (!res.ok) {
        let detail = 'HTTP ' + res.status;
        try { const j = await res.json(); detail = j.detail || detail; } catch (_) {}
        _clearLoading();
        appendMsg('assistant', detail, { error: true });
        if (res.status === 429) {
          if (window.toast) toast(detail, 'warn');
        }
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';

      // SSE frames: blank-line-separated; each line is "event:" or "data:"
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });

        // SSE frame separator can be LF-LF or CRLF-CRLF depending on server.
        // sse_starlette emits CRLF, so split on the first match of either.
        let m;
        while ((m = buf.match(/\r?\n\r?\n/))) {
          const frame = buf.slice(0, m.index);
          buf = buf.slice(m.index + m[0].length);
          const ev = parseSSEFrame(frame);
          if (!ev) continue;

          if (ev.event === 'token') {
            _clearLoading();
            if (!assistantEl) assistantEl = appendMsg('assistant', '', { streaming: true });
            const txt = (ev.data && ev.data.text) || '';
            assistantText += txt;
            assistantEl.textContent = assistantText;
            msgsEl.scrollTop = msgsEl.scrollHeight;
          } else if (ev.event === 'tool') {
            _clearLoading();
            appendToolNote(ev.data && ev.data.name);
          } else if (ev.event === 'error') {
            const msg = (ev.data && ev.data.message) || 'Something went wrong.';
            if (assistantEl) assistantEl.classList.remove('help-msg-streaming');
            _clearLoading();
            appendMsg('assistant', msg, { error: true });
          } else if (ev.event === 'actions') {
            _clearLoading();
            try {
              pendingActions = ev.data || null;
              renderActions(assistantEl, pendingActions || {});
            } catch (e) { /* never let action rendering break the chat */ }
          } else if (ev.event === 'done') {
            if (assistantEl) assistantEl.classList.remove('help-msg-streaming');
            _clearLoading();
          }
        }
      }
    } catch (err) {
      _clearLoading();
      appendMsg('assistant', 'Connection failed: ' + (err && err.message || err), { error: true });
    } finally {
      _clearLoading();
      if (assistantEl) assistantEl.classList.remove('help-msg-streaming');
      if (assistantText) {
        const entry = { role: 'assistant', content: assistantText, ts: Date.now() };
        if (pendingActions && Array.isArray(pendingActions.actions) && pendingActions.actions.length) {
          entry.actions = pendingActions;
        }
        history.push(entry);
        saveHistory();
      }
      streaming = false;
      sendBtn.disabled = false;
      input.disabled = false;
      input.focus();
    }
  }

  function parseSSEFrame(frame) {
    if (!frame) return null;
    let event = 'message';
    const dataLines = [];
    // Tolerate both \n and \r\n line endings.
    for (const rawLine of frame.split(/\r?\n/)) {
      const line = rawLine;
      if (!line || line.startsWith(':')) continue;  // skip SSE comments / keepalives
      if (line.startsWith('event:')) event = line.slice(6).trim();
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
    }
    const dataStr = dataLines.join('\n');
    let data = null;
    if (dataStr) {
      try { data = JSON.parse(dataStr); } catch (_) { data = dataStr; }
    }
    return { event, data };
  }

  // ── Input behaviour ─────────────────────────────────────────────────────
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  input.addEventListener('input', () => {
    // Auto-grow up to max-height (CSS cap kicks in past that)
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 120) + 'px';
  });
  sendBtn.addEventListener('click', send);

  // ── Excel-attachment paperclip ──────────────────────────────────────────
  if (attachBtn && fileInput) {
    attachBtn.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', async () => {
      const file = fileInput.files && fileInput.files[0];
      fileInput.value = '';  // allow re-picking the same file later
      if (!file) return;

      const sizeMB = file.size / (1024 * 1024);
      if (sizeMB > 5) {
        if (window.toast) toast('File too large (max 5 MB).', 'warn');
        return;
      }
      const ext = (file.name || '').toLowerCase().match(/\.(xlsx|xls)$/);
      if (!ext) {
        if (window.toast) toast('Only .xlsx or .xls files are supported.', 'warn');
        return;
      }

      // Hint the server which body the user is on so it can auto-pick a sheet.
      const ctx = getPageContext();
      const bodyHint = ctx && ctx.body ? '?body=' + encodeURIComponent(ctx.body) : '';

      const fd = new FormData();
      fd.append('file', file);

      attachBtn.disabled = true;
      const stopBusy = window.showBusy ? showBusy(attachBtn, '…') : (() => { attachBtn.disabled = false; });

      try {
        const res = await fetch('/api/help/attachment' + bodyHint, {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'X-CSRF-Token': _csrf() },
          body: fd,
        });
        if (!res.ok) {
          let detail = 'Upload failed (HTTP ' + res.status + ')';
          try { const j = await res.json(); detail = j.detail || detail; } catch (_) {}
          if (window.toast) toast(detail, 'warn');
          return;
        }
        const data = await res.json();
        // Drop any previous attachment so we don't orphan files server-side.
        if (attachment && attachment.upload_id !== data.upload_id) {
          await detachAttachment(true);
        }
        attachment = {
          upload_id: data.upload_id,
          filename:  data.filename,
          sheets:    data.sheets || [],
          sheet:     data.picked_sheet || (data.sheets && data.sheets[0]) || '',
        };
        saveAttachment();
        renderChip();
        if (window.toast) toast('Attached. The next question will compare against this sheet.', 'success');
      } catch (err) {
        if (window.toast) toast('Upload failed: ' + (err && err.message || err), 'warn');
      } finally {
        try { stopBusy(); } catch (_) {}
        attachBtn.disabled = false;
      }
    });
  }

  // Restore the chip from localStorage on first load.
  renderChip();
})();
