\
"""Terminal UI for the RRG pipeline using rich.

Base2Tone Mall color scheme: dark green-teal base + gold/yellow accent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.text import Text
from rich.align import Align
from rich.columns import Columns
from rich.rule import Rule

from .dispatch import dispatch
from .doctor import inspect_project
from .eval_lite import eval_run
from .prefs import (
    DEFAULTS, EXECUTOR_OPTIONS, MODE_OPTIONS, PREF_KEYS,
    load_prefs, save_prefs, reset_prefs,
)
from .project import Project

# --- Base2Tone Mall palette ---
# Dark green-teal base + gold/yellow accent, muted sage secondary
GOLD = "#ffd75f"       # primary accent (yellow-gold)
SAGE = "#94d2bd"       # secondary accent (sage green)
DIM = "#5f6b5d"        # muted green for comments/dim text
TEAL = "#223024"       # background tone (for reference; rich handles bg)
LIGHT = "#c5c8c6"      # foreground text
WARN = "#ff7733"       # warm red-orange for errors/warnings

console = Console()

# Status symbols
OK = f"[{GOLD}]\u2713[/]"
WARN_S = f"[{WARN}]\u26a0[/]"
FAIL = f"[{WARN}]\u2717[/]"
SKIP = f"[{DIM}]-[/]"

# ASCII art logo
LOGO = r"""
 ___ ___ ___ ___ ___ ___
