from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

from . import extract as extract_module
from . import figures as figures_module
from . import grading as grading_module
from . import importer as importer_module
from . import origin as origin_module
from .converter import convert_dataset
from .doctor import inspect_project
from .errors import RRGError
from .packager import build_package
from .project import Project
from .prompts import render_prompt
from .scorecard import build_scorecard, load_question_map
from .utils import dump_yaml, load_yaml, safe_label

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
TEXT_EXTENSIONS = {".md", ".txt", ".json", ".yaml", ".yml", ".py", ".r", ".csv", ".html", ".log"}
STAGE_COLORS = ["#3fb950", "#6ea8fe", "#a371f7", "#e3b341", "#f778ba", "#39c5cf"]


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _atomic_yaml(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(dump_yaml(value))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class GUIState:
    def __init__(self, project: Project):
        self._lock = threading.RLock()
        self.project = project
        self._config_relative = str(project.config_path.relative_to(project.root))
        self._study_relative = str(project.study_path.relative_to(project.root))

    def reload(self) -> Project:
        with self._lock:
            self.project = Project.load(
                self.project.root,
                config=self._config_relative,
                study=self._study_relative,
            )
            return self.project

    def _provenance(self) -> list[dict[str, Any]]:
        path = self.project.path_setting("packages", "operator/_packages") / "provenance_log.jsonl"
        records: list[dict[str, Any]] = []
        if path.is_file():
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records

    def questions(self) -> list[dict[str, Any]]:
        value = self.project.study.get("questions", {}).get("map", "questions_map.yaml")
        return load_question_map(self.project.path(value))

    def _finalized_scorecards(self) -> set[str]:
        finalized: set[str] = set()
        grading_dir = self.project.path_setting("grading", "operator/_grading")
        if grading_dir.is_dir():
            for path in grading_dir.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                if isinstance(data, dict) and data.get("finalized") and data.get("scorecard"):
                    finalized.add(str(data["scorecard"]))
        return finalized

    def scorecards(self) -> list[dict[str, Any]]:
        operator = self.project.path_setting("operator", "operator")
        finalized = self._finalized_scorecards()
        cards = []
        for path in sorted(operator.glob("SCORECARD_*.md"), key=lambda item: item.stat().st_mtime, reverse=True):
            relative = str(path.relative_to(self.project.root))
            cards.append(
                {
                    "path": relative,
                    "name": path.name,
                    "size": path.stat().st_size,
                    "modified": path.stat().st_mtime,
                    "protected": relative in finalized,
                }
            )
        return cards

    def _excluded_run_roots(self) -> list[Path]:
        values = [
            self.project.study.get("original", {}).get("results_key"),
            self.project.config.get("origin", {}).get("results_key"),
        ]
        values.extend(self.project.config.get("files", {}).get("withheld", []) or [])
        roots = []
        for value in values:
            if not value or any(char in str(value) for char in "*?["):
                continue
            try:
                roots.append(self.project.path(value))
            except RRGError:
                continue
        return roots

    def runs(self) -> list[dict[str, Any]]:
        operator = self.project.path_setting("operator", "operator")
        records = self._provenance()
        by_output = {str(Path(record.get("output_folder", "")).resolve()): record for record in records}
        candidates: set[Path] = set()
        candidates.update(Path(path) for path in by_output if path)
        if operator.is_dir():
            candidates.update(path for path in operator.iterdir() if path.is_dir())
        excluded = self._excluded_run_roots()
        package_root = self.project.path_setting("packages", "operator/_packages")
        rows = []
        question_list = self.questions()
        for path in sorted(candidates, key=lambda item: item.name.lower()):
            try:
                path.resolve().relative_to(operator.resolve())
            except (ValueError, OSError):
                continue
            if path.resolve() == package_root.resolve() or path.name.startswith("_"):
                continue
            if any(path.resolve() == root.resolve() or root.resolve() in path.resolve().parents for root in excluded if root.exists()):
                continue
            if path.name.lower() in {"archive", "private", "factor_tooling"}:
                continue
            record = by_output.get(str(path.resolve()), {})
            stage = str(record.get("stage") or self._infer_stage(path.name))
            model = str(record.get("model") or path.name)
            files = [item for item in path.rglob("*") if item.is_file()] if path.is_dir() else []
            relative = str(path.relative_to(self.project.root))
            returned = bool(files)
            rows.append(
                {
                    "path": relative,
                    "name": path.name,
                    "stage": stage,
                    "model": model,
                    "returned": returned,
                    "file_count": len(files),
                    "graded": returned and grading_module.is_graded(self.project, relative, question_list),
                }
            )
        return rows

    def _infer_stage(self, value: str) -> str:
        lower = value.lower()
        for stage in self.project.stage_ids():
            if stage.lower() in lower:
                return stage
        if "replicate" in lower:
            return "replication"
        return "unknown"

    def stages(self) -> list[dict[str, Any]]:
        package_root = self.project.path_setting("packages", "operator/_packages")
        runs = self.runs()
        rows = []
        configs = [self.project.stage(stage_id) for stage_id in self.project.stage_ids()]
        configs.sort(key=lambda item: int(item.get("order", 999)))
        for index, config in enumerate(configs):
            stage_id = config["id"]
            folder = package_root / stage_id
            models = []
            for item in self.project.roster(stage_id):
                models.append(
                    {
                        "model": str(item.get("model", "")),
                        "vendor": str(item.get("vendor", "")),
                        "type": str(item.get("type", "")),
                        "license": str(item.get("license", "")),
                    }
                )
            rows.append(
                {
                    "id": stage_id,
                    "order": config.get("order", index + 1),
                    "color": config.get("color", STAGE_COLORS[index % len(STAGE_COLORS)]),
                    "enabled": bool(config.get("enabled", True)),
                    "blocked_reason": str(config.get("blocked_reason", "")),
                    "opens": str(config.get("opens", "")),
                    "methodology": str(config.get("methodology", "")),
                    "prompt": str(config.get("prompt") or config.get("prompt_doc") or ""),
                    "send": config.get("send", []) or [],
                    "models": models,
                    "packages": len([path for path in folder.iterdir() if path.is_dir()]) if folder.is_dir() else 0,
                    "returned": sum(1 for run in runs if run["stage"] == stage_id and run["returned"]),
                    "graded": sum(1 for run in runs if run["stage"] == stage_id and run["graded"]),
                }
            )
        return rows

    def bootstrap(self) -> dict[str, Any]:
        dataset = self.project.study.get("dataset", {}) or {}
        return {
            "project": self.project.name,
            "root": str(self.project.root),
            "config_path": self._config_relative,
            "study_path": self._study_relative,
            "study": self.project.study,
            "stages": self.stages(),
            "questions": self.questions(),
            "runs": self.runs(),
            "scorecards": self.scorecards(),
            "dispatch_start": str(self.project.config.get("dispatch", {}).get("start_template", "")),
            "dispatch_slugs": self.project.config.get("dispatch", {}).get("model_slugs", {}) or {},
            "dataset": {
                "source": dataset.get("source") or self.project.config.get("origin", {}).get("source_data", ""),
                "main_name": dataset.get("main_name", ""),
                "formats": dataset.get("formats", ["csv", "parquet"]),
                "codebook": dataset.get("codebook", ""),
                "metadata": dataset.get("metadata", ""),
            },
            "preflight": inspect_project(self.project, strict=True),
        }

    def run_detail(self, run_value: str) -> dict[str, Any]:
        allowed = {run["path"]: run for run in self.runs()}
        if run_value not in allowed:
            raise RRGError("run is not an allowed validator output folder")
        root = self.project.path(run_value)
        files = []
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            extension = path.suffix.lower()
            files.append(
                {
                    "path": str(path.relative_to(root)),
                    "size": path.stat().st_size,
                    "kind": "image" if extension in IMAGE_EXTENSIONS else ("text" if extension in TEXT_EXTENSIONS else "binary"),
                }
            )
        return {**allowed[run_value], "files": files}

    def run_file(self, run_value: str, file_value: str) -> dict[str, Any]:
        detail = self.run_detail(run_value)
        if file_value not in {item["path"] for item in detail["files"]}:
            raise RRGError("file is not part of this run")
        root = self.project.path(run_value)
        path = (root / file_value).resolve()
        path.relative_to(root.resolve())
        kind = next(item["kind"] for item in detail["files"] if item["path"] == file_value)
        if kind == "image":
            if path.stat().st_size > 10 * 1024 * 1024:
                raise RRGError("image is too large to preview")
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            return {"kind": "image", "data_url": f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"}
        if kind == "text":
            return {"kind": "text", "text": path.read_text(encoding="utf-8", errors="replace")[:2_000_000]}
        return {"kind": "binary", "message": "Binary preview is not available."}

    def _figure_matches(self, root: Path, question: int) -> list[Path]:
        boundary = re.compile(rf"(?:^|[^A-Za-z0-9])Q0*{question}(?:[^0-9]|$)", re.IGNORECASE)
        return [
            path
            for path in sorted(root.rglob("*"))
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS and boundary.search(str(path.relative_to(root)))
        ]

    def compare(self, run_value: str, question_number: int) -> dict[str, Any]:
        run = self.run_detail(run_value)
        question = next((item for item in self.questions() if item["new"] == question_number), None)
        if not question:
            raise RRGError(f"unknown question: {question_number}")
        run_root = self.project.path(run_value)
        key_value = self.project.study.get("original", {}).get("results_key") or self.project.config.get("origin", {}).get("results_key")
        key_root = self.project.path(key_value)

        def encoded(paths: list[Path], root: Path) -> list[dict[str, str]]:
            output = []
            for path in paths[:12]:
                if path.stat().st_size > 10 * 1024 * 1024:
                    continue
                mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                output.append(
                    {
                        "name": str(path.relative_to(root)),
                        "data_url": f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}",
                    }
                )
            return output

        grading_state = grading_module.load_grading(self.project, run_value)
        verdict_entry = grading_state["verdicts"].get(str(question_number), {})
        extraction = extract_module.question_extraction(
            self.project, run_value, question_number, question["original"], stage=run["stage"]
        )
        question_file = self.project.path(self.project.study.get("questions", {}).get("file", "shared/QUESTIONS.md"))
        question_texts = (
            origin_module.parse_numbered(question_file.read_text(encoding="utf-8", errors="ignore"))
            if question_file.is_file()
            else {}
        )
        origin_query = f"{question['topic']} {question_texts.get(question_number, '')}"
        return {
            "run": run,
            "question": question,
            "validator": figures_module.resolve_figures(run_root, question_number, extraction.get("validator_narrative", "")),
            "original": figures_module.resolve_figures(
                key_root,
                question["original"],
                extraction.get("origin_narrative", ""),
                report_path=origin_module._find_report(self.project, key_root),
                match_text=origin_query,
            ),
            "verdict": verdict_entry.get("verdict", ""),
            "note": verdict_entry.get("note", ""),
            "confirmed": bool(verdict_entry.get("confirmed")),
            "legend": grading_module.VERDICTS,
            **extraction,
        }

    @staticmethod
    def _headline_stat(stats: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Pick the one stat to surface in the overview grid. Prefer the top-level
        p-value, then a nested p, then the first reported value."""

        def rank(label: str) -> int:
            lowered = label.lower()
            if lowered == "p_value":
                return 0
            if lowered.endswith(".p_value") or lowered.endswith("_p_value"):
                return 1
            if lowered == "p" or lowered.endswith(".p") or lowered.endswith("_p"):
                return 2
            if "p_value" in lowered:
                return 3
            if lowered.startswith("p_") or "_p_" in lowered:
                return 4
            return 99

        ranked = sorted(((rank(stat["label"]), index, stat) for index, stat in enumerate(stats)))
        if ranked and ranked[0][0] < 99:
            return ranked[0][2]
        return stats[0] if stats else None

    def cross_run_overview(self) -> dict[str, Any]:
        """A question x run snapshot: each cell shows a run's headline statistic for
        that question and whether it was found in the origin. Cells link back to the
        per-question side-by-side. The origin column shows the origin's own rendering
        of the headline value wherever a run corroborated it."""
        questions = self.questions()
        returned = [run for run in self.runs() if run["returned"]]
        run_cols = [{"path": run["path"], "model": run["model"], "stage": run["stage"]} for run in returned]
        rows: list[dict[str, Any]] = []
        for question in questions:
            cells: list[dict[str, Any]] = []
            origin_value = ""
            for run in returned:
                extraction = extract_module.question_extraction(
                    self.project, run["path"], question["new"], question["original"], stage=run["stage"]
                )
                stat = self._headline_stat(extraction.get("stats", []))
                cell = {
                    "run": run["path"],
                    "has_stats": bool(extraction.get("has_validator_stats")),
                    "label": stat["label"] if stat else "",
                    "value": stat["value"] if stat else "",
                    "in_origin": bool(stat["in_origin"]) if stat else False,
                    "origin_value": stat["origin_value"] if stat else "",
                }
                if cell["in_origin"] and cell["origin_value"] and not origin_value:
                    origin_value = cell["origin_value"]
                cells.append(cell)
            matched = sum(1 for cell in cells if cell["in_origin"])
            with_stats = sum(1 for cell in cells if cell["has_stats"])
            rows.append(
                {
                    "new": question["new"],
                    "original": question["original"],
                    "topic": question["topic"],
                    "origin_value": origin_value,
                    "cells": cells,
                    "agreement": f"{matched}/{with_stats}" if with_stats else "—",
                }
            )
        return {"questions": [{"new": q["new"], "topic": q["topic"]} for q in questions], "runs": run_cols, "rows": rows}

    def _notes_path(self, run_value: str) -> Path:
        root = self.project.path_setting("compare_notes", "operator/_compare_notes")
        digest = hashlib.sha256(run_value.encode()).hexdigest()[:12]
        return root / f"{safe_label(Path(run_value).name)}-{digest}.json"

    def load_notes(self, run_value: str) -> dict[str, str]:
        self.run_detail(run_value)
        path = self._notes_path(run_value)
        if not path.is_file():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    def save_note(self, run_value: str, question: int, text: str) -> dict[str, str]:
        notes = self.load_notes(run_value)
        if text.strip():
            notes[str(question)] = text.strip()
        else:
            notes.pop(str(question), None)
        path = self._notes_path(run_value)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(notes, indent=2, ensure_ascii=False), encoding="utf-8")
        return notes

    def scorecard_content(self, value: str) -> dict[str, str]:
        allowed = {item["path"] for item in self.scorecards()}
        if value not in allowed:
            raise RRGError("scorecard is not an allowed operator scorecard")
        path = self.project.path(value)
        return {"path": value, "text": path.read_text(encoding="utf-8", errors="replace")}

    def origin_overview(self) -> dict[str, Any]:
        return origin_module.origin_overview(self.project)

    def origin_report(self) -> dict[str, Any]:
        return origin_module.origin_report(self.project)

    def origin_report_bytes(self) -> tuple[bytes, str]:
        return origin_module.origin_report_bytes(self.project)

    def methodology_prompt(self) -> dict[str, Any]:
        return origin_module.methodology_prompt(self.project)

    def save_methodology(self, text: str) -> dict[str, Any]:
        with self._lock:
            return origin_module.save_methodology(self.project, text)

    def intake_prompt(self) -> dict[str, Any]:
        return origin_module.intake_prompt(self.project)

    def save_intake(self, text: str) -> dict[str, Any]:
        with self._lock:
            return origin_module.save_intake(self.project, text)

    def render(self, stage: str, model: str, mode: str) -> dict[str, Any]:
        prompt = render_prompt(self.project, stage, model, mode=mode)
        return {
            "stage": stage,
            "model": model,
            "source": str(prompt.source.relative_to(self.project.root)),
            "output_folder": prompt.output_folder,
            "report_name": prompt.report_name,
            "turns": [{"title": turn.title, "text": turn.text} for turn in prompt.turns],
            "reminders": prompt.reminders,
        }

    def convert(self, payload: dict[str, Any]) -> dict[str, Any]:
        dataset = self.project.study.get("dataset", {}) or {}
        source = self.project.path(payload.get("source") or dataset.get("source") or self.project.config.get("origin", {}).get("source_data"))
        if payload.get("out"):
            output = self.project.path(payload["out"])
        else:
            output = self.project.path_setting("data", "data") / str(dataset.get("main_name") or source.stem)
        return convert_dataset(
            source,
            output,
            formats=payload.get("formats") or dataset.get("formats") or ["csv", "parquet"],
            labeled=bool(payload.get("labeled")),
            na_token=str(payload.get("na_token") or "__RRG_NA__"),
            float_format=payload.get("float_format"),
        )

    def package(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_package(
            self.project,
            str(payload.get("stage", "")),
            str(payload.get("model", "")),
            label=payload.get("label"),
            dry_run=bool(payload.get("dry_run")),
            force=bool(payload.get("force")),
            allow_unlisted=bool(payload.get("allow_unlisted")),
        )

    def import_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            return importer_module.import_run(
                self.project,
                payload.get("stage") or None,
                payload.get("model") or None,
                str(payload.get("source", "")),
                label=payload.get("label") or None,
                run_id=payload.get("run_id") or None,
            )

    def make_scorecard(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_scorecard(
            self.project,
            self.project.path(payload.get("run", "")),
            str(payload.get("stage", "")),
            str(payload.get("model", "")),
            license_name=str(payload.get("license") or "record-at-run-time"),
        )

    def _run_record(self, run_value: str) -> dict[str, Any]:
        record = next((run for run in self.runs() if run["path"] == run_value), None)
        if record is None:
            raise RRGError("run is not an allowed validator output folder")
        return record

    def grading_overview(self, run_value: str) -> dict[str, Any]:
        record = self._run_record(run_value)
        return {**grading_module.overview(self.project, run_value), "returned": record["returned"], "stage": record["stage"], "model": record["model"]}

    def save_verdict(self, run_value: str, question: int, verdict: str, note: str, confirmed: bool) -> dict[str, Any]:
        with self._lock:
            record = self._run_record(run_value)
            if not record["returned"]:
                raise RRGError("run has not returned yet; nothing to grade")
            return grading_module.save_verdict(self.project, run_value, question, verdict, note, confirmed)

    def finalize_grading(self, run_value: str) -> dict[str, Any]:
        with self._lock:
            record = self._run_record(run_value)
            return grading_module.finalize(self.project, run_value, record["stage"], record["model"])

    def reopen_grading(self, run_value: str) -> dict[str, Any]:
        with self._lock:
            self._run_record(run_value)
            return grading_module.reopen(self.project, run_value)

    def acknowledge_breach(self, run_value: str) -> dict[str, Any]:
        with self._lock:
            self._run_record(run_value)
            return grading_module.acknowledge_breach(self.project, run_value)

    def delete_grading(self, run_value: str) -> dict[str, Any]:
        with self._lock:
            self._run_record(run_value)
            return grading_module.delete_grading(self.project, run_value)

    def delete_scorecard(self, value: str) -> dict[str, Any]:
        with self._lock:
            return grading_module.delete_scorecard(self.project, value)

    def save_setup(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            study_patch = payload.get("study") or {}
            if not isinstance(study_patch, dict):
                raise RRGError("study patch must be an object")
            raw_study = load_yaml(self.project.study_path)
            wrapped = "study" in raw_study
            current_study = raw_study.get("study", raw_study) or {}
            merged_study = _deep_merge(current_study, study_patch)
            _atomic_yaml(self.project.study_path, {"study": merged_study} if wrapped else merged_study)

            config_patch = payload.get("engine") or {}
            if config_patch:
                raw_config = load_yaml(self.project.config_path)
                project_name = config_patch.get("project_name")
                if project_name is not None:
                    if isinstance(raw_config.get("project"), dict):
                        raw_config.setdefault("project", {})["name"] = project_name
                    else:
                        raw_config["project"] = project_name
                stage_patches = config_patch.get("stages") or []
                stages = raw_config.get("stages", {})
                for patch in stage_patches:
                    stage_id = patch.get("id")
                    target = None
                    if isinstance(stages, list):
                        target = next((item for item in stages if item.get("id") == stage_id), None)
                    elif stage_id in stages:
                        target = stages[stage_id]
                    if target is None:
                        continue
                    for key in ("enabled", "blocked_reason", "send", "color"):
                        if key in patch:
                            target[key] = patch[key]
                    if "prompt" in patch:
                        target["prompt_doc" if "prompt_doc" in target else "prompt"] = patch["prompt"]
                if "roster" in config_patch and isinstance(config_patch["roster"], dict):
                    raw_config["roster"] = config_patch["roster"]
                if "dispatch_start" in config_patch:
                    raw_config.setdefault("dispatch", {})["start_template"] = config_patch["dispatch_start"]
                if "model_slugs" in config_patch and isinstance(config_patch["model_slugs"], dict):
                    raw_config.setdefault("dispatch", {})["model_slugs"] = config_patch["model_slugs"]
                _atomic_yaml(self.project.config_path, raw_config)
            self.reload()
            return self.bootstrap()
