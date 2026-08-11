# HANDOFF — RRG

*Continuity brief for a future session. Read this, then `WALKTHROUGH.md` (how to run
the pipeline), `SPEC.md` (full spec), and the ADRs in `docs/adr/`. Last updated
2025-08-11.*

---

## Quick orientation

RRG is a research-validation pipeline: **Replication → Robustness → Generalization**.
It builds blinded packages from a dataset + study, dispatches them to independent
validator models (via CLI agent harnesses), imports results, and evaluates.

**Current phase:** the agentic CLI foundation is built and tested. Two real
replication runs completed on Demo_MovieRatings (Qwen 3.7 Max: 9/11 reproduced;
Grok 4.5: 11/11 reproduced). The pipeline is ready for real LoveSmarter runs once
the advisor settles the measurement basis.

---

## Repo structure

```
RRG_real_root/
├── RRG_root/
│   ├── archive/
│   │   ├── RRG/                        ← old monorepo (history preserved)
│   │   └── gemini_test1_transcripts/   ← old Gemini breach transcript
│   └── rrg-cli/                        ← THE PROJECT (git repo → kaiser-factorial/rrg-cli)
│       ├── src/rrg_cli/                ← 31 Python modules (~250KB)
│       │   └── templates/project/      ← starter template for `rrg init`
│       ├── tests/                      ← 22 test files, 170 tests passing
│       ├── docs/                       ← design docs, ADRs, agent references
│       ├── skills/                     ← 7 RRG skills (SKILL.md files)
│       ├── workspace/                  ← gitignored working projects
│       │   ├── Demo_MovieRatings/      ← demo with 2 real runs (Qwen + Grok)
│       │   └── LoveSmarter/            ← real study (Skopje2, 13 questions)
│       ├── pyproject.toml              ← rich>=13.0 added
│       ├── README.md
│       ├── WALKTHROUGH.md              ← step-by-step pipeline guide
│       └── SPEC.md                    ← full system spec
└── (PANEL_VAL/ removed, examples/ removed)
```

## Environment

- **Python 3.13.9** via `.venv/` (recreated 2025-08-10)
- **Install:** `python3.13 -m venv .venv && .venv/bin/pip install -e '.[dev]'`
- **Tests:** `PYTHONPATH=src .venv/bin/python -m pytest` → 170 passed, 1 skipped
- **Installed validator CLIs:** hermes (qwen/qwen3.7-max), claude, codex
  (gpt-5.6-terra), grok (grok-4.5), pool (needs login)
- **OpenRouter API key** in environment

---

## What's built (31 modules, 170 tests)

### Core pipeline (pre-agentic, 80 tests)
- **Blinding lint** — per-stage content checks, blocks publication on hard fail
- **Validator isolation** (ADR 0001) — zip delivery, run outside project, import back
- **Round-trip lifecycle** (ADR 0002) — opaque run_id, auto-resolved imports,
  breach detection (hash against answer key), reversible archival
- **Standardized prompts** — multi-turn with discuss/nodiscuss mode filtering,
  strict deliverable contract (Q<n>_analysis.py → raw/Q<n>_raw.csv → Q<n>_fig.py →
  Q<n>_fig.png → raw/Q<n>_summary.json → DYFA section)
- **Scorecard** — versioned, human-only grading scaffolds
- **Provenance** — per-file SHA-256, prompt version, lint result, determinism
- **GUI** — parked, functional but not the primary interface

### Agentic CLI (built 2025-08-10/11, 90 tests)
- **`rrg prefs`** — per-project `.rrg_prefs.yaml` (validator, mode, skip_normalize,
  auto_import). Old "executor" key auto-migrated to "validator".
