from __future__ import annotations

import json

import pytest
import yaml

from rrg_cli.doctor import inspect_project
from rrg_cli.errors import RRGError
from rrg_cli.model_eval import MODEL_EVALUATION_SCHEMA, evaluate_model_record
from rrg_cli.packager import build_package
from rrg_cli.project import Project


def _declare_model(project: Project, evaluation_file: str = "operator/model-evaluations/personality.json") -> Project:
    study = yaml.safe_load(project.study_path.read_text(encoding="utf-8"))
    study["study"]["derived_models"] = [
        {
            "id": "personality-agent",
            "role": "feature_generator",
            "task_type": "continuous",
            "evaluation_file": evaluation_file,
            "required": True,
        }
    ]
    project.study_path.write_text(yaml.safe_dump(study, sort_keys=False), encoding="utf-8")
    return Project.load(project.root)


def _valid_continuous_record() -> dict:
    return {
        "schema_version": MODEL_EVALUATION_SCHEMA,
        "model_id": "personality-agent",
        "task_type": "continuous",
        "artifact": {"name": "personality-agent", "sha256": "a" * 64},
        "ground_truth": {
            "source": "operator/evaluation/personality-ground-truth.csv",
            "target": "validated self-report Big Five scores",
            "n": 120,
            "independent": True,
        },
        "metrics": {"mae": 8.5, "pearson_r": 0.42},
        "acceptance": {
            "criteria": [
                {"metric": "mae", "operator": "lte", "threshold": 10.0},
                {"metric": "pearson_r", "operator": "gte", "threshold": 0.3},
            ]
        },
        "approval": {"reviewer": "operator", "reviewed_at": "2026-09-02"},
        "limitations": ["Domain shift remains possible."],
    }


def test_continuous_model_evaluation_requires_error_and_association_metrics():
    record = _valid_continuous_record()
    result = evaluate_model_record(record)
    assert result["valid"] is True and result["passed"] is True

    missing_association = json.loads(json.dumps(record))
    missing_association["metrics"].pop("pearson_r")
    assert any("association metric" in issue for issue in evaluate_model_record(missing_association)["issues"])


def test_binary_evaluation_requires_auc_or_complete_confusion_matrix():
    record = _valid_continuous_record()
    record["task_type"] = "binary_classification"
    record["metrics"] = {"accuracy": 0.8}
    record["acceptance"]["criteria"] = [{"metric": "accuracy", "operator": "gte", "threshold": 0.75}]
    assert any("roc_auc or a complete confusion_matrix" in issue for issue in evaluate_model_record(record)["issues"])

    record["metrics"]["confusion_matrix"] = {"tn": 40, "fp": 10, "fn": 8, "tp": 42}
    assert evaluate_model_record(record)["valid"] is True


def test_required_derived_model_without_evaluation_blocks_preflight_and_package(ready_project: Project):
    project = _declare_model(ready_project)
    report = inspect_project(project, strict=True)
    model_check = next(item for item in report["checks"] if item["name"] == "model evaluation:personality-agent")
    assert model_check["severity"] == "error" and "missing" in model_check["detail"]
    with pytest.raises(RRGError, match="model evaluation gate"):
        build_package(project, "replication", "ReplicationModel")


def test_valid_operator_evaluation_unblocks_packaging(ready_project: Project):
    project = _declare_model(ready_project)
    path = project.path("operator/model-evaluations/personality.json")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_valid_continuous_record(), indent=2), encoding="utf-8")

    report = inspect_project(Project.load(project.root), strict=True)
    model_check = next(item for item in report["checks"] if item["name"] == "model evaluation:personality-agent")
    assert model_check["severity"] == "ok"
    assert build_package(Project.load(project.root), "replication", "ReplicationModel", dry_run=True)["blocked"] is False


def test_failed_operator_acceptance_threshold_blocks_package(ready_project: Project):
    project = _declare_model(ready_project)
    record = _valid_continuous_record()
    record["metrics"]["mae"] = 14.0
    path = project.path("operator/model-evaluations/personality.json")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    with pytest.raises(RRGError, match="acceptance criterion failed"):
        build_package(Project.load(project.root), "replication", "ReplicationModel")
