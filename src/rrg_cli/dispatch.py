\
"""Validator dispatch: build → prompt → run executor → collect → import → normalize.

This module orchestrates the full dispatch round-trip. It calls the existing
``build_package`` and ``render_prompt`` functions, then delegates to an executor
(manual, hermes, openrouter, or prime-agent) to run the validator model, and
finally imports the results via ``import_run`` with auto-normalization.

Preferences (``.rrg_prefs.yaml``) supply defaults for executor, mode,
skip_normalize, and auto_import. CLI flags override prefs.
"""

from __future__ import annotations

import json
import os
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

# --- Executor helpers ---

def _resolve_slug(project: Project, model: str) -> str:
    """Resolve a model name to its dispatch slug from rrg.yaml > dispatch.model_slugs."""
    slugs = project.config.get("dispatch", {}).get("model_slugs", {}) or {}
    # Exact match
    if model in slugs:
        return str(slugs[model])
    # Fuzzy match (case-insensitive substring)
    for key, slug in slugs.items():
        if model.lower() in key.lower() or key.lower() in model.lower():
            return str(slug)
    # Fall back to the model name itself
    return safe_label(model)


def _run_hermes(prompt: str, slug: str, work_dir: str) -> str:
    """Shell out to the hermes CLI with the rendered prompt.

    Hermes runs in *work_dir* (a temp dir outside the project tree) so the
    validator cannot reach operator secrets.
    """
    cmd = ["hermes", "run", "--model", slug]
    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            cwd=work_dir,
            timeout=600,
        )
        if result.returncode != 0:
            return f"[hermes error: exit {result.returncode}]\n{result.stderr}"
        return result.stdout
    except FileNotFoundError:
        raise RRGError("hermes CLI not found; install it or use --executor manual")
    except subprocess.TimeoutExpired:
        raise RRGError("hermes timed out after 600 seconds")


def _call_openrouter(prompt: str, slug: str, messages: list[dict[str, str]] | None = None) -> str:
    """Call the OpenRouter chat completions API directly.

    Uses ``OPENROUTER_API_KEY`` from the environment.
    """
    import httpx

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RRGError("OPENROUTER_API_KEY not set in environment")

    payload_messages = messages or [{"role": "user", "content": prompt}]
    payload = {
        "model": slug,
        "messages": payload_messages,
        "temperature": 0,
    }
    try:
        response = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=300,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except httpx.HTTPError as exc:
        raise RRGError(f"OpenRouter API error: {exc}")


# --- Agent-mode operator response generator ---

def _generate_operator_response(turn_title: str, validator_response: str, turn_num: int) -> str:
    """Generate a simple operator response for agent-mode discuss turns.

    This is intentionally conservative — it keeps the multi-turn flow moving
    without a human. It doesn't try to be a brilliant methodologist.
    """
    title_lower = turn_title.lower()
    if "propose" in title_lower:
        return (
            "I've reviewed your proposed methods. They look defensible. "
            "Please proceed to lock your approach."
        )
    if "discuss" in title_lower:
        return (
            "Your reasoning is sound. I don't have objections to the methods "
            "you've proposed. Please finalize your approach."
        )
    if "lock" in title_lower:
        return "Approach confirmed. You may proceed to execution."
    return "Proceed to the next step."


# --- Core dispatch ---

