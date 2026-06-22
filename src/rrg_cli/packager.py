from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .blinding import lint_package
from .errors import RRGError
from .project import Project
from .prompts import render_prompt
from .routing import RoutedInput, resolve_send
from .utils import normalize_permissions, safe_label, sha256


def _copy_inputs(inputs: list[RoutedInput], destination: Path) -> list[tuple[str, str]]:
    destination.mkdir(parents=True)
    manifest: list[tuple[str, str]] = []
    for item in inputs:
        output = destination / item.package_name
        if item.is_dir:
            shutil.copytree(item.source, output, copy_function=shutil.copyfile)
            for path in sorted(output.rglob("*")):
                if path.is_file() and path.name != ".DS_Store":
                    manifest.append((str(path.relative_to(destination)), sha256(path)))
        else:
            shutil.copyfile(item.source, output)
            manifest.append((item.package_name, sha256(output)))
    normalize_permissions(destination)
    return manifest


def _unique_destination(destination: Path) -> Path:
    if not destination.exists():
        return destination
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return destination.with_name(f"{destination.name}__{stamp}")


def build_package(
    project: Project,
    stage_id: str,
    model_query: str,
    *,
    label: str | None = None,
    dry_run: bool = False,
    force: bool = False,
    allow_unlisted: bool = False,
) -> dict[str, Any]:
    stage = project.stage(stage_id)
    if not stage.get("enabled", True):
        reason = stage.get("blocked_reason") or "stage is disabled"
        raise RRGError(f"{stage_id} is not buildable: {reason}")
    roster_entry = project.model(stage_id, model_query)
    if roster_entry is None and not allow_unlisted:
        raise RRGError(f"model is not in the {stage_id} roster: {model_query}")
    model_name = str(roster_entry.get("model") if roster_entry else model_query)
    vendor = str(roster_entry.get("vendor", "")) if roster_entry else ""
    constraints = project.config.get("constraints", {}) or {}
    excluded = [
        str(value).lower()
        for value in constraints.get("exclude_vendors", constraints.get("exclude_as_validator", []))
    ]
    if vendor.lower() in excluded:
        raise RRGError(f"validator vendor is excluded because it produced the origin work: {vendor}")
    run_label = label or safe_label(model_name)
    inputs = resolve_send(project, stage_id)
    package_root = project.path_setting("packages", "operator/_packages")
    destination = _unique_destination(package_root / stage_id / run_label)
    operator_root = project.path_setting("operator", "operator")
    output_template = str(stage.get("output_folder", f"{stage_id}_{{model}}"))
    output_folder = operator_root / output_template.format(model=run_label, MODEL=run_label)
    report_template = str(stage.get("report_name", "{model}_Report.docx"))
    report_name = report_template.format(model=run_label, MODEL=run_label)

    with tempfile.TemporaryDirectory(prefix="rrg_package_") as temporary:
        staged = Path(temporary) / f"{stage_id}_{run_label}"
        manifest = _copy_inputs(inputs, staged)
        lint = lint_package(staged, stage_id, project)
        blocked = not lint.passed and not force
        prompt = render_prompt(project, stage_id, model_name)
        provenance = {
            "schema_version": 1,
            "project": project.name,
            "stage": stage_id,
            "model": model_name,
            "label": run_label,
            "type": roster_entry.get("type") if roster_entry else None,
            "vendor": vendor or None,
            "license": roster_entry.get("license") if roster_entry else None,
            "files_sent": [item[0] for item in manifest],
            "file_hashes": dict(manifest),
            "prompt_version": {"path": str(prompt.source.relative_to(project.root)), "sha256": sha256(prompt.source)},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "blinding_lint_result": "pass" if lint.passed else "hard_fail",
            "blinding_flags": [finding.check for finding in lint.flags],
            "forced_override": bool(not lint.passed and force),
            "determinism": project.config.get("constraints", {}).get("determinism", {}),
            "output_folder": str(output_folder),
            "report_name": report_name,
            "package_dir": str(destination),
        }
        published = False
        if not dry_run and not blocked:
            (staged / "_provenance.json").write_text(
                json.dumps(provenance, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(staged, destination, copy_function=shutil.copyfile)
            output_folder.mkdir(parents=True, exist_ok=True)
            log_path = package_root / "provenance_log.jsonl"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(provenance, ensure_ascii=False) + "\n")
            published = True
        return {
            "blocked": blocked,
            "published": published,
            "dry_run": dry_run,
            "package_dir": str(destination),
            "output_folder": str(output_folder),
            "report_name": report_name,
            "lint": lint.as_dict(),
            "provenance": provenance,
        }
