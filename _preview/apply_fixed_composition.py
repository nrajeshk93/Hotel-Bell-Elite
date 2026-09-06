#!/usr/bin/env python3
"""Apply fixed-composition Sankey layout to Hotel Bell Elite charts JS/CSS."""
from __future__ import annotations

from pathlib import Path

ROOT = Path("/Users/rajesh/Documents/New project/Hotel Bell elite")
JS = ROOT / "static" / "main_dashboard_charts.js"
CSS = ROOT / "static" / "main_dashboard_analytics.css"
MARKER = "/* === FF FIXED COMPOSITION V3 OVERRIDES === */"


def replace_function(src: str, fn_name: str, new_fn: str) -> str:
    needle = f"function {fn_name}("
    start = src.find(needle)
    if start < 0:
        raise SystemExit(f"Could not find {fn_name}")
    jsdoc = src.rfind("/**", 0, start)
    if jsdoc >= 0 and src[jsdoc:start].count("\n") <= 10 and "*/" in src[jsdoc:start]:
        # only pull jsdoc if it looks like it belongs to this fn
        between = src[jsdoc:start]
        if "function " not in between:
            start = jsdoc
    brace = src.find("{", start)
    if brace < 0:
        raise SystemExit(f"No opening brace for {fn_name}")
    depth = 0
    i = brace
    end = None
    while i < len(src):
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
        i += 1
    if end is None:
        raise SystemExit(f"Unbalanced braces for {fn_name}")
    return src[:start] + new_fn.rstrip() + "\n" + src[end:]


def patch_js(text: str, layout_fn: str) -> str:
    text = replace_function(text, "layoutFinancialFlowNodes", layout_fn)

    text = text.replace(
        "    if (purchaseTotal > 0) {\n      html.push(ffNodeHtml({\n        id: 'purchase',",
        "    if (purchaseTotal > 0 || purchaseCats.length) {\n      html.push(ffNodeHtml({\n        id: 'purchase',",
    )
    text = text.replace(
        "    if (expenseTotal > 0) {\n      html.push(ffNodeHtml({\n        id: 'expense',",
        "    if (expenseTotal > 0 || expenseCats.length) {\n      html.push(ffNodeHtml({\n        id: 'expense',",
    )

    text = text.replace(
        "    var chartH = Math.max(620, 180 + leafCount * 66 + 48);",
        "    var chartH = Math.max(560, 140 + leafCount * 58 + 36);",
    )

    old_hub = (
        "    if (Number(flow.purchase_total || 0) > 0) {\n"
        "      hubToLeaves('purchase', purchaseCats, 'p-', '#93C5FD');\n"
        "    }\n"
        "    if (Number(flow.expense_total || 0) > 0) {\n"
        "      hubToLeaves('expense', expenseCats, 'e-', '#FDBA74');\n"
        "    }"
    )
    new_hub = (
        "    if (node('purchase')) {\n"
        "      hubToLeaves('purchase', purchaseCats, 'p-', '#93C5FD');\n"
        "    }\n"
        "    if (node('expense')) {\n"
        "      hubToLeaves('expense', expenseCats, 'e-', '#FDBA74');\n"
        "    }"
    )
    if old_hub in text:
        text = text.replace(old_hub, new_hub)

    # outSpecs for total→hub should also allow zero totals when node exists
    text = text.replace(
        "    if (Number(flow.purchase_total || 0) > 0 && node('purchase')) {\n"
        "      outSpecs.push({ id: 'purchase', amount: flow.purchase_total, color: '#93C5FD' });\n"
        "    }\n"
        "    if (Number(flow.expense_total || 0) > 0 && node('expense')) {\n"
        "      outSpecs.push({ id: 'expense', amount: flow.expense_total, color: '#FDBA74' });\n"
        "    }",
        "    if (node('purchase')) {\n"
        "      outSpecs.push({ id: 'purchase', amount: Math.max(Number(flow.purchase_total || 0), 0), color: '#93C5FD' });\n"
        "    }\n"
        "    if (node('expense')) {\n"
        "      outSpecs.push({ id: 'expense', amount: Math.max(Number(flow.expense_total || 0), 0), color: '#FDBA74' });\n"
        "    }",
    )

    if "type: 'sankey'" in text or 'type: "sankey"' in text:
        raise SystemExit("ERROR: sankey series still present in charts.js")
    if "fixed-composition-v3" not in text:
        raise SystemExit("ERROR: layout marker missing after patch")

    layout_body = text.split("function layoutFinancialFlowNodes", 1)[1].split(
        "function drawFinancialFlowLinks", 1
    )[0]
    if "groupMid" in layout_body or "purchaseMid" in layout_body:
        raise SystemExit("ERROR: leaf-driven hub placement still present")
    return text


