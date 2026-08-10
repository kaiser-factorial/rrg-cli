\
"""Tests for the output normalizer (parse non-conforming returns into canonical shape)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from rrg_cli.project import Project
from rrg_cli.normalize import (
    check_deliverable_contract,
    normalize_run,
    _fuzzy_match_q_files,
    _parse_summary_from_text,
)


def _make_run_dir(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    run.mkdir(parents=True, exist_ok=True)
    (run / "raw").mkdir(exist_ok=True)
    return run


def _make_project(ready_project: Project) -> Project:
    return ready_project


# --- Contract check ---

def test_contract_check_conforming(ready_project: Project) -> None:
    run = _make_run_dir(ready_project.root / "tmp_test")
    n = 3  # starter project has 3 questions
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
    (run / "REPORT.md").write_text("\n\n".join(
        f"## Q{i}\n\nD - Do\n\nY - Why\n\nF - Find\n\nA - Answer"
        for i in range(1, n + 1)
    ))
    result = check_deliverable_contract(run, n)
    assert all(q["has_analysis"] for q in result["questions"])
    assert all(q["has_raw_csv"] for q in result["questions"])
    assert all(q["has_fig_py"] for q in result["questions"])
    assert all(q["has_fig_png"] for q in result["questions"])
    assert all(q["has_summary_json"] for q in result["questions"])
    assert all(q["has_dyfa_section"] for q in result["questions"])
    assert result["all_conform"]


def test_contract_check_missing_files(ready_project: Project) -> None:
    run = _make_run_dir(ready_project.root / "tmp_test")
    # Only one question, missing summary.json and fig.py
    (run / "Q1_analysis.py").write_text("# analysis")
    (run / "Q1_fig.png").write_bytes(b"\x89PNG")
    result = check_deliverable_contract(run, 1)
    q = result["questions"][0]
    assert q["has_analysis"] is True
    assert q["has_raw_csv"] is False
    assert q["has_fig_py"] is False
    assert q["has_fig_png"] is True
    assert q["has_summary_json"] is False
    assert result["all_conform"] is False


# --- Fuzzy matching ---

def test_fuzzy_match_q_files(tmp_path: Path) -> None:
    run = _make_run_dir(tmp_path)
    # Various naming conventions
    (run / "q1_analysis.py").write_text("# a")
    (run / "Q01_fig.png").write_bytes(b"\x89PNG")
    (run / "analysis_q2.py").write_text("# a")
    (run / "visual_q1.png").write_bytes(b"\x89PNG")
    (run / "q2_fig1.png").write_bytes(b"\x89PNG")
    (run / "Q3_analysis.py").write_text("# a")

    matches = _fuzzy_match_q_files(run)
    # Should find question numbers 1, 2, 3
    assert 1 in matches
    assert 2 in matches
    assert 3 in matches
    # Check the mapping for question 1
    assert any("analysis" in str(p) for p in matches[1]["analysis"])
    assert any("fig" in str(p) and p.suffix == ".png" for p in matches[1]["figures"])
    # Question 2 should have analysis and figure
    assert matches[2]["analysis"]
    assert matches[2]["figures"]


def test_fuzzy_match_no_q_files(tmp_path: Path) -> None:
    run = _make_run_dir(tmp_path)
    (run / "random.py").write_text("# not a q file")
    matches = _fuzzy_match_q_files(run)
    assert matches == {}


# --- Parse summary from text ---

def test_parse_summary_from_results_txt(tmp_path: Path) -> None:
    text = """\
