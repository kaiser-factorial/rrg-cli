# Held-back MovieRatings origin summary

Source: `ORIGIN_REPORT.pdf`. Values below are transcribed from the report, not
recomputed. Q7 contains an internal p-value inconsistency that is intentionally
preserved for validation.

## Q1 - Popularity and ratings

Method: median split at 197.5 observed ratings per movie; pooled one-tailed
Mann-Whitney U test. High-popularity median = 3.000; low-popularity median = 2.500;
U = 1,242,808,144.50; reported p = 0.0000. Conclusion: popular movies were rated higher.

## Q2 - Release year and ratings

Method: median release-year split at 1999; pooled two-sample KS test. D = 0.0112;
p = 0.0023. Conclusion: newer and older movie ratings differed.

## Q3 - Shrek ratings by gender

Method: two-sample KS test. D = 0.0980; p = 0.0561. Conclusion: no significant
male-female difference for `Shrek (2001)`.

## Q4 - Gender effects across movies

Method: separate KS tests for all 400 movies at raw alpha 0.005. Finding: 25/400
(6.25%) differed significantly by gender.

## Q5 - Lion King and only-child status

Method: one-tailed Mann-Whitney U test. Only-child median = 3.5; sibling median = 4.0;
U = 5,292.0; p = 0.978. Conclusion: only children did not rate the movie higher.

## Q6 - Only-child effects across movies

Method: separate KS tests at raw alpha 0.005. Finding: 3/400 (0.75%):
`Happy Gilmore (1996)`, `Toy Story (1995)`, and `Billy Madison (1995)`. Each had a
higher median among viewers with siblings.

## Q7 - Wolf of Wall Street and social viewing

Method: one-tailed Mann-Whitney U test for higher ratings among social viewers.
Alone-preference median = 3.5; social-viewer median = 3.0; U = 49,303.50. The report
first states p = 0.9437 and later states p = 0.1128. Conclusion: no significant
evidence that social viewers rated the movie higher.

## Q8 - Social-viewing effects across movies

Method: separate one-tailed Mann-Whitney U tests at raw alpha 0.005. Finding: 6/400
(1.5%): `Shrek 2 (2004)`, `Captain America: Civil War (2016)`, `The Avengers (2012)`,
`Spider-Man (2002)`, `The Transporter (2002)`, and `North (1994)`.

## Q9 - Home Alone versus Finding Nemo

Method: two-sample KS test. Both medians = 3.5; Home Alone mean = 3.130; Finding Nemo
mean = 3.388; D = 0.1527; reported p = 0.0000. Conclusion: distributions differed,
with Finding Nemo generally rated higher.

## Q10 - Franchise consistency

Method: one Kruskal-Wallis test per franchise at raw alpha 0.005. Finding: 7/8 were
inconsistent. `Harry Potter` was the exception (H = 3.331, p = 0.343). The seven
flagged franchises were Star Wars, The Matrix, Indiana Jones, Jurassic Park,
Pirates of the Caribbean, Toy Story, and Batman.

## Q11 - Sensation-seeking effects

Method: sum the 21 sensation-seeking items, median split excluding participants at
the median, then separate KS tests at raw alpha 0.005. Finding: 7/400 movies:
`The Wolf of Wall Street (2013)`, `The Cabin in the Woods (2012)`, `The Ring (2002)`,
`Scary Movie (2000)`, `Scream (1996)`, `Along Came a Spider (2002)`, and `Saw (2004)`.
Each had a higher median among high sensation seekers.
