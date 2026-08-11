# Original MovieRatings analysis protocol

This is a result-free reconstruction of the methods described in the origin report.
It is revealed only in replication and forbidden in robustness.

Use alpha = 0.005 throughout. Apply the missingness and group definitions in
`VALIDATION_INSTRUCTIONS.md`.

1. Count observed ratings per movie, split the 400 movies at the median count into
   low- and high-popularity groups, pool the ratings within each group, and run a
   one-tailed Mann-Whitney U test for higher ratings in the high-popularity group.
2. Extract release years from movie titles, split movies at the median year with
   the median year included in the newer group, pool ratings within groups, and run
   a two-sample Kolmogorov-Smirnov test.
3. Run a two-sample Kolmogorov-Smirnov test comparing male and female ratings of
   `Shrek (2001)`.
4. Run a separate two-sample Kolmogorov-Smirnov test for each of the 400 movies by
   gender and report the count and proportion with raw p < 0.005.
5. Run a one-tailed Mann-Whitney U test of whether only children rate
   `The Lion King (1994)` higher than viewers with siblings.
6. Run a separate two-sample Kolmogorov-Smirnov test for each movie by only-child
   status and report the count, proportion, and qualifying titles at raw p < 0.005.
7. Run a one-tailed Mann-Whitney U test of whether social viewers rate
   `The Wolf of Wall Street (2013)` higher than viewers who prefer watching alone.
8. Run a separate one-tailed Mann-Whitney U test for each movie in the same
   direction and report the count, proportion, and qualifying titles at raw p < 0.005.
9. Run a two-sample Kolmogorov-Smirnov test comparing all observed ratings of
   `Home Alone (1990)` and `Finding Nemo (2003)`.
10. Identify movies by each of the eight franchise keywords. Within each franchise,
    run a Kruskal-Wallis test across constituent movies and count franchises with
    raw p < 0.005.
11. Sum columns 401-421 for each participant, split participants above and below
    the median while excluding participants exactly at the median, run a separate
    two-sample Kolmogorov-Smirnov test for each movie, and report the titles with
    raw p < 0.005.
