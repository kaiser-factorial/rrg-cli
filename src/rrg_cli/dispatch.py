"""Validator dispatch: build → prompt → run validator → collect → import → normalize.

Validators supported:
  - manual:    prints instructions for external execution
  - hermes:    shells out to `hermes -z` (OpenRouter via Hermes agent CLI)
  - claude:    shells out to `claude -p` (Claude Code CLI)
  - codex:     shells out to `codex exec` (Codex CLI)
  - grok:      shells out to `grok -p --single` (Grok CLI)
  - openrouter: calls the OpenRouter API directly (httpx)
  - prime-agent: spawns a subagent (requires async IPython context)

Multi-turn support: each validator tracks a session ID so turns share conversation
context. Session IDs are captured from the validator's session management after
the first turn and passed to --resume/--continue for subsequent turns.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .errors import RRGError
from .importer import import_run
from .packager import build_package
from .prefs import load_prefs
from .project import Project
from .prompts import render_prompt
from .utils import safe_label

# ---------------------------------------------------------------------------
# Slug resolution
# ---------------------------------------------------------------------------

def _resolve_slug(project: Project, model: str) -> str:
    """Resolve a model name to its dispatch slug from rrg.yaml > dispatch.model_slugs.

    Returns empty string for "default" or empty model — the validator will use
    its own configured default model.
    """
    if not model or model.lower() == "default":
        return ""
    slugs = project.config.get("dispatch", {}).get("model_slugs", {}) or {}
    if model in slugs:
        return str(slugs[model])
    for key, slug in slugs.items():
        if model.lower() in key.lower() or key.lower() in model.lower():
            return str(slug)
    return safe_label(model)


# ---------------------------------------------------------------------------
# Session ID extraction (per validator)
# ---------------------------------------------------------------------------

def _extract_hermes_session_id(output: str, work_dir: str) -> str | None:
    """Extract the session ID from `hermes sessions list` after a -z call."""
    try:
        result = subprocess.run(
            ["hermes", "sessions", "list"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
        # Parse the table — the first non-header row is the most recent session
        lines = result.stdout.strip().split("\n")
        for line in lines:
            # Skip header and separator lines
            if line.startswith("Title") or line.startswith("─") or not line.strip():
                continue
            # The ID is the last column
            parts = line.split()
            if parts:
                session_id = parts[-1]
                # Validate it looks like a session ID
                if re.match(r"\d{8}_\d{6}_[a-f0-9]+", session_id):
                    return session_id
        return None
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


def _extract_codex_session_id(output: str) -> str | None:
    """Extract session ID from codex exec --json output (JSONL)."""
    for line in output.strip().split("\n"):
        try:
            event = json.loads(line)
            if "session_id" in event:
                return event["session_id"]
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def _extract_claude_session_id(output: str) -> str | None:
    """Extract session ID from claude -p --output-format json output."""
    try:
        data = json.loads(output)
        if "session_id" in data:
            return data["session_id"]
    except (json.JSONDecodeError, TypeError):
        pass
    return None


# ---------------------------------------------------------------------------
# Validator call functions
# ---------------------------------------------------------------------------

def _call_openrouter(
    prompt: str, slug: str, messages: list[dict[str, str]] | None = None,
) -> str:
    """Call the OpenRouter chat completions API directly."""
    import httpx
    if not slug:
        raise RRGError("openrouter validator requires a model slug; set one in rrg.yaml > dispatch.model_slugs or use a different executor")
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RRGError("OPENROUTER_API_KEY not set in environment")
    payload_messages = messages or [{"role": "user", "content": prompt}]
    payload = {"model": slug, "messages": payload_messages, "temperature": 0}
    try:
        response = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload, timeout=300,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except httpx.HTTPError as exc:
        raise RRGError(f"OpenRouter API error: {exc}")


def _exec_hermes_turn(
    prompt: str, slug: str, work_dir: str, session_id: str | None = None,
) -> tuple[str, str | None, str | None]:
    """Send one turn to hermes -z. Returns (response, session_id, model)."""
    cmd = ["hermes", "-z", prompt]
    if slug:
        cmd.extend(["-m", slug, "--provider", "openrouter"])
    if session_id:
        cmd.extend(["--resume", session_id])
    # Use --usage-file to capture session_id + model
    usage_file = os.path.join(work_dir, ".rrg_hermes_usage.json")
    cmd.extend(["--usage-file", usage_file])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=work_dir, timeout=900)
        if result.returncode != 0:
            return f"[hermes error: exit {result.returncode}]\n{result.stderr}", session_id, None
        # Parse usage file for session_id and model
        new_sid = session_id
        model = None
        try:
            usage = json.loads(Path(usage_file).read_text())
            new_sid = usage.get("session_id", session_id)
            model = usage.get("model")
        except (json.JSONDecodeError, OSError):
            pass
        return result.stdout, new_sid, model
    except FileNotFoundError:
        raise RRGError("hermes CLI not found; install it or use --validator manual")
    except subprocess.TimeoutExpired:
        raise RRGError("hermes timed out after 900 seconds")


def _exec_claude_turn(
    prompt: str, work_dir: str, session_id: str | None = None,
) -> tuple[str, str | None, str | None]:
    """Send one turn to claude -p. Returns (response, session_id, model)."""
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--dangerously-skip-permissions"]
    if session_id:
        cmd.extend(["--resume", session_id])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=work_dir, timeout=900)
        if result.returncode != 0:
            return f"[claude error: exit {result.returncode}]\n{result.stderr}", session_id, None
        # Parse JSON output for session_id and model
        new_sid = session_id
        model = None
        try:
            data = json.loads(result.stdout)
            new_sid = data.get("session_id", session_id)
            model_usage = data.get("modelUsage", {})
            if model_usage:
                model = next(iter(model_usage.keys()))
            # Extract the result text
            text = data.get("result", result.stdout)
            return text, new_sid, model
        except (json.JSONDecodeError, TypeError):
            pass
        return result.stdout, new_sid, model
    except FileNotFoundError:
        raise RRGError("claude CLI not found; install it or use --validator manual")
    except subprocess.TimeoutExpired:
        raise RRGError("claude timed out after 900 seconds")


def _exec_codex_turn(
    prompt: str, work_dir: str, session_id: str | None = None,
) -> tuple[str, str | None, str | None]:
    """Send one turn to codex exec. Returns (response, session_id, model)."""
    if session_id:
        cmd = ["codex", "exec", "resume", session_id, "--json", "--skip-git-repo-check", prompt]
    else:
        cmd = ["codex", "exec", "--json", "--skip-git-repo-check", prompt]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=work_dir, timeout=900)
        if result.returncode != 0:
            return f"[codex error: exit {result.returncode}]\n{result.stderr}", session_id, None
        # Parse JSONL for session_id and model
        new_sid = session_id
        model = None
        text_parts = []
        for line in result.stdout.strip().split("\n"):
            try:
                event = json.loads(line)
                if "session_id" in event and not new_sid:
                    new_sid = event["session_id"]
                if "model" in event and not model:
                    model = event["model"]
                if "text" in event:
                    text_parts.append(event["text"])
                elif "content" in event:
                    text_parts.append(str(event["content"]))
            except (json.JSONDecodeError, TypeError):
                text_parts.append(line)
        text = "\n".join(text_parts) if text_parts else result.stdout
        return text, new_sid, model
    except FileNotFoundError:
        raise RRGError("codex CLI not found; install it or use --validator manual")
    except subprocess.TimeoutExpired:
        raise RRGError("codex timed out after 900 seconds")


def _exec_grok_turn(
    prompt: str, work_dir: str, session_id: str | None = None,
) -> tuple[str, str | None, str | None]:
    """Send one turn to grok --single. Returns (response, session_id, model)."""
    cmd = ["grok", "--single", prompt, "--output-format", "json",
           "--no-auto-update", "--always-approve"]
    if session_id:
        cmd.extend(["--resume", session_id])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=work_dir, timeout=900)
        if result.returncode != 0:
            return f"[grok error: exit {result.returncode}]\n{result.stderr}", session_id, None
        # Parse JSON output for session_id and model
        new_sid = session_id
        model = None
        try:
            data = json.loads(result.stdout)
            new_sid = data.get("sessionId", session_id)
            model_usage = data.get("modelUsage", {})
            if model_usage:
                model = next(iter(model_usage.keys()))
            text = data.get("text", result.stdout)
            return text, new_sid, model
        except (json.JSONDecodeError, TypeError):
            pass
        return result.stdout, new_sid, model
    except FileNotFoundError:
        raise RRGError("grok CLI not found; install it or use --validator manual")
    except subprocess.TimeoutExpired:
        raise RRGError("grok timed out after 900 seconds")


def _exec_pool_turn(
    prompt: str, work_dir: str, session_id: str | None = None,
) -> tuple[str, str | None, str | None]:
    """Send one turn to pool exec. Returns (response, session_id, model)."""
    cmd = ["pool", "exec", "-p", prompt, "--unsafe-auto-allow",
           "--sandbox", "disabled", "-d", work_dir, "-o", "json"]
    if session_id:
        cmd.extend(["--continue", session_id])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=work_dir, timeout=900)
        if result.returncode not in (0, 4):
            return f"[pool error: exit {result.returncode}]\n{result.stderr}", session_id, None
        # Parse NLJSON for session/run ID and model
        new_sid = session_id
        model = None
        text_parts = []
        for line in result.stdout.strip().split("\n"):
            try:
                event = json.loads(line)
                if "run_id" in event and not new_sid:
                    new_sid = event["run_id"]
                if "session_id" in event and not new_sid:
                    new_sid = event["session_id"]
                if "model" in event and not model:
                    model = event["model"]
                if "text" in event:
                    text_parts.append(event["text"])
                elif "content" in event:
                    text_parts.append(str(event["content"]))
            except (json.JSONDecodeError, TypeError):
                text_parts.append(line)
        text = "\n".join(text_parts) if text_parts else result.stdout
        return text, new_sid, model
    except FileNotFoundError:
        raise RRGError("pool CLI not found; install it or use --validator manual")
    except subprocess.TimeoutExpired:
        raise RRGError("pool timed out after 900 seconds")

# ---------------------------------------------------------------------------
# Agent-mode operator response generator
# ---------------------------------------------------------------------------

def _generate_operator_response(turn_title: str, validator_response: str, turn_num: int) -> str:
    """Generate a simple operator response for agent-mode discuss turns."""
    title_lower = turn_title.lower()
    if "propose" in title_lower:
        return ("I've reviewed your proposed methods. They look defensible. "
                "Please proceed to lock your approach.")
    if "discuss" in title_lower:
        return ("Your reasoning is sound. I don't have objections to the methods "
                "you've proposed. Please finalize your approach.")
    if "lock" in title_lower:
        return "Approach confirmed. You may proceed to execution."
    return "Proceed to the next step."


# ---------------------------------------------------------------------------
# Validator dispatch table
# ---------------------------------------------------------------------------

VALIDATORS = {
    "manual": None,
    "hermes": _exec_hermes_turn,
    "claude": _exec_claude_turn,
    "codex": _exec_codex_turn,
    "grok": _exec_grok_turn,
    "pool": _exec_pool_turn,
}

# Validators that support session-based multi-turn
MULTI_TURN_VALIDATORS = {"hermes", "claude", "codex", "grok", "pool"}

# Validators that need a slug (model identifier) from rrg.yaml
SLUG_VALIDATORS = {"hermes", "openrouter"}

# Validators where the model flag is optional (use agent's default)
OPTIONAL_MODEL_VALIDATORS = {"hermes", "codex", "grok", "claude", "pool"}




def _run_validator(
    validator: str,
    rendered: Any,
    slug: str,
    work_dir: str,
    mode: str,
) -> list[dict[str, Any]]:
    """Run the multi-turn validator loop. Returns conversation history."""
    conversation: list[dict[str, Any]] = []
    session_id: str | None = None
    messages: list[dict[str, str]] = []  # for openrouter conversation accumulation

    detected_model: str | None = None
    for i, turn in enumerate(rendered.turns, 1):
        if validator == "openrouter":
            messages.append({"role": "user", "content": turn.text})
            response = _call_openrouter(turn.text, slug, messages)
            messages.append({"role": "assistant", "content": response})
            detected_model = slug
        else:
            # Look up the validator function by name so mocks can patch it
            import sys
            exec_fn = getattr(sys.modules[__name__], f"_exec_{validator}_turn", None)
            if exec_fn is None:
                raise RRGError(f"validator not implemented: {validator}")

            if validator in SLUG_VALIDATORS:
                response, session_id, model = exec_fn(turn.text, slug, work_dir, session_id)
            else:
                response, session_id, model = exec_fn(turn.text, work_dir, session_id)
            if model and not detected_model:
                detected_model = model

        conversation.append({
            "turn": i,
            "title": turn.title,
            "prompt": turn.text,
            "response": response,
            "session_id": session_id,
            "model": model if validator != "openrouter" else slug,
        })

        # Agent mode: generate operator responses for discuss turns
        if mode == "agent" and "discuss" in turn.title.lower():
            op_response = _generate_operator_response(turn.title, response, i)
            if validator == "openrouter":
                messages.append({"role": "user", "content": op_response})
                op_reply = _call_openrouter(op_response, slug, messages)
                messages.append({"role": "assistant", "content": op_reply})
            else:
                import sys as _sys
                _exec_fn = getattr(_sys.modules[__name__], f"_exec_{validator}_turn", None)
                if validator in SLUG_VALIDATORS:
                    op_reply, session_id, _ = _exec_fn(op_response, slug, work_dir, session_id)
                else:
                    op_reply, session_id, _ = _exec_fn(op_response, work_dir, session_id)
            conversation.append({
                "turn": i,
                "title": "Operator response (agent)",
                "prompt": op_response,
                "response": op_reply,
                "session_id": session_id,
                "model": detected_model,
            })

    # For openrouter, write the final response to the work dir as a file
    if validator == "openrouter" and conversation:
        final = conversation[-1]["response"]
        (Path(work_dir) / "SUMMARY.md").write_text(final, encoding="utf-8")

    return conversation


# ---------------------------------------------------------------------------
# Model provenance extraction (fallback when JSON output doesn't include model)
# ---------------------------------------------------------------------------

def _get_model_provenance(validator: str, slug: str) -> str:
    """Best-effort extraction of the model name used by a validator.

    For validators that don't take a model flag or whose JSON output didn't
    include the model, this reads the agent's config to find the default model.
    """
    if validator == "hermes" and slug:
        return slug
    if validator == "openrouter" and slug:
        return slug

    import os
    home = os.path.expanduser("~")

    if validator == "hermes":
        try:
            result = subprocess.run(
                ["hermes", "status"], capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.split("\n"):
                if "Model:" in line:
                    return line.split("Model:")[1].strip()
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        return "hermes-default"

    if validator == "codex":
        config_path = os.path.join(home, ".codex", "config.toml")
        if os.path.exists(config_path):
            with open(config_path) as f:
                for line in f:
                    if line.strip().startswith("model"):
                        return line.split("=")[1].strip().strip("\"")
        return "codex-default"

    if validator == "grok":
        cache_path = os.path.join(home, ".grok", "models_cache.json")
        if os.path.exists(cache_path):
            try:
                with open(cache_path) as f:
                    data = json.load(f)
                models = data.get("models", {})
                if models:
                    return next(iter(models.keys()))
            except (json.JSONDecodeError, OSError):
                pass
        return "grok-default"

    if validator == "claude":
        return "claude-default"

    if validator == "pool":
        return "poolside-default"

    return f"{validator}-default"


# ---------------------------------------------------------------------------
# Package reuse
# ---------------------------------------------------------------------------

def _reuse_package(project: Project, stage: str, model: str, label: str | None) -> dict[str, Any]:
    """Find the most recent existing package for this stage+model."""
    from .gui_service import GUIState
    runs = GUIState(project).runs()
    for run in runs:
        if run.get("stage") == stage and model.lower() in str(run.get("model", "")).lower():
            run_id = run.get("run_id")
            if run_id:
                pkg_root = project.path_setting("packages", "operator/_packages")
                for pkg_dir in sorted(pkg_root.rglob(f"*{run_id}*"), reverse=True):
                    if pkg_dir.is_dir():
                        zip_path = Path(str(pkg_dir) + ".zip")
                        return {
                            "blocked": False, "published": True, "dry_run": False,
                            "run_id": run_id,
                            "package_dir": str(pkg_dir),
                            "package_zip": str(zip_path) if zip_path.exists() else None,
                            "output_folder": str(project.path_setting("operator", "operator") / f"{stage}_{safe_label(model)}__{run_id}"),
                            "report_name": None,
                            "lint": {"passed": True, "hard_fails": [], "flags": []},
                            "provenance": {},
                        }
    return build_package(project, stage, model, label=label)


# ---------------------------------------------------------------------------
# Manual instructions formatter
# ---------------------------------------------------------------------------

def _format_manual_instructions(
    zip_path: str | None, rendered: Any, stage: str, model: str, run_id: str | None,
) -> str:
    lines = [
        f"RRG Dispatch — {stage} / {model}",
        f"Run ID: {run_id or '(none)'}",
        "",
    ]
    if zip_path and Path(zip_path).exists():
        lines.append(f"Package zip: {zip_path}")
        lines.append("")
        lines.append("Instructions:")
        lines.append("  1. Copy the zip to a location OUTSIDE this project.")
        lines.append("  2. Unzip it and run your validator model there.")
        lines.append("  3. Zip the validator's output folder.")
        lines.append(f"  4. Run: rrg import <returned.zip> --stage {stage} --model '{model}'")
    else:
        lines.append("(package not published — dry run or blocked)")
    lines.append("")
    lines.append(f"Prompt: {len(rendered.turns)} turn(s)")
    for i, turn in enumerate(rendered.turns, 1):
        lines.append(f"  Turn {i} — {turn.title}")
        preview = turn.text[:200] + ("..." if len(turn.text) > 200 else "")
        lines.append(f"    {preview}")
        lines.append("")
    if rendered.reminders:
        lines.append("Operator reminders (never model-facing):")
        lines.append(f"  {rendered.reminders[:200]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core dispatch
# ---------------------------------------------------------------------------

def dispatch(
    project: Project,
    stage: str,
    model: str,
    *,
    validator: str | None = None,
    mode: str | None = None,
    label: str | None = None,
    dry_run: bool = False,
    reuse: bool = False,
    skip_normalize: bool | None = None,
    auto_import: bool | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Orchestrate a validation dispatch.

    1. Build (or reuse) the package.
    2. Render the prompt for the given mode.
    3. Execute via the chosen validator (manual/hermes/claude/codex/grok/openrouter/prime-agent).
    4. (Optionally) import results and normalize.
    """
    prefs = load_prefs(project)
    # If validator not explicitly passed, check the roster entry for a validator field
    if not validator:
        roster_entry = project.model(stage, model)
        if roster_entry and roster_entry.get("validator"):
            validator = roster_entry["validator"]
    if not validator:
        validator = prefs.get("validator", "manual")
    mode = mode or prefs.get("mode", "discuss")
    if skip_normalize is None:
        skip_normalize = prefs.get("skip_normalize", False)
    if auto_import is None:
        auto_import = prefs.get("auto_import", True)

    # Step 1: Build (or reuse) the package
    if reuse:
        pkg_result = _reuse_package(project, stage, model, label)
    else:
        pkg_result = build_package(project, stage, model, label=label, dry_run=dry_run, force=force)

    if pkg_result["blocked"]:
        return {
            "package": pkg_result, "prompt": None, "zip_path": None,
            "validator": validator, "mode": mode, "conversation": [],
            "import_result": None, "normalize_result": None,
            "instructions": "Package blocked by blinding lint. Use --force to override.",
        }

    # Step 2: Render the prompt
    rendered = render_prompt(project, stage, model, mode=mode)
    prompt_summary = {
        "stage": rendered.stage, "model": rendered.model,
        "output_folder": rendered.output_folder, "report_name": rendered.report_name,
        "turns": [{"title": t.title, "text": t.text} for t in rendered.turns],
        "reminders": rendered.reminders,
    }
    zip_path = pkg_result.get("package_zip")
    run_id = pkg_result.get("run_id")

    # Step 3: Execute
    conversation: list[dict[str, Any]] = []
    instructions = ""
    collected_dir: Path | None = None

    if validator == "manual":
        instructions = _format_manual_instructions(zip_path, rendered, stage, model, run_id)
        # In agent mode, generate the conversation plan for reference
        if mode == "agent":
            for i, turn in enumerate(rendered.turns, 1):
                conversation.append({"turn": i, "title": turn.title, "prompt": turn.text, "response": ""})
                if "discuss" in turn.title.lower():
                    op = _generate_operator_response(turn.title, "", i)
                    conversation.append({"turn": i, "title": "Operator response (agent)", "prompt": op, "response": ""})
    elif validator == "prime-agent":
        raise RRGError("prime-agent validator requires the async IPython context; "
                        "use it from a prime-agent session or choose --validator manual/hermes/claude/codex/grok/openrouter")
    else:
        # Non-manual validators: create temp work dir, extract zip, run turns
        collected_dir = Path(tempfile.mkdtemp(prefix="rrg_dispatch_"))
        slug = _resolve_slug(project, model) if validator in SLUG_VALIDATORS else ""

        # Extract the package zip into the work dir so the validator has the files
        if zip_path and Path(zip_path).exists():
            import zipfile
            with zipfile.ZipFile(zip_path) as bundle:
                bundle.extractall(collected_dir)
            # Remove the RRG_RUN.txt from the work dir (the validator doesn't need it
            # and we don't want it to accidentally end up in the output)
            marker = collected_dir / "RRG_RUN.txt"
            if marker.exists():
                marker.unlink()

        conversation = _run_validator(validator, rendered, slug, str(collected_dir), mode)

    # Step 4: Import
    import_result: dict[str, Any] | None = None
    if auto_import and collected_dir is not None:
        has_files = any(p.is_file() for p in collected_dir.rglob("*"))
        if has_files:
            # Restore RRG_RUN.txt marker for auto-resolve
            if run_id:
                marker = collected_dir / "RRG_RUN.txt"
                if not marker.exists():
                    from .importer import render_run_marker
                    marker.write_text(render_run_marker(run_id))
            # Extract model provenance — prefer model detected from JSON output, fall back to config
            detected_model = None
            if conversation:
                for entry in conversation:
                    if entry.get("model"):
                        detected_model = entry["model"]
                        break
            model_name = detected_model or _get_model_provenance(validator, slug if validator in SLUG_VALIDATORS else "")

            import_result = import_run(
                project, stage, model, collected_dir,
                run_id=run_id, normalize=not skip_normalize,
                validator=validator, model_provenance=model_name,
            )
        shutil.rmtree(collected_dir, ignore_errors=True)

    normalize_result = None
    if import_result and import_result.get("normalize"):
        normalize_result = import_result["normalize"]

    # Extract model provenance — prefer model detected from JSON output, fall back to config
    detected_model = None
    if conversation:
        for entry in conversation:
            if entry.get("model"):
                detected_model = entry["model"]
                break
    model_name = detected_model or _get_model_provenance(validator, slug if validator in SLUG_VALIDATORS else "")

    return {
        "package": pkg_result, "prompt": prompt_summary, "zip_path": zip_path,
        "validator": validator, "mode": mode, "conversation": conversation,
        "import_result": import_result, "normalize_result": normalize_result,
        "instructions": instructions,
        "model_provenance": model_name,
    }
