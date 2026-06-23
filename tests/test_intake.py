from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from pathlib import Path

import pytest
import yaml

from rrg_cli import origin
from rrg_cli.errors import RRGError
from rrg_cli.gui import make_handler
from rrg_cli.gui_service import GUIState
from rrg_cli.project import Project
from rrg_cli.scaffold import init_project

QUESTIONS = """# Validation questions

1. How was the analysis sample constructed?
2. What is the primary association between `x` and `y`?
3. Does the conclusion survive a defensible robustness check?
"""

# Origin summary keyed by ORIGINAL question number (## Q<original>).
SUMMARY = """# Held-back origin summary

## Q1 - Sample construction

Method: drop incomplete rows. Finding: 180 complete rows.

## Q2 - Primary association

Method: Pearson correlation of x and y. Finding: r = 0.42.
"""


def _origin_project(root: Path) -> Project:
    init_project(root)
    (root / "shared/QUESTIONS.md").write_text(QUESTIONS, encoding="utf-8")
    (root / "operator/origin").mkdir(parents=True, exist_ok=True)
    (root / "operator/origin/SUMMARY.md").write_text(SUMMARY, encoding="utf-8")
    (root / "operator/origin/ORIGIN_REPORT.pdf").write_bytes(b"%PDF-1.4\n1 0 obj<<>>endobj\n%%EOF\n")
    return Project.load(root)


# --- split_intake ---------------------------------------------------------


def test_split_intake_separates_summary_and_figure_map():
    text = (
        "## Q1 - A\n\n- p_value: 0.01\n\n"
        "### 2. Figure manifest\n\n"
        "```yaml\nfigure_map:\n  - {question: 1, report_label: \"Figure 1\", canonical: \"Q1_fig.png\"}\n```\n"
    )
    summary, yaml_text = origin.split_intake(text)
    assert summary.startswith("## Q1 - A")
    assert "figure manifest" not in summary.lower()  # trailing section heading stripped
    assert summary.strip().endswith("- p_value: 0.01")
    parsed = yaml.safe_load(yaml_text)
    assert parsed["figure_map"][0]["canonical"] == "Q1_fig.png"


def test_split_intake_without_fence_returns_empty_map():
    summary, yaml_text = origin.split_intake("## Q1 - A\n\n- p_value: 0.01\n")
    assert summary.strip().endswith("0.01")
    assert yaml_text == ""


# --- intake_prompt --------------------------------------------------------


def test_intake_prompt_renders_with_summary_token(tmp_path: Path):
    project = _origin_project(tmp_path / "study")
    prompt = origin.intake_prompt(project)
    text = prompt["text"]
    assert prompt["target"] == "operator/origin/SUMMARY.md"
    assert prompt["origin_report"] == "ORIGIN_REPORT.pdf"
    assert "SUMMARY.md" in text  # SUMMARY_FILE token resolved
    assert "transcription" in text.lower()
    import re as _re

    # No unresolved {UPPERCASE} placeholders (lowercase braces appear in the YAML example).
    assert not _re.findall(r"\{[A-Z][A-Z0-9_]*\}", text)


def test_intake_prompt_lists_questions_by_original_number(tmp_path: Path):
    project = _origin_project(tmp_path / "study")
    # Non-identity map: the origin SUMMARY is consumed by ORIGINAL number, so the
    # prompt must present questions and request sections in original numbering.
    (project.root / "questions_map.yaml").write_text(
        yaml.safe_dump(
            {"questions": [{"new": 1, "original": 5, "topic": "A"}, {"new": 2, "original": 3, "topic": "B"}]}
        ),
        encoding="utf-8",
    )
    (project.root / "shared/QUESTIONS.md").write_text(
        "# Questions\n\n1. First question text\n2. Second question text\n", encoding="utf-8"
    )
    text = origin.intake_prompt(Project.load(project.root))["text"]
    # Original numbering, sorted ascending: 3 (new 2) before 5 (new 1).
    assert "3. Second question text" in text
    assert "5. First question text" in text
    assert text.index("3. Second question text") < text.index("5. First question text")


# --- save_intake ----------------------------------------------------------

INTAKE_RETURN = """## Q1 - Sample construction

- question: How was the analysis sample constructed?
- n: 180
- groups: complete cases
- test: count of complete rows
- statistic: count = 180
- p_value: not reported
- effect_size: null
- multiplicity: null
- conclusion: 180 complete rows analyzed.

## Q2 - Primary association

- question: What is the primary association?
- n: 180
- test: Pearson correlation
- statistic: r = 0.42
- conclusion: Positive association.

### 2. Figure manifest

```yaml
figure_map:
  - {question: 1, report_label: "Figure 1", canonical: "Q1_fig.png"}
  - {question: 2, report_label: "Appendix C", canonical: "Q2_fig.png"}
```
"""


