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
