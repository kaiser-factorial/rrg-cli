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
from pathlib import Path
from typing import Any

from .errors import RRGError
from .project import Project
from .prompts import modules, placeholders, render_text
from .scorecard import _markdown_section, load_question_map

REPORT_CAP_BYTES = 12 * 1024 * 1024
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
