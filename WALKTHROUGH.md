# RRG Walkthrough — Start to Finish

This guide walks you through running the RRG validation pipeline from scratch:
given a dataset and a research report, you'll set up a project, blind the
inputs, dispatch a validator model, import its results, and evaluate.

**Prerequisites:** `rrg-cli` installed (see [README](README.md#install)) and at
least one validator CLI installed (Hermes, Claude Code, Codex, Grok, or Poolside).

---

## Overview: the validation ladder

RRG validates a finding by opening one degree of freedom at a time:

| Stage | What changes | What stays fixed | What it tests |
|-------|-------------|------------------|---------------|
| Replication | Model + software | Questions, data, method | Computational reproducibility |
| Robustness | Model + method | Questions, data | Survival under another defensible method |
| Generalization | Data | Questions, definitions | Survival beyond the original sample |

Each stage is a separate dispatch — you run them in order.

---

## Step 1: Create a project

```bash
rrg init my-validation
cd my-validation
```

This scaffolds a project from the template:

```
my-validation/
├── .rrg_root                    ← project marker
├── rrg.yaml                     ← engine config (stages, roster, blinding)
├── study.yaml                   ← study cartridge (dataset, questions, deliverables)
├── questions_map.yaml           ← maps pipeline Q# → original Q#
├── data/
│   └── source.csv               ← replace with your dataset
├── shared/                      ← model-facing inputs (validators see these)
│   ├── STUDY_OVERVIEW.md        ← result-neutral study description
│   ├── QUESTIONS.md             ← the validation questions
│   ├── VALIDATION_INSTRUCTIONS.md ← held-constant definitions
│   └── ANALYSIS_PROTOCOL_OG.md  ← original methodology (replication only)
├── prompts/                     ← stage prompt templates
│   ├── replication.md
│   ├── robustness.md
│   └── generalization.md
└── operator/                    ← operator-only (never sent to validators)
    ├── origin/                  ← the held-back answer key
    │   ├── README.md
    │   └── SUMMARY.md           ← per-question transcription of the origin report
    ├── private/                 ← anything else withheld
    └── OG_METHODOLOGY_PROMPT.md ← prompt for drafting the methodology
```

---

## Step 2: Bring your data

Place your source dataset in `data/`:

```bash
cp /path/to/your_data.csv data/source.csv
```

Supported formats: CSV/TSV, or (via pyreadstat) SPSS `.sav`, Stata `.dta`, SAS.

Then convert it to verified derivatives:

```bash
rrg convert
```

This creates `data/analysis.csv`, `data/analysis.parquet`, `data/analysis.codebook.csv`,
and `data/analysis.meta.json` — all cell-for-cell verified against the source. The
metadata file records the source hash so future checks catch any tampering.

Update `study.yaml` > `dataset` to match your file:
- `source`: path to the source file (e.g. `data/source.csv`)
- `main_name`: the base name for derivatives (e.g. `analysis`)
- `merge_key`: the row identifier column (if any)
- `formats`: output formats (`csv`, `parquet`)

---

## Step 3: Place the origin report

The origin report is the work being validated. It is **withheld** from validators —
they never see it. Place it in the operator-only area:

```bash
cp /path/to/origin_report.pdf operator/origin/ORIGIN_REPORT.pdf
```

Or if it's a markdown file:

```bash
cp /path/to/origin_report.md operator/origin/ORIGIN_REPORT.md
```

Then add the report filename to `rrg.yaml` > `blinding.always_withhold` so it's
never accidentally packaged:

```yaml
blinding:
  always_withhold:
    - origin/
    - ORIGIN_REPORT.pdf
    - ORIGIN_REPORT.md
```

---

## Step 4: Generate the model-facing documents

RRG can automate most of the document creation from the dataset codebook and
the origin report. Check what's needed:

```bash
rrg setup --status
```

### 4a. Extract questions from the origin report

```bash
rrg setup --questions                    # render the extraction prompt
# send it to a model (e.g. via hermes -z):
hermes -z "$(rrg setup --questions)"     # prints the numbered question list
# apply the result:
rrg setup --apply-questions extracted_questions.txt
```

This also auto-generates `questions_map.yaml` and updates `study.yaml` with the
question count. If the report uses its own numbering (e.g. Q1, Q4, Q7), the
original numbers are preserved in the map.

### 4b. Generate the study overview

```bash
rrg setup --overview                     # render the prompt (includes codebook context)
# send to model:
hermes -z "$(rrg setup --overview)"
# apply:
rrg setup --apply-overview generated_overview.md
```

The generated overview includes the dataset structure (rows, columns, value labels
from the codebook). `<!-- HUMAN: ... -->` comments mark where you should add context
the codebook can't provide (study motivation, theoretical framework).

### 4c. Generate validation instructions

```bash
rrg setup --instructions                 # render the prompt (includes value labels)
# send to model:
hermes -z "$(rrg setup --instructions)"
# apply:
rrg setup --apply-instructions generated_instructions.md
```

The generated instructions extract group definitions from the codebook's value
labels (e.g. "Gender: 1 (female) vs 2 (male); exclude 3 and missing"). The alpha
level and multiplicity policy are left as `<!-- HUMAN: ... -->` placeholders.

### 4d. Generate the analysis protocol

The `ANALYSIS_PROTOCOL_OG.md` is a result-free reconstruction of the methods.
Generate it from the origin report:

```bash
rrg intake                    # renders the methodology-drafting prompt
# send to model, then apply:
rrg intake --apply returned_protocol.md
```

### 4e. Transcribe the origin results

The `operator/origin/SUMMARY.md` is the held-back answer key — per-question
transcription of the origin report's findings.

```bash
rrg intake --check            # is intake needed?
rrg intake --simplified       # render the simplified intake prompt
# send to model, then apply:
rrg intake --apply returned_intake.md
```

### 4f. Review everything

All generated docs should be reviewed by a human. The model can extract questions
wrong, miss group definitions, or get the methodology slightly off. The blinding
lint and preflight will catch structural issues, but not content errors.

```bash
rrg preflight                 # verify everything is wired correctly
```

---

## Step 5: Configure the roster

---

## Step 6: Configure the roster

Edit `rrg.yaml` > `roster` to list which validator models will run each stage:

```yaml
roster:
  replication:
    - model: default           # "default" = use the validator's own default model
      validator: hermes         # which CLI agent to use (hermes/claude/codex/grok/pool)
      vendor: Alibaba
      type: open
      license: Apache-2.0
  robustness:
    - model: default
      validator: grok
      vendor: xAI
      type: frontier
      license: proprietary
```

Set `constraints.exclude_vendors` to the origin's vendor so it can't validate
its own work:

```yaml
constraints:
  exclude_vendors: [Anthropic]  # if the origin was Claude
```

---

## Step 7: Check readiness

```bash
rrg doctor      # soft check (warnings only)
rrg preflight   # strict check (errors block dispatch)
```

Or use the interactive wizard:

```bash
rrg wizard --non-interactive
# or interactively:
rrg tui
```

Preflight verifies: all inputs exist, derivatives verify against the source,
every enabled stage routes and renders its prompt cleanly.

---

## Step 8: Dispatch a replication run

```bash
# Manual: builds the package, prints instructions
rrg dispatch --stage replication --model "default"

# Automated: runs the validator via the CLI agent, auto-imports results
rrg dispatch --stage replication --model "default" --validator hermes --mode agent

# With a specific model:
rrg dispatch --stage replication --model "Qwen 3.7 Max" --validator hermes
```

**Validators:** `manual`, `hermes`, `claude`, `codex`, `grok`, `pool`, `openrouter`

**Modes:** `discuss` (human reviews each turn), `nodiscuss` (no discussion turns),
`agent` (built-in operator responses drive the discuss loop)

The dispatch command:
1. Builds the blinded package zip (blinding lint blocks if secrets leak)
2. Extracts it to a temp dir outside the project (isolation)
3. Sends the prompt turns to the validator via the chosen CLI
4. Runs the deterministic deliverable gates on the work dir; if the structure
   deviates (misnamed files, missing summary keys, `p_value: 0`, missing DYFA
   labels, ...) it sends the coded violation list back as a revision turn and
   re-checks, up to `--gate-revisions N` times (default 1; `--no-gates` to skip)
5. Auto-imports the validator's output back into the project, writing `GATES.json`
6. Auto-normalizes non-conforming file names
7. Checks for blinding breaches (hash comparison against the answer key)

Exit code `3` means the gates still failed after the last revision — the files were
imported anyway; read `GATES.json` in the run folder for the remaining violations.

---

## Step 9: Evaluate the run

```bash
# Pipeline metrics (contract + breach + grading status)
rrg eval --run operator/replication_hermes_qwen-3.7-max_2026-08-10__3a4c7025
```

Or use the rrg-eval skill to do a full scientific evaluation:

1. Create `evals/COMPARISON.md` — per-question comparison table with verdicts
2. Create `evals/DIVERGENCES.md` — detailed analysis of any divergences
3. Independently verify stats by running the protocol-specified tests yourself
4. Compare origin vs validator DYFA sections for each divergence

See `skills/rrg-eval/SKILL.md` for the full methodology.

---

## Step 10: Grade (human-only)

```bash
rrg scorecard --run <run_folder> --stage replication --model "default"
```

The scorecard lays each validator result beside the origin key with a PENDING
verdict. **The engine never assigns a final verdict — a human confirms every
one.** Verdict vocabulary: REPRODUCED, CONVERGED, DIVERGED, INCOMPLETE, N/A.

---

## Step 11: Dispatch robustness

Once replication is graded, run robustness (the validator designs its own
method, blind to the original):

```bash
rrg dispatch --stage robustness --model "default" --validator grok --mode agent
```

In robustness, the methodology is **hidden** — the validator gets the data
and questions but not `ANALYSIS_PROTOCOL_OG.md`. It must choose its own
defensible analysis method.

---

## Step 12: Review cross-model results

```bash
rrg runs    # list all runs with their status
rrg eval --run <run_folder>  # per-run metrics
```

Compare validators against each other and the origin:
- Same method, same answer → REPRODUCED
- Different method, same conclusion → CONVERGED
- Different conclusion → DIVERGED (investigate)

---

## Quick reference: the full cycle

```
rrg init my-validation && cd my-validation
rrg convert                                    # verify data derivatives
# ... edit rrg.yaml, study.yaml, shared/, operator/origin/ ...
rrg preflight                                  # readiness gate
rrg dispatch --stage replication --model "default" --validator hermes --mode agent
rrg eval --run <run_folder>                    # pipeline metrics
# ... run rrg-eval skill for scientific comparison ...
rrg scorecard --run <run_folder> --stage replication --model "default"
# ... human grades ...
rrg dispatch --stage robustness --model "default" --validator grok --mode agent
# ... repeat eval + grading ...
```

---

## Tips

- **Save your defaults** so you don't type the flags every time:
  ```bash
  rrg prefs --set validator=hermes
  rrg prefs --set mode=agent
  ```

- **Create aliases** for quick dispatch:
  ```bash
  rrg alias grok-val grok
  rrg alias --install  # writes ~/.rrg_aliases.sh
  source ~/.rrg_aliases.sh
  # Now: grok-val --stage replication --model "default"
  ```

- **Launch the TUI** for an interactive walkthrough:
  ```bash
  rrg tui
  ```

- **Model "default"** means the validator uses its own configured model
  (e.g. Hermes uses `qwen/qwen3.7-max`, Grok uses `grok-4.5`, Codex uses
  `gpt-5.6-terra`). The actual model is captured from JSON output for
  provenance and run folder naming.

- **Run folder naming:** `{stage}_{validator}_{model}_{date}__{run_id}`
  e.g. `replication_hermes_qwen-3.7-max_2026-08-10__3a4c7025`

- **RUN_INFO.md** is auto-written to every run folder on import with the
  full configuration (validator, model, run ID, breach status, etc.)

- **The evals/ subdirectory** is created in the run folder after evaluation:
  - `COMPARISON.md` — per-question comparison table
  - `DIVERGENCES.md` — detailed analysis of any non-reproduced questions
