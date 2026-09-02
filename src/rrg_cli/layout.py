"""Canonical operator-side paths with compatibility for existing projects.

New projects keep immutable outgoing packages, returned runs, reviews, grading state,
and reversible archives in named subdirectories under ``operator/``.  Existing projects
that do not declare the new paths retain their historical locations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .project import Project


def operator_root(project: Project) -> Path:
    return project.path_setting("operator", "operator")


def packages_root(project: Project) -> Path:
    return project.path_setting("packages", "operator/_packages")


def runs_root(project: Project) -> Path:
    paths = project.config.get("paths", {}) or {}
    return project.path_setting("runs", "operator") if "runs" in paths else operator_root(project)


def reviews_root(project: Project) -> Path:
    paths = project.config.get("paths", {}) or {}
    return project.path_setting("reviews", "operator") if "reviews" in paths else operator_root(project)


def grading_root(project: Project) -> Path:
    return project.path_setting("grading", "operator/_grading")


def archive_root(project: Project) -> Path:
    paths = project.config.get("paths", {}) or {}
    return project.path_setting("archive", "operator/_archive") if "archive" in paths else operator_root(project) / "_archive"


def run_destination(project: Project, stage: str, label: str, run_id: str | None) -> Path:
    root = runs_root(project)
    name = f"{label}__{run_id or 'norunid'}"
    if root.resolve() == operator_root(project).resolve():
        return root / f"{stage}_{name}"
    return root / stage / name


def layout_status(project: Project) -> dict[str, str]:
    """Resolved, project-relative operator paths for human and agent inspection."""
    roots = {
        "operator": operator_root(project),
        "runs": runs_root(project),
        "packages": packages_root(project),
        "reviews": reviews_root(project),
        "grading": grading_root(project),
        "archive": archive_root(project),
    }
    return {name: str(path.resolve().relative_to(project.root.resolve())) for name, path in roots.items()}


def provenance_run_path(project: Project, record: dict[str, Any]) -> Path | None:
    """Resolve a logged run path portably, accepting legacy absolute records."""
    relative = record.get("output_path")
    if relative:
        return project.path(str(relative)).resolve()
    absolute = record.get("output_folder")
    if absolute:
        candidate = Path(str(absolute)).expanduser().resolve()
        try:
            candidate.relative_to(operator_root(project).resolve())
            return candidate
        except ValueError:
            pass
    stage = record.get("stage")
    label = record.get("label") or record.get("model")
    run_id = record.get("run_id")
    if stage and label and run_id:
        return run_destination(project, str(stage), str(label), str(run_id)).resolve()
    return None
