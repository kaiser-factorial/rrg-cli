"""Origin-report review: per-question separation matrix and methodology drafting.

The origin report is the human- or model-authored source of truth being validated.
It is withheld from every package; the operator GUI is the only place it is read.
"Functionally separated" means each validation question has an isolated section in
every document the pipeline threads it through, so the scorecard can score it on its
own. The separation check below reuses the exact section matcher the scorecard uses,
so a question marked "scoreable" here is one the scorecard can actually extract.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from .errors import RRGError
from .project import Project
from .prompts import modules, placeholders, render_text
from .scorecard import _markdown_section, load_question_map
from .utils import dump_yaml

REPORT_CAP_BYTES = 12 * 1024 * 1024
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
SUMMARY_NAMES = ("SUMMARY.md", "INVESTIGATION_SUMMARY.md", "RAW.md")

# Heuristics that flag results leaking into a methods-only protocol.
_LEAK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("p-value", re.compile(r"\bp\s*[=<>]\s*\.?\d", re.IGNORECASE)),
    ("test statistic", re.compile(r"\b[UDHWtFZrz]\s*=\s*-?\d", re.IGNORECASE)),
    ("chi-square", re.compile(r"(?:chi-?square|χ2|x2)\s*=\s*\d", re.IGNORECASE)),
    ("reported median/mean", re.compile(r"\b(?:median|mean|sd|std)\s*=\s*-?\d", re.IGNORECASE)),
    ("count of significant items", re.compile(r"\b\d+\s*/\s*\d+\b")),
    ("percentage finding", re.compile(r"\d\s*%")),
    ("stated conclusion", re.compile(r"\b(?:conclusion|finding|we found|results? show)\b", re.IGNORECASE)),
]

_NUMBERED_RE = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")


def parse_numbered(text: str) -> dict[int, str]:
    """Parse a markdown numbered list into {number: text}.

    Continuation lines (indented or otherwise non-numbered) extend the current
    item; a blank line ends the current item so trailing prose is not absorbed.
    """
    items: dict[int, str] = {}
    current: int | None = None
    for line in text.splitlines():
        match = _NUMBERED_RE.match(line)
        if match:
            current = int(match.group(1))
            items[current] = match.group(2).strip()
        elif current is None:
            continue
        elif not line.strip():
            current = None
        else:
            items[current] = (items[current] + " " + line.strip()).strip()
    return items


def _study_path(project: Project, key_path: list[str], default: str) -> Any:
    node: Any = project.study
    for key in key_path:
        node = (node or {}).get(key) if isinstance(node, dict) else None
    return node if node else default


def _origin_dir(project: Project) -> Path:
    key = (
        project.study.get("original", {}).get("results_key")
        or project.config.get("origin", {}).get("results_key")
        or "operator/origin"
    )
    return project.path(key)


def _find_report(project: Project, origin_dir: Path) -> Path | None:
    explicit = project.study.get("original", {}).get("report_file")
    if explicit:
        candidate = project.path(explicit)
        return candidate if candidate.is_file() else None
    if not origin_dir.is_dir():
        return None
    pdfs = sorted(origin_dir.glob("*.pdf"))
    for path in pdfs:
        if "report" in path.name.lower():
            return path
    if pdfs:
        return pdfs[0]
    docs = sorted(p for p in origin_dir.iterdir() if p.suffix.lower() in {".docx", ".html"})
    return docs[0] if docs else None


def _find_summary(project: Project, origin_dir: Path) -> Path | None:
    explicit = project.study.get("original", {}).get("summary_file")
    if explicit:
        candidate = project.path(explicit)
        return candidate if candidate.is_file() else None
    for name in SUMMARY_NAMES:
        candidate = origin_dir / name
        if candidate.is_file():
            return candidate
    return None


def _read(path: Path | None) -> str:
    if path and path.is_file():
        return path.read_text(encoding="utf-8", errors="ignore")
    return ""


def _doc(project: Project, path: Path | None, exists: bool) -> dict[str, Any]:
    return {
        "exists": exists,
        "name": path.name if path else "",
        "path": str(path.relative_to(project.root)) if path else "",
        "abs": str(path) if path else "",
    }


def origin_overview(project: Project) -> dict[str, Any]:
    origin_dir = _origin_dir(project)
    map_path = project.path(project.study.get("questions", {}).get("map", "questions_map.yaml"))
    questions = load_question_map(map_path) if map_path.is_file() else []

    questions_path = project.path(project.study.get("questions", {}).get("file", "shared/QUESTIONS.md"))
    protocol_path = project.path(
        project.study.get("original", {}).get("methodology_file", "shared/ANALYSIS_PROTOCOL_OG.md")
    )
    summary_path = _find_summary(project, origin_dir)
    report_path = _find_report(project, origin_dir)

    question_items = parse_numbered(_read(questions_path))
    protocol_items = parse_numbered(_read(protocol_path))
    summary_text = _read(summary_path)

    rows: list[dict[str, Any]] = []
    for entry in questions:
        new, original = entry["new"], entry["original"]
        question_text = question_items.get(new, "")
        protocol_text = protocol_items.get(new, "")
        origin_text = _markdown_section(summary_text, original) if summary_text else ""
        rows.append(
            {
                "new": new,
                "original": original,
                "topic": entry["topic"],
                "question": question_text,
                "protocol": protocol_text,
                "origin": origin_text,
                "has_question": bool(question_text.strip()),
                "has_protocol": bool(protocol_text.strip()),
                "has_origin": bool(origin_text.strip()),
                "ok": bool(question_text.strip() and protocol_text.strip() and origin_text.strip()),
            }
        )

    counts = {
        "total": len(rows),
        "ok": sum(1 for row in rows if row["ok"]),
        "missing_question": [row["new"] for row in rows if not row["has_question"]],
        "missing_protocol": [row["new"] for row in rows if not row["has_protocol"]],
        "missing_origin": [row["new"] for row in rows if not row["has_origin"]],
    }
    return {
        "report": {**_doc(project, report_path, bool(report_path)), "size": report_path.stat().st_size if report_path else 0},
        "summary": _doc(project, summary_path, bool(summary_path)),
        "protocol": _doc(project, protocol_path, protocol_path.is_file()),
        "questions_file": _doc(project, questions_path, questions_path.is_file()),
        "results_key": str(origin_dir.relative_to(project.root)) if _inside(project.root, origin_dir) else str(origin_dir),
        "rows": rows,
        "counts": counts,
        "ok": bool(rows) and all(row["ok"] for row in rows),
    }


def _inside(root: Path, value: Path) -> bool:
    try:
        value.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def origin_report(project: Project) -> dict[str, Any]:
    """Report metadata. PDFs are embedded via the streaming endpoint, not inlined."""
    origin_dir = _origin_dir(project)
    report_path = _find_report(project, origin_dir)
    if not report_path:
        raise RRGError("no origin report found in the results key")
    size = report_path.stat().st_size
    info = {"name": report_path.name, "size": size, "abs": str(report_path), "path": str(report_path.relative_to(project.root))}
    extension = report_path.suffix.lower()
    if size > REPORT_CAP_BYTES:
        return {**info, "kind": "toolarge"}
    if extension == ".pdf":
        return {**info, "kind": "pdf"}
    if extension in {".md", ".txt"}:
        return {**info, "kind": "text", "text": report_path.read_text(encoding="utf-8", errors="replace")[:2_000_000]}
    return {**info, "kind": "binary"}


def origin_report_bytes(project: Project) -> tuple[bytes, str]:
    """Raw PDF bytes for the inline streaming endpoint."""
    origin_dir = _origin_dir(project)
    report_path = _find_report(project, origin_dir)
    if not report_path:
        raise RRGError("no origin report found in the results key")
    if report_path.suffix.lower() != ".pdf":
        raise RRGError("origin report is not a PDF")
    if report_path.stat().st_size > REPORT_CAP_BYTES:
        raise RRGError("origin report is too large to preview")
    return report_path.read_bytes(), "application/pdf"


def _methodology_prompt_template(project: Project) -> tuple[str, str]:
    value = project.study.get("original", {}).get("methodology_prompt", "operator/OG_METHODOLOGY_PROMPT.md")
    path = project.path(value)
    if path.is_file():
        return path.read_text(encoding="utf-8"), str(path.relative_to(project.root))
    return DEFAULT_METHODOLOGY_PROMPT, "(built-in default)"


def methodology_prompt(project: Project) -> dict[str, Any]:
    stage = (project.stage_ids() or ["replication"])[0]
    values = placeholders(project, stage, "Origin-Model")
    origin_dir = _origin_dir(project)
    report_path = _find_report(project, origin_dir)
    questions_path = project.path(project.study.get("questions", {}).get("file", "shared/QUESTIONS.md"))
    protocol_path = project.path(
        project.study.get("original", {}).get("methodology_file", "shared/ANALYSIS_PROTOCOL_OG.md")
    )
    values["ORIGIN_REPORT"] = report_path.name if report_path else "(attach the origin report)"
    values["STUDY_TITLE"] = str(project.study.get("title", project.name))
    values["QUESTIONS_LIST"] = _read(questions_path).strip() or "(see {QUESTIONS_FILE})"
    template, source = _methodology_prompt_template(project)
    rendered = render_text(template, values, modules(project.study))
    return {
        "text": rendered,
        "source": source,
        "target": str(protocol_path.relative_to(project.root)),
        "origin_report": values["ORIGIN_REPORT"],
    }


def result_leak_warnings(text: str) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for index, line in enumerate(text.splitlines(), 1):
        for label, pattern in _LEAK_PATTERNS:
            if pattern.search(line):
                warnings.append({"line": index, "reason": label, "text": line.strip()[:200]})
                break
        if len(warnings) >= 30:
            break
    return warnings


def save_methodology(project: Project, text: str) -> dict[str, Any]:
    if not text.strip():
        raise RRGError("methodology text is empty")
    protocol_path = project.path(
        project.study.get("original", {}).get("methodology_file", "shared/ANALYSIS_PROTOCOL_OG.md")
    )
    protocol_path.parent.mkdir(parents=True, exist_ok=True)
    body = text if text.endswith("\n") else text + "\n"
    protocol_path.write_text(body, encoding="utf-8")
    return {
        "written": str(protocol_path.relative_to(project.root)),
        "warnings": result_leak_warnings(text),
    }


# ---------------------------------------------------------------------------
# Origin intake: normalize the origin report into the canonical SUMMARY + figures
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```+\s*ya?ml\b(.*?)```+", re.DOTALL | re.IGNORECASE)
_MANIFEST_TAIL_RE = re.compile(r"\n#{1,6}\s*\d*\.?\s*figure manifest.*$", re.IGNORECASE | re.DOTALL)
_INTAKE_REQUIRED = ("test", "statistic", "p_value", "conclusion")


def _summary_path(project: Project) -> Path:
    explicit = project.study.get("original", {}).get("summary_file")
    if explicit:
        return project.path(explicit)
    return _origin_dir(project) / "SUMMARY.md"


def _intake_questions_list(project: Project) -> str:
    """Questions keyed by the report's ORIGINAL numbering — the origin SUMMARY is
    consumed by original number, so the model must section by it."""
    map_path = project.path(project.study.get("questions", {}).get("map", "questions_map.yaml"))
    questions = load_question_map(map_path) if map_path.is_file() else []
    questions_path = project.path(project.study.get("questions", {}).get("file", "shared/QUESTIONS.md"))
    by_new = parse_numbered(_read(questions_path))
    if not questions:
        return _read(questions_path).strip()
    lines = [
        f"{entry['original']}. {by_new.get(entry['new'], entry.get('topic', '')).strip()}"
        for entry in sorted(questions, key=lambda item: item["original"])
    ]
    return "\n".join(lines)


def _intake_prompt_template(project: Project) -> tuple[str, str]:
    value = project.study.get("original", {}).get("intake_prompt", "prompts/origin_intake.md")
    path = project.path(value)
    if path.is_file():
        return path.read_text(encoding="utf-8"), str(path.relative_to(project.root))
    return DEFAULT_INTAKE_PROMPT, "(built-in default)"


def intake_prompt(project: Project) -> dict[str, Any]:
    stage = (project.stage_ids() or ["replication"])[0]
    values = placeholders(project, stage, "Origin-Model")
    origin_dir = _origin_dir(project)
    report_path = _find_report(project, origin_dir)
    summary_path = _summary_path(project)
    values["ORIGIN_REPORT"] = report_path.name if report_path else "(attach the origin report)"
    values["STUDY_TITLE"] = str(project.study.get("title", project.name))
    values["QUESTIONS_LIST"] = _intake_questions_list(project) or "(see {QUESTIONS_FILE})"
    values["SUMMARY_FILE"] = summary_path.name
    template, source = _intake_prompt_template(project)
    rendered = render_text(template, values, modules(project.study))
    return {
        "text": rendered,
        "source": source,
        "target": str(summary_path.relative_to(project.root)) if _inside(project.root, summary_path) else str(summary_path),
        "origin_report": values["ORIGIN_REPORT"],
    }


def split_intake(text: str) -> tuple[str, str]:
    """Split a returned intake into (summary_markdown, figure_map_yaml). The model
    returns the SUMMARY markdown followed by a fenced ```yaml figure_map block."""
    match = _FENCE_RE.search(text)
    if not match:
        return _MANIFEST_TAIL_RE.sub("", text).strip(), ""
    summary = _MANIFEST_TAIL_RE.sub("", text[: match.start()]).strip()
    return summary, match.group(1).strip()


def _normalize_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _apply_figure_map(origin_dir: Path, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    images = (
        [path for path in sorted(origin_dir.rglob("*")) if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS]
        if origin_dir.is_dir()
        else []
    )
    results: list[dict[str, Any]] = []
    for entry in entries:
        question = entry.get("question")
        label = str(entry.get("report_label", "")).strip()
        canonical = str(entry.get("canonical") or (f"Q{question}_fig.png" if question else "")).strip()
        record = {"question": question, "report_label": label, "canonical": canonical, "status": "", "source": ""}
        if not canonical:
            record["status"] = "skipped: no canonical name"
            results.append(record)
            continue
        target = origin_dir / Path(canonical).name
        if target.exists():
            record["status"] = "exists"
            record["source"] = target.name
            results.append(record)
            continue
        key = _normalize_label(label)
        matches = [
            path
            for path in images
            if path.name != target.name and key and (_normalize_label(path.stem) == key or key in _normalize_label(path.stem))
        ]
        if len(matches) == 1:
            origin_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(matches[0], target)
            record["status"] = "renamed"
            record["source"] = str(matches[0].relative_to(origin_dir))
        elif not matches:
            record["status"] = "no source file (figure may live in the PDF)"
        else:
            record["status"] = f"ambiguous ({len(matches)} candidates) — left for manual rename"
        results.append(record)
    return results


def intake_warnings(summary: str, project: Project) -> list[dict[str, Any]]:
    """Presence check, mirror-image of the methodology leak linter: here we WANT the
    numbers, so flag any question section missing a required field."""
    map_path = project.path(project.study.get("questions", {}).get("map", "questions_map.yaml"))
    questions = load_question_map(map_path) if map_path.is_file() else []
    warnings: list[dict[str, Any]] = []
    for entry in questions:
        section = _markdown_section(summary, entry["original"])
        if not section.strip():
            warnings.append({"question": entry["original"], "reason": "missing section", "text": f"no ## Q{entry['original']} block found"})
            continue
        lowered = section.lower()
        missing = [field for field in _INTAKE_REQUIRED if field not in lowered]
        if missing:
            warnings.append({"question": entry["original"], "reason": "missing fields", "text": ", ".join(missing)})
    return warnings


def save_intake(project: Project, text: str) -> dict[str, Any]:
    if not text.strip():
        raise RRGError("intake text is empty")
    summary, yaml_text = split_intake(text)
    if not summary:
        raise RRGError("no SUMMARY content found before the figure_map block")
    summary_path = _summary_path(project)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(summary if summary.endswith("\n") else summary + "\n", encoding="utf-8")

    entries: list[dict[str, Any]] = []
    if yaml_text:
        try:
            parsed = yaml.safe_load(yaml_text)
        except yaml.YAMLError:
            parsed = None
        if isinstance(parsed, dict):
            entries = [item for item in (parsed.get("figure_map") or []) if isinstance(item, dict)]
        elif isinstance(parsed, list):
            entries = [item for item in parsed if isinstance(item, dict)]

    origin_dir = _origin_dir(project)
    figure_results = _apply_figure_map(origin_dir, entries) if entries else []
    figure_map_written = ""
    if entries:
        origin_dir.mkdir(parents=True, exist_ok=True)
        map_path = origin_dir / "figure_map.yaml"
        map_path.write_text(dump_yaml({"figure_map": entries}), encoding="utf-8")
        figure_map_written = (
            str(map_path.relative_to(project.root)) if _inside(project.root, map_path) else str(map_path)
        )
    return {
        "summary_written": str(summary_path.relative_to(project.root)) if _inside(project.root, summary_path) else str(summary_path),
        "figure_map_written": figure_map_written,
        "figures": figure_results,
        "warnings": intake_warnings(summary, project),
    }


DEFAULT_METHODOLOGY_PROMPT = """# Methodology reconstruction — {STUDY_TITLE}

You are acting as the origin author for this study. You are given the original
report `{ORIGIN_REPORT}` and the {N_QUESTIONS} validation questions below. Produce a
**result-free reconstruction of the analysis methods** that a replication team can
follow to reproduce the analysis without ever seeing the findings.

## Validation questions

{QUESTIONS_LIST}

## Rules

- Write exactly one numbered step per question, in the same order as the questions
  above (1 through {N_QUESTIONS}).
- Describe methods only: variable construction, sample/grouping and split rules, the
  exact test and its direction or alternative, and any thresholds. Honor every held
  constant defined in `{HELD_CONSTANTS_FILE}` ({HELD_CONSTANTS_SUMMARY}).
- Do NOT include any results: no test statistics, p-values, effect sizes, medians,
  means, counts or proportions of significant items, named significant items, or
  stated conclusions. If the report gives a number inline, keep the method and drop
  the number.
- Output GitHub-flavored markdown only, suitable to save verbatim as
  `{ORIGINAL_PROTOCOL}`. Begin with a one-line title and a single sentence stating
  this is a result-free reconstruction revealed only in replication.

Return only the protocol document, nothing else.
"""


DEFAULT_INTAKE_PROMPT = """# Origin intake — {STUDY_TITLE}

You are acting as the origin author for this study. You are given the original report
`{ORIGIN_REPORT}` and the {N_QUESTIONS} validation questions below. Produce a
**faithful, structured transcription** of what the report already says for each
question, in the canonical format the grading pipeline consumes. You are normalizing
an existing report — you are NOT re-running, re-computing, or correcting anything.

## Validation questions

{QUESTIONS_LIST}

## What to produce

Two things, in this order, in a single response:

### 1. `{SUMMARY_FILE}` — one fixed block per question

Output GitHub-flavored markdown. Write exactly one section per question, in order,
each headed `## Q<n> - <topic>`, where `<n>` is the question number exactly as shown
in the list above (this is the report's own numbering). Under each heading, give a
fixed field list whose keys mirror the validator deliverable schema:

- **question** — the question text, verbatim from the list above.
- **n** — the analysis N the report used for this question.
- **groups** — how cases were split or grouped (definitions only).
- **test** — the exact test and its alternative/direction.
- **statistic** — the reported test statistic with its label.
- **p_value** — the reported p, exactly as printed. Never round a small p to 0. If the
  report states two conflicting p-values, record BOTH and do not reconcile them.
- **effect_size** — the reported effect size, or `null` if none.
- **multiplicity** — how multiple comparisons were treated, or `null`.
- **conclusion** — the report's own one-sentence conclusion.

Copy numbers exactly as the report renders them. Transcribe; do not recompute. If a
field is genuinely absent, write `not reported` — do not infer.

### 2. Figure manifest

After the summary, output a fenced ```yaml block named `figure_map` mapping each
question to the figure(s) in `{ORIGIN_REPORT}` that answer it, identified by the
report's OWN figure label, so the operator can rename them to `Q<n>_fig.png`:

```yaml
figure_map:
  - {question: 1, report_label: "Figure 1", canonical: "Q1_fig.png"}
```

Match figures to questions by content, not position. If unsure, omit that row.

## Rules

- This is a transcription task. Do not analyze, run code, or "fix" the report.
- Honor the held constants in `{HELD_CONSTANTS_FILE}` ({HELD_CONSTANTS_SUMMARY}).
- Output only the two artifacts above. No preamble, no commentary.
"""
