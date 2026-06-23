from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from pathlib import Path

import pytest

from rrg_cli import origin
from rrg_cli.errors import RRGError
from rrg_cli.gui import make_handler
from rrg_cli.project import Project
from rrg_cli.scaffold import init_project

QUESTIONS = """# Validation questions

1. How was the analysis sample constructed?
2. What is the primary association between `x` and `y`?
3. Does the conclusion survive a defensible robustness check?
"""

PROTOCOL = """# Original analysis protocol

Methods only; revealed in replication.

1. Report the number of complete rows.
2. Estimate the Pearson correlation between `x` and `y`.
3. Repeat with Spearman correlation as the fixed robustness check.
"""

# Origin summary intentionally omits Q3 to exercise a separation gap.
SUMMARY = """# Held-back origin summary

## Q1 - Sample construction

Method: drop incomplete rows. Finding: 180 complete rows.

## Q2 - Primary association

Method: Pearson correlation of x and y. Finding: r = 0.42.
"""


def _origin_project(root: Path) -> Project:
    init_project(root)
    (root / "shared/QUESTIONS.md").write_text(QUESTIONS, encoding="utf-8")
    (root / "shared/ANALYSIS_PROTOCOL_OG.md").write_text(PROTOCOL, encoding="utf-8")
    (root / "operator/origin").mkdir(parents=True, exist_ok=True)
    (root / "operator/origin/SUMMARY.md").write_text(SUMMARY, encoding="utf-8")
    (root / "operator/origin/ORIGIN_REPORT.pdf").write_bytes(b"%PDF-1.4\n1 0 obj<<>>endobj\n%%EOF\n")
    return Project.load(root)


def test_parse_numbered_handles_continuations():
    parsed = origin.parse_numbered("1. first line\n   still first\n2. second\n\ntrailing prose")
    assert parsed == {1: "first line still first", 2: "second"}


def test_origin_overview_flags_missing_separation(tmp_path: Path):
    project = _origin_project(tmp_path / "study")
    overview = origin.origin_overview(project)

    assert overview["counts"]["total"] == 3
    assert overview["counts"]["missing_origin"] == [3]
    assert overview["ok"] is False

    by_q = {row["new"]: row for row in overview["rows"]}
    assert by_q[1]["ok"] and by_q[1]["has_question"] and by_q[1]["has_origin"]
    assert "Pearson" in by_q[2]["origin"]
    assert by_q[3]["has_question"] and by_q[3]["has_protocol"]
    assert by_q[3]["has_origin"] is False and by_q[3]["ok"] is False
    assert overview["report"]["name"] == "ORIGIN_REPORT.pdf"


def test_origin_overview_all_separated(tmp_path: Path):
    project = _origin_project(tmp_path / "study")
    (project.root / "operator/origin/SUMMARY.md").write_text(
        SUMMARY + "\n## Q3 - Robustness check\n\nMethod: Spearman correlation.\n",
        encoding="utf-8",
    )
    overview = origin.origin_overview(Project.load(project.root))
    assert overview["ok"] is True
    assert overview["counts"]["ok"] == 3


def test_methodology_prompt_renders_result_free(tmp_path: Path):
    project = _origin_project(tmp_path / "study")
    prompt = origin.methodology_prompt(project)
    text = prompt["text"]
    assert "result-free" in text
    assert "ORIGIN_REPORT.pdf" in text
    assert "ANALYSIS_PROTOCOL_OG.md" in text
    assert "primary association" in text  # question list injected
    assert "{" not in text  # no unresolved placeholders for the tokens we use
    assert prompt["target"] == "shared/ANALYSIS_PROTOCOL_OG.md"


