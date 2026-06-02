// Dev Inspector — admin-only, dev-environment-only.
// Toggle with Ctrl+Shift+D. Hold Alt and hover any element to see its
// reference info (tag, id, classes, data-attrs, source landmarks).
// Alt+Click copies the reference to clipboard.

(function () {
  const STORAGE_KEY = 'icecold.devInspectorOn';

  // Tip element
  const tip = document.createElement('div');
  tip.id = 'dev-inspector-tip';
  Object.assign(tip.style, {
    position: 'fixed', zIndex: 999999, pointerEvents: 'none',
    background: '#0d1117', color: '#c9d1d9',
    border: '1px solid #58a6ff', borderRadius: '6px',
    padding: '8px 10px', fontFamily: 'ui-monospace,monospace',
    fontSize: '11px', lineHeight: '1.5', maxWidth: '460px',
    boxShadow: '0 6px 18px rgba(0,0,0,.5)', display: 'none',
    whiteSpace: 'pre-wrap', wordBreak: 'break-word',
  });
  document.body.appendChild(tip);

  // Status badge (shown when inspector is active)
  const badge = document.createElement('div');
  badge.id = 'dev-inspector-badge';
  Object.assign(badge.style, {
    position: 'fixed', top: '8px', left: '50%', transform: 'translateX(-50%)',
    zIndex: 999998,
    background: '#0d1117', color: '#58a6ff',
    border: '1px solid #58a6ff', borderRadius: '4px',
    padding: '4px 8px', fontFamily: 'ui-monospace,monospace',
    fontSize: '10px', cursor: 'pointer', display: 'none',
    letterSpacing: '.5px',
  });
  badge.title = 'Click to toggle dev inspector';
  badge.style.display = 'block';
  badge.addEventListener('click', () => setActive(!active));
  document.body.appendChild(badge);

  let active = localStorage.getItem(STORAGE_KEY) === '1';
  setActive(active);

  function setActive(on) {
    active = on;
    localStorage.setItem(STORAGE_KEY, on ? '1' : '0');
    if (on) {
      badge.style.background = '#0d1117';
      badge.style.borderColor = '#58a6ff';
      badge.style.color = '#58a6ff';
      badge.textContent = 'DEV INSPECTOR ON  -  Alt+hover  -  click to turn off';
    } else {
      badge.style.background = 'transparent';
      badge.style.borderColor = '#30363d';
      badge.style.color = '#6e7681';
      badge.textContent = 'dev inspector  -  click to turn on';
    }
    if (!on) tip.style.display = 'none';
  }

  // Ctrl+Shift+D toggle
  document.addEventListener('keydown', e => {
    if (e.ctrlKey && e.shiftKey && (e.key === 'D' || e.key === 'd')) {
      e.preventDefault();
      setActive(!active);
    }
    if (e.key === 'Escape') tip.style.display = 'none';
  });

  // Curated landmarks: walks up DOM matching known selectors.
  // Each entry: { match: selector, label: string, file: string }
  const LANDMARKS = [
    { match: 'tr.calc-grp-hdr',          label: 'Calculator BOM section header',         file: 'calculator.js renderBOMWithCosts' },
    { match: 'tr.bom-skin-row',          label: 'BOM row (linked to SKIN formula)',      file: 'calculator.js / admin_templates.js' },
    { match: 'tr.bom-taping-row',        label: 'BOM row (linked to TAPING block)',      file: 'calculator.js / admin_templates.js' },
    { match: 'tr.bom-floor-row',         label: 'BOM row (linked to FLOOR plate)',       file: 'calculator.js / admin_templates.js' },
    { match: 'tr.bom-cleat-row',         label: 'BOM row (linked to MOUNTING CLEAT)',    file: 'calculator.js / admin_templates.js' },
    { match: 'tr.calc-grp-row',          label: 'Calculator BOM row',                    file: 'calculator.js renderBOMWithCosts' },
    { match: '#bom-area',                label: 'Calculator BOM area',                   file: 'calculator.html' },
    { match: '#bom-wrap',                label: 'Admin Templates BOM table',             file: 'admin_templates.js renderBOM' },
    { match: '.parts-group-title',       label: 'Pre-cost BOM section header',           file: 'calculator.js renderBOM' },
    { match: '.parts-group',             label: 'Pre-cost BOM section',                  file: 'calculator.js renderBOM' },
    { match: '.assembly-item',           label: 'Pre-cost BOM item',                     file: 'calculator.js renderBOM' },
    { match: '#body-options-section',    label: 'Body Options panel',                    file: 'calculator.js renderBodyOptions / calculator.html' },
    { match: '#body-options-list',       label: 'Body Options list',                     file: 'calculator.js renderBodyOptions' },
    { match: '.nav-item',                label: 'Sidebar nav link',                      file: 'base.html' },
    { match: '#trailer-list',            label: 'Admin Templates body-type list',        file: 'admin_templates.html' },
    { match: '#trailer-select',          label: 'Calculator body-type dropdown',         file: 'calculator.html' },
    { match: '#cost-summary-section',    label: 'Calculator cost summary panel',         file: 'calculator.html' },
    { match: '.modal',                   label: 'Modal dialog',                          file: '(check id on the modal)' },
    { match: 'form',                     label: 'Form',                                  file: '(check id/action)' },
  ];

  // Walk up DOM and return up to N nearest "identifiable" ancestors
  // (anything with an id, a data-* attribute, or a non-trivial class).
  function ancestorTrail(el, limit) {
    const out = [];
    let cur = el.parentElement;
    while (cur && cur !== document.body && out.length < limit) {
      const id = cur.id ? `#${cur.id}` : '';
      const dataKeys = Object.keys(cur.dataset || {});
      const dataAttrs = dataKeys.length
        ? ' [' + dataKeys.map(k => 'data-' + k.replace(/[A-Z]/g, m => '-' + m.toLowerCase())).join(', ') + ']'
        : '';
      const classes = (typeof cur.className === 'string' ? cur.className : '')
        .split(/\s+/).filter(Boolean).slice(0, 3).map(c => '.' + c).join('');
      if (id || dataKeys.length || classes) {
        const tag = cur.tagName.toLowerCase();
        out.push(`${tag}${id}${classes}${dataAttrs}`);
      }
      cur = cur.parentElement;
    }
    return out;
  }

  function landmarkPath(el) {
    const path = [];
    let cur = el;
    while (cur && cur !== document.body) {
      for (const lm of LANDMARKS) {
        if (cur.matches(lm.match)) {
          const id = cur.id ? `#${cur.id}` : '';
          path.unshift(`${lm.label}${id}  →  ${lm.file}`);
          break;
        }
      }
      cur = cur.parentElement;
    }
    return path;
  }

  function describe(el) {
    const tag = el.tagName.toLowerCase();
    const id = el.id ? `#${el.id}` : '';
    const cls = el.className && typeof el.className === 'string'
      ? '.' + el.className.split(/\s+/).filter(Boolean).join('.') : '';
    const data = Object.entries(el.dataset || {})
      .filter(([k]) => !k.startsWith('skinItems') && !k.startsWith('skinName') && !k.startsWith('skinRegion'))
      .map(([k, v]) => `data-${k.replace(/[A-Z]/g, m => '-' + m.toLowerCase())}="${v}"`)
      .join(' ');
    const text = (el.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 60);
    const lm = landmarkPath(el);
    const trail = ancestorTrail(el, 5);
    return [
      `Element: ${tag}${id}${cls}`,
      data ? `Attrs:   ${data}` : null,
      text  ? `Text:    "${text}"` : null,
      lm.length    ? `\nLandmarks:\n  ${lm.join('\n  ')}` : null,
      trail.length ? `\nNearest ancestors (closest first):\n  ${trail.join('\n  ')}` : null,
      `\nAlt+click to copy this to clipboard`,
    ].filter(Boolean).join('\n');
  }

  document.addEventListener('mousemove', e => {
    if (!active || !e.altKey) {
      if (active && tip.style.display !== 'none') tip.style.display = 'none';
      return;
    }
    const target = e.target;
    if (!target || target === tip || target === badge) return;
    tip.textContent = describe(target);
    tip.style.display = 'block';
    const vw = window.innerWidth, vh = window.innerHeight;
    const tw = tip.offsetWidth + 16, th = tip.offsetHeight + 16;
    const x = e.clientX + 16 + tw > vw ? e.clientX - tw : e.clientX + 16;
    const y = e.clientY + 16 + th > vh ? e.clientY - th - 8 : e.clientY + 16;
    tip.style.left = x + 'px';
    tip.style.top  = y + 'px';
  });

  document.addEventListener('keyup', e => {
    if (!active) return;
    if (e.key === 'Alt') tip.style.display = 'none';
  });

  document.addEventListener('click', e => {
    if (!active || !e.altKey) return;
    e.preventDefault();
    e.stopPropagation();
    const text = describe(e.target);
    navigator.clipboard.writeText(text).then(() => {
      const orig = badge.textContent;
      badge.style.background = '#0d4429';
      badge.style.borderColor = '#3d9970';
      badge.style.color = '#3d9970';
      badge.textContent = '✓ Copied to clipboard';
      setTimeout(() => {
        badge.style.background = '#0d1117';
        badge.style.borderColor = '#58a6ff';
        badge.style.color = '#58a6ff';
        badge.textContent = orig;
      }, 1200);
    }).catch(() => {});
  }, true);
})();
