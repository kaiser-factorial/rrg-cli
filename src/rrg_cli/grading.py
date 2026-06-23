"""Human grading state.

A run is *graded* only when a human has confirmed a verdict for every question.
Verdicts persist as JSON per run; finalizing exports a versioned scorecard markdown
filled with those verdicts. Generating a scaffold no longer implies grading.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import RRGError
from .project import Project
from .scorecard import _markdown_section, _material, build_scorecard, load_question_map
from .utils import safe_label

VERDICTS = ["REPRODUCED", "CONVERGED", "DIVERGED", "INCOMPLETE", "GENERALIZES", "SAMPLE-SPECIFIC", "N-A"]


def _grading_dir(project: Project) -> Path:
    return project.path_setting("grading", "operator/_grading")


def _grading_path(project: Project, run_value: str) -> Path:
    digest = hashlib.sha256(run_value.encode()).hexdigest()[:12]
    return _grading_dir(project) / f"{safe_label(Path(run_value).name)}-{digest}.json"


def questions(project: Project) -> list[dict[str, Any]]:
    map_path = project.path(project.study.get("questions", {}).get("map", "questions_map.yaml"))
    return load_question_map(map_path) if map_path.is_file() else []


def load_grading(project: Project, run_value: str) -> dict[str, Any]:
    path = _grading_path(project, run_value)
    base = {"run": run_value, "verdicts": {}, "finalized": False, "scorecard": None}
    if not path.is_file():
        return base
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return base
    except (json.JSONDecodeError, OSError):
        return base
    return {**base, **data, "verdicts": data.get("verdicts") or {}}


def _write(project: Project, run_value: str, data: dict[str, Any]) -> None:
    path = _grading_path(project, run_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def is_graded(project: Project, run_value: str, question_list: list[dict[str, Any]] | None = None) -> bool:
    question_list = question_list if question_list is not None else questions(project)
    if not question_list:
        return False
    data = load_grading(project, run_value)
    confirmed = {int(key) for key, value in data["verdicts"].items() if value.get("confirmed")}
    return all(entry["new"] in confirmed for entry in question_list)


def question_material(project: Project, run_value: str, question_new: int, question_original: int) -> dict[str, str]:
    run_dir = project.path(run_value)
    key_dir = project.path(project.study.get("original", {}).get("results_key", "operator/origin"))
    summary_path = None
    for name in ("SUMMARY.md", "INVESTIGATION_SUMMARY.md", "RAW.md"):
        candidate = key_dir / name
        if candidate.is_file():
            summary_path = candidate
            break
    origin_text = ""
    if summary_path:
        origin_text = _markdown_section(summary_path.read_text(encoding="utf-8", errors="ignore"), question_original)
    validator_text = _material(run_dir, question_new) if run_dir.is_dir() else ""
    return {"origin_text": origin_text, "validator_text": validator_text}


def save_verdict(project: Project, run_value: str, question: int, verdict: str, note: str, confirmed: bool) -> dict[str, Any]:
    if verdict and verdict not in VERDICTS:
        raise RRGError(f"unknown verdict: {verdict}")
    if confirmed and not verdict:
        raise RRGError("cannot confirm an empty verdict")
    data = load_grading(project, run_value)
    if data.get("finalized"):
        data["finalized"] = False  # editing reopens a finalized run
    key = str(int(question))
    if not verdict and not note and not confirmed:
        data["verdicts"].pop(key, None)
    else:
        data["verdicts"][key] = {
            "verdict": verdict,
            "note": note,
            "confirmed": bool(confirmed),
            "at": datetime.now(timezone.utc).isoformat(),
        }
    _write(project, run_value, data)
    return overview(project, run_value)


def overview(project: Project, run_value: str) -> dict[str, Any]:
    question_list = questions(project)
    data = load_grading(project, run_value)
    rows = []
    for entry in question_list:
        verdict = data["verdicts"].get(str(entry["new"]), {})
        rows.append(
            {
                "new": entry["new"],
                "original": entry["original"],
                "topic": entry["topic"],
                "verdict": verdict.get("verdict", ""),
                "note": verdict.get("note", ""),
                "confirmed": bool(verdict.get("confirmed")),
            }
        )
    confirmed = sum(1 for row in rows if row["confirmed"])
    return {
        "run": run_value,
        "verdicts": rows,
        "confirmed": confirmed,
        "total": len(rows),
        "graded": len(rows) > 0 and confirmed == len(rows),
        "finalized": bool(data.get("finalized")),
        "scorecard": data.get("scorecard"),
        "legend": VERDICTS,
    }


def finalize(project: Project, run_value: str, stage: str, model: str, license_name: str = "record-at-run-time") -> dict[str, Any]:
    question_list = questions(project)
    if not is_graded(project, run_value, question_list):
        raise RRGError("every question needs a confirmed verdict before finalizing")
    data = load_grading(project, run_value)
    verdicts = {int(key): value for key, value in data["verdicts"].items()}
    result = build_scorecard(
        project,
        project.path(run_value),
        stage,
        model,
        license_name=license_name,
        verdicts=verdicts,
    )
    data["finalized"] = True
    data["scorecard"] = str(Path(result["path"]).relative_to(project.root))
    _write(project, run_value, data)
    return {**result, "grading": overview(project, run_value)}


def reopen(project: Project, run_value: str) -> dict[str, Any]:
    data = load_grading(project, run_value)
    data["finalized"] = False
    _write(project, run_value, data)
    return overview(project, run_value)


def delete_grading(project: Project, run_value: str) -> dict[str, Any]:
    data = load_grading(project, run_value)
    if data.get("finalized"):
        raise RRGError("grading is finalized; reopen the run before deleting")
    path = _grading_path(project, run_value)
    if path.is_file():
        path.unlink()
    return {"deleted": run_value}


def delete_scorecard(project: Project, value: str) -> dict[str, Any]:
    operator = project.path_setting("operator", "operator").resolve()
    target = project.path(value).resolve()
    target.relative_to(operator)  # confinement; raises if outside
    if not target.is_file() or not target.name.startswith("SCORECARD_") or target.suffix != ".md":
        raise RRGError("not a deletable scorecard file")
    grading_dir = _grading_dir(project)
    if grading_dir.is_dir():
        for path in grading_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if data.get("finalized") and data.get("scorecard") == value:
                raise RRGError("this scorecard belongs to a finalized grading; reopen the run to delete it")
    target.unlink()
    return {"deleted": value}
