#!/usr/bin/env python3
from pathlib import Path

ROOT = Path("/Users/rajesh/Documents/New project/Hotel Bell elite")
js_path = ROOT / "static" / "main_dashboard_charts.js"
css_path = ROOT / "static" / "main_dashboard_analytics.css"
preview = ROOT / "_preview" / "financial_flow_preview.html"
js = js_path.read_text()
css = css_path.read_text()

old_ff = '''  function ffNodeHtml(opts) {
    var cls = 'rdx-ff-node' + (opts.extraClass ? ' ' + opts.extraClass : '');
    var stripe = opts.stripe
      ? '<span class="rdx-ff-node-stripe" style="background:' + ffEsc(opts.stripe) + '"></span>'
      : '';
    var pctHtml = opts.showPct === false
      ? ''
      : '<span class="rdx-ff-node-pct">(' + ffEsc(opts.pct) + '%)</span>';
    return (
      '<div class="' + cls + '" data-ff-id="' + ffEsc(opts.id) + '"' +
      (opts.tone ? ' data-ff-tone="' + ffEsc(opts.tone) + '"' : '') +
      (opts.col != null ? ' data-ff-col="' + ffEsc(opts.col) + '"' : '') +
      (opts.group ? ' data-ff-group="' + ffEsc(opts.group) + '"' : '') + '>' +
        stripe +
        '<div class="rdx-ff-node-body">' +
          '<span class="rdx-ff-node-name">' + ffEsc(opts.name) + '</span>' +
          '<span class="rdx-ff-node-amt">' + ffEsc(opts.compact) + '</span>' +
          pctHtml +
        '</div>' +
      '</div>'
    );
  }'''

new_ff = '''  function ffNodeHtml(opts) {
    var inline = !!opts.inline;
    var cls = 'rdx-ff-node' + (opts.extraClass ? ' ' + opts.extraClass : '') + (inline ? ' rdx-ff-node--inline' : '');
    var stripe = opts.stripe
      ? '<span class="rdx-ff-node-stripe" style="background:' + ffEsc(opts.stripe) + '"></span>'
      : '';
    var pctHtml = opts.showPct === false
      ? ''
      : '<span class="rdx-ff-node-pct">(' + ffEsc(opts.pct) + '%)</span>';
    var body;
    if (inline) {
      body =
        '<div class="rdx-ff-node-body rdx-ff-node-body--inline">' +
          '<span class="rdx-ff-node-name">' + ffEsc(opts.name) + '</span>' +
          '<span class="rdx-ff-node-sep" aria-hidden="true">-</span>' +
          '<span class="rdx-ff-node-amt">' + ffEsc(opts.compact) + '</span>' +
          (pctHtml ? '<span class="rdx-ff-node-inline-gap" aria-hidden="true"></span>' + pctHtml : '') +
        '</div>';
    } else {
      body =
        '<div class="rdx-ff-node-body">' +
          '<span class="rdx-ff-node-name">' + ffEsc(opts.name) + '</span>' +
          '<span class="rdx-ff-node-amt">' + ffEsc(opts.compact) + '</span>' +
          pctHtml +
        '</div>';
    }
    return (
      '<div class="' + cls + '" data-ff-id="' + ffEsc(opts.id) + '"' +
      (opts.tone ? ' data-ff-tone="' + ffEsc(opts.tone) + '"' : '') +
      (opts.col != null ? ' data-ff-col="' + ffEsc(opts.col) + '"' : '') +
      (opts.group ? ' data-ff-group="' + ffEsc(opts.group) + '"' : '') + '>' +
        stripe +
        body +
      '</div>'
    );
  }'''

if old_ff not in js:
    raise SystemExit('ffNodeHtml block not found exactly')
js = js.replace(old_ff, new_ff, 1)

