"""
Effort → RRG Normalizer

Transforms an Effort research-harness report into an RRG-validation-ready project.

Given an Effort report directory, it:
  1. Scans for report.md, data CSVs, methodology files, validation summaries
  2. Auto-detects the report structure (questions, results, methodology)
  3. Generates a complete RRG project directory with all required files

Supports three report archetypes:
  - statistical: has p-values, CIs, effect sizes (e.g. 100b-founders)
  - descriptive: has amounts, shares, rankings (e.g. lgbtq-funder-spending)
  - inventory: has counts, program records, dispositions (e.g. race-based-medicaid)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import hashlib
from pathlib import Path
from typing import Any

import pandas as pd


# ---------------------------------------------------------------------------
# Report scanning
# ---------------------------------------------------------------------------

_REPORT_EXCLUDES = {
    "navigator.html", "interactive_graph.html", "report-desktop.html", "report-mobile.html"
}


def _select_report_file(report_dir: Path, suffix: str) -> Path | None:
    """Choose the authored report, including named files inside ``deliverable/``."""
    candidates = [
        path for path in report_dir.rglob(f"*{suffix}")
        if path.is_file()
        and path.name.lower() not in _REPORT_EXCLUDES
        and not any(part in {"entity-graph", "research", "sources", "node_modules"} for part in path.parts)
    ]
    if not candidates:
        return None

    def score(path: Path) -> tuple[int, int, str]:
        relative = path.relative_to(report_dir)
        points = 0
        if relative == Path(f"report{suffix}"):
            points += 100
        if "deliverable" in relative.parts:
            points += 60
        if report_dir.name.lower() in path.stem.lower():
            points += 30
        if "report" in path.stem.lower():
            points += 20
        return points, -len(relative.parts), str(relative)

    return max(candidates, key=score)

def scan_report(report_dir: str | Path) -> dict[str, Any]:
    """Scan an Effort report directory and return a structural manifest."""
    report_dir = Path(report_dir)
    manifest: dict[str, Any] = {
        "dir": str(report_dir),
        "name": report_dir.name,
        "report_md": None,
        "report_html": None,
        "methodology_md": None,
        "validation_summary": None,
        "data_csvs": [],
        "data_jsons": [],
        "charts": [],
        "scripts": [],
        "research_dir": None,
        "headings": [],
        "report_type": "unknown",
    }

    # Find report files. Effort deliverables are often named after the investigation
    # rather than literally ``report.html``.
    report_md = _select_report_file(report_dir, ".md")
    report_html = _select_report_file(report_dir, ".html")
    manifest["report_md"] = str(report_md) if report_md else None
    manifest["report_html"] = str(report_html) if report_html else None

    # Find methodology
    for name in ("methodology.md",):
        p = report_dir / name
        if p.is_file():
            manifest["methodology_md"] = str(p)

    # Find validation summary
    for pattern in ("**/validation_summary.json", "**/investigation.json"):
        for p in report_dir.glob(pattern):
            manifest["validation_summary"] = str(p)
            break

    # Find research directory
    rd = report_dir / "research"
    if rd.is_dir():
        manifest["research_dir"] = str(rd)

    # Also check source_memos
    sm = report_dir / "research" / "source_memos"
    if sm.is_dir():
        manifest["source_memos_dir"] = str(sm)

    # Find all CSVs
    for p in sorted(report_dir.rglob("*.csv")):
        rel = p.relative_to(report_dir)
        if any(skip in str(rel) for skip in ("raw/", "transcripts/", "scoring_texts/", "entity-graph/")):
            continue
        try:
            df = pd.read_csv(p, nrows=1)
            manifest["data_csvs"].append({
                "path": str(rel),
                "abs": str(p),
                "rows": pd.read_csv(p).shape[0],
                "cols": df.shape[1],
                "columns": list(df.columns),
            })
        except Exception:
            pass

    # Find JSONs
    for p in sorted(report_dir.rglob("*.json")):
        rel = p.relative_to(report_dir)
        if "raw/" in str(rel):
            continue
        manifest["data_jsons"].append(str(rel))

    # Find charts/figures
    for ext in ("*.png", "*.svg", "*.jpg", "*.jpeg", "*.pdf"):
        for p in sorted(report_dir.rglob(ext)):
            rel = p.relative_to(report_dir)
            if "research/" in str(rel) or "raw/" in str(rel):
                continue
            manifest["charts"].append(str(rel))

    # Parse headings from report.md
    if manifest["report_md"]:
        with open(manifest["report_md"], encoding="utf-8", errors="ignore") as f:
            text = f.read()
        manifest["report_chars"] = len(text)
        for line in text.split("\n"):
            if line.startswith("#"):
                manifest["headings"].append(line.strip())

    elif manifest["report_html"]:
        text = Path(manifest["report_html"]).read_text(encoding="utf-8", errors="ignore")
        manifest["report_chars"] = len(text)
        for level, body in re.findall(r"<h([1-6])[^>]*>(.*?)</h\1>", text, re.IGNORECASE | re.DOTALL):
            title = re.sub(r"<[^>]+>", "", body)
            title = re.sub(r"\s+", " ", title).strip()
            if title:
                manifest["headings"].append("#" * int(level) + " " + title)

    # Classify report type
    manifest["report_type"] = classify_report(manifest)

    return manifest


def classify_report(manifest: dict[str, Any]) -> str:
    """Classify the report type from its structure."""
    headings_text = " ".join(manifest.get("headings", [])).lower()
    csv_columns = []
    for c in manifest.get("data_csvs", []):
        csv_columns.extend(c.get("columns", []))
    cols_lower = [c.lower() for c in csv_columns]

    # Statistical: has p-values, effect sizes, CIs
    has_p = any("p_value" in c or "pvalue" in c or "q_value" in c for c in cols_lower)
    has_effect = any("effect" in c or "statistic" in c or "icc" in c or "spearman" in c or "correlation" in c for c in cols_lower)
    has_ci = any("ci" in c and "95" in c for c in cols_lower)

    if has_p and (has_effect or has_ci):
        return "statistical"

    # Inventory: has tier or disposition in MAIN data tables (not just auxiliary)
    # Count how many CSVs have these columns
    inventory_csvs = 0
    for c in manifest.get("data_csvs", []):
        cols = [col.lower() for col in c.get("columns", [])]
        if any("tier" in col for col in cols) or any("disposition" in col for col in cols):
            # Exclude auxiliary files (API ecosystem, source ledger)
            if not any(skip in c["path"].lower() for skip in ("api_", "source_", "endpoint", "domain")):
                inventory_csvs += 1

    # Check headings for inventory keywords
    has_inventory_heading = any(kw in headings_text for kw in ("inventory", "candidate disposition", "scope test", "search procedure"))

    if inventory_csvs >= 1 and (has_inventory_heading or inventory_csvs >= 2):
        return "inventory"

    # Descriptive: has amounts, shares, rankings
    has_amount = any("amount" in c for c in cols_lower)
    has_share = any("share" in c or "percent" in c for c in cols_lower)
    has_rank = any("rank" in c for c in cols_lower)

    if has_amount or has_share or has_rank:
        return "descriptive"

    return "unknown"


def find_analysis_csv(manifest: dict[str, Any]) -> dict[str, Any] | None:
    """Auto-detect the best analysis-level CSV from the report.

    The "analysis CSV" is the table a validator would use to re-derive findings.
    Prefers:
      - statistical: CSVs with score + outcome columns, prefer "no_shared" variants
      - descriptive: CSVs with organization + year + amount columns (panel data)
      - inventory: CSVs with program/tier/status columns
    Excludes: raw/, evidence/, source_ledger, coverage, rejection files
    """
    csvs = manifest.get("data_csvs", [])
    if not csvs:
        return None

    # Exclude clearly non-analysis files
    EXCLUDE_PATTERNS = ("raw/", "evidence/", "source_ledger", "source-ledger",
                       "coverage", "rejection", "rejected", "candidate",
                       "api_", "endpoint", "layout_audit", "manifest",
                       "readme", "validation_summary", "chart_",
                       "filing_coverage", "domain_ecosystem",
                       "entity-graph/", "edges", "nodes",
                       "research/", "ocr", "lookthrough")
    candidates = [
        c for c in csvs
        if not any(pat in c["path"].lower() for pat in EXCLUDE_PATTERNS)
    ]
    if not candidates:
        candidates = csvs

    report_type = manifest["report_type"]

    if report_type == "statistical":
        # Prefer CSVs with score + outcome columns
        scored = []
        for csv in candidates:
            cols = [c.lower() for c in csv["columns"]]
            has_scores = any("score_100" in c or "score" in c for c in cols)
            has_outcome = any("valuation" in c or "founding" in c for c in cols)
            has_grouping = any("founder_id" in c or "company_id" in c or "company_slug" in c for c in cols)
            if has_scores and has_outcome and has_grouping:
                # Prefer "no_shared" variants (sensitivity analysis excluding shared interviews)
                is_no_shared = "no_shared" in csv["path"].lower()
                scored.append((csv, is_no_shared))

        if scored:
            # Sort: prefer no_shared=True, then more rows
            scored.sort(key=lambda x: (not x[1], -x[0]["rows"]))
            return scored[0][0]

    if report_type == "descriptive":
        # Prefer CSVs with name/org + time + amount/value/shares (panel/ledger data)
        panel_candidates = []
        for csv in candidates:
            cols = [c.lower() for c in csv["columns"]]
            has_entity = any(kw in c for c in cols for kw in ("organization", "funder", "name", "stakeholder", "holder"))
            has_time = any(kw in c for c in cols for kw in ("year", "as_of", "date"))
            has_value = any(kw in c for c in cols for kw in ("amount", "total", "value", "shares", "score"))
            if has_entity and has_time and has_value and csv["rows"] > 5:
                panel_candidates.append(csv)

        if panel_candidates:
            # Prefer the one with the most rows (richest data)
            panel_candidates.sort(key=lambda c: c["rows"], reverse=True)
            return panel_candidates[0]

        # Fallback: ranking CSV
        for csv in candidates:
            cols = [c.lower() for c in csv["columns"]]
            if "rank" in cols and any("amount" in c or "total" in c for c in cols):
                return csv

    if report_type == "inventory":
        # Prefer CSVs with program/tier/status
        for csv in candidates:
            cols = [c.lower() for c in csv["columns"]]
            if any("tier" in c or "program" in c for c in cols) and "status" in cols:
                return csv
        # Fallback: file named "program-inventory" or similar
        for csv in candidates:
            if "inventory" in csv["path"].lower() or "program" in csv["path"].lower():
                return csv

    # Last resort: the CSV with the most rows (likely the main data table)
    return max(candidates, key=lambda c: c["rows"]) if candidates else None

# ---------------------------------------------------------------------------
# Results CSV detection
# ---------------------------------------------------------------------------

def find_results_csv(manifest: dict[str, Any]) -> dict[str, Any] | None:
    """Auto-detect the structured results CSV (statistical test results).

    The "results CSV" has one row per (question, trait) with p-values, effect
    sizes, and confidence intervals — the summary-level statistical findings.

    Returns None for descriptive/inventory reports (no structured test results).
    """
    csvs = manifest.get("data_csvs", [])
    if not csvs:
        return None

    # Only statistical reports have structured results
    if manifest["report_type"] != "statistical":
        return None

    # Look for CSVs with both "question"/"family" and "p_value" columns
    candidates = []
    for csv in csvs:
        cols_lower = [c.lower() for c in csv["columns"]]
        has_question = "question" in cols_lower or "family" in cols_lower
        if has_question and "p_value" in cols_lower:
            # Exclude raw/ and auxiliary files
            if any(skip in csv["path"].lower() for skip in ("raw/", "source_ledger", "coverage")):
                continue
            is_no_shared = "no_shared" in csv["path"].lower()
            candidates.append((csv, is_no_shared))

    if not candidates:
        return None

    # Prefer "no_shared" variants (sensitivity analysis), then more rows
    candidates.sort(key=lambda x: (not x[1], -x[0]["rows"]))
    return candidates[0][0]


# ---------------------------------------------------------------------------
# Stage-safe contracts
# ---------------------------------------------------------------------------

PUBLIC_SPEC_SCHEMA = "rrg.metric-specs.v1"
ORIGIN_RESULTS_SCHEMA = "rrg.origin-results.v1"
MODEL_EVALUATION_SCHEMA = "rrg.model-evaluation.v1"


def _slug(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", str(value).strip().lower()).strip("_")
    return text or "metric"


def _json_number(value: Any) -> int | float | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return int(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _result_columns(df: pd.DataFrame) -> list[tuple[str, str, str]]:
    """Return (source column, semantic kind, unit) in stable comparison order."""
    available = set(df.columns)
    choices = [
        (("n", "n_companies", "n_founders", "n_rows"), "count", "count"),
        (("effect", "estimate", "value", "statistic"), "scalar", "1"),
        (("p_value",), "p_value", "probability"),
        (("q_value", "adjusted_p_value"), "p_value", "probability"),
        (("ci95_low", "ci_low"), "scalar", "1"),
        (("ci95_high", "ci_high"), "scalar", "1"),
    ]
    result: list[tuple[str, str, str]] = []
    for candidates, kind, unit in choices:
        match = next((name for name in candidates if name in available), None)
        if match:
            result.append((match, kind, unit))
    return result


def generate_metric_contracts(
    manifest: dict[str, Any], results_csv_info: dict[str, Any] | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a value-free public schema and a separate operator-only answer key."""
    public: dict[str, Any] = {"schema_version": PUBLIC_SPEC_SCHEMA, "questions": {}}
    origin: dict[str, Any] = {"schema_version": ORIGIN_RESULTS_SCHEMA, "questions": {}}
    if not results_csv_info:
        question_count = max(
            1,
            len(
                [
                    heading for heading in manifest.get("headings", [])
                    if heading.startswith("## ") and not heading.startswith("### ")
                ][:10]
            ),
        )
        for question in range(1, question_count + 1):
            public["questions"][str(question)] = {"metrics": []}
            origin["questions"][str(question)] = {"metrics": {}}
        return public, origin

    df = pd.read_csv(results_csv_info["abs"])
    group_col = next((column for column in ("question", "family") if column in df.columns), None)
    if not group_col:
        return public, origin
    columns = _result_columns(df)
    for question_number, question_value in enumerate(df[group_col].drop_duplicates(), 1):
        rows = df[df[group_col] == question_value]
        public_metrics: list[dict[str, Any]] = []
        origin_metrics: dict[str, dict[str, Any]] = {}
        used: set[str] = set()
        for row_number, (_, row) in enumerate(rows.iterrows(), 1):
            subresult = row.get("trait", row.get("subgroup", row.get("label", "")))
            prefix = _slug(subresult) if str(subresult).strip() and not pd.isna(subresult) else ""
            for source_column, kind, unit in columns:
                metric_id = _slug(f"{prefix}_{source_column}" if prefix else source_column)
                if metric_id in used:
                    metric_id = f"{metric_id}_{row_number}"
                used.add(metric_id)
                label_prefix = f"{str(subresult).strip()} " if prefix else ""
                public_metrics.append(
                    {
                        "id": metric_id,
                        "label": f"{label_prefix}{source_column.replace('_', ' ')}".strip(),
                        "validator_path": metric_id,
                        "kind": kind,
                        "unit": unit,
                        "nullable": bool(pd.isna(row.get(source_column))),
                    }
                )
                numeric = _json_number(row.get(source_column))
                origin_metrics[metric_id] = {
                    "value": numeric,
                    "unit": unit,
                    "display": "" if numeric is None else str(row.get(source_column)),
                    "source": f"{results_csv_info['path']} row {row_number} column {source_column}",
                }
        public["questions"][str(question_number)] = {"metrics": public_metrics}
        origin["questions"][str(question_number)] = {"metrics": origin_metrics}
    return public, origin


