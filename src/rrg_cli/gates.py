"""Deterministic deliverable gates for validator returns.

The deliverable contract (``study.yaml > deliverable.reporting_spec``) is stated to the
validator in prose. Prose is not enforceable, so this module re-states the contract as a
set of pure, file-based checks and turns every deviation into a coded violation with the
expected fix attached. The dispatcher runs the gates when the validator says it is done,
and if anything hard fails it sends the violation list back as a revision turn — the same
observation → revision loop a plan-validation harness uses, applied to files on disk.

Design rules:

- Every check is a function of the files only. No model judgment, no network.
- Every violation carries ``code``, ``message``, the offending ``path`` (if any) and the
  ``expected`` path or shape, so the feedback can be acted on mechanically.
- **Hard** violations block and trigger a revision. **Soft** violations are advisory: they
  are reported and included in feedback when a revision is sent anyway, but never cause
  one on their own.
- Feedback text is model-facing and therefore blinding-sensitive: it is built only from
  filenames, key names, and codes — never from report contents or operator files.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .metrics import PUBLIC_SPEC_SCHEMA, validate_public_metric_specs
from .normalize import IMAGE_EXTENSIONS, _extract_q_number

HARD = "hard"
SOFT = "soft"

# Evidence from the executable gate lives here inside the deliverable root. It is never a
# deliverable itself and is excluded from near-miss detection.
EVIDENCE_DIR = "_gates"
EXEC_TIMEOUT = 120        # seconds per figure script
EXEC_TOTAL_TIMEOUT = 600  # seconds across all figure scripts in one gate pass

REQUIRED_SUMMARY_KEYS: tuple[str, ...] = (
    "question", "n", "test", "statistic", "p_value", "effect_size", "conclusion",
)
DYFA_LABELS: tuple[tuple[str, str], ...] = (("D", "Do"), ("Y", "Why"), ("F", "Find"), ("A", "Answer"))
INDEX_FILES: tuple[str, ...] = ("RAW.md", "SUMMARY.md")
REPORT_FALLBACKS: tuple[str, ...] = ("REPORT.md", "DYFA.md", "INVESTIGATION_SUMMARY.md")
PNG_MAGIC = b"\x89PNG"

# Heading regexes shared with normalize.check_deliverable_contract so gates and `rrg eval`
# never disagree about whether a question has a section.
_H2_RE = re.compile(r"^##\s+(?!#)", re.MULTILINE)
_P_BOUND_RE = re.compile(r"^\s*<\s*[0-9.]+(?:[eE][+-]?\d+)?\s*$")


def _q_heading_re(n: int) -> re.Pattern[str]:
    return re.compile(
        rf"^##\s*(?:[Qq]0*{n}\b|[Qq]uestion\s+0*{n}\b)", re.MULTILINE | re.IGNORECASE
    )


def _dyfa_label_re(letter: str, word: str) -> re.Pattern[str]:
    # Accepts "D - Do", "D — Do", "**D - Do**", "### D - Do", "D-Do".
    return re.compile(rf"\b{letter}\s*[-–—:]\s*{word}\b", re.IGNORECASE)


@dataclass(frozen=True)
class GateViolation:
    code: str
    message: str
    severity: str = HARD
    question: int | None = None
    path: str | None = None
    expected: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GateResult:
    root: str
    question_count: int
    report_name: str
    violations: list[GateViolation] = field(default_factory=list)
    exec_info: dict[str, Any] = field(default_factory=dict)

    @property
    def hard(self) -> list[GateViolation]:
        return [v for v in self.violations if v.severity == HARD]

    @property
    def soft(self) -> list[GateViolation]:
        return [v for v in self.violations if v.severity == SOFT]

    @property
    def passed(self) -> bool:
        """No hard violations. Decides pass/fail and the exit code."""
        return not self.hard

    @property
    def clean(self) -> bool:
        """No violations at all. Decides whether a revision turn is worth sending."""
        return not self.violations

    def as_observation(self) -> dict[str, Any]:
        """Machine-readable outcome, the analogue of a harness ``as_observation()``."""
        return {
            "ok": self.passed,
            "clean": self.clean,
            "root": self.root,
            "question_count": self.question_count,
            "report_name": self.report_name,
            "hard_count": len(self.hard),
            "soft_count": len(self.soft),
            "hard": [v.as_dict() for v in self.hard],
            "soft": [v.as_dict() for v in self.soft],
            "exec": self.exec_info,
        }

    def summary_line(self) -> str:
        if self.passed and not self.soft:
            return "PASS — deliverables conform to the contract."
        if self.passed:
            return f"PASS — {len(self.soft)} advisory note(s)."
        return f"FAIL — {len(self.hard)} blocking violation(s), {len(self.soft)} advisory."

    def feedback(self, attempt: int, max_revisions: int) -> str:
        """Model-facing revision turn. Codes and artifact coordinates only.

        The operator observation may contain useful diagnostics, but this rendering never
        repeats observed values or report prose.  In particular, it cannot become an
        origin-comparison oracle: the gate process never loads the held-back origin file.
        """
        found = (
            f"{len(self.hard)} blocking structural problem(s) and {len(self.soft)} advisory deviation(s)"
            if self.hard else f"{len(self.soft)} advisory deviation(s) from the required shape"
        )
        lines = [
            f"## Deterministic deliverable check — revision {attempt} of {max_revisions}",
            "",
            f"An automated check of your output found {found}. Repair only the coded artifacts "
            "below. Structural codes require naming/shape repairs. Metric, arithmetic, unit, "
            "and DYFA-consistency codes require you to recompute or transcribe from your own "
            "scripts and returned data, then make your own artifacts agree. Do not search for "
            "or infer any withheld comparison result, and do not change the methodology. If an "
            "advisory item genuinely does not apply, leave it and say why. Do not re-run the analysis "
            "for a structural-only code.",
            "",
            f"Output root checked: `{self.root}`",
            "",
        ]
        lines.extend(self._render_group("Blocking — must fix", self.hard))
        if self.soft:
            lines.extend(self._render_group("Advisory — fix unless it does not apply", self.soft))
        lines.extend([
            "When done, reply with the single line `GATES: fixed` followed by a list of the "
            "files you renamed, moved, added, or repaired.",
        ])
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _render_group(title: str, items: list[GateViolation], collapse_at: int = 4) -> list[str]:
        if not items:
            return []
        out = [f"### {title}", ""]
        # A code that fires on many questions (e.g. SUMMARY_NOT_FLAT on all 11) is one
        # instruction, not eleven: collapse it into a single line listing the questions.
        by_code: dict[str, list[GateViolation]] = {}
        for v in items:
            by_code.setdefault(v.code, []).append(v)
        collapsed: list[str] = []
        remaining: list[GateViolation] = []
        for code, group in by_code.items():
            questions = sorted({v.question for v in group if v.question is not None})
            if len(questions) >= collapse_at and len(questions) == len(group):
                qs = ", ".join(f"Q{q}" for q in questions)
                target = group[0].path or group[0].expected or "declared deliverable"
                collapsed.append(f"- [{code}] on {qs} — repair `{target}`")
            else:
                remaining.extend(group)
        if collapsed:
            out.append("**Across questions**")
            out.extend(collapsed)
            out.append("")
        by_q: dict[int | None, list[GateViolation]] = {}
        for v in remaining:
            by_q.setdefault(v.question, []).append(v)
        for q in sorted(by_q, key=lambda k: (k is None, k or 0)):
            out.append(f"**{'General' if q is None else f'Q{q}'}**")
            for v in by_q[q]:
                target = v.path or v.expected or "declared deliverable"
                line = f"- [{v.code}] repair `{target}`"
                if v.expected and v.expected != target:
                    line += f" to match `{v.expected}`"
                out.append(line)
            out.append("")
        return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def project_question_count(project: Any) -> int:
    """The study's question count, from ``questions.count`` or the question map."""
    questions = project.study.get("questions", {}) or {}
    count = int(questions.get("count", 0) or 0)
    if count:
        return count
    from .scorecard import load_question_map
    map_path = project.path(questions.get("map", "questions_map.yaml"))
    if map_path.is_file():
        try:
            return len(load_question_map(map_path))
        except Exception:  # pragma: no cover - malformed map falls back to 0
            return 0
    return 0