js = js.replace(
'''      html.push(ffNodeHtml({
        id: 'p-' + idx + '-' + cat.key,
        name: cat.name,
        compact: cat.amount_compact || fmt(cat.amount),
        pct: cat.pct_of_revenue != null ? cat.pct_of_revenue : ffPct(cat.amount, revenue),
        col: 3,
        group: 'purchase',
        extraClass: 'rdx-ff-node--purchase-leaf',
      }));''',
'''      html.push(ffNodeHtml({
        id: 'p-' + idx + '-' + cat.key,
        name: cat.name,
        compact: cat.amount_compact || fmt(cat.amount),
        pct: cat.pct_of_revenue != null ? cat.pct_of_revenue : ffPct(cat.amount, revenue),
        col: 3,
        group: 'purchase',
        inline: true,
        extraClass: 'rdx-ff-node--purchase-leaf',
      }));'''
)
js = js.replace(
'''      html.push(ffNodeHtml({
        id: 'e-' + idx + '-' + cat.key,
        name: cat.name,
        compact: cat.amount_compact || fmt(cat.amount),
        pct: cat.pct_of_revenue != null ? cat.pct_of_revenue : ffPct(cat.amount, revenue),
        col: 3,
        group: 'expense',
        extraClass: 'rdx-ff-node--expense-leaf',
      }));''',
'''      html.push(ffNodeHtml({
        id: 'e-' + idx + '-' + cat.key,
        name: cat.name,
        compact: cat.amount_compact || fmt(cat.amount),
        pct: cat.pct_of_revenue != null ? cat.pct_of_revenue : ffPct(cat.amount, revenue),
        col: 3,
        group: 'expense',
        inline: true,
        extraClass: 'rdx-ff-node--expense-leaf',
      }));'''
)
js = js.replace(
'''      html.push(ffNodeHtml({
        id: 'tax',
        name: 'Tax',
        compact: flow.tax_compact || fmt(tax),
        pct: ffPct(tax, revenue),
        col: 3,
        group: 'output',
        extraClass: 'rdx-ff-node--tax',
      }));''',
'''      html.push(ffNodeHtml({
        id: 'tax',
        name: 'Tax',
        compact: flow.tax_compact || fmt(tax),
        pct: ffPct(tax, revenue),
        col: 3,
        group: 'output',
        inline: true,
        extraClass: 'rdx-ff-node--tax',
      }));'''
)

js = js.replace('var leafH = 52;', 'var leafH = 40;')
js = js.replace('var leafGap = 8;', 'var leafGap = 7;')
js = js.replace('var outLeafH = 52;', 'var outLeafH = 40;')

MARKER = '/* === FF INLINE LEAF ROWS === */'
inline_css = '''
.rdx-ff-node--inline {
  min-height: 40px !important;
  height: auto;
  align-items: center;
}

.rdx-ff-node-body--inline {
  display: flex !important;
  flex-direction: row !important;
  flex-wrap: nowrap;
  align-items: center;
  justify-content: flex-start;
  gap: 6px;
  padding: 8px 12px !important;
  width: 100%;
  min-width: 0;
  overflow: hidden;
}

.rdx-ff-node-body--inline .rdx-ff-node-name {
  flex: 1 1 auto;
  min-width: 0;
  max-width: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.25;
}

.rdx-ff-node-body--inline .rdx-ff-node-sep {
  flex: 0 0 auto;
  color: #94a3b8;
  font-weight: 600;
  font-size: 12px;
  line-height: 1;
}

.rdx-ff-node-body--inline .rdx-ff-node-amt {
  flex: 0 0 auto;
  white-space: nowrap;
  font-size: 12px;
  font-weight: 800;
  line-height: 1.25;
}

.rdx-ff-node-body--inline .rdx-ff-node-pct {
  flex: 0 0 auto;
  white-space: nowrap;
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  line-height: 1.25;
}

.rdx-ff-node-body--inline .rdx-ff-node-inline-gap {
  flex: 0 0 2px;
  width: 2px;
}

.rdx-ff-node--purchase-leaf.rdx-ff-node--inline .rdx-ff-node-amt { color: #1d4ed8; }
.rdx-ff-node--expense-leaf.rdx-ff-node--inline .rdx-ff-node-amt { color: #c2410c; }
.rdx-ff-node--tax.rdx-ff-node--inline .rdx-ff-node-amt { color: #475569; }
'''

if MARKER in css:
    css = css.split(MARKER, 1)[0].rstrip() + '\n\n' + MARKER + '\n' + inline_css.strip() + '\n'
else:
    css = css.rstrip() + '\n\n' + MARKER + '\n' + inline_css.strip() + '\n'

js_path.write_text(js)
css_path.write_text(css)

if preview.exists():
    prev = preview.read_text()
    if old_ff in prev:
        prev = prev.replace(old_ff, new_ff, 1)
    if "extraClass: 'rdx-ff-node--purchase-leaf'" in prev and 'inline: true' not in prev.split('purchase-leaf')[0][-80:]:
        prev = prev.replace(
            "extraClass: 'rdx-ff-node--purchase-leaf',",
            "inline: true,\n        extraClass: 'rdx-ff-node--purchase-leaf',",
        )
        prev = prev.replace(
            "extraClass: 'rdx-ff-node--expense-leaf',",
            "inline: true,\n        extraClass: 'rdx-ff-node--expense-leaf',",
        )
    if MARKER not in prev and '</style>' in prev:
        prev = prev.replace('</style>', MARKER + '\n' + inline_css.strip() + '\n</style>', 1)
    preview.write_text(prev)
    print('OK preview')

print('OK', js_path)
print('inline class', 'rdx-ff-node--inline' in js)
print('leafH40', 'var leafH = 40;' in js)
