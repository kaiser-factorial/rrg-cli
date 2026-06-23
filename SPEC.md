# RRG — Research-validation pipeline specification

RRG builds, blinds, and grades staged multi-model validation packages for a piece of
research. The premise: to know whether a result is trustworthy, hand the underlying
data and a fixed set of questions to independent models under controlled information
conditions, then compare what they produce against the held-back original. RRG is the
machinery that prepares those hand-offs correctly, proves nothing leaked, and lays the
findings side by side for a human grader.

This document specifies the whole system — the concepts, the on-disk project, the
`rrg` command-line tool, and the local GUI — in enough detail to operate or extend it.

---

## 1. Core ideas

**The validation ladder.** A study is validated in ordered *stages*, each opening up
more information to the validator and asking a different question of the result:

- **replication** — the validator is given the *original methodology* and must
  reproduce the analysis. Opens at the **model** level (does an independent model,
  following the same method, get the same answer?).
- **robustness** — the validator is given the data and questions but **not** the
  original methodology; it must choose its own defensible analysis. Opens at the
  **method** level (does the conclusion survive a different reasonable method?).
- **generalization** — the validator works a different sample or holdout. Opens at the
  **data** level (does the conclusion hold beyond this dataset?). Off by default until
  a data-variation plan is defined.

Stages are configuration, not code — a project can rename, reorder, disable, or add
them.

**Blinding is per-stage, not global.** The single most important invariant: each stage
has its own list of what it may and may not receive. The original methodology is
*required* in replication and *forbidden* in robustness. The origin report and any
results key are withheld from every stage. Every package is linted against these rules
before it can be published.

**Engine vs. cartridge.** The pipeline is retargetable to any lab. The reusable
**engine** is the `rrg` package (CLI, GUI, prompt scaffolds). The per-study
**cartridge** is two YAML files plus prompt templates and documents. Nothing about a
particular study is hard-coded.

**The operator owns the secrets.** The GUI and CLI are operator-facing tools that can
see everything, including the held-back origin. Safety lives at the *package boundary*:
what gets copied into an outgoing package is what's gated. The GUI never publishes the
origin; it only reads it for review.

---

## 2. Vocabulary

| Term | Meaning |
|---|---|
| **Project** | A self-contained study directory, marked by a `.rrg_root` file. |
| **Engine config** (`rrg.yaml`) | Routing, blinding rules, roster, stages, dispatch. |
| **Study cartridge** (`study.yaml`) | Study identity, dataset, questions, held constants, original work, deliverable spec. |
| **Origin report** | The human- or model-authored work being validated. Held back. |
| **Results key** | The directory holding the origin report + per-question summary. Withheld. |
| **Original methodology** (`ANALYSIS_PROTOCOL_OG.md`) | Result-free reconstruction of the methods; revealed only in replication. |
| **Held constants** | Definitions that must stay fixed across validators (grouping rules, thresholds, etc.). |
| **Roster** | The models assigned to run each stage. |
| **Package** | The exact, linted bundle of files sent to one validator for one stage. |
| **Run** | A validator's returned output folder, under the operator directory. |
| **Scorecard** | A provisional, per-question grading scaffold; final verdicts are human-only. |
| **Workspace** | A directory containing several projects, switchable in one GUI session. |

---

## 3. Project layout

```
my-study/
  .rrg_root                     marker that identifies a project root
  rrg.yaml                      engine config (routing, blinding, roster, stages)
  study.yaml                    study cartridge
  questions_map.yaml            maps new question number -> original number + topic
  data/
    source.csv                  authoritative source dataset
    <main>.csv / .parquet       deterministic, verified derivatives
    <main>.codebook.csv         column codebook (generated)
    <main>.meta.json            conversion metadata + source hash + verification
  shared/                       model-facing inputs (never secret on their own)
    STUDY_OVERVIEW.md
    QUESTIONS.md                model-facing question text
    VALIDATION_INSTRUCTIONS.md  held constants
    ANALYSIS_PROTOCOL_OG.md     original methodology (routed only into replication)
  prompts/
    replication.md robustness.md generalization.md
  operator/                     operator-only side; never sent wholesale
    origin/                     the results key
      ORIGIN_REPORT.pdf         the held-back report
      SUMMARY.md                per-question transcription used by the scorecard
    OG_METHODOLOGY_PROMPT.md    prompt template for drafting the methodology
    private/                    anything else withheld
    _packages/                  published packages + provenance_log.jsonl
    _compare_notes/             operator review notes
    SCORECARD_*.md              generated grading scaffolds
```