def project_report_name(project: Any, stage: str, model: str) -> str:
    """The configured report filename for a (stage, model), as the prompt states it."""
    from .utils import safe_label
    label = safe_label(model)
    stage_cfg = project.stage(stage)
    delivery = project.study.get("deliverable", {}) or {}
    report = str(stage_cfg.get("report_name") or delivery.get("report_name") or "{model}_Report.docx")
    return report.format(model=label, MODEL=label)


def gate_record(result: "GateResult", *, source: str) -> dict[str, Any]:
    """Wrap a single gate pass in the same shape the dispatch revision loop produces."""
    observation = result.as_observation()
    return {
        "enabled": True,
        "source": source,
        "passed": result.passed,
        "clean": result.clean,
        "revisions": 0,
        "max_revisions": 0,
        "root": result.root,
        "summary": result.summary_line(),
        "history": [observation],
        "final": observation,
    }


def _has_q_files(folder: Path) -> int:
    if not folder.is_dir() or folder.name == EVIDENCE_DIR:
        return 0
    return sum(
        1 for p in folder.iterdir()
        if p.is_file() and _extract_q_number(p.name) is not None
    )


def locate_deliverable_root(work_dir: Path, output_folder: str | None = None) -> Path:
    """Find where the validator actually put its deliverables.

    Prompts say "put all work in {OUTPUT_FOLDER}", so a conforming validator may nest its
    output one level down. Prefer that folder when it holds question files, then the work
    dir itself, then whichever folder in the tree holds the most question-numbered files.
    """
    work_dir = Path(work_dir)
    candidates: list[Path] = []
    if output_folder:
        candidates.append(work_dir / output_folder)
    candidates.append(work_dir)
    for candidate in candidates:
        if _has_q_files(candidate):
            return candidate
    best: Path | None = None
    best_count = 0
    for folder in sorted(p for p in work_dir.rglob("*") if p.is_dir()):
        if folder.name in {"raw", "__pycache__", ".git", EVIDENCE_DIR} or any(part.startswith(".") for part in folder.relative_to(work_dir).parts):
            continue
        count = _has_q_files(folder)
        if count > best_count:
            best, best_count = folder, count
    return best or work_dir