| . | . | -_|  _| . |  _|
|  _|   |___|_| |___|_  |
|_|                 |___|
"""

COMMAND_SUMMARY = [
    ("init",      "scaffold a new validation project",          "[--path .] [--force]"),
    ("doctor",    "inspect project health (non-strict)",       "[--stage S]"),
    ("preflight", "strict readiness gate before dispatch",      "[--stage S]"),
    ("convert",   "convert + verify data derivatives",          "[--formats csv parquet]"),
    ("package",   "build, lint, and publish a validator package", "--stage S --model M [--dry-run]"),
    ("dispatch",  "build + run + import in one step",            "--stage S --model M [--executor E] [--mode M]"),
    ("import",    "import returned validator output",           "<source> [--stage S] [--model M] [--skip-normalize]"),
    ("lint",      "lint an existing outgoing package",          "<package> --stage S"),
    ("prompt",    "render a stage prompt",                       "--stage S --model M [--turn N]"),
    ("runs",      "list the run registry",                       ""),
    ("scorecard", "generate a provisional grading scaffold",     "--run R --stage S --model M"),
    ("eval",      "evaluate a run (contract + breach + grading)", "--run R"),
    ("intake",    "origin intake prompt / check / apply",        "[--check] [--simplified] [--apply F]"),
    ("wizard",    "interactive 5-step setup walkthrough",        "[--non-interactive] [--step N] [--prefs]"),
    ("tui",       "this terminal UI",                            "[--step N] [--prefs] [--eval R]"),
    ("prefs",     "view/set user preferences",                    "[--set K=V] [--reset]"),
    ("gui",       "(parked) launch the local web GUI",            "[--workspace D] [--port P]"),
]

STEPS = [
    ("health", "Project health"),
    ("conversion", "Data conversion"),
    ("preflight", "Readiness checks"),
    ("roster", "Roster review"),
    ("dispatch", "Dispatch"),
]


def _logo_panel() -> Panel:
    """Build the RRG ASCII art logo panel."""
    logo_text = Text(LOGO, style=f"bold {GOLD}")
    subtitle = Text("Replication · Robustness · Generalization", style=f"{SAGE}")
    return Panel(
        Align.center(Group(logo_text, subtitle)),
        border_style=GOLD,
        padding=(0, 2),
    )


def _commands_table() -> Table:
    """Build the command summary table."""
    table = Table(
        show_header=True,
        header_style=f"bold {GOLD}",
        border_style=DIM,
        padding=(0, 1),
        title="Commands",
        title_style=f"bold {SAGE}",
    )
    table.add_column("Command", style=f"bold {GOLD}", no_wrap=True)
    table.add_column("Description", style=LIGHT)
    table.add_column("Flags", style=DIM, no_wrap=False)

    for cmd, desc, flags in COMMAND_SUMMARY:
        table.add_row(cmd, desc, flags)

    return table


def print_banner() -> None:
    """Print the RRG banner: ASCII art + command summary."""
    console.print()
    console.print(_logo_panel())
    console.print()
    console.print(Rule(style=DIM))
    console.print(_commands_table())
    console.print(Rule(style=DIM))
    console.print()


def run_tui(project: Project, step: int | None = None) -> None:
    """Launch the interactive TUI wizard."""
    console.clear()
    print_banner()

    project_info = Text.assemble(
        ("Project: ", f"bold {SAGE}"),
        (project.name, f"bold {GOLD}"),
        ("\n", ""),
        (str(project.root), DIM),
    )
    console.print(Panel(project_info, border_style=SAGE, padding=(0, 1)))
    console.print()

    max_step = step or len(STEPS)
    for i, (key, title) in enumerate(STEPS, 1):
        if i > max_step:
            break
        _run_step(project, key, title, i, max_step)
        if i < max_step:
            if not Confirm.ask(f"[{DIM}]Continue to step {i+1}?[/]", default=True):
                break


def _run_step(project: Project, key: str, title: str, step_num: int, max_step: int) -> None:
    """Run a single wizard step with rich formatting."""
    console.print()
    header = Text.assemble(
        (f" Step {step_num}/{max_step} ", f"bold {GOLD} on {TEAL}"),
        (f" {title} ", f"bold {LIGHT}"),
    )
    console.print(Rule(header, style=GOLD))

    if key == "health":
        _step_health(project)
    elif key == "conversion":
        _step_conversion(project)
    elif key == "preflight":
        _step_preflight(project)
    elif key == "roster":
        _step_roster(project)
    elif key == "dispatch":
        _step_dispatch(project)


def _step_health(project: Project) -> None:
    root = project.root
    checks = []

    marker = root / ".rrg_root"
    checks.append((".rrg_root marker", marker.exists(), "found" if marker.exists() else "missing"))

    config_path = project.config_path
    checks.append(("rrg.yaml", config_path.is_file(),
                   str(config_path.relative_to(root)) if config_path.is_file() else "missing"))

    study_path = project.study_path
    checks.append(("study.yaml", study_path.is_file(),
                   str(study_path.relative_to(root)) if study_path.is_file() else "missing"))

    version = project.config.get("version", 0)
    checks.append(("config version", int(version) == 1, f"v{version}" if version else "missing"))

    _print_checks(checks)


def _step_conversion(project: Project) -> None:
    dataset = project.study.get("dataset", {}) or {}
    source = dataset.get("source", "")
    main_name = dataset.get("main_name", "")
    checks = []

    source_path = project.path(source) if source else None
    checks.append(("source data", bool(source_path and source_path.exists()),
                   str(source_path.relative_to(project.root)) if source_path and source_path.exists() else "missing"))

    data_dir = project.path_setting("data", "data")
    for fmt in dataset.get("formats", ["csv", "parquet"]):
        deriv = data_dir / f"{main_name}.{fmt}"
        checks.append((f"{fmt} derivative", deriv.exists(),
                       str(deriv.relative_to(project.root)) if deriv.exists() else "not generated"))

    meta = dataset.get("metadata", "")
    if meta:
        meta_path = project.path(meta)
        checks.append(("metadata", meta_path.exists(),
                       "found" if meta_path.exists() else "missing"))

    _print_checks(checks)


def _step_preflight(project: Project) -> None:
    report = inspect_project(project, strict=True)
    checks = []
    for check in report["checks"]:
        is_ok = check["severity"] == "ok"
        checks.append((check["name"], is_ok, check["detail"]))

    _print_checks(checks)

    if report["ok"]:
        console.print(f"\n  {OK} [{SAGE}]All preflight checks passed.[/]")
    else:
        console.print(f"\n  {FAIL} [{WARN}]Some preflight checks failed.[/]")


def _step_roster(project: Project) -> None:
    for stage_id in project.stage_ids():
        stage = project.stage(stage_id)
        if not stage.get("enabled", True):
            console.print(f"\n  {SKIP} [{DIM}]Stage {stage_id}: disabled — {stage.get('blocked_reason', '')}[/]")
            continue

        models = project.roster(stage_id)
        table = Table(title=f"Stage: {stage_id}", show_header=True,
                      header_style=f"bold {GOLD}", border_style=DIM, padding=(0, 1))
        table.add_column("Model", style=f"bold {GOLD}")
        table.add_column("Vendor", style=LIGHT)
        table.add_column("Type", style=SAGE)
        table.add_column("License", style=DIM)

        for m in models:
            table.add_row(
                m.get("model", ""),
                m.get("vendor", ""),
                m.get("type", ""),
                m.get("license", ""),
            )
        console.print(table)


def _step_dispatch(project: Project) -> None:
    prefs = load_prefs(project)

    console.print(f"\n  [{SAGE}]Current preferences:[/]")
    console.print(f"    executor: [{GOLD}]{prefs.get('executor', 'manual')}[/]")
    console.print(f"    mode: [{GOLD}]{prefs.get('mode', 'discuss')}[/]")

    enabled_stages = []
    for sid in project.stage_ids():
        stage = project.stage(sid)
        if stage.get("enabled", True):
            models = project.roster(sid)
            enabled_stages.append((sid, models))

    if not enabled_stages:
        console.print(f"\n  {WARN_S} No enabled stages.")
        return

    console.print(f"\n  [{SAGE}]Enabled stages:[/]")
    for sid, models in enabled_stages:
        console.print(f"    [{GOLD}]{sid}[/]: {', '.join(m.get('model', '') for m in models)}")

    stage = Prompt.ask(f"\n  [{GOLD}]Which stage to dispatch?[/]",
                       choices=[s for s, _ in enabled_stages] + ["skip"],
                       default="skip")
    if stage == "skip":
        console.print(f"  [{DIM}]Skipping dispatch.[/]")
        return

    stage_models = next((ms for s, ms in enabled_stages if s == stage), [])
    if not stage_models:
        console.print(f"  {FAIL} No models in roster for {stage}")
        return

    model_names = [m.get("model", "") for m in stage_models]
    model = Prompt.ask(f"  [{GOLD}]Which model?[/]", choices=model_names, default=model_names[0])

    executor = Prompt.ask(f"  [{GOLD}]Executor?[/]",
                          choices=list(EXECUTOR_OPTIONS),
                          default=prefs.get("executor", "manual"))

    mode = Prompt.ask(f"  [{GOLD}]Mode?[/]",
                      choices=list(MODE_OPTIONS),
                      default=prefs.get("mode", "discuss"))

    console.print(f"\n  [{DIM}]Dispatching {stage} / {model} ({executor}, {mode})...[/]")
    result = dispatch(project, stage, model, executor=executor, mode=mode)

    _print_dispatch_result(result)

    if Confirm.ask(f"\n  [{SAGE}]Save these settings as defaults?[/]", default=False):
        save_prefs(project, {"executor": executor, "mode": mode})
        console.print(f"  [{SAGE}]Saved to .rrg_prefs.yaml[/]")


def _print_checks(checks: list[tuple[str, bool, str]]) -> None:
    for name, ok, detail in checks:
        symbol = OK if ok else FAIL
        console.print(f"  {symbol} [{SAGE}]{name}[/]: {detail}")


def _print_dispatch_result(result: dict[str, Any]) -> None:
    pkg = result["package"]
    if pkg.get("blocked"):
        console.print(Panel(f"{FAIL} [{WARN}]Package blocked by blinding lint[/]",
                            border_style=WARN))
        return

    console.print(f"  {OK} Run ID: [{GOLD}]{pkg.get('run_id', '\u2014')}[/]")

    if result.get("zip_path") and Path(result["zip_path"]).exists():
        console.print(f"  {OK} Package zip: {result['zip_path']}")

    prompt = result.get("prompt")
    if prompt:
        console.print(f"  {OK} Prompt: {len(prompt['turns'])} turn(s)")
        for i, t in enumerate(prompt["turns"], 1):
            console.print(f"     [{DIM}]Turn {i}[/] \u2014 {t['title']}")

    if result.get("conversation"):
        console.print(f"  {OK} Conversation: {len(result['conversation'])} exchange(s)")

    if result.get("import_result"):
        imp = result["import_result"]
        console.print(f"  {OK} Imported: {imp['count']} files into {imp['run']}")
        breach = imp.get("breach", {})
        if breach.get("copied_secrets"):
            console.print(f"  {FAIL} [{WARN}]BLINDING BREACH: {len(breach['copied_secrets'])} file(s) match answer key[/]")
        if imp.get("normalize"):
            norm = imp["normalize"]
            if norm.get("files_moved"):
                console.print(f"  {OK} Normalized: {len(norm['files_moved'])} file(s)")
            if norm.get("summary_json_created"):
                qs = ", ".join(f"Q{q}" for q in norm["summary_json_created"])
                console.print(f"  {OK} Created summary.json for {qs}")
            if norm.get("missing"):
                qs = ", ".join(f"Q{q}" for q in norm["missing"])
                console.print(f"  {WARN_S} Missing: {qs}")
    elif result.get("instructions"):
        console.print()
        console.print(Panel(result["instructions"], title="Instructions", border_style=GOLD))


def run_tui_prefs(project: Project) -> None:
    """Interactive prefs editor with rich formatting."""
    console.clear()
    print_banner()

    prefs = load_prefs(project)

    console.print(Panel(f"[bold]RRG Preferences[/bold]", border_style=GOLD))
    _print_prefs_table(prefs)

    console.print(f"\n  [{DIM}]executor: {', '.join(EXECUTOR_OPTIONS)}[/]")
    console.print(f"  [{DIM}]mode: {', '.join(MODE_OPTIONS)}[/]")
    console.print(f"  [{DIM}]skip_normalize: true/false  auto_import: true/false[/]")
    console.print(f"  [{DIM}]type 'reset' to restore defaults[/]")

    key = Prompt.ask(f"\n  [{GOLD}]Edit which?[/] (or press enter to exit)",
                     default="")
    if not key:
        return

    if key == "reset":
        reset_prefs(project)
        console.print(f"  [{SAGE}]Reset to defaults.[/]")
        _print_prefs_table(DEFAULTS)
        return

    if key not in PREF_KEYS:
        console.print(f"  [{WARN}]Unknown key: {key}[/]")
        return

    options = {
        "executor": list(EXECUTOR_OPTIONS),
        "mode": list(MODE_OPTIONS),
    }.get(key)

    if options:
        console.print(f"    [{DIM}]Options: {', '.join(options)}[/]")
    console.print(f"    [{DIM}]Current: [{GOLD}]{prefs.get(key)}[/]")

    value = Prompt.ask("    New value", default=str(prefs.get(key, "")))
    if not value:
        return

    if key in ("skip_normalize", "auto_import"):
        value = value.lower() in ("true", "yes", "1")

    save_prefs(project, {key: value})
    console.print(f"  [{SAGE}]Saved .rrg_prefs.yaml[/]")
    _print_prefs_table(load_prefs(project))


def _print_prefs_table(prefs: dict[str, Any]) -> None:
    table = Table(show_header=True, header_style=f"bold {GOLD}",
                  border_style=DIM, padding=(0, 2))
    table.add_column("Key", style=f"bold {GOLD}")
    table.add_column("Value", style=SAGE)
    for key in PREF_KEYS:
        table.add_row(key, str(prefs.get(key)))
    console.print(table)


def run_tui_eval(project: Project, run_path: str) -> None:
    """Run eval and display results with rich formatting."""
    console.clear()
    print_banner()

    result = eval_run(project, project.path(run_path))

    # Contract
    contract = result["deliverable_contract"]
    console.print(Panel(f"[bold]Deliverable Contract[/bold]", border_style=GOLD))
    if contract["all_conform"]:
        console.print(f"  {OK} [{SAGE}]All questions conform.[/]")
    else:
        for q in contract["questions"]:
            missing = []
            if not q["has_analysis"]: missing.append("analysis")
            if not q["has_raw_csv"]: missing.append("raw CSV")
            if not q["has_fig_py"]: missing.append("fig script")
            if not q["has_fig_png"]: missing.append("figure")
            if not q["has_summary_json"]: missing.append("summary.json")
            if not q["has_dyfa_section"]: missing.append("DYFA")
            if missing:
                console.print(f"  {FAIL} Q{q['question']}: missing {', '.join(missing)}")

    # Breach
    breach = result["breach"]
    console.print()
    console.print(Panel(f"[bold]Breach Status[/bold]", border_style=GOLD))
    if breach["flagged"]:
        console.print(f"  {FAIL} [{WARN}]BREACH: {len(breach['copied_secrets'])} file(s) match answer key[/]")
        if breach["acknowledged"]:
            console.print(f"  {OK} Acknowledged \u2014 grading unblocked.")
        else:
            console.print(f"  {WARN_S} NOT acknowledged \u2014 grading blocked.")
    else:
        console.print(f"  {OK} [{SAGE}]Clean \u2014 no copied secrets.[/]")
    if breach["ran_inside_project"]:
        console.print(f"  {WARN_S} Outputs came from inside project tree.")

    # Grading
    grading = result["grading"]
    console.print()
    console.print(Panel(f"[bold]Grading Status[/bold]", border_style=GOLD))
    if grading["graded"]:
        suffix = " (finalized)" if grading["finalized"] else ""
        console.print(f"  {OK} [{SAGE}]Graded \u2014 {grading['verdicts_count']} verdict(s).{suffix}[/]")
    else:
        console.print(f"  {WARN_S} Pending \u2014 {grading['verdicts_count']} verdict(s) assigned.")

    console.print(f"\n  [{DIM}]File count: {result['file_count']}[/]")
