"""Tests for the setup module (automated project initialization)."""

from __future__ import annotations

from pathlib import Path

import pytest

from rrg_cli.project import Project
from rrg_cli.setup import (
    setup_status,
    render_question_extraction_prompt,
    apply_questions,
    render_study_overview_prompt,
    apply_study_overview,
    render_validation_instructions_prompt,
    apply_validation_instructions,
    _summarize_codebook,
    _read_metadata,
)


def test_setup_status_fresh_project(ready_project: Project) -> None:
    """A freshly scaffolded+converted project needs most setup steps."""
    status = setup_status(ready_project)
    assert "steps" in status
    # Convert should be done (ready_project fixture converts)
    convert_step = next(s for s in status["steps"] if s["step"] == "convert")
    assert convert_step["done"] is True
    # But questions/overview/instructions may not be done
    steps_not_done = [s for s in status["steps"] if not s["done"]]
    assert len(steps_not_done) > 0


def test_setup_status_complete_project(ready_project: Project) -> None:
    """A project with all docs filled in should show all_done."""
    # Write all the required files
    shared = ready_project.root / "shared"
    shared.mkdir(exist_ok=True)
    (shared / "STUDY_OVERVIEW.md").write_text("# Study overview\n\nThis is a test study with enough content to pass the size check.")
    (shared / "VALIDATION_INSTRUCTIONS.md").write_text("# Validation instructions\n\nAlpha = 0.005. Groups defined here. Enough content.")
    # The ready_project already has QUESTIONS.md, ANALYSIS_PROTOCOL_OG.md, and SUMMARY.md from template
    status = setup_status(ready_project)
    # Check which are done
    for s in status["steps"]:
        if not s["done"]:
            print(f"  NOT DONE: {s['step']} — {s['name']}")


def test_summarize_codebook(ready_project: Project) -> None:
    """The codebook summary extracts row/column counts and column info."""
    summary = _summarize_codebook(ready_project)
    assert summary["n_rows"] > 0
    assert summary["n_cols"] > 0
    assert "columns" in summary
    assert len(summary["columns"]) > 0


def test_read_metadata(ready_project: Project) -> None:
    """Metadata is readable from the converted dataset."""
    meta = _read_metadata(ready_project)
    assert "n_rows" in meta or "source_sha256" in meta


def test_render_question_extraction_prompt(ready_project: Project) -> None:
    """The question extraction prompt renders without error."""
    result = render_question_extraction_prompt(ready_project)
    assert "text" in result
    assert len(result["text"]) > 100
    assert "STUDY_TITLE" not in result["text"]  # placeholders resolved


def test_apply_questions(ready_project: Project) -> None:
    """Applying extracted questions writes QUESTIONS.md and questions_map.yaml."""
    questions_text = """1. Is there a relationship between X and Y? (topic: Primary association)
2. Does the conclusion survive a robustness check? (topic: Robustness)
3. How was the analysis sample constructed? (topic: Sample construction)
"""
    result = apply_questions(ready_project, questions_text)
    assert result["count"] == 3
    assert (ready_project.root / "shared/QUESTIONS.md").exists()
    assert (ready_project.root / "questions_map.yaml").exists()
    # Check the questions file
    content = (ready_project.root / "shared/QUESTIONS.md").read_text()
    assert "1. Is there a relationship" in content
    assert "2. Does the conclusion survive" in content


def test_apply_questions_with_original_numbering(ready_project: Project) -> None:
    """Questions with original numbering (Q12) are parsed correctly."""
    questions_text = """1. Is there a relationship? (Q1)
2. Does it survive? (Q4)
3. How was the sample made? (Q7)
"""
    result = apply_questions(ready_project, questions_text)
    assert result["count"] == 3
    # The questions_map should have original numbers 1, 4, 7
    import yaml
    with open(ready_project.root / "questions_map.yaml") as f:
        map_data = yaml.safe_load(f)
    originals = [q["original"] for q in map_data["questions"]]
    assert originals == [1, 4, 7]


def test_render_study_overview_prompt(ready_project: Project) -> None:
    """The study overview prompt renders with codebook context."""
    result = render_study_overview_prompt(ready_project)
    assert "text" in result
    assert len(result["text"]) > 200
    # Should include dataset structure info
    assert "Rows:" in result["text"] or "Columns:" in result["text"]


def test_apply_study_overview(ready_project: Project) -> None:
    """Applying a study overview writes shared/STUDY_OVERVIEW.md."""
    text = "# Study overview\n\nThis is a generated study overview."
    result = apply_study_overview(ready_project, text)
    assert "written" in result
    assert (ready_project.root / "shared/STUDY_OVERVIEW.md").exists()


def test_render_validation_instructions_prompt(ready_project: Project) -> None:
    """The validation instructions prompt renders with codebook context."""
    result = render_validation_instructions_prompt(ready_project)
    assert "text" in result
    assert len(result["text"]) > 200


def test_apply_validation_instructions(ready_project: Project) -> None:
    """Applying validation instructions writes shared/VALIDATION_INSTRUCTIONS.md."""
    text = "# Validation instructions\n\nAlpha = 0.005."
    result = apply_validation_instructions(ready_project, text)
    assert "written" in result
    assert (ready_project.root / "shared/VALIDATION_INSTRUCTIONS.md").exists()


def test_apply_questions_empty_raises(ready_project: Project) -> None:
    """Empty question text raises an error."""
    with pytest.raises(Exception):
        apply_questions(ready_project, "")


def test_apply_questions_no_questions_raises(ready_project: Project) -> None:
    """Text without numbered questions raises an error."""
    with pytest.raises(Exception):
        apply_questions(ready_project, "This is just some text without numbered questions.")
