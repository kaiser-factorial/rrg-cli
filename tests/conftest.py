from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rrg_cli.converter import convert_dataset
from rrg_cli.project import Project
from rrg_cli.scaffold import init_project


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    init_project(root)
    return root


@pytest.fixture
def ready_project(project_root: Path) -> Project:
    convert_dataset(project_root / "data/source.csv", project_root / "data/analysis")
    return Project.load(project_root)
