import json
from pathlib import Path

import pytest

from rrg_cli.blinding import lint_package
from rrg_cli.errors import RRGError
from rrg_cli.packager import build_package


def test_replication_and_robustness_route_different_methodology(ready_project):
    replication = build_package(ready_project, "replication", "ReplicationModel")
    robustness = build_package(ready_project, "robustness", "RobustnessModel")
    replication_dir = Path(replication["package_dir"])
    robustness_dir = Path(robustness["package_dir"])
    assert replication["published"] and robustness["published"]
    assert (replication_dir / "ANALYSIS_PROTOCOL_OG.md").is_file()
    assert not (robustness_dir / "ANALYSIS_PROTOCOL_OG.md").exists()
    assert (replication_dir / "_provenance.json").is_file()
    provenance = json.loads((replication_dir / "_provenance.json").read_text())
    assert provenance["stage"] == "replication"
    assert provenance["forced_override"] is False
    assert Path(replication["output_folder"]).is_dir()


def test_dry_run_writes_nothing(ready_project):
    result = build_package(ready_project, "replication", "ReplicationModel", dry_run=True)
    assert not result["published"]
    assert not Path(result["package_dir"]).exists()


def test_linter_blocks_unexpected_scorecard(ready_project, tmp_path: Path):
    result = build_package(ready_project, "robustness", "RobustnessModel")
    package = Path(result["package_dir"])
    package.chmod(0o755)  # published packages are read-only; simulate tampering
    (package / "SCORECARD_leak.md").write_text("held-back result .44")
    report = lint_package(package, "robustness", ready_project)
    assert not report.passed
    assert {finding.check for finding in report.hard_fails} >= {"withheld_files", "routing"}


def test_result_token_scan_can_ignore_declared_shared_constants(ready_project):
    (ready_project.root / "operator/origin/SUMMARY.md").write_text(
        "Held-back result .44 using fixed alpha 0.005."
    )
    overview = ready_project.root / "shared/STUDY_OVERVIEW.md"
    overview.write_text(overview.read_text() + "\nFixed alpha 0.005; suspicious value .44.\n")
    ready_project.config["blinding"]["result_token_scan"]["ignore_tokens"] = ["0.005"]

    result = build_package(ready_project, "replication", "ReplicationModel")
    token_flags = [item for item in result["lint"]["flags"] if item["check"] == "result_token_scan"]

    assert len(token_flags) == 1
    assert any(".44" in item for item in token_flags[0]["items"])
    assert all("0.005" not in item for item in token_flags[0]["items"])


def test_origin_vendor_and_disabled_stage_are_refused(ready_project):
    with pytest.raises(RRGError, match="not in"):
        build_package(ready_project, "replication", "UnknownModel")
    with pytest.raises(RRGError, match="not buildable"):
        build_package(ready_project, "generalization", "AnyModel", allow_unlisted=True)
