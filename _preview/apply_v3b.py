#!/usr/bin/env python3
from pathlib import Path

ROOT = Path("/Users/rajesh/Documents/New project/Hotel Bell elite")
JS = ROOT / "static" / "main_dashboard_charts.js"
CSS = ROOT / "static" / "main_dashboard_analytics.css"
PREVIEW = ROOT / "_preview" / "financial_flow_preview.html"
HERE = Path(__file__).resolve().parent
LAYOUT = (HERE / "layoutFinancialFlowNodes_v3b.js").read_text()

def replace_fn(src: str, fn_name: str, new_fn: str) -> str:
    needle = f"function {fn_name}("
    start = src.find(needle)
    if start < 0:
        raise SystemExit(f"missing {fn_name}")
    jsdoc = src.rfind("/**", 0, start)
    if jsdoc >= 0 and "function " not in src[jsdoc:start] and src[jsdoc:start].count("\n") <= 14:
        start = jsdoc
    brace = src.find("{", start)
    depth = 0
    i = brace
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[:start] + new_fn.rstrip() + "\n" + src[i + 1 :]
        i += 1
    raise SystemExit("unbalanced")

js = JS.read_text()
js = replace_fn(js, "layoutFinancialFlowNodes", LAYOUT)
if "purchaseHubY" not in js or "fixed-composition-v3" not in js:
    raise SystemExit("patch markers missing")
JS.write_text(js)

css = CSS.read_text()
css = css.replace("overflow: hidden; /* no scroll; all cards stay inside */", "overflow: visible; /* grow height — never clip nodes */")
css = css.replace(
    "  overflow: hidden;\n  padding: 10px 8px 12px;",
    "  overflow: visible;\n  padding: 10px 8px 12px;",
)
# also in FF FIXED marker block for .rdx-ff-chart
CSS.write_text(css)

# Sync layout into offline preview if present
if PREVIEW.exists():
    prev = PREVIEW.read_text()
    if "function layoutFinancialFlowNodes(" in prev:
        prev = replace_fn(prev, "layoutFinancialFlowNodes", LAYOUT)
        PREVIEW.write_text(prev)
        print("OK preview layout synced")
    else:
        print("WARN preview has no layout fn")

print("OK", JS)
print("OK", CSS)
print("purchaseHubY", "purchaseHubY" in js)
print("overflow_hidden_comment_gone", "overflow: hidden; /* no scroll" not in css)