def dispatch(
    project: Project,
    stage: str,
    model: str,
    *,
    executor: str | None = None,
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
    3. Execute via the chosen executor.
    4. (Optionally) import results and normalize.

    Returns a dict with: package, prompt, zip_path, executor, mode, conversation,
    import_result, normalize_result, instructions.
    """
    # Resolve defaults from prefs
    prefs = load_prefs(project)
    executor = executor or prefs.get("executor", "manual")
    mode = mode or prefs.get("mode", "discuss")
    if skip_normalize is None:
        skip_normalize = prefs.get("skip_normalize", False)
    if auto_import is None:
        auto_import = prefs.get("auto_import", True)

    # Step 1: Build (or reuse) the package
    if reuse:
        pkg_result = _reuse_package(project, stage, model, label)
    else:
        pkg_result = build_package(
            project, stage, model,
            label=label, dry_run=dry_run, force=force,
        )

    if pkg_result["blocked"]:
        return {
            "package": pkg_result,
            "prompt": None,
            "zip_path": None,
            "executor": executor,
            "mode": mode,
            "conversation": [],
            "import_result": None,
            "normalize_result": None,
            "instructions": "Package blocked by blinding lint. Use --force to override.",
        }

    # Step 2: Render the prompt
    rendered = render_prompt(project, stage, model, mode=mode)
    prompt_summary = {
        "stage": rendered.stage,
        "model": rendered.model,
        "output_folder": rendered.output_folder,
        "report_name": rendered.report_name,
        "turns": [
            {"title": t.title, "text": t.text}
            for t in rendered.turns
        ],
        "reminders": rendered.reminders,
    }

    zip_path = pkg_result.get("package_zip")
    run_id = pkg_result.get("run_id")

    # Step 3: Execute
    conversation: list[dict[str, Any]] = []
    instructions = ""
    collected_dir: Path | None = None

    if executor == "manual":
        instructions = _format_manual_instructions(
            zip_path, rendered, stage, model, run_id,
        )
        # In agent mode, generate the conversation plan (for reference)
        if mode == "agent":
            for i, turn in enumerate(rendered.turns, 1):
                conversation.append({
                    "turn": i,
                    "title": turn.title,
                    "prompt": turn.text,
                    "response": "",
                })
                if "discuss" in turn.title.lower():
                    op_response = _generate_operator_response(turn.title, "", i)
                    conversation.append({
                        "turn": i,
                        "title": "Operator response (agent)",
                        "prompt": op_response,
                        "response": "",
                    })
    else:
        # For non-manual executors, create a temp work dir OUTSIDE the project
        collected_dir = Path(tempfile.mkdtemp(prefix="rrg_dispatch_"))
        slug = _resolve_slug(project, model)

        if executor == "hermes":
            conversation = _run_executor_hermes(
                rendered, slug, str(collected_dir), mode,
            )
        elif executor == "openrouter":
            conversation = _run_executor_openrouter(
                rendered, slug, str(collected_dir), mode,
            )
        elif executor == "prime-agent":
            raise RRGError(
                "prime-agent executor requires the async IPython context; "
                "use it from a prime-agent session or choose --executor manual/hermes/openrouter"
            )
        else:
            raise RRGError(f"unknown executor: {executor}")

    # Step 4: Import (if auto_import and we have collected output)
    import_result: dict[str, Any] | None = None
    if auto_import and collected_dir is not None:
        # Ensure there are some files to import
        has_files = any(p.is_file() for p in collected_dir.rglob("*"))
        if has_files:
            import_result = import_run(
                project, stage, model, collected_dir,
                run_id=run_id,
                normalize=not skip_normalize,
            )
        # Cleanup temp dir
        shutil.rmtree(collected_dir, ignore_errors=True)
    elif auto_import and executor == "manual":
        # Manual executor: no auto-import (human runs externally)
        pass

    normalize_result = None
    if import_result and import_result.get("normalize"):
        normalize_result = import_result["normalize"]

    return {
        "package": pkg_result,
        "prompt": prompt_summary,
        "zip_path": zip_path,
        "executor": executor,
        "mode": mode,
        "conversation": conversation,
        "import_result": import_result,
        "normalize_result": normalize_result,
        "instructions": instructions,
    }


def _reuse_package(project: Project, stage: str, model: str, label: str | None) -> dict[str, Any]:
    """Find the most recent existing package for this stage+model and return a summary."""
    from .gui_service import GUIState

    runs = GUIState(project).runs()
    for run in runs:
        if run.get("stage") == stage and model.lower() in str(run.get("model", "")).lower():
            run_id = run.get("run_id")
            if run_id:
                # Find the package dir
                pkg_root = project.path_setting("packages", "operator/_packages")
                for pkg_dir in sorted(pkg_root.rglob(f"*{run_id}*"), reverse=True):
                    if pkg_dir.is_dir():
                        zip_path = Path(str(pkg_dir) + ".zip")
                        return {
                            "blocked": False,
                            "published": True,
                            "dry_run": False,
                            "run_id": run_id,
                            "package_dir": str(pkg_dir),
                            "package_zip": str(zip_path) if zip_path.exists() else None,
                            "output_folder": str(project.path_setting("operator", "operator") / f"{stage}_{safe_label(model)}__{run_id}"),
                            "report_name": None,
                            "lint": {"passed": True, "hard_fails": [], "flags": []},
                            "provenance": {},
                        }
    # No existing package found — build a new one
    return build_package(project, stage, model, label=label)


def _format_manual_instructions(
    zip_path: str | None,
    rendered: Any,
    stage: str,
    model: str,
    run_id: str | None,
) -> str:
    """Format the instructions for manual execution."""
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
        lines.append("")
    else:
        lines.append("(package not published — dry run or blocked)")
        lines.append("")

    lines.append(f"Prompt: {len(rendered.turns)} turn(s)")
    for i, turn in enumerate(rendered.turns, 1):
        lines.append(f"  Turn {i} — {turn.title}")
        lines.append(f"    {turn.text[:200]}{'...' if len(turn.text) > 200 else ''}")
        lines.append("")

    if rendered.reminders:
        lines.append("Operator reminders (never model-facing):")
        lines.append(f"  {rendered.reminders[:200]}")

    return "\n".join(lines)


def _run_executor_hermes(
    rendered: Any,
    slug: str,
    work_dir: str,
    mode: str,
) -> list[dict[str, Any]]:
    """Run the hermes executor turn-by-turn."""
    conversation: list[dict[str, Any]] = []
    for i, turn in enumerate(rendered.turns, 1):
        response = _run_hermes(turn.text, slug, work_dir)
        conversation.append({
            "turn": i,
            "title": turn.title,
            "prompt": turn.text,
            "response": response,
        })
        # In agent mode, generate operator responses for discuss turns
        if mode == "agent" and "discuss" in turn.title.lower():
            op_response = _generate_operator_response(turn.title, response, i)
            op_reply = _run_hermes(op_response, slug, work_dir)
            conversation.append({
                "turn": i,
                "title": f"Operator response (agent)",
                "prompt": op_response,
                "response": op_reply,
            })
    return conversation


def _run_executor_openrouter(
    rendered: Any,
    slug: str,
    work_dir: str,
    mode: str,
) -> list[dict[str, Any]]:
    """Run the OpenRouter executor turn-by-turn."""
    conversation: list[dict[str, Any]] = []
    messages: list[dict[str, str]] = []

    for i, turn in enumerate(rendered.turns, 1):
        messages.append({"role": "user", "content": turn.text})
        response = _call_openrouter(turn.text, slug, messages)
        messages.append({"role": "assistant", "content": response})
        conversation.append({
            "turn": i,
            "title": turn.title,
            "prompt": turn.text,
            "response": response,
        })
        # In agent mode, generate operator responses for discuss turns
        if mode == "agent" and "discuss" in turn.title.lower():
            op_response = _generate_operator_response(turn.title, response, i)
            messages.append({"role": "user", "content": op_response})
            op_reply = _call_openrouter(op_response, slug, messages)
            messages.append({"role": "assistant", "content": op_reply})
            conversation.append({
                "turn": i,
                "title": f"Operator response (agent)",
                "prompt": op_response,
                "response": op_reply,
            })

    # Write any generated content to the work dir
    # (the validator's final response may contain code/output)
    if conversation:
        final = conversation[-1]["response"]
        (Path(work_dir) / "SUMMARY.md").write_text(final, encoding="utf-8")

    return conversation
