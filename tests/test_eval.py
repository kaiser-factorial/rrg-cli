"""Tests for the eval-lite command (deliverable contract + breach + process metrics)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from rrg_cli.project import Project
from rrg_cli.eval_lite import eval_run


def _make_conforming_run(tmp_path: Path, n: int = 3) -> Path:
    run = tmp_path / "run"
    (run / "raw").mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):
        (run / f"Q{i}_analysis.py").write_text("# analysis")
        (run / f"Q{i}_fig.py").write_text("# fig")
        (run / f"Q{i}_fig.png").write_bytes(b"\x89PNG")
        (run / "raw" / f"Q{i}_raw.csv").write_text("a,b\n1,2")
        (run / "raw" / f"Q{i}_summary.json").write_text(json.dumps({
            "question": i, "n": 100, "test": "t-test",
            "statistic": 2.5, "p_value": 0.01, "effect_size": 0.3,
            "ci": [0.1, 0.5], "conclusion": "significant"
        }))
    (run / "SUMMARY.md").write_text("## Summary\n\nAll done.")
    # Add a report with DYFA sections
    (run / "REPORT.md").write_text("\n\n".join(
        f"## Q{i}\n\nD - Do\n\nY - Why\n\nF - Find\n\nA - Answer"
        for i in range(1, n + 1)
    ))
    return run


def test_eval_conforming_run(ready_project: Project, tmp_path: Path) -> None:
    run = _make_conforming_run(tmp_path, n=3)
    result = eval_run(ready_project, run)
    assert result["deliverable_contract"]["all_conform"] is True
    assert result["breach"]["copied_secrets"] == []
    assert result["report"]


def test_eval_missing_deliverables(ready_project: Project, tmp_path: Path) -> None:
    run = tmp_path / "run"
    (run / "raw").mkdir(parents=True, exist_ok=True)
    (run / "Q1_analysis.py").write_text("# a")
    (run / "Q1_fig.png").write_bytes(b"\x89PNG")
    # Missing: raw/Q1_raw.csv, Q1_fig.py, raw/Q1_summary.json
    result = eval_run(ready_project, run)
    contract = result["deliverable_contract"]
    assert contract["all_conform"] is False
    q1 = contract["questions"][0]
    assert q1["has_raw_csv"] is False
    assert q1["has_fig_py"] is False
    assert q1["has_summary_json"] is False


def test_eval_breach_status(ready_project: Project, tmp_path: Path) -> None:
    from rrg_cli.importer import import_run
    from rrg_cli.packager import build_package
    # Build and import a run (clean, no breach)
    built = build_package(ready_project, "replication", "ReplicationModel")
    returned = tmp_path / "returned"
    returned.mkdir()
    (returned / "SUMMARY.md").write_text("## Q1\nok")
    import_run(ready_project, "replication", "ReplicationModel", returned,
               run_id=built["run_id"], normalize=False)
    # Now eval the imported run
    run_path = Path(built["output_folder"])
    result = eval_run(ready_project, run_path)
    assert "breach" in result
    assert result["breach"]["copied_secrets"] == []


def test_eval_report_contains_metrics(ready_project: Project, tmp_path: Path) -> None:
    run = _make_conforming_run(tmp_path, n=3)
    result = eval_run(ready_project, run)
    report = result["report"]
    assert "Deliverable contract" in report
    assert "Breach status" in report


def test_eval_file_count(ready_project: Project, tmp_path: Path) -> None:
    run = _make_conforming_run(tmp_path, n=2)
    result = eval_run(ready_project, run)
    assert result["file_count"] > 0


def test_eval_json_output(ready_project: Project, tmp_path: Path) -> None:
    run = _make_conforming_run(tmp_path, n=3)
    result = eval_run(ready_project, run)
    # Should be JSON-serializable
    json.dumps(result)
