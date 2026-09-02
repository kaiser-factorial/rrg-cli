from __future__ import annotations

import json

import pytest
import yaml

from rrg_cli.analysis_contract import ANALYSIS_CONTRACT_SCHEMA, evaluate_analysis_contract
from rrg_cli.errors import RRGError
from rrg_cli.packager import build_package
from rrg_cli.project import Project


def _contract(status: str = "approved") -> dict:
    return {
        "schema_version": ANALYSIS_CONTRACT_SCHEMA,
        "report_type": "descriptive",
        "dataset": "analysis.csv",
        "robustness_input": {"file": "data/analysis.csv", "result_neutral": True},
        "held_constants": {
            "population": {"status": "fixed", "definition": "Rows in the supplied cohort."},
            "unit_of_analysis": {"status": "fixed", "definition": "One row per entity."},
            "inclusion_exclusion": {"status": "fixed", "definition": "Use all eligible rows."},
            "time_window": {"status": "fixed", "definition": "Use the supplied period."},
            "constructs_and_outcomes": {"status": "fixed", "definition": "Use codebook semantics."},
            "missingness": {"status": "fixed", "definition": "__RRG_NA__ is missing."},
        },
        "robustness_method_policy": "Choose an independent method.",
        "approval": {"status": status, "reviewer": "operator", "reviewed_at": "2026-09-02"},
    }


def _configure(project: Project, contract: dict) -> Project:
    path = project.path("shared/ANALYSIS_CONTRACT.json")
    path.write_text(json.dumps(contract, indent=2), encoding="utf-8")
    study = yaml.safe_load(project.study_path.read_text(encoding="utf-8"))
    study["study"]["held_constants"]["contract"] = "shared/ANALYSIS_CONTRACT.json"
    project.study_path.write_text(yaml.safe_dump(study, sort_keys=False), encoding="utf-8")
    config = yaml.safe_load(project.config_path.read_text(encoding="utf-8"))
    config["files"]["all"].append("shared/ANALYSIS_CONTRACT.json")
    project.config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return Project.load(project.root)


def test_pending_held_constants_contract_blocks_robustness(ready_project: Project):
    contract = _contract("pending")
    assert evaluate_analysis_contract(contract)["passed"] is False
    project = _configure(ready_project, contract)
    with pytest.raises(RRGError, match="robustness contract gate"):
        build_package(project, "robustness", "RobustnessModel", dry_run=True)


def test_approved_result_neutral_contract_allows_robustness(ready_project: Project):
    project = _configure(ready_project, _contract())
    assert build_package(project, "robustness", "RobustnessModel", dry_run=True)["blocked"] is False


def test_normalizer_answer_column_audit_cannot_be_bypassed(ready_project: Project):
    project = _configure(ready_project, _contract())
    manifest = project.path("operator/normalization/manifest.json")
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "selected_analysis_csv": "data/analysis.csv",
                "robustness_audit": {"derived_or_answer_columns": ["model_score"]},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RRGError, match="model_score"):
        build_package(Project.load(project.root), "robustness", "RobustnessModel", dry_run=True)
