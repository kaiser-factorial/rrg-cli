\
"""Automated project setup: generate the shared docs from the dataset + origin report.

Given a project with source data (already converted) and an origin report placed in
operator/origin/, this module generates the model-facing documents:

1. QUESTIONS.md — extract research questions from the origin report
2. questions_map.yaml — derived from the questions
3. STUDY_OVERVIEW.md — structural overview from the codebook (with placeholders)
4. VALIDATION_INSTRUCTIONS.md — group definitions from codebook value labels (with placeholders)
5. ANALYSIS_PROTOCOL_OG.md — result-free methodology from the origin report (existing prompt)
6. operator/origin/SUMMARY.md — per-question transcription from the origin report (existing intake)

Steps 1, 3, 4, 5, 6 use a model. Steps 2 is deterministic. The user reviews all
generated docs and fills in placeholders.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .errors import RRGError
from .project import Project
from .utils import load_yaml, dump_yaml

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

QUESTION_EXTRACTION_PROMPT = """\
# Question extraction — {STUDY_TITLE}

You are given the original report `{ORIGIN_REPORT}`. Extract every research
question that the report investigates and list them as a numbered list.

## Rules

- List each question exactly as the report states it — do not rephrase or simplify.
- Number the questions 1 through N in the order they appear in the report.
- If the report uses its own numbering (e.g. Q1, Q4, Q7), renumber sequentially
  1 through N but preserve the original number in parentheses after each question.
- Include only research questions that the report actually investigates with data
  analysis — not section headings, not discussion prompts, not future-work questions.
- If a question references specific variables, movies, groups, or thresholds by name,
  keep those references verbatim — they are part of the question.

## Output format

Output a numbered list, one question per line:

```
1. <verbatim question text from the report>
2. <verbatim question text from the report>
...
```

If the report also states a topic label for each question, include it in parentheses:

```
1. <question text> (topic: <label>)
```

Output only the numbered list. No preamble, no commentary.
"""

STUDY_OVERVIEW_PROMPT = """\
# Study overview generation — {STUDY_TITLE}

You are generating a result-neutral study overview for a validation project.
You are given:
- The dataset codebook (`{CODEBOOK}`) with column names and value labels
- The dataset metadata (`{METADATA}`) with row/column counts and source info
- The validation questions (`{QUESTIONS_FILE}`)

Generate a markdown file that describes:
1. **The dataset** — number of rows, number of columns, what the columns contain
   (use the codebook column names and value labels to describe groups and scales)
2. **The research context** — what the study investigates, based on the questions
3. **A note that the origin report is withheld** from validators

## Rules

- Result-neutral: no findings, no p-values, no conclusions, no effect sizes
- Use the codebook to describe the data structure accurately
- If the codebook has value labels (e.g. "1=Yes, 0=No"), include them
- Leave a `<!-- HUMAN: ... -->` comment where the user should add context that
  the codebook cannot provide (e.g. study motivation, theoretical framework)

## Output

Output the full markdown for `shared/STUDY_OVERVIEW.md`. No preamble.
"""

VALIDATION_INSTRUCTIONS_PROMPT = """\
# Validation instructions generation — {STUDY_TITLE}

You are generating the held-constant definitions for a validation project.
You are given:
- The dataset codebook (`{CODEBOOK}`) with column names and value labels
- The validation questions (`{QUESTIONS_FILE}`)

Generate a markdown file with the fixed definitions that validators must follow:

## What to include

1. **Data and missingness** — how to handle missing values, what the scale ranges are
   (from value labels), any merge keys or identifiers
