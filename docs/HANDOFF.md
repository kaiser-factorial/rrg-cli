# HANDOFF — RRG

*Continuity brief for a future session. Read this, then `SPEC.md` (full spec) and
`docs/adr/0001-validator-isolation.md`. Last updated 2026-06-23 (pm session).*

---

## Where everything lives (after the 2026-06-23 restructure)

Everything is now under **`rrg-cli/`** (its own git repo → `kaiser-factorial/rrg-cli`):

- `src/rrg_cli/` — the engine (CLI + local GUI). `tests/` — pytest suite. `docs/` — this
  file, `SPEC.md` lives at the repo root, ADRs in `docs/adr/`.
- `examples/MovieRatings/` — committed, runnable demo project.
- `.venv/` — the project venv (gitignored). Use Python 3.13 (3.14's `ensurepip` is broken).
  Note: the venv's `python`/`python3` symlinks point at a broken `python3.14`; `rrg` and
  `pip` work because their shebangs hardcode `python3.13`, but a bare `.venv/bin/python`
  fails — repoint those two symlinks to `python3.13` when convenient.
- `workspace/` — **gitignored**; the live GUI workspace holding the real studies:
  - `LoveSmarter/` — the real study (consolidated: `rrg.yaml`, `study.yaml`, `prompts/`,
    `data/`, `operator/`, `shared/` all in one self-contained project).
  - `MovieRatings/` — working copy of the demo.
  - `experiments/` — test-run transcripts (e.g. `gemini_test1_MovieRatings/`).

`RRG_root/archive/RRG/` is the **old monorepo** (its own repo, history preserved). Its
`docs/HANDOFF.md` has the deep LoveSmarter research history — the validation ladder,
roster, re-runs needed, open scientific decisions. Read that for the science.

**Run the GUI:** `cd rrg-cli && .venv/bin/rrg gui --workspace workspace --open`
(after `.venv/bin/pip install -e .`). Static assets reload on browser refresh; Python
changes need a server restart.

## What RRG does (one paragraph)

Builds, blinds, and grades staged multi-model validation packages for a study. Stages:
replication (method revealed), robustness (method hidden), generalization (off until a
data plan exists). Each study is a self-contained project; the engine is retargetable via
a cartridge (`study.yaml`) + engine config (`rrg.yaml`). Full detail in `SPEC.md`.

## Built so far (all committed, tested)

- **Workspace mode** — `rrg gui --workspace DIR` confines one workspace, switches projects
  under a lock; Projects tab + new-project scaffolding.
- **Origin tab** — per-question separation matrix (questions ↔ protocol ↔ origin key),
  streamed PDF viewer of the origin report, a result-free methodology-drafting prompt, and
  the **origin-intake** card (below).
- **Origin intake** (`origin.py` + `rrg intake` + Origin-tab card) — normalizes the origin
  report into the canonical artifacts the pipeline consumes. A flat prompt
  (`prompts/origin_intake.md`, built-in default in `origin.py`) is handed to the *origin
  model* with its report; it returns (1) a per-question `SUMMARY.md` whose fields mirror the
  validator `Q<n>_summary.json` schema, **transcribe-not-recompute** (preserves quirks like
  the Q7 p-value inconsistency), and (2) a fenced `figure_map` YAML. `save_intake` splits the
  two, writes `SUMMARY.md`, copies matched figures to `Q<n>_fig.png` (conservative — only on
  an unambiguous filename match; PDF-only figures reported, never destructive), writes
  `figure_map.yaml`, and runs a presence linter (inverse of the methodology leak linter:
  flags any Q section missing `test/statistic/p_value/conclusion`). **Sections are keyed by
  ORIGINAL question number** (the SUMMARY is consumed by original #, unlike the protocol which
  is new-numbered) — the prompt's question list is built from the map accordingly. CLI:
  `rrg intake` renders the prompt; `rrg intake --apply FILE` applies a return.
- **Per-stage model editor** (Setup) — model/vendor/type/license/dispatch-slug rows.
- **Review & Grade tab** (replaces Compare + Scorecards) — per question: validator vs
  origin **stats** (validator-led, content-matched), **DYFA narratives**, **figures**, and
  a **verdict**. A run is *graded* only when a human confirms every question; finalizing
  writes a versioned `SCORECARD_*.md`. Narrative numbers are colored (origin amber /
  validator stage-color / red for untracked / figure refs italic + click-to-scroll).
- **Cross-run overview** (Review & Grade, collapsible at top) — a questions × runs matrix;
  each cell shows a run's **headline statistic** (`cross_run_overview` + `_headline_stat`:
  top-level p-value, falling back to nested/`top_p`) with a green/red dot for whether that
  value is found in the origin, plus an Origin reference column and a per-row agreement count.
  Click any cell to jump to that run+question in the side-by-side. The side-by-side grading
  view is unchanged. Endpoint `/api/overview`.
- **Validator isolation** (ADR 0001) — packages ship as a self-contained zip; run the
  validator **outside the project**; `rrg import` brings results back (zip-slip-safe). Fixes
  a real breach where a validator `ls`-ed `../../../origin/`.
- **Figure resolver** (`figures.py`) — Q-numbered files → reference tokens → **PDF
  appendix figures matched by the per-section Figure/Appendix reference** (number *or*
  letter, content-matched, not by position). Heuristic; prefers nothing over a wrong figure.
  PDF image extraction **requires Pillow** — declared as `pypdf[image]` in `pyproject.toml`
  (see Lessons; a bare `pypdf` install silently extracts no images).
