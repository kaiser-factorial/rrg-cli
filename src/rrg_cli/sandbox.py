"""OS-level confinement for validator processes (ADR 0001, enforced).

Validator isolation used to rest on convention: extract the package to a temp dir and
run the agent there. A real run showed an agent searching the whole home directory,
finding the project tree, reading other studies' protocols, and writing its output
into the published package directory. Convention is not isolation.

This module wraps a validator command so the operating system denies it the project
tree. On macOS it uses ``sandbox-exec`` with a deny-list profile: every file read or
write under the project root and the enclosing git checkout fails with "Operation not
permitted", for the agent and every child process it spawns. Everything else (the
agent's own config, its Python, the temp work dir) is untouched. Other platforms get no
wrapper yet; the project-tree write detector in ``dispatch`` still catches escapes there.

Configuration (``rrg.yaml``)::

    dispatch:
      sandbox: auto        # auto (default) | off
      sandbox_deny:        # extra absolute paths to deny, on top of the defaults
        - /Users/me/other-studies
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

SANDBOX_EXEC = "sandbox-exec"


def _git_toplevel(path: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    top = result.stdout.strip()
    return Path(top).resolve() if top else None


def deny_paths(project: Any, work_dir: str | Path | None = None) -> list[Path]:
    """Directories a validator must never read or write.

    Defaults to the project root and the git checkout that contains it (sibling studies
    live there too). ``dispatch.sandbox_deny`` adds more. A path that contains the work
    dir is dropped — the validator has to be able to work somewhere.
    """
    root = Path(project.root).resolve()
    candidates: list[Path] = [root]
    top = _git_toplevel(root)
    if top and top != root:
        candidates.append(top)
    extra = (project.config.get("dispatch", {}) or {}).get("sandbox_deny", []) or []
    for item in extra:
        try:
            candidates.append(Path(str(item)).expanduser().resolve())
        except OSError:
            continue
    work = Path(work_dir).resolve() if work_dir else None
    deny: list[Path] = []
    for path in candidates:
        if work is not None and (work == path or path in work.parents):
            continue
        if path not in deny:
            deny.append(path)
    # Keep only outermost paths: a parent already covers its children.
    return [p for p in deny if not any(q != p and q in p.parents for q in deny)]


def sandbox_mode(project: Any) -> str:
    mode = str((project.config.get("dispatch", {}) or {}).get("sandbox", "auto") or "auto").lower()
    return mode if mode in {"auto", "off"} else "auto"


def _quote(path: Path) -> str:
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_profile(deny: list[Path], writable_roots: list[Path] | None = None) -> str:
    """Build a profile that denies secrets and, when supplied, confines writes.

    ``writable_roots`` is an explicit allow-list.  The validator may read its installed
    runtime and configuration, but file writes outside these roots are denied.  Runtime
    state directories needed for session chaining are therefore visible in the returned
    sandbox record instead of being an implicit hole.
    """
    rules = "".join(f"(deny file-read* file-write* (subpath {_quote(path)}))" for path in deny)
    if writable_roots:
        allowed = "".join(f"(subpath {_quote(path)})" for path in writable_roots)
        rules += f"(deny file-write* (require-not (require-any {allowed})))"
    return f"(version 1)(allow default){rules}"


@lru_cache(maxsize=4)
def sandbox_exec_available(binary: str) -> bool:
    """A binary on PATH is not proof that this host permits applying a profile."""
    try:
        result = subprocess.run(
            [binary, "-p", "(version 1)(allow default)", "/usr/bin/true"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def writable_paths(project: Any, work_dir: str | Path, validator: str | None = None) -> list[Path]:
    """Explicit write roots for the analysis workspace and executor session state."""
    roots = [Path(work_dir).resolve(), Path("/dev")]
    runtime_names = {
        "hermes": ".hermes", "claude": ".claude", "codex": ".codex",
        "grok": ".grok", "pool": ".pool",
    }
    runtime = runtime_names.get(str(validator or "").lower())
    if runtime:
        roots.append(Path.home().joinpath(runtime).resolve())
    configured = (project.config.get("dispatch", {}) or {}).get("sandbox_write_allow", []) or []
    for item in configured:
        try:
            roots.append(Path(str(item)).expanduser().resolve())
        except OSError:
            continue
    return list(dict.fromkeys(roots))


def make_sandbox(
    project: Any, work_dir: str | Path | None = None, validator: str | None = None,
) -> dict[str, Any]:
    """Decide how (and whether) to confine validator commands for this dispatch.

    Returns ``{"mode": "sandbox-exec" | None, "prefix": [...], "deny": [...], "reason": str}``.
    ``prefix`` is prepended to the validator's argv.
    """
    deny = deny_paths(project, work_dir)
    writable = writable_paths(project, work_dir, validator) if work_dir is not None else []
    if sandbox_mode(project) == "off":
        return {"mode": None, "prefix": [], "deny": [str(p) for p in deny],
                "writable_roots": [str(p) for p in writable], "write_enforced": False,
                "reason": "disabled in rrg.yaml"}
    if sys.platform != "darwin":
        return {"mode": None, "prefix": [], "deny": [str(p) for p in deny],
                "writable_roots": [str(p) for p in writable], "write_enforced": False,
                "reason": f"no sandbox backend for {sys.platform}; relying on write detection"}
    binary = shutil.which(SANDBOX_EXEC)
    if not binary:
        return {"mode": None, "prefix": [], "deny": [str(p) for p in deny],
                "writable_roots": [str(p) for p in writable], "write_enforced": False,
                "reason": "sandbox-exec not found; relying on write detection"}
    if not sandbox_exec_available(binary):
        return {"mode": None, "prefix": [], "deny": [str(p) for p in deny],
                "writable_roots": [str(p) for p in writable], "write_enforced": False,
                "reason": "sandbox-exec cannot apply profiles; relying on write detection"}
    return {
        "mode": "sandbox-exec",
        "prefix": [binary, "-p", build_profile(deny, writable)],
        "deny": [str(p) for p in deny],
        "writable_roots": [str(p) for p in writable],
        "write_enforced": True,
        "reason": "",
    }


def wrap(prefix: list[str], cmd: list[str]) -> list[str]:
    return [*prefix, *cmd] if prefix else list(cmd)
