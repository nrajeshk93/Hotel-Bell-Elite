/* Retail Intelligence Dashboard — ECharts rendering */
(function () {
  'use strict';

  var charts = [];
  var resizeHandler = null;
  var chartResizeObserver = null;
  var ECHARTS_SRC = 'https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js';

  function ensureEcharts(cb) {
    if (typeof echarts !== 'undefined') {
      cb();
      return;
    }
    var existing = document.querySelector('script[data-de-echarts], script[src*="echarts"]');
    if (existing) {
      var tries = 0;
      var timer = setInterval(function () {
        if (typeof echarts !== 'undefined') {
          clearInterval(timer);
          cb();
        } else if (++tries > 80) {
          clearInterval(timer);
        }
      }, 50);
      existing.addEventListener('load', function () {
        if (typeof echarts !== 'undefined') {
          clearInterval(timer);
          cb();
        }
      });
      return;
    }
    var s = document.createElement('script');
    s.src = ECHARTS_SRC;
    s.setAttribute('data-de-echarts', '1');
    s.onload = function () { cb(); };
    s.onerror = function () { cb(); };
    document.head.appendChild(s);
  }

  function disposeCharts() {
    charts.forEach(function (c) {
      try { c.dispose(); } catch (e) {}
    });
    charts = [];
    if (typeof echarts !== 'undefined') {
      document.querySelectorAll('[id^="rdx-chart-"], [id^="rdx-spark-"]').forEach(function (el) {
        var inst = echarts.getInstanceByDom(el);
        if (inst) {
          try { inst.dispose(); } catch (e) {}
        }
      });
    }
    if (resizeHandler) {
      window.removeEventListener('resize', resizeHandler);
      resizeHandler = null;
    }
    if (window.__mdDashResizeHandler) {
      window.removeEventListener('resize', window.__mdDashResizeHandler);
      window.__mdDashResizeHandler = null;
    }
    if (chartResizeObserver) {
      try { chartResizeObserver.disconnect(); } catch (e) {}
      chartResizeObserver = null;
    }
    if (window.__mdDashChartResizeObserver) {
      try { window.__mdDashChartResizeObserver.disconnect(); } catch (e) {}
      window.__mdDashChartResizeObserver = null;
    }
  }

  // Soft-nav re-runs this file; dispose any prior module instance first.
  if (typeof window.__mdDashDisposeCharts === 'function') {
    try { window.__mdDashDisposeCharts(); } catch (e) {}
  }
  window.__mdDashDisposeCharts = disposeCharts;

  function initMainDashboardCharts() {
    var dataEl = document.getElementById('md-dashboard-data');
    if (!dataEl) return;

    ensureEcharts(function () {
      if (typeof echarts === 'undefined') return;

      var DATA;
      try {
        DATA = JSON.parse(dataEl.textContent);
      } catch (e) {
        return;
      }

      disposeCharts();

      try {

  function fmt(v) {
    if (typeof formatInr === 'function') return formatInr(v, 0);
    return '₹' + Number(v || 0).toLocaleString('en-IN');
  }

  function shortDate(iso) {
    if (!iso) return '';
    var p = iso.split('-');
    return p[2] + '/' + p[1];
  }

  function mount(id, option) {
    var el = document.getElementById(id);
    if (!el) return null;
    var existing = echarts.getInstanceByDom(el);
    if (existing) {
      // Force a clean option replace (avoids leftover axisPointer / splitLine from prior mounts).
      existing.setOption(option, { notMerge: true, lazyUpdate: false });
      observeChartHost(el);
      try {
        existing.resize({ width: el.clientWidth, height: el.clientHeight || undefined });
      } catch (e) {
        existing.resize();
      }
      return existing;
    }
    // Tall mounts for line charts only. Donut uses CSS aspect-ratio (Neeraj ~200px).
    if (
      id.indexOf('rdx-chart-') === 0 &&
      id !== 'rdx-chart-donut' &&
      !el.classList.contains('rdx-sc-chart') &&
      !el.style.minHeight
    ) {
      el.style.minHeight = el.classList.contains('rdx-chart-sm') ? '220px' : '280px';
    }
    if (id === 'rdx-chart-donut' || el.classList.contains('rdx-sc-chart')) {
      el.style.minHeight = '';
    }
    var chart = echarts.init(el, null, { renderer: 'canvas' });
    chart.setOption(option);
    charts.push(chart);
    observeChartHost(el);
    return chart;
  }

  function observeChartHost(el) {
    if (!el || typeof ResizeObserver === 'undefined') return;
    if (!chartResizeObserver) {
      chartResizeObserver = new ResizeObserver(function (entries) {
        entries.forEach(function (entry) {
          var host = entry.target;
          var inst = echarts.getInstanceByDom(host);
          if (!inst) return;
          try {
            inst.resize({ width: host.clientWidth, height: host.clientHeight });
          } catch (e) {}
        });
      });
      window.__mdDashChartResizeObserver = chartResizeObserver;
    }
    try { chartResizeObserver.observe(el); } catch (e) {}
  }

  function scheduleChartResize() {
    function resizeAll() {
      charts.forEach(function (c) {
        try {
          var dom = c.getDom && c.getDom();
          if (dom && dom.clientWidth > 0) {
            c.resize({ width: dom.clientWidth, height: dom.clientHeight || undefined });
          } else {
            c.resize();
          }
        } catch (e) {}
      });
    }
    resizeAll();
    if (typeof requestAnimationFrame === 'function') {
      requestAnimationFrame(function () {
        resizeAll();
        requestAnimationFrame(resizeAll);
      });
    }
    setTimeout(resizeAll, 50);
    setTimeout(resizeAll, 200);
    setTimeout(resizeAll, 450);
  }

  function baseGrid() {
    return {
      left: 48,
      right: 20,
      top: 36,
      bottom: 28,
      containLabel: true,
    };
  }

  function buildSalesSeries(series) {
    if (!series.length) return { points: [], labels: [], values: [] };

    var points = [];
    var prev = null;
    series.forEach(function (row) {
      var val = row.actual_sales || 0;
      points.push({
        date: row.date,
        label: formatDate(row.date),
        value: val,
        change_pct: prev != null ? pctChange(val, prev) : null,
      });
      prev = val;
    });
    return {
      points: points,
      labels: points.map(function (p) { return shortDate(p.date); }),
      values: points.map(function (p) { return p.value; }),
    };
  }

  function pctChange(cur, prev) {
    if (prev === 0) return cur === 0 ? 0 : (cur > 0 ? 100 : -100);
    return Math.round((cur - prev) / Math.abs(prev) * 1000) / 10;
  }

  var salesTrendPoints = [];

  function salesTrendOption(agg) {
    salesTrendPoints = agg.points || [];
    return {
      animationDuration: 700,
      animationEasing: 'cubicOut',
      color: ['#2563EB'],
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#0f172a',
        borderColor: '#0f172a',
        textStyle: { color: '#f8fafc', fontSize: 12 },
        formatter: function (params) {
          var idx = params[0].dataIndex;
          var pt = salesTrendPoints[idx] || {};
          var lines = [pt.label || params[0].axisValue];
          lines.push('Sales: ' + fmt(pt.value));
          if (pt.change_pct != null) {
            var sign = pt.change_pct >= 0 ? '+' : '';
            lines.push('Growth: ' + sign + pt.change_pct + '%');
          }
          return lines.join('<br/>');
        },
      },
      grid: { left: 12, right: 20, top: 16, bottom: 8, containLabel: true },
      xAxis: {
        type: 'category',
        data: agg.labels,
        boundaryGap: false,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: '#94a3b8', fontSize: 11, margin: 12 },
      },
      yAxis: {
        type: 'value',
        splitLine: { lineStyle: { color: '#f1f5f9', type: 'dashed' } },
        axisLabel: { color: '#94a3b8', fontSize: 11, formatter: function (v) { return fmt(v); } },
      },
      series: [{
        name: 'Sales',
        type: 'line',
        data: agg.values,
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        showSymbol: agg.values.length <= 45,
        lineStyle: { width: 3, color: '#2563EB' },
        itemStyle: { color: '#2563EB', borderColor: '#fff', borderWidth: 2 },
        emphasis: {
          focus: 'series',
          scale: true,
          itemStyle: { color: '#2563EB', borderColor: '#fff', borderWidth: 2 },
          symbolSize: 10,
        },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(37,99,235,0.18)' },
              { offset: 1, color: 'rgba(37,99,235,0)' },
            ],
          },
        },
      }],
    };
  }

  function renderSalesTrend() {
    mount('rdx-chart-trend', salesTrendOption(buildSalesSeries(DATA.daily_series || [])));
  }

  function formatDate(iso) {
    if (!iso) return '';
    var p = iso.split('-');
    return p[2] + ' ' + ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][parseInt(p[1], 10) - 1];
  }

  function animateKpiValues() {
    var nodes = document.querySelectorAll('.rdx-kpi-value[data-value]');
    var pending = nodes.length;
    if (!pending) {
      if (typeof window.scheduleFitKpiValues === 'function') window.scheduleFitKpiValues();
      return;
    }
    nodes.forEach(function (el) {
      var target = parseFloat(el.getAttribute('data-value') || '0');
      if (!isFinite(target)) {
        pending -= 1;
        if (!pending && typeof window.scheduleFitKpiValues === 'function') {
          window.scheduleFitKpiValues();
        }
        return;
      }
      var duration = 900;
      var startTime = null;
      function step(ts) {
        if (!startTime) startTime = ts;
        var progress = Math.min((ts - startTime) / duration, 1);
        var eased = 1 - Math.pow(1 - progress, 3);
        el.textContent = fmt(target * eased);
        if (progress < 1) {
          requestAnimationFrame(step);
          return;
        }
        pending -= 1;
        if (!pending && typeof window.scheduleFitKpiValues === 'function') {
          window.scheduleFitKpiValues();
        }
      }
      requestAnimationFrame(step);
    });
  }

  function sparklineOption(kpi) {
    var series = kpi.sparkline_series || (kpi.sparkline || []).map(function (v, i) {
      return { date: String(i), value: v, change_pct: null };
    });
    return {
      animationDuration: 800,
      animationEasing: 'cubicOut',
      grid: { left: 0, right: 0, top: 6, bottom: 0 },
      tooltip: {
        trigger: 'axis',
        confine: true,
        backgroundColor: '#0f172a',
        borderColor: '#0f172a',
        textStyle: { color: '#f8fafc', fontSize: 11 },
        formatter: function (params) {
          var idx = params[0].dataIndex;
          var pt = series[idx] || {};
          var lines = [formatDate(pt.date) || shortDate(pt.date)];
          lines.push('Value: ' + fmt(pt.value));
          if (pt.change_pct != null) {
            var sign = pt.change_pct >= 0 ? '+' : '';
            lines.push('Change: ' + sign + pt.change_pct + '%');
          }
          return lines.join('<br/>');
        },
      },
      xAxis: { type: 'category', show: false, boundaryGap: false, data: series.map(function (x) { return x.date; }) },
      yAxis: { type: 'value', show: false, scale: true },
      series: [{
        type: 'line',
        data: series.map(function (x) { return x.value; }),
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2, color: '#2563EB' },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(37,99,235,0.18)' },
              { offset: 1, color: 'rgba(37,99,235,0)' },
            ],
          },
        },
      }],
    };
  }

  animateKpiValues();

  (DATA.kpis || []).forEach(function (kpi, i) {
    mount('rdx-spark-' + i, sparklineOption(kpi));
  });

  renderSalesTrend();

  var contrib = DATA.sales_contribution || { entries: [] };
  var contribItems = contrib.entries || [];

  mount('rdx-chart-donut', {
    color: contribItems.map(function (x) { return x.color; }),
    tooltip: {
      trigger: 'item',
      backgroundColor: '#0f172a',
      borderColor: '#0f172a',
      textStyle: { color: '#f8fafc', fontSize: 12 },
      formatter: function (p) {
        var item = contribItems[p.dataIndex] || {};
        var lines = [p.name, 'Sales: ' + fmt(p.value), 'Contribution: ' + p.percent + '%'];
        if (item.growth_pct != null) {
          var sign = item.growth_pct >= 0 ? '+' : '';
          lines.push('Growth: ' + sign + item.growth_pct + '%');
        }
        return lines.join('<br/>');
      },
    },
    series: [{
      type: 'pie',
      /* Larger hole so center Total / amount never clips into the ring. */
      radius: ['64%', '86%'],
      center: ['50%', '50%'],
      padAngle: 2.5,
      itemStyle: { borderRadius: 6 },
      label: { show: false },
      labelLine: { show: false },
      data: contribItems.map(function (x) {
        return { name: x.name, value: x.sales, itemStyle: { color: x.color } };
      }),
    }],
  });

  var stack = DATA.digital_cash_stack || [];
  mount('rdx-chart-digital-cash', {
    animationDuration: 700,
    animationEasing: 'cubicOut',
    color: ['#2563EB', '#34D399'],
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#0f172a',
      borderColor: '#0f172a',
      textStyle: { color: '#f8fafc', fontSize: 12 },
      formatter: function (params) {
        var lines = [params[0].axisValue];
        params.forEach(function (p) {
          lines.push(p.seriesName + ': ' + p.value + '%');
        });
        return lines.join('<br/>');
      },
    },
    legend: { show: false },
    grid: { left: 8, right: 12, top: 8, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: stack.map(function (x) { return shortDate(x.date); }),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#94a3b8', fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      splitLine: { lineStyle: { color: '#f1f5f9', type: 'dashed' } },
      axisLabel: { color: '#94a3b8', fontSize: 11, formatter: '{value}%' },
    },
    series: [
      {
        name: 'Digital (%)',
        type: 'line',
        stack: 'payment',
        smooth: true,
        symbol: 'circle',
        symbolSize: 4,
        showSymbol: stack.length <= 31,
        lineStyle: { width: 2, color: '#2563EB' },
        itemStyle: { color: '#2563EB' },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(37,99,235,0.35)' },
              { offset: 1, color: 'rgba(37,99,235,0.05)' },
            ],
          },
        },
        data: stack.map(function (x) { return x.digital_pct; }),
      },
      {
        name: 'Cash (%)',
        type: 'line',
        stack: 'payment',
        smooth: true,
        symbol: 'circle',
        symbolSize: 4,
        showSymbol: stack.length <= 31,
        lineStyle: { width: 2, color: '#34D399' },
        itemStyle: { color: '#34D399' },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(52,211,153,0.35)' },
              { offset: 1, color: 'rgba(52,211,153,0.05)' },
            ],
          },
        },
        data: stack.map(function (x) { return x.cash_pct; }),
      },
    ],
  });

  mount('rdx-chart-dow', {
    color: ['#2563EB'],
    tooltip: {
      trigger: 'item',
      axisPointer: { type: 'none' },
    },
    axisPointer: { show: false },
    grid: baseGrid(),
    xAxis: {
      type: 'category',
      data: (DATA.dow_avg || []).map(function (x) { return x.day.slice(0, 3); }),
      boundaryGap: true,
      axisTick: { show: false, alignWithLabel: true, length: 0 },
      minorTick: { show: false },
      splitLine: { show: false, lineStyle: { width: 0, opacity: 0, color: 'transparent' } },
      minorSplitLine: { show: false },
      splitArea: { show: false },
      axisLine: { show: true, onZero: true, lineStyle: { color: '#e2e8f0', width: 1 } },
      axisPointer: { show: false, type: 'none', lineStyle: { width: 0, opacity: 0 } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { formatter: function (v) { return fmt(v); } },
      splitLine: { show: true, lineStyle: { color: '#f1f5f9', type: 'solid', width: 1 } },
      axisLine: { show: false },
      axisTick: { show: false },
      axisPointer: { show: false },
    },
    series: [{
      type: 'bar',
      data: (DATA.dow_avg || []).map(function (x) { return x.avg_sales; }),
      barMaxWidth: 28,
      barCategoryGap: '28%',
      showBackground: false,
      itemStyle: { borderRadius: [6, 6, 0, 0] },
    }],
  });

  function heatColor(intensity, hasSales, inRange) {
    if (!inRange) return '#F8FAFC';
    if (!hasSales || intensity <= 0) return '#F1F5F9';
    if (intensity >= 0.8) return '#2563EB';
    if (intensity >= 0.6) return '#3B82F6';
    if (intensity >= 0.4) return '#93C5FD';
    if (intensity >= 0.2) return '#DBEAFE';
    return '#EFF6FF';
  }

  function longDate(iso) {
    if (!iso) return '';
    var p = iso.split('-');
    var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return parseInt(p[2], 10) + ' ' + months[parseInt(p[1], 10) - 1] + ' ' + p[0];
  }

  function growthText(pct) {
    if (pct === null || pct === undefined) return '—';
    var sign = pct > 0 ? '+' : '';
    return sign + pct + '%';
  }

  function applyDateFilter(from, to) {
    var filterForm = document.getElementById('md-filter-form');
    if (!filterForm) return;
    var fromEl = document.getElementById('md-date-from') || filterForm.querySelector('input[name="date_from"]');
    var toEl = document.getElementById('md-date-to') || filterForm.querySelector('input[name="date_to"]');
    var periodEl = document.getElementById('md-period') || filterForm.querySelector('input[name="period"]');
    if (fromEl) fromEl.value = from;
    if (toEl) toEl.value = to;
    if (periodEl) periodEl.value = 'custom';
    if (typeof window.deSoftSubmitForm === 'function' && window.deSoftSubmitForm(filterForm)) return;
    if (typeof filterForm.requestSubmit === 'function') filterForm.requestSubmit();
    else filterForm.submit();
  }

  function initRdxFilterListboxes(form) {
    if (!form) return;
    var companyInput = document.getElementById('rdx-company');
    var locationInput = document.getElementById('rdx-location');

    function closeListbox(root) {
      if (!root) return;
      var trigger = root.querySelector('.se-filter-chip-trigger');
      var list = root.querySelector('.se-filter-listbox');
      root.classList.remove('is-open');
      if (trigger) trigger.setAttribute('aria-expanded', 'false');
      if (list) list.hidden = true;
    }
    function closeAllListboxes(except) {
      form.querySelectorAll('[data-se-listbox].is-open').forEach(function (root) {
        if (root !== except) closeListbox(root);
      });
    }
    function openListbox(root) {
      if (!root || root.classList.contains('is-disabled')) return;
      var trigger = root.querySelector('.se-filter-chip-trigger');
      if (trigger && trigger.disabled) return;
      closeAllListboxes(root);
      var list = root.querySelector('.se-filter-listbox');
      root.classList.add('is-open');
      if (trigger) trigger.setAttribute('aria-expanded', 'true');
      if (list) {
        list.hidden = false;
        var selected = list.querySelector('[aria-selected="true"]') || list.querySelector('.se-filter-listbox-option');
        if (selected) selected.focus();
      }
    }
    function toggleListbox(root) {
      if (!root) return;
      if (root.classList.contains('is-open')) closeListbox(root);
      else openListbox(root);
    }
    function selectOption(root, option) {
      if (!root || !option) return;
      var input = root.querySelector('input[type="hidden"]');
      var valueEl = root.querySelector('.se-filter-chip-value');
      var list = root.querySelector('.se-filter-listbox');
      var value = option.getAttribute('data-value') || '';
      var label = (option.textContent || '').trim();
      if (input) {
        input.disabled = false;
        input.value = value;
      }
      if (valueEl) valueEl.textContent = label;
      if (list) {
        list.querySelectorAll('.se-filter-listbox-option').forEach(function (opt) {
          var on = opt === option;
          opt.classList.toggle('is-selected', on);
          opt.setAttribute('aria-selected', on ? 'true' : 'false');
        });
      }
      // Changing company clears location (server rebuilds location options).
      if (input === companyInput && locationInput) {
        locationInput.value = '';
        locationInput.disabled = !value;
      }
      closeListbox(root);
      form.submit();
    }
    function bindListbox(root) {
      if (!root || root.__rdxListboxBound) return;
      var trigger = root.querySelector('.se-filter-chip-trigger');
      var list = root.querySelector('.se-filter-listbox');
      if (!trigger || !list) return;
      root.__rdxListboxBound = true;
      trigger.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        if (trigger.disabled) return;
        toggleListbox(root);
      });
      trigger.addEventListener('keydown', function (e) {
        if (trigger.disabled) return;
        if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          openListbox(root);
        } else if (e.key === 'Escape') {
          closeListbox(root);
        }
      });
      list.addEventListener('click', function (e) {
        var option = e.target.closest('.se-filter-listbox-option');
        if (!option || !list.contains(option)) return;
        e.preventDefault();
        selectOption(root, option);
      });
      list.addEventListener('keydown', function (e) {
        var options = Array.from(list.querySelectorAll('.se-filter-listbox-option'));
        if (!options.length) return;
        var idx = options.indexOf(document.activeElement);
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          options[Math.min(options.length - 1, Math.max(0, idx) + 1)].focus();
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          options[Math.max(0, (idx < 0 ? 0 : idx) - 1)].focus();
        } else if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          if (idx >= 0) selectOption(root, options[idx]);
        } else if (e.key === 'Escape') {
          e.preventDefault();
          closeListbox(root);
          trigger.focus();
        }
      });
    }

    form.querySelectorAll('[data-se-listbox]').forEach(bindListbox);
    if (!window.__rdxListboxDocBound) {
      window.__rdxListboxDocBound = true;
      document.addEventListener('click', function (e) {
        var liveForm = document.getElementById('rdx-filter-form');
        if (!liveForm) return;
        liveForm.querySelectorAll('[data-se-listbox].is-open').forEach(function (root) {
          if (!root.contains(e.target)) closeListbox(root);
        });
      });
      document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        var liveForm = document.getElementById('rdx-filter-form');
        if (!liveForm) return;
        liveForm.querySelectorAll('[data-se-listbox].is-open').forEach(closeListbox);
      });
    }
  }

  function createHeatmapTooltip(tipEl) {
    var EDGE = 12;
    var GAP = 10;
    var CURSOR_PAD = 12;
    var state = { visible: false, anchor: null, clientX: 0, clientY: 0 };
    var rafId = null;

    function clamp(n, lo, hi) {
      return Math.max(lo, Math.min(hi, n));
    }

    function rectsOverlap(x, y, w, h, rx, ry, rw, rh, pad) {
      pad = pad || 0;
      return x - pad < rx + rw && x + w + pad > rx && y - pad < ry + rh && y + h + pad > ry;
    }

    function overlapsCursor(x, y, w, h, cx, cy) {
      return cx >= x - CURSOR_PAD && cx <= x + w + CURSOR_PAD &&
        cy >= y - CURSOR_PAD && cy <= y + h + CURSOR_PAD;
    }

    function updatePosition() {
      rafId = null;
      if (!state.visible || !tipEl || !state.anchor) return;

      tipEl.classList.add('is-measuring');
      tipEl.classList.remove('is-visible');
      tipEl.hidden = false;
      tipEl.style.transform = 'translate3d(-9999px,-9999px,0)';

      var tw = tipEl.offsetWidth;
      var th = tipEl.offsetHeight;
      var vw = window.innerWidth;
      var vh = window.innerHeight;
      var rect = state.anchor.getBoundingClientRect();
      var cx = state.clientX;
      var cy = state.clientY;
      var maxX = Math.max(EDGE, vw - tw - EDGE);
      var maxY = Math.max(EDGE, vh - th - EDGE);

      var x = rect.right + GAP;
      var y = rect.top + (rect.height - th) / 2;

      if (x + tw + EDGE > vw) {
        x = rect.left - GAP - tw;
      }

      if (y + th + EDGE > vh) {
        y = rect.top - GAP - th;
      }

      x = clamp(x, EDGE, maxX);
      y = clamp(y, EDGE, maxY);

      if (rectsOverlap(x, y, tw, th, rect.left, rect.top, rect.width, rect.height, GAP)) {
        var rightX = rect.right + GAP;
        var leftX = rect.left - GAP - tw;
        if (rightX + tw + EDGE <= vw) {
          x = rightX;
          y = clamp(rect.top + (rect.height - th) / 2, EDGE, maxY);
        } else if (leftX >= EDGE) {
          x = leftX;
          y = clamp(rect.top + (rect.height - th) / 2, EDGE, maxY);
        } else {
          x = clamp(rect.left + (rect.width - tw) / 2, EDGE, maxX);
          y = rect.bottom + GAP + th + EDGE <= vh
            ? rect.bottom + GAP
            : rect.top - GAP - th;
          y = clamp(y, EDGE, maxY);
        }
      }

      if (overlapsCursor(x, y, tw, th, cx, cy)) {
        var belowY = cy + CURSOR_PAD;
        var aboveY = cy - CURSOR_PAD - th;
        if (belowY + th + EDGE <= vh && !rectsOverlap(x, belowY, tw, th, rect.left, rect.top, rect.width, rect.height, GAP)) {
          y = belowY;
        } else if (aboveY >= EDGE && !rectsOverlap(x, aboveY, tw, th, rect.left, rect.top, rect.width, rect.height, GAP)) {
          y = aboveY;
        } else if (rect.right + GAP + tw + EDGE <= vw) {
          x = rect.right + GAP;
          y = clamp(cy - th / 2, EDGE, maxY);
        } else {
          x = clamp(rect.left - GAP - tw, EDGE, maxX);
          y = clamp(cy - th / 2, EDGE, maxY);
        }
        x = clamp(x, EDGE, maxX);
        y = clamp(y, EDGE, maxY);
      }

      tipEl.style.transform = 'translate3d(' + Math.round(x) + 'px,' + Math.round(y) + 'px,0)';
      tipEl.classList.remove('is-measuring');
      tipEl.classList.add('is-visible');
    }

    function scheduleUpdate() {
      if (rafId) return;
      rafId = requestAnimationFrame(updatePosition);
    }

    function show(anchor, ev, html) {
      state.anchor = anchor;
      state.clientX = ev.clientX;
      state.clientY = ev.clientY;
      state.visible = true;
      tipEl.innerHTML = html;
      scheduleUpdate();
    }

    function move(ev) {
      if (!state.visible) return;
      state.clientX = ev.clientX;
      state.clientY = ev.clientY;
      scheduleUpdate();
    }

    function hide() {
      state.visible = false;
      state.anchor = null;
      tipEl.hidden = true;
      tipEl.classList.remove('is-visible', 'is-measuring');
      tipEl.style.transform = '';
    }

    function onViewportChange() {
      if (state.visible) scheduleUpdate();
    }

    window.addEventListener('resize', onViewportChange);
    window.addEventListener('scroll', onViewportChange, true);

    return { show: show, move: move, hide: hide };
  }

  function renderSalesHeatmap() {
    var root = document.getElementById('rdx-sales-heatmap');
    var tip = document.getElementById('rdx-heatmap-tooltip');
    var hm = DATA.heatmap;
    if (!root || !hm || !hm.weeks || !hm.weeks.length) {
      if (root) root.innerHTML = '<p style="color:#94a3b8;font-size:13px;padding:12px 0">No sales data for this period.</p>';
      return;
    }

    var heatmapTip = tip ? createHeatmapTooltip(tip) : null;

    root.innerHTML = '';
    root.appendChild(document.createElement('div')).className = 'rdx-heatmap-corner';
    (hm.columns || []).forEach(function (col) {
      var head = document.createElement('div');
      head.className = 'rdx-heatmap-col-head';
      head.textContent = col;
      root.appendChild(head);
    });

    hm.weeks.forEach(function (week) {
      var label = document.createElement('button');
      label.type = 'button';
      label.className = 'rdx-heatmap-row-label';
      label.textContent = week.label;
      label.title = 'Filter to ' + week.label;
      label.addEventListener('click', function () {
        applyDateFilter(week.filter_from, week.filter_to);
      });
      root.appendChild(label);

      (week.cells || []).forEach(function (cell) {
        var el = document.createElement('div');
        el.className = 'rdx-heatmap-cell';
        el.style.background = heatColor(cell.intensity, cell.has_sales, cell.in_range);

        if (!cell.in_range) {
          el.classList.add('is-out');
        } else if (cell.has_sales) {
          el.classList.add('is-active');
          el.setAttribute('role', 'button');
          el.setAttribute('tabindex', '0');
          el.setAttribute('aria-label', longDate(cell.date) + ', sales ' + fmt(cell.sales));

          el.addEventListener('click', function () {
            applyDateFilter(cell.date, cell.date);
          });
          el.addEventListener('keydown', function (ev) {
            if (ev.key === 'Enter' || ev.key === ' ') {
              ev.preventDefault();
              applyDateFilter(cell.date, cell.date);
            }
          });

          if (heatmapTip) {
            el.addEventListener('mouseenter', function (ev) {
              el.classList.add('is-hover');
              var growth = cell.growth_pct;
              var growthCls = growth > 0 ? 'rdx-ht-up' : (growth < 0 ? 'rdx-ht-down' : '');
              heatmapTip.show(el, ev,
                '<strong>' + longDate(cell.date) + '</strong>' +
                '<div class="rdx-ht-row"><span>Sales</span><span>' + fmt(cell.sales) + '</span></div>' +
                '<div class="rdx-ht-row"><span>Transactions</span><span>' + (cell.transactions || 0) + '</span></div>' +
                '<div class="rdx-ht-row"><span>Growth vs prev day</span><span class="' + growthCls + '">' + growthText(growth) + '</span></div>'
              );
            });
            el.addEventListener('mousemove', function (ev) {
              heatmapTip.move(ev);
            });
            el.addEventListener('mouseleave', function () {
              el.classList.remove('is-hover');
              heatmapTip.hide();
            });
          }
        } else {
          el.classList.add('is-empty');
        }

        root.appendChild(el);
      });
    });
  }

  renderSalesHeatmap();

      resizeHandler = function () {
        charts.forEach(function (c) { c.resize(); });
      };
      window.__mdDashResizeHandler = resizeHandler;
      window.addEventListener('resize', resizeHandler);
      scheduleChartResize();
    } catch (err) {
      try { console.error('main dashboard charts failed', err); } catch (eLog) {}
    }
    });
  }

  window.initMainDashboardCharts = initMainDashboardCharts;
  // Always init (including soft-nav re-runs via data-de-rerun) so charts remount on new DOM/data.
  initMainDashboardCharts();
})();