def _tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for child in sorted(item for item in path.rglob("*") if item.is_file() and "__pycache__" not in item.parts):
        digest.update(str(child.relative_to(path)).encode("utf-8"))
        digest.update(child.read_bytes())
    return digest.hexdigest()


def detect_derived_models(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Conservatively identify code bundles that create research variables."""
    root = Path(manifest["dir"])
    research = root / "research"
    if not research.is_dir():
        return []
    models: list[dict[str, Any]] = []
    for path in sorted(item for item in research.rglob("*") if item.is_dir()):
        normalized = path.name.lower().replace("_", "-")
        if "agent" not in normalized and "model" not in normalized:
            continue
        files = [item for item in path.rglob("*") if item.is_file() and "__pycache__" not in item.parts]
        if not files:
            continue
        evidence_names = " ".join(item.name.lower() for item in files)
        evidence_text = ""
        for candidate in (path / "README.md", path / "METHOD.md"):
            if candidate.is_file():
                evidence_text += " " + candidate.read_text(encoding="utf-8", errors="ignore")[:20_000].lower()
        learned_signal = (
            any(token in normalized for token in ("personality", "classifier", "predict", "scor", "model"))
            or any(token in evidence_names for token in ("scoring_prompt", "model_review", "predict", "inference"))
            or bool(re.search(r"\b(?:model|classifier|prediction|continuous scores?)\b", evidence_text))
        )
        if not learned_signal:
            continue
        task_type = "continuous" if any(
            token in normalized for token in ("personality", "score", "regression")
        ) else "custom"
        model_id = _slug(normalized).replace("_", "-")
        models.append(
            {
                "id": model_id,
                "role": "feature_generator",
                "task_type": task_type,
                "source": str(path.relative_to(root)),
                "artifact_sha256": _tree_hash(path),
                "evaluation_file": f"operator/model-evaluations/{model_id}.json",
                "required": True,
            }
        )
    return models


_DERIVED_COLUMN_PATTERNS = re.compile(
    r"(?:^|_)(?:model|prediction|score|rank|share|percent|effect|statistic|p_value|q_value|"
    r"ci(?:95)?_(?:low|high)|tier|disposition|classification)(?:_|$)",
    re.IGNORECASE,
)


def analyze_robustness_readiness(
    manifest: dict[str, Any],
    analysis_csv_info: dict[str, Any] | None,
    derived_models: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    models = derived_models if derived_models is not None else detect_derived_models(manifest)
    columns = list((analysis_csv_info or {}).get("columns", []))
    derived_columns = sorted(column for column in columns if _DERIVED_COLUMN_PATTERNS.search(column))
    reasons: list[str] = []
    if models:
        reasons.append("A derived model creates analysis variables and needs independent evaluation plus raw robustness inputs.")
    if derived_columns:
        reasons.append("The selected analysis CSV contains derived or answer-bearing columns.")
    if not analysis_csv_info:
        reasons.append("No candidate robustness dataset was found.")
    # Even apparently raw data needs operator confirmation of population, estimand,
    # inclusion rules, and unit of analysis before a hidden-method run is meaningful.
    reasons.append("Operator approval of the result-neutral held-constants contract is required.")
    return {
        "ready": False,
        "requires_operator_approval": True,
        "selected_dataset": (analysis_csv_info or {}).get("path"),
        "derived_or_answer_columns": derived_columns,
        "reasons": reasons,
    }


def generate_analysis_contract(
    manifest: dict[str, Any], analysis_name: str, df: pd.DataFrame
) -> dict[str, Any]:
    id_candidates = [column for column in df.columns if column.lower() == "id" or column.lower().endswith("_id")]
    return {
        "schema_version": "rrg.analysis-contract.v1",
        "report_type": manifest["report_type"],
        "dataset": f"{analysis_name}.csv",
        "robustness_input": {"file": "", "result_neutral": False},
        "held_constants": {
            "population": {"status": "operator_review_required", "definition": ""},
            "unit_of_analysis": {
                "status": "operator_review_required",
                "definition": "",
                "candidate_id_columns": id_candidates[:8],
            },
            "inclusion_exclusion": {"status": "operator_review_required", "definition": ""},
            "time_window": {"status": "operator_review_required", "definition": ""},
            "constructs_and_outcomes": {"status": "operator_review_required", "definition": ""},
            "missingness": {"status": "fixed", "definition": "__RRG_NA__ represents missing CSV values"},
        },
        "robustness_method_policy": "Choose an independent method after honoring only the approved held constants.",
        "approval": {"status": "pending", "reviewer": "", "reviewed_at": ""},
    }


def _model_evaluation_stub(model: dict[str, Any]) -> dict[str, Any]:
    task_type = str(model["task_type"])
    metrics: dict[str, Any]
    if task_type == "continuous":
        metrics = {"mae": None, "pearson_r": None}
    elif task_type == "binary_classification":
        metrics = {"roc_auc": None, "confusion_matrix": {"tn": None, "fp": None, "fn": None, "tp": None}}
    else:
        metrics = {}
    return {
        "schema_version": MODEL_EVALUATION_SCHEMA,
        "model_id": model["id"],
        "task_type": task_type,
        "artifact": {"name": model["source"], "sha256": model["artifact_sha256"]},
        "ground_truth": {"source": "", "target": "", "n": 0, "independent": False},
        "metrics": metrics,
        "acceptance": {"criteria": []},
        "approval": {"reviewer": "", "reviewed_at": ""},
        "limitations": ["Pending independent ground-truth evaluation."],
    }




# ---------------------------------------------------------------------------
# Effort intake review prompt and corrected-questions helper
# ---------------------------------------------------------------------------

EFFORT_INTAKE_REVIEW_PROMPT = """# Effort intake review — {STUDY_TITLE}

You are reviewing and correcting an auto-generated RRG project that was created
by the Effort normalizer from an Effort research-harness report. Your job is to
ensure the normalized output is accurate and complete.

You have access to:
- The original Effort report: `{ORIGIN_REPORT}`
- The auto-generated SUMMARY.md (may be a stub with "not reported" fields)
- The auto-generated QUESTIONS.md (may include non-question section headings)
- The validation questions (numbered list below)

## Validation questions

{QUESTIONS_LIST}

## What to do

### Step 1: Review QUESTIONS.md for inappropriate content

Read the auto-generated QUESTIONS.md. Check each numbered item:
- Is it an actual research question that the report investigates with data?
- Or is it a methodology section, appendix, data description, or limitation section?

Remove any items that are not research questions. If the auto-generated list is
missing actual research questions that the report addresses, add them.

Write the corrected questions as a numbered list.

### Step 2: Review SUMMARY.md against the original report

Read the original report (`{ORIGIN_REPORT}`). For each validation question:

1. Check if the auto-generated SUMMARY.md has the correct structured fields
2. Fill in any fields marked "not reported" by finding the information in the report
3. If a field is genuinely absent from the report, keep it as "not reported"
4. Cross-check: did the normalizer miss any research questions that the report
   actually investigates? If so, note them at the end.

### Step 3: Verify completeness

Go through the original report section by section. For each section that contains
research findings, verify that the corresponding question exists in the numbered
list and has a SUMMARY.md entry. Flag any missing questions.

## What to produce

Output TWO things, in this order:

### 1. Corrected `{SUMMARY_FILE}`

Output GitHub-flavored markdown with one section per question, in order, each
headed `## Q<n> - <topic>`, where `<n>` is the question number exactly as shown
in the list above. Under each heading, give the fixed field list:

- **question** — the question text, clearly stated as a research question.
- **n** — the analysis N the report used for this question. If not reported, write "not reported".
- **groups** — how cases were split or grouped (definitions only).
- **test** — the exact test or method and its alternative/direction.
- **statistic** — the reported test statistic with its label.
- **p_value** — the reported p, exactly as printed. Never round a small p to 0.
  If the report states two conflicting values, record BOTH.
- **effect_size** — the reported effect size, or `null` if none.
- **multiplicity** — how multiple comparisons were treated, or `null`.
- **conclusion** — the report's own one-sentence conclusion for this question.

Copy numbers exactly as the report renders them. Transcribe; do not recompute.
If a field is genuinely absent, write "not reported".

For reports with multiple sub-results per question (e.g. 5 personality traits
per question family), list each sub-result on its own bullet line within the
section, including its test, statistic, p-value, CI, and multiplicity.

### 2. Corrected questions block

After the SUMMARY, output a fenced ````yaml```` block named `corrected_questions`:

```yaml
corrected_questions:
  - {n: 1, topic: "<topic>", question: "<question text>"}
  - {n: 2, topic: "<topic>", question: "<question text>"}
  ...
```

This will be used to update QUESTIONS.md and questions_map.yaml.

### 3. Review notes

After the corrected questions block, output a short review notes section:

- What was removed from the auto-generated QUESTIONS.md and why
- What was added that the normalizer missed
- Any data quality issues found in the report
- Any fields that could not be filled from the report

## Rules

- Transcribe; do not recompute, re-analyze, or "fix" the report.
- If the normalizer's auto-generated content is correct, keep it.
- If the normalizer included non-question sections, remove them.
- If the normalizer missed research questions the report investigates, add them.
- Honor the held constants in `{HELD_CONSTANTS_FILE}` ({HELD_CONSTANTS_SUMMARY}).
- Output only the artifacts above. No preamble.
"""


def apply_intake_review(project_root: str | Path, intake_text: str) -> dict[str, Any]:
    """Apply a model-returned intake review to an RRG project.

    Parses the intake text to:
    1. Extract and write the corrected SUMMARY.md (via the standard split_intake logic)
    2. Extract and apply the corrected_questions block to QUESTIONS.md + questions_map.yaml

    Args:
        project_root: Path to the RRG project
        intake_text: The model's full response (SUMMARY + corrected_questions + notes)

    Returns:
        Summary of what was applied
    """
    import yaml as _yaml
    project_root = Path(project_root)

    # 1. Split the intake text into SUMMARY and corrected_questions
    # The corrected_questions is a fenced yaml block
    cq_pattern = re.compile(r"```+\s*ya?ml\b\s*corrected_questions.*?```+", re.DOTALL | re.IGNORECASE)
    cq_match = cq_pattern.search(intake_text)

    if cq_match:
        summary_text = intake_text[:cq_match.start()].strip()
        cq_yaml = cq_match.group(0)
        # Extract the yaml content
        cq_yaml = re.sub(r"^```+\s*ya?ml\s*", "", cq_yaml, flags=re.IGNORECASE)
        cq_yaml = re.sub(r"\s*```+$", "", cq_yaml)
    else:
        summary_text = intake_text.strip()
        cq_yaml = ""

    # Remove any trailing review notes section from the summary
    notes_pattern = re.compile(r"\n#{1,3}\s*(?:review\s*notes|notes)\s*\n.*$", re.IGNORECASE | re.DOTALL)
    summary_text = notes_pattern.sub("", summary_text).strip()

    # Write SUMMARY.md
    summary_path = project_root / "operator" / "origin" / "SUMMARY.md"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(summary_text + "\n", encoding="utf-8")

    # 2. Parse and apply corrected_questions
    questions_updated = False
    questions_map_updated = False

    if cq_yaml:
        try:
            parsed = _yaml.safe_load(cq_yaml)
            if isinstance(parsed, dict) and "corrected_questions" in parsed:
                questions = parsed["corrected_questions"]
                if isinstance(questions, list):
                    # Write QUESTIONS.md
                    lines = ["# Validation questions", ""]
                    for q in questions:
                        n = q.get("n", "?")
                        text = q.get("question", q.get("topic", ""))
                        lines.append(f"{n}. {text}")
                    lines.append("")
                    questions_path = project_root / "shared" / "QUESTIONS.md"
                    questions_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    questions_updated = True

                    # Write questions_map.yaml
                    map_lines = ["questions:"]
                    for q in questions:
                        n = q.get("n", 1)
                        topic = q.get("topic", f"Question {n}")
                        map_lines.append(f'  - {{ n: {n}, orig: {n}, topic: "{topic}" }}')
                    map_path = project_root / "questions_map.yaml"
                    map_path.write_text("\n".join(map_lines) + "\n", encoding="utf-8")
                    questions_map_updated = True

                    # Update study.yaml question count
                    study_path = project_root / "study.yaml"
                    if study_path.is_file():
                        study_text = study_path.read_text(encoding="utf-8")
                        study_text = re.sub(
                            r"count:\s*\d+",
                            f"count: {len(questions)}",
                            study_text
                        )
                        study_path.write_text(study_text, encoding="utf-8")
        except Exception:
            pass  # If YAML parsing fails, at least the SUMMARY.md was written

    return {
        "summary_written": str(summary_path.relative_to(project_root)),
        "questions_updated": questions_updated,
        "questions_map_updated": questions_map_updated,
    }

def _generate_rrg_yaml(project_name: str, analysis_name: str, robustness_audit: dict[str, Any]) -> str:
    return f"""version: 1
project:
  name: {project_name}

paths:
  shared: shared
  data: data
  operator: operator
  runs: operator/runs
  packages: operator/packages
  reviews: operator/reviews
  grading: operator/grading
  archive: operator/archive
  compare_notes: operator/reviews/compare-notes

origin:
  vendor: Effort
  model: ResearchHarness
  results_key: operator/origin
  source_data: data/{analysis_name}.csv

files:
  all:
    - shared/STUDY_OVERVIEW.md
    - shared/QUESTIONS.md
    - shared/VALIDATION_INSTRUCTIONS.md
    - shared/ANALYSIS_CONTRACT.json
    - shared/METRIC_SPEC.json
    - data/{analysis_name}.csv
    - data/{analysis_name}.parquet
    - data/{analysis_name}.meta.json
    - data/{analysis_name}.codebook.csv
  stage_specific:
    - file: shared/ANALYSIS_PROTOCOL_OG.md
      send_in: [replication]
  withheld:
    - operator/origin/
    - operator/model-evaluations/
    - operator/normalization/
    - "operator/**/SCORECARD_*"
    - operator/private/

roster:
  replication: []
  robustness: []
  generalization: []

stages:
  replication:
    order: 1
    enabled: false
    blocked_reason: Replace and approve the result-free replication protocol stub before enabling.
    opens: model
    methodology: revealed
    prompt: prompts/replication.md
    send: [all, shared/ANALYSIS_PROTOCOL_OG.md]
    output_folder: replication_{{model}}
    report_name: "{{model}}_Report.md"
  robustness:
    order: 2
    enabled: false
    blocked_reason: Review held constants and configure result-neutral robustness data before enabling.
    opens: method-and-data-audit
    methodology: hidden
    prompt: prompts/robustness.md
    send: [all]
    output_folder: robustness_{{model}}
    report_name: "{{model}}_Report.md"
  generalization:
    order: 3
    enabled: false
    blocked_reason: Define the data-variation plan and method policy before enabling.
    opens: data
    methodology: decide-in-cartridge
    prompt: prompts/generalization.md
    send: [all]
    output_folder: generalization_{{model}}
    report_name: "{{model}}_Report.md"

blinding:
  always_withhold:
    - origin/
    - SCORECARD_*
    - private/
    - ORIGINAL_METHODOLOGY.md
  per_stage_methodology:
    replication:
      require: [ANALYSIS_PROTOCOL_OG.md]
      forbid: []
    robustness:
      require: []
      forbid: [ANALYSIS_PROTOCOL_OG.md, "*PROTOCOL*", ORIGINAL_METHODOLOGY.md]
    generalization:
      require: []
      forbid: [ORIGINAL_METHODOLOGY.md]
  result_token_scan:
    source: operator/origin
    action: flag
    exclude_globs: ["*.csv", "*.parquet", "*.json"]
    ignore_tokens: []

constraints:
  exclude_vendors: [Effort]
  determinism:
    temperature: 0
    seed: fixed

dispatch:
  start_template: "agent run --model {{model_slug}}"
  model_slugs: {{}}
"""


def _generate_study_yaml(
    project_name: str,
    analysis_name: str,
    manifest: dict,
    results_csv_info: dict | None,
    derived_models: list[dict[str, Any]],
) -> str:
    report_type = manifest["report_type"]
    title = project_name.replace("-", " ").replace("_", " ").title()

    # Count questions (will be filled by question extraction)
    n_questions = 3  # default

    # If we have results CSV, count unique questions
    if results_csv_info:
        try:
            df = pd.read_csv(results_csv_info["abs"])
            for col in ("question", "family"):
                if col in df.columns:
                    n_questions = df[col].nunique()
                    break
        except Exception:
            pass
    else:
        # For non-statistical, count from headings
        headings = manifest.get("headings", [])
        SKIP_SECTIONS = {
            "executive findings", "executive finding", "limitations",
            "companion data and build provenance", "sources",
            "coverage and limitations", "further questions",
            "companion data and evidence", "methodology", "scope test",
            "search procedure", "funding conventions", "cohort and selection",
            "classification method", "textual-analysis method",
            "candidate disposition log", "funding findings",
            "all 50 states and dc", "universe and scope",
            "popularity-ranked writing and interview corpus",
            "limitations and record boundaries", "method and validation sources",
            "shared-interview sensitivity",
        }
        question_headings = [h for h in headings 
                             if h.startswith("## ") and not h.startswith("### ")
                             and h.lstrip("# ").strip().lower() not in SKIP_SECTIONS]
        if question_headings:
            n_questions = min(len(question_headings), 10)

    model_lines = ["  derived_models:"]
    if derived_models:
        for model in derived_models:
            model_lines.extend(
                [
                    f"    - id: {model['id']}",
                    f"      role: {model['role']}",
                    f"      task_type: {model['task_type']}",
                    f"      source: {model['source']}",
                    f"      evaluation_file: {model['evaluation_file']}",
                    "      required: true",
                ]
            )
    else:
        model_lines.append("    []")
    derived_block = "\n".join(model_lines)

    return f"""study:
  title: {title}
  overview_file: shared/STUDY_OVERVIEW.md
  dataset:
    source: data/{analysis_name}.csv
    main_name: {analysis_name}
    merge_key: id
    formats: [csv, parquet]
    codebook: data/{analysis_name}.codebook.csv
    metadata: data/{analysis_name}.meta.json
    orientation: >-
      Use {{MAIN_DATASET}} in one of these equivalent formats: {{FORMATS}}.
      Variable definitions are in {{CODEBOOK}} and conversion metadata is in {{METADATA}}.
    aux:
      enabled: false
      name: ""
      file: ""
      note: ""
  given_solution:
    enabled: false
    glossary: ""
    artifacts: []
    note: ""
  additional: []
  questions:
    file: shared/QUESTIONS.md
    count: {n_questions}
    map: questions_map.yaml
    metric_spec: shared/METRIC_SPEC.json
  held_constants:
    file: shared/VALIDATION_INSTRUCTIONS.md
    contract: shared/ANALYSIS_CONTRACT.json
    summary: the study's construct and grouping definitions
    qa_groups: all fixed grouping definitions
  original:
    methodology_file: shared/ANALYSIS_PROTOCOL_OG.md
    results_key: operator/origin/
    model: Effort Research Harness
    vendor: Effort
    summary_file: operator/origin/SUMMARY.md
    results_file: operator/origin/origin.json
    methodology_prompt: operator/OG_METHODOLOGY_PROMPT.md
    intake_prompt: prompts/effort_intake_review.md
    report_file: operator/origin/report.md
{derived_block}
  deliverable:
    report_name: "{{MODEL}}_Report.md"
    reporting_spec: >-
      Produce the same deliverables for every question, identically, so the outputs are
      directly comparable. For each question n: (1) an analysis script `Q<n>_analysis.py`
      that writes its raw outputs to `raw/Q<n>_raw.csv`; (2) a figure script `Q<n>_fig.py`
      that reads that CSV and writes `Q<n>_fig.png` — use that exact filename; (3) a
      machine-readable `raw/Q<n>_summary.json`, a single flat JSON object that always
      includes the keys `question`, `n` (analysis N), `test` (method name), `statistic`,
      `p_value` (the exact value, never a rounded 0), `effect_size` (null if not
      applicable), and `conclusion` (one sentence). Emit every numeric result declared
      in `METRIC_SPEC.json`, no undeclared numeric result, and an `_units` object mapping
      every metric id to its exact contract unit. (4) a report section in DYFA format
      labelled `D - Do`, `Y - Why`, `F - Find`, `A - Answer`, embedding `Q<n>_fig.png`.
      In F or A, repeat each declared metric as the exact backticked marker
      `<metric_id>=<value-or-null> <unit>`. Also write `RAW.md` and `SUMMARY.md`
      indexing the per-question artifacts. Before finishing, confirm every question has
      all four — script+csv, fig+png, summary.json, and a DYFA section — and that no
      `raw/Q<n>_summary.json` is missing.
    method_guide:
      enabled: false
      name: ""
      file: ""
"""


def _generate_questions_map(manifest: dict, results_csv_info: dict | None) -> str:
    """Generate questions_map.yaml."""
    lines = ["questions:"]

    if results_csv_info:
        try:
            df = pd.read_csv(results_csv_info["abs"])
            # Use "question" or "family" column
            group_col = None
            for col in ("question", "family"):
                if col in df.columns:
                    group_col = col
                    break
            if group_col:
                questions = df[group_col].unique()
                for i, q in enumerate(questions, 1):
                    topic = str(q).replace("_", " ").title()
                    lines.append(f'  - {{ n: {i}, orig: {i}, topic: "{topic}" }}')
                return "\n".join(lines) + "\n"
        except Exception:
            pass

    # For non-statistical reports, derive count from the question headings
    headings = manifest.get("headings", [])
    SKIP_SECTIONS = {
        "executive findings", "executive finding", "limitations",
        "companion data and build provenance", "sources",
        "coverage and limitations", "further questions",
        "companion data and evidence", "methodology", "scope test",
        "search procedure", "funding conventions", "cohort and selection",
        "classification method", "textual-analysis method",
        "candidate disposition log", "funding findings",
        "all 50 states and dc", "universe and scope",
        "popularity-ranked writing and interview corpus",
        "limitations and record boundaries", "method and validation sources",
        "shared-interview sensitivity",
    }
    question_headings = [h.lstrip("# ").strip() for h in headings 
                         if h.startswith("## ") and not h.startswith("### ")
                         and h.lstrip("# ").strip().lower() not in SKIP_SECTIONS]

    count = len(question_headings[:10]) if question_headings else 3

    for i in range(1, count + 1):
        topic = question_headings[i-1][:50] if i <= len(question_headings) else f"Question {i}"
        lines.append(f'  - {{ n: {i}, orig: {i}, topic: "{topic}" }}')

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Content generators (stubs that model-assisted steps will fill)
# ---------------------------------------------------------------------------

def _generate_questions_stub(manifest: dict, results_csv_info: dict | None = None) -> str:
    """Generate QUESTIONS.md stub based on report headings or results CSV."""
    lines = ["# Validation questions", ""]

    # For statistical reports with a results CSV, use the question column
    if results_csv_info:
        try:
            df = pd.read_csv(results_csv_info["abs"])
            # Use "question" or "family" column
            group_col = None
            for col in ("question", "family"):
                if col in df.columns:
                    group_col = col
                    break
            if group_col:
                questions = df[group_col].unique()
                # Map question IDs to human-readable text using the report's sub-headings
                report_md = manifest.get("report_md")
                question_text_map = {}
                if report_md and Path(report_md).is_file():
                    with open(report_md) as f:
                        text = f.read()
                    # Find ### sub-headings under "## Answers to the correlation questions"
                    for q_id in questions:
                        q_text = _find_question_heading(text, q_id)
                        question_text_map[q_id] = q_text or str(q_id).replace("_", " ").title()

                for i, q in enumerate(questions, 1):
                    q_text = question_text_map.get(q, str(q).replace("_", " ").title())
                    lines.append(f"{i}. {q_text}")

                lines.append("")
                lines.append("<!-- Auto-generated from results CSV question column. -->")
                return "\n".join(lines) + "\n"
        except Exception:
            pass

    # Fallback: extract from report headings
    headings = manifest.get("headings", [])
    # Expanded skip list
    SKIP_SECTIONS = {
        "executive findings", "executive finding", "limitations",
        "companion data and build provenance", "sources",
        "coverage and limitations", "further questions",
        "companion data and evidence", "methodology", "scope test",
        "search procedure", "funding conventions", "cohort and selection",
        "classification method", "textual-analysis method",
        "candidate disposition log", "funding findings",
        "all 50 states and dc", "universe and scope",
        "popularity-ranked writing and interview corpus",
        "limitations and record boundaries", "method and validation sources",
        "shared-interview sensitivity",
    }
    question_headings = []
    for h in headings:
        if h.startswith("## ") and not h.startswith("### "):
            title = h.lstrip("# ").strip()
            if title.lower() not in SKIP_SECTIONS:
                question_headings.append(title)

    for i, q in enumerate(question_headings[:10], 1):
        lines.append(f"{i}. {q}")
    lines.append("")
    lines.append("<!-- HUMAN: Review and refine these auto-extracted questions.")
    lines.append("     They were derived from report.md section headings.")
    lines.append("     Edit to match the actual research questions the report investigates. -->")

    return "\n".join(lines) + "\n"


def _find_question_heading(text: str, question_id: str) -> str | None:
    """Try to find a ### sub-heading that matches a question ID from the results CSV."""
    # Map common question IDs to heading patterns
    qid = str(question_id).lower().replace("_", " ")
    for line in text.split("\n"):
        if line.startswith("### "):
            heading = line.lstrip("# ").strip().lower()
            if qid in heading or any(word in heading for word in qid.split()):
                return line.lstrip("# ").strip()
    return None

def _generate_overview_stub(manifest: dict, analysis_name: str) -> str:
    """Generate a deliberately result-neutral validator-facing overview."""
    report_type = manifest["report_type"]
    name = manifest["name"]

    return f"""# Study overview — {name}

*Auto-generated by the Effort normalizer. Review and refine.*

## Summary

This study was produced by the Effort research harness. The report type is
**{report_type}**.

### Dataset

The analysis dataset is `{analysis_name}.csv` (with `.parquet`, `.codebook.csv`,
and `.meta.json` derivatives). Variable definitions are in the codebook.

### Research context

<!-- OPERATOR: Add result-neutral context only. Do not paste executive findings,
origin values, conclusions, or original-method details here. -->

## Note

The origin report and every origin value are withheld from validators. This overview
contains no findings by construction.
"""


def _generate_protocol_stub(manifest: dict) -> str:
    """Create a safe stub; copied origin methodology remains operator-only.

    A regex cannot prove prose is result-free. Replication therefore starts blocked
    until an operator reviews and explicitly supplies this protocol.
    """
    return """# Original analysis protocol — operator review required

Do not dispatch replication with this stub.

For each validation question, add the original method needed for exact reproduction.
Remove every observed result, effect direction, conclusion, value, table, and figure.
The full source methodology remains under `operator/origin/` for operator review and
is never copied here automatically.
"""


def _extract_methodology_sections(text: str) -> str:
    """Extract methodology-related sections from a report."""
    METHOD_HEADINGS = (
        "methodology", "classification method", "cohort and selection",
        "scope test", "search procedure", "funding conventions",
        "textual-analysis method",
    )
    lines = text.split("\n")
    sections = []
    current_section = None
    current_lines = []

    for line in lines:
        if line.startswith("## ") and not line.startswith("### "):
            heading = line.lstrip("# ").strip().lower()
            if current_section and any(mh in current_section.lower() for mh in METHOD_HEADINGS):
                sections.append(f"## {current_section}\n" + "\n".join(current_lines))
            current_section = line.lstrip("# ").strip()
            current_lines = []
        elif current_section:
            if line.startswith("## "):
                if any(mh in current_section.lower() for mh in METHOD_HEADINGS):
                    sections.append(f"## {current_section}\n" + "\n".join(current_lines))
                current_section = line.lstrip("# ").strip()
                current_lines = []
            else:
                current_lines.append(line)

    if current_section and any(mh in current_section.lower() for mh in METHOD_HEADINGS):
        sections.append(f"## {current_section}\n" + "\n".join(current_lines))

    return "\n\n".join(sections) if sections else ""

def _generate_validation_instructions(manifest: dict, analysis_name: str, df: pd.DataFrame) -> str:
    """Generate VALIDATION_INSTRUCTIONS.md with held constants."""
    report_type = manifest["report_type"]
    cols = list(df.columns)

    # Detect likely ID columns
    id_cols = [c for c in cols if "id" in c.lower() and df[c].dtype == "object"]
    group_cols = [c for c in cols if any(g in c.lower() for g in ("type", "status", "tier", "category", "group"))]

    lines = [
        "# Validation instructions",
        "",
        "These definitions are fixed across validation stages.",
        "",
        "## Decision policy",
        "",
        "- Use a per-test significance threshold of alpha = 0.05 unless the protocol specifies otherwise.",
        "- Report exact p-values where computationally available; do not report a rounded zero.",
        "- Record any multiplicity correction or lack of correction explicitly.",
        "- Do not search for the original report or prior answers.",
        "",
        "## Data and missingness",
        "",
        f"- Use `{analysis_name}.csv` (or `.parquet`) as the analysis dataset.",
        f"- Variable definitions are in `{analysis_name}.codebook.csv`.",
    ]

    if id_cols:
        lines.append(f"- Treat `{id_cols[0]}` as the row identifier.")
    if group_cols:
        lines.append(f"- Treat `{group_cols[0]}` as the primary grouping variable.")

    lines += [
        "- Report every derived analysis N.",
        "- Treat `__RRG_NA__` as missing in CSV format.",
        "- Read `METRIC_SPEC.json` and emit every listed validator path with the specified unit.",
        "- Add `_units` keyed by metric id, and transcribe each metric in DYFA F or A as `<metric_id>=<value-or-null> <unit>`.",
        "- Emit no undeclared numeric results; result annotations may be non-numeric.",
        "- Treat declared metric relations as exact internal identities.",
        "- Do not invent a tolerance; comparison policy is operator-owned and withheld.",
        "",
        "## Result-neutral reporting guidance",
        "",
    ]

    if report_type == "statistical":
        lines += [
            "- Quantify uncertainty and report exact p-values when the independently chosen method produces them.",
            "- State the analysis unit and every multiple-comparison decision.",
            "- Robustness validators must choose their method independently; no original test family is supplied.",
        ]
    elif report_type == "descriptive":
        lines += [
            "- Report the quantities needed to answer each question, with explicit units and denominators.",
            "- Distinguish atomic source records from derived rankings, totals, and shares.",
            "- Only operator-approved construct definitions in `ANALYSIS_CONTRACT.json` are held constant.",
        ]
    elif report_type == "inventory":
        lines += [
            "- Reconstruct counts and classifications from result-neutral evidence inputs.",
            "- Do not treat preassigned tiers, statuses, or dispositions as independent validation evidence.",
            "- Only operator-approved scope and construct definitions are held constant.",
        ]

    return "\n".join(lines) + "\n"


def _generate_summary_from_results(results_csv_info: dict, report_dir: Path) -> str | None:
    """Generate SUMMARY.md from a structured results CSV (statistical reports only)."""
    try:
        df = pd.read_csv(results_csv_info["abs"])
    except Exception:
        return None

    # Use "question" or "family" column for grouping
    group_col = None
    for col in ("question", "family"):
        if col in df.columns:
            group_col = col
            break
    if group_col is None:
        return None

    questions = df[group_col].unique()
    lines = ["# Origin intake SUMMARY — auto-generated from results CSV", ""]

    for i, q in enumerate(questions, 1):
        q_df = df[df[group_col] == q]
        topic = str(q).replace("_", " ").title()
        lines.append(f"## Q{i} - {topic}")
        lines.append("")

        # If there are multiple rows (e.g. per-trait), list each
        if len(q_df) > 1:
            lines.append("**question** — " + str(q))
            lines.append("")

            # Determine the N
            n_col = None
            for col in ["n_companies", "n_founders", "n"]:
                if col in q_df.columns:
                    n_col = col
                    break

            if n_col:
                n_val = q_df[n_col].iloc[0]
                lines.append(f"**n** — {n_val}")
            elif "n" in q_df.columns:
                lines.append(f"**n** — {q_df['n'].iloc[0]}")
            lines.append("")

            # List each sub-result
            for _, row in q_df.iterrows():
                # Handle both Effort schema (trait, effect, effect_metric) and
                # Fable schema (test, value, estimate)
                trait = row.get("trait", "")
                test_name = row.get("effect_metric", row.get("test", row.get("estimate", "")))
                effect = row.get("effect", row.get("value", row.get("statistic", "")))
                p_val = row.get("p_value", "")
                q_val = row.get("q_value", "")
                ci_low = row.get("ci95_low", row.get("ci_low", ""))
                ci_high = row.get("ci95_high", row.get("ci_high", ""))
                n_val = row.get("n_companies", row.get("n", ""))

                # For Fable schema, extract trait from test name
                if not trait and "test" in row:
                    test_text = str(row.get("test", ""))
                    # Try to extract trait name from test description
                    for t_name in ["openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"]:
                        if t_name in test_text.lower():
                            trait = t_name.capitalize()
                            break
                    if not trait:
                        trait = test_text  # Use full test name as label

                lines.append(f"- **{trait}**: test={test_name}, statistic={effect}, "
                           f"95% CI=[{ci_low}, {ci_high}], p={p_val}, "
                           f"multiplicity=BH-FDR q={q_val}")

            lines.append("")
            lines.append(f"**conclusion** — See origin report for the prose conclusion.")
            lines.append("")
            lines.append("---")
            lines.append("")
        else:
            row = q_df.iloc[0]
            lines.append(f"**question** — {q}")
            lines.append(f"**n** — {row.get('n_companies', row.get('n', 'not reported'))}")
            lines.append(f"**test** — {row.get('effect_metric', row.get('test', 'not reported'))}")
            lines.append(f"**statistic** — {row.get('effect', row.get('statistic', 'not reported'))}")
            lines.append(f"**p_value** — {row.get('p_value', 'not reported')}")
            lines.append(f"**effect_size** — {row.get('effect', 'not reported')}")
            lines.append(f"**multiplicity** — BH-FDR q={row.get('q_value', 'not reported')}")
            lines.append(f"**conclusion** — See origin report.")
            lines.append("")
            lines.append("---")
            lines.append("")

    return "\n".join(lines)

# ---------------------------------------------------------------------------
# Project generation
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def generate_codebook(df: pd.DataFrame, csv_path: Path) -> list[dict[str, str]]:
    """Generate a codebook from a DataFrame."""
    rows = []
    for col in df.columns:
        dtype = str(df[col].dtype)
        # Try to extract value labels for categorical columns
        vals = df[col].dropna()
        is_categorical = dtype in ("object", "str", "string", "bool")
        if is_categorical and vals.nunique() < 20:
            value_labels = "; ".join(f"{v}={v}" for v in sorted(vals.unique()))
        elif dtype in ("int64", "int32") and vals.nunique() < 20:
            value_labels = "; ".join(f"{v}={v}" for v in sorted(vals.unique()))
        else:
            value_labels = ""
        rows.append({
            "variable": col,
            "label": "",
            "dtype": dtype,
            "measure": "nominal" if is_categorical else "scale",
            "value_labels": value_labels,
            "missing": "",
        })
    return rows


def generate_meta_json(df: pd.DataFrame, source_path: Path) -> dict[str, Any]:
    """Generate metadata JSON for a dataset."""
    return {
        "source": source_path.name,
        "source_sha256": sha256_file(source_path),
        "source_format": source_path.suffix,
        "n_rows": df.shape[0],
        "n_cols": df.shape[1],
        "mode": "csv",
        "na_token": "__RRG_NA__",
        "columns": list(df.columns),
        "variables": {
            col: {
                "label": "",
                "dtype": str(df[col].dtype),
                "measure": "nominal" if str(df[col].dtype) in ("object", "str", "string", "bool") else "scale",
                "value_labels": {},
                "missing_ranges": [],
            }
            for col in df.columns
        },
    }


def generate_project(
    report_dir: str | Path,
    output_dir: str | Path,
    *,
    analysis_csv: str | None = None,
    results_csv: str | None = None,
    project_name: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Generate a complete RRG project from an Effort report.

    Args:
        report_dir: Path to the Effort report directory
        output_dir: Where to create the RRG project
        analysis_csv: Override the auto-detected analysis CSV (relative path)
        results_csv: Override the auto-detected results CSV (relative path)
        project_name: Override the project name

    Returns:
        Manifest of what was generated
    """
    report_dir = Path(report_dir).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()
    if not report_dir.is_dir():
        raise FileNotFoundError(f"report directory not found: {report_dir}")

    # 1. Scan the report
    manifest = scan_report(report_dir)

    # 2. Find the analysis CSV
    if analysis_csv:
        for csv in manifest["data_csvs"]:
            if csv["path"] == analysis_csv:
                analysis_csv_info = csv
                break
        else:
            raise ValueError(f"analysis_csv '{analysis_csv}' not found in report")
    else:
        analysis_csv_info = find_analysis_csv(manifest)

    if not analysis_csv_info:
        raise ValueError("Could not auto-detect analysis CSV. Please specify one.")

    # 3. Find the results CSV
    if results_csv:
        for csv in manifest["data_csvs"]:
            if csv["path"] == results_csv:
                results_csv_info = csv
                break
        else:
            raise ValueError(f"results_csv '{results_csv}' not found in report")
    else:
        results_csv_info = find_results_csv(manifest)

    # 4. Create project structure
    project_name = project_name or manifest["name"]
    project_root = output_dir / project_name
    if project_root.exists() and any(project_root.iterdir()):
        if not force:
            raise FileExistsError(f"refusing to overwrite non-empty project: {project_root}")
        shutil.rmtree(project_root)

    derived_models = detect_derived_models(manifest)
    robustness_audit = analyze_robustness_readiness(manifest, analysis_csv_info, derived_models)

    # Create directories
    dirs = [
        "shared",
        "data",
        "prompts",
        "operator/origin",
        "operator/model-evaluations",
        "operator/normalization",
    ]
    for d in dirs:
        (project_root / d).mkdir(parents=True, exist_ok=True)

    # Create .rrg_root marker
    (project_root / ".rrg_root").touch()

    # 5. Copy and convert the analysis dataset
    analysis_src = report_dir / analysis_csv_info["path"]
    analysis_name = Path(analysis_csv_info["path"]).stem
    analysis_csv_dst = project_root / "data" / f"{analysis_name}.csv"
    analysis_parquet_dst = project_root / "data" / f"{analysis_name}.parquet"
    analysis_codebook_dst = project_root / "data" / f"{analysis_name}.codebook.csv"
    analysis_meta_dst = project_root / "data" / f"{analysis_name}.meta.json"

    df = pd.read_csv(analysis_src)

    # Write CSV with NA token
    na_token = "__RRG_NA__"
    df.to_csv(analysis_csv_dst, index=False, na_rep=na_token, lineterminator="\n")

    # Write parquet
    try:
        df.to_parquet(analysis_parquet_dst, index=False)
    except Exception:
        pass  # parquet optional if pyarrow missing

    # Generate codebook
    codebook = generate_codebook(df, analysis_src)
    pd.DataFrame(codebook).to_csv(analysis_codebook_dst, index=False, lineterminator="\n")

    # Generate metadata
    meta = generate_meta_json(df, analysis_src)
    with open(analysis_meta_dst, "w") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    # 6. Copy the origin report
    report_md_path = Path(manifest["report_md"]) if manifest.get("report_md") else None
    if report_md_path and report_md_path.is_file():
        shutil.copy2(report_md_path, project_root / "operator" / "origin" / "report.md")

    report_html_path = Path(manifest["report_html"]) if manifest.get("report_html") else None
    if report_html_path and report_html_path.is_file():
        shutil.copy2(report_html_path, project_root / "operator" / "origin" / "report.html")

    # 7. Copy the methodology file
    methodology_src = manifest.get("methodology_md")
    if not methodology_src:
        # Try source_memos
        sm_dir = manifest.get("source_memos_dir")
        if sm_dir:
            # Look for a methodology-like file
            for p in Path(sm_dir).iterdir():
                if "method" in p.name.lower() and p.suffix == ".md":
                    methodology_src = str(p)
                    break
    if methodology_src:
        shutil.copy2(methodology_src, project_root / "operator" / "origin" / "methodology.md")

    # 8. Copy charts/figures if any (only summary-level, not per-entity/time-series)
    for chart in manifest.get("charts", []):
        src = report_dir / chart
        if not src.is_file():
            continue
        # Skip per-entity or per-year chart files (e.g. "arcus-2020.svg")
        if "/charts/" in chart or "\\charts\\" in chart:
            continue
        # Only copy PNG/JPG (not SVG which are often individual chart files)
        if src.suffix in (".png", ".jpg", ".jpeg"):
            shutil.copy2(src, project_root / "operator" / "origin" / src.name)

    # 9. Copy source-ledger if available
    for p in report_dir.rglob("*source*ledger*.csv"):
        shutil.copy2(p, project_root / "operator" / "origin" / "source_ledger.csv")
        break

    # 10. Generate the rrg.yaml
    rrg_yaml = _generate_rrg_yaml(project_name, analysis_name, robustness_audit)
    with open(project_root / "rrg.yaml", "w") as f:
        f.write(rrg_yaml)

    # 11. Generate the study.yaml
    study_yaml = _generate_study_yaml(
        project_name, analysis_name, manifest, results_csv_info, derived_models
    )
    with open(project_root / "study.yaml", "w") as f:
        f.write(study_yaml)

    # 12. Generate questions_map.yaml
    questions_map = _generate_questions_map(manifest, results_csv_info)
    with open(project_root / "questions_map.yaml", "w") as f:
        f.write(questions_map)

    # Public shape and operator-only values are generated separately. The public file
    # is safe to package; the origin JSON remains beneath the withheld results key.
    public_metrics, origin_results = generate_metric_contracts(manifest, results_csv_info)
    (project_root / "shared" / "METRIC_SPEC.json").write_text(
        json.dumps(public_metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (project_root / "operator" / "origin" / "origin.json").write_text(
        json.dumps(origin_results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    analysis_contract = generate_analysis_contract(manifest, analysis_name, df)
    (project_root / "shared" / "ANALYSIS_CONTRACT.json").write_text(
        json.dumps(analysis_contract, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    for model in derived_models:
        evaluation_path = project_root / model["evaluation_file"]
        evaluation_path.parent.mkdir(parents=True, exist_ok=True)
        evaluation_path.write_text(
            json.dumps(_model_evaluation_stub(model), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    # 13. Copy prompt templates from RRG defaults
    # Resolve template dir relative to the RRG CLI installation
    # The normalizer lives in skills/rrg-effort-normalizer/lib/
    # Templates live in src/rrg_cli/templates/project/ (3 levels up from skills/)
    _skill_dir = Path(__file__).resolve().parent.parent  # skills/rrg-effort-normalizer/
    _skills_parent = _skill_dir.parent  # skills/
    template_dir = _skills_parent.parent / "src" / "rrg_cli" / "templates" / "project"
    if not template_dir.is_dir():
        # Fallback: try common RRG root paths
        for candidate in (
            Path.cwd() / "src" / "rrg_cli" / "templates" / "project",
            Path.home() / "Projects" / "RRG_real_root" / "RRG_root" / "rrg-cli" / "src" / "rrg_cli" / "templates" / "project",
        ):
            if candidate.is_dir():
                template_dir = candidate
                break
    if template_dir.is_dir():
        for fname in ("replication.md", "robustness.md", "generalization.md", "origin_intake.md"):
            src = template_dir / "prompts" / fname
            if src.is_file():
                shutil.copy2(src, project_root / "prompts" / fname)

    # Save the Effort intake review prompt
    intake_review_path = project_root / "prompts" / "effort_intake_review.md"
    intake_review_path.write_text(EFFORT_INTAKE_REVIEW_PROMPT, encoding="utf-8")

    # 14. Copy shared template files as starting points
    if template_dir.is_dir():
        for fname in ("VALIDATION_INSTRUCTIONS.md",):
            src = template_dir / "shared" / fname
            if src.is_file():
                shutil.copy2(src, project_root / "shared" / fname)

    # 15. Generate the remaining shared files (these need model assistance)
    # QUESTIONS.md, STUDY_OVERVIEW.md, ANALYSIS_PROTOCOL_OG.md, SUMMARY.md
    # The normalizer generates stubs that the wizard/intake will fill

    # Generate the SUMMARY.md from the results CSV if available
    if results_csv_info:
        summary = _generate_summary_from_results(results_csv_info, report_dir)
        if summary:
            with open(project_root / "operator" / "origin" / "SUMMARY.md", "w") as f:
                f.write(summary)
    else:
        # For non-statistical reports, generate a stub SUMMARY.md from headings
        # to prevent dangling references in study.yaml
        stub_summary = _generate_stub_summary(manifest, project_name)
        with open(project_root / "operator" / "origin" / "SUMMARY.md", "w") as f:
            f.write(stub_summary)

    # Generate QUESTIONS.md stub
    questions_stub = _generate_questions_stub(manifest, results_csv_info)
    with open(project_root / "shared" / "QUESTIONS.md", "w") as f:
        f.write(questions_stub)

    # Generate STUDY_OVERVIEW.md stub
    overview_stub = _generate_overview_stub(manifest, analysis_name)
    with open(project_root / "shared" / "STUDY_OVERVIEW.md", "w") as f:
        f.write(overview_stub)

    # Generate ANALYSIS_PROTOCOL_OG.md stub
    protocol_stub = _generate_protocol_stub(manifest)
    with open(project_root / "shared" / "ANALYSIS_PROTOCOL_OG.md", "w") as f:
        f.write(protocol_stub)

    # Generate VALIDATION_INSTRUCTIONS.md
    vi_content = _generate_validation_instructions(manifest, analysis_name, df)
    with open(project_root / "shared" / "VALIDATION_INSTRUCTIONS.md", "w") as f:
        f.write(vi_content)

    # 16. Run rrg convert to create verified parquet + regenerate codebook + meta
    conversion = {"status": "not_run", "command": None, "stderr": ""}
    try:
        import subprocess
        rrg_bin = None
        for candidate in (
            project_root.parent.parent.parent.parent / ".venv" / "bin" / "rrg",
            Path.home() / "Projects" / "RRG_real_root" / "RRG_root" / "rrg-cli" / ".venv" / "bin" / "rrg",
        ):
            if candidate.is_file():
                rrg_bin = str(candidate)
                break
        if rrg_bin:
            command = [
                rrg_bin, "convert", f"data/{analysis_name}.csv",
                "--out", f"data/{analysis_name}", "--formats", "csv", "parquet",
            ]
            completed = subprocess.run(
                command,
                cwd=str(project_root),
                capture_output=True, text=True, timeout=60,
            )
            conversion = {
                "status": "passed" if completed.returncode == 0 else "failed",
                "command": command,
                "stderr": completed.stderr[-2000:],
            }
            if completed.returncode != 0:
                raise RuntimeError(f"rrg convert failed: {completed.stderr.strip()}")
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"rrg convert could not complete: {exc}") from exc

    normalization_record = {
        "schema_version": "rrg.effort-normalization.v1",
        "source_report": str(report_dir),
        "report_type": manifest["report_type"],
        "selected_analysis_csv": analysis_csv_info["path"],
        "selected_results_csv": results_csv_info["path"] if results_csv_info else None,
        "derived_models": derived_models,
        "robustness_audit": robustness_audit,
        "conversion": conversion,
        "operator_actions": [
            "Review the result-neutral shared/ANALYSIS_CONTRACT.json and mark its approval.",
            "Replace the replication protocol stub with a reviewed result-free protocol.",
            "Complete every required operator/model-evaluations record.",
            "Run origin intake to complete canonical origin values for descriptive or inventory reports.",
            "Select result-neutral robustness inputs before enabling the robustness stage.",
        ],
    }
    normalization_path = project_root / "operator" / "normalization" / "manifest.json"
    normalization_path.write_text(
        json.dumps(normalization_record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return {
        "project_root": str(project_root),
        "report_type": manifest["report_type"],
        "analysis_csv": analysis_csv_info["path"],
        "results_csv": results_csv_info["path"] if results_csv_info else None,
        "derived_models": [model["id"] for model in derived_models],
        "robustness_ready": robustness_audit["ready"],
        "normalization_manifest": str(normalization_path.relative_to(project_root)),
        "files_generated": sorted(str(p.relative_to(project_root)) for p in project_root.rglob("*") if p.is_file()),
    }


def _generate_stub_summary(manifest: dict, project_name: str) -> str:
    """Generate a stub SUMMARY.md for non-statistical reports (no results CSV)."""
    headings = manifest.get("headings", [])
    SKIP_SECTIONS = {
        "executive findings", "executive finding", "limitations",
        "companion data and build provenance", "sources",
        "coverage and limitations", "further questions",
        "companion data and evidence", "methodology", "scope test",
        "search procedure", "funding conventions", "cohort and selection",
        "classification method", "textual-analysis method",
        "candidate disposition log", "funding findings",
        "all 50 states and dc", "universe and scope",
        "popularity-ranked writing and interview corpus",
        "limitations and record boundaries", "method and validation sources",
        "shared-interview sensitivity",
    }
    question_headings = [h.lstrip("# ").strip() for h in headings 
                         if h.startswith("## ") and not h.startswith("### ")
                         and h.lstrip("# ").strip().lower() not in SKIP_SECTIONS]

    # Try to use investigation.json or validation_summary.json for structured data
    summary_data = {}
    vs_path = manifest.get("validation_summary")
    if vs_path and Path(vs_path).is_file():
        try:
            with open(vs_path) as f:
                summary_data = json.load(f)
        except Exception:
            pass

    lines = [
        f"# Origin intake SUMMARY — stub for {project_name}",
        "",
        "<!-- This is a stub. Run `rrg intake` to generate a proper SUMMARY.md from the report. -->",
        "",
    ]

    for i, q in enumerate(question_headings[:10], 1):
        lines.append(f"## Q{i} - {q}")
        lines.append("")
        lines.append(f"**question** — {q}")
        lines.append(f"**n** — not reported")
        lines.append(f"**test** — not reported")
        lines.append(f"**statistic** — not reported")
        lines.append(f"**p_value** — not reported")
        lines.append(f"**effect_size** — not reported")
        lines.append(f"**multiplicity** — not reported")
        lines.append(f"**conclusion** — See origin report.")
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)
