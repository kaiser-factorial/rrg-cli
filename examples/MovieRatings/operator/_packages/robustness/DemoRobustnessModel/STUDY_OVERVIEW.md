# MovieRatings study overview

This demonstration validates a human-authored analysis of movie-rating survey data.
The origin report is withheld from validators.

The dataset contains 1,097 participant rows and 477 columns:

- Columns 1-400: ratings of 400 movies on a 0-4 scale, with missing responses.
- Columns 401-421: 21 sensation-seeking self-assessments on a 1-5 scale.
- Columns 422-464: 43 personality-question responses on a 1-5 scale.
- Columns 465-474: 10 self-reported movie-experience items on a 1-5 scale.
- Column 475: gender identity (`1` female, `2` male, `3` self-described).
- Column 476: only-child status (`1` yes, `0` no, `-1` no response).
- Column 477: movies are best enjoyed alone (`1` yes, `0` no, `-1` no response).

Rows do not contain a participant identifier. Movie titles appear directly as the
first 400 column names and generally include release years in parentheses.

The goal is to determine whether the eleven findings in the withheld origin report
can be reproduced using the same methods and whether they survive independently
chosen defensible methods.
