from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

from .errors import RRGError


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RRGError(f"configuration file not found: {path}")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise RRGError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RRGError(f"expected a mapping in {path}")
    return value


def dump_yaml(value: dict[str, Any]) -> str:
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True, width=100)


def json_dump(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


def mint_run_id() -> str:
    """An opaque, blinding-safe correlation id for one build/run.

    Carries no methodology or result information — it is a random token used to bind a
    returned result set back to the build that produced it (ADR 0002). Eight hex chars is
    ample for human-scale run counts within a project while staying short in folder names.
    """
    return secrets.token_hex(4)


def safe_label(value: str) -> str:
    label = re.sub(r"\s*\([^)]*\)\s*", "", value).strip()
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-._")
    return label or "model"


def discover_root(start: Path | None = None, override: str | Path | None = None) -> Path:
    if override:
        root = Path(override).expanduser().resolve()
        if not root.is_dir():
            raise RRGError(f"project root is not a directory: {root}")
        return root
    env = os.environ.get("RRG_PROJECT_ROOT")
    if env:
        return discover_root(override=env)
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".rrg_root").exists():
            return candidate
    raise RRGError("not inside an RRG project; run `rrg init PATH` or pass --root")


def confined(root: Path, value: str | Path) -> Path:
    candidate = Path(value)
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise RRGError(f"path escapes project root: {value}") from exc
    return resolved


def ensure_empty_target(path: Path, force: bool = False) -> None:
    if path.exists() and any(path.iterdir()):
        if not force:
            raise RRGError(f"target is not empty: {path} (use --force to scaffold into it)")
    path.mkdir(parents=True, exist_ok=True)


def normalize_permissions(root: Path) -> None:
    for path in [root, *root.rglob("*")]:
        try:
            path.chmod(0o755 if path.is_dir() else 0o644)
        except OSError:
            pass


def make_read_only(root: Path) -> None:
    """Strip write permission from a tree (files 0444, directories 0555).

    Published packages are provenance artifacts; nothing should change them after the
    zip is cut — least of all a validator that found its way back into the project.
    """
    for path in [*sorted(root.rglob("*"), reverse=True), root]:
        try:
            path.chmod(0o555 if path.is_dir() else 0o444)
        except OSError:
            pass


def _force_writable_then_retry(func, path, exc_info) -> None:  # pragma: no cover - platform dependent
    parent = Path(path).parent
    for target in (parent, Path(path)):
        try:
            target.chmod(0o755 if target.is_dir() else 0o644)
        except OSError:
            pass
    func(path)


def remove_tree(path: Path) -> None:
    """rmtree that also removes read-only trees (see :func:`make_read_only`)."""
    if path.exists():
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=lambda func, p, exc: _force_writable_then_retry(func, p, exc))
        else:
            shutil.rmtree(path, onerror=_force_writable_then_retry)
