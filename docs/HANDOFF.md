# HANDOFF — RRG

*Current continuity brief. Last updated 2026-09-02.*

The detailed implementation record, requirement matrix, test evidence, outstanding
work, and architecture critique are in
[`HANDOFF_VALIDATION_HARDENING_2026-09-02.md`](HANDOFF_VALIDATION_HARDENING_2026-09-02.md).
Read that first, then `WALKTHROUGH.md`, `SPEC.md`, and the ADRs under `docs/adr/`.

## Current state

RRG is a blinded research-validation pipeline: **Replication → Robustness →
Generalization**. It packages only stage-permitted inputs, dispatches supported
validator harnesses, gates the returned deliverables, imports them into operator-only
run storage, and exposes deterministic comparisons for human review.

The validation-hardening trajectory is merged into `main` through PR #3
(`e04d309`). It contains both Claude PRs (#1 and #2) plus the commits
for shared comparison, blinded metric contracts, robustness/model prerequisites,
semantic gates, explicit writable roots, transactional imports, the new operator
layout, and CLI usability. GitHub CI passed on Python 3.9–3.12 plus the distribution
build. The feature branches and worktrees were retained.

## Trust boundaries

- `shared/METRIC_SPEC.json` is validator-facing and contains structure only.
- `operator/origin/origin.json` contains canonical values and is never packaged.
- Scorecard and Review UI use the same operator-side comparison engine.
- Non-p-value metrics are exact-only. P-values use a pipeline-owned absolute `0.005`
  band, while close non-exact values remain visibly flagged.
- Gate revision feedback contains codes and artifact coordinates, never origin values.
- Learned models declared by a study must pass operator-side evaluation prerequisites
  before packaging.

## New-project layout

```text
operator/
├── origin/
├── packages/
├── runs/<stage>/
├── reviews/
├── grading/
└── archive/
```

Existing projects retain legacy paths until explicitly migrated. Use `rrg paths` to
inspect the effective layout and `rrg workspace` to discover cartridges.

## Operational next step

Run a real end-to-end Hermes/Kimi canary from a prepared project and confirm:

1. the sandbox record says `write_enforced: true` on the deployment host;
2. gate revisions use the same Hermes session;
3. only validator-created/changed files enter the run;
4. a deliberate metric mismatch fails loudly without leaking the origin value; and
5. scorecard and Review UI show identical status/delta/tolerance output.

Do not delete retained feature branches/worktrees or migrate historical projects
without explicit operator authorization.