def _exists_exact(path: Path) -> bool:
    """``is_file()`` with an exact-case name match — APFS/NTFS would otherwise accept `q1_fig.png`."""
    if not path.is_file():
        return False
    try:
        return path.name in {p.name for p in path.parent.iterdir()}
    except OSError:
        return False


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _classify(path: Path) -> str | None:
    """Which deliverable kind a question-numbered file most plausibly is."""
    stem = path.stem.lower()
    suffix = path.suffix.lower()
    if suffix == ".py":
        return "fig_py" if "fig" in stem or "plot" in stem or "chart" in stem else "analysis"
    if suffix in IMAGE_EXTENSIONS:
        return "fig_png"
    if suffix == ".csv":
        return "raw_csv"
    if suffix == ".json":
        return "summary"
    return None


def _candidates(root: Path) -> dict[tuple[int, str], list[Path]]:
    """All question-numbered files in the tree, keyed by (question, kind)."""
    found: dict[tuple[int, str], list[Path]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == ".DS_Store" or "__pycache__" in path.parts or EVIDENCE_DIR in path.parts:
            continue
        q = _extract_q_number(path.name)
        kind = _classify(path)
        if q is None or kind is None:
            continue
        found.setdefault((q, kind), []).append(path)
    return found


def _to_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


_MISSING = object()
_BASE_SUMMARY_KEYS = set(REQUIRED_SUMMARY_KEYS) | {"_units"}
_METRIC_MARKER_RE = re.compile(
    r"`(?P<id>[A-Za-z][A-Za-z0-9_.-]*)\s*=\s*(?P<value>null|[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s+(?P<unit>[A-Za-z0-9_.%/-]+)`",
    re.IGNORECASE,
)


def _path_value(value: dict[str, Any], dotted: str) -> Any:
    current: Any = value
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def _numeric_leaf_paths(value: Any, prefix: str = "") -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if path == "_units" or path.startswith("_units."):
                continue
            if isinstance(child, dict):
                found.update(_numeric_leaf_paths(child, path))
            elif _decimal(child) is not None or child is None:
                found.add(path)
    return found


def _load_public_metric_contract(work_dir: Path, root: Path) -> dict[str, Any] | None:
    """Load only the validator-visible contract, never the operator origin contract."""
    candidates = [work_dir / "METRIC_SPEC.json", root / "METRIC_SPEC.json"]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {"_invalid": True, "_path": _rel(work_dir, path)}
        if not isinstance(value, dict) or validate_public_metric_specs(value):
            return {"_invalid": True, "_path": _rel(work_dir, path)}
        return value
    return None


def _check_metric_contract(
    root: Path,
    n: int,
    summary_path: Path | None,
    report_section: str | None,
    question_spec: dict[str, Any],
    out: list[GateViolation],
) -> None:
    if summary_path is None:
        return
    rel = _rel(root, summary_path)
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return  # the ordinary summary gate owns this violation
    if not isinstance(summary, dict):
        return
    metrics = question_spec.get("metrics", [])
    if not isinstance(metrics, list):
        return
    units = summary.get("_units")
    units = units if isinstance(units, dict) else {}
    by_id: dict[str, dict[str, Any]] = {}
    declared_paths: set[str] = set()
    values: dict[str, Any] = {}
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        metric_id = str(metric.get("id", ""))
        path = str(metric.get("validator_path", ""))
        by_id[metric_id] = metric
        declared_paths.add(path)
        value = _path_value(summary, path)
        values[metric_id] = value
        if value is _MISSING:
            out.append(GateViolation(
                "METRIC_MISSING", f"`{rel}` lacks declared metric `{metric_id}`",
                HARD, n, rel, f"metric `{metric_id}` at `{path}`",
            ))
        elif value is None:
            if not metric.get("nullable", False):
                out.append(GateViolation(
                    "METRIC_NULL_NOT_ALLOWED", f"`{rel}` metric `{metric_id}` may not be null",
                    HARD, n, rel, f"numeric metric `{metric_id}`",
                ))
        elif _decimal(value) is None:
            out.append(GateViolation(
                "METRIC_BAD_TYPE", f"`{rel}` metric `{metric_id}` must be a finite JSON number",
                HARD, n, rel, f"numeric metric `{metric_id}`",
            ))
        elif metric.get("kind") == "count" and Decimal(str(value)) != Decimal(str(value)).to_integral_value():
            out.append(GateViolation(
                "METRIC_BAD_TYPE", f"`{rel}` count metric `{metric_id}` must be an integer",
                HARD, n, rel, f"integer metric `{metric_id}`",
            ))
        if metric_id not in units:
            out.append(GateViolation(
                "METRIC_UNIT_MISSING", f"`{rel}` lacks `_units.{metric_id}`",
                HARD, n, rel, f"`_units.{metric_id}`",
            ))
        elif units[metric_id] != metric.get("unit"):
            out.append(GateViolation(
                "METRIC_UNIT_MISMATCH", f"`{rel}` declares the wrong unit for `{metric_id}`",
                HARD, n, rel, f"contract unit for `{metric_id}`",
            ))

    allowed_numeric = declared_paths | (_BASE_SUMMARY_KEYS - {"_units"})
    for path in sorted(_numeric_leaf_paths(summary) - allowed_numeric):
        out.append(GateViolation(
            "METRIC_EXTRA", f"`{rel}` contains undeclared numeric metric `{path}`",
            HARD, n, rel, f"declare `{path}` in METRIC_SPEC.json or remove it",
        ))

    for relation in question_spec.get("relations", []) or []:
        if not isinstance(relation, dict):
            continue
        input_values = [values.get(str(item), _MISSING) for item in relation.get("inputs", [])]
        output_value = values.get(str(relation.get("output")), _MISSING)
        if any(value is _MISSING or value is None or _decimal(value) is None for value in [*input_values, output_value]):
            continue
        decimals = [_decimal(value) for value in input_values]
        actual = _decimal(output_value)
        if relation.get("op") == "sum_equals":
            expected = sum((value for value in decimals if value is not None), Decimal(0))
        elif relation.get("op") == "difference_equals" and len(decimals) == 2:
            expected = decimals[0] - decimals[1]  # type: ignore[operator]
        else:
            continue
        if actual != expected:
            out.append(GateViolation(
                "ARITHMETIC_MISMATCH", f"`{rel}` violates relation `{relation.get('id')}`",
                HARD, n, rel, f"relation `{relation.get('id')}`",
            ))

    markers = {
        match.group("id"): (match.group("value").lower(), match.group("unit"))
        for match in _METRIC_MARKER_RE.finditer(report_section or "")
    }
    for metric_id, metric in by_id.items():
        value = values.get(metric_id, _MISSING)
        if value is _MISSING:
            continue
        marker = markers.get(metric_id)
        if marker is None:
            out.append(GateViolation(
                "DYFA_METRIC_MISSING", f"DYFA section lacks metric marker `{metric_id}`",
                HARD, n, rel, f"`{metric_id}=<value> {metric.get('unit')}`",
            ))
            continue
        shown, shown_unit = marker
        same_value = (value is None and shown == "null")
        if value is not None and shown != "null":
            try:
                same_value = Decimal(shown) == Decimal(str(value))
            except InvalidOperation:
                same_value = False
        if not same_value or shown_unit != metric.get("unit"):
            out.append(GateViolation(
                "DYFA_METRIC_MISMATCH", f"DYFA metric marker `{metric_id}` disagrees with `{rel}`",
                HARD, n, rel, f"same value and unit as `{metric_id}` in `{rel}`",
            ))


def _question_matches(value: Any, n: int) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return int(value) == n
    if isinstance(value, str):
        m = re.search(r"\d+", value)
        return bool(m) and int(m.group(0)) == n
    return False


def _find_report(root: Path, report_name: str) -> tuple[Path | None, bool]:
    """(report path or None, matched the configured name)."""
    exact = root / report_name if report_name else None
    if exact and exact.is_file():
        return exact, True
    for path in sorted(root.glob("*_Report.md")):
        if path.is_file():
            return path, False
    for name in REPORT_FALLBACKS:
        path = root / name
        if path.is_file():
            return path, False
    return None, False


def _section_for(report_text: str, n: int) -> str | None:
    match = _q_heading_re(n).search(report_text)
    if not match:
        return None
    rest = report_text[match.end():]
    nxt = _H2_RE.search(rest)
    return rest[: nxt.start()] if nxt else rest


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

_KIND_SPEC: tuple[tuple[str, str, str], ...] = (
    # kind, canonical relative path template, human label
    ("analysis", "Q{n}_analysis.py", "analysis script"),
    ("raw_csv", "raw/Q{n}_raw.csv", "raw output CSV"),
    ("fig_py", "Q{n}_fig.py", "figure script"),
    ("fig_png", "Q{n}_fig.png", "figure image"),
    ("summary", "raw/Q{n}_summary.json", "summary JSON"),
)


def _check_file_presence(
    root: Path, n: int, candidates: dict[tuple[int, str], list[Path]], out: list[GateViolation]
) -> dict[str, Path | None]:
    present: dict[str, Path | None] = {}
    for kind, template, label in _KIND_SPEC:
        expected_rel = template.format(n=n)
        expected = root / expected_rel
        if _exists_exact(expected):
            present[kind] = expected
            if expected.stat().st_size == 0:
                out.append(GateViolation(
                    "EMPTY_FILE", f"`{expected_rel}` is empty", HARD, n, expected_rel, expected_rel,
                ))
            continue
        present[kind] = None
        near = [p for p in candidates.get((n, kind), []) if p != expected]
        if near:
            observed = near[0]
            observed_rel = _rel(root, observed)
            if observed.name == expected.name:
                code, verb = "MISPLACED_FILE", "is in the wrong folder"
            else:
                code, verb = "MISNAMED_FILE", "does not use the required name"
            out.append(GateViolation(
                code, f"{label} `{observed_rel}` {verb}; rename/move it to `{expected_rel}`",
                HARD, n, observed_rel, expected_rel,
            ))
        else:
            out.append(GateViolation(
                "MISSING_FILE", f"no {label} for Q{n}; write `{expected_rel}`",
                HARD, n, None, expected_rel,
            ))
    return present


def _check_png(root: Path, n: int, path: Path | None, out: list[GateViolation]) -> None:
    if path is None:
        return
    rel = _rel(root, path)
    try:
        head = path.read_bytes()[:8]
    except OSError:
        head = b""
    if head and not head.startswith(PNG_MAGIC):
        out.append(GateViolation(
            "INVALID_PNG", f"`{rel}` is not a PNG image (wrong bytes at start of file)",
            HARD, n, rel, "a real PNG written by Q{n}_fig.py".format(n=n),
        ))


def _check_summary(root: Path, n: int, path: Path | None, out: list[GateViolation]) -> None:
    if path is None:
        return
    rel = _rel(root, path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        out.append(GateViolation(
            "INVALID_JSON", f"`{rel}` is not valid JSON ({exc.__class__.__name__})",
            HARD, n, rel, "a single flat JSON object",
        ))
        return
    if not isinstance(data, dict):
        out.append(GateViolation(
            "SUMMARY_NOT_OBJECT", f"`{rel}` must be a single JSON object, not {type(data).__name__}",
            HARD, n, rel, "a single flat JSON object",
        ))
        return
    missing = [k for k in REQUIRED_SUMMARY_KEYS if k not in data]
    for key in missing:
        hint = " (null if not applicable)" if key == "effect_size" else ""
        out.append(GateViolation(
            "SUMMARY_MISSING_KEY", f"`{rel}` lacks required key `{key}`{hint}",
            HARD, n, rel, f"key `{key}`",
        ))
    if "question" in data and not _question_matches(data["question"], n):
        out.append(GateViolation(
            "SUMMARY_QUESTION_MISMATCH",
            f"`{rel}` has `question` = {json.dumps(data['question'])[:40]} but the file is for Q{n}",
            HARD, n, rel, f"`question`: {n}",
        ))
    if "n" in data and data["n"] is not None and _to_number(data["n"]) is None:
        out.append(GateViolation(
            "SUMMARY_BAD_TYPE", f"`{rel}` key `n` must be a number", HARD, n, rel, "`n`: <number>",
        ))
    if "statistic" in data and data["statistic"] is not None and _to_number(data["statistic"]) is None:
        out.append(GateViolation(
            "SUMMARY_BAD_TYPE", f"`{rel}` key `statistic` must be a number (or null)",
            HARD, n, rel, "`statistic`: <number>",
        ))
    if "p_value" in data:
        p = data["p_value"]
        num = _to_number(p)
        if num is not None and num == 0:
            out.append(GateViolation(
                "P_VALUE_ZERO",
                f"`{rel}` has `p_value` = 0; the contract requires the exact value, never a rounded 0",
                HARD, n, rel, "`p_value`: the exact (unrounded) value, e.g. 3.2e-17",
            ))
        elif num is None and p is not None:
            if isinstance(p, str) and _P_BOUND_RE.match(p):
                out.append(GateViolation(
                    "P_VALUE_BOUND_STRING",
                    f"`{rel}` has `p_value` as the bound string {json.dumps(p)}; prefer the numeric "
                    "value (add `p_value_log10` if it underflows)",
                    SOFT, n, rel, "`p_value`: <number>",
                ))
            else:
                out.append(GateViolation(
                    "SUMMARY_BAD_TYPE",
                    f"`{rel}` key `p_value` must be a JSON number, not {type(p).__name__}; put the numeric "
                    "value in `p_value` and any annotation (z, log10(p), bound) in a separate key such as `p_value_note`",
                    HARD, n, rel, "`p_value`: <number>",
                ))
        elif p is None:
            out.append(GateViolation(
                "P_VALUE_NULL", f"`{rel}` has `p_value` = null; give the exact value unless the question is purely descriptive",
                SOFT, n, rel, "`p_value`: <number>",
            ))
    if "conclusion" in data and (not isinstance(data["conclusion"], str) or not data["conclusion"].strip()):
        out.append(GateViolation(
            "SUMMARY_BAD_TYPE", f"`{rel}` key `conclusion` must be a non-empty one-sentence string",
            HARD, n, rel, "`conclusion`: \"<one sentence>\"",
        ))
    nested = sorted(k for k, v in data.items() if isinstance(v, dict) and k != "_units")
    if nested:
        out.append(GateViolation(
            "SUMMARY_NOT_FLAT",
            f"`{rel}` nests objects under {', '.join(f'`{k}`' for k in nested)}; the contract asks for a flat object",
            SOFT, n, rel, "flat key: value pairs (lists of scalars are fine)",
        ))


def _mentions(text: str, n: int, suffix: str) -> bool:
    """Does a script name `Q<n><suffix>`, literally or via a template (`Q{q}`, `Q%d`, `Q{}`)?"""
    if f"Q{n}{suffix}" in text:
        return True
    return bool(re.search(rf"Q(?:\{{[^}}]*\}}|%[sd]){re.escape(suffix)}", text))


def _check_scripts(root: Path, n: int, present: dict[str, Path | None], out: list[GateViolation]) -> None:
    """The scripts must name the files the contract binds them to: analysis → raw CSV,
    figure script → reads that CSV and writes that PNG. A script that never names the
    file cannot be doing so, so these are hard."""
    analysis = present.get("analysis")
    fig_py = present.get("fig_py")
    if analysis is not None:
        text = analysis.read_text(encoding="utf-8", errors="ignore")
        if not _mentions(text, n, "_raw.csv"):
            out.append(GateViolation(
                "ANALYSIS_NO_CSV_WRITE",
                f"`{_rel(root, analysis)}` never names `raw/Q{n}_raw.csv`; it must write its raw outputs to exactly that file",
                HARD, n, _rel(root, analysis), f"raw/Q{n}_raw.csv",
            ))
    if fig_py is not None:
        text = fig_py.read_text(encoding="utf-8", errors="ignore")
        if not _mentions(text, n, "_raw.csv"):
            out.append(GateViolation(
                "FIG_SCRIPT_NO_CSV_READ",
                f"`{_rel(root, fig_py)}` never names `raw/Q{n}_raw.csv`; it must read that CSV rather than recompute",
                HARD, n, _rel(root, fig_py), f"raw/Q{n}_raw.csv",
            ))
        if not _mentions(text, n, "_fig.png"):
            out.append(GateViolation(
                "FIG_SCRIPT_NO_PNG_WRITE",
                f"`{_rel(root, fig_py)}` never names `Q{n}_fig.png`; it must write exactly that file",
                HARD, n, _rel(root, fig_py), f"Q{n}_fig.png",
            ))


def _check_report_section(
    n: int, report_rel: str | None, report_text: str, out: list[GateViolation]
) -> None:
    if report_rel is None:
        return  # MISSING_REPORT already reported once
    section = _section_for(report_text, n)
    if section is None:
        out.append(GateViolation(
            "MISSING_DYFA_SECTION", f"`{report_rel}` has no `## Q{n}` / `## Question {n}` section",
            HARD, n, report_rel, f"## Q{n} … with D - Do / Y - Why / F - Find / A - Answer",
        ))
        return
    missing = [f"{l} - {w}" for l, w in DYFA_LABELS if not _dyfa_label_re(l, w).search(section)]
    if missing:
        out.append(GateViolation(
            "MISSING_DYFA_LABELS",
            f"`{report_rel}` section for Q{n} lacks label(s): {', '.join(missing)}",
            HARD, n, report_rel, "labels `D - Do`, `Y - Why`, `F - Find`, `A - Answer`",
        ))
    if f"Q{n}_fig.png" not in section:
        out.append(GateViolation(
            "FIGURE_NOT_EMBEDDED", f"`{report_rel}` section for Q{n} does not embed `Q{n}_fig.png`",
            HARD, n, report_rel, f"![Q{n} figure](Q{n}_fig.png)",
        ))


# ---------------------------------------------------------------------------
# Executable figure gate
# ---------------------------------------------------------------------------
#
# The static checks prove a figure script *names* its CSV and PNG. Running it proves it
# *produces* the delivered PNG from that CSV — the file-system analogue of a harness
# rendering the compiled spec. The delivered PNG is moved aside, the script is run in
# the deliverable root (under the same OS sandbox as the validator, when given), the
# regenerated PNG is compared byte-wise and then pixel-wise, and the delivered PNG is
# always restored. Identical → the regenerated copy is discarded. Different → it is kept
# under `_gates/` as evidence and the question fails.

_PROBE = "import matplotlib, pandas"
_PROBE_CACHE: dict[str, bool] = {}  # interpreter path -> imports the validator stack


def _probe(exe: str) -> bool:
    if exe not in _PROBE_CACHE:
        try:
            result = subprocess.run([exe, "-c", _PROBE], capture_output=True, timeout=90)
            _PROBE_CACHE[exe] = result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            _PROBE_CACHE[exe] = False
    return _PROBE_CACHE[exe]


def _under_any(path: str, roots: list[str]) -> bool:
    real = Path(os.path.realpath(path))
    for root in roots:
        try:
            real.relative_to(Path(os.path.realpath(root)))
            return True
        except ValueError:
            continue
    return False


def resolve_gate_python(
    work_dir: str | Path, preferred: str = "", deny: list[str] | None = None,
) -> tuple[str | None, str]:
    """The interpreter to run figure scripts with: (path or None, note).

    Order: the configured ``gate_python``; a ``.venv`` the validator built in the work dir;
    then ``python3``, ``/usr/bin/python3`` and this process's interpreter — the first that
    imports matplotlib and pandas wins. The scripts are validator code and need the
    validator's stack, which this process's venv may not carry. Interpreters living under
    a ``deny`` path are skipped: the scripts run inside the sandbox, which could not even
    read such an interpreter (RRG's own venv sits inside the denied checkout).
    """
    candidates: list[str] = []
    if preferred:
        candidates.append(preferred)
    venv = Path(work_dir) / ".venv" / "bin" / "python"
    if venv.exists():
        candidates.append(str(venv))
    candidates += ["python3", "/usr/bin/python3", sys.executable]
    tried: list[str] = []
    skipped: list[str] = []
    for candidate in candidates:
        exe = candidate if os.path.isabs(candidate) else shutil.which(candidate)
        if not exe or not os.path.exists(exe) or exe in tried or exe in skipped:
            continue
        if deny and _under_any(exe, deny):
            skipped.append(exe)
            continue
        tried.append(exe)
        if _probe(exe):
            return exe, f"probed {len(tried)} interpreter(s)"
    note = "no interpreter imports matplotlib and pandas; tried " + ", ".join(tried)
    if skipped:
        note += "; skipped (inside sandbox deny list) " + ", ".join(skipped)
    return None, note


# Fraction of pixels allowed to differ before a regenerated figure counts as a different
# figure. Calibrated on 22 real figures re-rendered under a different matplotlib
# (3.10.6 → 3.9.4): identical layout, 2–6 % of pixels changed by text anti-aliasing.
DRIFT_TOLERANCE = 0.15


def _png_compare(a: Path, b: Path) -> tuple[str, str]:
    """Compare a delivered PNG with its regeneration.

    Returns ``("identical", …)`` when bytes or pixels match, ``("drift", …)`` when the
    dimensions match and fewer than :data:`DRIFT_TOLERANCE` of pixels differ (a different
    renderer, same figure), else ``("mismatch", …)``.
    """
    try:
        if a.read_bytes() == b.read_bytes():
            return "identical", "bytes identical"
    except OSError:
        return "mismatch", "unreadable"
    try:
        from PIL import Image
        import numpy as np
    except ImportError:  # pragma: no cover - both are dependencies
        return "mismatch", "bytes differ; Pillow/numpy unavailable for pixel comparison"
    try:
        with Image.open(a) as ia, Image.open(b) as ib:
            if ia.size != ib.size:
                return "mismatch", f"size {ia.size[0]}x{ia.size[1]} vs {ib.size[0]}x{ib.size[1]}"
            pa = np.asarray(ia.convert("RGB"), dtype=np.int16)
            pb = np.asarray(ib.convert("RGB"), dtype=np.int16)
    except Exception as exc:
        return "mismatch", f"bytes differ and pixels could not be compared ({exc.__class__.__name__})"
    differing = float((np.abs(pa - pb).max(axis=2) > 0).mean())
    if differing == 0:
        return "identical", "pixels identical"
    if differing <= DRIFT_TOLERANCE:
        return "drift", f"{differing:.1%} of pixels differ (renderer drift, same figure)"
    return "mismatch", f"{differing:.1%} of pixels differ"


def _run_figure_script(
    root: Path, n: int, python: str, timeout: int, prefix: list[str], out: list[GateViolation],
) -> str:
    """Regenerate Q<n>_fig.png in place. Returns one of: identical, mismatch, failed,
    timeout, missing, env."""
    fig_py = root / f"Q{n}_fig.py"
    png = root / f"Q{n}_fig.png"
    evidence = root / EVIDENCE_DIR
    evidence.mkdir(exist_ok=True)
    aside = evidence / f"Q{n}_fig.delivered.png"
    png.replace(aside)
    status = "failed"
    try:
        env = {**os.environ, "MPLBACKEND": "Agg"}
        try:
            proc = subprocess.run(
                [*prefix, python, fig_py.name], cwd=root, capture_output=True, text=True,
                timeout=timeout, env=env,
            )
        except subprocess.TimeoutExpired:
            out.append(GateViolation(
                "FIG_SCRIPT_TIMEOUT", f"`Q{n}_fig.py` did not finish within {timeout}s",
                HARD, n, f"Q{n}_fig.py", f"`python Q{n}_fig.py` writes Q{n}_fig.png in under {timeout}s",
            ))
            return "timeout"
        if proc.returncode != 0:
            tail = " | ".join(line for line in proc.stderr.strip().splitlines()[-3:])[:300]
            (evidence / f"Q{n}_fig.stderr.txt").write_text(proc.stderr, encoding="utf-8")
            if "ModuleNotFoundError" in proc.stderr or "ImportError" in proc.stderr:
                out.append(GateViolation(
                    "FIG_SCRIPT_ENV_MISSING",
                    f"`Q{n}_fig.py` needs a module the gate interpreter lacks ({tail})",
                    SOFT, n, f"Q{n}_fig.py", "a script that runs with matplotlib + pandas",
                ))
                return "env"
            out.append(GateViolation(
                "FIG_SCRIPT_FAILED", f"`Q{n}_fig.py` exited {proc.returncode}: {tail}",
                HARD, n, f"Q{n}_fig.py", f"`python Q{n}_fig.py` runs cleanly from the output root",
            ))
            return "failed"
        if not png.is_file():
            out.append(GateViolation(
                "FIG_NOT_REGENERATED", f"`Q{n}_fig.py` ran but did not write `Q{n}_fig.png`",
                HARD, n, f"Q{n}_fig.py", f"Q{n}_fig.png",
            ))
            return "missing"
        verdict, how = _png_compare(aside, png)
        if verdict == "identical":
            png.unlink()
            return "identical"
        if verdict == "drift":
            png.unlink()
            out.append(GateViolation(
                "FIG_RENDER_DRIFT",
                f"`Q{n}_fig.py` reproduces `Q{n}_fig.png` up to renderer differences ({how})",
                SOFT, n, f"Q{n}_fig.png", None,
            ))
            return "drift"
        regenerated = evidence / f"Q{n}_fig.regenerated.png"
        png.replace(regenerated)
        out.append(GateViolation(
            "FIG_MISMATCH",
            f"running `Q{n}_fig.py` produced a different `Q{n}_fig.png` than delivered ({how}); "
            f"the delivered figure must be exactly what the script writes from raw/Q{n}_raw.csv",
            HARD, n, f"Q{n}_fig.png", f"Q{n}_fig.png == output of Q{n}_fig.py",
        ))
        return "mismatch"
    finally:
        if png.exists() and png != aside:
            png.unlink()
        aside.replace(png)
        try:
            evidence.rmdir()  # only succeeds when no evidence was kept
        except OSError:
            pass


def run_figure_gate(
    root: Path,
    questions: list[int],
    *,
    python: str | None,
    timeout: int = EXEC_TIMEOUT,
    total_timeout: int = EXEC_TOTAL_TIMEOUT,
    prefix: list[str] | None = None,
    out: list[GateViolation],
) -> dict[str, Any]:
    info: dict[str, Any] = {
        "python": python, "attempted": [], "identical": [], "drift": [], "results": {}, "skipped": [],
    }
    if not questions:
        return info
    if python is None:
        out.append(GateViolation(
            "NO_GATE_INTERPRETER",
            "figure scripts were not executed: no interpreter with matplotlib and pandas was found "
            "(set the `gate_python` pref)",
            SOFT, None, None, "gate_python pref pointing at the validator's Python",
        ))
        info["skipped"] = list(questions)
        return info
    started = time.monotonic()
    for n in questions:
        if time.monotonic() - started > total_timeout:
            info["skipped"].append(n)
            out.append(GateViolation(
                "FIG_EXEC_SKIPPED", f"`Q{n}_fig.py` was not executed: gate time budget ({total_timeout}s) exhausted",
                SOFT, n, f"Q{n}_fig.py", None,
            ))
            continue
        info["attempted"].append(n)
        status = _run_figure_script(root, n, python, timeout, prefix or [], out)
        info["results"][str(n)] = status
        if status == "identical":
            info["identical"].append(n)
        elif status == "drift":
            info["drift"].append(n)
    return info


def check_gates(
    work_dir: str | Path,
    question_count: int,
    report_name: str = "",
    *,
    output_folder: str | None = None,
    exec_figures: bool = False,
    exec_python: str | None = None,
    exec_timeout: int = EXEC_TIMEOUT,
    exec_total_timeout: int = EXEC_TOTAL_TIMEOUT,
    exec_prefix: list[str] | None = None,
    exec_deny: list[str] | None = None,
) -> GateResult:
    """Run every deliverable gate against a validator's output tree.

    With ``exec_figures``, questions whose static figure checks pass also have their
    figure script executed (see :func:`run_figure_gate`). ``exec_python`` is the
    interpreter to use (resolved via :func:`resolve_gate_python` when None) and
    ``exec_prefix`` an argv prefix such as an OS sandbox wrapper.
    """
    work_dir = Path(work_dir)
    root = locate_deliverable_root(work_dir, output_folder)
    result = GateResult(
        root=_rel(work_dir, root) if root != work_dir else ".",
        question_count=question_count,
        report_name=report_name,
    )
    out = result.violations
    metric_contract = _load_public_metric_contract(work_dir, root)
    if metric_contract and metric_contract.get("_invalid"):
        out.append(GateViolation(
            "INVALID_METRIC_SPEC", "validator-visible METRIC_SPEC.json is invalid",
            HARD, None, str(metric_contract.get("_path") or "METRIC_SPEC.json"),
            f"schema `{PUBLIC_SPEC_SCHEMA}`",
        ))
        metric_contract = None

    if question_count < 1:
        out.append(GateViolation(
            "NO_QUESTION_COUNT", "the study declares no questions, so per-question gates cannot run",
            SOFT, None, None, "questions.count in study.yaml",
        ))

    report_path, exact = _find_report(root, report_name)
    report_rel: str | None = None
    report_text = ""
    if report_path is None:
        out.append(GateViolation(
            "MISSING_REPORT", f"no report file found (looked for `{report_name or '*_Report.md'}`)",
            HARD, None, None, report_name or "*_Report.md",
        ))
    else:
        report_rel = _rel(root, report_path)
        report_text = report_path.read_text(encoding="utf-8", errors="ignore")
        if report_name and not exact:
            out.append(GateViolation(
                "REPORT_MISNAMED", f"report is `{report_rel}` but the required name is `{report_name}`",
                SOFT, None, report_rel, report_name,
            ))

    for name in INDEX_FILES:
        if not (root / name).is_file():
            out.append(GateViolation(
                "MISSING_INDEX", f"`{name}` is missing; it should index the per-question artifacts",
                HARD, None, None, name,
            ))

    candidates = _candidates(root)
    executable: list[int] = []
    for n in range(1, question_count + 1):
        before = len(out)
        present = _check_file_presence(root, n, candidates, out)
        _check_png(root, n, present.get("fig_png"), out)
        _check_summary(root, n, present.get("summary"), out)
        _check_scripts(root, n, present, out)
        _check_report_section(n, report_rel, report_text, out)
        if metric_contract is not None:
            question_spec = (metric_contract.get("questions", {}) or {}).get(str(n))
            if not isinstance(question_spec, dict):
                out.append(GateViolation(
                    "METRIC_SPEC_QUESTION_MISSING", f"METRIC_SPEC.json lacks Q{n}",
                    HARD, n, "METRIC_SPEC.json", f"questions.{n}",
                ))
            else:
                _check_metric_contract(
                    root, n, present.get("summary"), _section_for(report_text, n),
                    question_spec, out,
                )
        figure_ok = all(present.get(k) is not None for k in ("fig_py", "fig_png", "raw_csv")) and not any(
            v.severity == HARD and v.code in {"INVALID_PNG", "EMPTY_FILE", "FIG_SCRIPT_NO_CSV_READ", "FIG_SCRIPT_NO_PNG_WRITE"}
            for v in out[before:]
        )
        if figure_ok:
            executable.append(n)

    if exec_figures:
        python = exec_python
        note = "given"
        if python is None:
            python, note = resolve_gate_python(work_dir, deny=exec_deny)
        result.exec_info = run_figure_gate(
            root, executable, python=python, timeout=exec_timeout,
            total_timeout=exec_total_timeout, prefix=exec_prefix, out=out,
        )
        result.exec_info["interpreter_note"] = note
    return result
