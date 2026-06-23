"""Import a validator's returned outputs back into its operator-side run folder.

Validators run in isolation (see docs/adr/0001-validator-isolation.md) and hand back a
folder or zip. This brings those outputs into ``operator/<output_folder>/`` for review.
The returned archive is untrusted, so every entry is verified to resolve inside the run
folder (zip-slip / path-traversal protection).
"""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

from .errors import RRGError
from .project import Project
from .utils import safe_label

RUN_MARKER_NAME = "RRG_RUN.txt"


def render_run_marker(run_id: str) -> str:
    """The blinding-safe marker shipped in a delivery zip (ADR 0002).

    Contains only the opaque ``run_id`` — no study, method, or result information. The
    validator is asked to return it unchanged so RRG can bind their results back to this build.
    """
    return (
        f"run_id: {run_id}\n"
        "\n"
        "This file binds your returned results to the validation package you received.\n"
        "Please return it unchanged alongside your outputs. It is an opaque identifier and\n"
        "carries no information about the study, its methods, or any expected result.\n"
    )


def parse_run_marker(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("run_id:"):
            value = stripped.split(":", 1)[1].strip()
            return value or None
    return None


def read_run_marker(source: Path) -> str | None:
    """Best-effort read of the ``run_id`` from a returned folder or zip; None if absent."""
    try:
        if source.is_file() and source.suffix.lower() == ".zip":
            with zipfile.ZipFile(source) as bundle:
                names = [name for name in bundle.namelist() if Path(name).name == RUN_MARKER_NAME]
                if not names:
                    return None
                with bundle.open(sorted(names, key=len)[0]) as handle:
                    return parse_run_marker(handle.read().decode("utf-8", "replace"))
        if source.is_dir():
            direct = source / RUN_MARKER_NAME
            candidate = direct if direct.is_file() else next(iter(sorted(source.rglob(RUN_MARKER_NAME))), None)
            if candidate and candidate.is_file():
                return parse_run_marker(candidate.read_text(encoding="utf-8", errors="replace"))
    except (OSError, zipfile.BadZipFile):
        return None
    return None


def lookup_provenance(project: Project, run_id: str) -> dict[str, Any] | None:
    """Return the most recent provenance-log record whose run_id matches, or None."""
    log_path = project.path_setting("packages", "operator/_packages") / "provenance_log.jsonl"
    if not log_path.is_file():
        return None
    found: dict[str, Any] | None = None
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("run_id") == run_id:
            found = record
    return found


def run_output_folder(
    project: Project, stage_id: str, run_label: str, run_id: str | None = None
) -> Path:
    """Resolve the operator-side run folder for a (stage, model) pair.

    With an explicit ``run_id`` (ADR 0002), the folder is the run_id-suffixed slug the build
    created. Without one, we resolve the newest run_id-suffixed folder that a build left for
    this label; if none exists (pre-ADR-0002 layout, or a manual import with no prior build)
    we fall back to the legacy un-suffixed name.
    """
    stage = project.stage(stage_id)
    operator_root = project.path_setting("operator", "operator")
    template = str(stage.get("output_folder", f"{stage_id}_{{model}}"))
    if run_id:
        slug = f"{run_label}__{run_id}"
        return operator_root / template.format(model=slug, MODEL=slug)
    base = template.format(model=run_label, MODEL=run_label)
    if operator_root.is_dir():
        matches = sorted(operator_root.glob(f"{base}__*"), key=lambda path: path.stat().st_mtime)
        if matches:
            return matches[-1]
    return operator_root / base


def _safe_target(destination: Path, member: str) -> Path:
    target = (destination / member).resolve()
    try:
        target.relative_to(destination)
    except ValueError as exc:  # zip-slip / traversal
        raise RRGError(f"refusing entry outside the run folder: {member}") from exc
    return target


def import_run(
    project: Project,
    stage_id: str | None = None,
    model_query: str | None = None,
    source: str | Path | None = None,
    *,
    label: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    if source is None:
        raise RRGError("a returned folder or .zip is required")
    source = Path(source).expanduser().resolve()
    if not source.exists():
        raise RRGError(f"returned output not found: {source}")

    # Auto-resolve from the in-package RRG_RUN.txt marker (ADR 0002). An explicit run_id wins;
    # otherwise the marker supplies it. A matching provenance record fills in any stage/model/
    # label not given by the caller. Explicit arguments always take precedence.
    run_id = run_id or read_run_marker(source)
    record = lookup_provenance(project, run_id) if run_id else None
    matched = bool(record)
    if record:
        stage_id = stage_id or record.get("stage")
        model_query = model_query or record.get("model")
        if label is None:
            label = record.get("label")
    if not stage_id or not model_query:
        raise RRGError(
            "could not resolve the run: no RRG_RUN.txt marker matched a logged build; "
            "pass --stage and --model explicitly"
        )

    project.stage(stage_id)  # validate stage exists
    roster_entry = project.model(stage_id, model_query)
    run_label = label or safe_label(roster_entry.get("model") if roster_entry else model_query)
    destination = run_output_folder(project, stage_id, run_label, run_id).resolve()

    destination.mkdir(parents=True, exist_ok=True)
    imported: list[str] = []

    if source.is_file() and source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as bundle:
            for member in bundle.namelist():
                if member.endswith("/"):
                    continue
                target = _safe_target(destination, member)
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                imported.append(str(target.relative_to(destination)))
    elif source.is_dir():
        for path in sorted(source.rglob("*")):
            if not path.is_file() or path.name == ".DS_Store":
                continue
            target = _safe_target(destination, str(path.relative_to(source)))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            imported.append(str(target.relative_to(destination)))
    else:
        raise RRGError("returned output must be a .zip file or a directory")

    return {
        "run": str(destination.relative_to(project.root)),
        "output_folder": str(destination),
        "run_id": run_id,
        "stage": stage_id,
        "model": model_query,
        "auto_resolved": matched,
        "imported": sorted(imported),
        "count": len(imported),
    }
