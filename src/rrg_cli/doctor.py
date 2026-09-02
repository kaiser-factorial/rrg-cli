from __future__ import annotations

import importlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .project import Project
from .metrics import load_origin_results, load_public_metric_specs
from .model_eval import check_model_evaluations
from .analysis_contract import analysis_contract_path, evaluate_analysis_contract, load_analysis_contract
from .prompts import render_prompt
from .routing import resolve_send
from .utils import sha256


@dataclass(frozen=True)
class Check:
    severity: str
    name: str
    detail: str
    path: str | None = None


def _study_paths(project: Project) -> list[tuple[str, str, bool]]:
    study = project.study
    dataset = study.get("dataset", {}) or {}
    aux = dataset.get("aux", {}) or {}
    solution = study.get("given_solution", {}) or {}
    questions = study.get("questions", {}) or {}
    held = study.get("held_constants", {}) or {}
    original = study.get("original", {}) or {}
    guide = (study.get("deliverable", {}) or {}).get("method_guide", {}) or {}
    paths = [
        ("study overview", study.get("overview_file"), True),
        ("dataset source", dataset.get("source"), True),
        ("dataset codebook", dataset.get("codebook"), True),
        ("dataset metadata", dataset.get("metadata"), False),
        ("questions", questions.get("file"), True),
        ("questions map", questions.get("map"), True),
        ("metric specifications", questions.get("metric_spec"), True),
        ("held constants", held.get("file"), True),
        ("original methodology", original.get("methodology_file"), True),
        ("results key", original.get("results_key"), True),
        ("canonical origin results", original.get("results_file"), True),
    ]
    if aux.get("enabled"):
        paths.append(("auxiliary dataset", aux.get("file"), True))
    if solution.get("enabled"):
        paths.append(("solution glossary", solution.get("glossary"), True))
        paths.extend(("solution artifact", value, True) for value in solution.get("artifacts", []) or [])
    paths.extend(("additional input", item.get("file"), True) for item in study.get("additional", []) or [])
    if guide.get("enabled"):
        paths.append(("method guide", guide.get("file"), True))
    return [(name, str(value or ""), required) for name, value, required in paths]


def inspect_project(project: Project, stage: str | None = None, strict: bool = False) -> dict[str, Any]:
    checks: list[Check] = []
    for module in ("yaml", "pandas", "numpy", "pyreadstat", "pyarrow"):
        try:
            importlib.import_module(module)
            checks.append(Check("ok", f"dependency:{module}", "available"))
        except ImportError:
            severity = "error" if strict else "warning"
            checks.append(Check(severity, f"dependency:{module}", "not installed"))

    generated_names = {
        "dataset codebook",
        "dataset metadata",
    }
    for name, value, required in _study_paths(project):
        if not value:
            checks.append(Check("error" if required else "warning", name, "path is not configured"))
            continue
        try:
            path = project.path(value)
        except Exception as exc:
            checks.append(Check("error", name, str(exc), value))
            continue
        exists = path.exists()
        severity = "ok" if exists else ("error" if strict or name not in generated_names else "warning")
        checks.append(Check(severity, name, "found" if exists else "missing", str(path)))

    for name, loader in (
        ("metric specification schema", load_public_metric_specs),
        ("canonical origin schema", load_origin_results),
    ):
        try:
            loader(project)
            checks.append(Check("ok", name, "valid"))
        except Exception as exc:
            checks.append(Check("error" if strict else "warning", name, str(exc)))

    metadata_value = (project.study.get("dataset", {}) or {}).get("metadata")
    source_value = (project.study.get("dataset", {}) or {}).get("source")
    if metadata_value and source_value:
        metadata_path, source_path = project.path(metadata_value), project.path(source_value)
        if metadata_path.is_file() and source_path.is_file():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                hash_ok = metadata.get("source_sha256") == sha256(source_path)
                verified = all(
                    item.get("ok") for item in (metadata.get("verification", {}) or {}).values()
                )
                checks.append(Check("ok" if hash_ok else "error", "source provenance", "hash matches" if hash_ok else "source hash changed", str(metadata_path)))
                checks.append(Check("ok" if verified else "error", "derivative verification", "all derivatives verified" if verified else "one or more derivatives did not verify", str(metadata_path)))
            except (OSError, json.JSONDecodeError) as exc:
                checks.append(Check("error", "dataset metadata", f"unreadable: {exc}", str(metadata_path)))

    for evaluation in check_model_evaluations(project):
        checks.append(
            Check(
                "ok" if evaluation["passed"] else ("error" if strict else "warning"),
                f"model evaluation:{evaluation['model_id']}",
                evaluation["detail"],
                evaluation.get("path"),
            )
        )

    contract_path = analysis_contract_path(project)
    if contract_path is not None:
        try:
            contract = load_analysis_contract(project) or {}
            contract_result = evaluate_analysis_contract(contract)
            checks.append(
                Check(
                    "ok" if contract_result["passed"] else ("error" if strict else "warning"),
                    "robustness analysis contract",
                    "approved and result-neutral"
                    if contract_result["passed"]
                    else "; ".join(contract_result["issues"]),
                    str(contract_path),
                )
            )
        except Exception as exc:
            checks.append(
                Check("error" if strict else "warning", "robustness analysis contract", str(exc), str(contract_path))
            )

    stages = [stage] if stage else project.stage_ids()
    for stage_id in stages:
        try:
            stage_config = project.stage(stage_id)
            if not stage_config.get("enabled", True):
                checks.append(Check("warning", f"stage:{stage_id}", f"disabled: {stage_config.get('blocked_reason', 'no reason recorded')}"))
                continue
            routed = resolve_send(project, stage_id)
            checks.append(Check("ok", f"routing:{stage_id}", f"{len(routed)} inputs resolved"))
            roster = project.roster(stage_id)
            model = str(roster[0].get("model")) if roster else "PreflightModel"
            prompt = render_prompt(project, stage_id, model)
            checks.append(Check("ok", f"prompt:{stage_id}", f"{len(prompt.turns)} turns render cleanly", str(prompt.source)))
        except Exception as exc:
            checks.append(Check("error", f"stage:{stage_id}", str(exc)))
    return {
        "ok": not any(check.severity == "error" for check in checks),
        "strict": strict,
        "project": project.name,
        "root": str(project.root),
        "checks": [asdict(check) for check in checks],
    }
