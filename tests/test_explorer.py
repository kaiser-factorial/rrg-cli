from __future__ import annotations

from pathlib import Path

import pytest

from rrg_cli import archive
from rrg_cli.errors import RRGError
from rrg_cli.gui_service import GUIState


def _find(nodes, name):
    return next((node for node in nodes if node["name"] == name), None)


def _operator_origin(tree):
    operator = _find(tree, "operator")
    assert operator is not None
    return _find(operator["children"], "origin")


def test_blinding_aware_tree_redacts_withheld(ready_project):
    state = GUIState(ready_project)
    data = state.file_tree(xray=False)
    origin = _operator_origin(data["tree"])
    assert origin["redacted"] is True
    assert origin["children"] is None, "redacted dirs are not enumerated in blinding-aware view"


def test_xray_tree_reveals_withheld(ready_project):
    state = GUIState(ready_project)
    data = state.file_tree(xray=True)
    origin = _operator_origin(data["tree"])
    assert origin["redacted"] is False
    names = {child["name"] for child in (origin["children"] or [])}
    assert "SUMMARY.md" in names


def test_tree_file_gated_by_xray(ready_project):
    state = GUIState(ready_project)
    with pytest.raises(RRGError, match="withheld"):
        state.tree_file("operator/origin/SUMMARY.md", xray=False)
    assert state.tree_file("operator/origin/SUMMARY.md", xray=True)["kind"] == "text"


def test_tree_file_confined_to_project(ready_project):
    state = GUIState(ready_project)
    with pytest.raises(RRGError, match="escapes the project root"):
        state.tree_file("../../etc/passwd", xray=True)


def test_non_withheld_files_visible_in_both_modes(ready_project):
    state = GUIState(ready_project)
    for xray in (False, True):
        shared = _find(state.file_tree(xray=xray)["tree"], "shared")
        assert shared is not None and shared["redacted"] is False
        assert shared["children"], "shared/ is operator-visible content, never redacted"


def test_list_archive_via_service(ready_project):
    record = archive.archive_item(ready_project, "operator/origin/README.md")
    items = GUIState(ready_project).list_archive()["items"]
    assert any(item["id"] == record["id"] for item in items)