Paths are configurable via `rrg.yaml > paths` (`shared`, `data`, `operator`,
`packages`, `compare_notes`). Everything is resolved through a confinement helper that
refuses paths escaping the project root.

---

## 4. Configuration

### 4.1 `rrg.yaml` — engine config

- `project.name` — display name.
- `paths` — directory overrides (see above).
- `origin` — `vendor`, `model`, `results_key`, `source_data`. Identifies who produced
  the original work and where the held-back key lives.
- `files` — the routing registry:
  - `all` — a named token expanding to a list of model-facing inputs.
  - `stage_specific` — list of `{file, send_in: [stages]}` for files routed only into
    certain stages (e.g. the methodology into replication).
  - `withheld` — glob patterns that must never appear in a package.
- `roster` — per stage, a list of `{model, vendor, type, license}`.
- `stages` — per stage: `order`, `enabled`, `opens` (model/method/data),
  `methodology` (revealed/hidden/decide-in-cartridge), `prompt`, `send` (tokens or
  paths), `output_folder`, `report_name`, and `blocked_reason` when disabled.
- `blinding`:
  - `always_withhold` — patterns withheld from every stage.
  - `per_stage_methodology.<stage>` — `require` and `forbid` pattern lists.
  - `result_token_scan` — `source`, `action` (off/flag/fail), `exclude_globs`,
    `ignore_tokens`.
- `constraints` — `exclude_vendors` (a vendor that produced the origin cannot validate
  it), `determinism` (recorded into provenance).
- `dispatch` — `start_template` (with `{model_slug}`) and `model_slugs` (model → slug).

### 4.2 `study.yaml` — cartridge

The cartridge may be wrapped in a top-level `study:` key or flat. Fields:

- `title`, `overview_file`.
- `dataset` — `source`, `main_name`, `merge_key`, `formats`, `codebook`, `metadata`,
  `orientation` (prose with placeholders), and an optional `aux` block.
- `given_solution` — optional fixed/supplied solution (`glossary`, `artifacts`).
- `additional` — extra inputs (`name :: file :: note`).
- `questions` — `file`, `count`, `map`.
- `held_constants` — `file`, `summary`, `qa_groups`.
- `original` — `methodology_file`, `results_key`, `summary_file`,
  `methodology_prompt`, `report_file` (optional), `model`, `vendor`.
- `deliverable` — `report_name`, `reporting_spec`, optional `method_guide`.

---

## 5. End-to-end lifecycle

1. **`rrg init`** scaffolds a project from the template.
2. **Configure** the cartridge and engine config (or the GUI *Setup* tab).
3. **`rrg convert`** turns the authoritative source into verified CSV/Parquet
   derivatives with a codebook and a metadata sidecar that records the source hash and
   a read-back verification of every derivative.
4. **Prepare the origin.** Verify each question is functionally separated across the
   question, methodology, and origin-key documents (GUI *Origin* tab), and draft the
   result-free methodology to reveal in replication.
5. **`rrg preflight`** confirms every referenced input exists, derivatives verify, and
   each enabled stage routes and renders cleanly.
6. **`rrg package --stage … --model …`** assembles the package in staging, lints it
   against the blinding rules, and publishes only if the lint passes (or `--force`,
   recorded). Provenance is written per package and appended to a log.
7. **Dispatch** the delivery zip to the validator and run it **outside the project** so
   the operator's secrets are unreachable; **`rrg import`** brings its returned outputs
   back into `operator/<run>/`.
8. **Review** returned runs (GUI *Runs*), compare validator vs. origin figures per
   question (*Compare*), and record notes.
9. **`rrg scorecard`** generates a provisional, versioned per-question grading scaffold
   for a human to complete. The engine never assigns a final verdict.

---

## 6. CLI reference

