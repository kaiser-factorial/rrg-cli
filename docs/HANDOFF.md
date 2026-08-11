# HANDOFF — RRG

*Continuity brief for a future session. Read this, then `SPEC.md` (full spec),
`WALKTHROUGH.md` (how to run the pipeline), and the ADRs: `docs/adr/0001-validator-isolation.md`
(zip delivery + import) and `docs/adr/0002-roundtrip-run-identity-and-archival.md` (run_id,
breach guard, archive). Last updated 2025-08-11.*

---

## Where everything lives

Everything is under **`rrg-cli/`** (its own git repo → `kaiser-factorial/rrg-cli`):

- `src/rrg_cli/` — the engine (CLI + TUI + parked GUI). `tests/` — pytest suite (155 tests).
  `docs/` — design docs, ADRs, agent references.
- `src/rrg_cli/templates/project/` — starter template for `rrg init`.
- `skills/` — 7 RRG skills (blinding-lint, package, replication, robustness, scorecard,
  generalization, eval).
- `workspace/` — **gitignored**; the working projects:
  - `Demo_MovieRatings/` — demo project with 2 real runs (Qwen 3.7 Max via Hermes, Grok 4.5).
  - `LoveSmarter/` — the real study (Skopje2 dataset, 13 questions, 8-factor structure).

`RRG_root/archive/RRG/` is the **old monorepo** (history preserved). `RRG_root/archive/
gemini_test1_transcripts/` has the old Gemini test transcript (the blinding breach that
led to ADR 0001).

## What RRG does (one paragraph)

Builds, blinds, and grades staged multi-model validation packages for a study. Stages:
replication (method revealed), robustness (method hidden), generalization (off until a
data plan exists). Each study is a self-contained project; the engine is retargetable via
a cartridge (`study.yaml`) + engine config (`rrg.yaml`). Full detail in `SPEC.md`.

## Built so far

### Core pipeline (all committed, tested)
- **Blinding lint** — per-stage content checks (withheld files, methodology require/forbid,
  routing drift, result-token scan) that block publication on hard fail.
- **Validator isolation** (ADR 0001) — packages ship as self-contained zips; validators
  run outside the project; `rrg import` brings results back (zip-slip-safe).
- **Round-trip lifecycle** (ADR 0002) — opaque `run_id`, auto-resolved imports, breach
  detection (hash returned files against answer key), reversible archival.
- **Standardized prompts** — multi-turn (orient → execute → verify for replication;
  orient → propose → discuss → lock → execute → verify for robustness) with discuss/nodiscuss
  mode filtering and strict deliverable contract.
- **Scorecard** — versioned, human-only grading scaffolds.
- **Provenance** — per-file SHA-256, prompt version, lint result, determinism settings.

### Agentic CLI (2025-08-10/11) — the current primary interface

The CLI is the primary interface; the web GUI is parked. New modules:

- **`rrg prefs`** — per-project saved defaults (`.rrg_prefs.yaml`, gitignored).
  Keys: `validator`, `mode`, `skip_normalize`, `auto_import`.
- **`rrg dispatch`** — one-command round-trip: build → render prompt → run validator →
  import → normalize. 7 validators: manual, hermes, claude, codex, grok, pool, openrouter.
  3 modes: discuss, nodiscuss, agent (built-in operator responses for discuss turns).
  Multi-turn via session ID tracking (each validator's JSON output parsed for session_id
  and model name). `--reuse` skips build. `--dry-run` lints only.
- **`rrg import`** — auto-normalizes non-conforming returns (fuzzy file matching, stat
  parsing from text, creates missing `raw/Q<n>_summary.json`). `--skip-normalize` opts out.
- **`rrg wizard`** — 5-step interactive walkthrough (health → conversion → preflight →
  roster → dispatch). `--non-interactive` for CI. `--prefs` for prefs editor.
- **`rrg eval`** — pipeline metrics: deliverable contract, breach status, grading status.
- **`rrg tui`** — rich terminal UI with Base2Tone Mall color palette, ASCII art banner,
  command summary table, interactive wizard, prefs editor, and eval viewer.
