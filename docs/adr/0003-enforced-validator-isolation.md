# ADR 0003 — Enforce validator isolation with an OS sandbox, write detection, and read-only packages

- **Status:** Accepted
- **Date:** 2026-09-02
- **Supersedes in part:** ADR 0001 (isolation by convention)

## Context

ADR 0001 isolates validators by *convention*: the package is extracted to a temp dir
outside the project and the agent is run there. On 2026-09-02 a Hermes run of Kimi K3
(`cmmi-condensed`, run `4d3cf3d8`) showed what convention is worth:

- The validator never listed its working directory. Its first action was a
  home-directory search for the study files (`search_files /Users/…`, `find ~/Projects`),
  which found the project tree, other studies' protocols (`LoveSmarter`, `Effort`), and
  its own published package under `operator/_packages/`.
- It executed the whole analysis inside that package directory. RRG's importer found
  nothing in the temp dir; the package was polluted with 43 output files.
- Each turn ran as an isolated one-shot: `hermes -z --resume` starts a fresh session
  (verified by a two-call probe), so the Execute turn had no memory of Orient.

Blinding cannot depend on the validator choosing to stay where it was put.

## Decision

1. **OS sandbox.** Every validator command (and every figure script the executable gate
   runs) is wrapped with `sandbox-exec` on macOS, denying `file-read*` and `file-write*`
   under the project root, the enclosing git checkout, and any `dispatch.sandbox_deny`
   extras. Hermes and its shell inherit the denial. Other platforms have no wrapper yet
   and rely on (2). `dispatch.sandbox: off` disables it. `src/rrg_cli/sandbox.py`.
2. **Write detection and quarantine.** The git checkout is stat-snapshotted before and
   after the validator runs. Any new, modified, or removed file is an *isolation breach*:
   recorded on the run's breach record as `wrote_inside_project` and **blocking**
   grading until acknowledged, like a copied secret — reaching the tree means the
   validator could read anything withheld. New files inside the published package dir
   are moved into the collection dir so import still works and the package is pristine.
3. **Read-only published packages.** After the zip is cut, the package dir and zip are
   chmod'd read-only. `archive`/`purge` restore write permission transiently.
4. **Working-directory inventory.** Dispatch prepends the absolute work dir and the
   file list to the first turn, with an explicit "do not search, read, or write outside".
5. **Real session chaining for Hermes.** `hermes chat -Q --query-file … --in <work_dir>
   --resume <sid>` replaces `hermes -z`.

## Consequences

- A run that escaped is now visible (`ISOLATION BREACH` in `rrg dispatch` output,
  `RUN_INFO.md`, `rrg eval`) and cannot be graded silently.
- Sandboxed validators cannot use Spotlight or `find` to locate the project; the
  inventory removes the reason to try.
- Package directories cannot be edited in place; tests that simulate tampering chmod first.
- Linux/Windows still lack an OS wrapper: detection is the only enforcement there.
  Candidates: `bwrap`, `firejail`, or a container. Tracked as follow-up work.
- The 2026-09-02 Kimi run predates this ADR. Its breach record says CLEAN because only
  copied bytes were hashed; the transcript shows it listed other studies' protocol files.
  Treat that run as breached.
