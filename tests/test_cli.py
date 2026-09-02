import json
from pathlib import Path

from rrg_cli.cli import build_parser, main


def test_help_is_workflow_oriented_and_exposes_human_aliases():
    help_text = build_parser().format_help()
    assert "Typical workflow" in help_text
    assert "validate" in help_text and "review" in help_text
    dispatch_help = build_parser()._subparsers._group_actions[0].choices["dispatch"].format_help()
    assert "--project" in dispatch_help
    assert "--gate-revisions" in dispatch_help


def test_workspace_command_and_project_alias_are_machine_readable(tmp_path: Path, capsys):
    project = tmp_path / "workspace" / "study"
    assert main(["init", str(project), "--json"]) == 0
    capsys.readouterr()
    assert main(["workspace", str(tmp_path / "workspace"), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["projects"][0]["root"] == "study"
    assert main(["status", "--project", str(project), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["project"] == "starter-validation"
    assert main(["paths", "--project", str(project), "--json"]) == 0
    paths = json.loads(capsys.readouterr().out)["paths"]
    assert paths["runs"] == "operator/runs"
    assert paths["packages"] == "operator/packages"


def test_import_exits_nonzero_when_deterministic_gates_fail(tmp_path: Path, capsys):
    root = tmp_path / "project"
    returned = tmp_path / "returned"
    assert main(["init", str(root), "--json"]) == 0
    capsys.readouterr()
    returned.mkdir()
    (returned / "SUMMARY.md").write_text("incomplete")
    code = main([
        "import", "--project", str(root), str(returned),
        "--stage", "replication", "--model", "ReplicationModel", "--json",
    ])
    assert code == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["gates"]["passed"] is False


def test_cli_end_to_end(tmp_path: Path, capsys):
    root = tmp_path / "cli-project"
    assert main(["init", str(root), "--json"]) == 0
    capsys.readouterr()
    assert main(["convert", "--root", str(root), "--json"]) == 0
    conversion = json.loads(capsys.readouterr().out)
    assert conversion["all_verified"]
    assert main(["preflight", "--root", str(root), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"]
    assert main([
        "package", "--root", str(root), "--stage", "replication",
        "--model", "ReplicationModel", "--json",
    ]) == 0
    package = json.loads(capsys.readouterr().out)
    assert package["published"]
    assert main([
        "prompt", "--root", str(root), "--stage", "robustness",
        "--model", "RobustnessModel", "--turn", "1",
    ]) == 0
    assert "original method" in capsys.readouterr().out.lower()


def test_cli_dispatch_forwards_validator_option(tmp_path: Path, capsys):
    root = tmp_path / "dispatch-project"
    assert main(["init", str(root), "--json"]) == 0
    capsys.readouterr()
    assert main(["convert", "--root", str(root), "--json"]) == 0
    capsys.readouterr()

    assert main([
        "dispatch", "--root", str(root), "--stage", "replication",
        "--model", "ReplicationModel", "--validator", "manual",
        "--dry-run", "--json",
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["validator"] == "manual"
    assert result["package"]["dry_run"] is True


def test_cli_runs_registry_and_archive_round_trip(tmp_path: Path, capsys):
    root = tmp_path / "p"
    assert main(["init", str(root), "--json"]) == 0
    capsys.readouterr()
    assert main(["convert", "--root", str(root), "--json"]) == 0
    capsys.readouterr()

    assert main([
        "package", "--root", str(root), "--stage", "replication",
        "--model", "ReplicationModel", "--json",
    ]) == 0
    run_id = json.loads(capsys.readouterr().out)["run_id"]

    # The freshly built run shows up in the registry as pending.
    assert main(["runs", "--root", str(root), "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)["runs"]
    row = next(item for item in rows if item["run_id"] == run_id)
    assert row["stage"] == "replication" and row["returned"] is False and row["flagged"] is False

    # Archive → list → restore via the CLI verbs.
    assert main(["archive", "--root", str(root), "shared/QUESTIONS.md", "--json"]) == 0
    item_id = json.loads(capsys.readouterr().out)["id"]
    assert not (root / "shared/QUESTIONS.md").exists()

    assert main(["archive-ls", "--root", str(root), "--json"]) == 0
    assert any(item["id"] == item_id for item in json.loads(capsys.readouterr().out)["items"])

    assert main(["restore", "--root", str(root), item_id, "--json"]) == 0
    capsys.readouterr()
    assert (root / "shared/QUESTIONS.md").exists()
