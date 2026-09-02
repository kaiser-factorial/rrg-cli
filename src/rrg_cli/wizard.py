\
"""Interactive setup and dispatch walkthrough.

The wizard runs the full pipeline health-check sequence: project health → data
conversion → preflight → roster review → dispatch. It calls existing CLI
functions and reports status at each step. Supports non-interactive mode for
agent/CI use, and a prefs editor for managing saved defaults.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .doctor import inspect_project
from .errors import RRGError
from .prefs import (
    DEFAULTS,
    VALIDATOR_OPTIONS,
    MODE_OPTIONS,
    PREF_KEYS,
    load_prefs,
    save_prefs,
    reset_prefs,
)
from .project import Project


def _check_health(project: Project) -> dict[str, Any]:
    """Step 1: Check project structure and config validity."""
    checks: list[dict[str, str]] = []
    root = project.root

    # .rrg_root marker
    marker = root / ".rrg_root"
    checks.append({
        "name": ".rrg_root",
        "status": "ok" if marker.exists() else "error",
        "detail": "found" if marker.exists() else "missing",
    })

    # rrg.yaml
    config_path = project.config_path
    checks.append({
        "name": "rrg.yaml",
        "status": "ok" if config_path.is_file() else "error",
        "detail": str(config_path.relative_to(root)) if config_path.is_file() else "missing",
    })

    # study.yaml
    study_path = project.study_path
    checks.append({
        "name": "study.yaml",
        "status": "ok" if study_path.is_file() else "error",
        "detail": str(study_path.relative_to(root)) if study_path.is_file() else "missing",
    })

    # Config version
    version = project.config.get("version", 0)
    checks.append({
        "name": "config version",
        "status": "ok" if int(version) == 1 else "warning",
        "detail": f"v{version}" if version else "missing",
    })

    all_ok = all(c["status"] == "ok" for c in checks)
    return {
        "name": "health",
        "status": "ok" if all_ok else "error",
        "checks": checks,
    }


def _check_conversion(project: Project) -> dict[str, Any]:
    """Step 2: Check data conversion status."""
    checks: list[dict[str, str]] = []
    dataset = project.study.get("dataset", {}) or {}
    source = dataset.get("source", "")
    main_name = dataset.get("main_name", "")

    # Source data
    source_path = project.path(source) if source else None
    checks.append({
        "name": "source data",
        "status": "ok" if source_path and source_path.exists() else "error",
        "detail": str(source_path.relative_to(project.root)) if source_path and source_path.exists() else "missing",
    })

    # Derivatives
    data_dir = project.path_setting("data", "data")
    for fmt in dataset.get("formats", ["csv", "parquet"]):
        deriv = data_dir / f"{main_name}.{fmt}"
        checks.append({
            "name": f"{fmt} derivative",
            "status": "ok" if deriv.exists() else "warning",
            "detail": str(deriv.relative_to(project.root)) if deriv.exists() else "not generated",
        })

    # Metadata
    meta = dataset.get("metadata", "")
    if meta:
        meta_path = project.path(meta)
        checks.append({
            "name": "metadata",
            "status": "ok" if meta_path.exists() else "warning",
            "detail": "found" if meta_path.exists() else "missing",
        })

    all_ok = all(c["status"] == "ok" for c in checks)
    has_warnings = any(c["status"] == "warning" for c in checks)
    return {
        "name": "conversion",
        "status": "ok" if all_ok else ("warning" if has_warnings else "error"),
        "checks": checks,
    }


def _check_preflight(project: Project) -> dict[str, Any]:
    """Step 3: Run preflight readiness checks."""
    report = inspect_project(project, strict=True)
    checks: list[dict[str, str]] = []
    for check in report["checks"]:
        checks.append({
            "name": check["name"],
            "status": check["severity"],
            "detail": check["detail"],
        })
    return {
        "name": "preflight",
        "status": "ok" if report["ok"] else "error",
        "checks": checks,
    }


def _check_roster(project: Project) -> dict[str, Any]:
    """Step 4: Display roster models for each enabled stage."""
    stages: list[dict[str, Any]] = []
    for stage_id in project.stage_ids():
        stage = project.stage(stage_id)
        if not stage.get("enabled", True):
            continue
        models = project.roster(stage_id)
        stages.append({
            "stage": stage_id,
            "opens": stage.get("opens", ""),
            "methodology": stage.get("methodology", ""),
            "models": [
                {
                    "model": m.get("model", ""),
                    "validator": m.get("validator", ""),
                    "vendor": m.get("vendor", ""),
                    "type": m.get("type", ""),
                    "license": m.get("license", ""),
                }
                for m in models
            ],
        })
    return {
        "name": "roster",
        "status": "ok" if stages else "warning",
        "checks": stages,
    }


def _step_dispatch(project: Project) -> dict[str, Any]:
    """Step 5: Dispatch info (non-interactive — just shows what's ready)."""
    prefs = load_prefs(project)
    return {
        "name": "dispatch",
        "status": "skipped" if prefs.get("validator") == "manual" else "ok",
        "checks": [
            {"name": "validator", "status": "ok", "detail": prefs.get("validator", "manual")},
            {"name": "mode", "status": "ok", "detail": prefs.get("mode", "discuss")},
        ],
    }


def run_wizard(
    project: Project,
    *,
    non_interactive: bool = False,
    step: int | None = None,
    prefs_editor: bool = False,
) -> dict[str, Any]:
    """Run the interactive wizard.

    In non-interactive mode, runs all steps and returns results without prompting.
    With ``step=N``, runs only steps 1..N.
    With ``prefs_editor=True``, runs the prefs editor instead of the walkthrough.
    """
    if prefs_editor:
        return {"prefs": wizard_prefs_editor(project)}

    steps_run: list[dict[str, Any]] = []

    all_steps = [
        ("health", _check_health),
        ("conversion", _check_conversion),
        ("preflight", _check_preflight),
        ("roster", _check_roster),
        ("dispatch", _step_dispatch),
    ]

    max_step = step if step is not None else len(all_steps)

    for i, (name, func) in enumerate(all_steps, 1):
        if i > max_step:
            break
        result = func(project)
        steps_run.append(result)

        if not non_interactive and i < max_step:
            # In interactive mode, pause between steps
            _print_step(result)
            try:
                input("\n→ Press enter to continue (or Ctrl+C to stop)...")
            except (EOFError, KeyboardInterrupt):
                break
        elif non_interactive:
            _print_step(result)

    return {
        "steps": steps_run,
        "dispatch_result": None,
        "prefs": load_prefs(project),
    }


def _print_step(step: dict[str, Any]) -> None:
    """Print a step's results to stdout."""
    print(f"\n{'='*60}")
    print(f"Step: {step['name'].title()} — {step['status'].upper()}")
    print(f"{'='*60}")
    for check in step.get("checks", []):
        if isinstance(check, dict):
            name = check.get("name", check.get("stage", ""))
            status = check.get("status", "")
            detail = check.get("detail", "")
            symbol = {"ok": "✓", "warning": "⚠", "error": "✗"}.get(status, " ")
            print(f"  {symbol} {name}: {detail}")
            # For roster, print models
            if "models" in check:
                for m in check["models"]:
                    print(f"      - {m['model']} ({m['type']}, {m['vendor']})")
    print()


def wizard_prefs_editor(project: Project) -> dict[str, Any]:
    """Interactive prefs editor. Returns the saved prefs."""
    prefs = load_prefs(project)
    print("\nCurrent preferences:")
    for key in PREF_KEYS:
        print(f"  {key}: {prefs.get(key)}")

    print(f"\nOptions:")
    print(f"  validator: {', '.join(VALIDATOR_OPTIONS)}")
    print(f"  mode: {', '.join(MODE_OPTIONS)}")
    print(f"  skip_normalize: true, false")
    print(f"  auto_import: true, false")
    print(f"  gates: true, false")
    print(f"  gate_revisions: 0, 1, 2, ...")
    print(f"  (or type 'reset' to restore defaults)")

    try:
        key = input("\nEdit which? (or enter to save) ").strip()
    except (EOFError, KeyboardInterrupt):
        return prefs

    if not key:
        return prefs

    if key == "reset":
        reset_prefs(project)
        print("Reset to defaults.")
        return dict(DEFAULTS)

    if key not in PREF_KEYS:
        print(f"Unknown key: {key}")
        return prefs

    options = {
        "validator": VALIDATOR_OPTIONS,
        "mode": MODE_OPTIONS,
    }.get(key)

    if options:
        print(f"  Options: {', '.join(options)}")
    print(f"  Current: {prefs.get(key)}")

    try:
        value = input("  New value: ").strip()
    except (EOFError, KeyboardInterrupt):
        return prefs

    if not value:
        return prefs

    from .prefs import coerce_pref
    try:
        value = coerce_pref(key, value)
    except ValueError as exc:
        print(f"  {exc}")
        return prefs

    save_prefs(project, {key: value})
    print(f"Saved .rrg_prefs.yaml")
    return load_prefs(project)
