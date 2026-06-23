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
