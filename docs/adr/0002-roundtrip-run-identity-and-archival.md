# ADR 0002 — Round-trip run identity, breach detection, and archival lifecycle

- **Status:** Accepted
- **Date:** 2026-06-23

## Context

ADR 0001 made delivery a self-contained zip, run **outside** the project, with `rrg import`
bringing results back. That closed the *reach* breach at the artifact level but left three
gaps the round-trip needs to be both safe and ergonomic:

1. **No durable run identity.** The delivery zip is meant to leave the project — that is the
   whole point — but once it does, nothing ties a *returned* result set back to the build
   that produced it. Today `import` makes the operator re-specify `--stage`/`--model` by
   hand, and the run-folder template `<stage>_<model>` **overwrites on re-run**, silently
   destroying prior history.

2. **Isolation is placement, not enforcement — and unverified.** ADR 0001 itself flags that
   if the operator unzips into `operator/` and runs there, the hole reopens. Nothing checks
   whether that happened: there is no signal, at import time, that a returned result set was
   produced under compromised blinding. (The June 2026 Gemini run — `ls ../../../origin/`
   "to check for prior results" — is the failure mode.)

3. **Destructive deletes.** `delete_scorecard` and `delete_grading` hard-`unlink`. There is
   no undo, no record, and — because the live `workspace/` is gitignored — no recovery for
   the real studies.

## Decision

Close the round trip with a durable run identity, detect breaches on the way back in, and
make all deletion reversible.

### 1. Run identity (`run_id`)

- At build/publish time, `rrg package` mints an opaque `run_id` (short random token carrying
  **no** methodology/result information). It is recorded in `_provenance.json` and in the
  `provenance_log.jsonl` entry.
- Run folders, package dirs, and the delivery zip are suffixed with it:
  `operator/<stage>_<model>__<run_id>/` and `…__<run_id>.zip`. Re-running a model mints a new
  `run_id` → a new folder; **latest-wins overwriting is gone** and runs accumulate as distinct
  history.
- Per-run and graded artifacts (run folders, package zips, scorecards, grading state,
  exports) inherit the suffix. **Deterministic data derivatives keep stable names** (converted
  CSV/Parquet, codebook, metadata): they are path-referenced in `rrg.yaml`, verified
  bit-for-bit against the source, and already content-addressed by hash in provenance.
  Versioning them by name would break the manifest and defeat their reproducibility.

### 2. Self-describing delivery + auto-resolved import

- The delivery zip carries one blinding-safe marker, `RRG_RUN.txt`, containing only the
  opaque `run_id` and a single instruction: *return this file unchanged with your outputs.*
  It reveals nothing about methodology or results.
- `rrg import <returned>` reads the marker, looks `run_id` up in `provenance_log.jsonl`, and
  resolves stage/model/label/output-folder automatically. If the marker is absent (the
  validator dropped it), it falls back to today's explicit `--stage`/`--model`.
  Identity-matching is **best-effort with a manual safety net** — never a hard dependency.

### 3. Breach detection at import (the guard)

- We do not try to detect *where* the validator ran. Instead, on import RRG hashes every
  returned file and compares against the hashes of the **withheld answer key** — the origin
  results and the original methodology a robustness validator must never see.
- A content match means the validator did not merely *reach* the secrets, it *copied* them —
  a near-certain blinding breach. RRG flags it loudly, records the flag on the run, and
  **blocks grading** until the operator acknowledges.
- Softer signal: if the import `source` path resolves *inside* the project tree, warn that the
  run may have executed without isolation.
- This complements, and does not replace, the content-lint (guards package **contents**) and
  isolation-by-placement (guards **reach**). It is the first check to guard the **return**
  path.

### 4. Archival lifecycle (reversible deletion)

- A per-project `operator/_archive/` holds soft-deleted items. Every "delete" surface —
  beginning with `delete_scorecard` and `delete_grading` — becomes *move into `_archive/`*,
  recording an `_archive/index.jsonl` entry (item type, original relative path, `run_id` if
  any, archived-at timestamp). No code path calls `unlink` directly anymore.
- The archive view is the **only** place that purges (hard-deletes), behind an explicit
  confirmation. **Restore** reverses the recorded move.
- Finalized/protected guards stay: a finalized scorecard must be reopened before it can be
  archived, exactly as today.

### 5. Surfaces

