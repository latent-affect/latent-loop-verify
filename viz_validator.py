#!/usr/bin/env python3
“””
viz_validator.py — Visual tab/state validation harness for interactive HTML files.

Loads an HTML file in a headless browser, optionally injects a JSON data file,
then clicks every interactive button/tab it finds and screenshots each state.
Screenshots are compared pixel-by-pixel to detect “stuck” tabs — buttons that
claim to change the view but produce an identical render.

Works with any HTML file. No CI pipeline, no external services, no config files.

Usage:
python viz_validator.py <html_file>
python viz_validator.py <html_file> –data <data.json>
python viz_validator.py <html_file> –data <data.json> –selector “button.tab”
python viz_validator.py <html_file> –data <data.json> –inject-fn loadData
python viz_validator.py <html_file> –data <data.json> –output my_report/
python viz_validator.py <html_file> –data <data.json> –threshold 0.5

Arguments:
html_file           Path to the HTML file to validate
–data              JSON file to inject into the page (optional)
–selector          CSS selector for buttons to test (default: auto-detect)
–inject-fn         JS function name to call with JSON data (default: auto-detect)
–output            Directory for screenshots and report (default: viz_validation/)
–threshold         Minimum % of pixels that must differ for tabs to pass (default: 1.0)
–headed            Show browser window (useful for debugging)
–pause             Seconds to wait after each click for animations (default: 0.8)

Output:
viz_validation/
00_baseline.png
01_<button_label>.png
02_<button_label>.png
…
REPORT.txt          Human-readable pass/fail summary
report.json         Machine-readable results

Exit codes:
0 — all tabs produce distinct visuals
1 — one or more tabs appear stuck (identical render)
2 — error loading page or injecting data

License: MIT
“””

import argparse
import json
import sys
import time
from pathlib import Path
from datetime import datetime

# —————————————————————————

# Pixel comparison (no PIL dependency — uses raw PNG bytes via zlib)

# —————————————————————————

def png_pixel_diff_pct(bytes_a: bytes, bytes_b: bytes) -> float:
“””
Compare two PNG screenshots. Returns % of pixels that differ (0.0–100.0).
Falls back to byte-level comparison if PNG decode is unavailable.
Fast enough for typical viewport screenshots.
“””
if bytes_a == bytes_b:
return 0.0

```
try:
    import png  # pypng
    import io

    def decode(b):
        r = png.Reader(file=io.BytesIO(b))
        w, h, rows, meta = r.read_flat()
        return list(rows), w, h, meta.get('planes', 3)

    rows_a, wa, ha, ch = decode(bytes_a)
    rows_b, wb, hb, _  = decode(bytes_b)

    if wa != wb or ha != hb:
        return 100.0

    total = wa * ha
    diff  = sum(1 for pa, pb in zip(rows_a, rows_b) if pa != pb)
    return (diff / total) * 100.0

except ImportError:
    pass

try:
    import zlib, struct

    def decode_simple(b):
        if b[1:4] != b'PNG':
            return None, None, None
        i = 8
        idat = b''
        w = h = 0
        while i < len(b):
            length = struct.unpack('>I', b[i:i+4])[0]
            chunk  = b[i+4:i+8]
            data   = b[i+8:i+8+length]
            if chunk == b'IHDR':
                w, h = struct.unpack('>II', data[:8])
            elif chunk == b'IDAT':
                idat += data
            elif chunk == b'IEND':
                break
            i += 12 + length
        return zlib.decompress(idat), w, h

    raw_a, wa, ha = decode_simple(bytes_a)
    raw_b, wb, hb = decode_simple(bytes_b)
    if raw_a is None or raw_b is None or wa != wb or ha != hb:
        return 50.0 if bytes_a != bytes_b else 0.0

    total = len(raw_a)
    diff  = sum(1 for a, b in zip(raw_a, raw_b) if a != b)
    return (diff / total) * 100.0

except Exception:
    if len(bytes_a) != len(bytes_b):
        return 100.0
    diff = sum(1 for a, b in zip(bytes_a, bytes_b) if a != b)
    return (diff / len(bytes_a)) * 100.0
```

