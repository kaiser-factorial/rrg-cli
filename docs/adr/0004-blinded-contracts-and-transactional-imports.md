# ADR 0004 — Blinded metric contracts, one run identity, and transactional imports

- **Status:** Accepted
- **Date:** 2026-09-02
- **Related:** ADR 0001 (validator isolation), ADR 0002 (round-trip lifecycle),
  ADR 0003 (enforced isolation)

## Context

Free-text comparison could miss a substantive discrepancy such as `8.1` versus `8.2`,
and the scorecard and Review UI could disagree because they had separate extraction
paths. At the same time, giving a validator expected values or permission to choose a
tolerance would break blinding. Returned artifacts also had two competing identities:
the dispatch scratch output and an importer-computed operator folder. A malformed zip
could begin writing before a later bad member was discovered.

## Decision

1. **Split the metric contract by trust boundary.** The validator receives
   `shared/METRIC_SPEC.json` (`rrg.metric-specs.v1`): stable metric ids, JSON paths,
   kinds, units, nullability, and a deliberately small set of result-neutral arithmetic
   relations. Canonical values live only in `operator/origin/origin.json`
   (`rrg.origin-results.v1`). The public schema rejects answer-, method-, tolerance-,
   and formula-bearing keys.
2. **Use one comparison engine.** Scorecards and the Review UI call
   `extract.question_extraction`. Canonical id/path joins are primary; free-text parsing
   is legacy fallback. Unit-normalized non-p-value comparisons are exact. P-values alone
   receive the pipeline-owned absolute band `0.005`, and a non-exact value within the
   band stays explicitly flagged.
3. **Gate internal consistency before comparison.** Every declared summary value and
   its `_units` entry must exist and type-check; undeclared numeric values fail. Declared
   `sum_equals` and `difference_equals` relations use decimal exactness. DYFA F/A must
   repeat each metric as a backticked machine marker that equals the JSON summary.
   Revision feedback contains codes and artifact coordinates only, never origin values
   or deltas.
4. **Give each build one run destination.** New projects store packages, runs, reviews,
   grading, and archives in named operator subdirectories. Provenance records a portable
   relative `output_path`; imports resolve that path even when runtime-reported validator
   or model names differ. Legacy paths remain readable.
5. **Treat returned output as an untrusted transaction.** A folder or zip is copied to
   isolated staging only after every path is validated. Traversal, duplicate or
   case-colliding archive names, and source symlinks are rejected. One transport-only
   wrapper may be stripped. Gates inspect the actual staged deliverable root. A unique
   sibling candidate is then atomically moved into an empty authoritative destination;
   a non-empty destination is never overwritten.
6. **Import the validator delta.** Automated dispatch snapshots the extracted package
   and imports only new or changed validator files when the validator writes at the
   scratch root. Unchanged package inputs are not duplicated into the operator run.

## Consequences

- A numeric discrepancy is visible deterministically in both review surfaces.
- Tolerance policy cannot be selected or widened by a validator.
- Validator-facing gates can detect self-contradiction without learning the answer.
- Failed gated returns remain importable for audit, but commands exit `3` and the run
  remains visibly failed rather than being normalized into apparent compliance.
- Existing projects are not silently migrated; `rrg paths` shows their resolved layout.
- The current relation language is intentionally limited to exact addition/subtraction.
  More expressive formulas require a typed, auditable DSL and a blinding review.
- The append-only provenance log is not yet signed or locked for concurrent writers.
