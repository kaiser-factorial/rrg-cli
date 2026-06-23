# Origin intake — {STUDY_TITLE}

You are acting as the origin author for this study. You are given the original report
`{ORIGIN_REPORT}` and the {N_QUESTIONS} validation questions below. Produce a
**faithful, structured transcription** of what the report already says for each
question, in the canonical format the grading pipeline consumes. You are normalizing
an existing report — you are NOT re-running, re-computing, or correcting anything.

## Validation questions

{QUESTIONS_LIST}

## What to produce

Two things, in this order, in a single response:

### 1. `{SUMMARY_FILE}` — one fixed block per question

Output GitHub-flavored markdown. Write exactly one section per question, in order,
each headed `## Q<n> - <topic>`, where `<n>` is the question number exactly as shown
in the list above (this is the report's own numbering). Under each heading, give a
fixed field list whose keys mirror the validator deliverable schema, so the origin
and validator sides are directly comparable question by question:

- **question** — the question text, verbatim from the list above.
- **n** — the analysis N the report used for this question (the sample/observation
  count actually analyzed). If the report gives several, use the one for the headline
  test and note the others in `conclusion`.
- **groups** — how cases were split or grouped for this question (definitions only).
- **test** — the exact test and its alternative/direction (e.g. "one-tailed
  Mann-Whitney U, higher in group A").
- **statistic** — the reported test statistic with its label (e.g. "U = 49,303.50").
- **p_value** — the reported p, exactly as printed. Never round a small p to 0; copy
  it as written. If the report states two conflicting p-values for one question,
  record BOTH exactly and do not reconcile them — that inconsistency is data.
- **effect_size** — the reported effect size, or `null` if the report gives none.
- **multiplicity** — how multiple comparisons were treated (e.g. "raw alpha 0.005,
  no correction"), or `null`.
- **conclusion** — the report's own one-sentence conclusion for this question.

Copy numbers exactly as the report renders them (keep the report's own precision,
thousands separators, and units). Transcribe; do not recompute. If a field is genuinely
absent from the report, write `not reported` — do not infer or fill it in.

### 2. Figure manifest

After the summary, output a fenced ```` ```yaml ```` block named `figure_map` mapping
each question to the figure(s) in `{ORIGIN_REPORT}` that answer it, identified by the
report's OWN figure label (number or appendix letter), so the operator can rename them
to the canonical `Q<n>_fig.png`:

```yaml
figure_map:
  - {question: 1, report_label: "Figure 1", canonical: "Q1_fig.png"}
  - {question: 2, report_label: "Appendix B", canonical: "Q2_fig.png"}
  # one row per question that has a figure; omit questions with no figure
```

Match figures to questions by what the figure actually shows (its caption/content),
not by position. If you are unsure which figure answers a question, omit that row
rather than guess.

## Rules

- This is a transcription task. Do not analyze the data, run code, change methods, or
  "fix" anything the report got wrong. Reproduce the report faithfully, quirks and all.
- Honor the held constants in `{HELD_CONSTANTS_FILE}` ({HELD_CONSTANTS_SUMMARY}) when
  describing groups and tests — these are fixed across the study.
- Output only the two artifacts above (the `{SUMMARY_FILE}` markdown, then the
  `figure_map` block). No preamble, no commentary.