All commands accept `--root`, `--config`, `--study` to locate the project, and most
accept `--json`. Exit code `0` = success, `2` = a checked condition failed (not
ready / not verified / blocked / lint failed), `1` = error.

- **`rrg init [path] [--force]`** — create a project from the template.
- **`rrg doctor [--stage S]`** — health inspection (missing deps and inputs are
  warnings).
- **`rrg preflight [--stage S]`** — strict readiness; missing inputs and deps are
  errors. Exit `2` if not ready.
- **`rrg convert [source] [--out] [--formats csv parquet] [--labeled] [--na-token T]
  [--float-format F]`** — convert and verify derivatives. Exit `2` if any derivative
  fails read-back verification.
- **`rrg package --stage S --model M [--label L] [--dry-run] [--force]
  [--allow-unlisted]`** — build, lint, publish. `--dry-run` lints without publishing;
  `--force` publishes despite lint failure (recorded as `forced_override`);
  `--allow-unlisted` permits a model not in the roster. Exit `2` if blocked.
- **`rrg lint <package> --stage S`** — lint an existing package directory.
- **`rrg import <returned> --stage S --model M [--label L]`** — import a validator's
  returned outputs (a folder or `.zip`) into its run folder, with zip-slip protection.
- **`rrg prompt --stage S --model M [--mode discuss|nodiscuss] [--turn N]
  [--include-reminders]`** — render a stage prompt (or a single turn).
- **`rrg scorecard --run R --stage S --model M [--key] [--map] [--out-dir]
  [--license]`** — generate a provisional scorecard.
- **`rrg gui [--workspace DIR] [--port 8765] [--open]`** — launch the local GUI. With
  `--workspace`, enable safe switching among projects beneath that directory.
- **`rrg version`** — print the version.

---

## 7. Blinding and packaging

This is the safety core. Packaging never copies a configured directory wholesale; it
copies exactly the resolved send list, lints it, and only then publishes.

**Routing (`resolve_send`).** A stage's `send` list is expanded: named tokens (e.g.
`all`) expand to their file lists from the registry; bare paths pass through. Any
methodology `require`d for the stage is appended from `stage_specific` if not already
present. Basename collisions are rejected (packages are flat by basename). Directory
inputs are copied recursively.

**Lint (`lint_package`).** Run against the staged package before publish. Checks:

1. **withheld_files** (hard fail) — any path matching `always_withhold` or
   `files.withheld`.
2. **stage_methodology_require** (hard fail) — a required methodology file is missing.
3. **stage_methodology_forbid** (hard fail) — a stage-forbidden methodology file is
   present (e.g. the protocol leaking into robustness).
4. **routing** (hard fail) — the package's files differ from the resolved send list
   (unexpected extras or missing inputs), ignoring `_provenance.json`.
5. **result_token_scan** (flag or hard fail) — decimal-looking values from the results
   key that appear verbatim in package text, minus `ignore_tokens` and
   `exclude_globs`. Severity follows `action`.

A package **passes** when there are no hard fails. Flags are surfaced but do not block.

**Provenance.** On publish, each package gets a `_provenance.json` (files sent, per-file
SHA-256, the prompt file's path and hash, the blinding result and flags, determinism
settings, any forced override, the output folder, and timestamp). The same record is
appended to `operator/_packages/provenance_log.jsonl`, which the GUI reads to mark
which runs were dispatched.

**Isolation (lint guards contents; isolation guards reach).** The lint controls what is
*inside* a package, not what a validator can *reach* on disk. Because the operator
directory holds the secrets (`origin/`, `private/`, scorecards, other runs) and
`shared/ANALYSIS_PROTOCOL_OG.md`, a validator run *inside* the project can simply
traverse to them (`ls ../../../origin/`). So on publish, RRG also writes a
self-contained delivery **zip** (`<package_dir>.zip`, package files only, no
`_provenance.json`). The validator must run on that zip in an environment **separate
from the project** — ideally a container — where the secrets are not reachable. Its
returned outputs come back via `rrg import`, which copies a returned folder or zip into
`operator/<run>/` and rejects any entry that resolves outside the run folder (zip-slip
protection). RRG deliberately does **not** add "don't snoop" instructions to the prompt;
it removes access rather than asking. See `docs/adr/0001-validator-isolation.md`.