def test_save_methodology_writes_and_flags_leaks(tmp_path: Path):
    project = _origin_project(tmp_path / "study")
    leaky = origin.save_methodology(project, "# Protocol\n\n1. Run a t-test (p = 0.001) and conclude an effect.\n")
    assert leaky["written"] == "shared/ANALYSIS_PROTOCOL_OG.md"
    reasons = {item["reason"] for item in leaky["warnings"]}
    assert "p-value" in reasons
    assert (project.root / "shared/ANALYSIS_PROTOCOL_OG.md").read_text(encoding="utf-8").startswith("# Protocol")

    clean = origin.save_methodology(project, "# Protocol\n\n1. Drop incomplete rows and count them.\n")
    assert clean["warnings"] == []

    with pytest.raises(RRGError):
        origin.save_methodology(project, "   ")


# --- HTTP surface ---------------------------------------------------------


def _serve(project):
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(project, token="test-token"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _request(server, method, path, body=None):
    conn = HTTPConnection("127.0.0.1", server.server_port)
    payload = json.dumps(body).encode() if body is not None else None
    headers = {"X-RRG-Token": "test-token"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=payload, headers=headers)
    response = conn.getresponse()
    data = json.loads(response.read())
    conn.close()
    return response.status, data


def test_origin_http_endpoints(tmp_path: Path):
    project = _origin_project(tmp_path / "study")
    server = _serve(project)
    try:
        status, overview = _request(server, "GET", "/api/origin")
        assert status == 200 and overview["counts"]["missing_origin"] == [3]

        status, report = _request(server, "GET", "/api/origin/report")
        assert status == 200 and report["kind"] == "pdf"
        assert report["name"] == "ORIGIN_REPORT.pdf" and "data_url" not in report

        status, prompt = _request(server, "GET", "/api/origin/methodology_prompt")
        assert status == 200 and "result-free" in prompt["text"]

        status, saved = _request(
            server,
            "POST",
            "/api/origin/methodology",
            {"text": "# Protocol\n\n1. Drop incomplete rows.\n"},
        )
        assert status == 200 and saved["written"] == "shared/ANALYSIS_PROTOCOL_OG.md"
        assert saved["origin"]["protocol"]["exists"] is True
    finally:
        server.shutdown()
        server.server_close()


def test_setup_persists_roster_and_model_slugs(tmp_path: Path):
    import yaml

    from rrg_cli.gui_service import GUIState

    project = _origin_project(tmp_path / "study")
    state = GUIState(project)
    result = state.save_setup(
        {
            "engine": {
                "roster": {
                    "replication": [
                        {"model": "Gemini", "vendor": "Google", "type": "frontier", "license": "proprietary"}
                    ],
                    "robustness": [],
                },
                "model_slugs": {"Gemini": "google/gemini"},
            }
        }
    )
    replication = next(stage for stage in result["stages"] if stage["id"] == "replication")
    assert [model["model"] for model in replication["models"]] == ["Gemini"]
    assert result["dispatch_slugs"]["Gemini"] == "google/gemini"

    config = yaml.safe_load((project.root / "rrg.yaml").read_text(encoding="utf-8"))
    assert config["roster"]["replication"][0]["vendor"] == "Google"
    assert config["dispatch"]["model_slugs"]["Gemini"] == "google/gemini"


def _raw_get(server, path, token="test-token"):
    conn = HTTPConnection("127.0.0.1", server.server_port)
    conn.request("GET", path, headers={"X-RRG-Token": token} if token else {})
    response = conn.getresponse()
    body = response.read()
    content_type = response.getheader("Content-Type")
    conn.close()
    return response.status, content_type, body


def test_origin_report_pdf_stream_accepts_query_token(tmp_path: Path):
    project = _origin_project(tmp_path / "study")
    server = _serve(project)
    try:
        status, content_type, body = _raw_get(server, "/api/origin/report.pdf?token=test-token", token=None)
        assert status == 200 and content_type == "application/pdf" and body.startswith(b"%PDF")

        status, _content_type, _body = _raw_get(server, "/api/origin/report.pdf?token=wrong", token=None)
        assert status == 403
    finally:
        server.shutdown()
        server.server_close()
