from __future__ import annotations

import fnmatch
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .project import Project
from .routing import expected_package_files, resolve_send

TEXT_EXTENSIONS = {".md", ".txt", ".yaml", ".yml", ".json", ".py", ".r", ".html"}
NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])[-+−]?\d*\.\d{2,4}%?(?![A-Za-z0-9])")


@dataclass(frozen=True)
class Finding:
    check: str
    severity: str
    message: str
    items: list[str] = field(default_factory=list)


@dataclass
class LintReport:
    package: str
    stage: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def hard_fails(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity == "hard_fail"]

    @property
    def flags(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity == "flag"]

    @property
    def passed(self) -> bool:
        return not self.hard_fails

    def add(self, check: str, severity: str, message: str, items: list[str] | None = None) -> None:
        self.findings.append(Finding(check, severity, message, items or []))

    def as_dict(self) -> dict[str, Any]:
        return {
            "package": self.package,
            "stage": self.stage,
            "passed": self.passed,
            "hard_fails": [asdict(item) for item in self.hard_fails],
            "flags": [asdict(item) for item in self.flags],
        }


def _files(package: Path) -> list[Path]:
    return sorted(path for path in package.rglob("*") if path.is_file() and path.name != ".DS_Store")


def _relative(path: Path, root: Path) -> str:
    return str(path.relative_to(root))


def _pattern_match(relative: str, pattern: str) -> bool:
    normalized = relative.replace("\\", "/")
    pattern = pattern.replace("\\", "/")
    plain = pattern.strip("/")
    return (
        fnmatch.fnmatch(normalized, pattern)
        or fnmatch.fnmatch(Path(normalized).name, pattern)
        or (plain and plain in normalized.split("/"))
        or (pattern.endswith("/") and normalized.startswith(plain + "/"))
    )


def _extract_result_tokens(root: Path) -> set[str]:
    tokens: set[str] = set()
    if not root.is_dir():
        return tokens
    for path in _files(root):
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        tokens.update(match.group(0).replace("−", "-").rstrip("%") for match in NUMBER_RE.finditer(text))
    return {token for token in tokens if token not in {".00", "0.00", "1.00"}}


def lint_package(package: Path, stage: str, project: Project) -> LintReport:
    package = package.resolve()
    report = LintReport(str(package), stage)
    package_files = _files(package)
    relatives = [_relative(path, package) for path in package_files]
    blinding = project.config.get("blinding", {}) or {}

    denied = list(blinding.get("always_withhold", []) or [])
    denied.extend(project.config.get("files", {}).get("withheld", []) or [])
    violations = sorted(
        {relative for relative in relatives for pattern in denied if _pattern_match(relative, str(pattern))}
    )
    if violations:
        report.add("withheld_files", "hard_fail", "Package contains withheld paths.", violations)

    method = blinding.get("per_stage_methodology", {}).get(stage, {}) or {}
    missing = [
        pattern
        for pattern in method.get("require", []) or []
        if not any(_pattern_match(relative, str(pattern)) for relative in relatives)
    ]
    if missing:
        report.add("stage_methodology_require", "hard_fail", "Required methodology is missing.", missing)
    forbidden = sorted(
        {
            relative
            for relative in relatives
            for pattern in method.get("forbid", []) or []
            if _pattern_match(relative, str(pattern))
        }
    )
    if forbidden:
        report.add("stage_methodology_forbid", "hard_fail", "Stage-forbidden methodology is present.", forbidden)

    try:
        expected = expected_package_files(resolve_send(project, stage))
    except Exception as exc:
        report.add("routing", "hard_fail", f"Could not resolve stage routing: {exc}")
        expected = set()
    extras = sorted(set(relatives) - expected - {"_provenance.json"})
    absent = sorted(expected - set(relatives))
    if extras or absent:
        items = [*(f"unexpected: {item}" for item in extras), *(f"missing: {item}" for item in absent)]
        report.add("routing", "hard_fail", "Package differs from the configured send list.", items)

    scan = blinding.get("result_token_scan", {}) or {}
    if scan.get("action", "flag") != "off":
        source_value = scan.get("source") or project.config.get("origin", {}).get("results_key")
        source = project.path(source_value) if source_value else Path("/__missing__")
        tokens = _extract_result_tokens(source)
        exclusions = scan.get("exclude_globs", []) or []
        hits: list[str] = []
        if tokens:
            for path, relative in zip(package_files, relatives):
                if path.suffix.lower() not in TEXT_EXTENSIONS:
                    continue
                if any(fnmatch.fnmatch(relative, pattern) for pattern in exclusions):
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore").replace("−", "-")
                found = sorted(token for token in tokens if token in text)
                if found:
                    hits.append(f"{relative}: {', '.join(found[:8])}")
        if hits:
            severity = "hard_fail" if scan.get("action") == "fail" else "flag"
            report.add("result_token_scan", severity, "Possible held-back result values appear in package text.", hits)
    return report
