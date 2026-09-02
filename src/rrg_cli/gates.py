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
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .normalize import IMAGE_EXTENSIONS, _extract_q_number

HARD = "hard"
SOFT = "soft"

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
        }

    def summary_line(self) -> str:
        if self.passed and not self.soft:
            return "PASS — deliverables conform to the contract."
        if self.passed:
            return f"PASS — {len(self.soft)} advisory note(s)."
        return f"FAIL — {len(self.hard)} blocking violation(s), {len(self.soft)} advisory."

    def feedback(self, attempt: int, max_revisions: int) -> str:
        """Model-facing revision turn. Filenames, keys, and codes only — nothing else."""
        found = (
            f"{len(self.hard)} blocking structural problem(s) and {len(self.soft)} advisory deviation(s)"
            if self.hard else f"{len(self.soft)} advisory deviation(s) from the required shape"
        )
        lines = [
            f"## Deliverable structure check — revision {attempt} of {max_revisions}",
            "",
            f"An automated check of your output found {found}. Fix the STRUCTURE only: rename, "
            "move, add, or repair the files listed below so they match the required names, "
            "locations, and shapes. Do not re-run the analysis, change any statistic or "
            "conclusion, or alter the methodology. Keep every existing file; add or rename "
            "rather than delete. If an advisory item genuinely does not apply, leave it and say why.",
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
                collapsed.append(f"- [{code}] on {qs} — e.g. {group[0].message}")
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
                line = f"- [{v.code}] {v.message}"
                if v.expected and v.expected not in v.message:
                    shown = v.expected if "`" in v.expected else f"`{v.expected}`"
                    line += f" → expected {shown}"
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
    if not folder.is_dir():
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
        if folder.name in {"raw", "__pycache__", ".git"} or any(part.startswith(".") for part in folder.relative_to(work_dir).parts):
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
        if not path.is_file() or path.name == ".DS_Store" or "__pycache__" in path.parts:
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
    nested = sorted(k for k, v in data.items() if isinstance(v, dict))
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


def check_gates(
    work_dir: str | Path,
    question_count: int,
    report_name: str = "",
    *,
    output_folder: str | None = None,
) -> GateResult:
    """Run every deliverable gate against a validator's output tree."""
    work_dir = Path(work_dir)
    root = locate_deliverable_root(work_dir, output_folder)
    result = GateResult(
        root=_rel(work_dir, root) if root != work_dir else ".",
        question_count=question_count,
        report_name=report_name,
    )
    out = result.violations

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
    for n in range(1, question_count + 1):
        present = _check_file_presence(root, n, candidates, out)
        _check_png(root, n, present.get("fig_png"), out)
        _check_summary(root, n, present.get("summary"), out)
        _check_scripts(root, n, present, out)
        _check_report_section(n, report_rel, report_text, out)

    return result
