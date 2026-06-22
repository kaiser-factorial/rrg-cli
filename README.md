# rrg-cli

`rrg-cli` is the reusable engine behind the RRG research-validation workflow:
**Replication → Robustness → Generalization**. It packages the right inputs for a
validator, enforces stage-specific blinding, records provenance, renders staged
prompts, and scaffolds human grading. It does not run models or grade findings.

## Install

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e /path/to/rrg-cli
```

Python 3.9+ is supported. Data conversion dependencies are installed with the
package so `rrg convert` works immediately.

## Start a project

```bash
rrg init my-validation
cd my-validation
rrg doctor
```

An RRG project contains a `.rrg_root` marker, `rrg.yaml` engine manifest,
`study.yaml` cartridge, model-facing `shared/`, source `data/`, withheld
`operator/`, and prompt scaffolds. Replace the starter content and update the two
YAML files; the CLI itself never needs study-specific edits.

## Commands

```text
rrg init PATH                         create a project cartridge
rrg doctor [--stage STAGE]           inspect configuration and dependencies
rrg preflight [--stage STAGE]        strict file + prompt readiness gate
rrg convert [SOURCE]                 create and verify CSV/Parquet derivatives
rrg package --stage S --model M      stage, lint, publish, and log a package
rrg lint PACKAGE --stage S           lint an existing outgoing package
rrg prompt --stage S --model M       render the stage prompt
rrg scorecard --run DIR ...          create a human-grading skeleton
rrg gui [--port 8765]                launch the local status interface
rrg version                           print the installed version
```

All project commands accept `--root`, `--config`, and `--study`. Otherwise project discovery is:
`$RRG_PROJECT_ROOT` → nearest `.rrg_root` ancestor → current directory.

The CLI also recognizes the original prototype layout automatically when it finds
`RRG/vp_config.yaml` and `RRG/study.yaml` below the project root.

## Safety model

- Packages are assembled in a temporary directory and published only after lint.
- Original results, scorecards, and operator-only paths are denied by pattern.
- Replication can require an original protocol; robustness can forbid all protocols.
- `--force` can override a lint hard-fail, but the override is recorded.
- The package and prompt are separate. Operator reminders are never model-facing.
- Scorecards remain provisional until a person assigns every verdict.

## Configuration

`rrg.yaml` owns engine concerns: paths, routing, stages, roster, blinding,
determinism, and dispatch. `study.yaml` owns the cartridge: dataset, questions,
held constants, original work, optional supplied solutions, and deliverables.

Generalization is included in the schema but disabled in the starter manifest. A
project must define its data-variation plan and prompt before enabling that stage;
the CLI does not silently choose a scientific policy.

## Development

```bash
pip install -e '.[dev]'
pytest
python -m build
```
