\
"""Normalize non-conforming validator returns into canonical deliverable shape.

Validators don't always follow the deliverable contract (wrong filenames, missing
``raw/Q<n>_summary.json``, monolithic scripts, etc.). This module detects,
reorganizes, and parses their output so the extract/grading modules can work
with a consistent structure. Originals are never deleted — files are copied or
created, not moved destructively.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from .project import Project

# Regex patterns for fuzzy-matching question-numbered files.
# Matches Q1, q1, Q01, q01 etc. with optional separators.
_Q_PREFIX_RE = re.compile(r"^[Qq]0*(\d+)[_\-\.]", re.IGNORECASE)
_Q_SUFFIX_RE = re.compile(r"[_\-\.][Qq]0*(\d+)[_\-\.]?", re.IGNORECASE)
_Q_EMBED_RE = re.compile(r"(?:^|[_\-\.])[Qq]0*(\d+)(?:[_\-\.]|$)", re.IGNORECASE)

# Patterns for parsing stats from text.
_N_RE = re.compile(r"\bN\s*=\s*([\d,.]+)", re.IGNORECASE)
_TEST_RE = re.compile(r"\b(?:test|method)\s*[:=]\s*(.+?)(?:\n|$)", re.IGNORECASE)
_STAT_RE = re.compile(r"\b(?:statistic|stat|chi2?|t|F|z)\s*[:=]\s*([\d.]+)", re.IGNORECASE)
_P_RE = re.compile(r"\bp[\s\-_]?value\s*[:=]\s*([\d.]+|<\s*0\.001)", re.IGNORECASE)
_EFFECT_RE = re.compile(r"\beffect\s*size(?:\s*\([^)]+\))?\s*[:=]\s*([\d.]+)", re.IGNORECASE)
_CI_RE = re.compile(r"\b95%\s*CI\s*[:=]\s*\[([\d.,\s\-]+)\]", re.IGNORECASE)
_CONCLUSION_RE = re.compile(r"\bconclusion\s*[:=]\s*(.+?)(?:\n|$)", re.IGNORECASE)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}


def _extract_q_number(filename: str) -> int | None:
    """Extract a question number from a filename using fuzzy matching."""
    name = Path(filename).stem
    # Try prefix: Q1_analysis, q1_fig, Q01_raw
    m = _Q_PREFIX_RE.match(filename)
    if m:
        return int(m.group(1))
    # Try suffix: analysis_q1, visual_q1
    m = _Q_SUFFIX_RE.search(filename)
    if m:
        return int(m.group(1))
    # Try embedded: q1_results.txt -> already caught by prefix
    # Try just the number after a Q: q1.py
    m = re.match(r"^[Qq]0*(\d+)$", name, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def _fuzzy_match_q_files(run_dir: Path) -> dict[int, dict[str, list[Path]]]:
    """Scan a run directory and group files by question number using fuzzy matching.

    Returns ``{question_number: {"analysis": [paths], "figures": [paths], "raw": [paths], "other": [paths]}}``.
    """
    result: dict[int, dict[str, list[Path]]] = {}
    if not run_dir.is_dir():
        return result
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path.name == ".DS_Store":
            continue
        q_num = _extract_q_number(path.name)
        if q_num is None:
            continue
        if q_num not in result:
            result[q_num] = {"analysis": [], "figures": [], "raw": [], "other": []}
        stem_lower = path.stem.lower()
        if path.suffix == ".py" and ("analysis" in stem_lower or "analysis" not in stem_lower):
            if "fig" in stem_lower:
                result[q_num]["other"].append(path)  # fig script
            else:
                result[q_num]["analysis"].append(path)
        elif path.suffix.lower() in IMAGE_EXTENSIONS:
            result[q_num]["figures"].append(path)
        elif path.suffix == ".csv":
            result[q_num]["raw"].append(path)
        else:
            result[q_num]["other"].append(path)
    return result


def _canonical_name(q_num: int, kind: str, source: Path) -> str:
    """Return the canonical filename for a question artifact."""
    if kind == "analysis":
        return f"Q{q_num}_analysis.py"
    if kind == "fig_script":
        return f"Q{q_num}_fig.py"
    if kind == "figure":
        return f"Q{q_num}_fig.png"
    if kind == "raw":
        return f"Q{q_num}_raw.csv"
    if kind == "summary":
        return f"Q{q_num}_summary.json"
    return source.name


def _copy_to_canonical(source: Path, destination: Path) -> bool:
    """Copy source to destination if it doesn't already exist. Returns True if copied."""
    if destination.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True


