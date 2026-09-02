# rrg-cli

`rrg-cli` is the reusable engine behind the RRG research-validation workflow:
**Replication → Robustness → Generalization**. It packages the right inputs for a
validator, enforces stage-specific blinding, records provenance, renders staged
prompts, dispatches supported validator CLIs, imports their outputs, and scaffolds
human grading. Scientific verdicts remain operator-owned.

## Install

```bash
python3.13 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e /path/to/rrg-cli
```

Python 3.9+ and pip 21.3+ are required for editable installation. Upgrading pip
first is important on macOS system-Python environments, which may create a virtual
environment with pip 21.2. Data conversion dependencies are installed with the
package so `rrg convert` works immediately. The TUI requires `rich>=13.0`,
included in the dependencies.

## Getting started

See **[WALKTHROUGH.md](WALKTHROUGH.md)** for a step-by-step guide to running the
pipeline from scratch (given a dataset + a report).

## Start a project

```bash
rrg init my-validation
cd my-validation
rrg doctor
```

An RRG project contains a `.rrg_root` marker, `rrg.yaml` engine manifest,
`study.yaml` cartridge, model-facing `shared/`, source `data/`, withheld
`operator/`, and prompt scaffolds. Replace the starter content and update the two
YAML files; the CLI itself never needs study-specific edits. The starter template
lives in `src/rrg_cli/templates/project/` — `rrg init` copies it.

## The CLI

The CLI is the primary interface. All project commands accept `--root` or its
human-readable alias `--project`, plus
`--config`, and `--study`. Project discovery: `$RRG_PROJECT_ROOT` → nearest
`.rrg_root` ancestor → current directory.

### Commands

```text
Project setup
  rrg init [PATH]                        create a project cartridge
  rrg doctor|status [--stage S]          inspect configuration and dependencies
  rrg preflight [--stage S]              strict file + prompt readiness gate
  rrg paths [--json]                     show resolved operator-side locations
  rrg workspace [PATH] [--json]          find RRG projects in a workspace
  rrg convert [SOURCE]                   create and verify CSV/Parquet derivatives
  rrg wizard [--non-interactive]         interactive 5-step setup walkthrough
                                         (--step N, --prefs, --json)

Build & dispatch
  rrg package --stage S --model M        stage, lint, publish, and log a package
                                         (--dry-run, --force, --label L)
  rrg dispatch|validate --stage S --model M
                                          build + run + gate + import in one step
                                         (--validator V, --mode M, --reuse,
                                          --dry-run, --skip-normalize,
                                          --no-auto-import, --force,
                                          --no-gates, --gate-revisions N,
                                          --no-exec-gates, --gate-python P)
  rrg lint PACKAGE --stage S             lint an existing outgoing package
  rrg prompt --stage S --model M         render the stage prompt
                                         (--turn N, --mode discuss|nodiscuss|agent)

Import & review
  rrg import SOURCE [--stage S --model M]  import validator output (auto-normalizes)
                                           (--run-id ID, --skip-normalize, --exec-gates)
  rrg runs                               list the run registry
  rrg scorecard|review --run R --stage S --model M
                                          create a human-grading review
  rrg eval --run R                       evaluate a run (contract + breach + grading)

Origin intake
  rrg intake                             render the origin-intake prompt
  rrg intake --check                     report whether intake is needed
  rrg intake --simplified                simplified prompt (no figure_map)
  rrg intake --apply FILE                apply a returned intake

Preferences
  rrg prefs                              view saved preferences
  rrg prefs --set validator=hermes        set a preference
  rrg prefs --reset                      reset to defaults

TUI
  rrg tui                                launch the interactive terminal UI
  rrg tui --prefs                        interactive prefs editor
  rrg tui --eval RUN                     eval a run with rich output

Lifecycle
  rrg archive PATH                       move a file/dir into reversible archive
  rrg archive-ls                         list archived items
  rrg restore ID                         restore an archived item
  rrg purge ID                           permanently delete an archived item
  rrg acknowledge-breach --run R         acknowledge a blinding breach

  rrg gui [--port 8765]                 (parked) launch the local web GUI
  rrg version                            print the installed version
```