def patch_css(text: str, overrides: str) -> str:
    # In-place small tweaks
    text = text.replace(
        "  min-height: 620px;\n  height: auto;\n  box-sizing: border-box;\n  border-radius: 14px;\n  background: linear-gradient(180deg, #fbfcfe 0%, #ffffff 55%);\n  border: 1px solid #f1f5f9;\n  overflow: visible;\n  padding: 8px 4px 12px;",
        "  min-height: 560px;\n  height: auto;\n  box-sizing: border-box;\n  border-radius: 14px;\n  background: linear-gradient(180deg, #fbfcfe 0%, #ffffff 55%);\n  border: 1px solid #f1f5f9;\n  overflow: hidden;\n  padding: 10px 8px 12px;",
    )
    text = text.replace(
        "  min-height: 600px;\n}\n\n.rdx-ff-node {",
        "  min-height: 520px;\n}\n\n.rdx-ff-node {",
    )
    text = text.replace(
        "  color: #334155;\n  line-height: 1.25;\n  letter-spacing: -0.01em;\n  white-space: nowrap;\n  overflow: hidden;\n  text-overflow: ellipsis;\n}",
        "  color: #0f172a;\n  line-height: 1.2;\n  letter-spacing: -0.01em;\n  white-space: nowrap;\n  overflow: hidden;\n  text-overflow: ellipsis;\n  opacity: 1;\n  visibility: visible;\n}",
    )
    text = text.replace(
        "  min-height: 110px;\n  background: #ffffff;\n  border: 2px solid #93c5fd;",
        "  min-height: 88px;\n  background: #ffffff;\n  border: 2px solid #93c5fd;",
    )
    text = text.replace(
        ".rdx-ff-node--total .rdx-ff-node-amt {\n  font-size: 20px;",
        ".rdx-ff-node--total .rdx-ff-node-amt {\n  font-size: 18px;",
    )

    block = "\n\n" + MARKER + "\n" + overrides.strip() + "\n"
    if MARKER in text:
        pre, rest = text.split(MARKER, 1)
        # drop old override body through EOF or next marker-like end
        text = pre.rstrip() + block
    else:
        text = text.rstrip() + block
    return text


def main() -> None:
    here = Path(__file__).resolve().parent
    layout_fn = (here / "layoutFinancialFlowNodes.js").read_text()
    overrides = (here / "ff_css_overrides.css").read_text()

    js = JS.read_text()
    css = CSS.read_text()

    bak_js = JS.with_suffix(".js.bak-ff-v3")
    bak_css = CSS.with_suffix(".css.bak-ff-v3")
    if not bak_js.exists():
        bak_js.write_text(js)
    if not bak_css.exists():
        bak_css.write_text(css)

    new_js = patch_js(js, layout_fn)
    new_css = patch_css(css, overrides)
    JS.write_text(new_js)
    CSS.write_text(new_css)

    print("OK", JS)
    print("OK", CSS)
    print("marker fixed-composition-v3 present:", "fixed-composition-v3" in new_js)
    print("hubCluster close-together:", "hubGap = 12" in new_js)
    print("echarts sankey series absent:", "sankey" not in new_js.lower() or "no engine auto-layout" in new_js)


if __name__ == "__main__":
    main()