---

## 8. Dataset conversion and verification

`convert` reads the authoritative source (CSV/TSV or, via `pyreadstat`, SPSS/Stata/SAS)
and writes the requested derivatives (CSV, Parquet), a column codebook, and a
`.meta.json` sidecar. The sidecar records the source SHA-256 and a per-derivative
verification that reads each output back and confirms it matches the source cell for
cell. `preflight`/`doctor` later re-check that the recorded source hash still matches
and that every derivative verified — so a silently edited source or a stale derivative
is caught before any package is built.

---

## 9. Origin report and methodology drafting

The origin lives in the results key and is withheld from every package; the GUI is the
only place it is read. The *Origin* tab provides three things:

**Per-question separation matrix.** For each question in `questions_map.yaml`, it
checks that an isolated section exists in (a) the model-facing questions file by *new*
number, (b) the original methodology by *new* number, and (c) the origin summary by
*original* number. The origin section is matched the *same way the scorecard extracts
it* (`## Q<n>`), so a question marked "scoreable" here is exactly one the scorecard can
grade on its own. Any question missing a section in any document is flagged as a gap.

**Report viewer.** The origin report PDF is streamed from a token-authenticated,
same-origin endpoint and embedded in an iframe (the browser's native PDF viewer), so
the operator can read the source of truth in place.

**Figure resolution.** Per question, the resolver (`figures.py`) tries, in order:
standalone image files carrying the question number, then images referenced by token in
the question text, then — when no image files exist — the matching figure from the origin
report's PDF appendix, paired to its per-section `Figure`/`Appendix` reference (by number
or letter, content-matched, never by position). Extracting images embedded in a PDF
**requires Pillow**, so the PDF dependency is declared as `pypdf[image]`; without Pillow,
`pypdf`'s image access raises and the appendix branch yields nothing (figures sourced from
image files on disk are unaffected).

**Methodology drafting.** A result-free generation prompt (`OG_METHODOLOGY_PROMPT.md`)
is rendered with the study's questions, held constants, and report filename. The
operator sends it to the origin model (or an origin-author stand-in), pastes the
returned protocol back, and the GUI writes it to the configured methodology file. On
save, a heuristic scans for result-like content (p-values, test statistics, reported
means, counts of significant items, stated conclusions) and warns if the supposedly
result-free protocol appears to leak findings.

---

## 10. Workspace mode

`rrg gui --workspace DIR` confines the GUI to one workspace directory and one active
project at a time. The server discovers every project beneath the workspace (by
`.rrg_root` marker, excluding VCS/data/operator/shared and hidden directories) and lets
the operator switch between them or scaffold a new one. A single lock serializes
project selection and every active-project operation, so a build or setup save can
never run against a switched-out project root. Project creation and selection reject
path traversal and require workspace-relative child paths. Without `--workspace`, the
GUI runs in single-project mode and the workspace surface is disabled.

---

## 11. Scorecards

