from pathlib import Path

from rrg_cli.doctor import inspect_project
from rrg_cli.project import Project, _normalize_config
from rrg_cli.prompts import render_prompt, unresolved_tokens


def test_scaffold_has_complete_project_contract(project_root: Path):
    expected = {
        ".rrg_root",
        "rrg.yaml",
        "study.yaml",
        "questions_map.yaml",
        "data/source.csv",
        "shared/STUDY_OVERVIEW.md",
        "shared/QUESTIONS.md",
        "shared/VALIDATION_INSTRUCTIONS.md",
        "shared/ANALYSIS_PROTOCOL_OG.md",
        "prompts/replication.md",
        "prompts/robustness.md",
        "prompts/generalization.md",
    }
    assert expected <= {str(path.relative_to(project_root)) for path in project_root.rglob("*") if path.is_file()}


def test_preflight_fails_before_conversion(project_root: Path):
    project = Project.load(project_root)
    assert not inspect_project(project, strict=True)["ok"]


def test_preflight_passes_after_conversion(ready_project: Project):
    assert inspect_project(ready_project, strict=True)["ok"]
    generalization = inspect_project(ready_project, stage="generalization", strict=True)
    assert generalization["ok"]
    assert any(check["severity"] == "warning" and "disabled" in check["detail"] for check in generalization["checks"])


def test_legacy_manifest_normalization():
    config = _normalize_config(
        {
            "project": "legacy",
            "paths": {
                "model_facing_root": "shared",
                "operator_root": "operator",
                "package_out": "operator/_packages",
            },
            "constraints": {"exclude_as_validator": ["OriginVendor"]},
            "stages": [
                {"id": "generalization", "data_plan": "TBD", "send": ["all"]}
            ],
        }
    )
    assert config["version"] == 1
    assert config["project"]["name"] == "legacy"
    assert config["paths"]["packages"] == "operator/_packages"
    assert config["constraints"]["exclude_vendors"] == ["OriginVendor"]
    assert config["stages"][0]["enabled"] is False
    assert "data-variation plan" in config["stages"][0]["blocked_reason"]


def test_prompts_render_without_cartridge_leaks(ready_project: Project):
    replication = render_prompt(ready_project, "replication", "ReplicationModel")
    robustness = render_prompt(ready_project, "robustness", "RobustnessModel")
    assert len(replication.turns) == 3  # Orient, Execute, Verify
    assert len(robustness.turns) == 7  # Orient, Propose, Discuss, Discuss-interactively, Lock, Execute, Verify (discuss mode)
    nodiscuss = render_prompt(ready_project, "robustness", "RobustnessModel", mode="nodiscuss")
    assert len(nodiscuss.turns) == 5  # discussion turns drop out, operator-reviewed Lock stays
    assert not unresolved_tokens(replication.text)
    assert "ANALYSIS_PROTOCOL_OG.md" in replication.text
    assert "original protocol" in robustness.reminders.lower()
    assert "Operator reminders" not in "\n".join(turn.text for turn in robustness.turns)
