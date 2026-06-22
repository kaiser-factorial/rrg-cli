from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import RRGError
from .project import Project


@dataclass(frozen=True)
class RoutedInput:
    source: Path
    package_name: str
    is_dir: bool = False


def resolve_send(project: Project, stage_id: str) -> list[RoutedInput]:
    stage = project.stage(stage_id)
    send = stage.get("send", []) or []
    registry = project.config.get("files", {}) or {}
    tokens: list[str] = []
    for token in send:
        if token in registry and isinstance(registry[token], list):
            tokens.extend(str(value) for value in registry[token])
        else:
            tokens.append(str(token))
    methodology = project.config.get("blinding", {}).get("per_stage_methodology", {}).get(stage_id, {})
    required = methodology.get("require", []) or []
    stage_specific = registry.get("stage_specific", []) or []
    for requirement in required:
        if any(Path(token).name == Path(requirement).name for token in tokens):
            continue
        match = next(
            (
                item.get("file")
                for item in stage_specific
                if Path(str(item.get("file", ""))).name == Path(requirement).name
                and stage_id in (item.get("send_in") or [])
            ),
            None,
        )
        if match:
            tokens.append(str(match))
        else:
            raise RRGError(f"required methodology is not routed: {requirement}")
    routed: list[RoutedInput] = []
    seen_names: dict[str, Path] = {}
    for token in tokens:
        path = project.path(token)
        if not path.exists():
            raise RRGError(f"routed input does not exist: {token}")
        name = path.name
        if name in seen_names and seen_names[name] != path:
            raise RRGError(f"package basename collision: {seen_names[name]} and {path}")
        seen_names[name] = path
        if not any(item.source == path for item in routed):
            routed.append(RoutedInput(path, name, path.is_dir()))
    return routed


def expected_package_files(inputs: list[RoutedInput]) -> set[str]:
    expected: set[str] = set()
    for item in inputs:
        if item.is_dir:
            expected.update(
                str(Path(item.package_name) / path.relative_to(item.source))
                for path in item.source.rglob("*")
                if path.is_file() and path.name != ".DS_Store"
            )
        else:
            expected.add(item.package_name)
    return expected