# —————————————————————————

# Auto-detection helpers

# —————————————————————————

AUTO_SELECTORS = [
“[role=‘tab’]”,
“[data-tab]”,
“[data-view]”,
“.tab”,
“.btn[data-view]”,
“button.tab-btn”,
“nav button”,
“.tabs button”,
“.tab-bar button”,
“.controls button”,
]

AUTO_INJECT_PATTERNS = [
“loadJSON”,
“loadData”,
“loadFile”,
“ingestData”,
“setData”,
“parseJSON”,
]

def detect_inject_fn(page) -> str | None:
“”“Scan page JS for a likely data injection function.”””
source = page.evaluate(“document.documentElement.innerHTML”)
for name in AUTO_INJECT_PATTERNS:
if f”function {name}” in source or f”window.{name}” in source:
return name
return None

def find_buttons(page, selector: str) -> list[dict]:
“”“Return list of {label, selector_index} for all matching buttons.”””
return page.evaluate(f”””() => {{
const els = document.querySelectorAll({json.dumps(selector)});
return Array.from(els).map((el, i) => ({{
label: (el.innerText || el.getAttribute(‘aria-label’) ||
el.getAttribute(‘data-view’) || el.getAttribute(‘data-tab’) ||
`button_${{i}}`).trim().replace(/\s+/g, ‘_’),
index: i,
visible: el.offsetParent !== null,
}}));
}}”””)

# —————————————————————————

# JSON data injection

# —————————————————————————

def inject_json(page, json_path: Path, pause: float = 0.8) -> bool:
“””
Inject data into an HTML visualizer by feeding the file directly to the
page’s file input element. This triggers the page’s own FileReader/onchange
handler, so it works regardless of whether state variables are let-scoped.

```
Falls back to a synthetic DataTransfer drop event if no file input is found.
Returns True on success.
"""
# Strategy 1: set_input_files on any file input (most reliable)
try:
    inputs = page.query_selector_all("input[type='file']")
    if inputs:
        inputs[0].set_input_files(str(json_path))
        page.wait_for_timeout(int(pause * 2000))
        return True
except Exception as e:
    print(f"  [inject] file input strategy failed: {e}")

# Strategy 2: synthetic drop event carrying the file content
try:
    content = json_path.read_text()
    page.evaluate(f"""() => {{
        const content = {json.dumps(content)};
        const file = new File([content], {json.dumps(json_path.name)},
                              {{type: 'application/json'}});
        const dt = new DataTransfer();
        dt.items.add(file);
        const zone = document.getElementById('upload-zone') ||
                     document.querySelector('[id*="drop"], [class*="drop"], [class*="upload"]');
        if (zone) {{
            zone.dispatchEvent(new DragEvent('drop', {{
                bubbles: true, cancelable: true, dataTransfer: dt
            }}));
        }}
    }}""")
    page.wait_for_timeout(int(pause * 2000))
    return True
except Exception as e:
    print(f"  [inject] drop event strategy failed: {e}")
    return False
```

# —————————————————————————

# Core validation runner

# —————————————————————————

def run_validation(
html_path: Path,
data_path: Path | None,
selector: str | None,
inject_fn: str | None,
output_dir: Path,
threshold: float,
headed: bool,
pause: float,
) -> dict:

```
output_dir.mkdir(parents=True, exist_ok=True)

results = {
    "html_file":  str(html_path),
    "data_file":  str(data_path) if data_path else None,
    "timestamp":  datetime.now().isoformat(),
    "threshold_pct": threshold,
    "tabs":       [],
    "passed":     0,
    "failed":     0,
    "errors":     [],
}

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=not headed)
    page = browser.new_page(viewport={"width": 1280, "height": 900})

    # Load page
    try:
        page.goto(html_path.as_uri())
        page.wait_for_timeout(int(pause * 1000))
    except Exception as e:
        results["errors"].append(f"Page load failed: {e}")
        browser.close()
        return results

    # Inject data
    if data_path:
        injected = False

        try:
            injected = inject_json(page, data_path, pause)
        except Exception as e:
            results["errors"].append(f"Injection error: {e}")

        # Try named function injection as fallback
        if not injected and inject_fn:
            try:
                raw = json.loads(data_path.read_text())
                page.evaluate(f"window['{inject_fn}'] && window['{inject_fn}'](...[{json.dumps(raw)}])")
                page.wait_for_timeout(int(pause * 1000))
                injected = True
            except Exception as e:
                results["errors"].append(f"Named function injection failed: {e}")

        if not injected:
            results["errors"].append("Data injection failed — screenshots may show empty state")

    # Auto-detect selector
    if not selector:
        for s in AUTO_SELECTORS:
            buttons = find_buttons(page, s)
            visible = [b for b in buttons if b["visible"]]
            if len(visible) >= 2:
                selector = s
                print(f"  [detect] Auto-selected: {selector!r} ({len(visible)} visible buttons)")
                break

    if not selector:
        results["errors"].append("No interactive buttons found. Try --selector.")
        browser.close()
        return results

    buttons = [b for b in find_buttons(page, selector) if b["visible"]]
    if len(buttons) < 2:
        results["errors"].append(f"Only {len(buttons)} visible button(s) found with {selector!r} — need ≥2 to compare.")
        browser.close()
        return results

    print(f"  [validate] Found {len(buttons)} buttons: {[b['label'] for b in buttons]}")

    # Find the container nearest to the tab buttons for targeted screenshots.
    container_el = page.evaluate(f"""() => {{
        const btn = document.querySelector({json.dumps(selector)});
        if (!btn) return null;
        let el = btn;
        while (el && el !== document.body) {{
            const canvas = el.querySelector('canvas');
            if (canvas) return canvas.parentElement ? canvas.parentElement.id || null : null;
            el = el.parentElement;
        }}
        return null;
    }}""")

    def take_shot(path: Path) -> bytes:
        """Screenshot the canvas container if found, else full viewport."""
        if container_el:
            try:
                el = page.query_selector(f"#{container_el}")
                if el:
                    el.scroll_into_view_if_needed()
                    page.wait_for_timeout(300)
                    return el.screenshot(path=str(path))
            except Exception:
                pass
        return page.screenshot(path=str(path), full_page=False)

    # Baseline screenshot (first tab, already active)
    baseline_path = output_dir / "00_baseline.png"
    baseline_bytes = take_shot(baseline_path)
    all_shots = {"baseline": baseline_bytes}

    for i, btn in enumerate(buttons):
        try:
            page.evaluate(f"""() => {{
                const els = document.querySelectorAll({json.dumps(selector)});
                if (els[{btn['index']}]) els[{btn['index']}].click();
            }}""")
            page.wait_for_timeout(int(pause * 1000))
        except Exception as e:
            results["errors"].append(f"Click failed for {btn['label']}: {e}")
            continue

        shot_path = output_dir / f"{i+1:02d}_{btn['label']}.png"
        shot_bytes = take_shot(shot_path)
        all_shots[btn["label"]] = shot_bytes

    # Compare: each tab must differ from at least one other tab.
    for i, btn in enumerate(buttons):
        label      = btn["label"]
        this_bytes = all_shots.get(label)
        if this_bytes is None:
            continue

        others = [(k, v) for k, v in all_shots.items() if k != label]
        diffs  = [(k, png_pixel_diff_pct(this_bytes, v)) for k, v in others]
        best_k, best_diff = max(diffs, key=lambda x: x[1])
        passed = best_diff >= threshold

        shot_path = output_dir / f"{i+1:02d}_{label}.png"
        tab_result = {
            "label":        label,
            "screenshot":   shot_path.name,
            "max_diff_pct": round(best_diff, 3),
            "max_diff_vs":  best_k,
            "passed":       passed,
        }
        results["tabs"].append(tab_result)

        status = "PASS" if passed else "FAIL (identical to all other tabs)"
        print(f"  [{status}] {label:30s}  max_diff={best_diff:.2f}%  (vs {best_k})")

        if passed:
            results["passed"] += 1
        else:
            results["failed"] += 1

    browser.close()

return results
```