- **`rrg dispatch`** — one-command round-trip: build → prompt → validator → import →
  normalize. 7 validators: manual, hermes, claude, codex, grok, pool, openrouter.
  3 modes: discuss, nodiscuss, agent. Multi-turn via session ID (parsed from each
  validator's JSON output). `--reuse`, `--dry-run`, `--force`.
- **`rrg import`** — auto-normalizes (fuzzy file matching, stat parsing from text).
  `--skip-normalize` opts out.
- **`rrg wizard`** — 5-step interactive walkthrough. `--non-interactive`, `--prefs`.
- **`rrg eval`** — pipeline metrics: deliverable contract, breach, grading.
- **`rrg tui`** — rich terminal UI (Base2Tone Mall palette, ASCII art, command table).
- **`rrg intake`** — origin intake: `--check`, `--simplified`, `--apply FILE`.
- **`rrg alias`** — shell aliases for dispatch. `--install` writes `~/.rrg_aliases.sh`.
- **`rrg setup`** — automated project init from data + origin report:
  - `--questions` / `--apply-questions FILE --select 1,3,5` (extract from report,
    pick which to keep, auto-generates questions_map.yaml)
  - `--overview` / `--apply-overview FILE` (from codebook + questions)
  - `--instructions` / `--apply-instructions FILE` (from codebook value labels,
    alpha=0.05 default, multiplicity detection)
  - `--regenerate-map` (rebuild after editing QUESTIONS.md)
  - `--status` (show which steps needed)

### Run naming + provenance
- Run folders: `{stage}_{validator}_{model}_{date}__{run_id}`
- `RUN_INFO.md` auto-written to every run folder on import
- Model provenance from JSON output (hermes --usage-file, grok/claude --output-format
  json, codex --json, pool -o json). Fallback: config files.
- Roster entries can include `validator:` field. Model can be `"default"` (uses
  the validator's own configured model).

### Skills (7)
rrg-blinding-lint, rrg-package, rrg-replication, rrg-robustness, rrg-scorecard,
rrg-generalization (pending), rrg-eval (scientific evaluation methodology)

### Docs
- `WALKTHROUGH.md` — 12-step pipeline guide
- `AGENTIC_CLI_DESIGN.md` — implementation spec (status: implemented)
- `EXECUTOR_REFERENCE.md` — normalized commands for all 7 validators
- `agent-references/*.txt` — raw extracted docs from each agent's website
- `PHASES.md` — strategic roadmap (updated: freeze lifted, agentic CLI built)
- `agentic-rrg-parked.md` — partially un-parked (CLI foundation is built)
- `eval-harness-brief.md` — auto-metrics built, voice logger not built
- `friction-log.md` — 6 entries from real runs

---

## Empirical results

### Demo MovieRatings — 2 replication runs

| Validator | Model | Reproduced | Diverged | Cost | Duration |
|-----------|-------|-----------|----------|------|----------|
| Hermes | Qwen 3.7 Max | 9/11 | 2 (protocol deviations) | — | ~18 min |
| Grok | Grok 4.5 Build | 11/11 | 0 | $0.54 | ~13 min |

**Qwen divergences:** Q2 (median split direction reversed), Q10 (wrong franchise
keywords). Both are protocol-following errors.
**Origin error found:** Q5 U=5,292 is a typo for U=52,929 (both validators
independently computed the correct value).
**Grok** followed the protocol exactly, including both areas where Qwen deviated.

Eval docs in each run folder: `evals/COMPARISON.md` + `evals/DIVERGENCES.md`.

### Workspace projects
- `workspace/Demo_MovieRatings/` — clean, 2 runs, preflight passes
- `workspace/LoveSmarter/` — clean, preflight passes, pre-ADR-0002 runs archived,
  validation_subset removed (VALIDATION_INSTRUCTIONS.md moved to shared/)

---

## What's parked

- **Web GUI** — functional but parked. CLI + TUI are primary.
- **Generalization stage** — disabled until data-variation plan is defined.
- **Voice process-logger** — designed in `docs/eval-harness-brief.md`, not built.
  Conclusion: "adopt, don't build."
- **Antigravity** — TUI-only, no CLI mode. Can't be used as a validator.

---

## Outstanding work

### Quick wins (low effort, high value)

1. **Report naming on import** — the `{model}_Report.md` template uses the roster
   model name, which may be "default" or wrong. The normalizer should rename the
   report file on import to match `{validator}_{model}_Report.md`.
   *Effort: ~30 min in normalize.py + test*

2. **TUI roster picker** — the TUI shows the roster and offers to dispatch, but the
   user types the stage/model instead of selecting from a menu. Add rich-based
   selection prompts (arrow keys, enter to pick).
   *Effort: ~1 hour in tui.py*

3. **LoveSmarter operator cleanup** — `factor_tooling/` directory and some operator
   files may need review. The pre-ADR-0002 runs are already archived.
   *Effort: ~15 min of manual cleanup*

### Medium effort

4. **Setup automation via dispatch** — currently setup prompts are rendered and the
   user manually sends them to a model. Could automate: `rrg setup --questions
   --validator hermes` renders + sends + applies in one step.
   *Effort: ~2 hours*

5. **Multi-validator comparison** — the eval currently compares origin vs one
   validator. A cross-validator comparison (Qwen DYFA vs Grok DYFA vs origin) would
   be valuable. Extend rrg-eval skill or add `rrg eval --compare-runs`.
   *Effort: ~3 hours*

6. **CLI grading flow** — `rrg scorecard` generates the scaffold but verdicts are
   assigned via the parked GUI. Add `rrg grade --run R --question N --verdict
   REPRODUCED` for CLI-based grading.
   *Effort: ~2 hours*

7. **Prime-agent executor** — requires async IPython context. Errors clearly when
   used from CLI. Implement the async dispatch path from a prime-agent session.
   *Effort: ~1 hour if in a prime-agent session*

### Scientific (not code)

8. **LoveSmarter replication** — the real study is ready (preflight passes, config
   migrated to v1). Blocked on advisor decision about CFA/measurement basis.
   Once settled: `rrg dispatch --stage replication --model "default" --validator
   hermes --mode agent --root workspace/LoveSmarter`

9. **Robustness runs** — after replication is graded, run robustness on
   Demo_MovieRatings and LoveSmarter.

10. **Advisor meeting** — `docs/ADVISOR_MEETING.md` has the demo plan + three
    decisions needed (CFA basis, generalization design, paper scope).

### Future

11. **Generalization stage** — define data-variation plan, enable the stage,
    run it. Blocked on advisor input.

12. **Methods paper** — per `docs/PHASES.md` Phase 4: per-finding validation-depth
    tiers, cross-model agreement, paper draft with LoveSmarter as worked example.

---

## Key files for next session

- `WALKTHROUGH.md` — how to run the pipeline
- `docs/AGENTIC_CLI_DESIGN.md` — the design spec (all implemented)
- `docs/agent-references/EXECUTOR_REFERENCE.md` — validator CLI commands
- `docs/friction-log.md` — what broke during real runs
- `skills/rrg-eval/SKILL.md` — evaluation methodology
- `workspace/Demo_MovieRatings/` — working demo with 2 runs + evals
- `workspace/LoveSmarter/` — real study, ready to run

## Quick start for next session

```bash
cd RRG_root/rrg-cli
python3.13 -m venv .venv && .venv/bin/pip install -e '.[dev]'
PYTHONPATH=src .venv/bin/python -m pytest  # 170 passed, 1 skipped
.venv/bin/rrg tui                          # launch the TUI
.venv/bin/rrg setup --status --root workspace/Demo_MovieRatings  # check demo
.venv/bin/rrg setup --status --root workspace/LoveSmarter        # check real study
```
