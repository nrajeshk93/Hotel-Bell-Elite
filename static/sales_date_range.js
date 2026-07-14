/**
 * Dual-month date range picker (Analytics / Report topbar).
 * Usage: SalesDateRangePicker.init({ wrapId, formId, ... });
 */
(function (global) {
  function positionPanel(trigger, panel, opts) {
    if (!trigger || !panel) return;
    opts = opts || {};
    const gap = opts.gap != null ? opts.gap : 8;
    const margin = opts.margin != null ? opts.margin : 12;

    panel.style.position = 'fixed';
    panel.style.right = 'auto';
    panel.style.bottom = 'auto';
    panel.style.visibility = 'hidden';
    panel.style.display = 'flex';
    panel.style.flexDirection = 'column';

    const panelW = panel.offsetWidth;
    const panelH = panel.offsetHeight;
    const rect = trigger.getBoundingClientRect();

    let top = rect.bottom + gap;
    let left = rect.left;

    if (left + panelW > window.innerWidth - margin) {
      left = Math.max(margin, window.innerWidth - margin - panelW);
    }
    if (left < margin) left = margin;

    if (top + panelH > window.innerHeight - margin) {
      const above = rect.top - gap - panelH;
      top = above >= margin ? above : Math.max(margin, window.innerHeight - margin - panelH);
    }
    if (top < margin) top = margin;

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
    panel.style.visibility = '';
  }

  function init(cfg) {
    const wrap = document.getElementById(cfg.wrapId);
    const trigger = document.getElementById(cfg.triggerId);
    const backdrop = document.getElementById(cfg.backdropId);
    const panel = document.getElementById(cfg.panelId);
    const display = document.getElementById(cfg.displayId);
    const form = document.getElementById(cfg.formId);
    const ff = document.getElementById(cfg.fromInputId);
    const ft = document.getElementById(cfg.toInputId);
    const cancelBtn = document.getElementById(cfg.cancelId);
    const applyBtn = document.getElementById(cfg.applyId);
    const btnPrev = document.getElementById(cfg.prevId);
    const btnNext = document.getElementById(cfg.nextId);
    const title0 = document.getElementById(cfg.title0Id);
    const title1 = document.getElementById(cfg.title1Id);
    const grid0 = document.getElementById(cfg.grid0Id);
    const grid1 = document.getElementById(cfg.grid1Id);
    if (
      !wrap ||
      !trigger ||
      !panel ||
      !display ||
      !form ||
      !ff ||
      !ft ||
      !btnPrev ||
      !btnNext ||
      !title0 ||
      !title1 ||
      !grid0 ||
      !grid1
    ) {
      return;
    }

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
    const now = new Date();
    let viewY = now.getFullYear();
    let viewM = now.getMonth();
    let openSnapshot = { from: '', to: '' };

    const initAnchor = parseISO(ff.value || maxDateStr);
    if (initAnchor) {
      viewY = initAnchor.y;
      viewM = initAnchor.mo - 1;
    }

    const monthShort = [
      'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
    ];
    function fmt(iso) {
      if (!iso || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return '—';
      const p = parseISO(iso);
      return p.d + ' ' + monthShort[p.mo - 1] + ', ' + p.y;
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
        return x.d + ' – ' + y.d + ' ' + monthShort[x.mo - 1] + ', ' + x.y;
      }
      if (x.y === y.y) {
        return x.d + ' ' + monthShort[x.mo - 1] + ' – ' + y.d + ' ' + monthShort[y.mo - 1] + ', ' + x.y;
      }
      return fmt(lo) + ' – ' + fmt(hi);
    }
    function refreshTriggerText() {
      if (selFrom && selTo) display.textContent = fmtRange(selFrom, selTo);
      else if (selFrom) display.textContent = fmt(selFrom) + ' – …';
      else display.textContent = 'Select date range';
    }
    function syncFormHidden() {
      ff.value = selFrom;
      ft.value = selTo;
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
      if (!selFrom || (selFrom && selTo)) {
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
      openSnapshot = { from: ff.value, to: ft.value };
      selFrom = openSnapshot.from;
      selTo = openSnapshot.to;
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
      const btn = e.target.closest('button[data-iso]');
      if (!btn || btn.disabled) return;
      onDayClick(btn.getAttribute('data-iso'));
    });
    btnPrev.addEventListener('click', function () {
      const p = addMonth(viewY, viewM, -1);
      viewY = p.y;
      viewM = p.m;
      renderCalendars();
    });
    btnNext.addEventListener('click', function () {
      if (btnNext.disabled) return;
      const p = addMonth(viewY, viewM, 1);
      viewY = p.y;
      viewM = p.m;
      renderCalendars();
    });

    trigger.addEventListener('click', function (e) {
      e.stopPropagation();
      if (wrap.classList.contains('open')) closePanel();
      else openPanel();
    });
    if (backdrop) backdrop.addEventListener('click', closePanel);
    if (cancelBtn) cancelBtn.addEventListener('click', closePanel);
    if (applyBtn) {
      applyBtn.addEventListener('click', function () {
        if (!selFrom) return;
        if (!selTo) selTo = selFrom;
        let lo = selFrom;
        let hi = selTo;
        if (compareIso(lo, hi) > 0) {
          lo = selTo;
          hi = selFrom;
        }
        ff.value = lo;
        ft.value = hi;
        if (cfg.syncReportScopeFromSelects) {
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
        form.submit();
      });
    }
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && wrap.classList.contains('open')) closePanel();
    });

    syncFormHidden();
    refreshTriggerText();
  }

  global.SalesDateRangePicker = {
    init: init,
    positionPanel: positionPanel,
    clearPanelPosition: clearPanelPosition,
    /**
     * Re-fill date chip labels after soft page navigation.
     * The display span starts empty in older markup and can stay blank if
     * entry-date init is skipped or races a fullscreen soft-nav swap.
     */
    syncChipDisplays: function () {
      var monthShort = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      function fmt(iso) {
        if (!iso || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return '';
        var p = iso.split('-').map(Number);
        return p[2] + ' ' + monthShort[p[1] - 1] + ', ' + p[0];
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
