from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .errors import RRGError
from .project import Project
from .utils import load_yaml, safe_label

FINAL_VERDICTS = {"REPRODUCED", "CONVERGED", "DIVERGED", "INCOMPLETE", "GENERALIZES", "SAMPLE-SPECIFIC", "N-A"}


def load_question_map(path: Path) -> list[dict[str, Any]]:
    data = load_yaml(path)
    rows = data.get("questions", data)
    if not isinstance(rows, list):
        raise RRGError("questions map must contain a `questions` list")
    normalized = []
    for row in rows:
        if not isinstance(row, dict) or not ({"new", "n"} & set(row)):
            raise RRGError("each question map entry needs `new` (or legacy `n`)")
        new_number = row.get("new", row.get("n"))
        original_number = row.get("original", row.get("orig", new_number))
        normalized.append(
            {
                "new": int(new_number),
                "original": int(original_number),
                "topic": str(row.get("topic", f"Question {new_number}")),
            }
        )
    return sorted(normalized, key=lambda row: row["new"])


def _markdown_section(text: str, question: int) -> str:
    pattern = re.compile(
        rf"^##+\s+(?:Question\s+|Q){question}\b.*?(?=^##+\s+(?:Question\s+|Q)\d+\b|\Z)",
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    match = pattern.search(text)
    return match.group(0).strip() if match else ""


def _material(directory: Path, question: int) -> str:
    candidates = [
        directory / "raw" / f"Q{question}_summary.json",
        directory / f"Q{question}_summary.json",
        directory / f"Q{question}.md",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        if path.suffix == ".json":
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return "; ".join(f"{key}={value}" for key, value in data.items())
            except (json.JSONDecodeError, OSError):
                return path.read_text(encoding="utf-8", errors="ignore")[:1200]
        return path.read_text(encoding="utf-8", errors="ignore")[:1200]
    for name in ("SUMMARY.md", "INVESTIGATION_SUMMARY.md", "RAW.md"):
        path = directory / name
        if path.is_file():
            section = _markdown_section(path.read_text(encoding="utf-8", errors="ignore"), question)
            if section:
                return section[:1200]
    return "_(not found)_"


def _cell(value: str) -> str:
    return re.sub(r"\s+", " ", value).replace("|", "\\|").strip()


def _next_version(output: Path, stage: str, label: str) -> tuple[int, Path | None]:
    pattern = re.compile(rf"^SCORECARD_{re.escape(stage)}_{re.escape(label)}_v(\d+)\.md$")
    versions = sorted(
        (int(match.group(1)), path)
        for path in output.glob(f"SCORECARD_{stage}_{label}_v*.md")
        if (match := pattern.match(path.name))
    )
    return (versions[-1][0] + 1, versions[-1][1]) if versions else (1, None)


def build_scorecard(
    project: Project,
    run_dir: Path,
    stage: str,
    model: str,
    *,
    key_dir: Path | None = None,
    map_path: Path | None = None,
    output_dir: Path | None = None,
    license_name: str = "record-at-run-time",
    verdicts: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    if not run_dir.is_dir():
        raise RRGError(f"run directory not found: {run_dir}")
    key_dir = (key_dir or project.path(project.study.get("original", {}).get("results_key", "operator/origin"))).resolve()
    if not key_dir.is_dir():
        raise RRGError(f"results key directory not found: {key_dir}")
    map_path = (map_path or project.path(project.study.get("questions", {}).get("map", "questions_map.yaml"))).resolve()
    questions = load_question_map(map_path)
    output_dir = (output_dir or project.path_setting("operator", "operator")).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    label = safe_label(model)
    version, prior = _next_version(output_dir, stage, label)
    destination = output_dir / f"SCORECARD_{stage}_{label}_v{version}.md"
    graded = bool(verdicts)
    subtitle = (
        "*Operator-only. Verdicts below were confirmed by a human grader.*"
        if graded
        else "*Operator-only. Every verdict is **PROVISIONAL** until confirmed by a human grader.*"
    )
    lines = [
        f"# Validation Scorecard — {stage} / {model} — v{version}",
        "",
        subtitle,
        "",
        f"- Run: `{run_dir}`",
        f"- Results key: `{key_dir}`",
        f"- Model license: {license_name}",
        f"- Prior version: `{prior.name}`" if prior else "- Prior version: none",
        "",
        "## Verdict legend",
        "",
        "`REPRODUCED` · `CONVERGED` · `DIVERGED` · `INCOMPLETE` · `GENERALIZES` · `SAMPLE-SPECIFIC` · `N-A`",
        "",
        "## Scorecard",
        "",
        "| Q | Topic | Verdict | Method vs. original | Validator material | Held-back key material | Note |",
        "|---:|---|---|---|---|---|---|",
    ]
    tally: dict[str, int] = {}
    for row in questions:
        validator = _cell(_material(run_dir, row["new"]))
        key = _cell(_material(key_dir, row["original"]))
        entry = (verdicts or {}).get(row["new"]) or (verdicts or {}).get(str(row["new"])) or {}
        verdict = str(entry.get("verdict") or "PENDING")
        note = _cell(str(entry.get("note") or "")) or f"orig Q{row['original']}"
        tally[verdict] = tally.get(verdict, 0) + 1
        verdict_cell = verdict if graded else "**PENDING**"
        lines.append(
            f"| {row['new']} | {_cell(row['topic'])} | {verdict_cell} | _(record)_ | {validator} | {key} | {note} |"
        )
    tally_rows = [f"| {name} | {count} |" for name, count in tally.items()] or ["| PENDING | 0 |"]
    lines.extend(
        [
            "",
            "## Tally",
            "",
            "| Verdict | Count |",
            "|---|---:|",
            *tally_rows,
            "",
            "## Method-choice distribution",
            "",
            "_Complete after human review._",
            "",
            "## Second-pass decisions",
            "",
            "_Record any targeted localization or rerun here._",
            "",
            "## What changed from prior version",
            "",
            "_Complete after review._" if prior else "_First version._",
            "",
        ]
    )
    text = "\n".join(lines)
    if not graded and re.search(r"\|\s*\*\*(?:" + "|".join(FINAL_VERDICTS) + r")\*\*\s*\|", text):
        raise RRGError("scorecard scaffold unexpectedly contains a final verdict")
    destination.write_text(text, encoding="utf-8")
    return {
        "path": str(destination),
        "version": version,
        "prior": str(prior) if prior else None,
        "questions": len(questions),
        "final_verdicts": 0,
    }
