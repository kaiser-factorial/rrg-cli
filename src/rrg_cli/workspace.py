from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, TypeVar

from .doctor import inspect_project
from .errors import RRGError
from .gui_service import GUIState
from .project import Project
from .scaffold import init_project

T = TypeVar("T")

EXCLUDED_DISCOVERY_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "node_modules",
    "data",
    "operator",
    "shared",
}


def _inside(root: Path, value: Path) -> bool:
    try:
        value.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def discover_project_roots(workspace: Path) -> list[Path]:
    workspace = workspace.expanduser().resolve()
    if not workspace.is_dir():
        raise RRGError(f"workspace directory not found: {workspace}")
    roots: list[Path] = []
    for current, directories, files in os.walk(workspace, followlinks=False):
        directories[:] = sorted(
            name
            for name in directories
            if name not in EXCLUDED_DISCOVERY_DIRS and not name.startswith(".")
        )
        current_path = Path(current)
        if ".rrg_root" in files and _inside(workspace, current_path):
            roots.append(current_path.resolve())
    return sorted(set(roots), key=lambda path: (len(path.relative_to(workspace).parts), str(path).lower()))


def initial_workspace_project(workspace: Path, requested: str | Path | None = None) -> Project:
    workspace = workspace.expanduser().resolve()
    if requested is not None:
        candidate = Path(requested).expanduser()
        root = (workspace / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        if not _inside(workspace, root):
            raise RRGError("initial project must be inside the workspace")
        return Project.load(root)
    roots = discover_project_roots(workspace)
    for root in roots:
        try:
            return Project.load(root)
        except RRGError:
            continue
    raise RRGError(f"no valid RRG projects found below workspace: {workspace}")


class WorkspaceState:
    """Serialize project selection and all active-project GUI operations."""

    def __init__(self, project: Project, workspace: str | Path | None = None):
        self._lock = threading.RLock()
        self.workspace = Path(workspace).expanduser().resolve() if workspace is not None else None
        if self.workspace is not None:
            if not self.workspace.is_dir():
                raise RRGError(f"workspace directory not found: {self.workspace}")
            if not _inside(self.workspace, project.root):
                raise RRGError("active project must be inside the workspace")
        self._state = GUIState(project)

    @property
    def project(self) -> Project:
        with self._lock:
            return self._state.project

    def _call(self, method: str, *args, **kwargs):
        with self._lock:
            return getattr(self._state, method)(*args, **kwargs)

    def _relative(self, root: Path) -> str:
        if self.workspace is None:
            return str(root)
        relative = root.resolve().relative_to(self.workspace)
        return "." if not relative.parts else str(relative)

    def workspace_status(self) -> dict[str, Any]:
        with self._lock:
            if self.workspace is None:
                return {
                    "enabled": False,
                    "root": None,
                    "active": str(self._state.project.root),
                    "projects": [],
                }
            projects = []
            for root in discover_project_roots(self.workspace):
                record: dict[str, Any] = {
                    "root": self._relative(root),
                    "path": str(root),
                    "active": root == self._state.project.root,
                    "valid": True,
                    "error": "",
                }
                try:
                    project = Project.load(root)
                    record["name"] = project.name
                except RRGError as exc:
                    record.update({"name": root.name, "valid": False, "error": str(exc)})
                projects.append(record)
            return {
                "enabled": True,
                "root": str(self.workspace),
                "active": self._relative(self._state.project.root),
                "projects": projects,
            }

    def bootstrap(self) -> dict[str, Any]:
        with self._lock:
            return {**self._state.bootstrap(), "workspace": self.workspace_status()}

    def select_project(self, root_value: str) -> dict[str, Any]:
        with self._lock:
            if self.workspace is None:
                raise RRGError("GUI is running in single-project mode")
            allowed = {self._relative(root): root for root in discover_project_roots(self.workspace)}
            if root_value not in allowed:
                raise RRGError("project is not an allowed workspace project")
            project = Project.load(allowed[root_value])
            self._state = GUIState(project)
            return self.bootstrap()

    def create_project(self, path_value: str, name: str) -> dict[str, Any]:
        with self._lock:
            if self.workspace is None:
                raise RRGError("GUI is running in single-project mode")
            relative = Path(path_value.strip())
            if (
                not path_value.strip()
                or relative.is_absolute()
                or any(part in {"", ".", ".."} or part.startswith(".") for part in relative.parts)
            ):
                raise RRGError("new project path must be a non-empty workspace-relative child path")
            target = (self.workspace / relative).resolve()
            if not _inside(self.workspace, target) or target == self.workspace:
                raise RRGError("new project must remain inside the workspace")
            if target.exists():
                raise RRGError("new project path already exists")
            display_name = name.strip() or target.name
            init_project(target)
            project = Project.load(target)
            state = GUIState(project)
            state.save_setup({"study": {"title": display_name}, "engine": {"project_name": display_name}})
            self._state = state
            return self.bootstrap()

    def preflight(self, stage: str | None = None) -> dict[str, Any]:
        with self._lock:
            return inspect_project(self._state.project, stage=stage, strict=True)

    def render(self, *args, **kwargs):
        return self._call("render", *args, **kwargs)

    def runs(self):
        return self._call("runs")

    def run_detail(self, *args, **kwargs):
        return self._call("run_detail", *args, **kwargs)

    def run_file(self, *args, **kwargs):
        return self._call("run_file", *args, **kwargs)

    def compare(self, *args, **kwargs):
        return self._call("compare", *args, **kwargs)

    def scorecards(self):
        return self._call("scorecards")

    def scorecard_content(self, *args, **kwargs):
        return self._call("scorecard_content", *args, **kwargs)

    def convert(self, *args, **kwargs):
        return self._call("convert", *args, **kwargs)

    def package(self, *args, **kwargs):
        return self._call("package", *args, **kwargs)

    def make_scorecard(self, *args, **kwargs):
        return self._call("make_scorecard", *args, **kwargs)

    def save_note(self, *args, **kwargs):
        return self._call("save_note", *args, **kwargs)

    def save_setup(self, *args, **kwargs):
        return self._call("save_setup", *args, **kwargs)
