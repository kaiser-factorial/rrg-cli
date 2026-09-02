# RRG Agentic CLI Foundation — Design Document

> **Status:** Implemented and hardened through 2026-09-02. This document covers the
> agentic CLI phase plus deterministic metric contracts, semantic gates, transactional
> imports, explicit operator paths, and shared Review UI/scorecard comparison.
> Companion: `docs/PHASES.md` (strategic roadmap), `docs/agentic-rrg-parked.md` (the
> parked vision — this is the first concrete step toward un-parking it).

---

## 1. Goals

Replace the human-operator-drives-the-GUI loop with an agent-drives-the-CLI loop. The
GUI is parked. The CLI becomes the primary interface, extended with:

1. **Prefs** — saved user defaults (validator, discussion mode, gates, etc.)
2. **Dispatch** — one command that builds, prompts, runs the validator, and imports results
3. **Normalizer** — auto-normalizes non-conforming validator returns on import
4. **Wizard** — interactive full-setup walkthrough (init → convert → preflight → package)
5. **Simplified origin intake** — streamlined for the agentic case
6. **Blinded contracts** — public metric/analysis structure without origin answers
7. **Transactional return handling** — gate the staged writable root, then atomically import

The existing 80 tests must stay green. New code is tested first (failing tests), then
implemented to pass.

---

## 2. Prefs System (`prefs.py`)

### Purpose

Save user defaults so `rrg dispatch` and `rrg wizard` don't need 6 flags every time.
Prefs are per-project (not global), living in `.rrg_prefs.yaml` at the project root.

### File: `.rrg_prefs.yaml`

```yaml
# RRG user preferences (per-project, gitignored)
validator: manual         # manual | hermes | claude | codex | grok | pool | openrouter
mode: discuss             # discuss | nodiscuss | agent
skip_normalize: false     # auto-normalize on import?
auto_import: true         # auto-import after dispatch completes?
open_browser: false       # (reserved for GUI un-park)
```

### Module: `src/rrg_cli/prefs.py`

```python
DEFAULTS = {
    "validator": "manual",
    "mode": "discuss",
    "skip_normalize": False,
    "auto_import": True,
}

def load_prefs(project: Project) -> dict[str, Any]:
    """Load .rrg_prefs.yaml, merged over DEFAULTS. Missing file → DEFAULTS."""

def save_prefs(project: Project, prefs: dict[str, Any]) -> None:
    """Write .rrg_prefs.yaml (only known keys; unknown keys preserved)."""

def get_pref(project: Project, key: str) -> Any:
    """Load prefs and return one key."""
```

### CLI: `rrg prefs`

```text
rrg prefs                          # show all current prefs
rrg prefs --set validator=hermes   # set one pref
rrg prefs --set mode=agent         # set another
rrg prefs --reset                   # reset to defaults
```

### `.gitignore` addition

Add `.rrg_prefs.yaml` to `.gitignore`.

### Tests (`test_prefs.py`)

- `test_load_defaults_when_no_file` — returns DEFAULTS when `.rrg_prefs.yaml` absent
- `test_save_and_load` — save then load round-trips
- `test_partial_override` — setting one key doesn't clobber others
- `test_reset` — reset restores DEFAULTS
- `test_unknown_key_preserved` — unknown keys survive save/load
- `test_get_pref_single_key` — get_pref returns one value

---

## 3. Validator Dispatch (`dispatch.py`)

### Purpose

One command that orchestrates: **package → render prompt → call validator → gate → import**.
Replaces the manual flow of `rrg package` → copy zip → run model externally → `rrg import`.

### Modes

| Mode | Behavior | Who acts as "operator" in discuss turns? |
|---|---|---|
| `discuss` (default) | Prompt rendered turn-by-turn; human reviews each turn | Human (interactive) |
| `nodiscuss` | All non-discuss turns sent in sequence; no discussion | N/A (no discuss turns) |
| `agent` | Built-in loop: harness sends turns to validator, acts as operator for discuss turns | The dispatch module itself |

### Validators

| Validator | How it calls the validator model | Package delivery |
|---|---|---|
| `manual` (default) | Prints zip path + prompt turns + instructions; human runs externally | Zip path printed |
| `hermes` | Shells out to `hermes chat -Q --query-file ... --in ... --resume` | Zip extracted to temp dir, validator runs there |
| `claude`, `codex`, `grok`, `pool` | Shells out to the installed CLI with session continuation where supported | Same — temp dir |
| `openrouter` | Calls OpenRouter API directly (httpx) | Same — temp dir |
| `prime-agent` | Spawns a prime-agent subagent via `rlm()` | Same — temp dir |

