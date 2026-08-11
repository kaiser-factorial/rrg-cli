"""Tests for the prefs system (per-project .rrg_prefs.yaml)."""

from __future__ import annotations

import pytest
from pathlib import Path

from rrg_cli.project import Project
from rrg_cli.prefs import (
    DEFAULTS,
    load_prefs,
    save_prefs,
    get_pref,
    PREFS_FILENAME,
)


def _make_project(project_root: Path) -> Project:
    return Project.load(project_root)


def test_load_defaults_when_no_file(project_root: Path) -> None:
    project = _make_project(project_root)
    prefs = load_prefs(project)
    assert prefs == DEFAULTS
    assert prefs["validator"] == "manual"
    assert prefs["mode"] == "discuss"
    assert prefs["skip_normalize"] is False
    assert prefs["auto_import"] is True


def test_save_and_load(project_root: Path) -> None:
    project = _make_project(project_root)
    save_prefs(project, {"validator": "hermes", "mode": "agent"})
    prefs = load_prefs(project)
    assert prefs["validator"] == "hermes"
    assert prefs["mode"] == "agent"
    # Keys not set should fall back to defaults
    assert prefs["skip_normalize"] is False
    assert prefs["auto_import"] is True


def test_partial_override(project_root: Path) -> None:
    project = _make_project(project_root)
    save_prefs(project, {"validator": "openrouter"})
    # Save again with a different key — first key must survive
    save_prefs(project, {"mode": "nodiscuss"})
    prefs = load_prefs(project)
    assert prefs["validator"] == "openrouter"
    assert prefs["mode"] == "nodiscuss"


def test_reset(project_root: Path) -> None:
    from rrg_cli.prefs import reset_prefs
    project = _make_project(project_root)
    save_prefs(project, {"validator": "hermes", "mode": "agent"})
    reset_prefs(project)
    prefs = load_prefs(project)
    assert prefs == DEFAULTS


def test_unknown_key_preserved(project_root: Path) -> None:
    project = _make_project(project_root)
    save_prefs(project, {"validator": "hermes", "custom_key": "custom_value"})
    prefs = load_prefs(project)
    assert prefs["custom_key"] == "custom_value"
    assert prefs["validator"] == "hermes"


def test_get_pref_single_key(project_root: Path) -> None:
    project = _make_project(project_root)
    save_prefs(project, {"validator": "openrouter"})
    assert get_pref(project, "validator") == "openrouter"
    assert get_pref(project, "mode") == DEFAULTS["mode"]


def test_prefs_file_gitignored(project_root: Path) -> None:
    """The prefs file should exist at the project root."""
    project = _make_project(project_root)
    save_prefs(project, {"validator": "hermes"})
    prefs_path = project_root / PREFS_FILENAME
    assert prefs_path.exists()
