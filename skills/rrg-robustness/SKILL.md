---
name: rrg-robustness
description: >
  Prepare a robustness-stage run: build the package and render the staged method-free
  prompt for one validator model, so it designs its OWN methodology, blind to the
  original methods and results. Use when running the robustness stage (second rung of
  the ladder, opening at the method level).
---

# rrg-robustness — robustness-stage run preparation

Robustness tests whether a finding survives a *different defensible method*. The
validator **designs its own approach** per question (it is not handed a protocol), blind
to both the original **methods and results**. This stage "opens at the method level":
does the conclusion survive a different reasonable method? Convergence — a different
method reaching the same conclusion — is the strong signal here.

This skill runs in the operator's environment to prepare one robustness run; the
validator executes it in isolation and the outputs return via `rrg import`.

## Inputs

- `MODEL` — the validator model, from `rrg.yaml > roster.robustness`.
- Send list, prompt, output-folder and report-name templates all resolve from
  `rrg.yaml > stages.robustness`.

## Stage invariants (enforced by config + lint)

- **Methodology: HIDDEN.** `stages.robustness.methodology: hidden`. No methodology
  protocol may be in the package — `per_stage_methodology.robustness.forbid` lists the
  protocol patterns, and the lint hard-fails if any appear. The model must design its own.
- **Results: BLIND.** Origin/results key, `SCORECARD_*`, and operator-private files are
  withheld everywhere.
- **Payload identical across models.** Do not tailor the prompt to the model.
- **Method choice is free and unsteered.** Never tell the model to use a different
  method, avoid the original's approach, or "think of something else." Independent
  convergence on the same method is a valid, informative outcome (method consensus +
  reproducibility), **not** a failure to test robustness — and forcing divergence makes
  any resulting change uninterpretable (you can't tell a fragile finding from a model
  using a method it judged inferior).
- **Gate:** run only after the replication stage is graded.

## Procedure

1. **Confirm the model** is in `roster.robustness` (type/license recorded). If two models
   run this stage, confirm ≥1 is open-weights.
2. **Preflight the stage:** `rrg preflight --stage robustness`. Must be ready (exit 0).
3. **Build the package:** `rrg package --stage robustness --model MODEL`. Routing sends
   the `all` token only — **no methodology**. The blinding lint must confirm no protocol
   of any kind is present (plus the standard withheld-file checks) before it publishes
   the package, the delivery zip, and provenance. `--dry-run` lints without publishing.
4. **Render the staged prompt:** `rrg prompt --stage robustness --model MODEL`. The
   method-free prompt walks the model through orient → propose methods → discuss → lock
   approach → execute → QA. Use `--mode discuss|nodiscuss` and `--turn N` to render a
   single turn or the interactive vs. operator-reviewed-lock variant.
   **Operator note (never sent to the model):** in any interactive discussion, raise
   alternatives from your own judgment, *not* from the original methodology — importing
   the originals re-anchors the model and breaks the blind.
5. **Dispatch in isolation.** Deliver the zip; the validator runs it **outside the
   project**. Record the chosen method per question from its returned approach — this
   feeds the cross-model method-choice distribution compiled in `rrg-scorecard`.
6. **Import the return:** `rrg import <returned> --stage robustness --model MODEL`.

## Deliverable shape (what the validator returns)

The method artifacts (proposed methods, discussion, locked approach), then the
per-question pipeline, the per-question raw summary the scorecard reads
(`raw/Q<n>_summary.json`), the DYFA narrative, the report named per
`stages.robustness.report_name`, and a `SUMMARY.md`. Each question reports N + subgroup
Ns, descriptive inputs, test statistic + effect size + 95% CI, and a one-sentence
conclusion.

## Grading

Grade against the results key via `rrg-scorecard` → `rrg scorecard --run <run> --stage
robustness --model MODEL`. Expect a **mix of REPRODUCED (same method chosen) and
CONVERGED (different method, same conclusion)**; a DIVERGED result triggers a localizing
second pass (re-run that one question with the original method pinned — matches →
method difference; still differs → genuine discrepancy). Record exact model name +
license.

## Notes

- The defining difference from `rrg-replication`: **no protocol is sent.** If a protocol
  ever appears in a robustness package, the lint hard-fails.
- Two method-free models give an inter-model agreement signal within the stage. The
  cross-model **method-choice distribution** (compiled in `rrg-scorecard`) shows which
  questions are method-settled (independent convergence) vs. method-ambiguous (spread) —
  a first-class finding. For fuller method coverage, use a *pre-specified multiverse arm*
  (operator-enumerated methods), never model coercion.
- A model that can't follow the clear, identical instructions is a finding — never
  hand-tune the prompt per model.