Q1 Results
---------
N = 100
Test: chi-square
Statistic: 45.3
p-value: 0.001
Effect size (Cramer's V): 0.67
95% CI: [0.45, 0.89]
Conclusion: Significant association found.
"""
    result = _parse_summary_from_text(text, 1)
    assert result is not None
    assert result["question"] == 1
    assert result["n"] == 100
    assert result["test"] == "chi-square"
    assert result["statistic"] == 45.3
    assert result["p_value"] == 0.001
    assert "0.67" in str(result["effect_size"])
    assert result["conclusion"] is not None


def test_parse_summary_from_text_none(tmp_path: Path) -> None:
    result = _parse_summary_from_text("no useful info here", 1)
    assert result is None


# --- Normalize run ---

def test_normalize_conforming_no_changes(ready_project: Project) -> None:
    run = _make_run_dir(ready_project.root / "tmp_test")
    n = 3
    for i in range(1, n + 1):
        (run / f"Q{i}_analysis.py").write_text("# analysis")
        (run / f"Q{i}_fig.py").write_text("# fig")
        (run / f"Q{i}_fig.png").write_bytes(b"\x89PNG")
        (run / "raw" / f"Q{i}_raw.csv").write_text("a,b\n1,2")
        (run / "raw" / f"Q{i}_summary.json").write_text(json.dumps({
            "question": i, "n": 100, "test": "t-test",
            "statistic": 2.5, "p_value": 0.01, "effect_size": 0.3,
            "ci": [0.1, 0.5], "conclusion": "ok"
        }))
    (run / "SUMMARY.md").write_text("## Summary")
    result = normalize_run(ready_project, run)
    assert result["files_moved"] == []
    assert result["summary_json_created"] == []
    assert all(q["status"] == "ok" for q in result["normalized"])


def test_normalize_renames_fuzzy_files(ready_project: Project) -> None:
    run = _make_run_dir(ready_project.root / "tmp_test")
    (run / "q1_analysis.py").write_text("# a")
    (run / "Q01_fig.png").write_bytes(b"\x89PNG")
    (run / "visual_q1.png").write_bytes(b"\x89PNG")
    result = normalize_run(ready_project, run)
    assert (run / "Q1_analysis.py").exists()
    assert (run / "Q1_fig.png").exists()
    assert len(result["files_moved"]) > 0


def test_normalize_creates_summary_from_text(ready_project: Project) -> None:
    run = _make_run_dir(ready_project.root / "tmp_test")
    (run / "Q1_analysis.py").write_text("# a")
    (run / "Q1_fig.png").write_bytes(b"\x89PNG")
    (run / "raw" / "Q1_raw.csv").write_text("a,b\n1,2")
    (run / "q1_results.txt").write_text(
        "N = 100\nTest: t-test\nStatistic: 2.5\np-value: 0.01\n"
        "Effect size: 0.3\nConclusion: significant"
    )
    result = normalize_run(ready_project, run)
    assert 1 in result["summary_json_created"]
    summary_path = run / "raw" / "Q1_summary.json"
    assert summary_path.exists()
    data = json.loads(summary_path.read_text())
    assert data["question"] == 1
    assert data["n"] == 100


def test_normalize_preserves_originals(ready_project: Project) -> None:
    run = _make_run_dir(ready_project.root / "tmp_test")
    original = run / "q1_analysis.py"
    original.write_text("# original")
    normalize_run(ready_project, run)
    assert original.exists(), "original file should not be deleted"


def test_normalize_missing_question(ready_project: Project) -> None:
    run = _make_run_dir(ready_project.root / "tmp_test")
    # Only question 1, but project expects 3
    (run / "Q1_analysis.py").write_text("# a")
    result = normalize_run(ready_project, run)
    missing = result["missing"]
    assert 2 in missing
    assert 3 in missing


def test_normalize_idempotent(ready_project: Project) -> None:
    run = _make_run_dir(ready_project.root / "tmp_test")
    (run / "q1_analysis.py").write_text("# a")
    (run / "Q01_fig.png").write_bytes(b"\x89PNG")
    first = normalize_run(ready_project, run)
    second = normalize_run(ready_project, run)
    assert second["files_moved"] == [], "second run should move nothing"
    assert second["summary_json_created"] == []



# --- Import integration ---

def test_import_auto_normalize(ready_project: Project, tmp_path: Path) -> None:
    """import_run with normalize=True runs the normalizer."""
    from rrg_cli.packager import build_package
    from rrg_cli.importer import import_run

    build_package(ready_project, "replication", "ReplicationModel")
    returned = tmp_path / "returned"
    returned.mkdir()
    # Non-conforming: lowercase q1 instead of Q1
    (returned / "q1_analysis.py").write_text("# a", encoding="utf-8")
    (returned / "q1_fig.png").write_bytes(b"\x89PNG")
    result = import_run(
        ready_project, "replication", "ReplicationModel", returned,
        normalize=True,
    )
    assert result["normalize"] is not None
    # The normalizer should have renamed q1_analysis.py → Q1_analysis.py
    assert (Path(result["output_folder"]) / "Q1_analysis.py").exists()


def test_import_skip_normalize(ready_project: Project, tmp_path: Path) -> None:
    """import_run with normalize=False skips the normalizer."""
    from rrg_cli.packager import build_package
    from rrg_cli.importer import import_run

    built = build_package(ready_project, "replication", "ReplicationModel")
    returned = tmp_path / "returned"
    returned.mkdir()
    (returned / "q1_analysis.py").write_text("# a", encoding="utf-8")
    result = import_run(
        ready_project, "replication", "ReplicationModel", returned,
        run_id=built["run_id"],
        normalize=False,
    )
    assert result["normalize"] is None
    out = Path(result["output_folder"])
    # q1_analysis.py should still be there (copied as-is)
    assert (out / "q1_analysis.py").exists()
    # Q1_analysis.py should NOT exist (normalizer didn't run)
    # Note: macOS is case-insensitive, so check actual filenames in the listing.
    filenames = [p.name for p in out.iterdir()]
    assert "Q1_analysis.py" not in filenames, f"normalizer should not have run, but found Q1_analysis.py. Files: {filenames}"
    assert "q1_analysis.py" in filenames
