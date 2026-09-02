---
name: rrg-effort-normalizer
description: >
  Transform an Effort research-harness report into an RRG-validation-ready project.
  Scans the report directory, auto-detects the analysis dataset and results CSV,
  classifies the report type (statistical / descriptive / inventory), audits whether
  selected data contains derived answers, detects learned measurement systems, and
  generates a staged RRG project with explicit operator review gates.
  Use as the bridge between Effort reports and the RRG replication/robustness
  validation pipeline.
---

# rrg-effort-normalizer — Effort → RRG project bridge

Transforms an Effort research-harness report into an RRG-validation-ready project
directory. This is the intermediary step between Effort's editorial reports and
RRG's hypothesis-testing validation pipeline.

## Two-step workflow

### Step 1: Programmatic normalization (this skill)

```python
from normalizer import generate_project

result = generate_project(
    report_dir="/path/to/effort-report",
    output_dir="/path/to/output",
)

# → Creates a staged RRG project with all files and operator review gates
# → Runs rrg convert to create verified parquet + codebook + meta.json
# → Saves a custom Effort intake review prompt at prompts/effort_intake_review.md
```

This produces:
- `rrg.yaml`, `study.yaml`, `questions_map.yaml`
- `shared/QUESTIONS.md`, `STUDY_OVERVIEW.md`, `VALIDATION_INSTRUCTIONS.md`, `ANALYSIS_PROTOCOL_OG.md`
- `data/*.csv`, `*.parquet`, `*.codebook.csv`, `*.meta.json`
- `operator/origin/SUMMARY.md`, `report.md`
- `operator/origin/origin.json` (canonical held-back values)
- `shared/METRIC_SPEC.json` (validator-safe IDs, types, and units; never values)
- `shared/ANALYSIS_CONTRACT.json` (result-neutral held constants for robustness)
- `operator/normalization/manifest.json` (selection and answer-column audit)
- `operator/model-evaluations/*.json` when a learned measurement system is detected
- `prompts/effort_intake_review.md` (custom intake review prompt)
- `prompts/replication.md`, `robustness.md`, `generalization.md`

Generation is deliberately fail-closed. Replication remains disabled until the
result-free protocol is reviewed. Robustness remains disabled until the held constants
are approved and a result-neutral input is selected. A detected learned model blocks
all packaging until its operator-side ground-truth evaluation passes declared
acceptance criteria.

### Step 2: Model-assisted intake review (via `rrg intake`)

After programmatic normalization, run the model-assisted intake review:

```bash
# Render the Effort intake review prompt
rrg intake

# (send the rendered prompt to a model — Fable, Claude, etc.)
# The model reviews the auto-generated content against the original report:
#   1. Removes non-question sections from QUESTIONS.md
#   2. Fills in "not reported" fields in SUMMARY.md from the report
#   3. Cross-checks the original report for missed questions
#   4. Outputs corrected SUMMARY.md + corrected_questions YAML block

# Apply the model's response
rrg intake --apply FILE

# If the response includes a corrected_questions block, also run:
python -c "
from normalizer import apply_intake_review
apply_intake_review('/path/to/project', open('FILE').read())
"
# → Updates QUESTIONS.md, questions_map.yaml, and study.yaml question count
```

This step is essential for all report types because:
- **Statistical reports**: the auto-generated SUMMARY.md has correct fields but
  placeholder conclusions ("See origin report"). The intake review fills them from
  the report's prose.
- **Descriptive/inventory reports**: the auto-generated QUESTIONS.md may include
  non-question section headings (methodology, appendices, etc.). The intake review
  removes them and fills the SUMMARY stubs from the report.

The intake model is an operator-side reviewer and may see the origin report. Its
response must never be routed to a validator. After applying it, validate the canonical
origin JSON and public metric specification separately; the public specification may
contain metric shape only, never expected values, tolerances, formulas, or the original
method.

## What the intake review does

The custom Effort intake review prompt asks the model to:

1. **Review QUESTIONS.md for inappropriate content**
   - Remove methodology sections, appendices, data descriptions
   - Add missing research questions the report actually investigates

2. **Review SUMMARY.md against the original report**
   - Fill in "not reported" structured fields from the report
   - Preserve exact numbers, p-values, CIs from the report

3. **Verify completeness**
   - Go through the report section by section
   - Confirm every research-finding section has a corresponding question
   - Flag any missed questions

## Report type handling

### Statistical (e.g. 100b-founders)
- Has `correlations.csv` with p-values, CIs, effect sizes
- SUMMARY.md is auto-generated from the results CSV (all fields filled)
- Intake review fills conclusions and verifies question wording

### Descriptive (e.g. lgbtq-funder-spending, spacex-stakeholders)
- Has amounts, shares, rankings but no p-values
- SUMMARY.md is a stub with "not reported" fields
- Intake review fills fields from the report prose and cleans questions

### Inventory (e.g. race-based-medicaid)
- Has tiers, statuses, dispositions
- SUMMARY.md is a stub
- Intake review fills fields from the report prose and cleans questions

## API

```python
from normalizer import scan_report, find_analysis_csv, find_results_csv, generate_project, apply_intake_review

# Step 1: Programmatic normalization
result = generate_project(
    report_dir="/path/to/effort-report",
    output_dir="/path/to/output",
    # Optional overrides:
    # analysis_csv="data/my_custom.csv",
    # results_csv="data/my_results.csv",
    # project_name="my-project",
    # force=False,  # refuses a non-empty destination unless explicitly true
)

# Step 2: After model returns intake review response
apply_intake_review(
    project_root=result["project_root"],
    intake_text=model_response_text,
)
# → Writes corrected SUMMARY.md, QUESTIONS.md, questions_map.yaml
```

## Required unlock sequence

1. Review `operator/normalization/manifest.json`, especially selected data and
   `derived_or_answer_columns`.
2. Complete the origin intake and canonical `operator/origin/origin.json`.
3. Replace the replication protocol stub with a result-free reviewed protocol.
4. Complete every required `operator/model-evaluations/*.json` against independent
   ground truth. Classification evaluations need ROC AUC or a full confusion matrix;
   continuous evaluations need both error and association metrics.
5. For robustness, select inputs that do not contain origin scores, ranks, shares,
   tiers, dispositions, or other derived answers. Approve only the population, unit of
   analysis, inclusion/exclusion rules, time window, construct definitions, and
   missingness in `shared/ANALYSIS_CONTRACT.json`.
6. Enable the stage only after its gate is satisfied, then run:

   - `rrg doctor` — inspect configuration and pending review gates
   - `rrg preflight --stage <stage>` — strict readiness gate
   - `rrg package --stage <stage> --model <model>` — build the blinded package
   - `rrg dispatch --stage <stage> --model <model> --validator <validator>` — run and import

Never enable robustness by merely hiding `ANALYSIS_PROTOCOL_OG.md`. Hidden methodology
also requires result-neutral input data; otherwise the supplied derived columns reveal
the origin answer or lock the validator into the origin measurement model.
