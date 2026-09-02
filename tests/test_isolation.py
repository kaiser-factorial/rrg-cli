"""Enforced validator isolation: OS sandbox, working-directory inventory, project-tree
write detection with quarantine, read-only published packages, and real Hermes chaining."""

from __future__ import annotations

import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from rrg_cli import grading
from rrg_cli.dispatch import _exec_hermes_turn, _parse_hermes_output, dispatch
from rrg_cli.errors import RRGError
from rrg_cli.packager import build_package
from rrg_cli.layout import packages_root
from rrg_cli.project import Project
from rrg_cli.sandbox import build_profile, deny_paths, make_sandbox, sandbox_exec_available, wrap

_SANDBOX_BINARY = shutil.which("sandbox-exec")
HAS_SANDBOX = bool(sys.platform == "darwin" and _SANDBOX_BINARY and sandbox_exec_available(_SANDBOX_BINARY))


# --- sandbox -------------------------------------------------------------------

def test_deny_paths_cover_project_and_extras_but_never_the_work_dir(ready_project: Project, tmp_path: Path) -> None:
    extra = tmp_path / "other-studies"
    extra.mkdir()
    ready_project.config.setdefault("dispatch", {})["sandbox_deny"] = [str(extra)]
    work = tmp_path / "work"
    work.mkdir()
    deny = deny_paths(ready_project, work)
    assert ready_project.root.resolve() in deny and extra.resolve() in deny
    # A deny path that contains the work dir is dropped: the validator must be able to work.
    assert deny_paths(ready_project, ready_project.root / "inside") == [extra.resolve()]


def test_profile_quotes_paths() -> None:
    profile = build_profile([Path('/tmp/has "quote"')])
    assert profile.startswith("(version 1)(allow default)")
    assert '(subpath "/tmp/has \\"quote\\"")' in profile


def test_profile_has_an_explicit_write_allowlist() -> None:
    profile = build_profile([Path("/secret")], [Path("/work"), Path("/dev")])
    assert "(deny file-write* (require-not (require-any" in profile
    assert '(subpath "/work")' in profile and '(subpath "/dev")' in profile


def test_make_sandbox_off_via_config(ready_project: Project, tmp_path: Path) -> None:
    ready_project.config.setdefault("dispatch", {})["sandbox"] = "off"
    box = make_sandbox(ready_project, tmp_path)
    assert box["mode"] is None and box["prefix"] == [] and "disabled" in box["reason"]
    assert wrap(box["prefix"], ["echo", "x"]) == ["echo", "x"]


