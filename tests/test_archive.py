from __future__ import annotations

from pathlib import Path

import pytest

from rrg_cli import archive
from rrg_cli.errors import RRGError


def test_archive_then_restore_round_trip(ready_project):
    target = ready_project.path("operator/origin/README.md")
    original_bytes = target.read_bytes()

    record = archive.archive_item(ready_project, "operator/origin/README.md", kind="file")
    assert not target.exists(), "archiving moves the file out of its original path"
    assert (ready_project.root / record["stored"]).is_file()
    assert record in archive.list_archive(ready_project)

    restored = archive.restore_item(ready_project, record["id"])
    assert restored["restored"] == "operator/origin/README.md"
    assert target.is_file() and target.read_bytes() == original_bytes
    assert archive.list_archive(ready_project) == []


def test_purge_removes_payload_and_is_confined(ready_project):
    record = archive.archive_item(ready_project, "operator/origin/README.md")
    bucket = (ready_project.root / record["stored"]).parent
    assert bucket.is_dir()

    result = archive.purge_item(ready_project, record["id"])
    assert result["purged"] == "operator/origin/README.md"
    assert not bucket.exists()
    assert archive.list_archive(ready_project) == []
    # Purged ids no longer resolve.
    with pytest.raises(RRGError, match="no archived item"):
        archive.purge_item(ready_project, record["id"])


def test_restore_refuses_to_clobber(ready_project):
    record = archive.archive_item(ready_project, "operator/origin/README.md")
    # Recreate something at the original path before restoring.
    ready_project.path("operator/origin/README.md").write_text("squatter", encoding="utf-8")
    with pytest.raises(RRGError, match="already exists"):
        archive.restore_item(ready_project, record["id"])


def test_delete_grading_reroutes_to_archive(ready_project):
    from rrg_cli import grading

    run = "operator/replication_demo"
    grading.save_verdict(ready_project, run, 1, "REPRODUCED", "", True)
    assert grading.load_grading(ready_project, run)["verdicts"]

    result = grading.delete_grading(ready_project, run)
    assert result["id"] and "archived" in result
    assert not grading.load_grading(ready_project, run)["verdicts"]  # gone, not unlinked

    assert any(item["id"] == result["id"] and item["kind"] == "grading"
               for item in archive.list_archive(ready_project))
    archive.restore_item(ready_project, result["id"])
    assert grading.load_grading(ready_project, run)["verdicts"]  # recovered


def test_archive_refuses_outside_project_and_missing(ready_project):
    with pytest.raises(RRGError, match="nothing to archive"):
        archive.archive_item(ready_project, "operator/does_not_exist.md")
    with pytest.raises(RRGError, match="escapes project root|outside the project"):
        archive.archive_item(ready_project, "../escape.md")