### The dispatch round-trip

`rrg dispatch` is the one-command round-trip that replaces the manual flow of
`rrg package` → copy zip → run model externally → `rrg import`:

```bash
# Manual: builds the package and prints instructions
rrg dispatch --stage replication --model "Gemini 3.1 Pro"

# Automated: shells out to hermes CLI, auto-imports results
rrg dispatch --stage replication --model "Gemini 3.1 Pro" --validator hermes

# Direct API call to OpenRouter, agent-driven discussion
rrg dispatch --stage robustness --model "GPT-5.5" \
    --validator openrouter --mode agent
```

**Validators:** `manual` (prints instructions), `hermes` (shells out to the
Hermes CLI), `openrouter` (calls the OpenRouter API directly),
`prime-agent` (spawns a subagent; requires async IPython context).

**Modes:** `discuss` (default; human reviews each turn),
`nodiscuss` (no discuss turns; model self-proposes and locks),
`agent` (built-in operator response generator drives the discuss loop).

### Preferences

Save defaults so you don't need six flags every time. Preferences are per-project,
stored in `.rrg_prefs.yaml` (gitignored):

```bash
rrg prefs --set validator=hermes
rrg prefs --set mode=nodiscuss
rrg prefs              # view current
rrg prefs --reset      # back to defaults
```

Keys: `validator`, `mode`, `skip_normalize`, `auto_import`, `gates`, `gate_revisions`,
`gate_exec`, `gate_python`.

### Operator layout

New projects use one explicit operator-side layout. `rrg paths` prints the resolved
locations instead of requiring callers to infer them:

```text
operator/
├── origin/                 held-back canonical results
├── packages/               immutable outgoing packages + provenance log
├── runs/<stage>/           one authoritative folder per returned run
├── reviews/                comparison notes and generated reviews
├── grading/                operator grading state
└── archive/                reversible archive
```

Projects that predate these path keys keep their legacy locations. The GUI and CLI
read both layouts; RRG does not silently relocate existing evidence.

### Deliverable gates

The deliverable contract in `study.yaml` is stated to the validator in prose. The
gates re-state it as deterministic file checks and enforce it while the validator is
still on the line. When a CLI validator (`hermes`, `claude`, `codex`, `grok`, `pool`)
finishes its last turn, `rrg dispatch` checks the work dir for, per question, the
five required files (`Q<n>_analysis.py`, `raw/Q<n>_raw.csv`, `Q<n>_fig.py`,
`Q<n>_fig.png`, `raw/Q<n>_summary.json`), the summary JSON schema (required keys,
numeric types, `question` matching `n`, `p_value` never `0`), every metric and unit
declared by `METRIC_SPEC.json`, declared sum/difference identities, a real PNG, and a
DYFA section in the report with all four labels, exact machine-readable metric
markers, and the figure embedded, plus
`RAW.md` and `SUMMARY.md`.

Every violation is a coded observation with the offending path and the expected
one (`MISNAMED_FILE`, `MISPLACED_FILE`, `MISSING_FILE`, `SUMMARY_MISSING_KEY`,
`P_VALUE_ZERO`, `MISSING_DYFA_LABELS`, `FIG_SCRIPT_NO_CSV_READ`, ...). Any
violation earns a revision turn: codes and artifact coordinates go back to the same
session, which must repair the return from its own scripts and data, and the gates run
again, up to
`gate_revisions` times (default 1). Only *hard* violations decide pass/fail. *Soft*
ones — a nested object in the summary JSON, a `"<1e-300"` p-value string, a null
p-value — are asked for but never fail the run, and if a revision leaves them
unchanged the loop stops rather than repeating the same request.

