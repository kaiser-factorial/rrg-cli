---
name: rrg-scorecard
description: >
  Grade a returned validator run against the held-back key: lay each result beside the
  original with deterministic deltas/statuses, leave a PENDING verdict per question, and leave every final
  verdict to the human grader. Use after `rrg import` brings a run back, to produce a
  versioned SCORECARD. The engine never assigns a final verdict.
---

# rrg-scorecard — grade a validator run against the key

Turns an imported validator run into a per-question scorecard that sets each result
beside the held-back origin material. **The engine exposes comparisons; a human assigns
every final verdict** — the validator never grades itself,
and neither does the scorecard builder on its own.

The scorecard is **operator-side and withheld** — it contains results and verdicts, so
it must never enter a package. `blinding.always_withhold` blocks `SCORECARD_*`, and the
lint hard-fails if one is ever staged.

## Inputs

- `RUN` — the imported run folder (new projects: `operator/runs/<stage>/...`).
- `STAGE` — `replication | robustness | generalization` (sets the verdict vocabulary).
- Resolved from config: the **results key** (`origin.results_key` / `study.yaml >
  original.results_key`), the **question map** (`questions_map.yaml`), and the rubric.
- `--key`, `--map`, `--out-dir`, `--license` override the defaults; `--prior` is
  auto-detected for refinement rounds.

## Command

```
rrg scorecard --run RUN --stage STAGE --model MODEL [--key DIR] [--map FILE]
              [--out-dir DIR] [--license T]
```

It writes `SCORECARD_<stage>_<label>_v<n>.md` (auto-incrementing, noting the prior
version) into the configured reviews directory.

## Verdict vocabulary

- **REPRODUCED** — same method and operator-reviewed results agree. Non-p-value
  comparisons are exact-only; a p-value inside the pipeline's tolerance is still
  visibly non-exact and requires judgment.
- **CONVERGED** — different defensible method, same conclusion (a pass; stronger
  robustness evidence).
- **DIVERGED** — conclusion or key number disagrees.
- **INCOMPLETE** — intended analysis not run (method gap / data limit).
- **GENERALIZES / SAMPLE-SPECIFIC** — generalization-stage outcomes.
- **N-A** — not answerable from the data.
- Tag **FRAGILE** where the original pre-flagged a result as tentative (a miss is noted,
  not failed).

## What the builder does (mechanically, and only mechanically)

1. **Maps each question** new # → original label via `questions_map.yaml`, so like is
   compared with like.
2. **Loads the validator summary** and, when present, the public metric spec plus
   operator-only canonical origin JSON.
3. **Joins canonical values** by original question, metric id, and declared JSON path,
   normalizes compatible units, and shows the exact delta and status. Text parsing is
   used only when canonical records are absent.
4. **Applies pipeline-owned policy:** all non-p metrics require exact equality; only
   p-values use absolute tolerance `0.005`, and an inside-band non-exact value is
   `WITHIN_TOLERANCE`, never exact. Validator output cannot set tolerance.
5. **Lays comparisons side by side** with a **PENDING** verdict and verdict legend.
6. A blank scaffold is explicitly **provisional** and is *rejected if it ever contains a
   final verdict* — the engine never grades.

## Finalizing (human-only)

Final verdicts are assigned in the GUI **Review & Grade** tab (which replaced the older
separate Compare/Scorecards tabs). Per question it shows: the validator-led **statistics
comparison** from the same engine the scorecard uses (status, units, delta, and fixed
policy), the
**origin-only figures** the validator didn't report, the **DYFA narratives** side by
side, the figures, and a **verdict** control. Grading state lives separately as per-run
JSON; a run is "graded" only when a human confirms a verdict for **every** question.
Finalizing exports the next versioned `SCORECARD_*.md` filled with those verdicts.

## Per-stage reading & the convergence taxonomy

- replication → mostly REPRODUCED (misses = stack differences);
- robustness → a mix of REPRODUCED/CONVERGED (the reproduction-vs-robustness signal);
- generalization → GENERALIZES / SAMPLE-SPECIFIC.

**Convergence is information — read robustness conditional on divergence.** The
per-finding taxonomy: *method-consensus + reproduced* (solid) · *method-divergent +
converged* (robust) · *method-divergent + diverged* (fragile/method-dependent) ·
*method-consensus + numbers diverged* (a reproduction problem to chase). Independent
same-method choice is never scored as a failure to test robustness; it's a consensus
signal. For a robustness stage run across several models, record the **method-choice
distribution** per question — how many models independently chose each approach — as a
first-class finding.

## Versioning & provenance

- Versions auto-increment; **keep prior versions** — the trajectory (e.g. v1→v2 flips
  after a refinement) is itself a result, and the builder seeds a "what changed from
  v{n-1}" view from the prior verdicts.
- Record the model's exact name + license (the open-models claim depends on it).

## Notes

- **Comparison ≠ verdict.** A human confirms every verdict; nothing is graded
  autonomously.
- This skill grades **correctness/agreement only** — blinding is `rrg-blinding-lint`'s
  job (at packaging), and input readiness is `rrg preflight`.
