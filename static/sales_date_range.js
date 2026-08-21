/**
 * Dual-month date range picker (Analytics / Report topbar).
 * Usage: SalesDateRangePicker.init({ wrapId, formId, ... });
 * Pass singleDay: true for one-day selection (from == to).
 */
(function (global) {
  function positionPanel(trigger, panel, opts) {
    if (!trigger || !panel) return;
    opts = opts || {};
    const gap = opts.gap != null ? opts.gap : 8;
    const margin = opts.margin != null ? opts.margin : 12;
    const vv = window.visualViewport;
    const viewW = (vv && vv.width) || window.innerWidth || document.documentElement.clientWidth || 0;
    const viewH = (vv && vv.height) || window.innerHeight || document.documentElement.clientHeight || 0;
    const offsetLeft = (vv && vv.offsetLeft) || 0;
    const offsetTop = (vv && vv.offsetTop) || 0;
    const maxPanelH = Math.max(180, viewH - margin * 2);

    panel.style.position = 'fixed';
    panel.style.right = 'auto';
    panel.style.bottom = 'auto';
    panel.style.maxHeight = Math.round(maxPanelH) + 'px';
    panel.style.overflowY = 'auto';
    panel.style.visibility = 'hidden';
    panel.style.display = 'flex';
    panel.style.flexDirection = 'column';

    const panelW = panel.offsetWidth;
    const panelH = Math.min(panel.offsetHeight, maxPanelH);
    const rect = trigger.getBoundingClientRect();

    let top = rect.bottom + gap;
    let left = rect.left;

    if (left + panelW > offsetLeft + viewW - margin) {
      left = Math.max(offsetLeft + margin, offsetLeft + viewW - margin - panelW);
    }
    if (left < offsetLeft + margin) left = offsetLeft + margin;

    if (top + panelH > offsetTop + viewH - margin) {
      const above = rect.top - gap - panelH;
      top = above >= offsetTop + margin
        ? above
        : Math.max(offsetTop + margin, offsetTop + viewH - margin - panelH);
    }
    if (top < offsetTop + margin) top = offsetTop + margin;

    panel.style.top = Math.round(top) + 'px';
    panel.style.left = Math.round(left) + 'px';
    panel.style.visibility = '';
  }

  function clearPanelPosition(panel) {
    if (!panel) return;
    panel.style.top = '';
    panel.style.left = '';
    panel.style.right = '';
    panel.style.bottom = '';
    panel.style.maxHeight = '';
    panel.style.overflowY = '';
    panel.style.visibility = '';
    panel.style.display = '';
    panel.style.flexDirection = '';
  }

  function init(cfg) {
    const wrap = document.getElementById(cfg.wrapId);
    if (!wrap) return;
    const chip = wrap.closest('.se-filter-chip') || wrap.parentElement || wrap;
    const page = wrap.closest('.de-main-inner') || wrap;
    function pick(id) {
      if (!id) return null;
      try {
        var sel = '#' + id;
        return (
          chip.querySelector(sel) ||
          wrap.querySelector(sel) ||
          page.querySelector(sel) ||
          document.getElementById(id)
        );
      } catch (err) {
        return document.getElementById(id);
      }
    }
    const trigger = pick(cfg.triggerId);
    const backdrop = pick(cfg.backdropId);
    const panel = pick(cfg.panelId);
    const display = pick(cfg.displayId);
    // Prefer the enclosing form: pick() looks inside the chip first and can miss
    // the filter form on pages that use .de-main-wrapper instead of .de-main-inner.
    const form =
      (cfg.formId && wrap.closest('#' + cfg.formId)) ||
      wrap.closest('form') ||
      (cfg.formId ? pick(cfg.formId) : null);
    const ff =
      pick(cfg.fromInputId) ||
      (form && cfg.fromInputId && form.querySelector('#' + cfg.fromInputId));
    const ft =
      pick(cfg.toInputId) ||
      (form && cfg.toInputId && form.querySelector('#' + cfg.toInputId));
    const cancelBtn = pick(cfg.cancelId);
    const applyBtn = pick(cfg.applyId);
    const btnPrev = pick(cfg.prevId);
    const btnNext = pick(cfg.nextId);
    const title0 = pick(cfg.title0Id);
    const title1 = pick(cfg.title1Id);
    const grid0 = pick(cfg.grid0Id);
    const grid1 = pick(cfg.grid1Id);
    const hasApplyHook = typeof cfg.onApply === 'function';
    if (
      !wrap ||
      !trigger ||
      !panel ||
      !display ||
      !ff ||
      !ft ||
      !btnPrev ||
      !btnNext ||
      !title0 ||
      !title1 ||
      !grid0 ||
      !grid1 ||
      (!form && !hasApplyHook)
    ) {
      return;
    }
    // Soft-nav runs page scripts, then deWorkspaceReinit may call init again on the
    // same nodes. A second click handler toggles open→close in one click.
    if (wrap.getAttribute('data-sdr-bound') === '1') return;
    wrap.setAttribute('data-sdr-bound', '1');

    const maxDateStr = (wrap.getAttribute('data-max-date') || '').trim();
    const monthLong = [
      'January',
      'February',
      'March',
      'April',
      'May',
      'June',
      'July',
      'August',
      'September',
      'October',
      'November',
      'December',
    ];

    function pad(n) {
      return n < 10 ? '0' + n : '' + n;
    }
    function toIso(y, m0, d) {
      return y + '-' + pad(m0 + 1) + '-' + pad(d);
    }
    function parseISO(s) {
      if (!s || !/^\d{4}-\d{2}-\d{2}$/.test(s)) return null;
      const p = s.split('-').map(Number);
      return { y: p[0], mo: p[1], d: p[2], t: new Date(p[0], p[1] - 1, p[2], 12, 0, 0) };
    }
    const maxParsed = parseISO(maxDateStr);
    const maxDateObj = maxParsed ? maxParsed.t : null;

    let selFrom = ff.value || '';
    let selTo = ft.value || '';
    const singleDay = !!(cfg.singleDay || cfg.mode === 'single');
    if (singleDay && selFrom) {
      selTo = selFrom;
      if (ft) ft.value = selFrom;
    }
    const now = new Date();
    let viewY = now.getFullYear();
    let viewM = now.getMonth();
    let openSnapshot = { from: '', to: '' };

    const initAnchor = parseISO(ff.value || maxDateStr);
    if (initAnchor) {
      viewY = initAnchor.y;
      viewM = initAnchor.mo - 1;
    }

    function fmt(iso) {
      if (!iso || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return '—';
      const p = parseISO(iso);
      return p.d + ' ' + monthLong[p.mo - 1] + ' ' + String(p.y).slice(-2);
    }
    function compareIso(a, b) {
      if (!a || !b) return 0;
      return a < b ? -1 : a > b ? 1 : 0;
    }
    function fmtRange(from, to) {
      if (!from || !to) return '—';
      const a = parseISO(from);
      const b = parseISO(to);
      if (!a || !b) return '—';
      let lo = from;
      let hi = to;
      if (compareIso(lo, hi) > 0) {
        lo = to;
        hi = from;
      }
      const x = parseISO(lo);
      const y = parseISO(hi);
      if (lo === hi) return fmt(lo);
      if (x.y === y.y && x.mo === y.mo) {
        return x.d + ' – ' + y.d + ' ' + monthLong[x.mo - 1] + ' ' + String(x.y).slice(-2);
      }
      if (x.y === y.y) {
        return x.d + ' ' + monthLong[x.mo - 1] + ' – ' + y.d + ' ' + monthLong[y.mo - 1] + ' ' + String(x.y).slice(-2);
      }
      return fmt(lo) + ' – ' + fmt(hi);
    }
    function refreshTriggerText() {
      if (singleDay) {
        if (selFrom) display.textContent = fmt(selFrom);
        else display.textContent = cfg.emptyLabel || 'Select date…';
        return;
      }
      if (selFrom && selTo) display.textContent = fmtRange(selFrom, selTo);
      else if (selFrom) display.textContent = fmt(selFrom) + ' – …';
      else display.textContent = cfg.emptyLabel || 'Select date range';
    }
    function syncFormHidden() {
      ff.value = selFrom;
      ft.value = singleDay ? selFrom : selTo;
    }

    function addMonth(y, m0, delta) {
      const t = new Date(y, m0 + delta, 1);
      return { y: t.getFullYear(), m: t.getMonth() };
    }
    function daysInMonth(y, m0) {
      return new Date(y, m0 + 1, 0).getDate();
    }
    function monthLabel(y, m0) {
      return monthLong[m0] + ' ' + y;
    }

    function rangeLoHi() {
      if (!selFrom) return { lo: null, hi: null };
      if (!selTo) return { lo: selFrom, hi: selFrom };
      return compareIso(selFrom, selTo) <= 0
        ? { lo: selFrom, hi: selTo }
        : { lo: selTo, hi: selFrom };
    }

    function cellClassList(iso) {
      const cls = ['an-cal-cell'];
      if (maxDateStr && compareIso(iso, maxDateStr) > 0) {
        cls.push('an-cal-disabled');
        return cls;
      }
      const { lo, hi } = rangeLoHi();
      if (!lo) return cls;
      if (lo === hi && iso === lo) {
        cls.push('an-cal-range-start', 'an-cal-range-end');
        return cls;
      }
      if (iso === lo) cls.push('an-cal-range-start');
      else if (iso === hi) cls.push('an-cal-range-end');
      else if (compareIso(iso, lo) > 0 && compareIso(iso, hi) < 0) cls.push('an-cal-inrange');
      return cls;
    }

    function fillGrid(gridEl, y, m0) {
      gridEl.textContent = '';
      const dim = daysInMonth(y, m0);
      const firstDow = (new Date(y, m0, 1).getDay() + 6) % 7;
      const frag = document.createDocumentFragment();
      for (let i = 0; i < firstDow; i++) {
        const el = document.createElement('div');
        el.className = 'an-cal-cell an-cal-pad';
        frag.appendChild(el);
      }
      for (let d = 1; d <= dim; d++) {
        const isoStr = toIso(y, m0, d);
        const el = document.createElement('button');
        el.type = 'button';
        el.dataset.iso = isoStr;
        el.textContent = String(d);
        const list = cellClassList(isoStr);
        el.className = list.join(' ');
        if (list.indexOf('an-cal-disabled') !== -1) el.disabled = true;
        frag.appendChild(el);
      }
      const used = firstDow + dim;
      const tail = (7 - (used % 7)) % 7;
      for (let i = 0; i < tail; i++) {
        const el = document.createElement('div');
        el.className = 'an-cal-cell an-cal-pad';
        frag.appendChild(el);
      }
      gridEl.appendChild(frag);
    }

    function updateNextDisabled() {
      if (!maxDateObj) {
        btnNext.disabled = false;
        return;
      }
      const nextLeft = new Date(viewY, viewM + 1, 1);
      btnNext.disabled = nextLeft > maxDateObj;
    }

    function renderCalendars() {
      const r = addMonth(viewY, viewM, 1);
      title0.textContent = monthLabel(viewY, viewM);
      title1.textContent = monthLabel(r.y, r.m);
      fillGrid(grid0, viewY, viewM);
      fillGrid(grid1, r.y, r.m);
      updateNextDisabled();
    }

    function onDayClick(iso) {
      if (maxDateStr && compareIso(iso, maxDateStr) > 0) return;
      if (singleDay) {
        selFrom = iso;
        selTo = iso;
      } else if (!selFrom || (selFrom && selTo)) {
        selFrom = iso;
        selTo = '';
      } else {
        if (compareIso(iso, selFrom) < 0) {
          selTo = selFrom;
          selFrom = iso;
        } else selTo = iso;
      }
      renderCalendars();
      refreshTriggerText();
    }

    function openPanel() {
      if (typeof cfg.onOpen === 'function') {
        try {
          cfg.onOpen();
        } catch (err) {}
      }
      openSnapshot = { from: ff.value, to: ft.value };
      selFrom = openSnapshot.from;
      selTo = singleDay ? openSnapshot.from || openSnapshot.to : openSnapshot.to;
      if (singleDay && selFrom) selTo = selFrom;
      const v = parseISO(selFrom || maxDateStr);
      if (v) {
        viewY = v.y;
        viewM = v.mo - 1;
      }
      wrap.classList.add('open');
      trigger.setAttribute('aria-expanded', 'true');
      panel.removeAttribute('hidden');
      renderCalendars();
      refreshTriggerText();
      requestAnimationFrame(function () {
        positionPanel(trigger, panel);
      });
    }
    function closePanel() {
      selFrom = openSnapshot.from;
      selTo = openSnapshot.to;
      syncFormHidden();
      refreshTriggerText();
      wrap.classList.remove('open');
      trigger.setAttribute('aria-expanded', 'false');
      panel.setAttribute('hidden', 'hidden');
      clearPanelPosition(panel);
    }

    function repositionIfOpen() {
      if (wrap.classList.contains('open')) positionPanel(trigger, panel);
    }
    window.addEventListener('resize', repositionIfOpen);
    window.addEventListener('scroll', repositionIfOpen, true);

    panel.addEventListener('click', function (e) {
      // Keep panel clicks from reaching the document outside-close handler.
      // Day cells are re-created in onDayClick; a detached e.target fails
      // wrap.contains() and would otherwise close + wipe the selection.
      e.stopPropagation();
      const btn = e.target.closest('button[data-iso]');
      if (!btn || btn.disabled) return;
      onDayClick(btn.getAttribute('data-iso'));
    });
    btnPrev.addEventListener('click', function (e) {
      e.stopPropagation();
      const p = addMonth(viewY, viewM, -1);
      viewY = p.y;
      viewM = p.m;
      renderCalendars();
    });
    btnNext.addEventListener('click', function (e) {
      e.stopPropagation();
      if (btnNext.disabled) return;
      const p = addMonth(viewY, viewM, 1);
      viewY = p.y;
      viewM = p.m;
      renderCalendars();
    });

    function togglePanel(e) {
      if (e) {
        e.preventDefault();
        e.stopPropagation();
      }
      if (wrap.classList.contains('open')) closePanel();
      else openPanel();
    }
    function eventInsidePicker(target) {
      if (!target || typeof target.closest !== 'function') {
        return !!(wrap && wrap.contains(target));
      }
      if (wrap.contains(target) || trigger.contains(target)) return true;
      var host = wrap.closest(
        '.se-filter-chip-control, .se-filter-chip, .se-filter-chip-date-host, .an-range-wrap'
      );
      return !!(host && host.contains(target));
    }
    trigger.addEventListener('click', togglePanel);
    var control = wrap.closest('.se-filter-chip-control');
    if (control && control.getAttribute('data-sdr-control-bound') !== '1') {
      control.setAttribute('data-sdr-control-bound', '1');
      control.addEventListener('click', function (e) {
        if (e.target.closest('.an-range-trigger, .an-range-panel, .an-range-backdrop')) return;
        togglePanel(e);
      });
    }
    if (backdrop) {
      backdrop.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        closePanel();
      });
    }
    // Outside click (backdrop may be clipped by overflow:hidden chip chrome).
    document.addEventListener('click', function (e) {
      if (!wrap.classList.contains('open')) return;
      if (eventInsidePicker(e.target)) return;
      // Ignore detached targets (e.g. day cell removed mid-bubble by re-render).
      if (!e.target || (e.target.isConnected === false)) return;
      closePanel();
    });
    if (cancelBtn) cancelBtn.addEventListener('click', closePanel);
    if (applyBtn) {
      applyBtn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        if (!selFrom) selFrom = (ff && ff.value) || '';
        if (!selFrom) return;
        if (singleDay || !selTo) selTo = selFrom;
        let lo = selFrom;
        let hi = singleDay ? selFrom : selTo;
        if (!singleDay && compareIso(lo, hi) > 0) {
          lo = selTo;
          hi = selFrom;
        }
        ff.value = lo;
        ft.value = hi;
        if (ff.name == null || ff.name === '') {
          ff.setAttribute('name', 'date_from');
        }
        if (ft.name == null || ft.name === '') {
          ft.setAttribute('name', 'date_to');
        }
        openSnapshot = { from: lo, to: hi };
        selFrom = lo;
        selTo = hi;
        refreshTriggerText();
        if (hasApplyHook) {
          try {
            cfg.onApply({ from: lo, to: hi });
          } catch (err) {}
          wrap.classList.remove('open');
          trigger.setAttribute('aria-expanded', 'false');
          panel.setAttribute('hidden', 'hidden');
          clearPanelPosition(panel);
          return;
        }
        if (cfg.syncReportScopeFromSelects && form) {
          var sc = document.getElementById('sr-filter-company');
          var sl = document.getElementById('sr-filter-location');
          var hc = form.querySelector('input[name="company"]');
          var hl = form.querySelector('input[name="location"]');
          if (sc && hc) hc.value = sc.value || '';
          if (sl && hl) hl.value = sl.value || '';
        }
        if (typeof cfg.onBeforeSubmit === 'function') {
          cfg.onBeforeSubmit(form);
        }
        wrap.classList.remove('open');
        trigger.setAttribute('aria-expanded', 'false');
        panel.setAttribute('hidden', 'hidden');
        clearPanelPosition(panel);
        if (typeof global.deSoftSubmitForm === 'function' && form && global.deSoftSubmitForm(form)) {
          return;
        }
        if (form && typeof form.requestSubmit === 'function') {
          form.requestSubmit();
          return;
        }
        if (form) form.submit();
      });
    }
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && wrap.classList.contains('open')) closePanel();
    });

    syncFormHidden();
    refreshTriggerText();
    wrap.__sdrClose = closePanel;
  }

  function closeIfOpen(wrapId) {
    var wrap = document.getElementById(wrapId);
    if (wrap && wrap.classList.contains('open') && typeof wrap.__sdrClose === 'function') {
      wrap.__sdrClose();
    }
  }

  global.SalesDateRangePicker = {
    init: init,
    closeIfOpen: closeIfOpen,
    positionPanel: positionPanel,
    clearPanelPosition: clearPanelPosition,
    /**
     * Re-fill date chip labels after soft page navigation.
     * The display span starts empty in older markup and can stay blank if
     * entry-date init is skipped or races a fullscreen soft-nav swap.
     */
    syncChipDisplays: function () {
      var monthLong = [
        'January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December',
      ];
      function fmt(iso) {
        if (!iso || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return '';
        var p = iso.split('-').map(Number);
        return p[2] + ' ' + monthLong[p[1] - 1] + ' ' + String(p[0]).slice(-2);
      }
      function setText(el, text) {
        if (el && text) el.textContent = text;
      }

      var entryDisplay = document.getElementById('se-date-range-display');
      var entryInput = document.getElementById('se-filter-date');
      var entryWrap = document.getElementById('se-date-range-wrap');
      var entryIso = ((entryInput && entryInput.value) || (entryWrap && entryWrap.getAttribute('data-initial-date')) || '').trim();
      if (!entryIso) {
        try { entryIso = sessionStorage.getItem('hbe.salesUpdate.date') || ''; } catch (e) {}
      }
      if (entryDisplay) {
        var entryLabel = fmt(entryIso);
        setText(entryDisplay, entryLabel || 'Select date');
      }

      var cashDisplay = document.getElementById('se-cash-date-display');
      var cashFrom = document.getElementById('se-filter-date-from');
      var cashTo = document.getElementById('se-filter-date-to');
      if (cashDisplay) {
        var fromIso = ((cashFrom && cashFrom.value) || entryIso || '').trim();
        var toIso = ((cashTo && cashTo.value) || fromIso || '').trim();
        var cashLabel = '';
        if (fromIso && toIso && fromIso !== toIso) cashLabel = fmt(fromIso) + ' – ' + fmt(toIso);
        else if (fromIso) cashLabel = fmt(fromIso);
        setText(cashDisplay, cashLabel || 'Select date range');
      }

      var clDisplay = document.getElementById('cl-date-range-display');
      var clFrom = document.getElementById('cash-ledger-date-from');
      var clTo = document.getElementById('cash-ledger-date-to');
      if (clDisplay) {
        var clFromIso = ((clFrom && clFrom.value) || '').trim();
        var clToIso = ((clTo && clTo.value) || '').trim();
        var clLabel = '';
        if (clFromIso && clToIso && clFromIso !== clToIso) clLabel = fmt(clFromIso) + ' – ' + fmt(clToIso);
        else if (clFromIso) clLabel = fmt(clFromIso);
        setText(clDisplay, clLabel || 'Date');
      }

      var cpDisplay = document.getElementById('cp-date-range-display');
      var cpFrom = document.getElementById('credit-payment-date-from');
      var cpTo = document.getElementById('credit-payment-date-to');
      if (cpDisplay) {
        var cpFromIso = ((cpFrom && cpFrom.value) || '').trim();
        var cpToIso = ((cpTo && cpTo.value) || '').trim();
        var cpLabel = '';
        if (cpFromIso && cpToIso && cpFromIso !== cpToIso) cpLabel = fmt(cpFromIso) + ' – ' + fmt(cpToIso);
        else if (cpFromIso) cpLabel = fmt(cpFromIso);
        setText(cpDisplay, cpLabel || 'Date');
      }

      var rtDisplay = document.getElementById('rt-date-range-display');
      var rtFrom = document.getElementById('room-transfer-date-from');
      var rtTo = document.getElementById('room-transfer-date-to');
      if (rtDisplay) {
        var rtFromIso = ((rtFrom && rtFrom.value) || '').trim();
        var rtToIso = ((rtTo && rtTo.value) || '').trim();
        var rtLabel = '';
        if (rtFromIso && rtToIso && rtFromIso !== rtToIso) rtLabel = fmt(rtFromIso) + ' – ' + fmt(rtToIso);
        else if (rtFromIso) rtLabel = fmt(rtFromIso);
        setText(rtDisplay, rtLabel || 'Date');
      }

      var plDisplay = document.getElementById('pl-date-range-display');
      var plFrom = document.getElementById('purchase-ledger-date-from');
      var plTo = document.getElementById('purchase-ledger-date-to');
      if (plDisplay) {
        var plFromIso = ((plFrom && plFrom.value) || '').trim();
        var plToIso = ((plTo && plTo.value) || '').trim();
        var plLabel = '';
        if (plFromIso && plToIso && plFromIso !== plToIso) plLabel = fmt(plFromIso) + ' – ' + fmt(plToIso);
        else if (plFromIso) plLabel = fmt(plFromIso);
        setText(plDisplay, plLabel || 'Date');
      }

      var mdDisplay = document.getElementById('md-date-range-display');
      var mdFrom = document.getElementById('md-date-from');
      var mdTo = document.getElementById('md-date-to');
      if (mdDisplay) {
        var mdFromIso = ((mdFrom && mdFrom.value) || '').trim();
        var mdToIso = ((mdTo && mdTo.value) || '').trim();
        var mdLabel = '';
        if (mdFromIso && mdToIso && mdFromIso !== mdToIso) {
          var mdFromParts = mdFromIso.split('-').map(Number);
          var mdToParts = mdToIso.split('-').map(Number);
          if (
            mdFromParts.length === 3 &&
            mdToParts.length === 3 &&
            mdFromParts[0] === mdToParts[0] &&
            mdFromParts[1] === mdToParts[1]
          ) {
            mdLabel =
              mdFromParts[2] +
              ' – ' +
              mdToParts[2] +
              ' ' +
              monthLong[mdFromParts[1] - 1] +
              ' ' +
              String(mdFromParts[0]).slice(-2);
          } else if (mdFromParts.length === 3 && mdToParts.length === 3 && mdFromParts[0] === mdToParts[0]) {
            mdLabel =
              mdFromParts[2] +
              ' ' +
              monthLong[mdFromParts[1] - 1] +
              ' – ' +
              mdToParts[2] +
              ' ' +
              monthLong[mdToParts[1] - 1] +
              ' ' +
              String(mdFromParts[0]).slice(-2);
          } else {
            mdLabel = fmt(mdFromIso) + ' – ' + fmt(mdToIso);
          }
        } else if (mdFromIso) {
          mdLabel = fmt(mdFromIso);
        }
        setText(mdDisplay, mdLabel || 'Select date range');
      }

      var tipsDisplay = document.getElementById('tips-date-range-display');
      var tipsFrom = document.getElementById('tips-date-from');
      var tipsTo = document.getElementById('tips-date-to');
      if (tipsDisplay) {
        var tipsFromIso = ((tipsFrom && tipsFrom.value) || '').trim();
        var tipsToIso = ((tipsTo && tipsTo.value) || '').trim();
        var tipsLabel = '';
        if (tipsFromIso && tipsToIso && tipsFromIso !== tipsToIso) tipsLabel = fmt(tipsFromIso) + ' – ' + fmt(tipsToIso);
        else if (tipsFromIso) tipsLabel = fmt(tipsFromIso);
        setText(tipsDisplay, tipsLabel || 'Date');
      }

      var ecDisplay = document.getElementById('ec-date-range-display');
      var ecFrom = document.getElementById('emp-credits-date-from');
      var ecTo = document.getElementById('emp-credits-date-to');
      if (ecDisplay) {
        var ecFromIso = ((ecFrom && ecFrom.value) || '').trim();
        var ecToIso = ((ecTo && ecTo.value) || '').trim();
        var ecLabel = '';
        if (ecFromIso && ecToIso && ecFromIso !== ecToIso) ecLabel = fmt(ecFromIso) + ' – ' + fmt(ecToIso);
        else if (ecFromIso) ecLabel = fmt(ecFromIso);
        setText(ecDisplay, ecLabel || 'Date');
      }

      var hresDisplay = document.getElementById('hres-date-range-display');
      var hresFrom = document.getElementById('hres-date-from');
      var hresTo = document.getElementById('hres-date-to');
      if (hresDisplay) {
        var hresFromIso = ((hresFrom && hresFrom.value) || '').trim();
        var hresToIso = ((hresTo && hresTo.value) || '').trim();
        var hresLabel = '';
        if (hresFromIso && hresToIso && hresFromIso !== hresToIso) {
          hresLabel = fmt(hresFromIso) + ' – ' + fmt(hresToIso);
        } else if (hresFromIso) {
          hresLabel = fmt(hresFromIso);
        }
        setText(hresDisplay, hresLabel || 'Select date…');
      }
    }
  };

  // Keep chip text correct after soft navigation or partial remounts.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      global.SalesDateRangePicker.syncChipDisplays();
    });
  } else {
    global.SalesDateRangePicker.syncChipDisplays();
  }
})(window);