def test_save_intake_writes_summary_and_renames_figures(tmp_path: Path):
    project = _origin_project(tmp_path / "study")
    # A source figure file the manifest can match by label ("Figure 1" -> figure_1).
    (project.root / "operator/origin/figure_1.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    result = origin.save_intake(project, INTAKE_RETURN)

    assert result["summary_written"] == "operator/origin/SUMMARY.md"
    assert result["figure_map_written"] == "operator/origin/figure_map.yaml"
    summary_text = (project.root / "operator/origin/SUMMARY.md").read_text(encoding="utf-8")
    assert summary_text.startswith("## Q1 - Sample construction")
    assert "figure manifest" not in summary_text.lower()

    by_q = {figure["question"]: figure for figure in result["figures"]}
    assert by_q[1]["status"] == "renamed"
    assert (project.root / "operator/origin/Q1_fig.png").is_file()
    assert by_q[2]["status"].startswith("no source file")  # Appendix C lives only in the PDF


def test_save_intake_flags_missing_fields_and_sections(tmp_path: Path):
    project = _origin_project(tmp_path / "study")  # identity map of 3 questions
    result = origin.save_intake(project, INTAKE_RETURN)  # Q2 lacks p_value; Q3 absent
    by_q = {warning["question"]: warning for warning in result["warnings"]}
    assert by_q[2]["reason"] == "missing fields" and "p_value" in by_q[2]["text"]
    assert by_q[3]["reason"] == "missing section"


def test_save_intake_rejects_empty(tmp_path: Path):
    project = _origin_project(tmp_path / "study")
    with pytest.raises(RRGError):
        origin.save_intake(project, "   ")


# --- cross_run_overview ---------------------------------------------------


def _returned_run(project: Project) -> None:
    raw = project.root / "operator/replication_ModelX/raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "Q1_summary.json").write_text(json.dumps({"p_value": 0.5}), encoding="utf-8")
    (raw / "Q2_summary.json").write_text(json.dumps({"p_value": 0.42}), encoding="utf-8")
    # Q3 deliberately has no summary.json.


def test_cross_run_overview_matrix(tmp_path: Path):
    project = _origin_project(tmp_path / "study")
    _returned_run(project)
    overview = GUIState(project).cross_run_overview()

    assert [run["model"] for run in overview["runs"]] == ["replication_ModelX"]
    rows = {row["new"]: row for row in overview["rows"]}
    assert len(rows) == 3

    # Q2's p-value (0.42) appears in the origin summary -> match.
    q2 = rows[2]["cells"][0]
    assert q2["has_stats"] and q2["in_origin"] and q2["value"] == "0.42"
    assert q2["origin_value"] == "0.42"
    assert rows[2]["origin_value"] == "0.42"
    assert rows[2]["agreement"] == "1/1"

    # Q1's value is not present in the origin -> no match.
    q1 = rows[1]["cells"][0]
    assert q1["has_stats"] and q1["in_origin"] is False and q1["value"] == "0.5"
    assert rows[1]["agreement"] == "0/1"

    # Q3 has no machine-readable stats.
    assert rows[3]["cells"][0]["has_stats"] is False
    assert rows[3]["agreement"] == "—"


def test_headline_stat_prefers_p_value():
    pick = GUIState._headline_stat(
        [
            {"label": "n", "value": 180, "in_origin": False, "origin_value": ""},
            {"label": "top_p", "value": 0.02, "in_origin": True, "origin_value": "0.02"},
        ]
    )
    assert pick["label"] == "top_p"  # nested/suffix p beats a non-p value
    assert GUIState._headline_stat([]) is None


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


def test_intake_http_endpoints(tmp_path: Path):
    project = _origin_project(tmp_path / "study")
    server = _serve(project)
    try:
        status, prompt = _request(server, "GET", "/api/origin/intake_prompt")
        assert status == 200 and "transcription" in prompt["text"].lower()
        assert prompt["target"] == "operator/origin/SUMMARY.md"

        status, saved = _request(server, "POST", "/api/origin/intake", {"text": INTAKE_RETURN})
        assert status == 200 and saved["summary_written"] == "operator/origin/SUMMARY.md"
        # Saving refreshes the separation overview; Q1/Q2 now have origin sections.
        assert saved["origin"]["summary"]["exists"] is True
    finally:
        server.shutdown()
        server.server_close()


def test_overview_http_endpoint(tmp_path: Path):
    project = _origin_project(tmp_path / "study")
    _returned_run(project)
    server = _serve(project)
    try:
        status, data = _request(server, "GET", "/api/overview")
        assert status == 200
        assert [run["model"] for run in data["runs"]] == ["replication_ModelX"]
        assert len(data["rows"]) == 3
    finally:
        server.shutdown()
        server.server_close()
