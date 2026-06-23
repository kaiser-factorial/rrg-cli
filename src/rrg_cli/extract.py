"""Validator-led statistic extraction.

The validator emits structured per-question stats (``raw/Q<n>_summary.json``). For
each value it reported, we look for the *same value* in the origin's per-question
material and mark whether it was found. This makes the two sides apples-to-apples:
"the validator reported chi2 = 1815.7 — did the origin report that too?" Matching is
value-based (with formatting variants) so it survives different labels and prose.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .errors import RRGError
from .project import Project
from .scorecard import _markdown_section

NARRATIVE_FILES = ("DYFA.md", "INVESTIGATION_SUMMARY.md", "SUMMARY.md", "RAW.md")


def flatten(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            items.extend(flatten(child, f"{prefix}{key}."))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            items.extend(flatten(child, f"{prefix}{index}."))
    else:
        items.append((prefix.rstrip(".") or "value", value))
    return items


def _number_forms(number: float) -> list[str]:
    forms: set[str] = set()
    if number == int(number) and abs(number) < 1e15:
        integer = int(number)
        forms.add(str(integer))
        forms.add(f"{integer:,}")
    for decimals in (0, 1, 2, 3, 4):
        forms.add(f"{number:.{decimals}f}")
        forms.add(f"{number:,.{decimals}f}")
    percent = number * 100
    for decimals in (0, 1, 2):
        forms.add(f"{percent:.{decimals}f}")
    # Drop forms that are too short to be meaningful on their own (e.g. "0").
    return sorted((form for form in forms if len(form.lstrip("-")) >= 2), key=len, reverse=True)


def _context(text: str, index: int, length: int) -> str:
    start = max(0, index - 45)
    end = min(len(text), index + length + 45)
    snippet = re.sub(r"\s+", " ", text[start:end]).strip()
    return ("…" if start > 0 else "") + snippet + ("…" if end < len(text) else "")


def find_value(value: Any, text: str) -> tuple[bool, str, str]:
    """Return (found, matched_form, context). ``matched_form`` is the origin's own
    rendering of the number (e.g. "88.3" where the validator reported 0.8832)."""
    if not text:
        return False, "", ""
    try:
        number = float(value)
        numeric = not isinstance(value, bool)
    except (TypeError, ValueError):
        numeric = False
    if numeric:
        for form in _number_forms(number):
            match = re.search(r"(?<![\d.,])" + re.escape(form) + r"(?![\d])", text)
            if match:
                return True, form, _context(text, match.start(), len(form))
        return False, "", ""
    needle = str(value).strip()
    if len(needle) < 2:
        return False, "", ""
    lowered = text.lower().find(needle.lower())
    if lowered >= 0:
        return True, needle, _context(text, lowered, len(needle))
    return False, "", ""


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if value == int(value) and abs(value) < 1e15:
            return f"{int(value):,}"
        rounded = f"{value:.4f}".rstrip("0").rstrip(".")
        return rounded if abs(value) < 1e6 else f"{value:.6g}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def origin_only(origin_text: str, validator_values: list[Any], limit: int = 14) -> list[dict[str, str]]:
    """Numbers the origin reported that the validator did not — so the human sees
    information the origin had beyond the validator's stat set."""
    known: set[str] = set()
    for value in validator_values:
        try:
            known.update(_number_forms(float(value)))
        except (TypeError, ValueError):
            known.add(str(value))
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in re.finditer(r"(?<![\w.,])([-+]?\d[\d,]*(?:\.\d+)?)(%?)", origin_text):
        token = match.group(1)
        full = token + match.group(2)
        bare = token.replace(",", "").lstrip("-")
        if full in known or token in known:
            continue
        if "." not in token and len(bare) < 2:  # skip bare single digits
            continue
        if bare in seen:
            continue
        seen.add(bare)
        results.append({"value": full, "context": _context(origin_text, match.start(), len(full))})
        if len(results) >= limit:
            break
    return results


def _validator_json(run_dir: Path, question_new: int) -> tuple[dict[str, Any] | None, str]:
    for candidate in (run_dir / "raw" / f"Q{question_new}_summary.json", run_dir / f"Q{question_new}_summary.json"):
        if candidate.is_file():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data, str(candidate.name)
            except (json.JSONDecodeError, OSError):
                continue
    return None, ""


def _narrative_section(directory: Path, question: int, configured: str = "") -> tuple[str, str]:
    names = ([configured] if configured else []) + list(NARRATIVE_FILES)
    for name in names:
        path = directory / Path(name).name
        if path.is_file():
            section = _markdown_section(path.read_text(encoding="utf-8", errors="ignore"), question)
            if section.strip():
                return section, path.name
    return "", ""


def _origin_question_text(key_dir: Path, question_original: int, summary_name: str) -> str:
    chunks: list[str] = []
    boundary = re.compile(rf"(?:^|[^A-Za-z0-9])[Qq]0*{question_original}(?:[^0-9]|$)")
    if key_dir.is_dir():
        for path in sorted(key_dir.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".txt", ".md", ".json", ".csv"}:
                continue
            if boundary.search(path.name):
                chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
    narrative, _ = _narrative_section(key_dir, question_original, summary_name)
    if narrative:
        chunks.append(narrative)
    return "\n\n".join(chunks)


def question_extraction(
    project: Project,
    run_value: str,
    question_new: int,
    question_original: int,
    stage: str = "",
) -> dict[str, Any]:
    run_dir = project.path(run_value)
    original = project.study.get("original", {}) or {}
    key_dir = project.path(original.get("results_key", "operator/origin"))
    summary_name = Path(str(original.get("summary_file", ""))).name

    payload, json_name = _validator_json(run_dir, question_new)
    origin_text = _origin_question_text(key_dir, question_original, summary_name)

    stats = []
    values = []
    for label, value in flatten(payload or {}):
        values.append(value)
        found, matched, context = find_value(value, origin_text)
        stats.append(
            {
                "label": label,
                "value": _format_value(value),
                "origin_value": matched,
                "in_origin": found,
                "origin_context": context,
            }
        )

    expect_exact = False
    if stage:
        try:
            expect_exact = str(project.stage(stage).get("methodology", "")).lower() == "revealed"
        except RRGError:
            expect_exact = False

    deliverable = project.study.get("deliverable", {}) or {}
    report_template = str(deliverable.get("report_name", ""))
    report_name = report_template.replace("{MODEL}", "").replace("{model}", "").strip("_ ") if report_template else ""
    validator_narrative, validator_source = _narrative_section(run_dir, question_new, report_name)
    origin_narrative, origin_source = _narrative_section(key_dir, question_original, summary_name)

    return {
        "stats": stats,
        "stats_source": json_name,
        "has_validator_stats": payload is not None,
        "origin_only": origin_only(origin_text, values),
        "expect_exact": expect_exact,
        "origin_narrative": origin_narrative,
        "origin_narrative_source": origin_source,
        "validator_narrative": validator_narrative,
        "validator_narrative_source": validator_source,
    }