### Flow (manual validator)

```
rrg dispatch --stage replication --model "Gemini (confirm flagship)" --validator manual
```

1. Load prefs; merge with CLI flags (flags win).
2. `build_package(project, stage, model)` — reuse existing packager. If already built
   and `--reuse` is set, skip. If `--dry-run`, stop after lint.
3. `render_prompt(project, stage, model, mode=mode)` — render turns.
4. Print: zip path, output folder, report name, each turn (numbered, with title).
5. Print instructions: "Run the validator on this zip outside the project. When done,
   run `rrg import <returned>` to bring results back."
6. Exit 0.

### Flow (Hermes validator)

```
rrg dispatch --stage replication --model "Gemini (confirm flagship)" --validator hermes
```

1. Same prep (package + render prompt).
2. Extract zip to a temp dir OUTSIDE the project tree.
3. For each turn:
   - `nodiscuss`: send all turns sequentially to `hermes chat -Q`, resuming one session.
   - `discuss`: print turn 1, pause for human input ("press enter to continue"),
     then send. For discuss turns (Turns 3–5), the human types their input.
   - `agent`: send turn 1, collect response. For discuss turns, the dispatch module
     generates an operator response (e.g. "Looks defensible. Proceed." or a push-back
     based on heuristics). Send that back. Continue until all turns are processed.
4. Gate the actual writable deliverable root and run the bounded revision loop.
5. Collect new/changed validator files from the temp dir.
6. If `auto_import` (default): call `import_run` with the temp dir as source.
7. If `skip_normalize` is False: run normalizer on the imported run.
8. Report: files collected, gate/import/breach status, and normalization report.
9. Cleanup temp dir.

### Flow (OpenRouter validator)

OpenRouter is text-only and therefore cannot satisfy filesystem deliverables or the
gate/revision loop. It remains available for prompt-response workflows:
1. Read `OPENROUTER_API_KEY` from env.
2. Resolve model slug from `dispatch.model_slugs` in `rrg.yaml`.
3. For each turn: `POST https://openrouter.ai/api/v1/chat/completions` with
   `{"model": slug, "messages": [...], "temperature": 0}`.
4. Record assistant responses; no automatic filesystem import is claimed.

### Flow (prime-agent validator)

Same structure, but spawns a subagent:
1. `handle = await rlm(f"Run this validation package...", name=f"validator-{stage}-{model}")`
2. Send the prompt turns as messages to the child.
3. Child writes outputs to a known directory.
4. Read outputs, import, normalize, report.

Note: prime-agent validation requires the async IPython context. The CLI command
detects this and errors clearly if called outside it.

### Module: `src/rrg_cli/dispatch.py`

```python
def dispatch(
    project: Project,
    stage: str,
    model: str,
    *,
    validator: str | None = None,
    mode: str | None = None,       # discuss | nodiscuss | agent
    label: str | None = None,
    dry_run: bool = False,
    reuse: bool = False,
    skip_normalize: bool | None = None,
    auto_import: bool | None = None,
    force: bool = False,
    gates: bool | None = None,
    gate_revisions: int | None = None,
    gate_exec: bool | None = None,
    gate_python: str | None = None,
) -> dict[str, Any]:
    """Orchestrate a validation dispatch. Returns a dict with:
    - package: the build_package result
    - prompt: the RenderedPrompt summary (turns, output_folder, report_name)
    - zip_path: the delivery zip path
    - validator: which validator harness was used
    - conversation: list of {turn, prompt, response} dicts (empty for manual)
    - import_result: the import_run result (None if auto_import=False or manual)
    - normalize_result: the normalize result (None if skip_normalize or no import)
    - instructions: str (for manual validation; empty otherwise)
    """
```

### CLI: `rrg dispatch`

```text
rrg dispatch --stage S --model M
    [--validator manual|hermes|claude|codex|grok|pool|openrouter|prime-agent]
    [--mode discuss|nodiscuss|agent]
    [--label L] [--dry-run] [--reuse]
    [--skip-normalize] [--no-auto-import]
    [--force] [--no-gates] [--gate-revisions N]
    [--no-exec-gates] [--gate-python PATH] [--json]
```

Defaults come from prefs. Flags override prefs.

