# MovieRatings validation instructions

These definitions are fixed across validation stages.

## Data and missingness

- Treat blank cells and the literal text `N/A` as missing.
- Do not impute missing movie ratings or grouping variables.
- The first 400 columns are the complete movie set; later columns are participant attributes.
- Movie ratings range from 0 to 4. Other survey items generally range from 1 to 5.
- There is no respondent identifier and no merge step.
- Report the usable N for every comparison and every movie-level test.

## Fixed groups

- Gender comparisons use `1` (female) versus `2` (male); exclude `3` and missing values.
- Sibling comparisons use column 476: `1` only child versus `0` has siblings; exclude `-1` and missing values.
- Watching-preference comparisons use column 477: `0` social preference versus `1` prefers alone; exclude `-1` and missing values.
- Sensation seeking is the row-wise sum of columns 401-421 when required by the fixed replication protocol.

## Decision policy

- Use a per-test significance threshold of alpha = 0.005.
- Preserve the eleven-question order in `QUESTIONS.md`.
- Use the movie titles and eight franchise keywords exactly as written in the questions.
- Report exact p-values where computationally available; do not report a rounded zero.
- Record any multiplicity correction or lack of correction explicitly.
- Do not search for the original report or prior answers.