def _parse_summary_from_text(text: str, question: int) -> dict[str, Any] | None:
    """Parse summary statistics from a text file (results.txt, SUMMARY.md, etc.).

    Returns a dict matching the summary.json schema, or None if no stats found.
    """
    n_match = _N_RE.search(text)
    test_match = _TEST_RE.search(text)
    stat_match = _STAT_RE.search(text)
    p_match = _P_RE.search(text)
    effect_match = _EFFECT_RE.search(text)
    ci_match = _CI_RE.search(text)
    conclusion_match = _CONCLUSION_RE.search(text)

    # Need at least a statistic or p-value to produce something useful
    if not stat_match and not p_match:
        return None

    def _to_float(val: str | None) -> float | None:
        if val is None:
            return None
        val = val.strip().replace(",", "").replace("<", "")
        try:
            return float(val)
        except ValueError:
            return None

    n_val = None
    if n_match:
        n_str = n_match.group(1).replace(",", "")
        try:
            n_val = int(n_str)
        except ValueError:
            n_val = _to_float(n_match.group(1))

    ci = None
    if ci_match:
        parts = [p.strip() for p in ci_match.group(1).split(",")]
        ci_nums = [_to_float(p) for p in parts]
        if len(ci_nums) == 2 and all(v is not None for v in ci_nums):
            ci = ci_nums

    return {
        "question": question,
        "n": n_val,
        "test": test_match.group(1).strip() if test_match else None,
        "statistic": _to_float(stat_match.group(1)) if stat_match else None,
        "p_value": _to_float(p_match.group(1)) if p_match else None,
        "effect_size": _to_float(effect_match.group(1)) if effect_match else None,
        "ci": ci,
        "conclusion": conclusion_match.group(1).strip() if conclusion_match else None,
    }


def _find_results_text(run_dir: Path, q_num: int) -> str | None:
    """Find text output for a question (results.txt, summary section, etc.)."""
    # Direct results file
    for pattern in [f"*q{q_num}*results*", f"*q{q_num:02d}*results*", f"*Q{q_num}*results*"]:
        for path in run_dir.glob(pattern):
            if path.is_file():
                return path.read_text(encoding="utf-8", errors="ignore")
    # Try SUMMARY.md sections
    summary = run_dir / "SUMMARY.md"
    if summary.is_file():
        text = summary.read_text(encoding="utf-8", errors="ignore")
        # Look for a Q<n> section
        section_re = re.compile(
            rf"(?:^|\n)##\s*[Qq]0*{q_num}.*?(?=\n##\s*[Qq]|\Z)",
            re.DOTALL
        )
        m = section_re.search(text)
        if m:
            return m.group(0)
    # Try RAW.md
    raw = run_dir / "RAW.md"
    if raw.is_file():
        text = raw.read_text(encoding="utf-8", errors="ignore")
        section_re = re.compile(
            rf"(?:^|\n)##\s*[Qq]0*{q_num}.*?(?=\n##\s*[Qq]|\Z)",
            re.DOTALL
        )
        m = section_re.search(text)
        if m:
            return m.group(0)
    return None


def check_deliverable_contract(run_path: Path, question_count: int) -> dict[str, Any]:
    """Check whether a run folder conforms to the deliverable contract.

    Does NOT modify anything. Returns per-question status and an overall flag.
    """
    questions: list[dict[str, Any]] = []
    raw_dir = run_path / "raw"
    all_conform = True

    # Find report file for DYFA check
    report_text = ""
    # Prefer *_Report.md files (the configured report name), then standard names
    for path in sorted(run_path.glob("*_Report.md")):
        if path.is_file():
            report_text = path.read_text(encoding="utf-8", errors="ignore")
            break
    if not report_text:
        for name in ("REPORT.md", "DYFA.md", "INVESTIGATION_SUMMARY.md"):
            path = run_path / name
            if path.is_file():
                report_text = path.read_text(encoding="utf-8", errors="ignore")
                break

    for q in range(1, question_count + 1):
        analysis = (run_path / f"Q{q}_analysis.py").exists()
        raw_csv = (raw_dir / f"Q{q}_raw.csv").exists()
        fig_py = (run_path / f"Q{q}_fig.py").exists()
        fig_png = (run_path / f"Q{q}_fig.png").exists()
        summary_json = (raw_dir / f"Q{q}_summary.json").exists()

        # DYFA section check: look for ## Q<n> in the report
        dyfa = bool(re.search(
            rf"^##\s*[Qq]0*{q}\b", report_text, re.MULTILINE
        )) if report_text else False

        q_conform = all([analysis, raw_csv, fig_py, fig_png, summary_json, dyfa])
        if not q_conform:
            all_conform = False

        questions.append({
            "question": q,
            "has_analysis": analysis,
            "has_raw_csv": raw_csv,
            "has_fig_py": fig_py,
            "has_fig_png": fig_png,
            "has_summary_json": summary_json,
            "has_dyfa_section": dyfa,
        })

    return {"questions": questions, "all_conform": all_conform}


