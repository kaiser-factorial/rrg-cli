from __future__ import annotations

from pathlib import Path

import pytest

from rrg_cli.errors import RRGError
from rrg_cli.gui_service import GUIState
from rrg_cli.project import Project
from rrg_cli.scaffold import init_project

RUN = "operator/replication_RunModel"


def _graded_project(root: Path) -> Project:
    init_project(root)
    origin = root / "operator/origin"
    origin.mkdir(parents=True, exist_ok=True)
    (origin / "SUMMARY.md").write_text(
        "## Q1 - a\nMethod a.\n\n## Q2 - b\nMethod b.\n\n## Q3 - c\nMethod c.\n", encoding="utf-8"
    )
    run = root / RUN
    run.mkdir(parents=True, exist_ok=True)
    (run / "SUMMARY.md").write_text("## Q1\nv1\n\n## Q2\nv2\n\n## Q3\nv3\n", encoding="utf-8")
    return Project.load(root)


def test_grading_requires_confirmed_verdicts_for_all_questions(tmp_path: Path):
    project = _graded_project(tmp_path / "study")
    state = GUIState(project)

    overview = state.grading_overview(RUN)
    assert overview["total"] == 3 and overview["confirmed"] == 0
    assert overview["graded"] is False and overview["returned"] is True
    assert not any(run["path"] == RUN and run["graded"] for run in state.runs())

    state.save_verdict(RUN, 1, "REPRODUCED", "matches", True)
    state.save_verdict(RUN, 2, "DIVERGED", "", True)
    partial = state.grading_overview(RUN)
    assert partial["confirmed"] == 2 and partial["graded"] is False

    final = state.save_verdict(RUN, 3, "CONVERGED", "", True)
    assert final["graded"] is True
    assert any(run["path"] == RUN and run["graded"] for run in state.runs())


def test_generating_scaffold_does_not_mark_graded(tmp_path: Path):
    project = _graded_project(tmp_path / "study")
    state = GUIState(project)
    state.make_scorecard({"run": RUN, "stage": "replication", "model": "RunModel"})
    assert not any(run["path"] == RUN and run["graded"] for run in state.runs())


def test_cannot_grade_an_unreturned_run(tmp_path: Path):
    project = _graded_project(tmp_path / "study")
    (project.root / "operator/replication_Empty").mkdir(parents=True, exist_ok=True)
    state = GUIState(project)
    with pytest.raises(RRGError, match="not returned|nothing to grade"):
        state.save_verdict("operator/replication_Empty", 1, "REPRODUCED", "", True)


def test_finalize_exports_scorecard_and_protects_it(tmp_path: Path):
    project = _graded_project(tmp_path / "study")
    state = GUIState(project)
    for question in (1, 2, 3):
        state.save_verdict(RUN, question, "REPRODUCED", "", True)

    result = state.finalize_grading(RUN)
    card = result["grading"]["scorecard"]
    assert result["grading"]["finalized"] is True
    text = (project.root / card).read_text(encoding="utf-8")
    assert "REPRODUCED" in text and "PROVISIONAL" not in text
    assert any(item["path"] == card and item["protected"] for item in state.scorecards())

    with pytest.raises(RRGError, match="finalized"):
        state.delete_scorecard(card)

    state.reopen_grading(RUN)
    assert any(item["path"] == card and not item["protected"] for item in state.scorecards())
    state.delete_scorecard(card)
    assert not (project.root / card).is_file()


def test_grading_http_endpoints(tmp_path: Path):
    import json
    import threading
    from http.client import HTTPConnection
    from http.server import ThreadingHTTPServer

    from rrg_cli.gui import make_handler

    project = _graded_project(tmp_path / "study")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(project, token="t"))
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def call(method, path, body=None):
        conn = HTTPConnection("127.0.0.1", server.server_port)
        payload = json.dumps(body).encode() if body is not None else None
        headers = {"X-RRG-Token": "t"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        data = json.loads(response.read())
        conn.close()
        return response.status, data

    try:
        status, overview = call("GET", f"/api/grading?run={RUN}")
        assert status == 200 and overview["total"] == 3 and overview["graded"] is False

        for question in (1, 2, 3):
            status, result = call(
                "POST",
                "/api/grading/verdict",
                {"run": RUN, "question": question, "verdict": "REPRODUCED", "note": "", "confirmed": True},
            )
            assert status == 200
        assert result["graded"] is True

        status, finalized = call("POST", "/api/grading/finalize", {"run": RUN})
        assert status == 200 and finalized["grading"]["finalized"] is True
    finally:
        server.shutdown()
        server.server_close()


def test_delete_grading_blocked_while_finalized(tmp_path: Path):
    project = _graded_project(tmp_path / "study")
    state = GUIState(project)
    for question in (1, 2, 3):
        state.save_verdict(RUN, question, "REPRODUCED", "", True)
    state.finalize_grading(RUN)
    with pytest.raises(RRGError, match="finalized"):
        state.delete_grading(RUN)
    state.reopen_grading(RUN)
    state.delete_grading(RUN)
    assert state.grading_overview(RUN)["confirmed"] == 0