- **Standardized prompts** — one canonical `prompts/replication.md` + `robustness.md` for
  *all* projects (LoveSmarter repointed off its old bespoke prompts). Robustness has the
  `{mode:discuss}`/`{mode:nodiscuss}` interactive discuss→lock flow; both stages end with a
  QA + format-verification turn. Deliverable contract is strict: per question
  `Q<n>_analysis.py → raw/Q<n>_raw.csv → Q<n>_fig.py → Q<n>_fig.png`, a
  `raw/Q<n>_summary.json` with fixed keys, and a DYFA section. New projects default to this.

## Lessons (the hard way)

- The GUI CSP is `style-src 'self'` → **inline `style=` is silently dropped**; use CSS
  classes. Chrome won't render a PDF from a `data:`/`blob:` `<object>` → stream it into an
  `<iframe>` from a same-origin endpoint. Committing from the Cowork sandbox fails (mount
  blocks unlink/rename) — **commit from the Mac**.
- A validator (Gemini 3.1 Pro) test exposed two things: the **blinding breach** (fixed via
  isolation) and a **convention gap** — it ignored `raw/Q<n>_summary.json`, used a
  monolithic script, and named figures `visual_q<n>.png`. We tightened the prompt + added
  the verify turn; whether to also add an import-time normalizer is still open.
- **Pillow is required for PDF figures, and its absence was invisible.** Origin figures
  showed "No figures" because the venv had `pypdf` but not Pillow, so `page.images` raised
  `ImportError: pillow is required…` — which `figures.py` swallowed in a broad
  `except Exception`, making a missing dependency look identical to a figure-less PDF. Fix:
  `pypdf[image]` in `pyproject.toml` (auto-installs Pillow on `pip install -e .`). Broad
  `except Exception` around optional-dependency calls hides setup problems — log or narrow.
- **Big responses + fast clicking = BrokenPipe spam.** Once figures inline as base64, the
  `/api/compare` payload is large; clicking through questions quickly makes the browser
  cancel in-flight requests, and the server's write hit a closed socket. The generic
  `except Exception` then tried to send an *error* response over the same dead socket,
  double-faulting into the server loop. Fix: `_send`/`_send_pdf` swallow `ConnectionError`.
- **pypdf xref warnings are benign and now filtered.** `Ignoring wrong pointing object N 0`
  is a recoverable cross-reference quirk in some PDFs (figures still extract). `serve()`
  installs a logging filter on `pypdf._reader` that drops *only* that message — every other
  pypdf warning, and all errors/exceptions, still surface.

## Open / next

- **Validator-compliance**: the prompt is now strict + has a verify turn, but a model can
  still drift. The **origin** side is now handled by origin-intake (above); a *validator*-side
  `rrg import`-time normalizer (parse a non-conforming report into `raw/Q<n>_summary.json`,
  standardize figure names) is still open. Per discussion the plan is to lean on clean prompts
  first and normalize as a fallback.
- **Origin column in the overview is reference-only** until intake has been run for a study —
  it shows the origin's value only where a validator corroborated it. After `rrg intake`
  writes a structured `SUMMARY.md`, wire a label-aligned origin parse so the column is solid.
- **Multi-validator DYFA view** (optional) — the Review side-by-side is origin vs *one*
  validator. A view comparing several validators' DYFA narratives at once was discussed.
- **Figure caption-matching is heuristic** — calibrate against a real LoveSmarter-style
  report (it nailed MovieRatings; reports whose captions don't restate the question match
  less well). PDF figures live only in `ORIGIN_REPORT.pdf` for MovieRatings. Origin-intake's
  `figure_map` (origin model names the figure→question mapping) sidesteps this on the origin
  side when figures exist as files.
- **Observed in the test1 Review (screenshot 2026-06-23):** (a) origin **Figures** showed
  "No figures" — **RESOLVED**: root cause was missing **Pillow** (not pypdf); the resolver's
  broad `except` hid the `ImportError`. Fixed via `pypdf[image]` in `pyproject.toml` (see
  Lessons). (b) validator **Full report** shows "No report section for this question" — the
  Gemini test1 report isn't in DYFA `## Q<n>` sections, so `_markdown_section` finds nothing.
  Resolves on the rerun with the standardized DYFA prompt; for non-conforming reports, this
  is the case the import-time normalizer (above) would handle.
- Minor: orphaned old LoveSmarter prompts (`STAGE1_REPLICATION_PROMPT.md`,
  `METHOD_FREE_PROMPT.md`, `CODEX_PROMPT.md`, …) are safe to delete. Optional: color stat
  *names* (`p`, `chi-square`) in narratives, not just values.
- **Then actually run the pipeline** for LoveSmarter: build → dispatch zip → run isolated →
  `rrg import` → Review & Grade → finalize scorecards.

## Tests

`cd rrg-cli && PYTHONPATH=src .venv/bin/python -m pytest -q` — green (58 tests). `pyreadstat`
must be installed for strict preflight (it's a dependency). Files: origin, **intake** (new:
split_intake / intake_prompt original-numbering / save_intake / cross_run_overview /
headline-stat / intake+overview HTTP), grading, extract, figures, dispatch, scorecard_gui,
packaging_blinding, converter, scaffold_doctor, cli.
