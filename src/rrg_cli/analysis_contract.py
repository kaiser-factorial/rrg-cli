"""Stage-safe held-constants contract for hidden-method robustness runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import RRGError
from .project import Project

ANALYSIS_CONTRACT_SCHEMA = "rrg.analysis-contract.v1"
_REQUIRED_CONSTANTS = {
    "population",
    "unit_of_analysis",
    "inclusion_exclusion",
    "time_window",
    "constructs_and_outcomes",
    "missingness",
}
_FORBIDDEN_KEYS = {"answer", "expected_value", "finding", "findings", "origin_value", "results", "tolerance"}


def _forbidden_paths(value: Any, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).lower() in _FORBIDDEN_KEYS:
                paths.append(path)
            paths.extend(_forbidden_paths(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_forbidden_paths(child, f"{prefix}[{index}]"))
    return paths


def evaluate_analysis_contract(value: dict[str, Any]) -> dict[str, Any]:
    issues = [f"{path} is forbidden in a validator-facing analysis contract" for path in _forbidden_paths(value)]
    if value.get("schema_version") != ANALYSIS_CONTRACT_SCHEMA:
        issues.append(f"schema_version must be {ANALYSIS_CONTRACT_SCHEMA!r}")

    robustness_input = value.get("robustness_input")
    if not isinstance(robustness_input, dict):
        issues.append("robustness_input is required")
    else:
        if not isinstance(robustness_input.get("file"), str) or not robustness_input.get("file", "").strip():
            issues.append("robustness_input.file is required")
        if robustness_input.get("result_neutral") is not True:
            issues.append("robustness_input.result_neutral must be true")

    constants = value.get("held_constants")
    if not isinstance(constants, dict):
        issues.append("held_constants must be an object")
        constants = {}
    for name in sorted(_REQUIRED_CONSTANTS):
        record = constants.get(name)
        if not isinstance(record, dict):
            issues.append(f"held_constants.{name} is required")
            continue
        if record.get("status") not in {"fixed", "approved"}:
            issues.append(f"held_constants.{name}.status must be fixed or approved")
        if not isinstance(record.get("definition"), str) or not record.get("definition", "").strip():
            issues.append(f"held_constants.{name}.definition is required")

    policy = value.get("robustness_method_policy")
    if not isinstance(policy, str) or "independent" not in policy.lower():
        issues.append("robustness_method_policy must require independent method choice")

    approval = value.get("approval")
    if not isinstance(approval, dict) or approval.get("status") != "approved":
        issues.append("approval.status must be approved")
    elif not all(
        isinstance(approval.get(key), str) and approval.get(key, "").strip()
        for key in ("reviewer", "reviewed_at")
    ):
        issues.append("approval requires reviewer and reviewed_at")
    return {"passed": not issues, "issues": issues}


def analysis_contract_path(project: Project) -> Path | None:
    configured = (project.study.get("held_constants", {}) or {}).get("contract")
    return project.path(str(configured)) if configured else None


def load_analysis_contract(project: Project) -> dict[str, Any] | None:
    path = analysis_contract_path(project)
    if path is None:
        return None
    if not path.is_file():
        raise RRGError(f"robustness analysis contract is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RRGError(f"robustness analysis contract is unreadable: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RRGError("robustness analysis contract must be a JSON object")
    return value


def _normalization_audit(project: Project) -> dict[str, Any]:
    path = project.path("operator/normalization/manifest.json")
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def assert_stage_analysis_contract(project: Project, stage: str) -> None:
    if stage != "robustness":
        return
    contract = load_analysis_contract(project)
    if contract is None:  # Legacy projects remain usable until explicitly migrated.
        return
    result = evaluate_analysis_contract(contract)
    if result["issues"]:
        raise RRGError("robustness contract gate failed: " + "; ".join(result["issues"]))

    audit = _normalization_audit(project)
    audited_input = str(audit.get("selected_analysis_csv") or "")
    contract_input = str((contract.get("robustness_input") or {}).get("file") or "")
    answer_columns = ((audit.get("robustness_audit") or {}).get("derived_or_answer_columns") or [])
    if answer_columns and Path(audited_input).name == Path(contract_input).name:
        raise RRGError(
            "robustness contract gate failed: selected input still contains derived or answer-bearing "
            f"columns: {', '.join(str(item) for item in answer_columns)}"
        )