# —————————————————————————

# Report writer

# —————————————————————————

def write_report(results: dict, output_dir: Path):
lines = [
“=” * 60,
“VIZ VALIDATOR — REPORT”,
“=” * 60,
f”HTML:      {results[‘html_file’]}”,
f”Data:      {results[‘data_file’] or ‘none’}”,
f”Run:       {results[‘timestamp’]}”,
f”Threshold: {results[‘threshold_pct’]}% pixel difference to pass”,
“”,
f”PASSED: {results[‘passed’]}   FAILED: {results[‘failed’]}”,
“”,
“TAB RESULTS”,
“-” * 60,
]
for t in results[“tabs”]:
mark = “✅” if t[“passed”] else “❌”
lines.append(
f”  {mark}  {t[‘label’]:<30s}  max_diff={t[‘max_diff_pct’]:.2f}%  “
f”(vs {t[‘max_diff_vs’]})  → {t[‘screenshot’]}”
)

```
if results["errors"]:
    lines += ["", "ERRORS", "-" * 60]
    for e in results["errors"]:
        lines.append(f"  ⚠️  {e}")

lines += [
    "",
    "INTERPRETATION",
    "-" * 60,
    "  PASS = button click produced a visually distinct render.",
    "  FAIL = render was identical before and after click.",
    "         Likely cause: JS render function not branching on",
    "         the active tab state variable.",
    "=" * 60,
]

report_txt = output_dir / "REPORT.txt"
report_txt.write_text("\n".join(lines))
print(f"\n  Report: {report_txt}")

report_json = output_dir / "report.json"
report_json.write_text(json.dumps(results, indent=2))

print("\n" + "\n".join(lines))
```

# —————————————————————————

# CLI

# —————————————————————————

def main():
parser = argparse.ArgumentParser(
description=“Visual tab validation harness for interactive HTML files.”,
formatter_class=argparse.RawDescriptionHelpFormatter,
epilog=**doc**.split(“License:”)[0].strip(),
)
parser.add_argument(“html_file”,               help=“HTML file to validate”)
parser.add_argument(”–data”,                  help=“JSON data file to inject”)
parser.add_argument(”–selector”,              help=“CSS selector for tab buttons”)
parser.add_argument(”–inject-fn”,             help=“JS function name to call with data”)
parser.add_argument(”–output”,  default=“viz_validation”, help=“Output directory”)
parser.add_argument(”–threshold”, type=float, default=1.0,
help=“Min %% pixel diff to count as ‘changed’ (default: 1.0)”)
parser.add_argument(”–headed”,  action=“store_true”, help=“Show browser window”)
parser.add_argument(”–pause”,   type=float,  default=0.8,
help=“Seconds to wait after each click (default: 0.8)”)
args = parser.parse_args()

```
html_path = Path(args.html_file).resolve()
if not html_path.exists():
    print(f"ERROR: HTML file not found: {html_path}")
    sys.exit(2)

data_path = Path(args.data).resolve() if args.data else None
if data_path and not data_path.exists():
    print(f"ERROR: Data file not found: {data_path}")
    sys.exit(2)

output_dir = Path(args.output) / html_path.stem
output_dir.mkdir(parents=True, exist_ok=True)

print(f"\nViz Validator")
print(f"  HTML:   {html_path}")
print(f"  Data:   {data_path or 'none'}")
print(f"  Output: {output_dir}")
print()

results = run_validation(
    html_path   = html_path,
    data_path   = data_path,
    selector    = args.selector,
    inject_fn   = args.inject_fn,
    output_dir  = output_dir,
    threshold   = args.threshold,
    headed      = args.headed,
    pause       = args.pause,
)

write_report(results, output_dir)

sys.exit(0 if results["failed"] == 0 and not results["errors"] else 1)
```

if **name** == “**main**”:
main()
