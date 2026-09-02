# Architecture

## Boundary

The installable engine is study-neutral. Each project supplies two manifests:

- `rrg.yaml`: paths, stages, roster, routing, blinding, determinism, dispatch.
- `study.yaml`: dataset, questions, held constants, original work, supplied
  solutions, and deliverables.

The validator receives a package of inputs. The prompt is rendered separately.
Returned outputs are staged, deterministically gated, and atomically installed into
one provenance-selected operator run folder. Canonical origin values, review notes,
grading state, and model-evaluation evidence never enter validator packages.

## Operator layout

New projects declare separate roots for `operator/packages`, `operator/runs`,
`operator/reviews`, `operator/grading`, and `operator/archive`; origin evidence remains
under `operator/origin`. Existing projects without those path keys retain their legacy
locations. `layout.py` is the only source of path resolution, and `rrg paths` exposes
the result to humans and agents.

One package provenance record owns one output destination. It stores a portable
project-relative `output_path` plus a legacy-compatible absolute `output_folder`.
Dispatch scratch/output directories are not second run identities.

## Trust flow

```text
operator origin values ──────────────────────┐
                                                │ operator-only comparison
public metric + analysis contracts → package → validator scratch
                                                │
                                                ↓
                         isolated staging → deterministic gates
                                                │
                                                ↓ atomic install
                                     operator/runs/<stage>/<run>
```

The package includes the public metric schema but never the origin metric values or
comparison tolerance. Import validates a complete untrusted archive/folder before its
first destination write, rejects traversal/collisions/symlinks, gates the actual
staged deliverable root, and refuses to replace a non-empty run.

## Modules

| Module | Responsibility |
|---|---|
| `project` | root discovery, YAML loading, legacy manifest normalization |
| `scaffold` | complete starter project creation |
| `converter` | deterministic derivatives, metadata, cell-level verification |
| `prompts` | placeholders, optional modules, mode filtering, turn parsing |
| `routing` | resolve configured stage inputs and detect basename collisions |
| `blinding` | withheld paths, methodology policy, routing, result-token flags |
| `packager` | temporary assembly, lint gate, publication, provenance |
| `doctor` | dependencies, file references, hashes, routing, prompt preflight |
| `layout` | canonical operator paths, run destinations, legacy fallback |
| `metrics` | public metric schema and held-back canonical origin schema |
| `analysis_contract` | result-neutral held constants for robustness |
| `model_eval` | operator-side learned-model evidence and acceptance gate |
| `gates` | structure, metric, unit, arithmetic, DYFA, and executable-figure checks |
| `scorecard` | operator-side review rendered by the shared comparison engine |
| `gui_service` | generic setup, conversion, packaging, runs, comparison, notes, scorecards (parked) |
| `prefs` | per-project saved defaults (validator, mode, skip_normalize, auto_import) |
| `dispatch` | one-command round-trip: build → prompt → validator → import → normalize |
| `normalize` | post-gate fuzzy file matching and canonical deliverable shape |
| `wizard` | interactive 5-step setup walkthrough (health → conversion → preflight → roster → dispatch) |
| `eval_lite` | pipeline metrics: deliverable contract, breach status, grading status |
| `tui` | rich terminal UI (Base2Tone Mall palette, ASCII banner, command table) |
| `alias` | shell aliases for dispatch validators |
| `gui` | authenticated loopback HTTP boundary and packaged static assets |
| `cli` | command parsing, structured output, exit codes |

## Exit codes

- `0`: command completed; gate passed where applicable.
- `1`: invalid command, configuration, or input.
- `2`: a readiness or blinding gate did not pass.
- `3`: returned artifacts were imported for audit but deterministic gates failed.
- `130`: interrupted.

## Scientific boundary

The engine can represent a disabled stage but does not invent its scientific policy.
The starter generalization stage remains disabled until its cartridge defines the
new-data plan, method policy, measurement-model transport, and success rubric.

Robustness can be enabled only with an operator-approved result-neutral analysis
contract when that contract is configured. Derived models declared in `study.yaml`
must have a valid operator-side evaluation record and pass operator-defined thresholds
before any package is published.

## Comparison boundary

Scorecard and GUI review routes call `extract.question_extraction`. Canonical records
are compared by metric id/path after unit normalization. All non-p-value metrics require
exact equality. P-values alone use the fixed pipeline-owned absolute band `0.005`, and
a close-but-non-exact value remains a visible `within_tolerance` finding. Text parsing
is a compatibility fallback only when canonical records are absent.

## GUI security boundary

The browser frontend is a packaged static asset and calls the Python service with
structured JSON. The service invokes engine functions directly and never shells out.
It binds to loopback, uses a per-process session token, rejects cross-origin writes,
caps request bodies, confines all paths, and excludes the results key/private roots
from run discovery. Images are returned as bounded data URLs rather than unauthenticated
file routes.