**Executable figure gate.** Naming the files is not the same as producing them. For every
question whose static figure checks pass, dispatch also *runs* `Q<n>_fig.py` in the
output root (under the same OS sandbox as the validator), with the delivered PNG moved
aside, and compares what comes back: byte-identical or pixel-identical → clean;
same dimensions with under 15 % of pixels changed → advisory `FIG_RENDER_DRIFT`
(a different matplotlib build, same figure — calibrated on 22 real figures);
anything else → hard `FIG_MISMATCH`, with the regenerated file kept under `_gates/`
as evidence. A script that crashes, times out, or never writes the PNG fails hard;
one that only lacks a module on this machine is advisory. The interpreter is the
`gate_python` pref, else a `.venv` the validator built, else the first of `python3`,
`/usr/bin/python3`, and RRG's own that imports matplotlib and pandas. Executing
validator code is default-on for `rrg dispatch` and default-off for manual
`rrg import` (`--exec-gates` to opt in), because a manual return may be code that has
never run on this machine.

The outcome, including every attempt's observation, is written to `GATES.json` in
the run folder and summarized in `RUN_INFO.md` and `rrg eval`, so a run that needed
a revision is distinguishable from one that conformed first time. `rrg dispatch`
exits `3` when the gates still fail after the last revision; the files are imported
regardless. Manual returns are gated once at `rrg import` (before normalization) so
the record shows what was actually delivered.

Gate feedback never contains origin values, comparison deltas, or operator-only
material. The validator-facing metric contract defines identifiers, JSON paths, kinds,
units, nullability, and safe arithmetic relations only. Origin values live separately
in `operator/origin/origin.json` and are loaded only by operator-side review.

```bash
rrg dispatch --stage replication --model default --validator hermes --gate-revisions 2
rrg dispatch ... --no-gates            # skip entirely
rrg dispatch ... --no-exec-gates       # static checks only
rrg prefs --set gate_revisions=0       # report only, never send a revision turn
rrg prefs --set gate_python=/opt/anaconda3/bin/python
```

### Enforced isolation

ADR 0001 put the validator in a temp dir and trusted it to stay there. A real run did
not (see ADR 0003): the agent searched the home directory, found the project, and
worked inside the published package. Isolation is now enforced three ways:

- **OS sandbox.** On macOS every validator command runs under `sandbox-exec`. Reads
  and writes are denied under the project and enclosing checkout, and writes are
  allowed only in the run workspace, `/dev`, the selected validator's session-state
  directory, and explicit `dispatch.sandbox_write_allow` roots. The sandbox record
  states whether write enforcement was actually applied. `dispatch.sandbox: off`
  disables it; unsupported/restricted hosts fall back to write detection.
- **Write detection.** The checkout is snapshotted before and after the run. Any
  file the validator created, changed, or removed inside it is an isolation breach:
  recorded on the run, printed as `ISOLATION BREACH`, and blocking grading until
  acknowledged. Files dropped into the published package are quarantined into the
  run so nothing is lost and the package is pristine again.
- **Read-only packages.** Published package dirs and zips are chmod'd read-only.

Dispatch also prepends the absolute working directory and a file inventory to the
first turn, so the validator has no reason to look elsewhere, and the Hermes
validator now uses `hermes chat -Q --resume` so turns share one session
(`hermes -z --resume` silently starts a new one).

### Output normalizer

`rrg import` first validates the entire untrusted return in temporary staging. It
rejects traversal, duplicate/case-colliding archive paths, and source symlinks before
writing any run file; strips one transport-only wrapper; gates the actual staged
deliverable root; and atomically installs it into the provenance-selected run folder.
It never overwrites a non-empty run. Automated dispatch imports only files created or
changed by the validator, not unchanged package inputs.

After that boundary is safe, import auto-normalizes non-conforming validator returns.
If a validator produces `q1_analysis.py` instead of `Q1_analysis.py`, or omits
`raw/Q<n>_summary.json`, the normalizer fuzzy-matches files, parses stats from
text output, and creates the canonical deliverable shape. Originals are
preserved — files are copied, never deleted. Use `--skip-normalize` to opt out.

### Robustness and learned-model prerequisites

A robustness project may point `study.yaml > held_constants.contract` at an approved
`rrg.analysis-contract.v1` JSON record. It fixes the population, unit of analysis,
inclusion/exclusion rules, time window, constructs/outcomes, and missingness policy,
while requiring independent method choice and forbidding origin findings, expected
values, and tolerances. If the Effort normalizer's audit says the selected robustness
input still contains derived or answer-bearing columns, packaging stops.

