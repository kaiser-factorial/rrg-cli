"""Import a validator's returned outputs back into its operator-side run folder.

Validators run in isolation (see docs/adr/0001-validator-isolation.md) and hand back a
folder or zip. This brings those outputs into ``operator/<output_folder>/`` for review.
The returned archive is untrusted, so every entry is verified to resolve inside the run
folder (zip-slip / path-traversal protection).
"""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

from . import grading as grading_module
from .errors import RRGError
from .project import Project
from .utils import safe_label, sha256

RUN_MARKER_NAME = "RRG_RUN.txt"


def render_run_marker(run_id: str) -> str:
    """The blinding-safe marker shipped in a delivery zip (ADR 0002).

    Contains only the opaque ``run_id`` — no study, method, or result information. The
    validator is asked to return it unchanged so RRG can bind their results back to this build.
    """
    return (
        f"run_id: {run_id}\n"
        "\n"
        "This file binds your returned results to the validation package you received.\n"
        "Please return it unchanged alongside your outputs. It is an opaque identifier and\n"
        "carries no information about the study, its methods, or any expected result.\n"
    )


def parse_run_marker(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("run_id:"):
            value = stripped.split(":", 1)[1].strip()
            return value or None
    return None


def read_run_marker(source: Path) -> str | None:
    """Best-effort read of the ``run_id`` from a returned folder or zip; None if absent."""
    try:
        if source.is_file() and source.suffix.lower() == ".zip":
            with zipfile.ZipFile(source) as bundle:
                names = [name for name in bundle.namelist() if Path(name).name == RUN_MARKER_NAME]
                if not names:
                    return None
                with bundle.open(sorted(names, key=len)[0]) as handle:
                    return parse_run_marker(handle.read().decode("utf-8", "replace"))
        if source.is_dir():
            direct = source / RUN_MARKER_NAME
            candidate = direct if direct.is_file() else next(iter(sorted(source.rglob(RUN_MARKER_NAME))), None)
            if candidate and candidate.is_file():
                return parse_run_marker(candidate.read_text(encoding="utf-8", errors="replace"))
    except (OSError, zipfile.BadZipFile):
        return None
    return None


def lookup_provenance(project: Project, run_id: str) -> dict[str, Any] | None:
    """Return the most recent provenance-log record whose run_id matches, or None."""
    log_path = project.path_setting("packages", "operator/_packages") / "provenance_log.jsonl"
    if not log_path.is_file():
        return None
    found: dict[str, Any] | None = None
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("run_id") == run_id:
            found = record
    return found


def _run_folder_name(
    stage_id: str, run_label: str, run_id: str | None,
    validator: str | None = None, model_provenance: str | None = None,
) -> str:
    """Build a descriptive run folder name.

    With validator + model_provenance (the modern path):
        {stage}_{validator}_{model-slug}_{YYYY-MM-DD}__{run_id}
    Without (backward compat):
        {stage}_{run_label}__{run_id}
    """
    from datetime import date
    today = date.today().isoformat()

    if validator and model_provenance:
        # Normalize model provenance to a filesystem-safe slug
        model_slug = re.sub(r"[^A-Za-z0-9._-]", "-", model_provenance).strip("-.")
        # Remove provider prefix (e.g. "qwen/qwen3.7-max" → "qwen3.7-max")
        if "/" in model_slug:
            model_slug = model_slug.split("/")[-1]
        return f"{stage_id}_{validator}_{model_slug}_{today}__{run_id or 'norunid'}"
    else:
        return f"{stage_id}_{run_label}__{run_id or 'norunid'}"


def run_output_folder(
    project: Project, stage_id: str, run_label: str, run_id: str | None = None,
    *,
    validator: str | None = None, model_provenance: str | None = None,
) -> Path:
    """Resolve the operator-side run folder for a (stage, model) pair.

    With validator + model_provenance, the folder is descriptively named:
        {stage}_{validator}_{model}_{date}__{run_id}
    Without, falls back to the legacy naming: {stage}_{model}__{run_id}

    When no run_id is given, resolves the newest matching folder.
    """
    stage = project.stage(stage_id)
    operator_root = project.path_setting("operator", "operator")

    if run_id:
        name = _run_folder_name(stage_id, run_label, run_id, validator, model_provenance)
        return operator_root / name
    # No run_id — try to find an existing folder
    if validator and model_provenance:
        # Search by prefix pattern (date varies)
        model_slug = re.sub(r"[^A-Za-z0-9._-]", "-", model_provenance).strip("-.")
        if "/" in model_slug:
            model_slug = model_slug.split("/")[-1]
        prefix = f"{stage_id}_{validator}_{model_slug}_"
    else:
        prefix = f"{stage_id}_{run_label}"
    if operator_root.is_dir():
        matches = sorted(operator_root.glob(f"{prefix}*__*"), key=lambda path: path.stat().st_mtime)
        if matches:
            return matches[-1]
        # Also try legacy naming
        legacy = f"{stage_id}_{run_label}"
        matches = sorted(operator_root.glob(f"{legacy}__*"), key=lambda path: path.stat().st_mtime)
        if matches:
            return matches[-1]
    return operator_root / f"{stage_id}_{run_label}"


def _withheld_hashes(project: Project, stage_id: str) -> dict[str, str]:
    """sha256 -> human path for every withheld secret a validator at this stage must not hold.

    The universal set is the configured ``files.withheld`` (the origin answer key, private
    operator files, scorecards). For stages that hide the methodology (e.g. robustness), the
    original methodology file is added too — a robustness validator legitimately never has it,
    so a byte-identical copy in its output is a breach. Replication, which is *given* the
    methodology, is unaffected because its stage does not hide it.
    """
    root = project.root.resolve()
    patterns = list(
        project.config.get("files", {}).get("withheld", [])
        or ["operator/origin/", "operator/private/", "operator/**/SCORECARD_*"]
    )
    secrets: set[Path] = set()
    for pattern in patterns:
        cleaned = str(pattern).rstrip("/")
        base = root / cleaned
        if base.is_dir():
            secrets.update(path for path in base.rglob("*") if path.is_file())
        else:
            secrets.update(path for path in root.glob(cleaned) if path.is_file())
    stage = project.stage(stage_id)
    if str(stage.get("methodology", "")).lower() == "hidden":
        methodology = project.study.get("original", {}).get("methodology_file")
        if methodology:
            candidate = project.path(methodology)
            if candidate.is_file():
                secrets.add(candidate)
    hashes: dict[str, str] = {}
    for path in secrets:
        try:
            hashes[sha256(path)] = str(path.relative_to(root))
        except (OSError, ValueError):
            continue
    return hashes


def detect_breach(
    project: Project, stage_id: str, destination: Path, source: Path
) -> dict[str, Any]:
    """Compare returned files against the withheld answer key (ADR 0002).

    A content match means the validator *copied* a secret, not merely reproduced a result —
    a near-certain blinding breach. Also reports whether the returned outputs came from inside
    the project tree, a softer signal that isolation may have been skipped.
    """
    secrets = _withheld_hashes(project, stage_id)
    copied: list[dict[str, str]] = []
    if secrets:
        for path in sorted(destination.rglob("*")):
            if not path.is_file() or path.name in {"_breach.json", ".DS_Store"}:
                continue
            match = secrets.get(sha256(path))
            if match:
                copied.append({"returned": str(path.relative_to(destination)), "matches": match})
    try:
        source.resolve().relative_to(project.root.resolve())
        ran_inside = True
    except ValueError:
        ran_inside = False
    return {"copied_secrets": copied, "ran_inside_project": ran_inside}


def _safe_target(destination: Path, member: str) -> Path:
    target = (destination / member).resolve()
    try:
        target.relative_to(destination)
    except ValueError as exc:  # zip-slip / traversal
        raise RRGError(f"refusing entry outside the run folder: {member}") from exc
    return target


def _write_run_info(
    destination: Path,
    stage: str,
    model: str | None,
    run_id: str | None,
    run_value: str,
    *,
    validator: str | None = None,
    model_provenance: str | None = None,
    breach: dict[str, Any] | None = None,
    normalize_result: dict[str, Any] | None = None,
    gates: dict[str, Any] | None = None,
) -> None:
    """Write a RUN_INFO.md to the run folder with metadata for human reference."""
    from datetime import date
    today = date.today().isoformat()
    breach = breach or {}
    norm = normalize_result or {}
    if gates and gates.get("enabled"):
        revisions = gates.get("revisions", 0)
        gate_line = (
            f"- **Deliverable gates**: {'PASS' if gates.get('passed') else 'FAIL'} "
            f"after {revisions} revision(s) — {gates.get('summary', '')} (see GATES.json)"
        )
    else:
        gate_line = "- **Deliverable gates**: not run"

    lines = [
        f"# Run Info — {destination.name}",
        "",
        "## Configuration",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Stage | {stage} |",
        f"| Validator | {validator or 'manual'} |",
        f"| Model | {model_provenance or model or 'unknown'} |",
        f"| Roster model | {model or 'N/A'} |",
        f"| Run ID | {run_id or 'N/A'} |",
        f"| Date | {today} |",
        f"| Run path | {run_value} |",
        "",
        "## Pipeline status",
        "",
        f"- **Breach check**: {'BREACH DETECTED' if breach.get('copied_secrets') else 'CLEAN'}",
        f"- **Ran inside project**: {'yes (warning)' if breach.get('ran_inside_project') else 'no'}",
        gate_line,
        f"- **Normalization**: {len(norm.get('files_moved', []))} file(s) renamed, "
        f"{len(norm.get('summary_json_created', []))} summary.json created"
        if norm else "- **Normalization**: skipped",
        f"- **Missing questions**: {norm.get('missing', [])}" if norm and norm.get('missing') else "",
        "",
        "## Notes",
        "",
        "This file is auto-generated by `rrg import` and provides a human-readable",
        "summary of the run configuration. Do not edit — it is metadata, not analysis.",
    ]

    info_path = destination / "RUN_INFO.md"
    info_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def import_run(
    project: Project,
    stage_id: str | None = None,
    model_query: str | None = None,
    source: str | Path | None = None,
    *,
    label: str | None = None,
    run_id: str | None = None,
    normalize: bool = True,
    validator: str | None = None,
    model_provenance: str | None = None,
    gates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Copy a returned folder/zip into its run folder, then check, normalize, and record.

    ``gates`` is the dispatch-time gate record (with its revision history) when the
    validator ran under ``rrg dispatch``. When absent, the gates are run once here on the
    files exactly as returned — before normalization touches them — so the record always
    reflects what the validator actually delivered. Either way the record is written to
    ``GATES.json`` in the run folder and summarized in ``RUN_INFO.md``.
    """
    if source is None:
        raise RRGError("a returned folder or .zip is required")
    source = Path(source).expanduser().resolve()
    if not source.exists():
        raise RRGError(f"returned output not found: {source}")

    # Auto-resolve from the in-package RRG_RUN.txt marker (ADR 0002). An explicit run_id wins;
    # otherwise the marker supplies it. A matching provenance record fills in any stage/model/
    # label not given by the caller. Explicit arguments always take precedence.
    run_id = run_id or read_run_marker(source)
    record = lookup_provenance(project, run_id) if run_id else None
    matched = bool(record)
    if record:
        stage_id = stage_id or record.get("stage")
        model_query = model_query or record.get("model")
        if label is None:
            label = record.get("label")
    if not stage_id or not model_query:
        raise RRGError(
            "could not resolve the run: no RRG_RUN.txt marker matched a logged build; "
            "pass --stage and --model explicitly"
        )

    project.stage(stage_id)  # validate stage exists
    roster_entry = project.model(stage_id, model_query)
    run_label = label or safe_label(roster_entry.get("model") if roster_entry else model_query)
    destination = run_output_folder(
        project, stage_id, run_label, run_id,
        validator=validator, model_provenance=model_provenance,
    ).resolve()

    destination.mkdir(parents=True, exist_ok=True)
    imported: list[str] = []

    if source.is_file() and source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as bundle:
            for member in bundle.namelist():
                if member.endswith("/"):
                    continue
                target = _safe_target(destination, member)
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                imported.append(str(target.relative_to(destination)))
    elif source.is_dir():
        for path in sorted(source.rglob("*")):
            if not path.is_file() or path.name == ".DS_Store":
                continue
            target = _safe_target(destination, str(path.relative_to(source)))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            imported.append(str(target.relative_to(destination)))
    else:
        raise RRGError("returned output must be a .zip file or a directory")

    run_value = str(destination.relative_to(project.root))
    breach = detect_breach(project, stage_id, destination, source)
    grading_module.record_breach(
        project,
        run_value,
        copied_secrets=breach["copied_secrets"],
        ran_inside_project=breach["ran_inside_project"],
    )

    # Deliverable gates on the files as returned (before normalization renames anything).
    if gates is None:
        from .gates import check_gates, gate_record, project_question_count, project_report_name
        gates = gate_record(
            check_gates(
                destination, project_question_count(project),
                project_report_name(project, stage_id, roster_entry.get("model") if roster_entry else model_query),
            ),
            source="import",
        )
    (destination / "GATES.json").write_text(
        json.dumps(gates, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )

    # Auto-normalize non-conforming returns (unless skipped).
    normalize_result: dict[str, Any] | None = None
    if normalize:
        from .normalize import normalize_run
        normalize_result = normalize_run(project, destination)

    # Auto-write RUN_INFO.md with run metadata
    _write_run_info(
        destination, stage_id, model_query, run_id, run_value,
        validator=validator, model_provenance=model_provenance,
        breach=breach, normalize_result=normalize_result, gates=gates,
    )

    return {
        "run": run_value,
        "output_folder": str(destination),
        "run_id": run_id,
        "stage": stage_id,
        "model": model_query,
        "auto_resolved": matched,
        "imported": sorted(imported),
        "count": len(imported),
        "breach": breach,
        "normalize": normalize_result,
        "gates": gates,
        "validator": validator,
        "model_provenance": model_provenance,
    }
