# Architecture

## Boundary

The installable engine is study-neutral. Each project supplies two manifests:

- `rrg.yaml`: paths, stages, roster, routing, blinding, determinism, dispatch.
- `study.yaml`: dataset, questions, held constants, original work, supplied
  solutions, and deliverables.

The validator receives a package of inputs. The prompt is rendered separately.
Returned outputs go to an operator-side run folder. The answer key and scorecards
never enter packages.

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
| `scorecard` | provisional side-by-side grading skeleton |
| `gui_service` | generic setup, conversion, packaging, runs, comparison, notes, scorecards |
| `gui` | authenticated loopback HTTP boundary and packaged static assets |
| `cli` | command parsing, structured output, exit codes |

## Exit codes

- `0`: command completed; gate passed where applicable.
- `1`: invalid command, configuration, or input.
- `2`: a readiness or blinding gate did not pass.
- `130`: interrupted.

## Scientific boundary

The engine can represent a disabled stage but does not invent its scientific policy.
The starter generalization stage remains disabled until its cartridge defines the
new-data plan, method policy, measurement-model transport, and success rubric.

## GUI security boundary

The browser frontend is a packaged static asset and calls the Python service with
structured JSON. The service invokes engine functions directly and never shells out.
It binds to loopback, uses a per-process session token, rejects cross-origin writes,
caps request bodies, confines all paths, and excludes the results key/private roots
from run discovery. Images are returned as bounded data URLs rather than unauthenticated
file routes.
