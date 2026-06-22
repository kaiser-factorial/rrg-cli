# Configuration reference

## `rrg.yaml`

- `version`: manifest version; currently `1`.
- `project.name`: display and provenance name.
- `paths`: project-relative `shared`, `data`, `operator`, and `packages` roots.
- `origin`: origin vendor/model, withheld results key, authoritative data source.
- `files.all`: inputs sent to every enabled stage.
- `files.stage_specific`: inputs permitted only in listed stages.
- `files.withheld`: project paths that must never be sent.
- `roster.<stage>`: validator model, vendor, type, and license records.
- `stages.<id>`: enablement, degree of freedom, prompt, send list, output/report names.
- `blinding.always_withhold`: package-relative deny patterns.
- `blinding.per_stage_methodology`: required and forbidden filename patterns.
- `blinding.result_token_scan`: held-back source, action, excluded package globs, and
  optional `ignore_tokens` for declared shared constants such as a fixed alpha.
- `constraints.exclude_vendors`: origin-family or otherwise ineligible validators.
- `constraints.determinism`: settings copied into provenance.
- `dispatch`: optional agent start template and model slugs.

Every path is confined to the project root. Routed top-level files are flattened by
basename; a collision is a configuration error.

## `study.yaml`

- `overview_file`: result-neutral study overview.
- `dataset`: source, analysis-copy name, formats, key, codebook, metadata, orientation,
  and optional auxiliary dataset.
- `given_solution`: optional fixed artifact that validators must not rederive.
- `additional`: other supplied files with names and result-neutral notes.
- `questions`: file, count, and new-to-original map.
- `held_constants`: definitions file, summary, and QA groups.
- `original`: methodology, withheld results key, model, and vendor.
- `deliverable`: report template, reporting specification, optional method guide.

Prompt placeholders use uppercase braces. Optional blocks use
`{#module}...{/module}` for `aux`, `given_solution`, `additional`, and
`method_guide`. Robustness prompts may tag turns `{mode:discuss}` or
`{mode:nodiscuss}`.

## Existing prototype compatibility

If `rrg.yaml` is absent but `RRG/vp_config.yaml` exists, the CLI normalizes the
prototype manifest automatically. It likewise discovers `RRG/study.yaml`.
Explicit locations are also supported:

```bash
rrg preflight --root /project/root \
  --config RRG/vp_config.yaml --study RRG/study.yaml --stage replication
```

## GUI workspace mode

`rrg gui --workspace PATH` discovers valid `.rrg_root` projects below `PATH`, lets
the operator switch the active project, and can scaffold a new child project. All
project operations remain confined to the selected root. `rrg gui --root PROJECT`
retains locked single-project behavior.
