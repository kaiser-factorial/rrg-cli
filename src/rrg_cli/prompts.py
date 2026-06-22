from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import RRGError
from .project import Project
from .utils import safe_label


MODULE_RE = re.compile(r"\{#([a-zA-Z0-9_]+)\}(.*?)\{/\1\}", re.DOTALL)
TOKEN_RE = re.compile(r"\{([A-Z][A-Z0-9_]*)\}")
TURN_RE = re.compile(r"^##\s+Turn\s+\d+\s*[—-]\s*(.+?)\s*$", re.MULTILINE)
REMINDER_RE = re.compile(r"^##\s+Operator reminders.*$", re.MULTILINE | re.IGNORECASE)
MODE_RE = re.compile(r"\s*\{mode:(discuss|nodiscuss)\}\s*", re.IGNORECASE)


@dataclass(frozen=True)
class PromptTurn:
    title: str
    text: str


@dataclass(frozen=True)
class RenderedPrompt:
    stage: str
    model: str
    turns: list[PromptTurn]
    reminders: str
    source: Path
    output_folder: str
    report_name: str

    @property
    def text(self) -> str:
        blocks = [f"## Turn {i} — {turn.title}\n\n{turn.text}" for i, turn in enumerate(self.turns, 1)]
        if self.reminders:
            blocks.append(f"## Operator reminders\n\n{self.reminders}")
        return "\n\n".join(blocks).rstrip() + "\n"


def _base(value: Any) -> str:
    return Path(str(value)).name if value else ""


def modules(study: dict[str, Any]) -> dict[str, bool]:
    dataset = study.get("dataset", {}) or {}
    return {
        "aux": bool((dataset.get("aux") or {}).get("enabled")),
        "given_solution": bool((study.get("given_solution") or {}).get("enabled")),
        "additional": bool(study.get("additional")),
        "method_guide": bool(((study.get("deliverable") or {}).get("method_guide") or {}).get("enabled")),
    }


def placeholders(project: Project, stage: str, model: str) -> dict[str, str]:
    study = project.study
    dataset = study.get("dataset", {}) or {}
    questions = study.get("questions", {}) or {}
    held = study.get("held_constants", {}) or {}
    original = study.get("original", {}) or {}
    delivery = study.get("deliverable", {}) or {}
    guide = delivery.get("method_guide", {}) or {}
    aux = dataset.get("aux", {}) or {}
    solution = study.get("given_solution", {}) or {}
    stage_cfg = project.stage(stage)
    label = safe_label(model)
    output = str(stage_cfg.get("output_folder", f"{stage}_{label}")).format(
        model=label, MODEL=label
    )
    report = str(stage_cfg.get("report_name") or delivery.get("report_name") or "{model}_Report.docx")
    report = report.format(model=label, MODEL=label)
    additional = study.get("additional", []) or []
    additional_text = "\n".join(
        f"- {item.get('name') or _base(item.get('file'))}: {_base(item.get('file'))}"
        + (f" — {item.get('note')}" if item.get("note") else "")
        for item in additional
    )
    formats = ", ".join(dataset.get("formats", []) or [])
    values = {
        "MODEL": model,
        "OUTPUT_FOLDER": output,
        "REPORT_NAME": report,
        "STUDY_OVERVIEW": _base(study.get("overview_file")),
        "MAIN_DATASET": str(dataset.get("main_name", "")),
        "MERGE_KEY": str(dataset.get("merge_key", "")),
        "FORMATS": formats,
        "CODEBOOK": _base(dataset.get("codebook")),
        "METADATA": _base(dataset.get("metadata")),
        "DATA_ORIENTATION": str(dataset.get("orientation", "")),
        "AUX_DATASET": str(aux.get("name") or _base(aux.get("file"))),
        "AUX_NOTE": str(aux.get("note", "")),
        "SOLUTION_GLOSSARY": _base(solution.get("glossary")),
        "SOLUTION_ARTIFACTS": ", ".join(_base(x) for x in solution.get("artifacts", []) or []),
        "GIVEN_SOLUTION_NOTE": str(solution.get("note", "")),
        "ADDITIONAL": additional_text,
        "QUESTIONS_FILE": _base(questions.get("file")),
        "N_QUESTIONS": str(questions.get("count", "")),
        "HELD_CONSTANTS_FILE": _base(held.get("file")),
        "HELD_CONSTANTS_SUMMARY": str(held.get("summary", "")),
        "HELD_CONSTANT_GROUPS": str(held.get("qa_groups", "")),
        "ORIGINAL_PROTOCOL": _base(original.get("methodology_file")),
        "RESULTS_KEY": str(original.get("results_key", "operator/results-key")),
        "REPORTING_SPEC": str(delivery.get("reporting_spec", "")),
        "METHOD_GUIDE_NAME": str(guide.get("name", "")),
        "METHOD_GUIDE_FILE": _base(guide.get("file")),
    }
    # Cartridge prose may itself contain placeholders.
    for _ in range(5):
        changed = False
        for key, value in list(values.items()):
            rendered = TOKEN_RE.sub(lambda match: values.get(match.group(1), match.group(0)), value)
            if rendered != value:
                values[key] = rendered
                changed = True
        if not changed:
            break
    return values


def render_text(text: str, values: dict[str, str], enabled: dict[str, bool]) -> str:
    def module_replace(match: re.Match[str]) -> str:
        return match.group(2) if enabled.get(match.group(1), False) else ""

    previous = None
    while previous != text:
        previous = text
        text = MODULE_RE.sub(module_replace, text)
    text = TOKEN_RE.sub(lambda match: values.get(match.group(1), match.group(0)), text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def unresolved_tokens(text: str) -> list[str]:
    return sorted(set(TOKEN_RE.findall(text)))


def parse_turns(text: str) -> tuple[list[PromptTurn], str]:
    reminder = REMINDER_RE.search(text)
    reminders = text[reminder.end() :].strip() if reminder else ""
    body = text[: reminder.start()] if reminder else text
    matches = list(TURN_RE.finditer(body))
    if not matches:
        raise RRGError("prompt has no `## Turn N — Title` sections")
    turns: list[PromptTurn] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        turns.append(PromptTurn(match.group(1).strip(), body[match.end() : end].strip()))
    return turns, reminders


def render_prompt(project: Project, stage: str, model: str, mode: str = "discuss") -> RenderedPrompt:
    stage_cfg = project.stage(stage)
    prompt_value = stage_cfg.get("prompt") or stage_cfg.get("prompt_doc")
    if not prompt_value:
        raise RRGError(f"stage {stage} has no prompt configured")
    source = project.path(prompt_value)
    if not source.is_file():
        raise RRGError(f"prompt not found: {source}")
    values = placeholders(project, stage, model)
    rendered = render_text(source.read_text(encoding="utf-8"), values, modules(project.study))
    missing = unresolved_tokens(rendered)
    if missing:
        raise RRGError(f"unresolved prompt placeholders: {', '.join(missing)}")
    turns, reminders = parse_turns(rendered)
    filtered: list[PromptTurn] = []
    for turn in turns:
        match = MODE_RE.search(turn.title)
        if match and match.group(1).lower() != mode:
            continue
        filtered.append(PromptTurn(MODE_RE.sub("", turn.title).strip(), MODE_RE.sub("", turn.text).strip()))
    turns = filtered
    return RenderedPrompt(
        stage=stage,
        model=model,
        turns=turns,
        reminders=reminders,
        source=source,
        output_folder=values["OUTPUT_FOLDER"],
        report_name=values["REPORT_NAME"],
    )
