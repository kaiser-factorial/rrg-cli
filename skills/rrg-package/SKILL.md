---
name: rrg-package
description: >
  Prepare and verify a project's shared inputs so any stage can be packaged:
  configure the cartridge (study.yaml) and engine (rrg.yaml), convert the source
  data into verified derivatives, and confirm readiness with preflight. Use at the
  start of a validation effort, or whenever the source data, questions, or routing
  changes. The actual per-validator bundle is built later by `rrg package`.
---

# rrg-package — prepare the project's shared inputs (Stage 0)

Gets a project to the point where `rrg package --stage … --model …` can build a
clean, linted bundle for any validator. This skill does **not** assemble the
per-validator package itself — the engine does that from the routing config at
dispatch time. Here you establish and verify the inputs that routing draws from.

> **Engine vs. cartridge.** Nothing study-specific is hardcoded. The reusable engine
> is the `rrg` CLI; the per-study cartridge is `rrg.yaml` (routing, blinding, roster,
> stages) + `study.yaml` (dataset, questions, held constants, original work,
> deliverable) plus the prompt templates and model-facing docs. This skill edits the
> cartridge and verifies it; it never edits the engine.

## What "the shared inputs" are

Resolved from `rrg.yaml`, not enumerated by hand:

- **`files.all`** — the named token expanding to the model-facing inputs every stage
  receives (study overview, questions, validation instructions, and the data
  derivatives).
- **`files.stage_specific`** — files routed only into certain stages (e.g. the
  original methodology, sent only in replication).
- **`files.withheld` / `blinding.always_withhold`** — glob patterns that must never
  reach any package (the origin/results key, scorecards, operator-private files).
- **The data derivatives** under `paths.data` — produced and verified by `rrg convert`.

When you need the concrete file list for the current project, read it from
`rrg.yaml > files` rather than assuming names — different projects (and the
LoveSmarter vs. MovieRatings conventions) use different basenames.

## Procedure

1. **Scaffold or locate the project.** `rrg init PATH` for a new study, or work inside
   an existing project (discovered via `$RRG_PROJECT_ROOT` → nearest `.rrg_root`
   ancestor → cwd). Confirm `.rrg_root`, `rrg.yaml`, and `study.yaml` are present.
2. **Fill the cartridge.** Set `study.yaml` (dataset `source`/`main_name`/`formats`,
   `questions`, `held_constants`, `original`, `deliverable`) and the model-facing docs
   under `paths.shared`. Set `rrg.yaml > files`, `roster`, `stages`, and `blinding` to
   match. The GUI *Setup* tab does the same edits and preserves unknown YAML fields.
3. **Convert the source to verified derivatives:** `rrg convert [SOURCE]`. The
   authoritative source is the single source of truth — convert it **once**,
   deterministically, and ship the derivatives so no validator converts in-run (that
   would make conversion a per-model degree of freedom → drift). See *Conversion* below.
4. **Confirm separation of the origin.** Each question must be functionally isolated
   across the questions file (by new number), the methodology (by new number), and the
   origin summary (by original number) — the GUI *Origin* tab's separation matrix checks
   this the same way the scorecard later extracts (`## Q<n>`). A question flagged here is
   one the scorecard can't grade cleanly.
5. **Gate on preflight:** `rrg preflight [--stage S]`. It is strict — every referenced
   input must exist, every derivative must still verify against the recorded source
   hash, and each enabled stage must route and render its prompt cleanly. Exit `2` means
   not ready; fix before packaging. (`rrg doctor` is the softer, warning-only version
   for a quick health read.)
6. **Hand off** to the stage-prep skills (`rrg-replication`, `rrg-robustness`), which
   call `rrg package` for a specific `{stage, model}` — that command stages the resolved
   send list, runs the blinding lint, and publishes only on PASS.

## Conversion (`rrg convert`)

The engine is format-agnostic so it can validate any lab's analysis, not just SPSS
ones.

- **Reads** the authoritative source: CSV/TSV, or (via `pyreadstat`) SPSS `.sav/.zsav`,
  Stata `.dta`, SAS — with value/variable labels and missing-value metadata.
- **Writes** the requested derivatives (`--formats csv parquet`), a column codebook,
  and a `.meta.json` sidecar. CSV is universal/human-readable (best for exploring);
  Parquet is typed and language-agnostic via Arrow (best analysis companion). Ship both.
- **Verification:** each derivative is read back and compared to the source cell for
  cell (NaN pattern, max numeric diff, strings); Parquet matches exactly, CSV to float
  precision. Results land in the sidecar's verification block.
- **Provenance:** the sidecar records the **source SHA-256** — the anchor proving the
  derivative came from this exact source. `preflight`/`doctor` later re-check that the
  hash still matches, so a silently edited source or a stale derivative is caught before
  any package is built.

Exit `2` from `rrg convert` means a derivative failed read-back — do not package until
it's green.

## Notes

- This skill never assembles a per-validator package and never decides routing — that
  lives in `rrg.yaml > stages.<stage>.send` and is executed by `rrg package`.
- Keep the measurement/given-solution artifact (if the study has one, `study.yaml >
  given_solution`) fixed across all stages and models — only its form changes with the
  study, not per run.
- The shared inputs are identical for every validator of a stage — uniformity is an
  experimental control. Per-stage differences (e.g. the methodology in replication) come
  from `stage_specific`, not from editing the shared core.
