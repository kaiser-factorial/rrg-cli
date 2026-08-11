"""Tests for the TUI module (import and non-interactive checks)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from rrg_cli.project import Project
from rrg_cli.tui import run_tui, run_tui_prefs, run_tui_eval, _print_prefs_table


def test_tui_imports(ready_project: Project) -> None:
    """The TUI module imports cleanly."""
    assert run_tui is not None
    assert run_tui_prefs is not None
    assert run_tui_eval is not None


def test_tui_run_non_interactive(ready_project: Project, capsys) -> None:
    """run_tui runs all steps without error in non-interactive mode."""
    with patch("rich.prompt.Confirm.ask", return_value=False):
        run_tui(ready_project)
    captured = capsys.readouterr()
    assert "Commands" in captured.out
    assert "health" in captured.out.lower() or "Step" in captured.out


def test_tui_prefs_editor(ready_project: Project, capsys) -> None:
    """run_tui_prefs works with mocked input."""
    with patch("rich.prompt.Prompt.ask", side_effect=["validator", "hermes"]):
        run_tui_prefs(ready_project)
    from rrg_cli.prefs import load_prefs
    prefs = load_prefs(ready_project)
    assert prefs["validator"] == "hermes"


def test_tui_eval(ready_project: Project, tmp_path: Path, capsys) -> None:
    """run_tui_eval displays eval results."""
    import json
    # Create run dir inside the project so paths resolve correctly
    run = ready_project.root / "tmp_test_run"
    (run / "raw").mkdir(parents=True, exist_ok=True)
    (run / "Q1_analysis.py").write_text("# a")
    (run / "Q1_fig.py").write_text("# f")
    (run / "Q1_fig.png").write_bytes(b"\x89PNG")
    (run / "raw" / "Q1_raw.csv").write_text("a\n1")
    (run / "raw" / "Q1_summary.json").write_text(json.dumps({
        "question": 1, "n": 10, "test": "t", "statistic": 1, "p_value": 0.05
    }))
    (run / "REPORT.md").write_text("## Q1\n\nD\nY\nF\nA")
    run_tui_eval(ready_project, "tmp_test_run")
    captured = capsys.readouterr()
    assert "Deliverable" in captured.out


def test_print_prefs_table(ready_project: Project, capsys) -> None:
    """_print_prefs_table renders without error."""
    from rrg_cli.prefs import load_prefs
    prefs = load_prefs(ready_project)
    _print_prefs_table(prefs)
    captured = capsys.readouterr()
    assert "validator" in captured.out
