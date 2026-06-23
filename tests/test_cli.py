import json
from pathlib import Path

from rrg_cli.cli import main


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
