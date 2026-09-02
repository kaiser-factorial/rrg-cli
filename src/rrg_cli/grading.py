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

from . import archive as archive_module
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


def _breach_path(project: Project, run_value: str) -> Path:
    digest = hashlib.sha256(run_value.encode()).hexdigest()[:12]
    return _grading_dir(project) / f"{safe_label(Path(run_value).name)}-{digest}.breach.json"


def load_breach(project: Project, run_value: str) -> dict[str, Any] | None:
    """The breach record for a run (ADR 0002), or None if the run is clean."""
    path = _breach_path(project, run_value)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def record_breach(
    project: Project,
    run_value: str,
    *,
    copied_secrets: list[dict[str, str]],
    ran_inside_project: bool,
    wrote_inside_project: list[dict[str, str]] | None = None,
) -> dict[str, Any] | None:
    """Persist (or clear) a run's breach state after an import.

    A *copied secret* — a returned file whose content matches the withheld answer key — is a
    hard breach that blocks grading until acknowledged. So is *writing inside the project*:
    a validator that created or changed files in the project tree during dispatch had
    reached the tree, and therefore could have read anything withheld. ``ran_inside_project``
    is a softer signal (the run may have executed without isolation) that is recorded but
    does not block. A fully clean import clears any prior record.
    """
    wrote_inside_project = wrote_inside_project or []
    path = _breach_path(project, run_value)
    if not copied_secrets and not ran_inside_project and not wrote_inside_project:
        path.unlink(missing_ok=True)
        return None
    record = {
        "run": run_value,
        "copied_secrets": copied_secrets,
        "ran_inside_project": bool(ran_inside_project),
        "wrote_inside_project": wrote_inside_project,
        "blocking": bool(copied_secrets or wrote_inside_project),
        "acknowledged": False,
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return record


def acknowledge_breach(project: Project, run_value: str) -> dict[str, Any]:
    breach = load_breach(project, run_value)
    if not breach:
        raise RRGError("no breach is recorded for this run")
    breach["acknowledged"] = True
    breach["acknowledged_at"] = datetime.now(timezone.utc).isoformat()
    _breach_path(project, run_value).write_text(
        json.dumps(breach, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return breach


def _guard_breach(project: Project, run_value: str) -> None:
    breach = load_breach(project, run_value)
    if breach and breach.get("blocking") and not breach.get("acknowledged"):
        count = len(breach.get("copied_secrets") or [])
        wrote = len(breach.get("wrote_inside_project") or [])
        reasons = []
        if count:
            reasons.append(f"{count} returned file(s) match the withheld answer key")
        if wrote:
            reasons.append(f"the validator wrote {wrote} file(s) inside the project tree")
        raise RRGError(
            f"blinding breach: {'; '.join(reasons)}; grading is blocked until the breach is acknowledged"
        )


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
    _guard_breach(project, run_value)
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
        "breach": load_breach(project, run_value),
        "legend": VERDICTS,
    }


def finalize(project: Project, run_value: str, stage: str, model: str, license_name: str = "record-at-run-time") -> dict[str, Any]:
    _guard_breach(project, run_value)
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
    if not path.is_file():
        return {"archived": run_value, "id": None}
    record = archive_module.archive_item(
        project, str(path.relative_to(project.root)), kind="grading"
    )
    return {"archived": run_value, "id": record["id"]}


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
    record = archive_module.archive_item(project, value, kind="scorecard")
    return {"archived": value, "id": record["id"]}
