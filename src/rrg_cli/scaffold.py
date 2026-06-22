from __future__ import annotations

import shutil
from importlib.resources import as_file, files
from pathlib import Path

from .errors import RRGError
from .utils import ensure_empty_target


def init_project(target: Path, force: bool = False) -> list[Path]:
    target = target.expanduser().resolve()
    ensure_empty_target(target, force=force)
    template_root = files("rrg_cli").joinpath("templates/project")
    created: list[Path] = []
    with as_file(template_root) as source:
        for item in sorted(source.rglob("*")):
            relative = item.relative_to(source)
            destination = target / relative
            if item.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            if destination.exists() and not force:
                raise RRGError(f"refusing to overwrite: {destination}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item, destination)
            created.append(destination)
    marker = target / ".rrg_root"
    marker.touch(exist_ok=True)
    created.append(marker)
    return created