`scorecard` produces `SCORECARD_<stage>_<label>_v<n>.md`, auto-incrementing the version
and noting the prior one. For each question it lays the validator's material beside the
held-back key material (pulled by the question's *original* number), with a **PENDING**
verdict and a verdict legend (`REPRODUCED`, `CONVERGED`, `DIVERGED`, `INCOMPLETE`,
`GENERALIZES`, `SAMPLE-SPECIFIC`, `N-A`). A blank scaffold is explicitly provisional and
is rejected if it ever contains a final verdict — the engine never grades. When the
operator finalizes a fully-graded run (Review & Grade), the same builder fills the table
with the human-confirmed verdicts and writes the next version. Grading state lives
separately as per-run JSON; a run is "graded" only when every question is confirmed.

---

## 12. The GUI

A single-page app served locally. Tabs:

- **Dashboard** — project-scoped counts (published packages, returned runs, blocking
  preflight issues), per-stage status, and the preflight summary.
- **Convert** — run and verify dataset conversion.
- **Build** — build/lint/publish a package for a stage and model, with a blocker notice
  and dry-run/force options.
- **Prompts** — render a stage prompt; operator reminders are kept visually separate
  from paste-ready turns; supports discussion vs. operator-reviewed-lock mode.
- **Runs** — browse validator output folders (the results key and operator-only
  directories are excluded), with per-file preview.
- **Review & Grade** — the unified review-and-grading surface (replaces the older
  Compare and Scorecards tabs). For a returned run, each question shows: a
  validator-led **statistics comparison** (every stat the validator reported in
  `raw/Q<n>_summary.json`, checked for the same value in the origin's per-question
  material and marked found / not-found, with the stage's expectation noted —
  replication should match exactly, robustness may legitimately differ), an
  **origin-only figures** list (numbers the origin reported that the validator did
  not), the full **DYFA narratives** side by side, the figures, and a **verdict**
  control. A run is graded only when a human confirms a verdict for every question;
  finalizing exports a versioned `SCORECARD_*.md` filled with those verdicts. Draft
  scorecards can be deleted; finalized ones are protected until the run is reopened.
- **Origin** — the separation matrix, content preview, report viewer, and methodology
  drafting (section 9).
- **Projects** — workspace switcher and new-project scaffolding (workspace mode).
- **Setup** — edit the cartridge and engine config, including a per-stage model editor
  (model, vendor, type, license, dispatch slug) and the dispatch start template.
  Unknown YAML fields are preserved on save.

### 12.1 HTTP API

`GET`: `/api/bootstrap`, `/api/workspace`, `/api/preflight`, `/api/prompt`,
`/api/runs`, `/api/run`, `/api/file`, `/api/compare` (per-question figures, stats
comparison, and narratives), `/api/grading` (per-run verdict state), `/api/scorecards`,
`/api/scorecard`, `/api/origin`, `/api/origin/report`,
`/api/origin/report.pdf` (PDF stream), `/api/origin/methodology_prompt`.

`POST`: `/api/convert`, `/api/package`, `/api/scorecard`, `/api/setup`,
`/api/project/select`, `/api/project/create`, `/api/origin/methodology`,
`/api/grading/verdict`, `/api/grading/finalize`, `/api/grading/reopen`,
`/api/grading/delete`, `/api/scorecard/delete`.

**Connection and log hygiene.** Figure payloads are inlined as base64, so `/api/compare`
responses can be large; if the browser cancels an in-flight request (e.g. clicking
through questions quickly), the write target disappears. Response writers swallow
`ConnectionError` so a dropped client doesn't surface as a traceback. Separately, `serve()`
installs a logging filter that drops pypdf's benign `Ignoring wrong pointing object`
cross-reference warnings while leaving every other pypdf warning and all errors intact.

---

## 13. Security model

- **Local only.** The server binds to `127.0.0.1`.
- **Session token.** Every API call requires the `X-RRG-Token` header, injected into the
  page as a meta tag. The PDF stream additionally accepts the token as a query param,
  since an iframe cannot send headers (same-origin, localhost).
- **CSRF.** State-changing `POST`s are refused unless the `Origin` header is a
  localhost origin; request bodies are capped (2 MB).
- **CSP.** A restrictive policy (`default-src 'self'`, no inline anything,
  `frame-ancestors 'none'`); the PDF response relaxes only `frame-ancestors 'self'` so
  the page can frame it.
- **Path confinement.** Every project-relative path is resolved through a helper that
  refuses to escape the project root.
- **Leak surfaces excluded.** The Runs view excludes the results key and
  operator-only directories; the origin is never packaged; the package lint is the
  enforcement boundary.

---

## 14. Extending

**Prompt templates** are markdown with `## Turn N — Title` sections and an optional
`## Operator reminders` block. They use `{TOKEN}` placeholders (resolved from the
cartridge — recursively, since cartridge prose may itself contain tokens) and
`{#module}…{/module}` blocks toggled by cartridge state (`aux`, `given_solution`,
`additional`, `method_guide`). Per-turn `{mode:discuss}` / `{mode:nodiscuss}` tags
filter turns by mode. Rendering fails loudly on any unresolved placeholder, so a
mis-templated prompt cannot reach a validator.

**Adding a stage** is config: add it under `stages`, give it a prompt, a `send` list,
and `per_stage_methodology` rules, and add roster entries. The engine picks it up with
no code change.
