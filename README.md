# aor-loop

**AI self-verification via visual ground truth.**

A lightweight implementation of what we're calling the **Automated Perception Loop (APL)**:
a closed feedback cycle where an AI system generates output, visually confirms it worked,
and retries on failure — without a human in the loop.

```
Model generates fix
       ↓
  Visual check       ← aor-loop lives here
       ↓
 Pass → done
 Fail → model sees failure → retries → converges
```

---

## The problem

LLMs are weak at truth — but strong when grounded in feedback loops.

When you ask a model to fix a multi-tab HTML dashboard, it will tell you it's fixed.
Half the time it isn't. The tabs accept clicks but render identical views.
The bug is invisible unless you manually click every tab and compare.

Traditional loop:
```
Model → claims success → human verifies → loop
```

With aor-loop:
```
Model → generates fix → visual check → detects failure → retries → converges
```

You removed the human bottleneck. The system is forced to rely on **actual outcomes**,
not its own assumptions.

---

## What it does

`viz_validator.py` is a headless visual regression harness for interactive HTML files.

1. **Load** — opens the HTML file in headless Chromium
2. **Inject** — feeds JSON data to the page's file input (triggers native FileReader,
   bypasses `let`-scoped JS variables that external `evaluate()` can't reach)
3. **Detect** — auto-discovers interactive buttons using 10 CSS selector patterns
4. **Screenshot** — finds the canvas container, scrolls to it, screenshots that element
5. **Compare** — each tab is compared against ALL others (not just adjacent),
   using the maximum pixel diff — eliminates false positives from clicking an already-active tab
6. **Report** — REPORT.txt + report.json, exits 0/1/2 for clean CI integration

---

## Install

```bash
pip install playwright
playwright install chromium
```

No other dependencies. Pixel comparison uses stdlib `zlib` by default.

---

## Usage

```bash
# Validate tabs in any HTML file
python viz_validator.py my_dashboard.html

# With JSON data injection
python viz_validator.py my_dashboard.html --data my_data.json

# Custom tab selector
python viz_validator.py my_dashboard.html --data my_data.json --selector "button.tab"

# Debug mode (shows browser)
python viz_validator.py my_dashboard.html --data my_data.json --headed

# Custom output dir + slower pause for animated UIs
python viz_validator.py my_dashboard.html --data my_data.json --output reports/ --pause 1.5
```

---

## Output

```
viz_validation/
    00_baseline.png
    01_Radar.png
    02_Bar_Chart.png
    03_Table.png
    REPORT.txt
    report.json
```

```
============================================================
VIZ VALIDATOR — REPORT
============================================================
PASSED: 3   FAILED: 0

TAB RESULTS
------------------------------------------------------------
  ✅  Radar        max_diff=16.12%  (vs Bar_Chart)  → 01_Radar.png
  ✅  Bar_Chart    max_diff=16.04%  (vs Radar)      → 02_Bar_Chart.png
  ✅  Table        max_diff=14.38%  (vs Radar)      → 03_Table.png
```

**Exit codes:** `0` = all pass, `1` = stuck tabs, `2` = load/injection error

---

## Why this matters beyond HTML tabs

This pattern applies anywhere an AI generates output that has a verifiable visual form:

**UI testing** — what this tool does now. Replace manual QA with visual regression.

**Video pipeline** — extract a frame from a generated clip, check composition, detect
missing elements or wrong physics. Retry the prompt on failure.

**Prompt correctness verification** — instead of asking "did the model follow the prompt?",
ask "does the output *look like the prompt*?" Ground truth over self-report.

**Confidence scoring** (coming) — instead of pass/fail, a continuous match score.
Threshold triggers automatic retry at configurable sensitivity.

---

## Design decisions

**Why `set_input_files()` instead of `page.evaluate()`?**
LLM-generated HTML frequently uses `let data = ...` scoped inside a `<script>` block.
These variables are invisible to external `page.evaluate()`. Triggering the page's own
file input handler bypasses this entirely.

**Why compare against all other tabs, not just the previous?**
If you click an already-active tab, diff vs baseline = 0% → false failure.
Comparing against all others and taking the max diff eliminates this class of false positive.

**Why screenshot the canvas container, not the full viewport?**
AI visualizers typically have stat bars and headers above the canvas. Full-viewport
comparison dilutes real canvas diffs with identical header pixels, making stuck tabs
harder to detect.

**Why no config file?**
Drop it in any project directory and run immediately. Every option is a CLI flag with a
sane default.

---

## Arguments

| Flag | Default | Description |
|------|---------|-------------|
| `html_file` | required | HTML file to validate |
| `--data` | none | JSON data file to inject |
| `--selector` | auto | CSS selector for tab buttons |
| `--inject-fn` | auto | JS function name to call with data |
| `--output` | `viz_validation/` | Output directory |
| `--threshold` | `1.0` | Min % pixel diff to count as changed |
| `--headed` | false | Show browser window |
| `--pause` | `0.8` | Seconds to wait after each click |

---

## Tested on

- MAIF Visualizer (canvas-based, sovereign JSON, 3 tabs) — 3/3 PASS at 14-16% pixel diff
- Playwright 1.x, Python 3.10+, macOS / Linux

---

## Roadmap

- [ ] Confidence scoring with configurable retry threshold
- [ ] Frame extraction + visual check for video pipeline clips
- [ ] Prompt-to-visual alignment scoring

---

## Part of the latent-affect research stack

- **aor-dmma** — Dynamic Music Metric Analysis pipeline (AI transcription bias research)
- **aor-loop** — this repo (Automated Perception Loop)

---

## License

MIT

## Author

Jon Wright / [latent-affect](https://github.com/latent-affect)
