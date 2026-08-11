---
name: rrg-eval
description: >
  Evaluate a returned validator run against the held-back origin: compare per-question
  statistics, classify verdicts (REPRODUCED / DIVERGED), investigate discrepancies by
  re-running the original analysis and comparing both DYFA/report sections, and write
  the results to an evals/ subdirectory in the run folder. Use after `rrg import` brings
  a run back and `rrg eval` confirms the deliverable contract passes.
---

# rrg-eval — post-import validation evaluation

After `rrg import` brings a validator's output back and `rrg eval` confirms the
deliverable contract passes, this skill performs the **scientific evaluation**:
comparing the validator's results against the held-back origin to determine
which findings were reproduced, which diverged, and why.

This is distinct from `rrg eval --run R` (which checks pipeline mechanics —
contract compliance, breach status, grading). This skill evaluates the
**scientific content**: did the validator get the same answers?

## When to run

- After `rrg import` + `rrg eval` (pipeline mechanics pass)
- Before human grading (it pre-classifies verdicts for the human to confirm)
- For any stage (replication, robustness, generalization)

## Inputs

- `RUN` — the imported run folder under `operator/`
- The **origin summary** (`operator/origin/SUMMARY.md` or the results key)
- The **validator's summary JSONs** (`raw/Q<n>_summary.json`)
- The **validator's report** (DYFA sections, `*_Report.md`)
- The **analysis protocol** (for replication — to verify protocol adherence)
- The **source data** (for independent stat verification)

## Procedure

### Step 1: Create evals/ subdirectory

```
<run_folder>/evals/
  COMPARISON.md    — per-question comparison table with verdicts
  DIVERGENCES.md   — detailed analysis of each non-REPRODUCED question
```

### Step 2: Build the comparison table (COMPARISON.md)

For each question, extract from both origin and validator:

| Field | Source |
|-------|--------|
| Test statistic (U, D, H, etc.) | origin SUMMARY.md / validator raw/Q<n>_summary.json |
| p-value | same |
| N / group sizes | same |
| Count (for multi-test questions) | same |
| Conclusion (sig/null at α) | same |

Classify each question:

- **REPRODUCED** — same statistic, same p-value (within rounding), same conclusion
- **REPRODUCED (same conclusion)** — p-value differs but both on same side of α
- **REPRODUCED (stat convention)** — statistic differs but p-value matches (e.g. U computed for different group)
- **DIVERGED** — conclusions differ (one significant, one null) or counts differ
- **DIVERGED (protocol deviation)** — divergence caused by validator not following the protocol exactly

### Step 3: Investigate divergences (DIVERGENCES.md)

For each non-REPRODUCED question:

1. **Read both DYFA/report sections** — origin's Q<n> section and validator's Q<n> DYFA
2. **Identify the discrepancy** — is it a statistic difference, a p-value crossing α, a count difference?
3. **Check protocol adherence** — did the validator follow the protocol exactly?
   - Common deviations: split direction (≤ vs <), group definitions, keyword matching, NaN handling
4. **Re-run the analysis independently** — compute the stat yourself from the source data
   - Use the protocol's exact method
   - Compare your result to both origin and validator
   - This confirms which side is correct
5. **Check for origin errors** — the origin is human-authored and may have:
   - Transcription errors (e.g. dropped digits in U statistics)
   - Rounding artifacts (p=0.0000 means p < 0.0001, not p=0)
   - Internal inconsistencies (multiple p-values reported for the same test)
6. **Write the analysis** — include:
   - Origin's values and conclusion
   - Validator's values and conclusion
   - Root cause (protocol deviation / origin error / genuine method difference)
   - Independent verification (your computation)
   - Verdict with justification

### Step 4: Summarize

At the top of COMPARISON.md:
- Total reproduced / diverged counts
- Pipeline metrics (from `rrg eval`)
- Notes on origin errors found

## Verdict taxonomy

| Verdict | Meaning | When to use |
|---------|---------|-------------|
| REPRODUCED | Same stat, same p, same conclusion | Exact match |
| REPRODUCED (same conclusion) | p differs but same side of α | Rounding or minor implementation difference |
| REPRODUCED (stat convention) | Stat differs but p matches | U computed for different group, different library |
| DIVERGED | Conclusions differ | One sig, one null; or different counts |
| DIVERGED (protocol deviation) | Validator didn't follow protocol | Wrong split direction, wrong keywords, etc. |
| DIVERGED (origin error) | Origin has a transcription error | Dropped digits, wrong column, etc. |
| DIVERGED (genuine) | Same protocol, different result | Real implementation/data difference to investigate |

## Independent verification

The dispatch agent is **encouraged to run the statistics themselves** to confirm
which side is correct. This is not re-doing the analysis from scratch — it's
running the **exact protocol-specified test** on the source data and comparing
to both sides:

```python
from scipy import stats
import pandas as pd

df = pd.read_csv('data/movie_ratings.csv')
# ... follow the protocol exactly ...
stat, p = stats.mannwhitneyu(group1, group2, alternative='greater')
print(f"U={stat}, p={p}")
```

If your computation matches the origin → the validator diverged.
If your computation matches the validator → the origin may have an error.
If your computation matches neither → investigate further.

## Per-stage reading

- **Replication** → mostly REPRODUCED (misses = protocol deviations or implementation differences)
- **Robustness** → mix of REPRODUCED (same method chosen) and CONVERGED (different method, same conclusion)
- **Generalization** → GENERALIZES / SAMPLE-SPECIFIC

For robustness, the comparison is against the origin's **conclusion**, not exact
numbers (a different method may legitimately produce different statistics).

## Output files

```
<run_folder>/evals/
  COMPARISON.md    — table with all questions, verdicts, pipeline metrics
  DIVERGENCES.md   — per-divergence analysis with origin vs validator sections,
                     root cause, independent verification, and final verdict
```

## Notes

- This skill does NOT assign final verdicts — that remains human-only (`rrg scorecard`).
- It pre-classifies and investigates so the human grader has the analysis ready.
- The independent stat verification is the key value-add: it resolves "who's right?"
  by computing the answer from scratch using the protocol.
- Origin errors found during eval should be noted but do not change the validator's
  verdict (the validator reproduced the correct result; the origin had the error).