- **File explorer** (new top-level tab) — a within-project tree. The **default** view is
  blinding-aware: it mirrors the Runs exclusions and shows withheld regions (`origin/`,
  `private/`, the results key) as **redacted placeholders**, so the operator can confirm they
  exist and are correctly withheld without seeing contents. An **operator x-ray** toggle
  reveals everything. The x-ray is safe because the GUI is operator-side, served locally
  behind a token, and never part of any package — it does not touch the blinding guarantee,
  which concerns the *validator's* filesystem, not the operator's screen. The **Archive**
  panel lives inside this tab (file lifecycle is one concern).
- **CLI** — `rrg package` prints the zip path and `run_id`; `rrg import <returned>`
  auto-resolves via the marker; `rrg runs` prints the provenance registry (built runs, each
  returned / pending / graded / flagged). Archive operations get verbs too:
  `rrg archive`, `rrg restore`, `rrg purge`.

## Consequences

**Positive**

- A returned result set re-binds to its build automatically and tamper-evidently; the zip can
  live anywhere on disk or another machine.
- Re-runs are preserved, not clobbered — real experiment history.
- The return path is guarded for the first time: a copied answer key is caught at the door.
- Deletion is recoverable with an audit trail, which matters precisely because the live
  workspace is gitignored.

**Negative / responsibilities**

- The breach guard catches *copied* secrets, not *read-and-paraphrased* ones. It raises the
  cost of a breach and catches the lazy case; it is not proof of clean isolation. OS-level
  sandboxing (ADR 0001) remains the real enforcement.
- The `RRG_RUN.txt` marker depends on the validator returning it; hence the manual fallback.
  We do **not** prompt-harden around it, consistent with ADR 0001's stance on not priming
  models toward forbidden behavior.
- `_archive/` grows until purged. It is operator-only and excluded from packages and the
  blinding-aware explorer view by the same rules as `private/`.
- run_id-suffixed folders change the on-disk layout; existing LoveSmarter runs predate it.
  **Resolved: no migration code.** The studies will be re-run under the new scheme, and the
  pre-ADR-0002 runs moved into `_archive/` by hand at that point.

## Alternatives considered

- **Track packages by zip location.** Rejected — the zip is meant to leave the project;
  location is not identity. The provenance log is already a location-independent registry; we
  add only a correlation id.
- **Encode identity in the zip filename only.** Weaker: the operator can rename the results
  zip, and filenames leak the model/stage. The in-package opaque marker survives renaming and
  reveals nothing.
- **Hard-delete behind a confirm dialog (no archive).** Rejected for the live studies:
  gitignored workspace = no recovery. Reversible-by-default with an explicit purge is safer
  and barely more code.
- **Detect breach by where the validator ran.** Not reliably knowable from returned files.
  Hashing returned content against the withheld key is a direct, enforceable signal.

## Security notes

- `RRG_RUN.txt` contains only an opaque token — no path, model, methodology, or result hint.
- The breach-detection hashes are computed operator-side over withheld files that never leave
  the project; nothing about them is shipped.
- `_archive/` is operator-only: excluded from packages (blinding lint) and shown only in the
  operator x-ray, never in the blinding-aware default view.
- Purge is confined to the project tree and to `_archive/` specifically; restore validates
  that the recorded original path resolves back inside the project — the same zip-slip
  discipline as `import`.

## Implementation plan (sequencing)

Each slice is independently shippable and testable.

- **A. run_id core** — mint in `packager.py`; thread into provenance + folder/zip naming;
  update `importer.run_output_folder` to honor the suffix. Tests: naming, no-clobber re-run.
- **B. Marker + auto-resolve import** — write `RRG_RUN.txt` into the zip; `import` reads it,
  resolves from the log, manual fallback. Tests: round-trip resolve, missing-marker fallback.
- **C. Breach guard** — withheld-key hashing + returned-file comparison + path-inside-project
  warning; surface the flag on the run and block grading. Tests: planted-key match flags;
  clean run passes.
- **D. Archive lifecycle** — `operator/_archive/` + `index.jsonl`; reroute
  `delete_scorecard`/`delete_grading` to archive; add restore/purge (service + CLI). Tests:
  archive→restore round-trip, purge confined, finalized-guard preserved.
- **E. File explorer tab** — blinding-aware tree + redacted placeholders + operator x-ray
  toggle + Archive panel; `/api/tree` endpoint reusing the Runs exclusion rules. Tests:
  withheld paths redacted in default mode, present in x-ray.
- **F. CLI registry** — `rrg runs`, `rrg archive` / `restore` / `purge`. Tests: registry
  lists status.

A–C close the round-trip and the guard; D–F add the lifecycle and surfaces.
