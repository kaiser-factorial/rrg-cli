from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .blinding import lint_package
from .converter import DEFAULT_NA_TOKEN, SUPPORTED_FORMATS, convert_dataset
from .doctor import inspect_project
from .errors import RRGError
from .gui import serve
from .importer import import_run
from .packager import build_package
from .project import Project
from .prompts import render_prompt
from .scaffold import init_project
from .scorecard import build_scorecard
from .workspace import initial_workspace_project


def _emit(value: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, indent=2, ensure_ascii=False))
    elif isinstance(value, str):
        print(value)
    else:
        print(json.dumps(value, indent=2, ensure_ascii=False))


def _project(args) -> Project:
    return Project.load(
        root=getattr(args, "root", None),
        config=getattr(args, "config", "rrg.yaml"),
        study=getattr(args, "study", "study.yaml"),
    )


def _add_project_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root")
    parser.add_argument("--config", default="rrg.yaml")
    parser.add_argument("--study", default="study.yaml")


def _checks_human(report: dict[str, Any]) -> str:
    markers = {"ok": "✓", "warning": "⚠", "error": "✗"}
    lines = [f"RRG {'preflight' if report['strict'] else 'doctor'} — {report['project']}"]
    for check in report["checks"]:
        lines.append(f"{markers[check['severity']]} {check['name']}: {check['detail']}")
    lines.append("PASS" if report["ok"] else "NOT READY")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rrg", description="RRG research-validation pipeline")
    parser.add_argument("--version", action="version", version=f"rrg-cli {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create a new RRG project")
    init.add_argument("path", nargs="?", default=".")
    init.add_argument("--force", action="store_true")
    init.add_argument("--json", action="store_true")

    for name, help_text in (("doctor", "inspect project health"), ("preflight", "run strict readiness checks")):
        command = sub.add_parser(name, help=help_text)
        _add_project_args(command)
        command.add_argument("--stage")
        command.add_argument("--json", action="store_true")

    convert = sub.add_parser("convert", help="convert and verify a source dataset")
    convert.add_argument("source", nargs="?")
    _add_project_args(convert)
    convert.add_argument("--out")
    convert.add_argument("--formats", nargs="+", choices=SUPPORTED_FORMATS, default=list(SUPPORTED_FORMATS))
    convert.add_argument("--labeled", action="store_true")
    convert.add_argument("--na-token", default=DEFAULT_NA_TOKEN)
    convert.add_argument("--float-format")
    convert.add_argument("--json", action="store_true")

    package = sub.add_parser("package", help="build, lint, and publish a validator package")
    _add_project_args(package)
    package.add_argument("--stage", required=True)
    package.add_argument("--model", required=True)
    package.add_argument("--label")
    package.add_argument("--dry-run", action="store_true")
    package.add_argument("--force", action="store_true")
    package.add_argument("--allow-unlisted", action="store_true")
    package.add_argument("--json", action="store_true")

    lint = sub.add_parser("lint", help="lint an existing outgoing package")
    lint.add_argument("package")
    _add_project_args(lint)
    lint.add_argument("--stage", required=True)
    lint.add_argument("--json", action="store_true")

    importer = sub.add_parser("import", help="import a validator's returned outputs into its run folder")
    _add_project_args(importer)
    importer.add_argument("source", help="the returned folder or .zip from the validator")
    importer.add_argument("--stage", help="optional; auto-resolved from the RRG_RUN.txt marker when omitted")
    importer.add_argument("--model", help="optional; auto-resolved from the RRG_RUN.txt marker when omitted")
    importer.add_argument("--label")
    importer.add_argument("--run-id", dest="run_id", help="target a specific build's run folder (ADR 0002)")
    importer.add_argument("--skip-normalize", action="store_true", help="skip auto-normalization of returned output")
    importer.add_argument("--json", action="store_true")

    ack = sub.add_parser(
        "acknowledge-breach", help="acknowledge a flagged blinding breach so grading can proceed"
    )
    _add_project_args(ack)
    ack.add_argument("--run", required=True, help="the run path the breach was recorded against")
    ack.add_argument("--json", action="store_true")

    archive_cmd = sub.add_parser("archive", help="move a file/dir into the reversible archive")
    _add_project_args(archive_cmd)
    archive_cmd.add_argument("path", help="project-relative path to archive")
    archive_cmd.add_argument("--json", action="store_true")

    archive_ls = sub.add_parser("archive-ls", help="list archived items")
    _add_project_args(archive_ls)
    archive_ls.add_argument("--json", action="store_true")

    restore_cmd = sub.add_parser("restore", help="restore an archived item to its original path")
    _add_project_args(restore_cmd)
    restore_cmd.add_argument("id", help="archive item id (see archive-ls)")
    restore_cmd.add_argument("--json", action="store_true")

    purge_cmd = sub.add_parser("purge", help="permanently delete an archived item")
    _add_project_args(purge_cmd)
    purge_cmd.add_argument("id", help="archive item id (see archive-ls)")
    purge_cmd.add_argument("--json", action="store_true")

    runs_cmd = sub.add_parser("runs", help="list the run registry (built runs and their status)")
    _add_project_args(runs_cmd)
    runs_cmd.add_argument("--json", action="store_true")

    prompt = sub.add_parser("prompt", help="render a stage prompt")
    _add_project_args(prompt)
    prompt.add_argument("--stage", required=True)
    prompt.add_argument("--model", required=True)
    prompt.add_argument("--mode", choices=["discuss", "nodiscuss"], default="discuss")
    prompt.add_argument("--turn", type=int)
    prompt.add_argument("--include-reminders", action="store_true")
    prompt.add_argument("--json", action="store_true")

    scorecard = sub.add_parser("scorecard", help="create a provisional human-grading scorecard")
    _add_project_args(scorecard)
    scorecard.add_argument("--run", required=True)
    scorecard.add_argument("--stage", required=True)
    scorecard.add_argument("--model", required=True)
    scorecard.add_argument("--key")
    scorecard.add_argument("--map")
    scorecard.add_argument("--out-dir")
    scorecard.add_argument("--license", default="record-at-run-time")
    scorecard.add_argument("--json", action="store_true")

    intake = sub.add_parser(
        "intake",
        help="render the origin-intake prompt, or apply a returned intake to write SUMMARY.md + rename figures",
    )
    _add_project_args(intake)
    intake.add_argument("--apply", metavar="FILE", help="apply a returned intake file (writes SUMMARY.md, renames figures)")
    intake.add_argument("--check", action="store_true", help="check whether intake is needed (reports missing sections)")
    intake.add_argument("--simplified", action="store_true", help="use simplified intake (no figure_map; normalizer handles figures)")
    intake.add_argument("--json", action="store_true")

    gui = sub.add_parser("gui", help="launch the local status GUI")
    _add_project_args(gui)
    gui.add_argument("--workspace", help="enable safe switching among projects below this directory")
    gui.add_argument("--port", type=int, default=8765)
    gui.add_argument("--open", action="store_true")

    prefs_cmd = sub.add_parser("prefs", help="view or set user preferences")
    _add_project_args(prefs_cmd)
    prefs_cmd.add_argument("--set", metavar="KEY=VALUE", action="append", help="set a preference (e.g. --set executor=hermes)")
    prefs_cmd.add_argument("--reset", action="store_true", help="reset preferences to defaults")
    prefs_cmd.add_argument("--json", action="store_true")

    dispatch_cmd = sub.add_parser("dispatch", help="build, run, and import a validation package in one step")
    _add_project_args(dispatch_cmd)
    dispatch_cmd.add_argument("--stage", required=True)
    dispatch_cmd.add_argument("--model", required=True)
    dispatch_cmd.add_argument("--executor", choices=["manual", "hermes", "claude", "codex", "grok", "pool", "openrouter", "prime-agent"],
                              default=None, help="executor (default: from prefs or manual)")
    dispatch_cmd.add_argument("--mode", choices=["discuss", "nodiscuss", "agent"],
                              default=None, help="prompt mode (default: from prefs or discuss)")
    dispatch_cmd.add_argument("--label")
    dispatch_cmd.add_argument("--dry-run", action="store_true")
    dispatch_cmd.add_argument("--reuse", action="store_true", help="reuse an existing package if one exists")
    dispatch_cmd.add_argument("--skip-normalize", action="store_true")
    dispatch_cmd.add_argument("--no-auto-import", action="store_true")
    dispatch_cmd.add_argument("--force", action="store_true")
    dispatch_cmd.add_argument("--json", action="store_true")

    wizard_cmd = sub.add_parser("wizard", help="interactive setup and dispatch walkthrough")
    _add_project_args(wizard_cmd)
    wizard_cmd.add_argument("--non-interactive", action="store_true", help="run all steps without prompting")
    wizard_cmd.add_argument("--step", type=int, default=None, help="run up to this step (1-5)")
    wizard_cmd.add_argument("--prefs", action="store_true", help="interactive prefs editor")
    wizard_cmd.add_argument("--json", action="store_true")

    eval_cmd = sub.add_parser("eval", help="evaluate a run for pipeline metrics (deliverable contract + breach + grading)")
    _add_project_args(eval_cmd)
    eval_cmd.add_argument("--run", required=True, help="run folder path (relative to project root)")
    eval_cmd.add_argument("--json", action="store_true")

    tui_cmd = sub.add_parser("tui", help="launch the interactive terminal UI")
    _add_project_args(tui_cmd)
    tui_cmd.add_argument("--step", type=int, default=None, help="run up to this step (1-5)")
    tui_cmd.add_argument("--prefs", action="store_true", help="interactive prefs editor")
    tui_cmd.add_argument("--eval", metavar="RUN", default=None, help="eval a run with rich output")

    sub.add_parser("version", help="print the installed version")
    return parser


