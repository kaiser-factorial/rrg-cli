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
    importer.add_argument("--stage", required=True)
    importer.add_argument("--model", required=True)
    importer.add_argument("--label")
    importer.add_argument("--json", action="store_true")

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
    intake.add_argument("--json", action="store_true")

    gui = sub.add_parser("gui", help="launch the local status GUI")
    _add_project_args(gui)
    gui.add_argument("--workspace", help="enable safe switching among projects below this directory")
    gui.add_argument("--port", type=int, default=8765)
    gui.add_argument("--open", action="store_true")

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
        result = import_run(project, args.stage, args.model, args.source, label=args.label)
        _emit(result if args.json else f"Imported {result['count']} files into {result['run']}", args.json)
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
    if args.command == "gui":
        serve(project, args.port, open_browser=args.open)
        return 0
    raise RRGError(f"unknown command: {args.command}")


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
