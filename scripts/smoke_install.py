"""Exercise the installed wheel without importing from the source tree."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-m", "rrg_cli", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"rrg {' '.join(args)} failed with exit {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def read_json(result: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(result.stdout)


def main() -> None:
    import rrg_cli

    module_path = Path(rrg_cli.__file__).resolve()
    repository = Path(__file__).resolve().parents[1]
    source_tree = repository / "src"
    if module_path.is_relative_to(source_tree):
        raise RuntimeError(f"smoke test imported the source tree: {module_path}")

    with tempfile.TemporaryDirectory(prefix="rrg-clean-install-") as temp:
        workspace = Path(temp)
        project = workspace / "demo"

        version = run("version", cwd=workspace).stdout.strip()
        if version != rrg_cli.__version__:
            raise RuntimeError(f"version mismatch: CLI={version!r}, package={rrg_cli.__version__!r}")

        initialized = read_json(run("init", str(project), "--json", cwd=workspace))
        if Path(initialized["root"]).resolve() != project.resolve():
            raise RuntimeError("init reported the wrong project root")

        converted = read_json(run("convert", "--root", str(project), "--json", cwd=workspace))
        if not converted["all_verified"]:
            raise RuntimeError("generated data derivatives did not verify")

        preflight = read_json(run("preflight", "--root", str(project), "--json", cwd=workspace))
        if not preflight["ok"]:
            raise RuntimeError("starter project did not pass preflight")

        packaged = read_json(
            run(
                "package",
                "--root",
                str(project),
                "--stage",
                "replication",
                "--model",
                "ReplicationModel",
                "--json",
                cwd=workspace,
            )
        )
        if not packaged["published"] or packaged["blocked"]:
            raise RuntimeError("starter replication package was not published")

        prompt = run(
            "prompt",
            "--root",
            str(project),
            "--stage",
            "robustness",
            "--model",
            "RobustnessModel",
            "--turn",
            "1",
            cwd=workspace,
        ).stdout
        if "original method" not in prompt.lower():
            raise RuntimeError("installed package did not render the expected prompt")

        print(f"clean-install smoke test passed: {module_path}")


if __name__ == "__main__":
    main()