### Tests (`test_dispatch.py`)

- `test_dispatch_manual_prints_instructions` — manual validation produces zip path + turns + instructions
- `test_dispatch_dry_run` — dry-run stops after package lint, no zip written
- `test_dispatch_reuse_skips_build` — reuse=True skips build_package when a matching run exists
- `test_dispatch_blocked_package` — if package lint fails and no --force, dispatch stops with exit 2
- `test_dispatch_force` — --force publishes despite lint failure
- `test_dispatch_mode_nodiscuss_filters_turns` — nodiscuss mode excludes discuss-tagged turns
- `test_dispatch_mode_agent_generates_operator_responses` — agent mode produces operator responses for discuss turns
- `test_dispatch_hermes_shells_out` — (mocked) hermes call produces conversation
- `test_dispatch_openrouter_api_call` — (mocked) OpenRouter API produces conversation
- `test_dispatch_auto_import` — auto_import=True calls import_run
- `test_dispatch_no_auto_import` — auto_import=False skips import
- `test_dispatch_skip_normalize` — skip_normalize=True skips normalizer
- `test_dispatch_with_prefs` — prefs supply defaults when flags omitted

---

## 4. Output Normalizer (`normalize.py`)

### Purpose

Validators don't always follow the deliverable contract. The normalizer parses
non-conforming returns into the canonical shape the extract/grading modules expect:

```
raw/Q<n>_summary.json    # flat JSON: question, n, test, statistic, p_value, effect_size, ci, conclusion
raw/Q<n>_raw.csv         # raw outputs
Q<n>_analysis.py         # analysis script
Q<n>_fig.py              # figure script
Q<n>_fig.png             # figure image
DYFA sections in report  # ## Q<n> with D/Y/F/A
SUMMARY.md               # index of per-question artifacts
```

### Detection strategy

1. **Scan the run folder** for all files.
2. **Fuzzy-match Q-numbered files**: patterns like `Q1_analysis.py`, `q1_analysis.py`,
   `Q01_analysis.py`, `analysis_q1.py`, `q1.py`, `visual_q1.png`, `q1_fig1.png`, etc.
   → rename/copy to canonical `Q{n}_*.py` / `Q{n}_fig.png`.
3. **Check for `raw/Q<n>_summary.json`**: if missing, try to parse stats from:
   - The analysis script (regex for `statistic`, `p_value`, `effect_size`, etc.)
   - Output text files (`q{n}_results.txt`, `SUMMARY.md`, `RAW.md`)
   - The report markdown (DYFA sections)
4. **Check for DYFA sections**: if the report isn't in `## Q<n>` format, try to split
   by question references and resection.
5. **Report**: what was found, what was normalized, what's still missing.

### Module: `src/rrg_cli/normalize.py`

```python
def normalize_run(project: Project, run_path: Path) -> dict[str, Any]:
    """Normalize a validator run folder into canonical deliverable shape.
    Returns:
    - normalized: list of {question, actions: [str], status: "ok"|"partial"|"missing"}
    - files_moved: list of {from: str, to: str}
    - summary_json_created: list of int (question numbers)
    - missing: list of int (questions with no detectable material)
    - report: str (human-readable summary)
    """

def check_deliverable_contract(run_path: Path, question_count: int) -> dict[str, Any]:
    """Check whether a run folder conforms to the deliverable contract.
    Returns per-question: has_analysis, has_raw_csv, has_fig_py, has_fig_png,
    has_summary_json, has_dyfa_section. Does NOT modify anything.
    """
```

### Integration with import

`import_run` gains a `normalize: bool = True` parameter. When True (default), after
copying files it calls `normalize_run`. The `--skip-normalize` CLI flag sets it False.

The import result dict gains:
```python
"normalize": normalize_result  # or None if skipped
```

### Tests (`test_normalize.py`)

- `test_contract_check_conforming` — a perfectly conforming run passes with no changes
- `test_contract_check_missing_files` — detects missing summary.json, figures, etc.
- `test_fuzzy_match_q_files` — matches `q1_analysis.py`, `Q01_fig.png`, `visual_q1.png`, etc.
- `test_rename_to_canonical` — renames fuzzy matches to `Q{n}_*` format
- `test_create_summary_from_script` — parses stats from a Python script when no JSON exists
- `test_create_summary_from_results_txt` — parses stats from results text
- `test_resection_dyfa` — splits a non-`## Q<n>` report into question sections
- `test_normalize_preserves_originals` — original files are not deleted, only copied
- `test_normalize_missing_question` — a question with no material is reported as missing
- `test_normalize_idempotent` — running normalize twice produces no changes the second time
- `test_import_auto_normalize` — import_run with normalize=True runs the normalizer
- `test_import_skip_normalize` — import_run with normalize=False skips it

