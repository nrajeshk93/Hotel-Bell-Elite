  /**
   * FIXED COMPOSITION — absolute card coordinates only.
   * FLOW POSITION ≠ LABEL POSITION: SVG ribbons curve freely; destination
   * cards/labels stay on a fixed 4-column grid. No ECharts/d3 Sankey layout.
   *
   * COL1 sources → COL2 Total Revenue → COL3 hubs (Purchase/Expenses/PBT)
   * → COL4 fixed ranked lists (purchase → expense → Tax/Net Profit)
   * Hubs sit next to their leaf groups (reference composition) while remaining
   * a tight vertical stack — never library auto-placement.
   */
  function layoutFinancialFlowNodes(root, flow) {
    var layout = root.querySelector('.rdx-ff-layout');
    var canvas = root.querySelector('[data-ff-canvas]') || layout;
    if (!layout || !canvas) return;

    var W = Math.max(root.clientWidth || layout.clientWidth || 980, 880);
    var padX = 12;
    var padY = 14;
    var padRight = 14;

    var col0W = 148;
    var col1W = 168;
    var col2W = 168;
    var col3W = 248;

    var gap01 = 18;
    var gap12 = 48;
    var gap23 = 52;
    var used = padX + padRight + col0W + col1W + col2W + col3W + gap01 + gap12 + gap23;
    var leftover = W - used;
    if (leftover > 0) {
      gap12 += Math.round(leftover * 0.4);
      gap23 += Math.round(leftover * 0.45);
      gap01 += Math.round(leftover * 0.1);
    } else if (leftover < 0) {
      var shrink = Math.min(col3W - 210, -leftover);
      col3W -= shrink;
      leftover += shrink;
      if (leftover < 0) {
        gap12 = Math.max(34, gap12 + Math.round(leftover * 0.5));
        gap23 = Math.max(34, gap23 + Math.round(leftover * 0.5));
      }
    }

    var x0 = padX;
    var x1 = x0 + col0W + gap01;
    var x2 = x1 + col1W + gap12;
    var x3 = x2 + col2W + gap23;

    var srcH = 58;
    var srcGap = 10;
    var totalH = 96;
    var hubH = 64;
    var leafH = 52;
    var leafGap = 8;
    var groupGap = 22;
    var outGap = 18;
    var outLeafH = 52;
    var netH = 62;

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
      el.style.maxWidth = 'none';
    }

    function node(id) {
      return root.querySelector('[data-ff-id="' + id + '"]');
    }

    function mid(a, b) { return (a + b) / 2; }

    var y = padY;
    var purchaseTop = y;
    purchaseCats.forEach(function (cat, idx) {
      setBox(node('p-' + idx + '-' + cat.key), x3, y, col3W, leafH);
      y += leafH + leafGap;
    });
    var purchaseBottom = purchaseCats.length ? (y - leafGap) : purchaseTop;
    if (purchaseCats.length) y += groupGap - leafGap;
    else y += 4;

    var expenseTop = y;
    expenseCats.forEach(function (cat, idx) {
      setBox(node('e-' + idx + '-' + cat.key), x3, y, col3W, leafH);
      y += leafH + leafGap;
    });
    var expenseBottom = expenseCats.length ? (y - leafGap) : expenseTop;
    if (expenseCats.length) y += outGap - leafGap;
    else y += 4;

    var taxTop = y;
    if (showTax) {
      setBox(node('tax'), x3, y, col3W, outLeafH);
      y += outLeafH + leafGap;
    }
    var netTop = y;
    if (showNet) {
      setBox(node('net'), x3, y, col3W, netH);
      y += netH;
    }
    var outBottom = y;
    var contentBottom = y + padY;

    var purchaseEl = node('purchase');
    var expenseEl = node('expense');
    var pbtEl = node('pbt');

    var purchaseHubY = purchaseCats.length
      ? mid(purchaseTop, purchaseBottom) - hubH / 2
      : padY;
    var expenseHubY = expenseCats.length
      ? mid(expenseTop, expenseBottom) - hubH / 2
      : purchaseHubY + hubH + 14;
    var pbtHubY = (showTax || showNet)
      ? mid(taxTop, outBottom) - hubH / 2
      : expenseHubY + hubH + 14;

    var minHubGap = 10;
    if (expenseHubY < purchaseHubY + hubH + minHubGap) {
      expenseHubY = purchaseHubY + hubH + minHubGap;
    }
    if (pbtHubY < expenseHubY + hubH + minHubGap) {
      pbtHubY = expenseHubY + hubH + minHubGap;
    }

    if (purchaseEl) setBox(purchaseEl, x2, purchaseHubY, col2W, hubH);
    if (expenseEl) setBox(expenseEl, x2, expenseHubY, col2W, hubH);
    if (pbtEl) setBox(pbtEl, x2, pbtHubY, col2W, hubH);

    var hubTops = [];
    if (purchaseEl) hubTops.push(purchaseHubY);
    if (expenseEl) hubTops.push(expenseHubY);
    if (pbtEl) hubTops.push(pbtHubY);
    var hubClusterTop = hubTops.length ? Math.min.apply(null, hubTops) : padY;
    var hubClusterBottom = hubTops.length ? Math.max.apply(null, hubTops) + hubH : padY + hubH;
    var hubClusterMid = mid(hubClusterTop, hubClusterBottom);

    var totalTop = hubClusterMid - totalH / 2;
    totalTop = Math.max(padY, Math.min(totalTop, Math.max(padY, contentBottom - padY - totalH)));
    setBox(node('total'), x1, totalTop, col1W, totalH);
    var totalMid = totalTop + totalH / 2;

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
      hubClusterBottom + padY,
      pbtHubY + hubH + padY
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
