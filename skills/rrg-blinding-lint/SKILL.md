---
name: rrg-blinding-lint
description: >
  The blinding safety-gate for the RRG pipeline. Lints a staged package against the
  stage's blinding rules (withheld files, stage-forbidden methodology, routing drift,
  result-token leaks) and blocks publication on a hard failure. Runs automatically
  inside `rrg package`; run `rrg lint` directly to check an already-built package.
---

# rrg-blinding-lint — the pre-publish blinding gate

The check that stands between "package staged" and "package published." It
mechanically enforces the per-stage blinding rules so a human can't accidentally leak
the results key or the methodology. It runs **on every `rrg package`** (in the staging
directory, before publish); use `rrg lint <package> --stage S` to re-check a package
that already exists on disk.

> **Per-stage, not global.** The single most important invariant: each stage has its
> own list of what it may and may not receive. The methodology is *required* in
> replication and *forbidden* in robustness. The origin/results key is withheld
> everywhere. Rules live in `rrg.yaml > blinding` and `files.withheld`.

## Inputs (all resolved from config)

- The **staged package** for one `{stage, model}` run (a temp dir during `rrg package`,
  or a published package dir for `rrg lint`).
- **`STAGE`** — selects the `per_stage_methodology` rule set.
- **`rrg.yaml`** — `blinding.always_withhold`, `files.withheld`,
  `per_stage_methodology.<stage>.{require,forbid}`, `blinding.result_token_scan`.
- The **results key** (`origin.results_key`) — read only to derive result tokens; never
  packaged.

## Checks (`lint_package`)

A package **passes** when there are no hard fails. Flags are surfaced but do not block.

1. **withheld_files — HARD FAIL.** Any package path matching `blinding.always_withhold`
   or `files.withheld` (origin/results key, `SCORECARD_*`, operator-private files).
2. **stage_methodology_require — HARD FAIL.** A methodology file the stage *requires* is
   missing (e.g. the original protocol absent from a replication package).
3. **stage_methodology_forbid — HARD FAIL.** A stage-forbidden methodology file is
   present (e.g. any protocol leaking into a robustness package — the rule that keeps
   "design your own" honest).
4. **routing — HARD FAIL.** The package's files differ from the **resolved send list**
   for the stage (unexpected extras or missing inputs), ignoring `_provenance.json`.
   This replaces the old "subset integrity" check: instead of hash-locking one folder,
   the engine asserts the package is *exactly* what routing said to send.
5. **result_token_scan — FLAG or HARD FAIL** (per `result_token_scan.action`). Decimal
   values from the results key that appear verbatim in package text, minus
   `ignore_tokens` and `exclude_globs` (data files, sample sizes). Tune to exclude
   legitimate constants; treat as assistive, not authoritative.

Exit code: `0` = pass, `2` = a checked condition failed (blocked). `rrg package
--force` can publish despite a hard fail, but the override is recorded in provenance as
`forced_override`.

## Output

- **PASS** — `rrg package` proceeds to publish; the lint result + flags are written into
  `_provenance.json` and appended to the configured packages root's
  `provenance_log.jsonl`.
- **HARD FAIL** — publication blocked; the offending files/rules are listed. Fix and
  re-run (or `--force` with logged justification).
- **FLAGS** — listed for human confirmation; each is a false positive or gets removed.

## Lint guards contents; isolation guards reach

The lint controls what is **inside** a package — not what a validator can **reach** on
disk. Because the operator directory holds the secrets (`origin/`, `private/`,
scorecards, other runs) and the routed-only methodology, a validator running *inside*
the project could simply traverse to them (`ls ../../../origin/`). So the safety model
has two layers:

- **Lint** (this skill) certifies the package's *contents* are clean.
- **Isolation** (ADRs 0001 and 0003): on publish, `rrg package` writes a self-contained,
  read-only delivery zip. Supported macOS dispatches deny project reads/writes and
  confine writes to explicit roots; other hosts rely on escape detection until they
  gain an enforcing backend. Returned output is fully validated in staging before
  `rrg import` atomically installs it (ADR 0004). RRG removes access rather than asking
  the model not to snoop.

## Important limits (necessary, not sufficient)

- The token scan catches *literal* leaks (a number, a method name). It will **not** catch
  a *paraphrased* leak. Whenever a model-facing document is edited, a human should still
  eyeball it for semantic leakage.
- False positives on coincidental numbers are expected — that's why it flags rather than
  blocks (unless `action: fail`).
- This gate protects **blinding only**. Analytic correctness is grading (`rrg-scorecard`);
  input completeness is `rrg preflight`.

## Where it sits

Called automatically by `rrg package` after staging and before publish, for every
stage and model. No package is published without a PASS (or a recorded `--force`
override). Run `rrg lint` standalone whenever you want to re-verify a package already on
disk.
