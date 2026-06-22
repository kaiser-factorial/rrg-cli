import base64
import json
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
import yaml

from rrg_cli.gui import make_handler, status
from rrg_cli.gui_service import GUIState
from rrg_cli.project import Project
from rrg_cli.converter import convert_dataset
from rrg_cli.errors import RRGError
from rrg_cli.scaffold import init_project
from rrg_cli.scorecard import build_scorecard, load_question_map
from rrg_cli.workspace import WorkspaceState, discover_project_roots


def test_scorecard_is_provisional_and_versioned(ready_project):
    run = ready_project.root / "operator/robustness_TestModel"
    raw = run / "raw"
    raw.mkdir(parents=True)
    key = ready_project.root / "operator/origin"
    for question in range(1, 4):
        (raw / f"Q{question}_summary.json").write_text(json.dumps({"estimate": question / 10}))
        (key / f"Q{question}.md").write_text(f"## Q{question}\nHeld-back finding {question}")
    first = build_scorecard(ready_project, run, "robustness", "TestModel")
    second = build_scorecard(ready_project, run, "robustness", "TestModel")
    text = Path(first["path"]).read_text()
    assert first["version"] == 1 and second["version"] == 2
    assert first["final_verdicts"] == 0
    assert text.count("**PENDING**") == 3
    assert "Held-back finding" in text


def test_question_map_accepts_current_and_legacy_keys(tmp_path: Path):
    path = tmp_path / "map.yaml"
    path.write_text(yaml.safe_dump({"questions": [{"n": 4, "orig": 9, "topic": "Legacy"}]}))
    assert load_question_map(path) == [{"new": 4, "original": 9, "topic": "Legacy"}]


def _serve(project, token="test-token", workspace=None):
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        make_handler(project, token=token, workspace=workspace),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _get(server, path, token="test-token"):
    request = Request(
        f"http://127.0.0.1:{server.server_port}{path}",
        headers={"X-RRG-Token": token},
    )
    with urlopen(request) as response:
        return response.status, response.headers, response.read()