---

## 4b. Deliverable Gates (`gates.py`)

### Purpose

The normalizer repairs non-conforming returns *after the fact*, silently. The gates
enforce the contract *while the validator is still on the line*, so the model fixes
its own structure and the operator sees exactly what was delivered. The pattern is
the observation → revision loop from a plan-validation harness: a deterministic
validator raises coded violations, the harness hands them back as feedback, the model
gets a bounded number of revisions, and every attempt is recorded.

### Rules

- Every check is a pure function of the files on disk. No model judgment.
- Every violation carries `code`, `message`, `severity`, `question`, `path` (observed)
  and `expected` (the fix), so feedback is mechanically actionable.
- Any violation, hard or soft, triggers a revision turn while revisions remain. Only
  **hard** violations decide pass/fail (and the exit code); **soft** ones are asked for
  but never fail the run. A revision that leaves the soft set unchanged stops the loop.
- Feedback is model-facing and therefore blinding-sensitive: it is built only from
  codes and artifact coordinates — never returned values, comparison deltas, origin
  contents, or operator files. Structural errors can be repaired directly. Semantic
  errors instruct the validator to regenerate the affected artifact from its own
  scripts/data; the gate never tells it the expected answer.

### Checks (per question n)

| Code | Severity | Trigger |
|---|---|---|
| `MISSING_FILE` | hard | none of the five required files for this kind exists |
| `MISNAMED_FILE` | hard | a fuzzy-matched candidate exists under a different name |
| `MISPLACED_FILE` | hard | canonical name, wrong folder (e.g. `Q1_summary.json` at root) |
| `EMPTY_FILE` | hard | required file is zero bytes |
| `INVALID_PNG` | hard | `Q<n>_fig.png` does not start with the PNG magic |
| `INVALID_JSON` / `SUMMARY_NOT_OBJECT` | hard | summary is not a JSON object |
| `SUMMARY_MISSING_KEY` | hard | one of `question n test statistic p_value effect_size conclusion` absent |
| `SUMMARY_QUESTION_MISMATCH` | hard | `question` does not resolve to n |
| `SUMMARY_BAD_TYPE` | hard | `n`/`statistic`/`p_value` non-numeric, `conclusion` empty |
| `P_VALUE_ZERO` | hard | `p_value == 0` |
| `P_VALUE_BOUND_STRING` | soft | `p_value` is a bound like `"<1e-300"` |
| `P_VALUE_NULL` | soft | `p_value` is null |
| `SUMMARY_NOT_FLAT` | soft | nested object values (seen in real runs: `groups`) |
| `ANALYSIS_NO_CSV_WRITE` / `FIG_SCRIPT_NO_CSV_READ` / `FIG_SCRIPT_NO_PNG_WRITE` | hard | script never names the file it must write/read (literal `Q<n>_raw.csv` or a template like `Q{q}_raw.csv` / `Q%d_raw.csv` both count) |
| `MISSING_DYFA_SECTION` | hard | no `## Q<n>` / `## Question n` heading (same regex as `check_deliverable_contract`) |
| `MISSING_DYFA_LABELS` | hard | section lacks `D - Do`, `Y - Why`, `F - Find` or `A - Answer` |
| `FIGURE_NOT_EMBEDDED` | hard | section never references `Q<n>_fig.png` |
| `METRIC_MISSING` / `METRIC_BAD_TYPE` | hard | a declared metric path is absent or has the wrong type |
| `METRIC_NULL_NOT_ALLOWED` | hard | null supplied for a non-nullable metric |
| `METRIC_EXTRA` | hard | an undeclared numeric summary field is present |
| `METRIC_UNIT_MISSING` / `METRIC_UNIT_MISMATCH` | hard | `_units` lacks the exact declared unit |
| `ARITHMETIC_MISMATCH` | hard | a declared sum/difference relation does not hold exactly |
| `DYFA_METRIC_MISSING` / `DYFA_METRIC_MISMATCH` | hard | F/A marker absent or inconsistent with summary JSON |

