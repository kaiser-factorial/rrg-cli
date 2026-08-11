# MovieRatings RRG demonstration

This project demonstrates the reusable RRG validation workflow using a 1,097-row,
477-column movie-ratings dataset and a human-authored origin report.

The original CSV is preserved at `data/movieReplicationSet.csv`. The original
assignment and report are operator-only. Result-neutral Markdown files define the
model-facing study, and `ANALYSIS_PROTOCOL_OG.md` reconstructs the origin methods
without exposing its findings.

## Prepare and inspect

```bash
rrg convert --root .
rrg preflight --root .
rrg gui --root . --open
```

## Build demonstration packages

```bash
rrg package --root . --stage replication --model DemoReplicationModel
rrg package --root . --stage robustness --model DemoRobustnessModel
```

Generalization is intentionally disabled until a distinct data or holdout policy is
defined. The placeholder model names and dispatch slugs should be replaced before
running a real validator.
