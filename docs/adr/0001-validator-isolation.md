# ADR 0001 — Isolate validators from operator secrets via zip delivery + import

- **Status:** Accepted historically; enforcement/import mechanics superseded by ADRs 0003 and 0004
- **Date:** 2026-06-23

## Context

> Path names and import behavior below describe the 2026-06-23 design. New projects
> use explicit `operator/packages` and `operator/runs` roots; imports are now staged,
> gated, and atomic. See ADRs 0003 and 0004.

RRG's purpose is to blind validators from the original methodology and results so their
work is independent. Until now, blinding was enforced **only at the package-content
level**: `lint_package` guarantees no withheld files are *inside* an outgoing package
(see `blinding.py`).

But packages were built — and validators were run — *inside* the project's `operator/`
tree, which also holds every secret:

- `operator/origin/` — the held-back origin report + per-question `SUMMARY.md` (the answer key)
- `operator/private/`
- `operator/_packages/…` — every model's package and the provenance log
- `operator/SCORECARD_*` — grading
- and `shared/ANALYSIS_PROTOCOL_OG.md` — the original methodology a *robustness* validator must never see

Because the validator's working directory sat inside this tree (a built package lived at
`operator/_packages/<stage>/<model>/`), a single relative traversal exposed everything.

This is not hypothetical. In a June 2026 test run, Gemini 3.1 Pro — unprompted — executed
`ls -la ../../../origin/ ../../../private/` **twice**, explicitly "to check if any of the
prior analysis results or methodologies are documented there." The content-lint passed;
blinding failed anyway, because **the lint controls what is *in* the package, not what the
validator can *reach* on disk.**

The gap is most dangerous in robustness (both method and results must be hidden), but it
compromises replication too — a validator can copy the answer key instead of reproducing it.

## Decision

Deliver each linted package as a **self-contained zip**, run validators in an environment
**separate from the project**, and **import** their returned outputs back for review.

1. `rrg package` (and the GUI Build) writes a `<run_label>.zip` containing exactly the
   package files, excluding the operator-only `_provenance.json`.
2. The operator runs the validator on that zip in a location that does **not** have the
   project's `operator/` tree as an ancestor — a scratch directory, a container, or a
   separate machine. RRG no longer expects validators to run inside `operator/`.
3. `rrg import --stage S --model M <returned>` ingests the validator's returned folder or
   zip into `operator/<output_folder>/`, with **zip-slip protection**: any entry that
   resolves outside the run folder is rejected.

We explicitly **do not** add "do not snoop" instructions to the validator prompt (see
Alternatives).

## Consequences

**Positive**

- The validator's filesystem contains only the package and its own outputs; there is no
  relative path to the secrets. `ls ../../../origin` returns nothing.
- The zip is a clean, hashable, archivable artifact — useful provenance.
- It is exactly the unit you mount into a container when you want OS-level *enforcement*
  rather than isolation-by-placement.

**Negative / responsibilities**

- This is isolation by *placement*, not OS enforcement. If the operator unzips into
  `operator/` and runs there, the hole reopens. Workflow and docs must be explicit: never
  run a validator inside the project.
- Real protection against a deliberately adversarial agent still requires an OS sandbox
  (container/VM/chroot). The zip makes that natural but does not impose it.
- Adds an explicit import step to the operator workflow.

## Alternatives considered

- **Isolated dispatch directory (no zip).** Copy the package to an external dir and run in
  place. Weaker than a zip: the project's secrets still exist at an absolute path on the
  same disk, reachable via `cat /full/path/...` or `find`. It stops lazy `../` traversal
  only. May still be offered later as a local convenience.
- **Prompt hardening** ("operate only within this folder; do not look for prior results").
  Rejected. Prompt instructions are not enforcement, and — supported by red-teaming
  observations — explicitly naming a forbidden behavior can *prime* a model toward it
  ("oh, I had the option to be bad?"). We rely on removing access, not on asking nicely.
  The existing turn-gating ("orient only, then stop and wait") stays, since it limits
  premature filesystem activity for benign reasons.
- **OS-level sandbox built into RRG.** Out of scope: RRG does not control the operator's
  runtime. We make sandboxing easy (zip) rather than mandatory.

## Security notes

- The delivered zip excludes `_provenance.json` (operator metadata: file hashes, blinding
  result, prompt version).
- `rrg import` validates that every entry resolves inside the destination run folder
  (zip-slip / path-traversal protection), because the returned archive is untrusted
  validator output.
- The blinding lint remains in force: it guards package **contents**; isolation guards
  **reach**. They are complementary, not redundant.