def normalize_run(project: Project, run_path: Path) -> dict[str, Any]:
    """Normalize a validator run folder into canonical deliverable shape.

    - Fuzzy-matches Q-numbered files and copies to canonical names.
    - Creates ``raw/Q<n>_summary.json`` from text output when missing.
    - Preserves all original files (copies, never deletes).
    - Reports what was normalized and what's still missing.

    Returns a dict with: normalized, files_moved, summary_json_created, missing, report.
    """
    question_count = int(project.study.get("questions", {}).get("count", 0))
    if not question_count:
        # Try to infer from the question map
        from .scorecard import load_question_map
        map_path = project.path(
            project.study.get("questions", {}).get("map", "questions_map.yaml")
        )
        if map_path.is_file():
            question_count = len(load_question_map(map_path))

    contract = check_deliverable_contract(run_path, question_count or 1)
    matches = _fuzzy_match_q_files(run_path)

    files_moved: list[dict[str, str]] = []
    summary_json_created: list[int] = []

    # Phase 1: rename fuzzy-matched files to canonical names
    for q_num, groups in matches.items():
        # Analysis scripts
        for source in groups.get("analysis", []):
            dest = run_path / _canonical_name(q_num, "analysis", source)
            if _copy_to_canonical(source, dest):
                files_moved.append({"from": str(source.relative_to(run_path)), "to": dest.name})

        # Figures — prefer one that's not already Q{n}_fig.png
        existing_fig = run_path / f"Q{q_num}_fig.png"
        if not existing_fig.exists() and groups.get("figures"):
            # Pick the best figure (prefer one with "fig" in the name)
            figs = groups["figures"]
            best = next((f for f in figs if "fig" in f.stem.lower()), figs[0])
            dest = run_path / f"Q{q_num}_fig.png"
            if _copy_to_canonical(best, dest):
                files_moved.append({"from": str(best.relative_to(run_path)), "to": dest.name})

        # Raw CSVs
        raw_dir = run_path / "raw"
        for source in groups.get("raw", []):
            dest = raw_dir / f"Q{q_num}_raw.csv"
            if _copy_to_canonical(source, dest):
                files_moved.append({"from": str(source.relative_to(run_path)), "to": f"raw/{dest.name}"})

        # Fig scripts
        for source in groups.get("other", []):
            if source.suffix == ".py" and "fig" in source.stem.lower():
                dest = run_path / f"Q{q_num}_fig.py"
                if _copy_to_canonical(source, dest):
                    files_moved.append({"from": str(source.relative_to(run_path)), "to": dest.name})

    # Phase 2: create missing summary.json from text output
    for q_num in range(1, (question_count or max(matches.keys(), default=0)) + 1):
        summary_path = run_path / "raw" / f"Q{q_num}_summary.json"
        if not summary_path.exists():
            text = _find_results_text(run_path, q_num)
            if text:
                parsed = _parse_summary_from_text(text, q_num)
                if parsed:
                    summary_path.parent.mkdir(parents=True, exist_ok=True)
                    summary_path.write_text(
                        json.dumps(parsed, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    summary_json_created.append(q_num)

    # Phase 3: build the report
    normalized: list[dict[str, Any]] = []
    missing: list[int] = []
    final_contract = check_deliverable_contract(run_path, question_count or 1)
    for q_info in final_contract["questions"]:
        q_num = q_info["question"]
        all_present = all([
            q_info["has_analysis"], q_info["has_raw_csv"],
            q_info["has_fig_py"], q_info["has_fig_png"],
            q_info["has_summary_json"],
        ])
        if not q_info["has_analysis"] and not q_info["has_fig_png"]:
            missing.append(q_num)
            normalized.append({"question": q_num, "status": "missing", "actions": []})
        elif all_present:
            normalized.append({"question": q_num, "status": "ok", "actions": []})
        else:
            actions = []
            if not q_info["has_analysis"]:
                actions.append("missing analysis script")
            if not q_info["has_raw_csv"]:
                actions.append("missing raw CSV")
            if not q_info["has_fig_py"]:
                actions.append("missing figure script")
            if not q_info["has_fig_png"]:
                actions.append("missing figure image")
            if not q_info["has_summary_json"]:
                actions.append("missing summary JSON")
            normalized.append({"question": q_num, "status": "partial", "actions": actions})

    report_lines = ["Normalization report:", ""]
    if files_moved:
        report_lines.append(f"  Files renamed: {len(files_moved)}")
        for item in files_moved:
            report_lines.append(f"    {item['from']} → {item['to']}")
    if summary_json_created:
        report_lines.append(f"  Summary JSON created: {summary_json_created}")
    if missing:
        report_lines.append(f"  Missing questions: {missing}")
    partial = [q for q in normalized if q["status"] == "partial"]
    if partial:
        report_lines.append(f"  Partial: {[q['question'] for q in partial]}")
    if not files_moved and not summary_json_created and not missing and not partial:
        report_lines.append("  Already conforming — no changes needed.")

    return {
        "normalized": normalized,
        "files_moved": files_moved,
        "summary_json_created": summary_json_created,
        "missing": missing,
        "report": "\n".join(report_lines),
    }
