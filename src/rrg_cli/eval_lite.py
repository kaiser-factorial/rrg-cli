\
"""Eval-lite: derive process and outcome signals from a returned run.

Evaluates the *pipeline itself* (did the round-trip produce conforming
deliverables? was blinding maintained?) — not the scientific validity of any
finding. Reads artifacts RRG already emits: the run folder, the provenance log,
the breach record, and the grading state.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .normalize import check_deliverable_contract
from .project import Project


def eval_run(project: Project, run_path: Path) -> dict[str, Any]:
    """Evaluate a returned validator run for pipeline metrics.

    Checks:
    - **Deliverable contract** — does the run have the expected per-question
      artifacts (Q<n>_analysis.py, raw/Q<n>_raw.csv, Q<n>_fig.py, Q<n>_fig.png,
      raw/Q<n>_summary.json, DYFA section)?
    - **Breach status** — reads the breach record (if any) for this run.
    - **File counts** — how many files the run produced.
    - **Grading status** — whether the run has been graded.

    Returns a dict with all metrics plus a human-readable report.
    """
    run_path = Path(run_path).resolve()
    run_value = str(run_path.relative_to(project.root)) if _inside_tree(project.root, run_path) else str(run_path)

    # Deliverable contract
    question_count = int(project.study.get("questions", {}).get("count", 0))
    if not question_count:
        from .scorecard import load_question_map
        map_path = project.path(
            project.study.get("questions", {}).get("map", "questions_map.yaml")
        )
        if map_path.is_file():
            question_count = len(load_question_map(map_path))

    contract = check_deliverable_contract(run_path, question_count or 1)

    # Breach status — read the breach record if it exists
    breach = _read_breach(project, run_value)

    # Grading status — check if grading state exists
    grading_status = _check_grading(project, run_value)

    # File count
    file_count = sum(1 for p in run_path.rglob("*") if p.is_file() and p.name != ".DS_Store")

    # Gate record written at dispatch/import time (what the validator actually delivered,
    # and how many revision turns it took to get there).
    gates = _read_gates(run_path)

    # Build report
    report = _build_report(contract, breach, grading_status, file_count, run_value, gates)

    return {
        "run": run_value,
        "file_count": file_count,
        "deliverable_contract": contract,
        "breach": breach,
        "grading": grading_status,
        "gates": gates,
        "report": report,
    }


def _read_gates(run_path: Path) -> dict[str, Any] | None:
    path = run_path / "GATES.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _inside_tree(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _read_breach(project: Project, run_value: str) -> dict[str, Any]:
    """Read the breach record for a run (if it exists)."""
    from .grading import load_breach
    record = load_breach(project, run_value)
    if record is None:
        return {"flagged": False, "copied_secrets": [], "wrote_inside_project": [],
                "ran_inside_project": False, "acknowledged": False}
    return {
        "flagged": bool(record.get("copied_secrets") or record.get("wrote_inside_project")),
        "copied_secrets": record.get("copied_secrets", []),
        "wrote_inside_project": record.get("wrote_inside_project", []),
        "ran_inside_project": record.get("ran_inside_project", False),
        "acknowledged": record.get("acknowledged", False),
    }


def _check_grading(project: Project, run_value: str) -> dict[str, Any]:
    """Check grading status for a run."""
    from .grading import load_grading, is_graded, questions as grading_questions
    try:
        grading = load_grading(project, run_value)
        q_list = grading_questions(project)
        graded = is_graded(project, run_value, q_list)
        verdicts = grading.get("verdicts", {}) if grading else {}
        return {
            "graded": graded,
            "verdicts_count": len(verdicts) if verdicts else 0,
            "finalized": bool(grading and grading.get("finalized")),
        }
    except Exception:
        return {"graded": False, "verdicts_count": 0, "finalized": False}


def _build_report(
    contract: dict[str, Any],
    breach: dict[str, Any],
    grading: dict[str, Any],
    file_count: int,
    run_value: str,
    gates: dict[str, Any] | None = None,
) -> str:
    lines = [
        f"# RRG Eval Report — {run_value}",
        "",
        f"## Deliverable contract",
        "",
    ]
    if gates and gates.get("enabled"):
        status = "PASS" if gates.get("passed") else "FAIL"
        lines.append(
            f"  Gates at {gates.get('source', 'dispatch')}: {status} after "
            f"{gates.get('revisions', 0)} revision(s) — {gates.get('summary', '')}"
        )
    if contract["all_conform"]:
        lines.append("  PASS — all questions conform to the deliverable contract.")
    else:
        lines.append("  FAIL — some questions are missing deliverables:")
        for q in contract["questions"]:
            missing = []
            if not q["has_analysis"]: missing.append("analysis")
            if not q["has_raw_csv"]: missing.append("raw CSV")
            if not q["has_fig_py"]: missing.append("fig script")
            if not q["has_fig_png"]: missing.append("figure")
            if not q["has_summary_json"]: missing.append("summary.json")
            if not q["has_dyfa_section"]: missing.append("DYFA section")
            if missing:
                lines.append(f"  Q{q['question']}: missing {', '.join(missing)}")

    lines.extend([
        "",
        "## Breach status",
        "",
    ])
    if breach["flagged"]:
        if breach["copied_secrets"]:
            lines.append(f"  BREACH — {len(breach['copied_secrets'])} file(s) match the answer key.")
        if breach.get("wrote_inside_project"):
            lines.append(f"  BREACH — validator wrote {len(breach['wrote_inside_project'])} file(s) inside the project tree.")
        if breach["acknowledged"]:
            lines.append("  (acknowledged — grading unblocked)")
        else:
            lines.append("  (NOT acknowledged — grading is blocked)")
    else:
        lines.append("  CLEAN — no copied secrets detected.")
    if breach["ran_inside_project"]:
        lines.append("  NOTE: returned outputs came from inside the project tree (isolation may have been skipped).")

    lines.extend([
        "",
        "## Grading status",
        "",
    ])
    if grading["graded"]:
        lines.append(f"  GRADED — {grading['verdicts_count']} verdict(s) assigned.")
        if grading["finalized"]:
            lines.append("  (finalized)")
    else:
        lines.append(f"  PENDING — {grading['verdicts_count']} verdict(s) assigned, not yet complete.")

    lines.extend([
        "",
        f"## File count: {file_count}",
    ])
    return "\n".join(lines)
