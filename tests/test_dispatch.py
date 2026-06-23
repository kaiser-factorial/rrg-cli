from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from rrg_cli.errors import RRGError
from rrg_cli.gui_service import GUIState
from rrg_cli.importer import import_run
from rrg_cli.packager import build_package


def test_package_writes_delivery_zip(ready_project):
    result = build_package(ready_project, "replication", "ReplicationModel")
    assert result["published"] is True and result["package_zip"]
    zip_path = Path(result["package_zip"])
    assert zip_path.is_file()
    with zipfile.ZipFile(zip_path) as bundle:
        names = bundle.namelist()
    assert names, "delivery zip should not be empty"
    assert "_provenance.json" not in names, "operator metadata must not be delivered"


def test_package_mints_run_id_and_suffixes_names(ready_project):
    result = build_package(ready_project, "replication", "ReplicationModel")
    run_id = result["run_id"]
    assert run_id and len(run_id) == 8 and all(c in "0123456789abcdef" for c in run_id)
    assert result["provenance"]["run_id"] == run_id
    # The run folder, package dir, and zip all carry the run_id suffix.
    assert result["output_folder"].endswith(f"__{run_id}")
    assert Path(result["package_dir"]).name.endswith(f"__{run_id}")
    assert Path(result["package_zip"]).name == f"ReplicationModel__{run_id}.zip"


def test_repackage_does_not_clobber_run_folder(ready_project):
    first = build_package(ready_project, "replication", "ReplicationModel")
    second = build_package(ready_project, "replication", "ReplicationModel")
    assert first["run_id"] != second["run_id"]
    assert first["output_folder"] != second["output_folder"]
    # Both run folders survive — re-running a model accumulates history, never overwrites.
    assert Path(first["output_folder"]).is_dir()
    assert Path(second["output_folder"]).is_dir()


def test_import_targets_run_id_folder(ready_project, tmp_path: Path):
    built = build_package(ready_project, "replication", "ReplicationModel")
    returned = tmp_path / "returned"
    returned.mkdir()
    (returned / "SUMMARY.md").write_text("## Q1\nok", encoding="utf-8")
    result = import_run(
        ready_project, "replication", "ReplicationModel", returned, run_id=built["run_id"]
    )
    # An explicit run_id lands the results in exactly the folder the build created.
    assert result["output_folder"] == built["output_folder"]
    assert (Path(built["output_folder"]) / "SUMMARY.md").is_file()


def test_import_without_run_id_resolves_latest_build(ready_project, tmp_path: Path):
    build_package(ready_project, "replication", "ReplicationModel")
    latest = build_package(ready_project, "replication", "ReplicationModel")
    returned = tmp_path / "returned"
    returned.mkdir()
    (returned / "SUMMARY.md").write_text("## Q1\nok", encoding="utf-8")
    result = import_run(ready_project, "replication", "ReplicationModel", returned)
    # With no run_id given, import resolves to the newest run_id-suffixed build folder.
    assert result["output_folder"] == latest["output_folder"]


def test_delivery_zip_carries_run_marker(ready_project):
    result = build_package(ready_project, "replication", "ReplicationModel")
    with zipfile.ZipFile(result["package_zip"]) as bundle:
        assert "RRG_RUN.txt" in bundle.namelist()
        marker = bundle.read("RRG_RUN.txt").decode("utf-8")
    # Marker is blinding-safe: only the opaque run_id, nothing about study/methods/results.
    assert result["run_id"] in marker
    assert "ReplicationModel" not in marker and "replication" not in marker


def test_import_auto_resolves_from_marker(ready_project, tmp_path: Path):
    from rrg_cli.importer import render_run_marker

    built = build_package(ready_project, "robustness", "RobustnessModel")
    bundle = tmp_path / "returned.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("RRG_RUN.txt", render_run_marker(built["run_id"]))
        archive.writestr("SUMMARY.md", "## Q1\nok")
    # No stage/model passed — the marker drives full resolution.
    result = import_run(ready_project, source=bundle)
    assert result["auto_resolved"] is True
    assert result["stage"] == "robustness" and result["model"] == "RobustnessModel"
    assert result["run_id"] == built["run_id"]
    assert result["output_folder"] == built["output_folder"]


