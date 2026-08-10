---
name: rrg-scorecard
description: >
  Grade a returned validator run against the held-back key: lay each result beside the
  original, pre-classify a PROVISIONAL verdict per question, and leave every final
  verdict to the human grader. Use after `rrg import` brings a run back, to produce a
  versioned SCORECARD. The engine never assigns a final verdict.
---

# rrg-scorecard — grade a validator run against the key

Turns an imported validator run into a per-question scorecard that sets each result
beside the held-back origin material and assigns a verdict. **The engine scaffolds and
*suggests*; a human assigns every final verdict** — the validator never grades itself,
and neither does the scorecard builder on its own.

The scorecard is **operator-side and withheld** — it contains results and verdicts, so
it must never enter a package. `blinding.always_withhold` blocks `SCORECARD_*`, and the
lint hard-fails if one is ever staged.

## Inputs

- `RUN` — the imported run folder under `operator/` (from `rrg import`).
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
version) into the operator directory.

## Verdict vocabulary

- **REPRODUCED** — same method, numbers match within tolerance.
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
2. **Pulls the validator's headline material** — the numbers in `raw/Q<n>_summary.json`
   and the per-question line in `SUMMARY.md`.
3. **Pulls the key's matching material** by the question's *original* number (the
   origin's `## Q<n>` section — extracted the same way the *Origin* separation matrix
   checks, so a question marked scoreable there is exactly one this can grade).
4. **Lays them side by side** with a **PENDING** verdict and the verdict legend. A
   provisional hint is emitted *only* where a labelled scalar clearly matches within the
   rubric's tolerance (direction/sign matches; magnitude within bands — r ≈ ±.05; d/η² ≈
   ±.10; balanced accuracy ≈ ±3 pts; coefficients same sign, overlapping CIs; relative
   ordering preserved). **Every other row stays PENDING.**
5. A blank scaffold is explicitly **provisional** and is *rejected if it ever contains a
   final verdict* — the engine never grades.

## Finalizing (human-only)

Final verdicts are assigned in the GUI **Review & Grade** tab (which replaced the older
separate Compare/Scorecards tabs). Per question it shows: the validator-led **statistics
comparison** (each stat in `raw/Q<n>_summary.json`, checked for the same value in the
origin material and marked found / not-found, with the stage's expectation noted —
replication should match exactly, robustness may legitimately differ), the
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

- **Suggested ≠ final.** The builder may pre-classify to save effort, but a human
  confirms every verdict; nothing is graded autonomously.
- This skill grades **correctness/agreement only** — blinding is `rrg-blinding-lint`'s
  job (at packaging), and input readiness is `rrg preflight`.
