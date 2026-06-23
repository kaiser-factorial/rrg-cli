# HANDOFF — RRG

*Continuity brief for a future session. Read this, then `SPEC.md` (full spec) and
`docs/adr/0001-validator-isolation.md`. Last updated 2026-06-23.*

---

## Where everything lives (after the 2026-06-23 restructure)

Everything is now under **`rrg-cli/`** (its own git repo → `kaiser-factorial/rrg-cli`):

- `src/rrg_cli/` — the engine (CLI + local GUI). `tests/` — pytest suite. `docs/` — this
  file, `SPEC.md` lives at the repo root, ADRs in `docs/adr/`.
- `examples/MovieRatings/` — committed, runnable demo project.
- `.venv/` — the project venv (gitignored). Use Python 3.13 (3.14's `ensurepip` is broken).
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
  streamed PDF viewer of the origin report, and a result-free methodology-drafting prompt.
- **Per-stage model editor** (Setup) — model/vendor/type/license/dispatch-slug rows.
- **Review & Grade tab** (replaces Compare + Scorecards) — per question: validator vs
  origin **stats** (validator-led, content-matched), **DYFA narratives**, **figures**, and
  a **verdict**. A run is *graded* only when a human confirms every question; finalizing
  writes a versioned `SCORECARD_*.md`. Narrative numbers are colored (origin amber /
  validator stage-color / red for untracked / figure refs italic + click-to-scroll).
- **Validator isolation** (ADR 0001) — packages ship as a self-contained zip; run the
  validator **outside the project**; `rrg import` brings results back (zip-slip-safe). Fixes
  a real breach where a validator `ls`-ed `../../../origin/`.
- **Figure resolver** (`figures.py`) — Q-numbered files → reference tokens → **PDF
  appendix figures matched by the per-section Figure/Appendix reference** (number *or*
  letter, content-matched, not by position). Heuristic; prefers nothing over a wrong figure.
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

## Open / next

- **Validator-compliance**: the prompt is now strict + has a verify turn, but a model can
  still drift. Decide whether to add an `rrg import`-time normalizer (parse the report's
  table into `raw/Q<n>_summary.json`, standardize figure names).
- **Figure caption-matching is heuristic** — calibrate against a real LoveSmarter-style
  report (it nailed MovieRatings; reports whose captions don't restate the question match
  less well). PDF figures live only in `ORIGIN_REPORT.pdf` for MovieRatings.
- Minor: orphaned old LoveSmarter prompts (`STAGE1_REPLICATION_PROMPT.md`,
  `METHOD_FREE_PROMPT.md`, `CODEX_PROMPT.md`, …) are safe to delete. Optional: color stat
  *names* (`p`, `chi-square`) in narratives, not just values.
- **Then actually run the pipeline** for LoveSmarter: build → dispatch zip → run isolated →
  `rrg import` → Review & Grade → finalize scorecards.

## Tests

`cd rrg-cli && PYTHONPATH=src .venv/bin/python -m pytest -q` — green. `pyreadstat` must be
installed for strict preflight (it's a dependency). Files: origin, grading, extract,
figures, dispatch, scorecard_gui, packaging_blinding, converter, scaffold_doctor, cli.