def run(args: argparse.Namespace) -> int:
    if args.command == "version":
        print(__version__)
        return 0
    if args.command == "init":
        created = init_project(Path(args.path), force=args.force)
        result = {"root": str(Path(args.path).resolve()), "created": [str(path) for path in created]}
        _emit(result if args.json else f"Created RRG project at {result['root']} ({len(created)} files)", args.json)
        return 0
    if args.command == "gui" and args.workspace:
        workspace = Path(args.workspace).expanduser().resolve()
        project = initial_workspace_project(workspace, requested=args.root)
        serve(project, args.port, open_browser=args.open, workspace=str(workspace))
        return 0
    project = _project(args)
    if args.command in {"doctor", "preflight"}:
        report = inspect_project(project, stage=args.stage, strict=args.command == "preflight")
        _emit(report if args.json else _checks_human(report), args.json)
        return 0 if report["ok"] else 2
    if args.command == "convert":
        dataset = project.study.get("dataset", {}) or {}
        source = project.path(args.source or dataset.get("source") or project.config.get("origin", {}).get("source_data"))
        if args.out:
            output = project.path(args.out)
        else:
            main_name = str(dataset.get("main_name") or source.stem)
            output = project.path_setting("data", "data") / main_name
        result = convert_dataset(source, output, args.formats, args.labeled, args.na_token, args.float_format)
        _emit(result, args.json)
        return 0 if result["all_verified"] else 2
    if args.command == "package":
        result = build_package(
            project,
            args.stage,
            args.model,
            label=args.label,
            dry_run=args.dry_run,
            force=args.force,
            allow_unlisted=args.allow_unlisted,
        )
        _emit(result, args.json)
        return 2 if result["blocked"] else 0
    if args.command == "lint":
        report = lint_package(project.path(args.package), args.stage, project)
        _emit(report.as_dict(), args.json)
        return 0 if report.passed else 2
    if args.command == "import":
        result = import_run(
            project, args.stage, args.model, args.source, label=args.label, run_id=args.run_id,
            normalize=not args.skip_normalize,
        )
        how = " (auto-resolved from RRG_RUN.txt)" if result.get("auto_resolved") else ""
        breach = result.get("breach") or {}
        if args.json:
            _emit(result, args.json)
        else:
            print(f"Imported {result['count']} files into {result['run']}{how}")
            copied = breach.get("copied_secrets") or []
            if copied:
                print(
                    f"  ⚠ BLINDING BREACH: {len(copied)} returned file(s) match the withheld "
                    "answer key — grading is blocked until acknowledged "
                    "(rrg acknowledge-breach --run …):"
                )
                for item in copied:
                    print(f"    - {item['returned']}  ==  {item['matches']}")
            elif breach.get("ran_inside_project"):
                print("  ⚠ note: returned outputs came from inside the project tree; "
                      "isolation may have been skipped.")
        return 3 if (breach.get("copied_secrets")) else 0
    if args.command == "acknowledge-breach":
        from . import grading as grading_module

        result = grading_module.acknowledge_breach(project, args.run)
        _emit(result if args.json else f"Breach acknowledged for {args.run}; grading unblocked.", args.json)
        return 0
    if args.command == "runs":
        from .gui_service import GUIState

        rows = GUIState(project).runs()
        if args.json:
            _emit({"runs": rows}, args.json)
        elif not rows:
            print("No runs yet.")
        else:
            for row in rows:
                status = "graded" if row["graded"] else ("returned" if row["returned"] else "pending")
                if row.get("flagged"):
                    status += " ⚠BREACH"
                run_id = row.get("run_id") or "—"
                print(f"{row['stage']:<14} {row['model']:<22} {run_id:<10} {status:<18} {row['file_count']} files")
        return 0
    if args.command == "archive":
        from . import archive as archive_module

        record = archive_module.archive_item(project, args.path)
        _emit(record if args.json else f"Archived {record['original']} (id {record['id']})", args.json)
        return 0
    if args.command == "archive-ls":
        from . import archive as archive_module

        items = archive_module.list_archive(project)
        if args.json:
            _emit({"items": items}, args.json)
        elif not items:
            print("Archive is empty.")
        else:
            for item in items:
                print(f"{item['id']}  {item['kind']:<9}  {item['original']}")
        return 0
    if args.command == "restore":
        from . import archive as archive_module

        result = archive_module.restore_item(project, args.id)
        _emit(result if args.json else f"Restored {result['restored']}", args.json)
        return 0
    if args.command == "purge":
        from . import archive as archive_module

        result = archive_module.purge_item(project, args.id)
        _emit(result if args.json else f"Purged {result['purged']} (permanent)", args.json)
        return 0
    if args.command == "prompt":
        rendered = render_prompt(project, args.stage, args.model, mode=args.mode)
        if args.turn:
            if args.turn < 1 or args.turn > len(rendered.turns):
                raise RRGError(f"turn must be between 1 and {len(rendered.turns)}")
            text = rendered.turns[args.turn - 1].text
        else:
            blocks = [f"## Turn {index} — {turn.title}\n\n{turn.text}" for index, turn in enumerate(rendered.turns, 1)]
            if args.include_reminders and rendered.reminders:
                blocks.append(f"## Operator reminders\n\n{rendered.reminders}")
            text = "\n\n".join(blocks) + "\n"
        if args.json:
            _emit(
                {
                    "stage": rendered.stage,
                    "model": rendered.model,
                    "output_folder": rendered.output_folder,
                    "report_name": rendered.report_name,
                    "turns": [{"title": turn.title, "text": turn.text} for turn in rendered.turns],
                    "reminders": rendered.reminders if args.include_reminders else None,
                },
                True,
            )
        else:
            print(text, end="")
        return 0
    if args.command == "scorecard":
        result = build_scorecard(
            project,
            project.path(args.run),
            args.stage,
            args.model,
            key_dir=project.path(args.key) if args.key else None,
            map_path=project.path(args.map) if args.map else None,
            output_dir=project.path(args.out_dir) if args.out_dir else None,
            license_name=args.license,
        )
        _emit(result, args.json)
        return 0
    if args.command == "intake":
        from .origin import intake_prompt, save_intake

        if args.check:
            from .origin import check_intake_needed
            result = check_intake_needed(project)
            if args.json:
                _emit(result, True)
            else:
                if result["needed"]:
                    print(f"Intake needed: {result['reason']}")
                else:
                    print(f"Intake not needed: {result['reason']}")
            return 0
        if args.apply:
            text = project.path(args.apply).read_text(encoding="utf-8", errors="ignore")
            result = save_intake(project, text)
            if args.json:
                _emit(result, True)
            else:
                lines = [f"Wrote {result['summary_written']}"]
                if result["figure_map_written"]:
                    lines.append(f"Wrote {result['figure_map_written']}")
                for figure in result["figures"]:
                    lines.append(f"  fig Q{figure['question']}: {figure['status']}")
                for warning in result["warnings"]:
                    lines.append(f"  ⚠ Q{warning['question']}: {warning['reason']} ({warning['text']})")
                print("\n".join(lines))
            return 0
        rendered = intake_prompt(project)
        if args.json:
            _emit(rendered, True)
        else:
            print(rendered["text"])
        return 0
    if args.command == "prefs":
        from .prefs import load_prefs, save_prefs, reset_prefs, DEFAULTS
        if args.reset:
            reset_prefs(project)
            _emit({"prefs": dict(DEFAULTS)}, args.json) if args.json else print("Reset to defaults.")
            return 0
        if args.set:
            for item in args.set:
                if "=" not in item:
                    raise RRGError(f"invalid --set value (expected KEY=VALUE): {item}")
                key, value = item.split("=", 1)
                key = key.strip()
                if key in ("skip_normalize", "auto_import"):
                    value = value.lower() in ("true", "yes", "1")
                save_prefs(project, {key: value})
            prefs = load_prefs(project)
            _emit({"prefs": prefs}, args.json) if args.json else print("Saved.")
            return 0
        prefs = load_prefs(project)
        if args.json:
            _emit({"prefs": prefs}, True)
        else:
            print("RRG Preferences:")
            for key, value in prefs.items():
                print(f"  {key}: {value}")
        return 0
    if args.command == "dispatch":
        from .dispatch import dispatch
        result = dispatch(
            project, args.stage, args.model,
            executor=args.executor, mode=args.mode, label=args.label,
            dry_run=args.dry_run, reuse=args.reuse,
            skip_normalize=args.skip_normalize or None,
            auto_import=None if not args.no_auto_import else False,
            force=args.force,
        )
        if args.json:
            _emit(result, True)
        else:
            _print_dispatch_result(result)
        return 2 if result["package"].get("blocked") else 0
    if args.command == "wizard":
        from .wizard import run_wizard
        result = run_wizard(project, non_interactive=args.non_interactive,
                            step=args.step, prefs_editor=args.prefs)
        if args.json:
            _emit(result, True)
        return 0
    if args.command == "eval":
        from .eval_lite import eval_run
        run_path = project.path(args.run)
        result = eval_run(project, run_path)
        if args.json:
            _emit(result, True)
        else:
            print(result["report"])
        return 0
    if args.command == "tui":
        from .tui import run_tui, run_tui_prefs, run_tui_eval
        if args.prefs:
            run_tui_prefs(project)
        elif args.eval:
            run_tui_eval(project, args.eval)
        else:
            run_tui(project, step=args.step)
        return 0
    if args.command == "gui":
        serve(project, args.port, open_browser=args.open)
        return 0
    raise RRGError(f"unknown command: {args.command}")


