from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import RRGError
from .utils import confined, discover_root, load_yaml


def _normalize_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize the original vp_config manifest into the v1 standalone schema."""
    if int(raw.get("version", 0)) == 1:
        return raw
    config = dict(raw)
    config["version"] = 1
    if isinstance(config.get("project"), str):
        config["project"] = {"name": config["project"]}
    old_paths = config.get("paths", {}) or {}
    config["paths"] = {
        **old_paths,
        "shared": old_paths.get("shared", old_paths.get("model_facing_root", "shared")),
        "operator": old_paths.get("operator", old_paths.get("operator_root", "operator")),
        "packages": old_paths.get("packages", old_paths.get("package_out", "operator/_packages")),
    }
    constraints = dict(config.get("constraints", {}) or {})
    constraints.setdefault("exclude_vendors", constraints.get("exclude_as_validator", []))
    config["constraints"] = constraints
    stages = config.get("stages", {})
    stage_values = stages if isinstance(stages, list) else stages.values()
    for stage in stage_values:
        if not isinstance(stage, dict):
            continue
        if str(stage.get("data_plan", "")).upper() == "TBD":
            stage.setdefault("enabled", False)
            stage.setdefault(
                "blocked_reason",
                "Define the data-variation plan and method policy before enabling.",
            )
    return config


@dataclass(frozen=True)
class Project:
    root: Path
    config_path: Path
    study_path: Path
    config: dict[str, Any]
    study: dict[str, Any]

    @classmethod
    def load(
        cls,
        root: str | Path | None = None,
        config: str = "rrg.yaml",
        study: str = "study.yaml",
    ) -> "Project":
        resolved_root = discover_root(override=root)
        config_path = confined(resolved_root, config)
        if config == "rrg.yaml" and not config_path.exists() and (resolved_root / "RRG/vp_config.yaml").is_file():
            config_path = resolved_root / "RRG/vp_config.yaml"
        study_path = confined(resolved_root, study)
        if study == "study.yaml" and not study_path.exists() and (resolved_root / "RRG/study.yaml").is_file():
            study_path = resolved_root / "RRG/study.yaml"
        cfg = _normalize_config(load_yaml(config_path))
        cartridge = load_yaml(study_path)
        if "study" in cartridge:
            cartridge = cartridge["study"] or {}
        if not isinstance(cartridge, dict):
            raise RRGError("study.yaml must contain a study mapping")
        dataset = cartridge.setdefault("dataset", {})
        if isinstance(dataset, dict) and not dataset.get("metadata"):
            metadata = next(
                (
                    value
                    for value in (cfg.get("files", {}).get("all", []) or [])
                    if str(value).endswith(".meta.json")
                ),
                None,
            )
            if metadata:
                dataset["metadata"] = metadata
        return cls(resolved_root, config_path, study_path, cfg, cartridge)

    @property
    def name(self) -> str:
        return str(self.config.get("project", {}).get("name") or self.study.get("title") or self.root.name)

    def path(self, value: str | Path) -> Path:
        return confined(self.root, value)

    def path_setting(self, key: str, default: str) -> Path:
        return self.path(self.config.get("paths", {}).get(key, default))

    def stage(self, stage_id: str) -> dict[str, Any]:
        stages = self.config.get("stages", {})
        if isinstance(stages, list):
            match = next((item for item in stages if item.get("id") == stage_id), None)
        else:
            match = stages.get(stage_id)
        if not isinstance(match, dict):
            raise RRGError(f"unknown stage: {stage_id}")
        return {"id": stage_id, **match}

    def stage_ids(self) -> list[str]:
        stages = self.config.get("stages", {})
        if isinstance(stages, list):
            return [str(item["id"]) for item in stages if "id" in item]
        return list(stages)

    def roster(self, stage: str) -> list[dict[str, Any]]:
        entries = self.config.get("roster", {}).get(stage, [])
        return entries if isinstance(entries, list) else []

    def model(self, stage: str, query: str) -> dict[str, Any] | None:
        q = query.lower()
        return next(
            (entry for entry in self.roster(stage) if q in str(entry.get("model", "")).lower()),
            None,
        )
