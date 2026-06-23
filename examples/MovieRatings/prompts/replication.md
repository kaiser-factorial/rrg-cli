# Replication prompt

## Turn 1 — Orient

Read {STUDY_OVERVIEW}, {QUESTIONS_FILE}, {HELD_CONSTANTS_FILE}, and {ORIGINAL_PROTOCOL}.
{DATA_ORIENTATION}

You are replicating a fixed method. Do not search for prior results. This turn is for
orientation only: confirm the inputs load and that you understand the task, then stop and
wait. Do not run any analysis, write scripts, or produce results yet — that happens only
after you receive the separate execute instruction. Put all work in {OUTPUT_FOLDER}.

## Turn 2 — Execute

Execute {ORIGINAL_PROTOCOL} exactly for all {N_QUESTIONS} questions, then compile
{REPORT_NAME}. {REPORTING_SPEC}

## Turn 3 — Verify

Run a quality-assurance pass before finishing. Keep the methodology fixed — this confirms
the execution is correct, it does not change the approach.

- Re-check any question where a figure or a number looks off, surprising, or internally
  inconsistent — e.g., an N that doesn't match across steps, a confidence interval that
  excludes its own point estimate, or an effect direction that contradicts the
  descriptives. Trace it back through {OUTPUT_FOLDER}/Q<n>_analysis.py to the data.
- Confirm each question was executed exactly as written in {ORIGINAL_PROTOCOL}. Flag —
  don't fix-by-redesign — any place you had to deviate or where a step was infeasible.
- Verify the held-constant definitions produced the expected group structure: report the
  Ns for {HELD_CONSTANT_GROUPS}.
- Confirm the deliverables are complete and in the required format: for every question a
  `Q<n>_analysis.py`, `raw/Q<n>_raw.csv`, `Q<n>_fig.py`, `Q<n>_fig.png`, and a
  `raw/Q<n>_summary.json` with the required keys, plus a DYFA section in {REPORT_NAME}
  embedding the figure. Fix anything missing or malformed.
- Record anything you corrected, anything still uncertain, and any deviation in `SUMMARY.md`.

## Operator reminders

Never share {RESULTS_KEY}, scorecards, or operator-only files.
