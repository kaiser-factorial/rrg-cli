---
name: rrg-generalization
description: >
  DRAFT / PENDING — not ready for use. Sketch of a generalization-stage run-prep skill
  (third rung of the ladder, opening at the data level). The generalization stage is
  disabled by default in the engine until a data-variation plan exists; this file
  collects ideas, not an operational procedure.
---

# rrg-generalization — generalization-stage prep (PENDING SKETCH)

> **Status: pending.** Do not run this as-is. The generalization stage is `enabled:
> false` in the starter manifest and blocked with: *"Define an independent sample or
> holdout policy before enabling."* The engine deliberately does not choose a scientific
> policy for you. This file is a placeholder capturing the shape the skill should take
> once that policy is decided.

## What the stage is for

Generalization tests whether a conclusion holds **beyond this dataset** — it "opens at
the data level." The validator works a *different sample or holdout*, not the original
data. It is the rung above robustness (which varied the method on the same data).

## Open decisions that must be settled first (these block the skill)

1. **Data-variation plan.** What is the "different data"? Candidate designs:
   - a held-out split of the original sample (pre-registered, never touched upstream);
   - an independent replication dataset (different collection, same instrument);
   - a temporally or demographically distinct subsample;
   - a synthetic/perturbed dataset for stress-testing.
   Each implies a different `study.yaml` dataset config and a different blinding posture.
2. **Methodology posture.** `stages.generalization.methodology` is `decide-in-cartridge`
   — does the validator get the original method (closer to replication-on-new-data) or
   design its own (closer to robustness-on-new-data)? This sets the
   `per_stage_methodology.generalization` require/forbid rules.
3. **Verdict semantics.** `rrg-scorecard` already carries **GENERALIZES /
   SAMPLE-SPECIFIC**; confirm the tolerance bands and what counts as "holds" when the
   sample itself differs (effect sizes may legitimately shift even when the conclusion
   survives).
4. **Origin comparison.** What is the key graded against when the data changed? Possibly
   the original conclusion rather than the original numbers.

## Likely shape once unblocked (mirrors the other stage skills)

- Inputs: `MODEL` from `roster.generalization`; everything else from
  `stages.generalization` in `rrg.yaml`.
- Procedure: confirm roster → `rrg preflight --stage generalization` → `rrg package
  --stage generalization --model MODEL` (routing + blinding lint + zip + provenance) →
  `rrg prompt --stage generalization --model MODEL` → dispatch in isolation → `rrg
  import` → grade with `rrg-scorecard` (expect GENERALIZES / SAMPLE-SPECIFIC).
- The generalization-specific blinding rule (`per_stage_methodology.generalization`,
  currently `forbid: [ORIGINAL_METHODOLOGY.md]`) and the new dataset's withhold patterns
  must be set before the first package.

## Next step

Decide the data-variation plan and methodology posture (decisions 1–2 above), set them
in `study.yaml` / `rrg.yaml`, flip `stages.generalization.enabled: true`, then promote
this sketch to a full skill modeled on `rrg-replication` / `rrg-robustness`.
