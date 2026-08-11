\
"""Tests for the wizard (interactive setup walkthrough)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from rrg_cli.project import Project
from rrg_cli.wizard import run_wizard, wizard_prefs_editor
from rrg_cli.prefs import DEFAULTS, load_prefs


def test_wizard_non_interactive_all_steps(ready_project: Project) -> None:
    result = run_wizard(ready_project, non_interactive=True)
    assert "steps" in result
    assert len(result["steps"]) == 5
    assert result["steps"][0]["name"] == "health"
    assert result["steps"][1]["name"] == "conversion"
    assert result["steps"][2]["name"] == "preflight"
    assert result["steps"][3]["name"] == "roster"
    assert result["steps"][4]["name"] == "dispatch"
    # All steps should have a status
    for step in result["steps"]:
        assert step["status"] in ("ok", "warning", "error", "skipped")


def test_wizard_health_check(ready_project: Project) -> None:
    result = run_wizard(ready_project, non_interactive=True)
    health = result["steps"][0]
    assert health["name"] == "health"
    assert health["status"] == "ok"
    # Should check for .rrg_root, rrg.yaml, study.yaml
    check_names = [c["name"] for c in health["checks"]]
    assert ".rrg_root" in check_names
    assert "rrg.yaml" in check_names
    assert "study.yaml" in check_names


def test_wizard_conversion_check(ready_project: Project) -> None:
    result = run_wizard(ready_project, non_interactive=True)
    conversion = result["steps"][1]
    assert conversion["name"] == "conversion"
    # The ready_project fixture has converted derivatives
    assert conversion["status"] in ("ok", "warning")


def test_wizard_preflight_check(ready_project: Project) -> None:
    result = run_wizard(ready_project, non_interactive=True)
    preflight = result["steps"][2]
    assert preflight["name"] == "preflight"
    assert preflight["status"] in ("ok", "warning")


def test_wizard_roster_display(ready_project: Project) -> None:
    result = run_wizard(ready_project, non_interactive=True)
    roster = result["steps"][3]
    assert roster["name"] == "roster"
    # The starter project has roster entries
    assert "models" in roster or "checks" in roster


def test_wizard_jump_to_step(ready_project: Project) -> None:
    result = run_wizard(ready_project, non_interactive=True, step=3)
    # Should only run steps up to and including step 3
    assert len(result["steps"]) <= 3


def test_wizard_prefs_editor_sets_value(ready_project: Project) -> None:
    # Simulate the user choosing to set validator to hermes
    with patch("builtins.input", side_effect=["validator", "hermes", ""]):
        result = wizard_prefs_editor(ready_project)
    prefs = load_prefs(ready_project)
    assert prefs["validator"] == "hermes"


def test_wizard_prefs_reset(ready_project: Project) -> None:
    from rrg_cli.prefs import save_prefs
    save_prefs(ready_project, {"validator": "hermes", "mode": "agent"})
    with patch("builtins.input", side_effect=["reset", ""]):
        result = wizard_prefs_editor(ready_project)
    prefs = load_prefs(ready_project)
    assert prefs == DEFAULTS