- **`rrg intake`** — origin intake: `--check` (is intake needed?), `--simplified` (no
  figure_map), `--apply FILE` (writes SUMMARY.md).
- **`rrg alias`** — create shell aliases for dispatch (e.g. `grok-val → rrg dispatch
  --validator grok`). `--install` writes `~/.rrg_aliases.sh`.

New modules: `prefs.py`, `dispatch.py`, `normalize.py`, `wizard.py`, `eval_lite.py`,
`tui.py`, `alias.py`. All in `src/rrg_cli/`.

### Run folder naming
`{stage}_{validator}_{model}_{date}__{run_id}` — e.g.
`replication_hermes_qwen-3.7-max_2026-08-10__3a4c7025`.
Auto-written `RUN_INFO.md` in every run folder with full config + pipeline status.

### Roster executor field
Roster entries can include `validator: hermes|claude|codex|grok|pool|openrouter`.
Model can be `"default"` — the validator uses its own configured model (e.g. hermes →
qwen/qwen3.7-max, grok → grok-4.5, codex → gpt-5.6-terra). Model provenance captured
from JSON output.

### Model provenance
Each dispatch captures the actual model used (from JSON output: hermes --usage-file,
claude --output-format json, grok --output-format json, codex --json, pool -o json).
Fallback: config files (hermes status, ~/.codex/config.toml, ~/.grok/models_cache.json).

## Empirical results (2025-08-10/11)

### Demo MovieRatings — 2 replication runs completed

| Validator | Model | Via | Reproduced | Diverged | Cost | Duration |
|-----------|-------|-----|-----------|----------|------|----------|
| Hermes | Qwen 3.7 Max | OpenRouter | 9/11 | 2 (protocol deviations) | — | ~18 min |
| Grok | Grok 4.5 Build | grok --single | 11/11 | 0 | $0.54 | ~13 min |

**Qwen divergences:** Q2 (median split direction reversed), Q10 (wrong franchise keywords).
Both are protocol-following errors, not method disagreements.
**Origin error found:** Q5 U=5,292 is a typo for U=52,929 (both validators independently
computed the correct value).
**Grok** followed the protocol exactly, including both areas where Qwen deviated.

Eval docs in each run folder: `evals/COMPARISON.md` + `evals/DIVERGENCES.md`.
See `skills/rrg-eval/SKILL.md` for the evaluation methodology.

## Tests

`cd rrg-cli && PYTHONPATH=src .venv/bin/python -m pytest -q` — **155 tests** (154 pass,
1 skipped — a figure test needing Pillow PDF extraction). On the Mac, use `.venv/bin/python`
(recreated 2025-08-10 with Python 3.13.9: `python3.13 -m venv .venv && .venv/bin/pip install -e '.[dev]'`).

## What's parked

- **Web GUI** — functional but parked. CLI + TUI are the primary interface.
- **Generalization stage** — disabled until a data-variation plan is defined.
- **Voice process-logger** — designed in `docs/eval-harness-brief.md`, not built.
  Conclusion was "adopt, don't build."
- **Agentic RRG** — the CLI IS the agentic foundation now. See `docs/agentic-rrg-parked.md`
  for the original vision; much of it is now implemented.

## Open / next

- **LoveSmarter replication** — the real study is ready to run (preflight passes, config
  migrated to v1). Needs: settle CFA/measurement basis with advisor, then dispatch.
- **Robustness runs** — after replication is graded, run robustness on Demo_MovieRatings
  and LoveSmarter.
- **Report naming** — the report_name template (`{model}_Report.md`) uses the roster model
  name, which may be "default". The normalizer or dispatch should rename the report file
  to match the actual validator+model on import.
- **Multi-validator comparison** — compare several validators' DYFA narratives at once
  (currently the eval compares origin vs one validator).
- **Prime-agent executor** — requires async IPython context; errors clearly when used
  from CLI. Implement when needed from a prime-agent session.
