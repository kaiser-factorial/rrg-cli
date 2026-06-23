# Robustness prompt

## Turn 1 — Orient

Read {STUDY_OVERVIEW}, {QUESTIONS_FILE}, and {HELD_CONSTANTS_FILE}. {DATA_ORIENTATION}

The original method and results are withheld. This turn is for orientation only: confirm
the inputs load and that you understand the questions, then stop and wait. Do not run any
analysis or propose methods yet — that happens only after you receive the next
instruction. Put all work in {OUTPUT_FOLDER}.

## Turn 2 — Propose methodology

Design a defensible method for each of the {N_QUESTIONS} questions and reconsider each
choice once. Honor every held constant in {HELD_CONSTANTS_FILE}; the analysis method for
each question is otherwise your own choice. Write your plan to `APPROACH.md`. Do not run
analyses yet.

## Turn 3 — Discuss {mode:discuss}

Walk through `APPROACH.md` question by question. For each, state the method, why it is
defensible, and the main alternative you considered. Invite the operator's input; do not
lock anything yet.

## Turn 4 — Discuss interactively {mode:discuss}

(Operator-led; no fixed prompt text. The operator pushes on specific choices and you
revise `APPROACH.md` in response.)

## Turn 5 — Lock the methodology {mode:discuss}

Finalize `APPROACH.md`, incorporating the discussion. Restate the locked method for each
question. Do not run analyses until the operator confirms the lock.

## Turn 5 — Lock the methodology (operator-reviewed) {mode:nodiscuss}

Finalize `APPROACH.md` as proposed — no debate. Restate the locked method for each
question and wait for the operator's go-ahead before running anything.

## Turn 6 — Execute

After the lock is confirmed, execute `APPROACH.md`, then compile {REPORT_NAME}.
{REPORTING_SPEC}

## Turn 7 — Verify

Run a quality-assurance pass before finishing — do not change any results.

- Re-check any question where a figure or a number looks off, surprising, or internally
  inconsistent — e.g., an N that doesn't match across steps, a confidence interval that
  excludes its own point estimate, or an effect direction that contradicts the
  descriptives. Trace it back through Q<n>_analysis.py to the data.
- Confirm each question was executed as agreed in `APPROACH.md`; flag anything you had to
  change.
- Verify the held-constant definitions produced the expected group structure: report the
  Ns for {HELD_CONSTANT_GROUPS}.
- Confirm the deliverables are complete and in the required format: for every question a
  `Q<n>_analysis.py`, `raw/Q<n>_raw.csv`, `Q<n>_fig.py`, `Q<n>_fig.png`, and a
  `raw/Q<n>_summary.json` with the required keys, plus a DYFA section in {REPORT_NAME}
  embedding the figure. Fix anything missing or malformed.
- Record anything you corrected, anything still uncertain, and any deviation in `SUMMARY.md`.

## Operator reminders

Never reveal the original protocol, {RESULTS_KEY}, scorecards, or other runs.
