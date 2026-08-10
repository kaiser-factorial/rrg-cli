"""Per-project user preferences for the RRG CLI.

Preferences are stored in ``.rrg_prefs.yaml`` at the project root and provide
defaults for ``rrg dispatch`` and ``rrg wizard`` so you don't need to pass six
flags every time.  Per-project (not global) — each study may use different
executors or modes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .project import Project

PREFS_FILENAME = ".rrg_prefs.yaml"

DEFAULTS: dict[str, Any] = {
    "executor": "manual",        # manual | hermes | openrouter | prime-agent
    "mode": "discuss",           # discuss | nodiscuss | agent
    "skip_normalize": False,    # skip auto-normalize on import?
    "auto_import": True,         # auto-import after dispatch completes?
}

# Known pref keys (for validation in CLI/TUI)
PREF_KEYS: tuple[str, ...] = ("executor", "mode", "skip_normalize", "auto_import")

EXECUTOR_OPTIONS: tuple[str, ...] = ("manual", "hermes", "openrouter", "prime-agent")
MODE_OPTIONS: tuple[str, ...] = ("discuss", "nodiscuss", "agent")


def _prefs_path(project: Project) -> Path:
    return project.root / PREFS_FILENAME


def load_prefs(project: Project) -> dict[str, Any]:
    """Load ``.rrg_prefs.yaml`` merged over :data:`DEFAULTS`.

    Missing file → DEFAULTS.  Unknown keys from the file are preserved
    (they may be used by future versions or custom workflows).
    """
    path = _prefs_path(project)
    if not path.is_file():
        return dict(DEFAULTS)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return dict(DEFAULTS)
    if not isinstance(raw, dict):
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    merged.update(raw)
    return merged


def save_prefs(project: Project, prefs: dict[str, Any]) -> None:
    """Save prefs to ``.rrg_prefs.yaml``.

    Only the provided keys are written — keys already on disk that are not in
    *prefs* are preserved (partial update).  Unknown keys are kept too.
    """
    path = _prefs_path(project)
    # Read the raw file (not merged with DEFAULTS) so we preserve exactly what
    # the user has written. Missing file → empty dict.
    if path.is_file():
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            raw = {}
        existing = raw if isinstance(raw, dict) else {}
    else:
        existing = {}
    existing.update(prefs)
    path.write_text(
        yaml.safe_dump(existing, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )


def reset_prefs(project: Project) -> None:
    """Reset prefs to DEFAULTS by removing the prefs file."""
    path = _prefs_path(project)
    if path.exists():
        path.unlink()


def get_pref(project: Project, key: str) -> Any:
    """Load prefs and return a single key."""
    return load_prefs(project).get(key)
