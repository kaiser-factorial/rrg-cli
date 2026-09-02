# Multiple projects in the GUI

## Decision

Do not store several study profiles in one `rrg.yaml` or `study.yaml`. Each study
remains a self-contained RRG project root with its own data, shared inputs, withheld
origin, packages, runs, notes, and scorecards.

A **workspace** is a parent directory containing one or more RRG project roots. The
GUI may switch its active project within that workspace or scaffold a new child
project. This preserves the engine/cartridge boundary and prevents files from one
study from being routed into another study's package.

## Interface

```text
rrg gui --workspace /path/to/RRG_root --open
rrg workspace /path/to/RRG_root          # discover projects without launching GUI
```

- The header shows the active project and a `Projects` control near `Setup`.
- `Projects` lists discovered project roots, readiness, and last-opened time.
- `New project` asks for a project name and a new child directory, then runs the
  same scaffold as `rrg init` and opens its Setup screen.
- Switching projects reloads all dashboard, setup, package, run, comparison, and
  scorecard state from the selected root.
- Existing `rrg gui --root PROJECT` behavior remains available as locked
  single-project mode.

## Safety boundary

- Resolve the workspace and every project path canonically.
- Accept only project roots at or beneath the workspace; reject symlink escapes.
- A project must contain `.rrg_root` plus readable engine and study manifests.
- Exclude generated, private, virtual-environment, and VCS directories from
  recursive discovery.
- Confine every API operation to the active project exactly as in single-project
  mode.
- Serialize project selection and mutations so a save or package build cannot
  change roots midway through a request.
- Never combine manifests, package registries, or operator directories across
  projects.

## State

Project configuration is already saved by each project's `rrg.yaml` and
`study.yaml`; no new multi-profile file format is required. Optional UI-only state
may record the last active project and recent projects, but it must not become a
source of scientific configuration.

This interface is implemented. `rrg workspace` supports JSON output for agents, while
`rrg paths --project <root>` shows the active project's effective operator layout.
New projects separate packages, runs, reviews, grading, and archive state; legacy
projects remain readable without automatic relocation.

For the current workspace, LoveSmarter can remain the root project and demonstrations
can live below `demo_projects/`, each with its own `.rrg_root` marker.