2. **Fixed groups** — every grouping variable used in the questions, with the exact
   value labels and exclusion rules (e.g. "Gender: 1 (female) vs 2 (male); exclude 3
   and missing")
3. **Decision policy** — include:
   - A default significance threshold of alpha = 0.05 unless the questions or
     origin report clearly specify a different threshold
   - A note on multiplicity: if any question involves testing many items (e.g.
     "what proportion of 400 movies..."), state whether raw p-values are reported
     or whether a correction (Bonferroni, FDR, etc.) is applied. Default: report
     raw p-values with no correction unless the report specifies otherwise.

## Rules

- Extract group definitions from the codebook's value labels — these are the
  fixed definitions validators must use
- If a question references a specific variable (e.g. "column 476"), include the
  mapping from the codebook
- Alpha defaults to 0.05 — do not leave it as a placeholder. If a different
  alpha is clearly stated in the questions or report, use that instead.

## Output

Output the full markdown for `shared/VALIDATION_INSTRUCTIONS.md`. No preamble.
"""


# ---------------------------------------------------------------------------
# Codebook analysis (deterministic)
# ---------------------------------------------------------------------------

def _read_codebook(project: Project) -> list[dict[str, Any]]:
    """Read the codebook CSV and return column info."""
    import csv
    codebook_path = project.path(
        project.study.get("dataset", {}).get("codebook", "data/analysis.codebook.csv")
    )
    if not codebook_path.is_file():
        raise RRGError(f"codebook not found: {codebook_path}")
    with open(codebook_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def _read_metadata(project: Project) -> dict[str, Any]:
    """Read the dataset metadata JSON."""
    meta_value = project.study.get("dataset", {}).get("metadata", "data/analysis.meta.json")
    meta_path = project.path(meta_value)
    if not meta_path.is_file():
        return {}
    return json.loads(meta_path.read_text(encoding="utf-8"))


def _summarize_codebook(project: Project) -> dict[str, Any]:
    """Generate a structural summary of the dataset from the codebook."""
    codebook = _read_codebook(project)
    meta = _read_metadata(project)

    n_rows = meta.get("n_rows", len(codebook))
    n_cols = meta.get("n_cols", len(codebook))

    # Group columns by type if available
    columns = []
    for row in codebook:
        col_info = {
            "name": row.get("name", row.get("column", "")),
            "label": row.get("label", row.get("description", "")),
            "type": row.get("type", ""),
            "values": row.get("values", row.get("value_labels", "")),
        }
        columns.append(col_info)

    return {
        "n_rows": n_rows,
        "n_cols": n_cols,
        "columns": columns[:50],  # first 50 for the prompt (full list is in the codebook)
        "total_columns": len(columns),
    }


# ---------------------------------------------------------------------------
# Question extraction
# ---------------------------------------------------------------------------

def render_question_extraction_prompt(project: Project) -> dict[str, Any]:
    """Render the question extraction prompt for the origin report."""
    from .prompts import placeholders, render_text, modules
    from .origin import _find_report, _origin_dir, _summary_path

    stage = (project.stage_ids() or ["replication"])[0]
    values = placeholders(project, stage, "Setup-Model")
    origin_dir = _origin_dir(project)
    report_path = _find_report(project, origin_dir)
    values["ORIGIN_REPORT"] = report_path.name if report_path else "(attach the origin report)"
    values["STUDY_TITLE"] = str(project.study.get("title", project.name))

    template = QUESTION_EXTRACTION_PROMPT
    rendered = render_text(template, values, modules(project.study))

    return {
        "text": rendered,
        "source": "(built-in question extraction prompt)",
        "target": "shared/QUESTIONS.md",
        "origin_report": values["ORIGIN_REPORT"],
    }


def apply_questions(project: Project, text: str, select: str | None = None) -> dict[str, Any]:
    """Apply extracted questions to shared/QUESTIONS.md.

    Parses the numbered list, writes QUESTIONS.md, and generates questions_map.yaml.
    """
    text = text.strip()
    if not text:
        raise RRGError("question extraction text is empty")

    # Parse the numbered list
    questions: list[dict[str, str]] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Match "1. question text" or "1) question text"
        m = re.match(r"^(\d+)[.)]\s+(.+)$", line)
        if m:
            num = int(m.group(1))
            q_text = m.group(2).strip()
            # Extract topic if present: "(topic: label)"
            topic_match = re.search(r"\(topic:\s*(.+?)\)", q_text, re.IGNORECASE)
            topic = topic_match.group(1).strip() if topic_match else ""
            # Clean the question text (remove the topic annotation)
            if topic_match:
                q_text = q_text[:topic_match.start()].strip()
            # Extract original number if present: "(orig: N)" or "(Q12)"
            orig_match = re.search(r"\(Q?(\d+)\)|\(orig:\s*Q?(\d+)\)", q_text, re.IGNORECASE)
            original = int(orig_match.group(1) or orig_match.group(2)) if orig_match else num
            if orig_match:
                q_text = q_text[:orig_match.start()].strip()
            questions.append({
                "new": num,
                "original": original,
                "topic": topic,
                "text": q_text,
            })

    if not questions:
        raise RRGError("no questions found in the extraction text (expected a numbered list)")

    # Filter to selected questions if --select was passed
    if select:
        selected_nums = set()
        for part in select.split(","):
            part = part.strip()
            if part:
                try:
                    selected_nums.add(int(part))
                except ValueError:
                    raise RRGError(f"invalid question number in --select: {part}")
        questions = [q for q in questions if q["new"] in selected_nums]
        if not questions:
            raise RRGError(f"no questions matched --select '{select}' (available: {','.join(str(q['new']) for q in questions)})")

    # Renumber sequentially after selection
    for new_num, q in enumerate(questions, 1):
        q["new"] = new_num

    # Write QUESTIONS.md
    questions_path = project.path("shared/QUESTIONS.md")
    questions_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Validation questions", ""]
    for q in questions:
        lines.append(f"{q['new']}. {q['text']}")
    questions_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Generate questions_map.yaml
    map_path = project.path(project.study.get("questions", {}).get("map", "questions_map.yaml"))
    map_path.parent.mkdir(parents=True, exist_ok=True)
    map_entries = [
        {"new": q["new"], "original": q["original"], "topic": q["topic"] or f"Q{q['new']}"}
        for q in questions
    ]
    map_path.write_text(
        dump_yaml({"questions": map_entries}),
        encoding="utf-8",
    )

    # Update study.yaml question count
    study = dict(project.study)
    study.setdefault("questions", {})["count"] = len(questions)
    # Write back (simple — just update the count)
    study_path = project.study_path
    existing = load_yaml(study_path)
    if "study" in existing:
        existing["study"].setdefault("questions", {})["count"] = len(questions)
        study_path.write_text(dump_yaml(existing), encoding="utf-8")

    return {
        "questions_written": str(questions_path.relative_to(project.root)),
        "map_written": str(map_path.relative_to(project.root)),
        "count": len(questions),
        "question_numbers": ",".join(str(q["new"]) for q in questions),
        "questions": [{"new": q["new"], "text": q["text"][:80]} for q in questions],
    }


# ---------------------------------------------------------------------------
# Study overview generation
# ---------------------------------------------------------------------------

def render_study_overview_prompt(project: Project) -> dict[str, Any]:
    """Render the study overview generation prompt."""
    from .prompts import placeholders, render_text, modules
    from .origin import _find_report

    stage = (project.stage_ids() or ["replication"])[0]
    values = placeholders(project, stage, "Setup-Model")
    values["STUDY_TITLE"] = str(project.study.get("title", project.name))
    values["CODEBOOK"] = project.study.get("dataset", {}).get("codebook", "data/analysis.codebook.csv").split("/")[-1]
    values["METADATA"] = project.study.get("dataset", {}).get("metadata", "data/analysis.meta.json").split("/")[-1]
    values["QUESTIONS_FILE"] = "QUESTIONS.md"

    # Include codebook summary in the prompt
    summary = _summarize_codebook(project)
    overview_context = (
        f"\n## Dataset structure (from codebook)\n\n"
        f"- Rows: {summary['n_rows']}\n"
        f"- Columns: {summary['n_cols']}\n"
        f"- First 50 column names and labels:\n"
    )
    for col in summary["columns"]:
        name = col["name"]
        label = col["label"]
        vals = col["values"]
        if label or vals:
            overview_context += f"  - {name}"
            if label:
                overview_context += f": {label}"
            if vals:
                overview_context += f" (values: {vals})"
            overview_context += "\n"
        else:
            overview_context += f"  - {name}\n"
    if summary["total_columns"] > 50:
        overview_context += f"  ... and {summary['total_columns'] - 50} more columns (see codebook)\n"

    template = STUDY_OVERVIEW_PROMPT + overview_context
    rendered = render_text(template, values, modules(project.study))

    return {
        "text": rendered,
        "source": "(built-in study overview prompt)",
        "target": "shared/STUDY_OVERVIEW.md",
    }


def apply_study_overview(project: Project, text: str) -> dict[str, Any]:
    """Apply the generated study overview to shared/STUDY_OVERVIEW.md."""
    text = text.strip()
    if not text:
        raise RRGError("study overview text is empty")
    overview_path = project.path("shared/STUDY_OVERVIEW.md")
    overview_path.parent.mkdir(parents=True, exist_ok=True)
    overview_path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    return {"written": str(overview_path.relative_to(project.root))}


# ---------------------------------------------------------------------------
# Validation instructions generation
# ---------------------------------------------------------------------------

def render_validation_instructions_prompt(project: Project) -> dict[str, Any]:
    """Render the validation instructions generation prompt."""
    from .prompts import placeholders, render_text, modules

    stage = (project.stage_ids() or ["replication"])[0]
    values = placeholders(project, stage, "Setup-Model")
    values["STUDY_TITLE"] = str(project.study.get("title", project.name))
    values["CODEBOOK"] = project.study.get("dataset", {}).get("codebook", "data/analysis.codebook.csv").split("/")[-1]
    values["QUESTIONS_FILE"] = "QUESTIONS.md"

    # Include codebook summary with value labels
    summary = _summarize_codebook(project)
    codebook_context = "\n## Codebook entries (columns with value labels)\n\n"
    for col in summary["columns"]:
        name = col["name"]
        label = col["label"]
        vals = col["values"]
        if vals:  # only include columns with value labels
            codebook_context += f"  - {name}"
            if label:
                codebook_context += f": {label}"
            codebook_context += f" → values: {vals}\n"
    if not any(c["values"] for c in summary["columns"]):
        codebook_context += "  (no value labels found in codebook — describe groups from the questions)\n"

    template = VALIDATION_INSTRUCTIONS_PROMPT + codebook_context
    rendered = render_text(template, values, modules(project.study))

    return {
        "text": rendered,
        "source": "(built-in validation instructions prompt)",
        "target": "shared/VALIDATION_INSTRUCTIONS.md",
    }


def apply_validation_instructions(project: Project, text: str) -> dict[str, Any]:
    """Apply the generated validation instructions to shared/VALIDATION_INSTRUCTIONS.md."""
    text = text.strip()
    if not text:
        raise RRGError("validation instructions text is empty")
    vi_path = project.path("shared/VALIDATION_INSTRUCTIONS.md")
    vi_path.parent.mkdir(parents=True, exist_ok=True)
    vi_path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    return {"written": str(vi_path.relative_to(project.root)) if _inside(project.root, vi_path) else str(vi_path)}


def _inside(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root.resolve())
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Setup orchestration
# ---------------------------------------------------------------------------

def regenerate_map(project: Project) -> dict[str, Any]:
    """Rebuild questions_map.yaml from the current QUESTIONS.md.

    Use this after the user edits QUESTIONS.md to remove questions they don't
    want to validate. Re-parses the numbered list and regenerates the map.
    """
    questions_path = project.path("shared/QUESTIONS.md")
    if not questions_path.is_file():
        raise RRGError("QUESTIONS.md not found — run `rrg setup --questions` first")

    text = questions_path.read_text(encoding="utf-8")
    questions: list[dict[str, str]] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(\d+)[.)]\s+(.+)$", line)
        if m:
            num = int(m.group(1))
            q_text = m.group(2).strip()
            # Try to extract topic from the question text
            topic = q_text[:50].rstrip()
            # Check for original number annotation
            orig_match = re.search(r"\(Q?(\d+)\)", q_text)
            original = int(orig_match.group(1)) if orig_match else num
            questions.append({
                "new": num,
                "original": original,
                "topic": topic,
                "text": q_text,
            })

    if not questions:
        raise RRGError("no questions found in QUESTIONS.md (expected a numbered list)")

    # Renumber sequentially (in case the user deleted some)
    renumbered = []
    for new_num, q in enumerate(questions, 1):
        renumbered.append({
            "new": new_num,
            "original": q["original"],
            "topic": q["topic"],
        })

    # Write questions_map.yaml
    map_path = project.path(project.study.get("questions", {}).get("map", "questions_map.yaml"))
    map_path.parent.mkdir(parents=True, exist_ok=True)
    map_path.write_text(dump_yaml({"questions": renumbered}), encoding="utf-8")

    # Update study.yaml count
    study_path = project.study_path
    existing = load_yaml(study_path)
    if "study" in existing:
        existing["study"].setdefault("questions", {})["count"] = len(renumbered)
        study_path.write_text(dump_yaml(existing), encoding="utf-8")

    # Also rewrite QUESTIONS.md with sequential numbering
    lines = ["# Validation questions", ""]
    for new_num, q in enumerate(questions, 1):
        lines.append(f"{new_num}. {q['text']}")
    questions_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {
        "count": len(renumbered),
        "question_numbers": ",".join(str(q["new"]) for q in renumbered),
        "map_written": str(map_path.relative_to(project.root)) if _inside(project.root, map_path) else str(map_path),
        "questions_renumbered": len(questions),
    }


def setup_status(project: Project) -> dict[str, Any]:
    """Check which setup steps are needed for a project."""
    steps = []

    # Data conversion
    dataset = project.study.get("dataset", {}) or {}
    main_name = dataset.get("main_name", "analysis")
    data_dir = project.path_setting("data", "data")
    has_csv = (data_dir / f"{main_name}.csv").exists()
    has_parquet = (data_dir / f"{main_name}.parquet").exists()
    steps.append({
        "step": "convert",
        "name": "Data conversion",
        "done": has_csv and has_parquet,
        "action": "rrg convert",
    })

    # Questions
    questions_file = project.path("shared/QUESTIONS.md")
    has_questions = questions_file.is_file() and questions_file.stat().st_size > 200
    steps.append({
        "step": "questions",
        "name": "Extract questions from origin report",
        "done": has_questions,
        "action": "rrg setup --questions",
    })

    # Questions map
    map_file = project.path(project.study.get("questions", {}).get("map", "questions_map.yaml"))
    has_map = map_file.is_file() and map_file.stat().st_size > 50
    steps.append({
        "step": "questions_map",
        "name": "Generate questions_map.yaml",
        "done": has_map,
        "action": "auto (from questions)",
    })

    # Study overview
    overview_file = project.path("shared/STUDY_OVERVIEW.md")
    has_overview = overview_file.is_file() and overview_file.stat().st_size > 200
    steps.append({
        "step": "overview",
        "name": "Generate STUDY_OVERVIEW.md",
        "done": has_overview,
        "action": "rrg setup --overview",
    })

    # Validation instructions
    vi_file = project.path("shared/VALIDATION_INSTRUCTIONS.md")
    has_vi = vi_file.is_file() and vi_file.stat().st_size > 300
    steps.append({
        "step": "instructions",
        "name": "Generate VALIDATION_INSTRUCTIONS.md",
        "done": has_vi,
        "action": "rrg setup --instructions",
    })

    # Analysis protocol
    protocol_file = project.path(
        project.study.get("original", {}).get("methodology_file", "shared/ANALYSIS_PROTOCOL_OG.md")
    )
    has_protocol = protocol_file.is_file() and protocol_file.stat().st_size > 300
    steps.append({
        "step": "protocol",
        "name": "Generate ANALYSIS_PROTOCOL_OG.md",
        "done": has_protocol,
        "action": "rrg intake (methodology prompt)",
    })

    # Origin summary
    from .origin import _summary_path
    summary_file = _summary_path(project)
    has_summary = summary_file.is_file() and summary_file.stat().st_size > 300
    steps.append({
        "step": "summary",
        "name": "Transcribe origin SUMMARY.md",
        "done": has_summary,
        "action": "rrg intake --simplified",
    })

    # Preflight
    from .doctor import inspect_project
    preflight = inspect_project(project, strict=True)
    steps.append({
        "step": "preflight",
        "name": "Preflight readiness",
        "done": preflight["ok"],
        "action": "rrg preflight",
    })

    all_done = all(s["done"] for s in steps)
    return {"steps": steps, "all_done": all_done}
