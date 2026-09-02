# Handoff — validation hardening trajectory (2026-09-02)

## Repository state

- Repository: `kaiser-factorial/rrg-cli`
- Working branch: `feat/rrg-workspace-cli`
- Continuation worktree: `/Users/corinakaiser/Projects/Effort/rrg-cli-worktree`
- Base feature branch: `feat/rrg-validation-hardening`
- Remote status checked 2026-09-02: `origin/main` remains at `4511054`; open PR #1
  (`feat/deliverable-gates`) and PR #2 (`claude/focused-curran-8e09f2`) are both
  ancestors of this branch. PR #2's deterministic extraction-order fix is present.
- Local hardening commits:
  - `59b6493` — Unify scorecard and review metric comparison
  - `0183a16` — Add blinded canonical metric contracts
  - `a3d31fa` — Gate robustness inputs and derived model evaluations
  - `218bb01` — Enforce semantic deliverable gates
  - `2e3eeb6` — Simplify run layout and transactional imports
- Nothing from this trajectory has been pushed. The original checkout's unrelated
  untracked `skills/rrg-effort-expander/` was not modified or staged.

## Requirement-by-requirement status

| # | Requirement | Status and evidence |
|---|---|---|
| 1 | One scorecard/Review UI comparison engine | Complete. Both call `extract.question_extraction`; a monkeypatch regression test proves the shared call path. |
| 2 | Canonical origin JSON + per-question metric specs | Complete. `rrg.origin-results.v1` is withheld; `rrg.metric-specs.v1` is public, schema-checked, and contains no values/tolerance/method/formula. |
| 3 | Robust normalizer + blinded robustness package | Complete as a gated foundation. The Effort normalizer audits report categories and flags derived/answer-bearing columns. Optional approved `rrg.analysis-contract.v1` fixes result-neutral design constants while requiring independent method choice. |
| 4 | Evaluate learned models before validating outputs | Complete. Required derived models need immutable artifact hashes, independent ground truth, task-appropriate metrics, reviewer approval, and operator thresholds under `rrg.model-evaluation.v1`. RRG computes pass/fail. |
| 5 | Arithmetic/unit/DYFA consistency gates | Complete. Metrics/units/types/nullability, undeclared numeric fields, exact sum/difference relations, and DYFA F/A markers are checked deterministically. |
| 6 | Gate actual writable deliverable root before import | Complete. Dispatch locates/gates scratch output; manual import stages and gates the located root before the first operator-run install. |
| 7 | Bounded semantic revision without origin leakage | Complete. Default one revision; semantic feedback names only codes/artifact coordinates and tells the validator to regenerate from its own files. Origin values/deltas never enter feedback. |
| 8 | Cleaner workspace/import structure | Complete for new projects with legacy fallback. One provenance-selected run destination under explicit operator subdirectories; no duplicate runtime-derived destination. |
| 9 | Human- and agent-usable CLI | Complete. Workflow help, `status`/`validate`/`review`, `--project`, `workspace`, `paths`, agent prompt mode, JSON outputs, and exit `3` for imported gate failure. |
| 10 | Failure-first tests and boundary repair | Complete. New tests cover schema leakage, exact/tolerant comparison, semantic gates, result-bearing robustness inputs, invalid learned-model evidence, writable roots, transaction rollback, traversal/collisions/symlinks, wrapper stripping, run identity, and delta-only imports. |
| 11 | Current documentation | Complete in README, changelog, architecture, agentic CLI design, ADR 0003, and ADR 0004. |
| 12 | Handoff + critique | This document. |

## Important behavior

### Comparison policy

- Non-p-value metrics are exact-only. `8.1` versus `8.2` is `different` with a visible
  delta; currency magnitude does not widen tolerance.
- P-values alone receive a fixed absolute `0.005` band owned by the pipeline. A
  non-exact p-value inside the band is `within_tolerance`, never `exact`.
- Validator output cannot choose, communicate, or widen tolerance.
- Canonical metric id/path comparison is primary. Text extraction remains only for
  existing projects without canonical records.

### Blinding boundary

- Validator-safe: `shared/METRIC_SPEC.json`, result-neutral analysis contract, data,
  questions, stage-permitted protocol.
- Operator-only: `operator/origin/origin.json`, origin narrative/results, scorecards,
  review notes, grading state, and learned-model evaluation evidence.
- Gate feedback checks the validator against its own public contract and internal
  artifacts. It never compares against the origin.

### Import/run lifecycle

1. Package build records one portable `output_path`.
2. Validator works in external scratch with explicit writable roots where macOS can
   enforce them.
3. Dispatch gates the located writable deliverable root and may issue bounded revisions.
4. The returned tree is staged outside the project. All archive paths are validated
   before extraction; traversal, case collisions, duplicates, and symlinks are rejected.