Run-level: `MISSING_REPORT` (hard), `REPORT_MISNAMED` (soft, found under a fallback
name), `MISSING_INDEX` (hard, `RAW.md` / `SUMMARY.md`), `NO_QUESTION_COUNT` (soft).

### Executable figure gate (`exec_figures`)

For each question whose static figure checks pass, `Q<n>_fig.py` is executed in the
deliverable root (cwd, `MPLBACKEND=Agg`, under the dispatch's sandbox prefix, per-script
timeout 120 s, 600 s total budget) with the delivered PNG moved aside; the delivered PNG
is always restored.

| Code | Severity | Trigger |
|---|---|---|
| `FIG_SCRIPT_FAILED` | hard | non-zero exit (stderr saved to `_gates/Q<n>_fig.stderr.txt`) |
| `FIG_SCRIPT_TIMEOUT` | hard | exceeded the per-script timeout |
| `FIG_NOT_REGENERATED` | hard | ran cleanly, never wrote `Q<n>_fig.png` |
| `FIG_MISMATCH` | hard | different dimensions, or > 15 % of pixels differ; regenerated PNG kept under `_gates/` |
| `FIG_RENDER_DRIFT` | soft | same dimensions, ≤ 15 % pixels differ (different matplotlib build); regenerated copy discarded |
| `FIG_SCRIPT_ENV_MISSING` | soft | `ModuleNotFoundError` / `ImportError` on this machine |
| `FIG_EXEC_SKIPPED` | soft | total time budget exhausted |
| `NO_GATE_INTERPRETER` | soft | no interpreter imports matplotlib + pandas (set `gate_python`) |

Calibration (2026-09-02): the 22 Demo figures re-rendered under matplotlib 3.9.4
instead of the validator's 3.10.6 all had identical dimensions and 2–6 % changed
pixels (text anti-aliasing) — hence the 15 % tolerance. Interpreter resolution:
`gate_python` pref → `<work_dir>/.venv/bin/python` → `python3`, `/usr/bin/python3`,
`sys.executable`, first that imports matplotlib and pandas (probe results cached).
Default on for dispatch, off for `rrg import` (`--exec-gates`).

### Deliverable root

Prompts say "put all work in {OUTPUT_FOLDER}", so a conforming validator may nest its
output. `locate_deliverable_root` prefers `work_dir/OUTPUT_FOLDER` when it holds
question files, then `work_dir`, then whichever folder holds the most question-numbered
files. Near-miss detection is `rglob`-based, so a misplaced file is reported with both
its observed and expected path.

### Module

```python
def check_gates(work_dir, question_count, report_name="", *, output_folder=None) -> GateResult
GateResult.passed / .hard / .soft
GateResult.as_observation() -> dict     # machine-readable, JSON-serializable
GateResult.feedback(attempt, max_revisions) -> str   # the revision turn
def project_question_count(project) -> int
def project_report_name(project, stage, model) -> str
def gate_record(result, *, source) -> dict   # same shape the dispatch loop produces
```

### Integration

- `dispatch.py::_gate_loop` runs after the validator's final turn (CLI validators only;
  `openrouter` has no filesystem). Revision turns reuse the session id and are appended
  to the conversation as `Gate revision k` with the triggering observation attached.
- `dispatch()` gains `gates: bool | None` and `gate_revisions: int | None`; prefs
  `gates` (True) and `gate_revisions` (1) supply defaults. CLI: `--no-gates`,
  `--gate-revisions N`. Exit code `3` when gates still fail.
- `import_run(..., gates=record)` writes `GATES.json` and a `RUN_INFO.md` line. With no
  record (manual `rrg import`), the complete untrusted return is staged, its actual
  deliverable root is gated once *before* normalization, and only then is it atomically
  installed in the authoritative run destination.
- `eval_run` reads `GATES.json` and surfaces it in the report.

### Tests (`test_gates.py`)

Pure checks (conforming, empty, misnamed/misplaced, schema, real-world soft shapes,
PNG/empty, report sections, fallback report name, script advisories, nested root,
feedback content and blinding), the dispatch loop with a stateful stand-in validator
(revise-and-pass, exhausted revisions still import, disabled, revisions=0, prefs),
openrouter skip, import-time record before normalization, eval surfacing, pref coercion.

## 4c. Enforced Isolation (`sandbox.py`, dispatch write detection)

See ADR 0003 for the incident and decision. Mechanics:

- `sandbox.make_sandbox(project, work_dir, validator)` returns the command prefix, deny
  list, explicit writable roots, enforcement state, and fallback reason. Denied roots
  are the project + git toplevel + `dispatch.sandbox_deny`. macOS also denies writes
  outside the work dir, `/dev`, the validator state directory, and
  `dispatch.sandbox_write_allow`. A capability probe verifies that the host can apply
  the profile; finding `sandbox-exec` on `PATH` is insufficient.
- `dispatch._SANDBOX_PREFIX` (module state) is applied by `_run()` to every validator
  subprocess; the same prefix is passed to the exec gate as `exec_prefix`.
- `_snapshot_tree` / `_detect_escapes`: `{rel: (size, mtime_ns)}` over the git toplevel
  (skipping `.git`, `.venv`, `node_modules`, `__pycache__`), diffed after the run. New
  files under the package dir are moved into the collection dir (`quarantined_to`).
  Records go to `import_run(wrote_inside_project=…)` → `grading.record_breach`, where
  they are blocking like `copied_secrets`.
- `packager` calls `utils.make_read_only` on the package dir and chmods the zip 0444;
  `archive._move` restores write permission for the rename; `utils.remove_tree` handles
  read-only purges.
- `_inventory_preamble(work_dir)` is prepended to turn 1 for CLI validators.
- `_exec_hermes_turn` uses `hermes chat -Q --query-file F --in DIR --no-restore-cwd
  --run-budget 900 [--resume SID]`; `_parse_hermes_output` strips the toolset warning
  and reads `session_id:` from stderr.

Tests: `test_isolation.py`.

## 4d. Blinded contracts, comparison, and transactional imports

### Contract split

- `shared/METRIC_SPEC.json` uses `rrg.metric-specs.v1` and is safe to package. Each
  metric declares `id`, `label`, `validator_path`, `kind`, `unit`, and `nullable`.
  Optional relations support only `sum_equals` and `difference_equals` across metrics
  with the same unit. Answer-, method-, formula-, origin-, and tolerance-bearing keys
  are rejected recursively.
- `operator/origin/origin.json` uses `rrg.origin-results.v1` and maps those metric ids
  to canonical values/units. It is operator-only and blocked even if routing would
  flatten its filename.
- Optional robustness contracts (`rrg.analysis-contract.v1`) hold population, unit of
  analysis, inclusion/exclusion, time window, constructs/outcomes, and missingness
  fixed while explicitly requiring independent method selection. The normalizer audit
  blocks inputs that still contain detected derived/answer-bearing columns.
- Each required `study.yaml > derived_models` declaration points to an operator-side
  `rrg.model-evaluation.v1` record. The gate binds an artifact SHA-256 to independent
  ground truth and computes operator-defined acceptance criteria from task-appropriate
  metrics; claimed pass/fail fields have no authority.

### Comparison policy

`extract.question_extraction` is shared by scorecard generation and GUI review. It
prefers the canonical id/path join and falls back to legacy text extraction only when
canonical records are absent. Units are normalized before comparison. Non-p-value
metrics have zero tolerance. P-values alone use an absolute `0.005` band owned by RRG;
inside-band non-exact values are still emitted as `within_tolerance` with a delta.

### Import transaction and run identity

New projects declare `operator/{packages,runs,reviews,grading,archive}`. `layout.py`
resolves these paths and preserves legacy behavior for existing configs. Package
provenance records one portable `output_path`, which controls the eventual run even if
the validator reports a different runtime model name.

`import_run` stages an untrusted folder/zip outside the project. It validates every zip
member before extraction, rejects traversal, duplicate/case-colliding paths and source
symlinks, strips one transport wrapper, and gates the located deliverable root. The
staged tree is copied to a unique sibling candidate and atomically renamed into an
empty destination; a non-empty run is never overwritten. Dispatch snapshots the
extracted package and imports only new/changed files when output shares that root.

See ADR 0004 and tests in `test_metrics.py`, `test_analysis_contract.py`,
`test_model_eval.py`, `test_gates.py`, `test_dispatch.py`, `test_dispatch_new.py`,
and `test_cli.py`.

## 5. Wizard (`wizard.py`)

### Purpose

Interactive walkthrough that calls existing commands in sequence, reports status at
each step, and lets the user proceed or fix issues. Also manages prefs defaults.

### Flow

```
rrg wizard
```

