from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from rrg_cli import extract
from rrg_cli.errors import RRGError
from rrg_cli.metrics import (
    ORIGIN_RESULTS_SCHEMA,
    PUBLIC_SPEC_SCHEMA,
    load_origin_results,
    load_public_metric_specs,
    validate_public_metric_specs,
)
from rrg_cli.packager import build_package
from rrg_cli.project import Project


def _write_contract(project: Project) -> None:
    public = {
        "schema_version": PUBLIC_SPEC_SCHEMA,
        "questions": {
            "1": {
                "metrics": [
                    {
                        "id": "component_sum",
                        "label": "Combined component total",
                        "validator_path": "component_sum",
                        "kind": "currency",
                        "unit": "USD_billion",
                        "nullable": False,
                    },
                    {
                        "id": "bootstrap_p_value",
                        "label": "Bootstrap p-value",
                        "validator_path": "bootstrap.p_value",
                        "kind": "p_value",
                        "unit": "probability",
                        "nullable": False,
                    },
                ]
            }
        },
    }
    origin = {
        "schema_version": ORIGIN_RESULTS_SCHEMA,
        "questions": {
            "1": {
                "metrics": {
                    "component_sum": {"value": 8.2, "unit": "USD_billion", "display": "$8.2 billion"},
                    "bootstrap_p_value": {"value": 0.05, "unit": "probability", "display": "0.050"},
                }
            }
        },
    }
    project.path("shared/METRIC_SPEC.json").write_text(json.dumps(public, indent=2), encoding="utf-8")
    project.path("operator/origin/origin.json").write_text(json.dumps(origin, indent=2), encoding="utf-8")


def test_public_metric_spec_rejects_operator_comparison_policy_and_answers():
    safe = {
        "schema_version": PUBLIC_SPEC_SCHEMA,
        "questions": {
            "1": {
                "metrics": [
                    {
                        "id": "estimate",
                        "label": "Primary estimate",
                        "validator_path": "estimate",
                        "kind": "scalar",
                        "unit": "1",
                        "nullable": False,
                    }
                ]
            }
        },
    }
    assert validate_public_metric_specs(safe) == []

    for forbidden in ("expected_value", "origin_value", "tolerance", "method", "formula"):
        leaky = json.loads(json.dumps(safe))
        leaky["questions"]["1"]["metrics"][0][forbidden] = 0.1
        assert any(forbidden in issue for issue in validate_public_metric_specs(leaky))


def test_canonical_origin_json_drives_exact_and_flagged_comparison(ready_project: Project):
    _write_contract(ready_project)
    run = ready_project.path("operator/replication_TestModel/raw")
    run.mkdir(parents=True)
    run.joinpath("Q1_summary.json").write_text(
        json.dumps({"component_sum": 8.1, "bootstrap": {"p_value": 0.047}}), encoding="utf-8"
    )

    result = extract.question_extraction(
        ready_project, "operator/replication_TestModel", 1, 1, stage="replication"
    )
    rows = {row["metric_id"]: row for row in result["stats"]}

    assert result["comparison_source"] == "canonical_origin"
    assert rows["component_sum"]["status"] == "different"
    assert rows["component_sum"]["origin_value"] == "$8.2 billion"
    assert rows["component_sum"]["delta_display"] == "-0.1 billion USD"
    assert rows["component_sum"]["tolerance"] == 0
    assert rows["bootstrap_p_value"]["status"] == "within_tolerance"
    assert rows["bootstrap_p_value"]["exact"] is False
    assert rows["bootstrap_p_value"]["tolerance"] == 0.005


def test_contract_loaders_use_configured_operator_and_shared_paths(ready_project: Project):
    _write_contract(ready_project)
    assert load_public_metric_specs(ready_project)["schema_version"] == PUBLIC_SPEC_SCHEMA
    assert load_origin_results(ready_project)["schema_version"] == ORIGIN_RESULTS_SCHEMA


def test_package_blocks_origin_json_even_when_routing_flattens_its_name(ready_project: Project):
    _write_contract(ready_project)
    config = yaml.safe_load(ready_project.config_path.read_text(encoding="utf-8"))
    config["files"]["all"].append("operator/origin/origin.json")
    ready_project.config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    project = Project.load(ready_project.root)

    result = build_package(project, "replication", "ReplicationModel", dry_run=True)
    assert result["blocked"] is True
    findings = {item["check"]: item for item in result["lint"]["hard_fails"]}
    assert "withheld_source_routing" in findings
    assert "operator/origin/origin.json" in findings["withheld_source_routing"]["items"]


def test_package_contains_only_validator_safe_metric_contract(ready_project: Project):
    _write_contract(ready_project)
    config = yaml.safe_load(ready_project.config_path.read_text(encoding="utf-8"))
    config["files"]["all"].append("shared/METRIC_SPEC.json")
    ready_project.config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    project = Project.load(ready_project.root)

    result = build_package(project, "replication", "ReplicationModel")
    package = Path(result["package_dir"])
    assert (package / "METRIC_SPEC.json").is_file()
    assert not (package / "origin.json").exists()
    sent = (package / "METRIC_SPEC.json").read_text(encoding="utf-8")
    assert "8.2" not in sent and "0.05" not in sent and "tolerance" not in sent


def test_invalid_public_contract_blocks_packaging(ready_project: Project):
    _write_contract(ready_project)
    spec_path = ready_project.path("shared/METRIC_SPEC.json")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["questions"]["1"]["metrics"][0]["expected_value"] = 8.2
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    config = yaml.safe_load(ready_project.config_path.read_text(encoding="utf-8"))
    config["files"]["all"].append("shared/METRIC_SPEC.json")
    ready_project.config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    with pytest.raises(RRGError, match="validator-facing metric specification"):
        build_package(Project.load(ready_project.root), "replication", "ReplicationModel")
