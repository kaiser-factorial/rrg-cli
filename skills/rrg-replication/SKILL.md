---
name: rrg-replication
description: >
  Prepare a replication-stage run: build the blinded package and render the
  fixed-method prompt for one validator model, so it executes the ORIGINAL
  methodology exactly. Use when running or setting up the replication stage (the
  first rung of the degrees-of-freedom ladder, opening at the model level).
---

# rrg-replication — replication-stage run preparation

Replication tests whether the **original** analysis reproduces on a different model +
software stack. The validator is **given** the original methodology and must **execute
it exactly** (it does not design methods). It is blind only to the original **results**.
This stage "opens at the model level": does an independent model, following the same
method, get the same answer?

This skill runs in the operator's environment to prepare one replication run. It does
**not** execute the analysis — the validator runs the package (in isolation) in its own
agent app, and its outputs come back via `rrg import`.

## Inputs

- `MODEL` — the validator model, from `rrg.yaml > roster.replication`.
- Everything else is resolved from config: the send list, the prompt, the output-folder
  and report-name templates all come from `rrg.yaml > stages.replication`.

## Stage invariants (enforced by config + lint)

- **Methodology: REVEALED.** `stages.replication.methodology: revealed`, and the original
  protocol is routed in via `files.stage_specific` (`send_in: [replication]`) and
  `per_stage_methodology.replication.require`. The lint hard-fails if it's missing.
- **Results: BLIND.** The origin/results key, any `SCORECARD_*`, and operator-private
  files are in `blinding.always_withhold` / `files.withheld` — never packaged.
- **Payload identical across models.** Do not tailor the prompt to the model; that would
  confound the comparison. The prompt is rendered from one template per stage.
- **Gate:** replication is stage 1, so no upstream gate; downstream stages wait on it.

## Procedure

1. **Confirm the model** is in `roster.replication` with its type/license recorded. If
   two models run this stage, confirm at least one is open-weights. (`constraints.exclude_vendors`
   already blocks the origin's own vendor from validating it.)
2. **Preflight the stage:** `rrg preflight --stage replication`. Must be ready (exit 0).
3. **Build the package:** `rrg package --stage replication --model MODEL`. This resolves
   the send list, stages it in a temp dir, runs the blinding lint (`rrg-blinding-lint`),
   and publishes only on PASS — writing the published package, a delivery **zip**, and a
   `_provenance.json` (files + per-file SHA-256, prompt hash, lint result, determinism,
   timestamp). Use `--dry-run` to lint without publishing. Confirm the lint shows the
   methodology present and no withheld files.
4. **Render the prompt:** `rrg prompt --stage replication --model MODEL`. Operator
   reminders render visually separate from the paste-ready turns and are **never**
   model-facing. Keep wording identical across models.
5. **Dispatch in isolation.** Deliver the package **zip** to the validator and have it
   run **outside the project** (ideally a container), so the operator's secrets are
   unreachable. Do not run a validator inside the project tree.
6. **Import the return:** `rrg import <returned-folder-or-zip> --stage replication
   --model MODEL` validates the complete untrusted return in staging, gates the actual
   deliverable root, and atomically installs it into the provenance-selected run. It
   rejects traversal, duplicate/case-colliding paths, symlinks, and non-empty targets.

## Deliverable shape (what the validator returns)

A per-question pipeline (`Q…_analysis` → raw results → figure), a per-question raw
summary the scorecard reads (`raw/Q<n>_summary.json`), the DYFA narrative, the report
named per `stages.replication.report_name`, and a `SUMMARY.md`. Each question reports N +
subgroup Ns, descriptive inputs, the test statistic + effect size + 95% CI, and a
one-sentence conclusion. Every `METRIC_SPEC.json` metric and exact `_units` entry must
appear in the summary; DYFA F/A repeats the same values as machine markers. (Exact
filenames follow the project's deliverable spec in `study.yaml`.)

## Grading

Grade the imported run against the results key via `rrg-scorecard` → `rrg scorecard
--run <run> --stage replication --model MODEL`. Methodology is fixed, so expect
**REPRODUCED**; any miss localizes a model/stack difference (that's the finding). Record
the exact model name + license.

## Notes

- The *orchestration* runs in the operator's environment; the *payload* is the zip +
  rendered prompt the validator receives — keep that identical across all replication
  models.
- Do not let the original methodology leak into a robustness package; that stage forbids
  all protocols, and the lint will hard-fail if one appears.
- A model that can't follow the clear, identical instructions is itself a finding —
  never hand-tune the prompt per model to "help" it.