def _print_dispatch_result(result):
    pkg = result["package"]
    model_prov = result.get("model_provenance", "")
    model_str = f" [{model_prov}]" if model_prov else ""
    print(f"RRG Dispatch \u2014 {result.get('mode', 'discuss')} mode, {result['executor']} executor{model_str}")
    if pkg.get("blocked"):
        print("  \u2717 Package blocked by blinding lint")
        return
    print(f"  Run ID: {pkg.get('run_id', '\u2014')}")
    if result.get("zip_path") and Path(result["zip_path"]).exists():
        print(f"  Package zip: {result['zip_path']}")
    prompt = result.get("prompt")
    if prompt:
        print(f"  Prompt: {len(prompt['turns'])} turn(s)")
        for i, t in enumerate(prompt["turns"], 1):
            print(f"    Turn {i} \u2014 {t['title']}")
    if result.get("conversation"):
        print(f"  Conversation: {len(result['conversation'])} exchange(s)")
    if result.get("import_result"):
        imp = result["import_result"]
        print(f"  Imported: {imp['count']} files into {imp['run']}")
        breach = imp.get("breach", {})
        if breach.get("copied_secrets"):
            print(f"  \u26a0 BLINDING BREACH: {len(breach['copied_secrets'])} file(s) match the answer key")
        if imp.get("normalize"):
            norm = imp["normalize"]
            if norm.get("files_moved"):
                print(f"  Normalized: {len(norm['files_moved'])} file(s) renamed")
            if norm.get("summary_json_created"):
                qs = ", ".join(f"Q{q}" for q in norm["summary_json_created"])
                print(f"  Normalized: created summary.json for {qs}")
            if norm.get("missing"):
                qs = ", ".join(f"Q{q}" for q in norm["missing"])
                print(f"  \u26a0 Missing: {qs}")
    elif result.get("instructions"):
        print()
        print(result["instructions"])


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        return run(parser.parse_args(argv))
    except RRGError as exc:
        parser.exit(1, f"rrg: error: {exc}\n")
    except KeyboardInterrupt:
        return 130
    return 1


if __name__ == "__main__":
    sys.exit(main())
