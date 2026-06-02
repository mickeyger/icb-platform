// Shared opt-in section state for EXTRAS / OPTIONAL EXTRAS (any
// bom_sections row with is_optional = 1). Loaded by both calculator.js
// (Costings 1) and calculator2.js (Costings 2) so the two pages share
// the same per-trailer state shape:
//
//   optsec_enabled_<tid>       — Set of bom_section_id that the user
//                                has ticked ON. Optional sections not in
//                                this set are greyed out + contribute 0.
//   optsec_row_excl_<page>_<tid> — Set of bom_id that the user has
//                                individually ticked OFF inside an
//                                enabled optional section. page = 'c1'
//                                or 'c2'. Costings 2 also keeps its
//                                existing _calc2Excl set for non-
//                                optional rows — the two are merged at
//                                payload time.

(function () {
  function _key(tid)             { return `optsec_enabled_${tid}`; }
  function _rowKey(tid, page)    { return `optsec_row_excl_${page}_${tid}`; }

  function loadEnabled(tid) {
    if (!tid) return new Set();
    try {
      const raw = localStorage.getItem(_key(tid));
      return new Set((raw ? JSON.parse(raw) : []).map(Number).filter(Number.isFinite));
    } catch (_) { return new Set(); }
  }
  function saveEnabled(tid, set) {
    if (!tid) return;
    try { localStorage.setItem(_key(tid), JSON.stringify([...set])); } catch (_) {}
  }
  function loadRowExcl(tid, page) {
    if (!tid) return new Set();
    try {
      const raw = localStorage.getItem(_rowKey(tid, page));
      return new Set((raw ? JSON.parse(raw) : []).map(Number).filter(Number.isFinite));
    } catch (_) { return new Set(); }
  }
  function saveRowExcl(tid, page, set) {
    if (!tid) return;
    try { localStorage.setItem(_rowKey(tid, page), JSON.stringify([...set])); } catch (_) {}
  }

  // Walk the items list and return every bom_id that should be treated as
  // excluded because of the optional-section layer — either the section is
  // not enabled, or the section is enabled but the row is individually
  // ticked off. Items in non-optional sections are never added.
  function compute(items, tid, page) {
    const enabled = loadEnabled(tid);
    const rowExcl = loadRowExcl(tid, page);
    const out = new Set();
    (items || []).forEach(it => {
      if (!it || !it.section_is_optional) return;
      const sid = it.bom_section_id;
      if (sid == null) return;
      if (!enabled.has(+sid)) {
        if (it.bom_id != null) out.add(+it.bom_id);
        return;
      }
      if (it.bom_id != null && rowExcl.has(+it.bom_id)) {
        out.add(+it.bom_id);
      }
    });
    return out;
  }

  // Master header toggle: unticked means "include everything in this section",
  // checked means "exclude everything in this section" — the same semantics as
  // SRD/DRD in Calculator 2. We still keep the enabled-set for backward
  // compatibility with compute(), but "OFF" now also writes every row into the
  // per-row exclusion set so the first row untick can promote the section into
  // a partial (indeterminate) state.
  function toggleSection(tid, page, sectionId, allBomIdsInSection, enabled) {
    if (!tid || sectionId == null) return;
    const enSet = loadEnabled(tid);
    const exSet = loadRowExcl(tid, page);
    const ids = Array.isArray(allBomIdsInSection) ? allBomIdsInSection.map(Number).filter(Number.isFinite) : [];
    if (enabled) {
      enSet.add(+sectionId);
      ids.forEach(id => exSet.delete(+id));
    } else {
      enSet.delete(+sectionId);
      ids.forEach(id => exSet.add(+id));
    }
    saveEnabled(tid, enSet);
    saveRowExcl(tid, page, exSet);
  }

  function toggleRow(tid, page, sectionId, allBomIdsInSection, bomId, excluded) {
    if (!tid || bomId == null) return;
    const ids = Array.isArray(allBomIdsInSection) ? allBomIdsInSection.map(Number).filter(Number.isFinite) : [];
    const exSet = loadRowExcl(tid, page);
    const enSet = loadEnabled(tid);
    const sid = sectionId != null ? +sectionId : null;
    const wasEnabled = sid != null && enSet.has(sid);
    // Fresh disabled sections historically persisted as:
    //   enabled = false, rowExcl = []
    // Seed every row as excluded before including the clicked one so the
    // first untick produces a partial state instead of waking the whole section.
    if (!excluded && sid != null && !wasEnabled && ids.length) {
      ids.forEach(id => exSet.add(+id));
    }
    if (excluded) exSet.add(+bomId);
    else          exSet.delete(+bomId);
    if (sid != null) {
      if (!excluded) {
        enSet.add(sid);
      }
      if (ids.length) {
        const allExcluded = ids.every(id => exSet.has(+id));
        if (allExcluded) enSet.delete(sid);
        else             enSet.add(sid);
      }
    }
    saveEnabled(tid, enSet);
    saveRowExcl(tid, page, exSet);
  }

  // Bulk select/deselect every row in an optional section.
  // selectAll=true  → clear all matching bom_ids from the excl set (= included)
  // selectAll=false → add all matching bom_ids to the excl set    (= excluded)
  function bulkRows(tid, page, sectionId, bomIds, selectAll) {
    if (!tid || !Array.isArray(bomIds)) return;
    const exSet = loadRowExcl(tid, page);
    const enSet = loadEnabled(tid);
    bomIds.forEach(id => {
      if (selectAll) exSet.delete(+id);
      else           exSet.add(+id);
    });
    if (sectionId != null) {
      if (selectAll) enSet.add(+sectionId);
      else           enSet.delete(+sectionId);
    }
    saveEnabled(tid, enSet);
    saveRowExcl(tid, page, exSet);
  }

  window.OptionalSections = {
    loadEnabled, saveEnabled,
    loadRowExcl, saveRowExcl,
    compute, toggleSection, toggleRow, bulkRows,
  };
})();
