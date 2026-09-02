# Changelog

## Unreleased

- Deterministic deliverable gates (`gates.py`): after a CLI validator's final turn,
  `rrg dispatch` checks the returned structure against the deliverable contract and
  sends coded violations back as a revision turn (default 1, `--gate-revisions N`,
  `--no-gates`; prefs `gates`, `gate_revisions`). Hard violations (files, summary
  schema, DYFA, scripts naming their CSV/PNG) fail the run; advisory ones are asked
  for but never fail it. Every attempt is recorded in
  `GATES.json`, `RUN_INFO.md`, and `rrg eval`; exit code 3 when gates still fail.
  `rrg import` gates manual returns once, before normalization.
- `rrg prefs --set` now validates integer prefs (`gate_revisions`).

## 0.1.0

- Initial standalone package.
- Project scaffolding and discovery.
- Study-cartridge prompt rendering and preflight.
- Verified CSV/Parquet conversion with metadata and codebook outputs.
- Build-then-publish package assembly, blinding lint, and provenance.
- Human-reviewed scorecard scaffolding.
- Full cartridge-driven GUI for setup, conversion, packaging, prompts, runs,
  comparison notes, and scorecards.
- Authenticated loopback API with no shell execution and confined file previews.
- Compatibility normalization for the original RRG manifest and question-map schema.
