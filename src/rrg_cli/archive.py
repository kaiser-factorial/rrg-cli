"""Reversible deletion: archive → restore → purge (ADR 0002).

Every "delete" in RRG *moves* its target into ``operator/_archive/`` and records it in
``operator/_archive/index.jsonl`` instead of unlinking. The archive is the only place that
hard-deletes (purge); restore reverses the recorded move. ``_archive/`` is operator-only — it
is never packaged and is skipped by the runs view (``_``-prefixed).
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import RRGError
from .layout import archive_root
from .project import Project
from .utils import remove_tree


def _index_path(project: Project) -> Path:
    return archive_root(project) / "index.jsonl"


def _confined(project: Project, target: Path) -> Path:
    """Resolve ``target`` and refuse anything outside the project root."""
    resolved = target.resolve()
    try:
        resolved.relative_to(project.root.resolve())
    except ValueError as exc:
        raise RRGError(f"refusing to operate outside the project: {target}") from exc
    return resolved


def _read_index(project: Project) -> list[dict[str, Any]]:
    path = _index_path(project)
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _append_index(project: Project, record: dict[str, Any]) -> None:
    path = _index_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _rewrite_index(project: Project, records: list[dict[str, Any]]) -> None:
    path = _index_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def _move(src: Path, dst: Path) -> None:
    """Move a file or directory, including a read-only package directory.

    Published packages are read-only (utils.make_read_only). macOS refuses to rename a
    directory without write permission on it, and shutil.move refuses to touch one at
    all, so write permission is restored for the rename and stripped again afterwards.
    """
    mode: int | None = None
    if src.is_dir() and not os.access(src, os.W_OK):
        mode = src.stat().st_mode
        src.chmod(mode | stat.S_IWUSR)
    try:
        try:
            os.rename(src, dst)
        except OSError:
            shutil.move(str(src), str(dst))
    finally:
        if mode is not None:
            target = dst if dst.exists() else src
            try:
                target.chmod(mode)
            except OSError:
                pass


def archive_item(
    project: Project,
    target: str | Path,
    *,
    kind: str = "file",
    run_id: str | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Move a file or directory into the archive and log it. Returns the index record."""
    resolved = _confined(project, project.path(target))
    if not resolved.exists():
        raise RRGError(f"nothing to archive at: {target}")
    archive = archive_root(project).resolve()
    if resolved == archive or archive in resolved.parents:
        raise RRGError("item is already in the archive")
    root = project.root.resolve()
    item_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"
    bucket = archive / item_id
    bucket.mkdir(parents=True, exist_ok=False)
    destination = bucket / resolved.name
    record = {
        "id": item_id,
        "kind": kind,
        "original": str(resolved.relative_to(root)),
        "stored": str(destination.relative_to(root)),
        "name": resolved.name,
        "run_id": run_id,
        "note": note,
        "archived_at": datetime.now(timezone.utc).isoformat(),
    }
    _move(resolved, destination)
    _append_index(project, record)
    return record


def list_archive(project: Project) -> list[dict[str, Any]]:
    """Archived items, newest first, skipping any whose payload is gone."""
    root = project.root.resolve()
    live = [record for record in _read_index(project) if (root / record.get("stored", "")).exists()]
    return sorted(live, key=lambda record: record.get("archived_at", ""), reverse=True)


def _locate(project: Project, item_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    records = _read_index(project)
    record = next((item for item in records if item.get("id") == item_id), None)
    if record is None:
        raise RRGError(f"no archived item with id: {item_id}")
    return record, records


def restore_item(project: Project, item_id: str) -> dict[str, Any]:
    """Move an archived item back to its original path. Refuses to clobber an existing file."""
    record, records = _locate(project, item_id)
    root = project.root.resolve()
    stored = _confined(project, root / record["stored"])
    if not stored.exists():
        raise RRGError(f"archived payload is missing: {record['stored']}")
    original = _confined(project, root / record["original"])
    if original.exists():
        raise RRGError(f"cannot restore: something already exists at {record['original']}")
    original.parent.mkdir(parents=True, exist_ok=True)
    _move(stored, original)
    bucket = (root / record["stored"]).parent
    try:
        bucket.rmdir()
    except OSError:
        pass
    _rewrite_index(project, [item for item in records if item.get("id") != item_id])
    return {"restored": record["original"], "id": item_id}


def purge_item(project: Project, item_id: str) -> dict[str, Any]:
    """Hard-delete an archived item. Confined to the archive directory."""
    record, records = _locate(project, item_id)
    root = project.root.resolve()
    archive = archive_root(project).resolve()
    bucket = (root / record["stored"]).parent.resolve()
    if bucket != archive and archive not in bucket.parents:
        raise RRGError("refusing to purge outside the archive")
    if bucket.exists():
        remove_tree(bucket)  # packages are read-only after publish; plain rmtree would fail
    _rewrite_index(project, [item for item in records if item.get("id") != item_id])
    return {"purged": record["original"], "id": item_id}