5. A transport wrapper is stripped, manual returns are gated, and a unique sibling
   candidate is atomically installed into an empty authoritative destination.
6. Normalization happens after the evidence/gate boundary. Failed gated returns are
   retained for audit, marked failed, and return exit code `3`.

## Verification record

- Extraction/metric/Review overlap after remote sync: `19 passed`.
- Final focused hardening suite: `103 passed`.
- All six touched RRG skills pass the Codex skill `quick_validate.py` check.
- Final unrestricted local suite after the cross-version CI repairs: `252 passed,
  1 skipped` from 253 collected tests.
- Python 3.9 and 3.11 compile checks cover the CLI/TUI syntax that Python 3.13 accepts
  more permissively; the 46 affected CLI/TUI/gate tests pass locally.
- Re-run the full suite and the
  nine loopback tests after any code change touching dispatch, import, GUI service,
  grading, intake, or origin APIs.

Suggested commands:

```bash
PYTHONPATH=src /opt/anaconda3/bin/python -m pytest -q
PYTHONPATH=src /opt/anaconda3/bin/python -m rrg_cli.cli --help
PYTHONPATH=src /opt/anaconda3/bin/python -m rrg_cli.cli paths --project <project>
```

The managed desktop sandbox may deny loopback binds. That is an environment failure,
not an application assertion failure; rerun the named HTTP tests in an allowed shell.

## Outstanding work

1. Push/open/update PRs only with explicit authorization. Current work is local.
2. Existing projects are deliberately not auto-migrated. Add the new path keys when an
   operator is ready, then verify `rrg paths`; do not move historical evidence silently.
3. Populate and approve real `METRIC_SPEC.json`, canonical origin JSON, robustness
   contracts, and learned-model evaluation records per study. Templates are contracts,
   not scientific judgments.
4. Review the Effort normalizer audit for each selected analysis table before enabling
   robustness. HTML/column-name heuristics can over-flag and are not evidence of leakage
   by themselves.
5. No fresh live Hermes/Kimi validation was run after these changes. The code and tests
   are verified; a real end-to-end canary should be the next operational check.
6. macOS write allow-list behavior is unit-tested and capability-probed, but this
   managed host can prevent nested `sandbox-exec`. Confirm a real canary records
   `write_enforced: true` on the deployment host.

## Critique and failure modes

### Isolation is improved, not complete

The selected validator state directory (`~/.hermes`, `~/.claude`, etc.) is still a
broader write root than ideal. A stronger design would launch each run with an isolated
`HOME`, copy in only required credentials/configuration, and persist only an opaque
session token. Linux/Windows still need an enforcing backend (`bwrap`, a container, or
equivalent), not detection alone.

The checkout escape snapshot uses size and nanosecond mtime. A pathological same-size,
mtime-preserving edit could evade it. Hashing likely targets, an OS file-event audit,
or a read-only checkout mount would close that gap.

### Canonical output should eventually eliminate redundant transcription

DYFA backtick markers make prose machine-checkable, but they duplicate summary JSON and
can drift. The more robust end state is to generate the human report's result block from
the canonical summary, or embed a single machine section that the renderer consumes.
Until then, loud mismatch failure is appropriate.

The arithmetic relation language supports exact sum and difference only. Extending it
with a typed expression DSL could cover ratios, percentages, and cross-question totals,
but arbitrary formulas could reveal original methodology or become unsafe to execute.
Any extension needs schema validation, dimensional analysis, and a blinding review.

### Comparison migration needs a sunset

Legacy free-text extraction preserves old projects, but remains heuristic and can pair
the wrong number when prose is dense. The UI should show `comparison_source`, offer a
canonicalization workflow, and eventually treat text fallback as an explicit warning or
error for high-stakes review.

### Model evaluation proves less than it may appear to

The gate proves that declared evidence is structurally complete and that its metrics
meet declared thresholds. It does not independently prove absence of train/test leakage,
selection bias, inappropriate ground truth, subgroup failure, or artifact/data mismatch.
Next revisions should bind evaluation dataset/split hashes, record lineage, require
subgroup/error analysis when relevant, and separate threshold approval from evaluation
execution.

### Failed import state should be more visible

Importing a failed return is intentional: it preserves evidence and supports debugging.
Exit code `3` and `GATES.json` are accurate, but the GUI should present these runs as a
quarantine/failed state so an operator cannot mistake presence under `runs/` for
validation success.

### Provenance and package storage can harden further

`provenance_log.jsonl` is append-only but not locked, signed, or tamper-evident. Parallel
writers can race. Add file locking plus a chained hash or signed manifest. The unpacked
package and zip are intentionally redundant for inspection/delivery, but could become a
content-addressed immutable object with the zip derived on demand.
