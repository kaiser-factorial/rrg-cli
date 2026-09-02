# Validation instructions

These definitions are fixed across validation stages.

## Decision policy

- Use a per-test significance threshold of alpha = 0.05 unless the protocol specifies otherwise.
- Report exact p-values where computationally available; do not report a rounded zero.
- Record any multiplicity correction or lack of correction explicitly.
- Do not search for the original report or prior answers.

## Data and missingness

- Use the same inclusion and grouping definitions across all stages.
- Report every derived analysis N.
- Treat `id` as the row identifier and `group` as the fixed grouping variable.

## Machine-readable metric contract

- Read `METRIC_SPEC.json` before analysis and write every listed `validator_path` to
  the corresponding `raw/Q<n>_summary.json`.
- The contract fixes metric identifiers, semantic targets, types, and units only. It
  does not contain origin values, comparison tolerances, formulas, or the original
  method.
- Do not invent a tolerance. Preserve the requested units and report computed numeric
  values without display strings or unit suffixes in the JSON value itself.
- Add a top-level `_units` object to each question summary, keyed by metric id, with
  the exact unit strings from the contract. Every numeric result must be declared in
  the contract; annotations may remain non-numeric.
- In each DYFA F or A subsection, transcribe every metric as a backticked marker in the
  exact form `<metric_id>=<value-or-null> <unit>` so the report can be checked against
  the summary without interpreting prose.
- If a question declares `relations`, they are exact internal accounting identities.
  They do not carry tolerances or origin values and must hold within your own summary.