Any learned scorer, classifier, embedding, or measurement model that creates variables
used downstream belongs under `study.yaml > derived_models`. Its operator-only
`rrg.model-evaluation.v1` record binds an immutable artifact hash to independent ground
truth, task-appropriate metrics, reviewer approval, and operator-defined acceptance
criteria. RRG computes those criteria itself; a claimed `passed` string is ignored.
Binary classification requires ROC AUC or a complete confusion matrix, multiclass a
square matrix with labels, continuous outcomes both error and association metrics,
and ordinal outcomes MAE plus Spearman correlation. Packaging fails when a required
evaluation is missing, malformed, or below its declared threshold.

### Eval-lite

`rrg eval --run R` checks whether a returned run conforms to the deliverable
contract, reports breach status, and shows grading progress:

```bash
rrg eval --run operator/robustness_GPT-5.5
rrg eval --run R --json    # machine-readable
```

### Deterministic comparison policy

Scorecards and the Review UI call the same extraction/comparison engine. Canonical
metrics are joined by question, metric id, and JSON path; units are normalized before
comparison. Non-p-value metrics are exact-only: a reported `8.1` against `8.2` is a
visible difference, never rounded away. P-values alone use a pipeline-owned absolute
band of `0.005`; a non-exact p-value inside that band is still labeled
`WITHIN_TOLERANCE`, with its delta shown. Validators cannot set or widen tolerance.
Legacy text extraction is used only when canonical metric records do not exist.

### Origin intake

`rrg intake` normalizes the origin report into the canonical `SUMMARY.md` the
grading pipeline consumes. Three modes:

```bash
rrg intake --check          # is intake needed? (checks for existing Q sections)
rrg intake --simplified     # simplified prompt (no figure_map)
rrg intake --apply FILE     # apply a returned intake to write SUMMARY.md
```

## The TUI

`rrg tui` launches the interactive terminal UI with a rich, color-coded
interface (Base2Tone Mall palette: gold accent, sage green, dark teal). It shows
an ASCII art banner, a command summary table, and a 5-step walkthrough:

```
rrg tui                    # full interactive wizard
rrg tui --step 3           # run steps 1–3 only
rrg tui --prefs            # interactive prefs editor
rrg tui --eval RUN         # eval a run with rich formatting
```

The 5 steps:

1. **Project health** — `.rrg_root`, `rrg.yaml`, `study.yaml`, config version
2. **Data conversion** — source data, CSV/Parquet derivatives, metadata
3. **Readiness checks** — preflight (dependencies, inputs, routing, prompts)
4. **Roster review** — models per stage with vendor/type/license
5. **Dispatch** — pick stage + model + validator + mode, build, run, import

## Safety model

- Packages are assembled in a temporary directory and published only after lint.
- Original results, scorecards, and operator-only paths are denied by pattern.
- Replication can require an original protocol; robustness can forbid all protocols.
- `--force` can override a lint hard-fail, but the override is recorded.
- The package and prompt are separate. Operator reminders are never model-facing.
- Scorecards remain provisional until a person assigns every verdict.
- Validators run in isolation: packages ship as self-contained zips, results come
  back via `rrg import` with zip-slip protection and breach detection.

## Configuration

`rrg.yaml` owns engine concerns: paths, routing, stages, roster, blinding,
determinism, and dispatch. `study.yaml` owns the cartridge: dataset, questions,
held constants, original work, optional supplied solutions, and deliverables.

Generalization is included in the schema but disabled in the starter manifest. A
project must define its data-variation plan and prompt before enabling that stage;
the CLI does not silently choose a scientific policy.

## GUI (parked)

The web GUI (`rrg gui`) is parked for the agentic CLI phase. It remains functional
but is no longer the primary interface. The CLI + TUI replace it for all
operations. To use it:

```bash
rrg gui --port 8765 --open
rrg gui --workspace /path/to/workspace --open   # multi-project mode
```

## Development

```bash
pip install -e '.[dev]'
pytest                    # 253 tests collected as of 2026-09-02
python -m build
```