```
RRG Wizard — LoveSmarter-validation

Step 1/5: Project health
  ✓ .rrg_root found
  ✓ rrg.yaml valid (v1)
  ✓ study.yaml valid
  → Press enter to continue

Step 2/5: Data conversion
  ✓ Source: data/source.csv (26 MB)
  ✓ CSV derivative verified
  ✓ Parquet derivative verified
  → All good. Press enter to continue.

Step 3/5: Preflight readiness
  ✓ All dependencies available
  ✓ All inputs found
  ✓ Replication: 9 inputs resolved, 3 turns render
  ✓ Robustness: 8 inputs resolved, 7 turns render
  ⚠ Generalization: disabled (no data plan)
  → Ready for replication + robustness. Press enter to continue.

Step 4/5: Roster review
  Replication models:
    1. Gemini (confirm flagship) — frontier, Google
    2. Nemotron-3 (Super/Ultra) — open, NVIDIA
  Robustness models:
    1. GPT-5.5 — frontier, OpenAI (done)
    2. DeepSeek (confirm) — open, DeepSeek (pending)
    3. Laguna-M.1 — open, Poolside (partial)
  → Which stage+model to dispatch? (e.g. "replication 1" or "skip")

Step 5/5: Dispatch
  → Executor? [manual/hermes/openrouter/prime-agent] (default: manual)
  → Mode? [discuss/nodiscuss/agent] (default: discuss)
  Building package...
  ✓ Package published (run_id: a0efcecd)
  ✓ Lint passed
  ...
```

### Non-interactive mode

```text
rrg wizard --non-interactive    # runs all steps, prints status, exits
rrg wizard --step 3             # jump to a specific step
rrg wizard --prefs              # interactive prefs editor
```

### Prefs editor

```
rrg wizard --prefs

Current preferences:
  validator: manual
  mode: discuss
  skip_normalize: false
  auto_import: true

Edit which? [validator/mode/skip_normalize/auto_import/gates/gate_revisions/gate_exec/gate_python/reset]
> validator
  Options: manual, hermes, claude, codex, grok, pool, openrouter, prime-agent
  Current: manual
  New value: hermes

Saved .rrg_prefs.yaml
```

### Module: `src/rrg_cli/wizard.py`

```python
def run_wizard(
    project: Project,
    *,
    non_interactive: bool = False,
    step: int | None = None,
    prefs_editor: bool = False,
) -> dict[str, Any]:
    """Run the interactive wizard. Returns a dict with:
    - steps: list of {name, status, checks: [...], actions: [...]}
    - dispatch_result: the dispatch result if dispatched (None otherwise)
    - prefs: current prefs dict
    """

def wizard_prefs_editor(project: Project) -> dict[str, Any]:
    """Interactive prefs editor. Returns the saved prefs."""
```

### Tests (`test_wizard.py`)

- `test_wizard_non_interactive_all_steps` — non-interactive mode runs all 5 steps
- `test_wizard_health_check` — step 1 reports project health correctly
- `test_wizard_conversion_check` — step 2 reports conversion status
- `test_wizard_preflight_check` — step 3 reports preflight status
- `test_wizard_roster_display` — step 4 lists roster models
- `test_wizard_jump_to_step` — --step N jumps to that step
- `test_wizard_prefs_editor` — prefs editor saves changes
- `test_wizard_prefs_reset` — prefs editor reset restores defaults

---

## 6. Simplified Origin Intake

### Current state

`origin.py` (535 lines) has a complex intake flow:
- Renders an intake prompt from a template (`prompts/origin_intake.md`)
- The origin model returns SUMMARY.md + a fenced `figure_map` YAML
- `save_intake` splits them, writes SUMMARY.md, copies figures by filename match,
  writes `figure_map.yaml`, runs a presence linter

### Simplification for agentic case

The agent can read the origin `SUMMARY.md` directly. The separate intake prompt +
return + apply flow is unnecessary overhead when an agent is driving.

