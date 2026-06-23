"""Import a validator's returned outputs back into its operator-side run folder.

Validators run in isolation (see docs/adr/0001-validator-isolation.md) and hand back a
folder or zip. This brings those outputs into ``operator/<output_folder>/`` for review.
The returned archive is untrusted, so every entry is verified to resolve inside the run
folder (zip-slip / path-traversal protection).
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
from typing import Any

from .errors import RRGError
from .project import Project
from .utils import safe_label


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
    stage_id: str,
    model_query: str,
    source: str | Path,
    *,
    label: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    project.stage(stage_id)  # validate stage exists
    roster_entry = project.model(stage_id, model_query)
    run_label = label or safe_label(roster_entry.get("model") if roster_entry else model_query)
    destination = run_output_folder(project, stage_id, run_label, run_id).resolve()
    source = Path(source).expanduser().resolve()
    if not source.exists():
        raise RRGError(f"returned output not found: {source}")

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
        "imported": sorted(imported),
        "count": len(imported),
    }
