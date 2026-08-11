# Methodology reconstruction — {STUDY_TITLE}

You are acting as the origin author for this study. You are given the original
report `{ORIGIN_REPORT}` and the {N_QUESTIONS} validation questions below. Produce a
**result-free reconstruction of the analysis methods** that a replication team can
follow to reproduce the analysis without ever seeing the findings.

## Validation questions

{QUESTIONS_LIST}

## Rules

- Write exactly one numbered step per question, in the same order as the questions
  above (1 through {N_QUESTIONS}).
- Describe methods only: variable construction, sample/grouping and split rules, the
  exact test and its direction or alternative, and any thresholds. Honor every held
  constant defined in `{HELD_CONSTANTS_FILE}` ({HELD_CONSTANTS_SUMMARY}).
- Do NOT include any results: no test statistics, p-values, effect sizes, medians,
  means, counts or proportions of significant items, named significant items, or
  stated conclusions. If the report gives a number inline, keep the method and drop
  the number.
- Output GitHub-flavored markdown only, suitable to save verbatim as
  `{ORIGINAL_PROTOCOL}`. Begin with a one-line title and a single sentence stating
  this is a result-free reconstruction revealed only in replication.

Return only the protocol document, nothing else.