**Change:** Add a `rrg intake --simplify` flag (and a `simplify_intake: true` pref)
that:
1. Reads the origin report directly (if it's markdown) or prints the intake prompt
   for the origin model (if it's a PDF and needs transcription).
2. If the origin already has a `SUMMARY.md` with `## Q<n>` sections, skip intake entirely.
3. If not, render the intake prompt but with a simpler template — just "transcribe the
   report into `## Q<n>` sections with these fields" — no figure_map.
4. Figure mapping becomes the normalizer's job (it already fuzzy-matches figures).

This doesn't remove the existing intake flow — it adds a simpler path. The complex
flow stays for cases where the origin report is a PDF with embedded figures that need
the model to name the mapping.

### Tests

Added to `test_intake.py`:
- `test_simplify_intake_skips_when_summary_exists` — if SUMMARY.md has all Q sections, skip
- `test_simplify_intake_renders_simple_prompt` — simplified prompt has no figure_map block
- `test_simplify_intake_apply` — applying a simplified intake just writes SUMMARY.md

---

## 7. CLI surface (`cli.py`)

The top-level help is grouped by the actual workflow: orient, prepare, validate,
review, and maintain. Human-readable aliases preserve the original command names:

| Canonical | Alias | Purpose |
|---|---|---|
| `doctor` | `status` | inspect project/configuration readiness |
| `dispatch` | `validate` | package, run, gate, and import |
| `scorecard` | `review` | generate the operator review |

Every project command accepts both `--root` and `--project`. `rrg workspace [PATH]`
discovers cartridges under a workspace, and `rrg paths` prints the resolved operator
layout; both offer JSON output for agents. `rrg prompt --mode agent` uses the same mode
vocabulary as dispatch. Failed imported gates return exit code `3` instead of a generic
configuration error.

Dispatch flags include `--validator`, `--mode`, `--label`, `--dry-run`, `--reuse`,
`--skip-normalize`, `--no-auto-import`, `--force`, `--no-gates`,
`--gate-revisions`, `--no-exec-gates`, `--gate-python`, and `--json`. Unspecified
preference-backed flags resolve from `.rrg_prefs.yaml` and then the built-in defaults.

---

## 8. Historical implementation order

Build bottom-up, test-first:

1. **prefs.py + test_prefs.py** — no dependencies on other new modules
2. **normalize.py + test_normalize.py** — depends only on existing modules
3. **Hook normalizer into importer.py** — small modification + test
4. **dispatch.py + test_dispatch.py** — depends on prefs + normalize + existing modules
5. **wizard.py + test_wizard.py** — depends on prefs + dispatch + existing modules
6. **Simplified origin intake** — small addition to origin.py + test
7. **cli.py** — wire up all new subcommands
8. **Full test suite** — existing + new failure-first tests, all green
9. **Update .gitignore** — add `.rrg_prefs.yaml`
10. **Update HANDOFF.md** — document the new commands

---

## 9. Preserved invariants

- **Blinding lint remains non-negotiable.** Public contracts cannot contain answers,
  origin values, methods, formulas, or tolerance policy.
- **Origin comparisons remain operator-only.** Validator revision feedback is derived
  only from the validator's own artifacts and the public contract.
- **Returned bytes remain evidence.** Failed gated output is retained for audit and is
  never silently converted into a pass.
- **Provenance remains append-only.** Package/run identity and every gate attempt are
  recorded.
- **Legacy cartridges remain readable.** New layout keys are opt-in for existing
  projects; no evidence is automatically moved.
- **Scientific verdicts remain human-owned.** Automation exposes exactness and
  divergence but does not assign the final research judgment.

---

## 10. Design decisions and rationale

### Why prefs are per-project, not global

Different studies may use different validators (MovieRatings demo vs. LoveSmarter real
run). Per-project prefs via `.rrg_prefs.yaml` keep each study self-contained, consistent
with the cartridge philosophy.

### Why the normalizer doesn't delete originals

Validators' raw output is evidence. The normalizer copies/renames into canonical shape
but never deletes. If a human later needs to inspect what the validator actually
produced, the originals are still there.

### Why `agent` mode generates operator responses internally

The robustness prompt's discuss turns (3–5) require an "operator" to push back on
method choices. In `agent` mode, the dispatch module acts as that operator. It generates
conservative responses like "Looks defensible. Proceed to lock." or, if it detects
potential issues (e.g., a method that doesn't match the question type), a push-back.
This is intentionally simple — it's not trying to be a brilliant methodologist, just
to keep the multi-turn flow moving without a human.

### Why `prime-agent` validation is included

The prime-agent adapter lets RRG dispatch spawn a subagent that runs the validator
model. This is the natural path toward fully agentic RRG: the dispatch command itself
becomes an agent orchestrating other agents. It requires the async IPython context
(available when running from a prime-agent session), and errors clearly otherwise.

### Why the wizard is non-interactive-capable

The wizard's non-interactive mode (`--non-interactive`) lets an agent or CI pipeline
run the full health check sequence programmatically. The interactive mode is for
human operators (a lightweight TUI, not a web GUI).
