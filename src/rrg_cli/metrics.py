"""Structured metric contracts for validator output and held-back origin results.

The public contract contains no answers or comparison policy.  It gives validators
stable metric identifiers, JSON paths, semantic labels, kinds, and units.  The origin
contract lives under the withheld results key and supplies the values used only by the
operator-side comparison engine.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from .errors import RRGError
from .project import Project

PUBLIC_SPEC_SCHEMA = "rrg.metric-specs.v1"
ORIGIN_RESULTS_SCHEMA = "rrg.origin-results.v1"

METRIC_KINDS = {"scalar", "count", "currency", "percent", "proportion", "p_value"}
RELATION_OPS = {"sum_equals", "difference_equals"}
_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
_FORBIDDEN_PUBLIC_KEYS = {
    "answer",
    "baseline",
    "comparison",
    "expected",
    "expected_value",
    "formula",
    "method",
    "origin",
    "origin_value",
    "reference_value",
    "tolerance",
    "value",
}


def public_metric_spec_path(project: Project) -> Path:
    configured = (project.study.get("questions", {}) or {}).get("metric_spec")
    return project.path(configured or "shared/METRIC_SPEC.json")


def origin_results_path(project: Project) -> Path:
    configured = (project.study.get("original", {}) or {}).get("results_file")
    return project.path(configured or "operator/origin/origin.json")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RRGError(f"{label} is not readable JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RRGError(f"{label} must be a JSON object: {path}")
    return value


def _question_map(value: Any, issues: list[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        issues.append(f"{label} must be an object keyed by question number")
        return {}
    for question in value:
        if not str(question).isdigit() or int(question) < 1:
            issues.append(f"{label}.{question}: question keys must be positive integers")
    return value


def _forbidden_public_paths(value: Any, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).lower() in _FORBIDDEN_PUBLIC_KEYS:
                found.append(path)
            found.extend(_forbidden_public_paths(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_forbidden_public_paths(child, f"{prefix}[{index}]"))
    return found


def validate_public_metric_specs(value: dict[str, Any]) -> list[str]:
    """Return deterministic validation issues for the validator-facing contract."""
    issues = [
        f"{path} is forbidden in a validator-facing metric specification"
        for path in _forbidden_public_paths(value)
    ]
    if value.get("schema_version") != PUBLIC_SPEC_SCHEMA:
        issues.append(f"schema_version must be {PUBLIC_SPEC_SCHEMA!r}")
    questions = _question_map(value.get("questions"), issues, "questions")
    for question, entry in questions.items():
        prefix = f"questions.{question}"
        if not isinstance(entry, dict):
            issues.append(f"{prefix} must be an object")
            continue
        metrics = entry.get("metrics")
        if not isinstance(metrics, list):
            issues.append(f"{prefix}.metrics must be a list")
            continue
        ids: set[str] = set()
        paths: set[str] = set()
        for index, metric in enumerate(metrics):
            location = f"{prefix}.metrics[{index}]"
            if not isinstance(metric, dict):
                issues.append(f"{location} must be an object")
                continue
            for key in ("id", "label", "validator_path", "kind", "unit", "nullable"):
                if key not in metric:
                    issues.append(f"{location}.{key} is required")
            metric_id = metric.get("id")
            validator_path = metric.get("validator_path")
            if not isinstance(metric_id, str) or not _IDENTIFIER_RE.fullmatch(metric_id):
                issues.append(f"{location}.id must be a stable identifier")
            elif metric_id in ids:
                issues.append(f"{location}.id duplicates {metric_id!r}")
            else:
                ids.add(metric_id)
            if not isinstance(validator_path, str) or not _IDENTIFIER_RE.fullmatch(validator_path):
                issues.append(f"{location}.validator_path must be a dotted JSON path")
            elif validator_path in paths:
                issues.append(f"{location}.validator_path duplicates {validator_path!r}")
            else:
                paths.add(validator_path)
            if metric.get("kind") not in METRIC_KINDS:
                issues.append(f"{location}.kind must be one of {', '.join(sorted(METRIC_KINDS))}")
            if not isinstance(metric.get("unit"), str) or not metric.get("unit", "").strip():
                issues.append(f"{location}.unit must be a non-empty string")
            if "nullable" in metric and not isinstance(metric.get("nullable"), bool):
                issues.append(f"{location}.nullable must be boolean")
        relations = entry.get("relations", [])
        if not isinstance(relations, list):
            issues.append(f"{prefix}.relations must be a list when present")
            continue
        relation_ids: set[str] = set()
        for index, relation in enumerate(relations):
            location = f"{prefix}.relations[{index}]"
            if not isinstance(relation, dict):
                issues.append(f"{location} must be an object")
                continue
            allowed = {"id", "op", "inputs", "output"}
            extra = sorted(set(relation) - allowed)
            if extra:
                issues.append(f"{location} has unsupported keys: {', '.join(extra)}")
            relation_id = relation.get("id")
            if not isinstance(relation_id, str) or not _IDENTIFIER_RE.fullmatch(relation_id):
                issues.append(f"{location}.id must be a stable identifier")
            elif relation_id in relation_ids:
                issues.append(f"{location}.id duplicates {relation_id!r}")
            else:
                relation_ids.add(relation_id)
            if relation.get("op") not in RELATION_OPS:
                issues.append(f"{location}.op must be one of {', '.join(sorted(RELATION_OPS))}")
            inputs = relation.get("inputs")
            minimum = 2 if relation.get("op") == "sum_equals" else 2
            if not isinstance(inputs, list) or len(inputs) < minimum or not all(isinstance(item, str) and item in ids for item in inputs):
                issues.append(f"{location}.inputs must list at least {minimum} declared metric ids")
            if relation.get("op") == "difference_equals" and isinstance(inputs, list) and len(inputs) != 2:
                issues.append(f"{location}.inputs must contain exactly two ids for difference_equals")
            if not isinstance(relation.get("output"), str) or relation.get("output") not in ids:
                issues.append(f"{location}.output must name a declared metric id")
            # Addition and subtraction are meaningful only within one declared unit.
            metric_units = {
                metric.get("id"): metric.get("unit") for metric in metrics if isinstance(metric, dict)
            }
            referenced = list(inputs) if isinstance(inputs, list) else []
            referenced.append(relation.get("output"))
            units = {metric_units.get(item) for item in referenced if item in metric_units}
            if len(units) > 1:
                issues.append(f"{location} references metrics with different units")
    return issues


def validate_origin_results(
    value: dict[str, Any], public_specs: dict[str, Any] | None = None
) -> list[str]:
    issues: list[str] = []
    if value.get("schema_version") != ORIGIN_RESULTS_SCHEMA:
        issues.append(f"schema_version must be {ORIGIN_RESULTS_SCHEMA!r}")
    questions = _question_map(value.get("questions"), issues, "questions")
    spec_questions = (public_specs or {}).get("questions", {})
    for question, entry in questions.items():
        prefix = f"questions.{question}"
        if not isinstance(entry, dict) or not isinstance(entry.get("metrics"), dict):
            issues.append(f"{prefix}.metrics must be an object keyed by metric id")
            continue
        known = {
            metric.get("id")
            for metric in (spec_questions.get(str(question), {}) or {}).get("metrics", [])
            if isinstance(metric, dict)
        }
        for metric_id, record in entry["metrics"].items():
            location = f"{prefix}.metrics.{metric_id}"
            if public_specs is not None and metric_id not in known:
                issues.append(f"{location} has no matching public metric id")
            if not isinstance(record, dict):
                issues.append(f"{location} must be an object")
                continue
            if "value" not in record:
                issues.append(f"{location}.value is required")
            raw = record.get("value")
            if raw is not None and (
                isinstance(raw, bool)
                or not isinstance(raw, (int, float))
                or not math.isfinite(float(raw))
            ):
                issues.append(f"{location}.value must be a finite number or null")
            if not isinstance(record.get("unit"), str) or not record.get("unit", "").strip():
                issues.append(f"{location}.unit must be a non-empty string")
            if "display" in record and not isinstance(record.get("display"), str):
                issues.append(f"{location}.display must be a string")
    return issues


def load_public_metric_specs(project: Project, *, required: bool = True) -> dict[str, Any]:
    path = public_metric_spec_path(project)
    if not path.is_file():
        if required:
            raise RRGError(f"validator-facing metric specification is missing: {path}")
        return {}
    value = _read_json(path, "validator-facing metric specification")
    issues = validate_public_metric_specs(value)
    if issues:
        raise RRGError("validator-facing metric specification is invalid: " + "; ".join(issues))
    return value


def load_origin_results(project: Project, *, required: bool = True) -> dict[str, Any]:
    path = origin_results_path(project)
    if not path.is_file():
        if required:
            raise RRGError(f"canonical origin results are missing: {path}")
        return {}
    value = _read_json(path, "canonical origin results")
    public = load_public_metric_specs(project, required=False)
    issues = validate_origin_results(value, public or None)
    if issues:
        raise RRGError("canonical origin results are invalid: " + "; ".join(issues))
    return value


def question_metric_specs(value: dict[str, Any], question: int) -> list[dict[str, Any]]:
    entry = (value.get("questions", {}) or {}).get(str(question), {}) or {}
    metrics = entry.get("metrics", [])
    return metrics if isinstance(metrics, list) else []


def question_origin_metrics(value: dict[str, Any], question: int) -> dict[str, dict[str, Any]]:
    entry = (value.get("questions", {}) or {}).get(str(question), {}) or {}
    metrics = entry.get("metrics", {})
    return metrics if isinstance(metrics, dict) else {}
