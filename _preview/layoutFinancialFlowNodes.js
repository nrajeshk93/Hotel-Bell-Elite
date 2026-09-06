  /**
   * FIXED COMPOSITION — absolute card coordinates only.
   * FLOW POSITION ≠ LABEL POSITION: SVG ribbons curve freely; destination
   * cards/labels stay on a fixed 4-column grid. No ECharts/d3 Sankey layout.
   *
   * COL1 sources (compact, even) → COL2 Total Revenue (center hub)
   * → COL3 costs clustered close (Purchase / Expenses / PBT)
   * → COL4 ranked lists (purchase group → expense group → Tax / Net Profit)
   */
  function layoutFinancialFlowNodes(root, flow) {
    var layout = root.querySelector('.rdx-ff-layout');
    var canvas = root.querySelector('[data-ff-canvas]') || layout;
    if (!layout || !canvas) return;

    var W = Math.max(root.clientWidth || layout.clientWidth || 980, 880);
    var padX = 12;
    var padY = 12;
    var padRight = 12;

    // Fixed column widths — leaves stay a compact ranked-list column.
    var col0W = 148;
    var col1W = 166;
    var col2W = 166;
    var col3W = 236;

    // Gaps sized for ribbon curves; leftover width expands gaps (not leaf width).
    var gap01 = 16;
    var gap12 = 52;
    var gap23 = 56;
    var used = padX + padRight + col0W + col1W + col2W + col3W + gap01 + gap12 + gap23;
    var leftover = W - used;
    if (leftover > 0) {
      gap12 += Math.round(leftover * 0.42);
      gap23 += Math.round(leftover * 0.42);
      gap01 += Math.round(leftover * 0.08);
      padRight += Math.max(0, W - (padX + col0W + col1W + col2W + col3W + gap01 + gap12 + gap23 + padRight));
    } else if (leftover < 0) {
      var shrink = Math.min(col3W - 200, -leftover);
      col3W -= shrink;
      leftover += shrink;
      if (leftover < 0) {
        gap12 = Math.max(36, gap12 + Math.round(leftover * 0.5));
        gap23 = Math.max(36, gap23 + Math.round(leftover * 0.5));
      }
    }

    var x0 = padX;
    var x1 = x0 + col0W + gap01;
    var x2 = x1 + col1W + gap12;
    var x3 = x2 + col2W + gap23;

    // Vertical metrics — readable, no font shrinking; ~16:9 via modest height.
    var srcH = 58;
    var srcGap = 12;
    var totalH = 92;
    var hubH = 62;
    var hubGap = 12;      // COL3 close together
    var leafH = 50;
    var leafGap = 7;
    var groupGap = 20;    // clear purchase ↔ expense separation
    var outGap = 16;      // expense ↔ tax/net
    var outLeafH = 52;
    var netH = 60;

    var purchaseCats = ffEnsureOtherLast(
      flow.purchase_categories || [],
      'other_purchase',
      'Other Purchase',
      '#93C5FD'
    );
    var expenseCats = ffEnsureOtherLast(
      flow.expense_categories || [],
      'other_expenses',
      'Other Expenses',
      '#FDBA74'
    );
    var pbt = Number(flow.profit_before_tax || 0);
    var tax = Number(flow.tax || 0);
    var net = Number(flow.net_profit || 0);
    var showTax = pbt > 0 && tax > 0;
    var showNet = pbt > 0 || net !== 0;

    function setBox(el, x, y, w, h) {
      if (!el) return;
      el.style.position = 'absolute';
      el.style.left = Math.round(x) + 'px';
      el.style.top = Math.round(y) + 'px';
      el.style.width = Math.round(w) + 'px';
      if (h) {
        el.style.height = Math.round(h) + 'px';
        el.style.minHeight = Math.round(h) + 'px';
      }
      el.style.margin = '0';
      el.style.right = 'auto';
      el.style.bottom = 'auto';
    }

    function node(id) {
      return root.querySelector('[data-ff-id="' + id + '"]');
    }

    // ── COL4 OUTPUT: fixed ranked lists (labels never follow ribbon flow) ──
    var y = padY;
    purchaseCats.forEach(function (cat, idx) {
      setBox(node('p-' + idx + '-' + cat.key), x3, y, col3W, leafH);
      y += leafH + leafGap;
    });
    if (purchaseCats.length) y += groupGap - leafGap;
    else y += 4;

    expenseCats.forEach(function (cat, idx) {
      setBox(node('e-' + idx + '-' + cat.key), x3, y, col3W, leafH);
      y += leafH + leafGap;
    });
    if (expenseCats.length) y += outGap - leafGap;
    else y += 4;

    if (showTax) {
      setBox(node('tax'), x3, y, col3W, outLeafH);
      y += outLeafH + leafGap;
    }
    if (showNet) {
      setBox(node('net'), x3, y, col3W, netH);
      y += netH;
    }

    var contentBottom = y + padY;

    // ── COL3 COSTS: clustered CLOSE TOGETHER (independent of leaf mids) ──
    var purchaseEl = node('purchase');
    var expenseEl = node('expense');
    var pbtEl = node('pbt');
    var hubEls = [];
    if (purchaseEl) hubEls.push(purchaseEl);
    if (expenseEl) hubEls.push(expenseEl);
    if (pbtEl) hubEls.push(pbtEl);

    var hubClusterH = hubEls.length
      ? hubEls.length * hubH + Math.max(0, hubEls.length - 1) * hubGap
      : hubH;
    var canvasMid = contentBottom / 2;
    var hubTop = canvasMid - hubClusterH / 2;
    hubTop = Math.max(padY, Math.min(hubTop, contentBottom - padY - hubClusterH));

    var hubCursor = hubTop;
    hubEls.forEach(function (el) {
      setBox(el, x2, hubCursor, col2W, hubH);
      hubCursor += hubH + hubGap;
    });
    var hubClusterMid = hubTop + hubClusterH / 2;

    // ── COL2 TOTAL REVENUE: centered on hub cluster (not excessively tall) ──
    var totalTop = hubClusterMid - totalH / 2;
    totalTop = Math.max(padY, Math.min(totalTop, contentBottom - padY - totalH));
    setBox(node('total'), x1, totalTop, col1W, totalH);
    var totalMid = totalTop + totalH / 2;

    // ── COL1 REVENUE: compact evenly-spaced sources, centered on Total ──
    var sources = flow.sources || [];
    var srcCount = sources.length || (node('empty-src') ? 1 : 0);
    var clusterH = srcCount > 0
      ? srcCount * srcH + Math.max(0, srcCount - 1) * srcGap
      : srcH;
    var srcTop = totalMid - clusterH / 2;
    srcTop = Math.max(padY, srcTop);
    if (srcTop + clusterH > contentBottom - padY) {
      srcTop = Math.max(padY, contentBottom - padY - clusterH);
    }
    if (!sources.length) {
      setBox(node('empty-src'), x0, srcTop, col0W, srcH);
    } else {
      sources.forEach(function (src, idx) {
        setBox(node('src-' + src.key), x0, srcTop + idx * (srcH + srcGap), col0W, srcH);
      });
    }

    var neededH = Math.max(
      contentBottom,
      totalTop + totalH + padY,
      srcTop + clusterH + padY,
      hubTop + hubClusterH + padY
    );

    layout.style.height = Math.round(neededH) + 'px';
    layout.style.minHeight = Math.round(neededH) + 'px';
    canvas.style.height = Math.round(neededH) + 'px';
    canvas.style.position = 'relative';
    canvas.style.width = '100%';
    root.style.minHeight = Math.round(neededH + 8) + 'px';
    root.style.height = Math.round(neededH + 8) + 'px';
    root.setAttribute('data-ff-layout', 'fixed-composition-v3');
  }