def test_import_without_marker_requires_stage_and_model(ready_project, tmp_path: Path):
    returned = tmp_path / "returned"
    returned.mkdir()
    (returned / "SUMMARY.md").write_text("## Q1\nok", encoding="utf-8")
    with pytest.raises(RRGError, match="could not resolve the run"):
        import_run(ready_project, source=returned)
    # Explicit stage/model still works as the manual fallback.
    result = import_run(ready_project, "replication", "ReplicationModel", returned)
    assert result["count"] == 1 and result["auto_resolved"] is False


def test_import_flags_copied_answer_key_and_blocks_grading(ready_project, tmp_path: Path):
    from rrg_cli import grading

    # Simulate a validator that copied the withheld origin answer key into its output.
    key_bytes = ready_project.path("operator/origin/SUMMARY.md").read_bytes()
    returned = tmp_path / "returned"
    returned.mkdir()
    (returned / "leaked.md").write_bytes(key_bytes)

    result = import_run(ready_project, "replication", "ReplicationModel", returned)
    copied = result["breach"]["copied_secrets"]
    assert copied and copied[0]["matches"] == "operator/origin/SUMMARY.md"

    # Grading is blocked until the breach is acknowledged.
    with pytest.raises(RRGError, match="blinding breach"):
        grading.save_verdict(ready_project, result["run"], 1, "REPRODUCED", "", True)
    grading.acknowledge_breach(ready_project, result["run"])
    grading.save_verdict(ready_project, result["run"], 1, "REPRODUCED", "", True)  # unblocked


def test_clean_import_records_no_breach(ready_project, tmp_path: Path):
    from rrg_cli import grading

    returned = tmp_path / "returned"
    returned.mkdir()
    (returned / "SUMMARY.md").write_text("## Q1\nmy own reproduction", encoding="utf-8")
    result = import_run(ready_project, "replication", "ReplicationModel", returned)
    assert not result["breach"]["copied_secrets"]
    assert result["breach"]["ran_inside_project"] is False
    assert grading.load_breach(ready_project, result["run"]) is None


def test_import_from_inside_project_warns_without_blocking(ready_project, tmp_path: Path):
    from rrg_cli import grading

    inside = ready_project.path("returned_inside")
    inside.mkdir(parents=True)
    (inside / "SUMMARY.md").write_text("## Q1\nok", encoding="utf-8")
    result = import_run(ready_project, "replication", "ReplicationModel", inside)
    assert result["breach"]["ran_inside_project"] is True
    assert not result["breach"]["copied_secrets"]
    # Soft signal only — grading is not blocked.
    grading.save_verdict(ready_project, result["run"], 1, "REPRODUCED", "", True)


def test_import_run_from_directory(ready_project, tmp_path: Path):
    returned = tmp_path / "returned"
    (returned / "raw").mkdir(parents=True)
    (returned / "SUMMARY.md").write_text("## Q1\nresult", encoding="utf-8")
    (returned / "raw" / "Q1_summary.json").write_text("{}", encoding="utf-8")

    result = import_run(ready_project, "replication", "ReplicationModel", returned)
    assert result["count"] == 2
    run_dir = ready_project.path(result["run"])
    assert (run_dir / "SUMMARY.md").is_file()
    assert (run_dir / "raw" / "Q1_summary.json").is_file()


def test_import_run_from_zip(ready_project, tmp_path: Path):
    bundle = tmp_path / "returned.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("SUMMARY.md", "## Q1\nok")
        archive.writestr("raw/Q1_summary.json", "{}")

    result = import_run(ready_project, "robustness", "RobustnessModel", bundle)
    assert result["count"] == 2
    run_dir = ready_project.path(result["run"])
    assert (run_dir / "raw" / "Q1_summary.json").is_file()


def test_import_rejects_zip_slip(ready_project, tmp_path: Path):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as archive:
        archive.writestr("../../origin/STOLEN.md", "leak")
    with pytest.raises(RRGError, match="outside the run folder"):
        import_run(ready_project, "replication", "ReplicationModel", evil)


def test_gui_import_run(ready_project, tmp_path: Path):
    returned = tmp_path / "out"
    returned.mkdir()
    (returned / "SUMMARY.md").write_text("## Q1\nok", encoding="utf-8")
    result = GUIState(ready_project).import_run(
        {"stage": "replication", "model": "ReplicationModel", "source": str(returned)}
    )
    assert result["count"] == 1
    assert any(run["path"] == result["run"] and run["returned"] for run in GUIState(ready_project).runs())
