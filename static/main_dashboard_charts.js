/* Retail Intelligence Dashboard — ECharts rendering */
(function () {
  'use strict';

  var charts = [];
  var resizeHandler = null;
  var chartResizeObserver = null;
  var salesTrendObserver = null;
  var kpiSparkObserver = null;
  var outletLeaderboardObserver = null;
  var salesContribObserver = null;
  var paymentModeObserver = null;
  var salesHeatmapObserver = null;
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
    if (salesTrendObserver) {
      try { salesTrendObserver.disconnect(); } catch (e) {}
      salesTrendObserver = null;
    }
    if (window.__mdDashSalesTrendObserver) {
      try { window.__mdDashSalesTrendObserver.disconnect(); } catch (e) {}
      window.__mdDashSalesTrendObserver = null;
    }
    if (kpiSparkObserver) {
      try { kpiSparkObserver.disconnect(); } catch (e) {}
      kpiSparkObserver = null;
    }
    if (window.__mdDashKpiSparkObserver) {
      try { window.__mdDashKpiSparkObserver.disconnect(); } catch (e) {}
      window.__mdDashKpiSparkObserver = null;
    }
    if (outletLeaderboardObserver) {
      try { outletLeaderboardObserver.disconnect(); } catch (e) {}
      outletLeaderboardObserver = null;
    }
    if (window.__mdDashOutletLeaderboardObserver) {
      try { window.__mdDashOutletLeaderboardObserver.disconnect(); } catch (e) {}
      window.__mdDashOutletLeaderboardObserver = null;
    }
    if (salesContribObserver) {
      try { salesContribObserver.disconnect(); } catch (e) {}
      salesContribObserver = null;
    }
    if (window.__mdDashSalesContribObserver) {
      try { window.__mdDashSalesContribObserver.disconnect(); } catch (e) {}
      window.__mdDashSalesContribObserver = null;
    }
    if (paymentModeObserver) {
      try { paymentModeObserver.disconnect(); } catch (e) {}
      paymentModeObserver = null;
    }
    if (window.__mdDashPaymentModeObserver) {
      try { window.__mdDashPaymentModeObserver.disconnect(); } catch (e) {}
      window.__mdDashPaymentModeObserver = null;
    }
    if (salesHeatmapObserver) {
      try { salesHeatmapObserver.disconnect(); } catch (e) {}
      salesHeatmapObserver = null;
    }
    if (window.__mdDashSalesHeatmapObserver) {
      try { window.__mdDashSalesHeatmapObserver.disconnect(); } catch (e) {}
      window.__mdDashSalesHeatmapObserver = null;
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

  function salesTrendOption(agg, opts) {
    salesTrendPoints = agg.points || [];
    var values = agg.values || [];
    var pointCount = values.length;
    return {
      // Line path is revealed via CSS clip wipe on scroll-in (not ECharts blink).
      animation: false,
      animationDuration: 0,
      animationDurationUpdate: 0,
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
        data: values,
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        showSymbol: pointCount > 0 && pointCount <= 45,
        animation: false,
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

  function preferReducedMotion() {
    try {
      return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    } catch (e) {
      return false;
    }
  }

  function remountTrendChart(option) {
    var el = document.getElementById('rdx-chart-trend');
    if (!el || typeof echarts === 'undefined') return null;
    var existing = echarts.getInstanceByDom(el);
    if (existing) {
      try { existing.dispose(); } catch (e) {}
      charts = charts.filter(function (c) { return c !== existing; });
    }
    return mount('rdx-chart-trend', option);
  }

  function playSalesTrendEntrance() {
    var card = document.querySelector('[data-md-sales-trend]');
    if (!card) return;
    card.classList.remove('is-entering');
    void card.offsetWidth;
    if (preferReducedMotion()) return;
    card.classList.add('is-entering');
  }

  function setSalesTrendStatValues(mode) {
    var nodes = document.querySelectorAll('[data-md-sales-trend] .rdx-st-stat-value[data-value]');
    nodes.forEach(function (el) {
      var target = parseFloat(el.getAttribute('data-value') || '0');
      if (!isFinite(target)) return;
      el.textContent = mode === 'zero' ? fmt(0) : fmt(target);
    });
  }

  function animateSalesTrendStats() {
    var nodes = document.querySelectorAll('[data-md-sales-trend] .rdx-st-stat-value[data-value]');
    if (!nodes.length) return;
    if (preferReducedMotion()) {
      setSalesTrendStatValues('final');
      return;
    }
    nodes.forEach(function (el, index) {
      var target = parseFloat(el.getAttribute('data-value') || '0');
      if (!isFinite(target)) return;
      el.textContent = fmt(0);
      window.setTimeout(function () {
        var duration = 900;
        var startTime = null;
        function step(ts) {
          if (!startTime) startTime = ts;
          var progress = Math.min((ts - startTime) / duration, 1);
          var eased = 1 - Math.pow(1 - progress, 3);
          el.textContent = fmt(target * eased);
          if (progress < 1) requestAnimationFrame(step);
        }
        requestAnimationFrame(step);
      }, index * 90);
    });
  }

  function paintSalesTrendChart(series) {
    var card = document.querySelector('[data-md-sales-trend]');
    var mask = card && card.querySelector('[data-md-st-chart-mask]');
    var el = document.getElementById('rdx-chart-trend');
    if (!mask || !el) {
      remountTrendChart(salesTrendOption(series));
      return;
    }

    // Open mask to full width so ECharts can measure & paint correctly.
    mask.style.width = '100%';
    remountTrendChart(salesTrendOption(series));

    var fullW = Math.max(Math.floor(mask.getBoundingClientRect().width), 320);
    var fullH = Math.max(el.clientHeight || 0, 280);
    el.style.width = fullW + 'px';
    el.style.minWidth = fullW + 'px';
    el.style.maxWidth = fullW + 'px';

    var inst = typeof echarts !== 'undefined' ? echarts.getInstanceByDom(el) : null;
    if (inst) {
      try { inst.resize({ width: fullW, height: fullH }); } catch (e) {}
    }

    // Collapse again until scroll-in wipe (JS-driven, not CSS !important).
    if (card && card.classList.contains('is-pending') && !preferReducedMotion()) {
      mask.style.overflow = 'hidden';
      mask.style.width = '0px';
    }
  }

  function wipeSalesTrendChart() {
    var card = document.querySelector('[data-md-sales-trend]');
    var mask = card && card.querySelector('[data-md-st-chart-mask]');
    var el = document.getElementById('rdx-chart-trend');
    if (!mask || !el) return;

    var fullW = parseInt(el.style.width, 10);
    if (!fullW) {
      fullW = Math.max(
        Math.floor((card.querySelector('.rdx-st-stats') || card).getBoundingClientRect().width),
        320
      );
      el.style.width = fullW + 'px';
      el.style.minWidth = fullW + 'px';
      el.style.maxWidth = fullW + 'px';
    }
    var fullH = Math.max(el.clientHeight || 0, 280);
    var inst = typeof echarts !== 'undefined' ? echarts.getInstanceByDom(el) : null;
    if (inst) {
      try { inst.resize({ width: fullW, height: fullH }); } catch (e) {}
    }

    if (preferReducedMotion()) {
      mask.style.width = '100%';
      el.style.width = '';
      el.style.minWidth = '';
      el.style.maxWidth = '';
      if (inst) {
        try { inst.resize(); } catch (e) {}
      }
      return;
    }

    mask.style.overflow = 'hidden';
    mask.style.width = '0px';
    void mask.offsetWidth;

    var duration = 2200;
    var startTime = null;
    function step(ts) {
      if (!startTime) startTime = ts;
      var progress = Math.min((ts - startTime) / duration, 1);
      var eased = 1 - Math.pow(1 - progress, 3);
      mask.style.width = Math.round(fullW * eased) + 'px';
      if (progress < 1) {
        requestAnimationFrame(step);
        return;
      }
      mask.style.width = '100%';
      el.style.width = '';
      el.style.minWidth = '';
      el.style.maxWidth = '';
      if (inst) {
        try { inst.resize(); } catch (e) {}
      }
    }
    window.setTimeout(function () {
      requestAnimationFrame(step);
    }, 280);
  }

  function revealSalesTrend(series) {
    var card = document.querySelector('[data-md-sales-trend]');
    if (card) {
      if (card.getAttribute('data-md-st-revealed') === '1') return;
      card.setAttribute('data-md-st-revealed', '1');
      card.classList.remove('is-pending');
    }
    var el = document.getElementById('rdx-chart-trend');
    var inst = el && typeof echarts !== 'undefined' ? echarts.getInstanceByDom(el) : null;
    if (!inst) {
      paintSalesTrendChart(series);
    }
    playSalesTrendEntrance();
    animateSalesTrendStats();
    wipeSalesTrendChart();
  }

  function renderSalesTrend() {
    var card = document.querySelector('[data-md-sales-trend]');
    var series = buildSalesSeries(DATA.daily_series || []);

    if (card) {
      card.removeAttribute('data-md-st-revealed');
      card.classList.remove('is-entering', 'is-entered');
      card.classList.add('is-pending');
    }

    setSalesTrendStatValues(preferReducedMotion() ? 'final' : 'zero');
    paintSalesTrendChart(series);

    if (!card || preferReducedMotion()) {
      if (card) {
        card.classList.remove('is-pending');
        card.setAttribute('data-md-st-revealed', '1');
      }
      setSalesTrendStatValues('final');
      var mask = card && card.querySelector('[data-md-st-chart-mask]');
      if (mask) mask.style.width = '100%';
      var el = document.getElementById('rdx-chart-trend');
      if (el) {
        el.style.width = '';
        el.style.minWidth = '';
        el.style.maxWidth = '';
      }
      return;
    }

    if (typeof IntersectionObserver === 'undefined') {
      revealSalesTrend(series);
      return;
    }

    if (salesTrendObserver) {
      try { salesTrendObserver.disconnect(); } catch (e) {}
    }
    salesTrendObserver = new IntersectionObserver(
      function (entries) {
        for (var i = 0; i < entries.length; i++) {
          if (!entries[i].isIntersecting) continue;
          revealSalesTrend(series);
          if (salesTrendObserver) {
            try { salesTrendObserver.disconnect(); } catch (e) {}
            salesTrendObserver = null;
            window.__mdDashSalesTrendObserver = null;
          }
          break;
        }
      },
      { threshold: 0.28, rootMargin: '0px 0px -10% 0px' }
    );
    window.__mdDashSalesTrendObserver = salesTrendObserver;
    salesTrendObserver.observe(card);
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
    if (series.length === 1) {
      series = [series[0], {
        date: series[0].date,
        value: series[0].value,
        change_pct: null,
      }];
    }
    var values = series.map(function (x) { return Number(x.value) || 0; });
    var lo = values.length ? Math.min.apply(null, values) : 0;
    var hi = values.length ? Math.max.apply(null, values) : 0;
    var yAxis = { type: 'value', show: false };
    if (!values.length || lo === hi) {
      var mid = values.length ? lo : 0;
      var pad = Math.max(Math.abs(mid) * 0.15, 1);
      yAxis.min = mid - pad;
      yAxis.max = mid + pad;
      yAxis.scale = false;
    } else {
      yAxis.scale = true;
    }
    return {
      animation: false,
      animationDuration: 0,
      animationDurationUpdate: 0,
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
      yAxis: yAxis,
      series: [{
        type: 'line',
        data: values,
        smooth: values.length > 2,
        symbol: 'none',
        animation: false,
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

  function paintKpiSparks() {
    var masks = document.querySelectorAll('[data-md-kpi-spark-mask]');
    masks.forEach(function (mask, i) {
      var el = document.getElementById('rdx-spark-' + i);
      if (!el) return;
      mask.style.width = 'calc(100% - 24px)';
      mount('rdx-spark-' + i, sparklineOption((DATA.kpis || [])[i] || {}));
      var fullW = Math.max(Math.floor(mask.getBoundingClientRect().width), 80);
      el.style.width = fullW + 'px';
      el.style.minWidth = fullW + 'px';
      el.style.maxWidth = fullW + 'px';
      var inst = typeof echarts !== 'undefined' ? echarts.getInstanceByDom(el) : null;
      if (inst) {
        try { inst.resize({ width: fullW, height: 44 }); } catch (e) {}
      }
      if (!preferReducedMotion()) {
        mask.style.overflow = 'hidden';
        mask.style.width = '0px';
      }
    });
  }

  function wipeKpiSparkMask(mask, index) {
    var el = mask.querySelector('.rdx-spark');
    if (!el) return;
    var fullW = parseInt(el.style.width, 10);
    if (!fullW) {
      fullW = Math.max(Math.floor(mask.parentElement.getBoundingClientRect().width - 24), 80);
      el.style.width = fullW + 'px';
      el.style.minWidth = fullW + 'px';
      el.style.maxWidth = fullW + 'px';
    }
    var inst = typeof echarts !== 'undefined' ? echarts.getInstanceByDom(el) : null;
    if (inst) {
      try { inst.resize({ width: fullW, height: 44 }); } catch (e) {}
    }

    if (preferReducedMotion()) {
      mask.style.width = 'calc(100% - 24px)';
      el.style.width = '';
      el.style.minWidth = '';
      el.style.maxWidth = '';
      if (inst) {
        try { inst.resize(); } catch (e) {}
      }
      return;
    }

    mask.style.overflow = 'hidden';
    mask.style.width = '0px';
    void mask.offsetWidth;

    var duration = 1400;
    var startDelay = index * 90;
    window.setTimeout(function () {
      var startTime = null;
      function step(ts) {
        if (!startTime) startTime = ts;
        var progress = Math.min((ts - startTime) / duration, 1);
        var eased = 1 - Math.pow(1 - progress, 3);
        mask.style.width = Math.round(fullW * eased) + 'px';
        if (progress < 1) {
          requestAnimationFrame(step);
          return;
        }
        mask.style.width = 'calc(100% - 24px)';
        el.style.width = '';
        el.style.minWidth = '';
        el.style.maxWidth = '';
        if (inst) {
          try { inst.resize(); } catch (e) {}
        }
      }
      requestAnimationFrame(step);
    }, startDelay);
  }

  function revealKpiSparks() {
    var grid = document.querySelector('.rdx-kpi-grid');
    if (grid && grid.getAttribute('data-md-kpi-revealed') === '1') return;
    if (grid) grid.setAttribute('data-md-kpi-revealed', '1');
    animateKpiValues();
    document.querySelectorAll('[data-md-kpi-spark-mask]').forEach(function (mask, i) {
      wipeKpiSparkMask(mask, i);
    });
  }

  function renderKpiSparks() {
    var grid = document.querySelector('.rdx-kpi-grid');
    if (grid) grid.removeAttribute('data-md-kpi-revealed');
    paintKpiSparks();

    if (!grid || preferReducedMotion()) {
      revealKpiSparks();
      return;
    }

    if (typeof IntersectionObserver === 'undefined') {
      revealKpiSparks();
      return;
    }

    if (kpiSparkObserver) {
      try { kpiSparkObserver.disconnect(); } catch (e) {}
    }
    kpiSparkObserver = new IntersectionObserver(
      function (entries) {
        for (var i = 0; i < entries.length; i++) {
          if (!entries[i].isIntersecting) continue;
          revealKpiSparks();
          if (kpiSparkObserver) {
            try { kpiSparkObserver.disconnect(); } catch (e) {}
            kpiSparkObserver = null;
            window.__mdDashKpiSparkObserver = null;
          }
          break;
        }
      },
      { threshold: 0.2, rootMargin: '0px 0px -5% 0px' }
    );
    window.__mdDashKpiSparkObserver = kpiSparkObserver;
    kpiSparkObserver.observe(grid);
  }

  renderKpiSparks();

  renderSalesTrend();

  function playOutletLeaderboardEntrance() {
    var card = document.querySelector('[data-md-co-leaderboard]');
    if (!card) return;
    card.classList.remove('is-entering');
    void card.offsetWidth;
    if (preferReducedMotion()) return;
    card.classList.add('is-entering');
  }

  function animateOutletBars() {
    var fills = document.querySelectorAll('[data-md-co-bar-fill]');
    if (!fills.length) return;
    fills.forEach(function (el, index) {
      var target = parseFloat(el.getAttribute('data-width') || '0');
      if (!isFinite(target)) target = 0;
      el.style.width = '0%';
      if (preferReducedMotion()) {
        el.style.width = target + '%';
        return;
      }
      window.setTimeout(function () {
        var duration = 1400;
        var startTime = null;
        function step(ts) {
          if (!startTime) startTime = ts;
          var progress = Math.min((ts - startTime) / duration, 1);
          var eased = 1 - Math.pow(1 - progress, 3);
          el.style.width = (target * eased) + '%';
          if (progress < 1) requestAnimationFrame(step);
        }
        requestAnimationFrame(step);
      }, index * 100);
    });
  }

  function revealOutletLeaderboard() {
    var card = document.querySelector('[data-md-co-leaderboard]');
    if (!card) return;
    if (card.getAttribute('data-md-co-revealed') === '1') return;
    card.setAttribute('data-md-co-revealed', '1');
    card.classList.remove('is-pending');
    playOutletLeaderboardEntrance();
    animateOutletBars();
  }

  function renderOutletLeaderboard() {
    var card = document.querySelector('[data-md-co-leaderboard]');
    if (!card) return;
    card.removeAttribute('data-md-co-revealed');
    card.classList.remove('is-entering');
    card.classList.add('is-pending');
    document.querySelectorAll('[data-md-co-bar-fill]').forEach(function (el) {
      el.style.width = preferReducedMotion()
        ? ((el.getAttribute('data-width') || '0') + '%')
        : '0%';
    });

    if (preferReducedMotion()) {
      card.classList.remove('is-pending');
      revealOutletLeaderboard();
      return;
    }

    if (typeof IntersectionObserver === 'undefined') {
      revealOutletLeaderboard();
      return;
    }

    if (outletLeaderboardObserver) {
      try { outletLeaderboardObserver.disconnect(); } catch (e) {}
    }
    outletLeaderboardObserver = new IntersectionObserver(
      function (entries) {
        for (var i = 0; i < entries.length; i++) {
          if (!entries[i].isIntersecting) continue;
          revealOutletLeaderboard();
          if (outletLeaderboardObserver) {
            try { outletLeaderboardObserver.disconnect(); } catch (e) {}
            outletLeaderboardObserver = null;
            window.__mdDashOutletLeaderboardObserver = null;
          }
          break;
        }
      },
      { threshold: 0.25, rootMargin: '0px 0px -8% 0px' }
    );
    window.__mdDashOutletLeaderboardObserver = outletLeaderboardObserver;
    outletLeaderboardObserver.observe(card);
  }

  renderOutletLeaderboard();

  var contrib = DATA.sales_contribution || { entries: [] };
  var contribItems = contrib.entries || [];

  function salesContribDonutOption(animated) {
    return {
      animation: !!animated,
      animationType: 'expansion',
      animationDuration: animated ? 1400 : 0,
      animationEasing: 'cubicOut',
      animationDelay: animated
        ? function (idx) {
            return idx * 120;
          }
        : 0,
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
        radius: ['64%', '86%'],
        center: ['50%', '50%'],
        padAngle: 2.5,
        itemStyle: { borderRadius: 6 },
        label: { show: false },
        labelLine: { show: false },
        animationType: 'expansion',
        animationDuration: animated ? 1400 : 0,
        data: contribItems.map(function (x) {
          return { name: x.name, value: x.sales, itemStyle: { color: x.color } };
        }),
      }],
    };
  }

  function remountDonut(option) {
    var el = document.getElementById('rdx-chart-donut');
    if (!el || typeof echarts === 'undefined') return null;
    var existing = echarts.getInstanceByDom(el);
    if (existing) {
      try { existing.dispose(); } catch (e) {}
      charts = charts.filter(function (c) { return c !== existing; });
    }
    return mount('rdx-chart-donut', option);
  }

  function playSalesContribEntrance() {
    var card = document.querySelector('[data-md-sales-contrib]');
    if (!card) return;
    card.classList.remove('is-entering');
    void card.offsetWidth;
    if (preferReducedMotion()) return;
    card.classList.add('is-entering');
  }

  function revealSalesContrib() {
    var card = document.querySelector('[data-md-sales-contrib]');
    if (!card) return;
    if (card.getAttribute('data-md-sc-revealed') === '1') return;
    card.setAttribute('data-md-sc-revealed', '1');
    card.classList.remove('is-pending');
    playSalesContribEntrance();
    remountDonut(salesContribDonutOption(!preferReducedMotion()));
  }

  function renderSalesContrib() {
    var card = document.querySelector('[data-md-sales-contrib]');
    if (!card) {
      remountDonut(salesContribDonutOption(false));
      return;
    }
    card.removeAttribute('data-md-sc-revealed');
    card.classList.remove('is-entering');
    card.classList.add('is-pending');
    // Keep chart shell ready but empty of motion until scroll-in.
    remountDonut(salesContribDonutOption(false));

    if (preferReducedMotion()) {
      card.classList.remove('is-pending');
      revealSalesContrib();
      return;
    }

    if (typeof IntersectionObserver === 'undefined') {
      revealSalesContrib();
      return;
    }

    if (salesContribObserver) {
      try { salesContribObserver.disconnect(); } catch (e) {}
    }
    salesContribObserver = new IntersectionObserver(
      function (entries) {
        for (var i = 0; i < entries.length; i++) {
          if (!entries[i].isIntersecting) continue;
          revealSalesContrib();
          if (salesContribObserver) {
            try { salesContribObserver.disconnect(); } catch (e) {}
            salesContribObserver = null;
            window.__mdDashSalesContribObserver = null;
          }
          break;
        }
      },
      { threshold: 0.25, rootMargin: '0px 0px -8% 0px' }
    );
    window.__mdDashSalesContribObserver = salesContribObserver;
    salesContribObserver.observe(card);
  }

  renderSalesContrib();

  function digitalCashOption(stack) {
    stack = stack || [];
    return {
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
    };
  }

  function remountPaymentModeChart(option) {
    var el = document.getElementById('rdx-chart-digital-cash');
    if (!el || typeof echarts === 'undefined') return null;
    var existing = echarts.getInstanceByDom(el);
    if (existing) {
      try { existing.dispose(); } catch (e) {}
      charts = charts.filter(function (c) { return c !== existing; });
    }
    return mount('rdx-chart-digital-cash', option);
  }

  function fmtPct(v) {
    var n = Number(v);
    if (!isFinite(n)) n = 0;
    return (Math.round(n * 10) / 10).toFixed(1) + '%';
  }

  function playPaymentModeEntrance() {
    var card = document.querySelector('[data-md-payment-mode]');
    if (!card) return;
    card.classList.remove('is-entering');
    void card.offsetWidth;
    if (preferReducedMotion()) return;
    card.classList.add('is-entering');
  }

  function setPaymentModeKpiValues(mode) {
    var nodes = document.querySelectorAll('[data-md-payment-mode] [data-md-pm-value][data-value]');
    nodes.forEach(function (el) {
      var target = parseFloat(el.getAttribute('data-value') || '0');
      if (!isFinite(target)) return;
      el.textContent = mode === 'zero' ? fmtPct(0) : fmtPct(target);
    });
  }

  function animatePaymentModeKpis() {
    var nodes = document.querySelectorAll('[data-md-payment-mode] [data-md-pm-value][data-value]');
    if (!nodes.length) return;
    if (preferReducedMotion()) {
      setPaymentModeKpiValues('final');
      return;
    }
    nodes.forEach(function (el, index) {
      var target = parseFloat(el.getAttribute('data-value') || '0');
      if (!isFinite(target)) return;
      el.textContent = fmtPct(0);
      window.setTimeout(function () {
        var duration = 900;
        var startTime = null;
        function step(ts) {
          if (!startTime) startTime = ts;
          var progress = Math.min((ts - startTime) / duration, 1);
          var eased = 1 - Math.pow(1 - progress, 3);
          el.textContent = fmtPct(target * eased);
          if (progress < 1) requestAnimationFrame(step);
        }
        requestAnimationFrame(step);
      }, index * 90);
    });
  }

  function paymentModeChartWidth(card, mask) {
    var col = (card && card.querySelector('.rdx-pm-chart-col')) || card;
    var host = mask || col;
    var hostW = host ? Math.floor(host.getBoundingClientRect().width) : 0;
    var colW = col ? Math.floor(col.getBoundingClientRect().width) : 0;
    var cardW = card ? Math.floor(card.getBoundingClientRect().width) : 0;
    var w = Math.max(hostW, colW, 0);
    if (cardW > 0) w = Math.min(w || cardW, cardW);
    if (!w) w = 240;
    return Math.max(160, Math.min(w, cardW || w));
  }

  function paintPaymentModeChart(stack) {
    var card = document.querySelector('[data-md-payment-mode]');
    var mask = card && card.querySelector('[data-md-pm-chart-mask]');
    var el = document.getElementById('rdx-chart-digital-cash');
    if (!mask || !el) {
      remountPaymentModeChart(digitalCashOption(stack));
      return;
    }

    mask.style.width = '100%';
    mask.style.maxWidth = '100%';
    el.style.width = '100%';
    el.style.minWidth = '0';
    el.style.maxWidth = '100%';
    remountPaymentModeChart(digitalCashOption(stack));

    var fullW = paymentModeChartWidth(card, mask);
    var fullH = Math.max(el.clientHeight || 0, 200);
    el.style.width = fullW + 'px';
    el.style.minWidth = '0';
    el.style.maxWidth = '100%';

    var inst = typeof echarts !== 'undefined' ? echarts.getInstanceByDom(el) : null;
    if (inst) {
      try { inst.resize({ width: fullW, height: fullH }); } catch (e) {}
    }

    if (card && card.classList.contains('is-pending') && !preferReducedMotion()) {
      mask.style.overflow = 'hidden';
      mask.style.width = '0px';
    }
  }

  function wipePaymentModeChart() {
    var card = document.querySelector('[data-md-payment-mode]');
    var mask = card && card.querySelector('[data-md-pm-chart-mask]');
    var el = document.getElementById('rdx-chart-digital-cash');
    if (!mask || !el) return;

    var fullW = paymentModeChartWidth(card, mask);
    el.style.width = fullW + 'px';
    el.style.minWidth = '0';
    el.style.maxWidth = '100%';
    var fullH = Math.max(el.clientHeight || 0, 200);
    var inst = typeof echarts !== 'undefined' ? echarts.getInstanceByDom(el) : null;
    if (inst) {
      try { inst.resize({ width: fullW, height: fullH }); } catch (e) {}
    }

    if (preferReducedMotion()) {
      mask.style.width = '100%';
      el.style.width = '';
      el.style.minWidth = '';
      el.style.maxWidth = '';
      if (inst) {
        try { inst.resize(); } catch (e) {}
      }
      return;
    }

    mask.style.overflow = 'hidden';
    mask.style.width = '0px';
    void mask.offsetWidth;

    var duration = 2200;
    var startTime = null;
    function step(ts) {
      if (!startTime) startTime = ts;
      var progress = Math.min((ts - startTime) / duration, 1);
      var eased = 1 - Math.pow(1 - progress, 3);
      mask.style.width = Math.round(fullW * eased) + 'px';
      if (progress < 1) {
        requestAnimationFrame(step);
        return;
      }
      mask.style.width = '100%';
      el.style.width = '';
      el.style.minWidth = '';
      el.style.maxWidth = '';
      if (inst) {
        try { inst.resize(); } catch (e) {}
      }
    }
    window.setTimeout(function () {
      requestAnimationFrame(step);
    }, 280);
  }

  function revealPaymentMode(stack) {
    var card = document.querySelector('[data-md-payment-mode]');
    if (card) {
      if (card.getAttribute('data-md-pm-revealed') === '1') return;
      card.setAttribute('data-md-pm-revealed', '1');
      card.classList.remove('is-pending');
    }
    var el = document.getElementById('rdx-chart-digital-cash');
    var inst = el && typeof echarts !== 'undefined' ? echarts.getInstanceByDom(el) : null;
    if (!inst) {
      paintPaymentModeChart(stack);
    }
    playPaymentModeEntrance();
    animatePaymentModeKpis();
    wipePaymentModeChart();
  }

  function renderPaymentMode() {
    var card = document.querySelector('[data-md-payment-mode]');
    var stack = DATA.digital_cash_stack || [];

    if (card) {
      card.removeAttribute('data-md-pm-revealed');
      card.classList.remove('is-entering', 'is-entered');
      card.classList.add('is-pending');
    }

    setPaymentModeKpiValues(preferReducedMotion() ? 'final' : 'zero');
    paintPaymentModeChart(stack);

    if (!card || preferReducedMotion()) {
      if (card) {
        card.classList.remove('is-pending');
        card.setAttribute('data-md-pm-revealed', '1');
      }
      setPaymentModeKpiValues('final');
      var mask = card && card.querySelector('[data-md-pm-chart-mask]');
      if (mask) mask.style.width = '100%';
      var el = document.getElementById('rdx-chart-digital-cash');
      if (el) {
        el.style.width = '';
        el.style.minWidth = '';
        el.style.maxWidth = '';
      }
      return;
    }

    if (typeof IntersectionObserver === 'undefined') {
      revealPaymentMode(stack);
      return;
    }

    if (paymentModeObserver) {
      try { paymentModeObserver.disconnect(); } catch (e) {}
    }
    paymentModeObserver = new IntersectionObserver(
      function (entries) {
        for (var i = 0; i < entries.length; i++) {
          if (!entries[i].isIntersecting) continue;
          revealPaymentMode(stack);
          if (paymentModeObserver) {
            try { paymentModeObserver.disconnect(); } catch (e) {}
            paymentModeObserver = null;
            window.__mdDashPaymentModeObserver = null;
          }
          break;
        }
      },
      { threshold: 0.28, rootMargin: '0px 0px -10% 0px' }
    );
    window.__mdDashPaymentModeObserver = paymentModeObserver;
    paymentModeObserver.observe(card);
  }

  renderPaymentMode();

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

  function paintSalesHeatmap() {
    var root = document.getElementById('rdx-sales-heatmap');
    var tip = document.getElementById('rdx-heatmap-tooltip');
    var hm = DATA.heatmap;
    if (!root || !hm || !hm.weeks || !hm.weeks.length) {
      if (root) root.innerHTML = '<p style="color:#94a3b8;font-size:13px;padding:12px 0">No sales data for this period.</p>';
      return false;
    }

    var heatmapTip = tip ? createHeatmapTooltip(tip) : null;

    root.innerHTML = '';
    root.appendChild(document.createElement('div')).className = 'rdx-heatmap-corner';
    (hm.columns || []).forEach(function (col, colIdx) {
      var head = document.createElement('div');
      head.className = 'rdx-heatmap-col-head';
      head.style.setProperty('--rdx-hm-i', String(colIdx));
      head.textContent = col;
      root.appendChild(head);
    });

    hm.weeks.forEach(function (week, weekIdx) {
      var label = document.createElement('button');
      label.type = 'button';
      label.className = 'rdx-heatmap-row-label';
      label.style.setProperty('--rdx-hm-i', String(weekIdx));
      label.textContent = week.label;
      label.title = 'Filter to ' + week.label;
      label.addEventListener('click', function () {
        applyDateFilter(week.filter_from, week.filter_to);
      });
      root.appendChild(label);

      (week.cells || []).forEach(function (cell, cellIdx) {
        var el = document.createElement('div');
        el.className = 'rdx-heatmap-cell';
        el.style.setProperty('--rdx-hm-i', String(weekIdx * 7 + cellIdx));
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
    return true;
  }

  function playSalesHeatmapEntrance() {
    var card = document.querySelector('[data-md-sales-heatmap]');
    if (!card) return;
    card.classList.remove('is-entering', 'is-entered');
    void card.offsetWidth;
    if (preferReducedMotion()) {
      card.classList.add('is-entered');
      return;
    }
    card.classList.add('is-entering');
    var maxI = 0;
    card.querySelectorAll('.rdx-heatmap-cell').forEach(function (el) {
      var i = parseInt(el.style.getPropertyValue('--rdx-hm-i'), 10);
      if (isFinite(i) && i > maxI) maxI = i;
    });
    // Drop is-entering after cascade so hover scale is not locked by fill-mode.
    window.setTimeout(function () {
      card.classList.remove('is-entering');
      card.classList.add('is-entered');
    }, 160 + maxI * 38 + 520);
  }

  function revealSalesHeatmap() {
    var card = document.querySelector('[data-md-sales-heatmap]');
    if (card) {
      if (card.getAttribute('data-md-hm-revealed') === '1') return;
      card.setAttribute('data-md-hm-revealed', '1');
      card.classList.remove('is-pending');
    }
    playSalesHeatmapEntrance();
  }

  function renderSalesHeatmap() {
    var card = document.querySelector('[data-md-sales-heatmap]');
    if (card) {
      card.removeAttribute('data-md-hm-revealed');
      card.classList.remove('is-entering', 'is-entered');
      card.classList.add('is-pending');
    }

    var painted = paintSalesHeatmap();
    if (!painted) {
      if (card) card.classList.remove('is-pending');
      return;
    }

    if (!card || preferReducedMotion()) {
      if (card) {
        card.classList.remove('is-pending');
        card.setAttribute('data-md-hm-revealed', '1');
      }
      return;
    }

    if (typeof IntersectionObserver === 'undefined') {
      revealSalesHeatmap();
      return;
    }

    if (salesHeatmapObserver) {
      try { salesHeatmapObserver.disconnect(); } catch (e) {}
    }
    salesHeatmapObserver = new IntersectionObserver(
      function (entries) {
        for (var i = 0; i < entries.length; i++) {
          if (!entries[i].isIntersecting) continue;
          revealSalesHeatmap();
          if (salesHeatmapObserver) {
            try { salesHeatmapObserver.disconnect(); } catch (e) {}
            salesHeatmapObserver = null;
            window.__mdDashSalesHeatmapObserver = null;
          }
          break;
        }
      },
      { threshold: 0.28, rootMargin: '0px 0px -10% 0px' }
    );
    window.__mdDashSalesHeatmapObserver = salesHeatmapObserver;
    salesHeatmapObserver.observe(card);
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
