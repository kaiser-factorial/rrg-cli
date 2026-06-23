# Examples

Self-contained RRG projects you can open with the GUI or drive from the CLI.

## MovieRatings

A worked demonstration built on the public Movie Ratings dataset (1,097 participants ×
477 columns). It ships with the converted dataset, 11 validation questions, a withheld
origin report + per-question summary, two built validator packages, and the DYFA report
/ per-question artifact conventions.

Open it in the GUI as a one-project workspace:

```
rrg gui --workspace examples --open
```

or point at the single project directly:

```
rrg gui --root examples/MovieRatings
```

Note: `examples/MovieRatings/operator/origin/` contains the held-back origin report.
In a real study this is withheld from validators; it is included here only so the
example is runnable end to end (compare, grade, finalize a scorecard).
