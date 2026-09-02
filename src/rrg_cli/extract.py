"""Validator-led statistic extraction.

The validator emits structured per-question stats (``raw/Q<n>_summary.json``).
For each numerical value it reported, we compare against the origin's per-question
material using field-derived units and pipeline-owned policy. Exact, within-tolerance,
different, and unpaired values remain distinct so a tolerance never hides divergence.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from .errors import RRGError
from .project import Project
from .scorecard import _markdown_section

NARRATIVE_FILES = ("DYFA.md", "INVESTIGATION_SUMMARY.md", "SUMMARY.md", "RAW.md")

# Comparison tolerances are owned by the pipeline, never by validator output.  Exactness
# is always recorded separately: a value inside a tolerance band is still surfaced as a
# flagged, non-exact comparison.  All non-p fields are exact-only.
P_VALUE_ABS_TOLERANCE = 0.005

STATUS_EXACT = "exact"
STATUS_WITHIN_TOLERANCE = "within_tolerance"
STATUS_DIFFERENT = "different"
STATUS_VALIDATOR_ONLY = "validator_only"

_ORIGIN_FIELD_RE = re.compile(
    r"^\s*-\s*\*\*(?P<key>[A-Za-z0-9_ -]+)\*\*\s*[—–-]\s*(?P<value>.*)$"
)
_NUMBER_RE = re.compile(
    r"(?<![\w.])(?P<sign>[+-]?)\s*(?P<currency>\$)?\s*(?P<number>\d[\d,]*(?:\.\d+)?)"
)


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


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _is_p_label(label: str) -> bool:
    leaf = label.lower().split(".")[-1]
    return leaf in {"p", "p_value", "pvalue"} or leaf.endswith("_p") or leaf.endswith("_p_value")


def _value_kind(label: str, unit_hint: str = "") -> tuple[str, float]:
    """Return (comparison unit, multiplier to canonical units) from field structure."""
    lowered = label.lower()
    hinted = unit_hint.lower()
    if _is_p_label(label):
        return "p_value", 1.0
    if "percent" in lowered or "%" in hinted or "percent" in hinted or lowered.endswith("_pct") or ".pct" in lowered:
        return "percent", 1.0
    if "billion" in lowered or "billion" in hinted:
        return "usd", 1_000_000_000.0
    if "million" in lowered or "million" in hinted:
        return "usd", 1_000_000.0
    if lowered.endswith("_usd") or ".usd" in lowered or "_usd." in lowered or hinted in {"usd", "dollars"}:
        return "usd", 1.0
    return "scalar", 1.0


def _format_delta(label: str, canonical: float, unit_hint: str = "") -> str:
    kind, multiplier = _value_kind(label, unit_hint)
    shown = canonical / multiplier
    if kind == "usd" and multiplier == 1.0:
        sign = "-" if shown < 0 else ""
        magnitude = abs(shown)
        rendered = f"{magnitude:,.0f}" if magnitude == int(magnitude) else f"{magnitude:,.6g}"
        return f"{sign}${rendered}"
    if kind == "usd":
        unit = "billion USD" if multiplier == 1_000_000_000.0 else "million USD"
        return f"{shown:,.6g} {unit}"
    if kind == "percent":
        return f"{shown:,.6g} percentage points"
    return f"{shown:,.6g}"


def _origin_fields(text: str) -> dict[str, str]:
    """Parse the fixed origin-intake Markdown bullets without interpreting their values."""
    fields: dict[str, str] = {}
    current = ""
    for line in text.splitlines():
        match = _ORIGIN_FIELD_RE.match(line)
        if match:
            current = match.group("key").strip().lower().replace(" ", "_")
            fields[current] = match.group("value").strip()
        elif current and line.startswith((" ", "\t")):
            fields[current] = f"{fields[current]} {line.strip()}".strip()
        elif not line.strip():
            current = ""
    return fields


def _comparison_text(label: str, origin_text: str) -> str:
    fields = _origin_fields(origin_text)
    leaf = label.lower().split(".")[-1]
    if _is_p_label(label):
        return fields.get("p_value", origin_text)
    if leaf == "n":
        return fields.get("n", origin_text)
    if leaf in {"statistic", "effect_size"}:
        return fields.get(leaf, origin_text)
    # Extra validator metrics normally expand the origin's statistic/conclusion fields.
    focused = "\n".join(value for key, value in fields.items() if key in {"statistic", "conclusion"})
    return focused or origin_text


def _numeric_mentions(text: str) -> list[dict[str, Any]]:
    mentions: list[dict[str, Any]] = []
    for match in _NUMBER_RE.finditer(text):
        raw_number = match.group("number")
        try:
            number = float(raw_number.replace(",", ""))
        except ValueError:
            continue
        sign = -1.0 if match.group("sign") == "-" else 1.0
        tail = text[match.end():match.end() + 24]
        currency = bool(match.group("currency"))
        kind = "scalar"
        multiplier = 1.0
        unit_match = re.match(r"\s*(billion|million|%)", tail, re.IGNORECASE)
        unit = unit_match.group(1).lower() if unit_match else ""
        if currency or unit in {"billion", "million"}:
            kind = "usd"
            multiplier = 1_000_000_000.0 if unit == "billion" else 1_000_000.0 if unit == "million" else 1.0
        elif unit == "%":
            kind = "percent"
        shown_end = match.end() + (unit_match.end() if unit_match else 0)
        shown = re.sub(r"\s+", " ", text[match.start():shown_end]).strip()
        mentions.append({
            "value": sign * number * multiplier,
            "kind": kind,
            "shown": shown,
            "context": _context(text, match.start(), max(1, shown_end - match.start())),
        })
    return mentions


def compare_value(label: str, value: Any, origin_text: str, *, unit_hint: str = "") -> dict[str, Any]:
    """Compare one structured validator value with the normalized origin section.

    The field path determines units and policy.  Validator content cannot supply or
    widen a tolerance.  Exact matches remain distinct from within-tolerance flags.
    """
    base = {
        "label": label,
        "value": _format_value(value),
        "origin_value": "",
        "in_origin": False,
        "exact": False,
        "within_tolerance": False,
        "status": STATUS_VALIDATOR_ONLY,
        "delta": None,
        "delta_display": "",
        "tolerance": P_VALUE_ABS_TOLERANCE if _is_p_label(label) else 0.0,
        "policy": "p_value_abs" if _is_p_label(label) else "exact",
        "origin_context": "",
    }
    if not _is_number(value):
        return base

    kind, multiplier = _value_kind(label, unit_hint)
    canonical = float(value) * multiplier
    focused = _comparison_text(label, origin_text)
    candidates = _numeric_mentions(focused)

    # Untyped scalar fields should not be paired with currency or percentage tokens.
    compatible = [item for item in candidates if item["kind"] == kind]
    if kind == "p_value":
        # p-values are written as ordinary scalars in Markdown.
        has_p_context = bool(
            _origin_fields(origin_text).get("p_value")
            or re.search(r"\bp(?:[_ -]?value)?\s*[=<>:]", focused, re.IGNORECASE)
        )
        compatible = [item for item in candidates if item["kind"] == "scalar"] if has_p_context else []

    exact = [
        item for item in compatible
        if math.isclose(item["value"], canonical, rel_tol=1e-12, abs_tol=1e-12)
    ]
    if exact:
        item = exact[0]
        return {
            **base,
            "origin_value": item["shown"],
            "in_origin": True,
            "exact": True,
            "status": STATUS_EXACT,
            "delta": 0.0,
            "delta_display": "0",
            "origin_context": item["context"],
        }

    lowered_label = label.lower()
    leaf = lowered_label.split(".")[-1]
    can_pair_nearest = (
        leaf in {"n", "statistic", "effect_size"}
        or _is_p_label(label)
        or (kind in {"usd", "percent"} and "." not in label)
        or any(marker in lowered_label for marker in ("component_sum", "recomputed_net", "my1_2"))
    )
    if not compatible or "discrepanc" in lowered_label or not can_pair_nearest:
        return base
    nearest = compatible[0] if leaf == "n" else min(
        compatible, key=lambda item: abs(item["value"] - canonical)
    )
    delta = canonical - float(nearest["value"])
    tolerance = float(base["tolerance"])
    if kind != "p_value" and leaf != "n":
        scale = max(abs(canonical), abs(float(nearest["value"])), 1e-12)
        if abs(delta) / scale > 0.05:
            return base  # not close enough to claim these un-keyed values correspond
    within = tolerance > 0 and abs(delta) <= tolerance + 1e-12
    return {
        **base,
        "origin_value": nearest["shown"],
        "in_origin": within,
        "within_tolerance": within,
        "status": STATUS_WITHIN_TOLERANCE if within else STATUS_DIFFERENT,
        "delta": delta,
        "delta_display": _format_delta(label, delta, unit_hint),
        "origin_context": nearest["context"],
    }


def _unit_hint(payload: dict[str, Any], label: str) -> str:
    """Find a sibling `unit`/`units` value for a flattened metric path."""
    node: Any = payload
    parts = label.split(".")[:-1]
    try:
        for part in parts:
            node = node[int(part)] if isinstance(node, list) else node[part]
    except (KeyError, IndexError, TypeError, ValueError):
        return ""
    if isinstance(node, dict):
        value = node.get("unit", node.get("units", ""))
        return str(value) if value is not None else ""
    return ""


def _number_forms(number: float) -> list[str]:
    # Build an ordered list, not a set: ``sorted`` is stable, so equal-length forms keep
    # this insertion order (plain decimal, then comma-grouped, then percent). With a set
    # the tie order would follow PYTHONHASHSEED and ``find_value`` could report a
    # different ``matched_form`` from one run to the next.
    forms: list[str] = []
    if number == int(number) and abs(number) < 1e15:
        integer = int(number)
        forms.append(str(integer))
        forms.append(f"{integer:,}")
    for decimals in (0, 1, 2, 3, 4):
        forms.append(f"{number:.{decimals}f}")
        forms.append(f"{number:,.{decimals}f}")
    if abs(number) <= 1.5:  # percentage forms only make sense for proportions
        percent = number * 100
        for decimals in (0, 1, 2):
            forms.append(f"{percent:.{decimals}f}")
    # Drop forms that are too short to be meaningful on their own (e.g. "0").
    unique = dict.fromkeys(form for form in forms if len(form.lstrip("-")) >= 2)
    return sorted(unique, key=len, reverse=True)


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
            number = float(value)
            known.update(_number_forms(number))
            known.update(_number_forms(abs(number)))  # origin currency often renders the sign before `$`
            # Structured validator fields often store currency in base USD while the
            # origin renders millions or billions. Suppress those equivalent displays
            # from the origin-only list; field-level comparison still verifies units.
            if abs(number) >= 1_000_000:
                known.update(_number_forms(number / 1_000_000))
                known.update(_number_forms(number / 1_000_000_000))
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
        try:
            parsed = float(token.replace(",", ""))
            if 1900 <= parsed <= 2100 and parsed.is_integer():
                continue  # periods are context, not origin-only results
        except ValueError:
            pass
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
    origin_known_values: list[Any] = []
    for label, value in flatten(payload or {}):
        # Comparison rows are numerical results. Narrative metadata remains available in
        # the side-by-side report and should not become dozens of false "not found" stats.
        leaf = label.lower().split(".")[-1]
        if not _is_number(value) or label.lower() == "question" or leaf in {"rank", "score", "year"}:
            continue
        values.append(value)
        hint = _unit_hint(payload or {}, label)
        stats.append(compare_value(label, value, origin_text, unit_hint=hint))
        number = float(value)
        kind, multiplier = _value_kind(label, hint)
        origin_known_values.append(number)
        if kind == "usd":
            canonical = number * multiplier
            origin_known_values.extend((canonical, canonical / 1_000_000, canonical / 1_000_000_000))

    expect_exact = False
    if stage:
        try:
            expect_exact = str(project.stage(stage).get("methodology", "")).lower() == "revealed"
        except RRGError:
            expect_exact = False

    fields = _origin_fields(origin_text)
    origin_numeric_text = "\n".join(
        fields.get(key, "") for key in ("n", "statistic", "p_value", "effect_size")
    )
    if not origin_numeric_text.strip():
        origin_numeric_text = origin_text
    extra = origin_only(origin_numeric_text, origin_known_values)
    paired_origin = [str(row.get("origin_value", "")) for row in stats if row.get("origin_value")]
    extra = [
        item for item in extra
        if not any(item["value"].rstrip("%") in shown for shown in paired_origin)
    ]
    validator_highlights = _highlight_forms(values)
    # Ordered dedupe (stats order, then origin-only order) so equal-length marks keep a
    # fixed order instead of set iteration order.
    origin_marks = [row["origin_value"] for row in stats if row["origin_value"]]
    origin_marks.extend(item["value"].rstrip("%") for item in extra)
    origin_highlights = sorted(
        (mark for mark in dict.fromkeys(origin_marks) if len(mark) >= 2), key=len, reverse=True
    )

    deliverable = project.study.get("deliverable", {}) or {}
    report_template = str(deliverable.get("report_name", ""))
    report_name = report_template.replace("{MODEL}", "").replace("{model}", "").strip("_ ") if report_template else ""
    validator_narrative, validator_source = _narrative_section(run_dir, question_new, report_name)
    origin_narrative, origin_source = _narrative_section(key_dir, question_original, summary_name)

    return {
        "stats": stats,
        "comparison_counts": {
            status: sum(1 for row in stats if row["status"] == status)
            for status in (STATUS_EXACT, STATUS_WITHIN_TOLERANCE, STATUS_DIFFERENT, STATUS_VALIDATOR_ONLY)
        },
        "tolerance_policy": {
            "default": 0.0,
            "p_value_abs": P_VALUE_ABS_TOLERANCE,
            "within_tolerance_is_exact": False,
            "source": "pipeline field policy",
        },
        "stats_source": json_name,
        "has_validator_stats": payload is not None,
        "origin_only": extra,
        "expect_exact": expect_exact,
        "validator_highlights": validator_highlights,
        "origin_highlights": origin_highlights,
        "origin_narrative": origin_narrative,
        "origin_narrative_source": origin_source,
        "validator_narrative": validator_narrative,
        "validator_narrative_source": validator_source,
    }


def _highlight_forms(values: list[Any]) -> list[str]:
    forms: list[str] = []  # ordered, deduped below, so tie order is deterministic
    for value in values:
        try:
            forms.extend(_number_forms(float(value)))
        except (TypeError, ValueError):
            text = str(value).strip()
            if len(text) >= 3:
                forms.append(text)
    return sorted((form for form in dict.fromkeys(forms) if len(form) >= 2), key=len, reverse=True)
