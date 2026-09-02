from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml


NORMALIZER_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "rrg-effort-normalizer"
    / "lib"
    / "normalizer.py"
)
SPEC = importlib.util.spec_from_file_location("rrg_effort_normalizer", NORMALIZER_PATH)
assert SPEC and SPEC.loader
normalizer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(normalizer)


def _statistical_report(root: Path, *, with_model: bool = False) -> Path:
    report = root / "statistical-report"
    (report / "data").mkdir(parents=True)
    report.joinpath("report.md").write_text(
        "# Study\n\n## Executive findings\n\nThe reported effect was 8.2.\n\n"
        "## Answers\n\n### Outcome association\n\nResult prose.\n",
        encoding="utf-8",
    )
    pd.DataFrame(
        {
            "founder_id": ["a", "b", "c"],
            "model_score": [0.1, 0.2, 0.3],
            "outcome": [1, 2, 3],
        }
    ).to_csv(report / "data/analysis.csv", index=False)
    pd.DataFrame(
        {
            "question": ["outcome", "outcome"],
            "trait": ["alpha", "beta"],
            "effect": [0.42, -0.11],
            "p_value": [0.004, 0.45],
            "q_value": [0.008, 0.45],
            "ci95_low": [0.2, -0.3],
            "ci95_high": [0.6, 0.1],
            "n": [3, 3],
        }
    ).to_csv(report / "data/results.csv", index=False)
    if with_model:
        model = report / "research/personality_agent"
        model.mkdir(parents=True)
        model.joinpath("README.md").write_text("Produces continuous scores.", encoding="utf-8")
    return report


def test_scan_report_finds_named_html_inside_deliverable(tmp_path: Path):
    report = tmp_path / "cmmi"
    (report / "deliverable").mkdir(parents=True)
    report.joinpath("deliverable/cmmi-condensed.html").write_text("<h1>CMMI</h1>", encoding="utf-8")
    report.joinpath("navigator.html").write_text("navigation", encoding="utf-8")

    manifest = normalizer.scan_report(report)
    assert manifest["report_html"].endswith("deliverable/cmmi-condensed.html")


def test_metric_contracts_separate_public_shape_from_operator_values(tmp_path: Path):
    report = _statistical_report(tmp_path)
    manifest = normalizer.scan_report(report)
    results = normalizer.find_results_csv(manifest)
    public, origin = normalizer.generate_metric_contracts(manifest, results)

    metric = public["questions"]["1"]["metrics"][0]
    assert {"id", "label", "validator_path", "kind", "unit", "nullable"} <= set(metric)
    assert not ({"value", "expected_value", "tolerance", "method", "formula"} & set(metric))
    origin_values = [item["value"] for item in origin["questions"]["1"]["metrics"].values()]
    assert 0.42 in origin_values and 0.004 in origin_values
    assert "0.42" not in json.dumps(public)


def test_robustness_audit_blocks_derived_or_answer_columns(tmp_path: Path):
    report = _statistical_report(tmp_path, with_model=True)
    manifest = normalizer.scan_report(report)
    analysis = normalizer.find_analysis_csv(manifest)
    models = normalizer.detect_derived_models(manifest)
    audit = normalizer.analyze_robustness_readiness(manifest, analysis, models)

    assert models and models[0]["id"] == "personality-agent"
    assert audit["ready"] is False
    assert "model_score" in audit["derived_or_answer_columns"]
    assert any("derived model" in reason.lower() for reason in audit["reasons"])


def test_generate_project_is_non_destructive_and_gates_model_dependent_report(tmp_path: Path):
    report = _statistical_report(tmp_path, with_model=True)
    output = tmp_path / "output"
    result = normalizer.generate_project(
        report,
        output,
        analysis_csv="data/analysis.csv",
        results_csv="data/results.csv",
    )
    project = Path(result["project_root"])
    study = yaml.safe_load(project.joinpath("study.yaml").read_text(encoding="utf-8"))["study"]
    config = yaml.safe_load(project.joinpath("rrg.yaml").read_text(encoding="utf-8"))

    assert study["derived_models"][0]["id"] == "personality-agent"
    assert study["questions"]["metric_spec"] == "shared/METRIC_SPEC.json"
    assert study["original"]["results_file"] == "operator/origin/origin.json"
    assert config["stages"]["robustness"]["enabled"] is False
    assert "result-neutral robustness data" in config["stages"]["robustness"]["blocked_reason"]
    assert project.joinpath("shared/ANALYSIS_CONTRACT.json").is_file()
    assert project.joinpath("shared/METRIC_SPEC.json").is_file()
    assert project.joinpath("operator/origin/origin.json").is_file()
    assert project.joinpath("operator/model-evaluations/personality-agent.json").is_file()
    assert "8.2" not in project.joinpath("shared/STUDY_OVERVIEW.md").read_text(encoding="utf-8")

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        normalizer.generate_project(report, output)