def _post(server, path, payload, token="test-token", origin=None):
    headers={"Content-Type": "application/json", "X-RRG-Token": token}
    if origin:
        headers["Origin"] = origin
    request = Request(
        f"http://127.0.0.1:{server.server_port}{path}",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    with urlopen(request) as response:
        return response.status, json.loads(response.read())


def test_gui_assets_status_and_authenticated_api(ready_project):
    payload = status(ready_project)
    assert payload["project"] == "starter-validation"
    assert [stage["id"] for stage in payload["stages"]] == ["replication", "robustness", "generalization"]
    server = _serve(ready_project)
    try:
        status_code, headers, body = _get(server, "/")
        assert status_code == 200 and b"__RRG_TOKEN__" not in body and b"RRG validation pipeline" in body
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
        assert _get(server, "/assets/app.js")[0] == 200
        code, _headers, body = _get(server, "/api/bootstrap")
        data = json.loads(body)
        assert code == 200 and data["preflight"]["ok"]
        assert data["workspace"]["enabled"] is False
        with pytest.raises(HTTPError) as error:
            urlopen(f"http://127.0.0.1:{server.server_port}/api/bootstrap")
        assert error.value.code == 403
    finally:
        server.shutdown()
        server.server_close()


def _ready_workspace_project(root: Path) -> Project:
    init_project(root)
    convert_dataset(root / "data/source.csv", root / "data/analysis")
    return Project.load(root)


def test_workspace_discovers_switches_and_creates_confined_projects(tmp_path: Path):
    workspace = tmp_path / "workspace"
    first = _ready_workspace_project(workspace / "first")
    second = _ready_workspace_project(workspace / "demos/second")
    ignored = first.root / "operator/nested"
    ignored.mkdir(parents=True)
    (ignored / ".rrg_root").touch()

    assert discover_project_roots(workspace) == [first.root, second.root]
    state = WorkspaceState(first, workspace)
    assert state.bootstrap()["workspace"]["active"] == "first"
    assert state.select_project("demos/second")["root"] == str(second.root)

    created = state.create_project("demos/third", "Third study")
    assert created["project"] == "Third study"
    assert created["workspace"]["active"] == "demos/third"
    assert (workspace / "demos/third/.rrg_root").is_file()
    with pytest.raises(RRGError, match="workspace-relative"):
        state.create_project("../escape", "Escape")


def test_workspace_http_api_switches_and_creates_projects(tmp_path: Path):
    workspace = tmp_path / "workspace"
    first = _ready_workspace_project(workspace / "first")
    second = _ready_workspace_project(workspace / "second")
    server = _serve(first, workspace=str(workspace))
    try:
        _code, _headers, body = _get(server, "/api/bootstrap")
        bootstrap = json.loads(body)
        assert bootstrap["workspace"]["enabled"] is True
        assert {item["root"] for item in bootstrap["workspace"]["projects"]} == {"first", "second"}

        code, selected = _post(server, "/api/project/select", {"root": "second"})
        assert code == 200 and selected["root"] == str(second.root)

        code, created = _post(
            server,
            "/api/project/create",
            {"path": "demos/new-project", "name": "New project"},
        )
        assert code == 200 and created["project"] == "New project"
        assert created["workspace"]["active"] == "demos/new-project"

        with pytest.raises(HTTPError) as error:
            _post(server, "/api/project/select", {"root": "../outside"})
        assert error.value.code == 400
    finally:
        server.shutdown()
        server.server_close()


def test_gui_rejects_cross_origin_writes_and_path_escape(ready_project):
    server = _serve(ready_project)
    try:
        with pytest.raises(HTTPError) as error:
            _post(
                server,
                "/api/package",
                {"stage": "replication", "model": "ReplicationModel", "dry_run": True},
                origin="https://malicious.example",
            )
        assert error.value.code == 403
        with pytest.raises(HTTPError) as error:
            _get(server, "/api/run?run=operator/origin")
        assert error.value.code == 400
    finally:
        server.shutdown()
        server.server_close()


def test_gui_convert_package_prompt_and_scorecard_endpoints(project_root):
    project = Project.load(project_root)
    server = _serve(project)
    try:
        code, converted = _post(server, "/api/convert", {"formats": ["csv", "parquet"]})
        assert code == 200 and converted["all_verified"]
        code, package = _post(
            server,
            "/api/package",
            {"stage": "replication", "model": "ReplicationModel", "dry_run": True},
        )
        assert code == 200 and not package["blocked"] and not package["published"]
        _code, _headers, prompt_body = _get(
            server,
            "/api/prompt?stage=robustness&model=RobustnessModel&mode=nodiscuss",
        )
        prompt = json.loads(prompt_body)
        assert prompt["turns"] and "original method" in prompt["turns"][0]["text"].lower()

        run = project_root / "operator/robustness_RobustnessModel/raw"
        run.mkdir(parents=True)
        for question in range(1, 4):
            (run / f"Q{question}_summary.json").write_text(json.dumps({"estimate": question}))
            (project_root / f"operator/origin/Q{question}.md").write_text(f"## Q{question}\nkey")
        code, scorecard = _post(
            server,
            "/api/scorecard",
            {"run": "operator/robustness_RobustnessModel", "stage": "robustness", "model": "RobustnessModel"},
        )
        assert code == 200 and scorecard["final_verdicts"] == 0
    finally:
        server.shutdown()
        server.server_close()


def test_gui_setup_preserves_unknown_fields_and_supports_arbitrary_cartridge(ready_project):
    study_path = ready_project.study_path
    raw = yaml.safe_load(study_path.read_text())
    raw["study"]["custom_extension"] = {"keep": "yes"}
    raw["study"]["questions"]["count"] = 2
    raw["study"]["questions"]["map"] = "questions_map.yaml"
    study_path.write_text(yaml.safe_dump(raw, sort_keys=False))
    map_path = ready_project.root / "questions_map.yaml"
    map_path.write_text(yaml.safe_dump({"questions": [{"new": 1, "topic": "Alpha"}, {"new": 2, "topic": "Beta"}]}))
    config_path = ready_project.config_path
    config = yaml.safe_load(config_path.read_text())
    config["stages"]["followup"] = {
        "order": 4,
        "enabled": False,
        "blocked_reason": "optional follow-up",
        "prompt": "prompts/generalization.md",
        "send": ["all"],
    }
    config["roster"]["followup"] = []
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    state = GUIState(Project.load(ready_project.root))
    result = state.save_setup(
        {
            "study": {"title": "Different lab", "dataset": {"merge_key": "participant"}},
            "engine": {
                "project_name": "different-validation",
                "stages": [{"id": "generalization", "enabled": False, "blocked_reason": "new sample pending"}],
            },
        }
    )
    saved = yaml.safe_load(study_path.read_text())["study"]
    assert saved["custom_extension"] == {"keep": "yes"}
    assert saved["dataset"]["merge_key"] == "participant"
    assert result["project"] == "different-validation"
    assert [question["topic"] for question in result["questions"]] == ["Alpha", "Beta"]
    assert next(stage for stage in result["stages"] if stage["id"] == "generalization")["blocked_reason"] == "new sample pending"
    assert [stage["id"] for stage in result["stages"]] == [
        "replication",
        "robustness",
        "generalization",
        "followup",
    ]


def test_runs_compare_and_notes_exclude_withheld_key(ready_project):
    state = GUIState(ready_project)
    run = ready_project.root / "operator/robustness_TestModel"
    run.mkdir()
    (run / "SUMMARY.md").write_text("## Q1\nvalidator")
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
    (run / "Q1_figure.png").write_bytes(png)
    key = ready_project.root / "operator/origin"
    (key / "Q1_figure.png").write_bytes(png)
    paths = {item["path"] for item in state.runs()}
    assert "operator/robustness_TestModel" in paths
    assert "operator/origin" not in paths
    comparison = state.compare("operator/robustness_TestModel", 1)
    assert len(comparison["validator"]) == len(comparison["original"]) == 1
    state.save_note("operator/robustness_TestModel", 1, "Check axis labels")
    assert state.compare("operator/robustness_TestModel", 1)["note"] == "Check axis labels"
