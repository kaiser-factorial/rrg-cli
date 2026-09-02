"""Operator-side evaluation gate for models that create research variables.

RRG validates downstream analyses, but that cannot establish the validity of an
upstream classifier, scorer, embedding model, or other learned measurement system.
Projects declare those models explicitly and provide ground-truth evaluation records;
the package gate computes acceptance rather than trusting a claimed status string.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from .errors import RRGError
from .project import Project

MODEL_EVALUATION_SCHEMA = "rrg.model-evaluation.v1"
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_OPERATORS = {
    "gte": lambda value, threshold: value >= threshold,
    "lte": lambda value, threshold: value <= threshold,
    "gt": lambda value, threshold: value > threshold,
    "lt": lambda value, threshold: value < threshold,
    "eq": lambda value, threshold: value == threshold,
}


def _number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _task_metric_issues(task_type: str, metrics: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if task_type == "binary_classification":
        matrix = metrics.get("confusion_matrix")
        complete_matrix = isinstance(matrix, dict) and all(
            _number(matrix.get(key)) and matrix[key] >= 0 for key in ("tn", "fp", "fn", "tp")
        )
        if not _number(metrics.get("roc_auc")) and not complete_matrix:
            issues.append("binary classification requires roc_auc or a complete confusion_matrix")
    elif task_type == "multiclass_classification":
        matrix = metrics.get("confusion_matrix")
        labels = metrics.get("class_labels")
        square = (
            isinstance(matrix, list)
            and matrix
            and all(isinstance(row, list) and len(row) == len(matrix) for row in matrix)
            and all(_number(cell) and cell >= 0 for row in matrix for cell in row)
        )
        if not square or not isinstance(labels, list) or len(labels) != len(matrix or []):
            issues.append("multiclass classification requires a square confusion_matrix and matching class_labels")
    elif task_type in {"continuous", "regression"}:
        if not any(_number(metrics.get(name)) for name in ("mae", "rmse")):
            issues.append("continuous evaluation requires an error metric (mae or rmse)")
        if not any(_number(metrics.get(name)) for name in ("pearson_r", "spearman_rho", "r_squared")):
            issues.append("continuous evaluation requires an association metric (pearson_r, spearman_rho, or r_squared)")
    elif task_type == "ordinal":
        if not _number(metrics.get("mae")):
            issues.append("ordinal evaluation requires mae")
        if not _number(metrics.get("spearman_rho")):
            issues.append("ordinal evaluation requires spearman_rho")
    elif task_type in {"human_coding", "generative", "custom"}:
        if not metrics:
            issues.append(f"{task_type} evaluation requires at least one task-specific metric")
    else:
        issues.append(f"unsupported task_type: {task_type!r}")
    return issues


def evaluate_model_record(value: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    if value.get("schema_version") != MODEL_EVALUATION_SCHEMA:
        issues.append(f"schema_version must be {MODEL_EVALUATION_SCHEMA!r}")
    if not isinstance(value.get("model_id"), str) or not value.get("model_id", "").strip():
        issues.append("model_id is required")
    task_type = str(value.get("task_type") or "")

    artifact = value.get("artifact")
    if not isinstance(artifact, dict):
        issues.append("artifact must identify the evaluated immutable model")
    else:
        if not isinstance(artifact.get("name"), str) or not artifact.get("name", "").strip():
            issues.append("artifact.name is required")
        if not isinstance(artifact.get("sha256"), str) or not _HASH_RE.fullmatch(artifact.get("sha256", "")):
            issues.append("artifact.sha256 must be a 64-character lowercase hex digest")

    ground_truth = value.get("ground_truth")
    if not isinstance(ground_truth, dict):
        issues.append("ground_truth is required")
    else:
        for key in ("source", "target"):
            if not isinstance(ground_truth.get(key), str) or not ground_truth.get(key, "").strip():
                issues.append(f"ground_truth.{key} is required")
        if not _number(ground_truth.get("n")) or ground_truth.get("n", 0) <= 0:
            issues.append("ground_truth.n must be positive")
        if ground_truth.get("independent") is not True:
            issues.append("ground_truth.independent must be true")

    metrics = value.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
        issues.append("metrics must be an object")
    issues.extend(_task_metric_issues(task_type, metrics))

    approval = value.get("approval")
    if not isinstance(approval, dict) or not all(
        isinstance(approval.get(key), str) and approval.get(key, "").strip()
        for key in ("reviewer", "reviewed_at")
    ):
        issues.append("approval requires reviewer and reviewed_at")

    acceptance = value.get("acceptance")
    criteria = acceptance.get("criteria") if isinstance(acceptance, dict) else None
    criterion_results: list[dict[str, Any]] = []
    if not isinstance(criteria, list) or not criteria:
        issues.append("acceptance.criteria must contain at least one operator-defined threshold")
    else:
        for index, criterion in enumerate(criteria):
            location = f"acceptance.criteria[{index}]"
            if not isinstance(criterion, dict):
                issues.append(f"{location} must be an object")
                continue
            metric = criterion.get("metric")
            operator = criterion.get("operator")
            threshold = criterion.get("threshold")
            observed = metrics.get(metric) if isinstance(metric, str) else None
            if operator not in _OPERATORS:
                issues.append(f"{location}.operator must be one of {', '.join(sorted(_OPERATORS))}")
                continue
            if not _number(threshold) or not _number(observed):
                issues.append(f"{location} must reference a numeric metric and threshold")
                continue
            passed = bool(_OPERATORS[operator](float(observed), float(threshold)))
            criterion_results.append(
                {
                    "metric": metric,
                    "operator": operator,
                    "threshold": threshold,
                    "observed": observed,
                    "passed": passed,
                }
            )

    valid = not issues
    passed = valid and bool(criterion_results) and all(item["passed"] for item in criterion_results)
    return {"valid": valid, "passed": passed, "issues": issues, "criteria": criterion_results}


def _declarations(project: Project) -> list[dict[str, Any]]:
    value = project.study.get("derived_models", []) or []
    return [item for item in value if isinstance(item, dict) and item.get("required", True)]


def check_model_evaluations(project: Project) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for declaration in _declarations(project):
        model_id = str(declaration.get("id") or "unnamed")
        configured = declaration.get("evaluation_file")
        if not configured:
            checks.append({"model_id": model_id, "passed": False, "detail": "evaluation_file is not configured"})
            continue
        path = project.path(str(configured))
        if not path.is_file():
            checks.append({"model_id": model_id, "passed": False, "detail": f"missing: {path}"})
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            checks.append({"model_id": model_id, "passed": False, "detail": f"unreadable: {exc}"})
            continue
        if not isinstance(record, dict):
            checks.append({"model_id": model_id, "passed": False, "detail": "record must be a JSON object"})
            continue
        result = evaluate_model_record(record)
        if record.get("model_id") != model_id:
            result["issues"].append(
                f"model_id {record.get('model_id')!r} does not match declaration {model_id!r}"
            )
            result["valid"] = False
            result["passed"] = False
        failed = [item for item in result["criteria"] if not item["passed"]]
        if result["issues"]:
            detail = "; ".join(result["issues"])
        elif failed:
            item = failed[0]
            detail = (
                f"acceptance criterion failed: {item['metric']}={item['observed']} "
                f"{item['operator']} {item['threshold']}"
            )
        else:
            detail = f"passed {len(result['criteria'])} operator-defined acceptance criteria"
        checks.append({"model_id": model_id, "passed": result["passed"], "detail": detail, "path": str(path)})
    return checks


def assert_model_evaluations(project: Project) -> None:
    failed = [item for item in check_model_evaluations(project) if not item["passed"]]
    if failed:
        detail = "; ".join(f"{item['model_id']}: {item['detail']}" for item in failed)
        raise RRGError(f"model evaluation gate failed: {detail}")
