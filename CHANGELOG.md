# Changelog

## Unreleased

- Scorecards and the Review UI now use one deterministic comparison engine. Canonical
  metrics are matched by question/id/path with unit normalization and visible deltas.
  Non-p-value metrics are exact-only; only p-values receive the pipeline-owned absolute
  tolerance `0.005`, and non-exact values inside it remain flagged
  `WITHIN_TOLERANCE`. Validator output cannot set comparison policy.
- Added a blinded metric contract pair: validator-facing `shared/METRIC_SPEC.json`
  (`rrg.metric-specs.v1`) contains identifiers, paths, kinds, units, nullability, and
  safe sum/difference relations; operator-only `operator/origin/origin.json`
  (`rrg.origin-results.v1`) contains canonical answers. Doctor validates both and
  packaging blocks origin-result leakage even through flattened routing.
- Metric gates now enforce every declared value and exact `_units` sidecar, reject
  undeclared numeric fields, verify declared arithmetic with decimal exactness, and
  require DYFA F/A markers to agree with the summary. Revision feedback contains only
  codes and artifact coordinates, never origin values or comparison deltas.
- Added optional approved robustness analysis contracts
  (`rrg.analysis-contract.v1`) and an Effort normalization audit. Robustness packaging
  is blocked when held constants are incomplete, origin-derived content is present, or
  the selected analysis input still has derived/answer-bearing columns.
- Added required evaluation gates for declared learned/derived models
  (`rrg.model-evaluation.v1`): immutable artifact hashes, independent ground truth,
  task-appropriate metrics, reviewer approval, and operator-defined thresholds that
  RRG evaluates rather than trusting claimed pass/fail text.
- New projects use explicit `operator/{packages,runs,reviews,grading,archive}` roots;
  runs are stage-scoped and provenance stores a portable relative output path. Existing
  projects retain their legacy layout and remain discoverable.
- Returned folders and zips are fully validated in temporary staging before any run
  write. Import rejects traversal, duplicate/case-colliding paths, and symlinks; strips
  a transport wrapper; gates the actual deliverable root; refuses non-empty targets;
  and atomically installs one provenance-selected run. Dispatch imports only files the
  validator created or changed, not unchanged package inputs.
- Added workflow aliases `rrg status`, `rrg validate`, and `rrg review`, the universal
  `--project` alias, `rrg workspace`, and `rrg paths`; reorganized top-level help around
  the human workflow and added JSON output where useful to agents.
- Deterministic deliverable gates (`gates.py`): after a CLI validator's final turn,
  `rrg dispatch` checks the returned structure against the deliverable contract and
  sends coded violations back as a revision turn (default 1, `--gate-revisions N`,
  `--no-gates`; prefs `gates`, `gate_revisions`). Hard violations (files, summary
  schema, DYFA, scripts naming their CSV/PNG) fail the run; advisory ones are asked
  for but never fail it. Every attempt is recorded in
  `GATES.json`, `RUN_INFO.md`, and `rrg eval`; exit code 3 when gates still fail.
  `rrg import` gates manual returns once, before normalization.
- `rrg prefs --set` now validates integer prefs (`gate_revisions`).
- Executable figure gate: dispatch runs each `Q<n>_fig.py` (sandboxed) and requires it
  to reproduce `Q<n>_fig.png`; renderer drift under 15 % of pixels is advisory,
  crashes/timeouts/missing output/real mismatches are hard. Prefs `gate_exec`,
  `gate_python`; flags `--no-exec-gates`, `--gate-python`; `rrg import --exec-gates`.
- Enforced validator isolation (ADR 0003): macOS `sandbox-exec` denies reads/writes in
  the project tree and confines writes to explicit roots (`dispatch.sandbox`,
  `dispatch.sandbox_deny`, `dispatch.sandbox_write_allow` in rrg.yaml), project-tree
  write detection with quarantine and a blocking `wrote_inside_project` breach,
  read-only published packages, and a working-directory inventory on the first turn.
- Hermes validator switched from `hermes -z --resume` (which starts a new session each
  turn) to `hermes chat -Q --query-file … --in <work_dir> --resume`, so turns chain.
- `MPLBACKEND=Agg` is set for validator and gate subprocesses.

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