@pytest.mark.skipif(not HAS_SANDBOX, reason="sandbox-exec only on macOS")
def test_sandbox_exec_denies_project_tree_but_allows_work_dir(ready_project: Project, tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    box = make_sandbox(ready_project, work)
    assert box["mode"] == "sandbox-exec" and box["write_enforced"] is True
    secret = ready_project.path("operator/origin/SUMMARY.md")
    assert secret.is_file()
    script = (
        f"cat {secret} >/dev/null 2>&1 && echo READ_OK || echo READ_DENIED; "
        f"touch {ready_project.root}/escaped.txt 2>/dev/null && echo WRITE_OK || echo WRITE_DENIED; "
        f"touch {outside}/escaped.txt 2>/dev/null && echo OUTSIDE_OK || echo OUTSIDE_DENIED; "
        f"touch {work}/fine.txt && echo WORK_OK"
    )
    result = subprocess.run(wrap(box["prefix"], ["/bin/sh", "-c", script]), capture_output=True, text=True, timeout=30)
    assert result.stdout.split() == ["READ_DENIED", "WRITE_DENIED", "OUTSIDE_DENIED", "WORK_OK"], result
    assert not (ready_project.root / "escaped.txt").exists()
    assert not (outside / "escaped.txt").exists()


# --- hermes: real session chaining ------------------------------------------------

def test_parse_hermes_output_strips_noise_and_reads_session_id() -> None:
    text, sid = _parse_hermes_output(
        "Warning: Unknown toolsets: a2a, bfl\npineapple\n", "↻ Resumed session x\nsession_id: 20260902_010246_931f3b\n", None,
    )
    assert text == "pineapple" and sid == "20260902_010246_931f3b"
    text, sid = _parse_hermes_output("hi", "", "keep-me")
    assert text == "hi" and sid == "keep-me"


def test_hermes_turn_uses_chat_quiet_with_pinned_cwd_and_resume(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, work_dir, timeout=900):
        calls.append(cmd)
        query = Path(cmd[cmd.index("--query-file") + 1]).read_text(encoding="utf-8")
        assert query == "the prompt $(not shell) `verbatim`"
        return subprocess.CompletedProcess(cmd, 0, stdout="reply\n", stderr="session_id: s-2\n")

    with patch("rrg_cli.dispatch._run", side_effect=fake_run):
        response, sid, model = _exec_hermes_turn("the prompt $(not shell) `verbatim`", "vendor/model", str(tmp_path), "s-1")
    assert (response, sid, model) == ("reply", "s-2", "vendor/model")
    cmd = calls[0]
    assert cmd[:3] == ["hermes", "chat", "-Q"]
    assert "-z" not in cmd
    assert cmd[cmd.index("--in") + 1] == str(tmp_path)
    assert cmd[cmd.index("--resume") + 1] == "s-1"
    assert "--no-restore-cwd" in cmd and "--run-budget" in cmd
    assert not Path(cmd[cmd.index("--query-file") + 1]).exists()  # temp query file cleaned up


# --- inventory preamble ------------------------------------------------------------

def test_first_turn_carries_working_directory_and_inventory(ready_project: Project) -> None:
    prompts: list[str] = []

    def side_effect(prompt, slug, work_dir, session_id=None):
        prompts.append(prompt)
        return ("Done.", "s1", "m")

    with patch("rrg_cli.dispatch._exec_hermes_turn", side_effect=side_effect):
        result = dispatch(ready_project, "replication", "ReplicationModel",
                          validator="hermes", mode="nodiscuss", gates=False, auto_import=False)
    first, second = prompts[0], prompts[1]
    assert first.startswith("## Working directory")
    assert "rrg_dispatch_" in first and "Files present:" in first
    assert "- `STUDY_OVERVIEW.md`" in first
    assert "Do not search, read, or write anywhere outside" in first
    assert not second.startswith("## Working directory")
    assert result["conversation"][0]["prompt"] == first
    assert result["sandbox"] is not None and result["escapes"]["count"] == 0


# --- write detection + quarantine -------------------------------------------------------

def _package_dir(project: Project) -> Path:
    dirs = [p for p in (packages_root(project) / "replication").iterdir() if p.is_dir()]
    return sorted(dirs, key=lambda p: p.stat().st_mtime)[-1]


def test_escape_is_detected_quarantined_and_blocks_grading(ready_project: Project) -> None:
    def side_effect(prompt, slug, work_dir, session_id=None):
        (Path(work_dir) / "SUMMARY.md").write_text("## Q1\nok")
        if "Execute" in prompt or "Verify" in prompt:
            return ("Done.", "s1", "m")
        # An agent that wandered into the project: a stray note at the root and a
        # deliverable dropped into the published package (after undoing read-only).
        (ready_project.root / "stray_note.txt").write_text("hi")
        pkg = _package_dir(ready_project)
        pkg.chmod(0o755)
        (pkg / "Q1_fig.png").write_bytes(b"\x89PNG")
        return ("Done.", "s1", "m")

    ready_project.config.setdefault("dispatch", {})["sandbox"] = "off"
    with patch("rrg_cli.dispatch._exec_hermes_turn", side_effect=side_effect):
        result = dispatch(ready_project, "replication", "ReplicationModel",
                          validator="hermes", mode="nodiscuss", gates=False)
    escapes = result["escapes"]
    paths = {r["path"]: r for r in escapes["records"]}
    assert "stray_note.txt" in paths and paths["stray_note.txt"]["change"] == "new"
    pkg_hit = next(r for r in escapes["records"] if r["path"].endswith("Q1_fig.png"))
    assert pkg_hit["quarantined_to"] == "Q1_fig.png"
    assert not (_package_dir(ready_project) / "Q1_fig.png").exists()      # package pristine again
    run_dir = Path(result["import_result"]["output_folder"])
    assert (run_dir / "Q1_fig.png").is_file()                            # deliverable still imported
    breach = grading.load_breach(ready_project, result["import_result"]["run"])
    assert breach["blocking"] and len(breach["wrote_inside_project"]) == 2
    with pytest.raises(RRGError, match="wrote 2 file"):
        grading.save_verdict(ready_project, result["import_result"]["run"], 1, "REPRODUCED", "", True)
    assert "Wrote inside project**: 2 file(s) (BREACH" in (run_dir / "RUN_INFO.md").read_text()


def test_detect_escapes_scopes_project_vs_checkout(tmp_path: Path) -> None:
    """Only changes under the project are breaches; the rest of the checkout is a note.
    (The ready_project fixture has no enclosing checkout, so this is exercised directly.)"""
    from rrg_cli.dispatch import _detect_escapes, _snapshot_tree
    checkout = tmp_path / "checkout"
    project = checkout / "workspace" / "study"
    pkg = project / "operator" / "_packages" / "replication" / "M__abc"
    pkg.mkdir(parents=True)
    (checkout / "src").mkdir()
    (checkout / "src" / "extract.py").write_text("v1")
    (pkg / "_provenance.json").write_text("{}")
    collected = tmp_path / "collected"
    collected.mkdir()
    before = _snapshot_tree(checkout)
    (checkout / "src" / "extract.py").write_text("v2 — operator editing source mid-run")
    (checkout / "workspace" / "other_study.txt").write_text("sibling study")
    (pkg / "Q1_fig.png").write_bytes(b"\x89PNG")
    (project / "stray.txt").write_text("x")
    escapes = _detect_escapes(checkout, before, _snapshot_tree(checkout), str(pkg), collected, project_root=project)
    assert escapes["count"] == 4
    breaches = {r["path"]: r for r in escapes["breaches"]}
    notes = {r["path"] for r in escapes["notes"]}
    assert set(breaches) == {"workspace/study/stray.txt", "workspace/study/operator/_packages/replication/M__abc/Q1_fig.png"}
    assert notes == {"src/extract.py", "workspace/other_study.txt"}
    assert breaches["workspace/study/operator/_packages/replication/M__abc/Q1_fig.png"]["quarantined_to"] == "Q1_fig.png"
    assert (collected / "Q1_fig.png").exists() and not (pkg / "Q1_fig.png").exists()


def test_gate_python_skips_interpreters_inside_deny_list(tmp_path: Path) -> None:
    from rrg_cli.gates import resolve_gate_python
    denied_root = Path(sys.executable).resolve().parents[2]
    python, note = resolve_gate_python(tmp_path, preferred=sys.executable, deny=[str(denied_root)])
    assert python is None or Path(python).resolve() != Path(sys.executable).resolve()
    assert "skipped (inside sandbox deny list)" in note or python is not None


def test_clean_dispatch_records_no_escape(ready_project: Project) -> None:
    def side_effect(prompt, slug, work_dir, session_id=None):
        (Path(work_dir) / "SUMMARY.md").write_text("## Q1\nok")
        return ("Done.", "s1", "m")

    ready_project.config.setdefault("dispatch", {})["sandbox"] = "off"
    with patch("rrg_cli.dispatch._exec_hermes_turn", side_effect=side_effect):
        result = dispatch(ready_project, "replication", "ReplicationModel",
                          validator="hermes", mode="nodiscuss", gates=False)
    assert result["escapes"]["count"] == 0
    assert grading.load_breach(ready_project, result["import_result"]["run"]) is None


# --- read-only published packages ---------------------------------------------------------

def test_published_package_is_read_only(ready_project: Project) -> None:
    built = build_package(ready_project, "replication", "ReplicationModel")
    pkg = Path(built["package_dir"])
    assert not (pkg.stat().st_mode & stat.S_IWUSR)
    for path in pkg.rglob("*"):
        assert not (path.stat().st_mode & stat.S_IWUSR), path
    assert not (Path(built["package_zip"]).stat().st_mode & stat.S_IWUSR)
    with pytest.raises(PermissionError):
        (pkg / "late_output.txt").write_text("x")
    # Provenance log stays appendable and a second build still works alongside.
    second = build_package(ready_project, "replication", "ReplicationModel")
    assert second["run_id"] != built["run_id"]


def test_read_only_package_can_still_be_archived_and_purged(ready_project: Project) -> None:
    from rrg_cli import archive as archive_module
    built = build_package(ready_project, "replication", "ReplicationModel")
    pkg = Path(built["package_dir"])
    record = archive_module.archive_item(ready_project, str(pkg.relative_to(ready_project.root)))
    assert not pkg.exists()
    purged = archive_module.purge_item(ready_project, record["id"])
    assert purged["id"] == record["id"]
    assert not (ready_project.root / record["stored"]).exists()


def test_import_exec_gates_default_off(ready_project: Project, tmp_path: Path) -> None:
    from rrg_cli.importer import import_run
    returned = tmp_path / "returned"
    returned.mkdir()
    (returned / "SUMMARY.md").write_text("## Q1\nok")
    result = import_run(ready_project, "replication", "ReplicationModel", returned)
    assert result["gates"]["final"]["exec"] == {}
