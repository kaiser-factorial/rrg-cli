"""Tests for the deterministic deliverable gates and the dispatch revision loop."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from rrg_cli.dispatch import dispatch
from rrg_cli.gates import check_gates, locate_deliverable_root
from rrg_cli.importer import import_run
from rrg_cli.prefs import coerce_pref, save_prefs
from rrg_cli.project import Project

REPORT = "ReplicationModel_Report.md"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _summary(n: int, **overrides) -> dict:
    data = {
        "question": n, "n": 100, "test": "t-test", "statistic": 2.5,
        "p_value": 0.013, "effect_size": 0.3, "conclusion": "Groups differ.",
    }
    data.update(overrides)
    return data


def _write_conforming(root: Path, n_questions: int = 3, report_name: str = REPORT) -> None:
    (root / "raw").mkdir(parents=True, exist_ok=True)
    sections = []
    for n in range(1, n_questions + 1):
        # Real, runnable scripts: the executable gate re-runs Q<n>_fig.py and expects the
        # delivered PNG back.
        (root / f"Q{n}_analysis.py").write_text(
            f"open('raw/Q{n}_raw.csv', 'w').write('a,b\\n1,2\\n')\n"
        )
        (root / f"Q{n}_fig.py").write_text(
            f"open('raw/Q{n}_raw.csv').read()\nopen('Q{n}_fig.png', 'wb').write({PNG!r})\n"
        )
        (root / f"Q{n}_fig.png").write_bytes(PNG)
        (root / "raw" / f"Q{n}_raw.csv").write_text("a,b\n1,2\n")
        summary = _summary(n)
        metric_line = ""
        if (root / "METRIC_SPEC.json").is_file():
            summary["_units"] = {
                "n": "count", "statistic": "1", "p_value": "probability", "effect_size": "1",
            }
            metric_line = (
                f"Metrics: `n=100 count`; `statistic=2.5 1`; `p_value=0.013 probability`; "
                f"`effect_size=0.3 1`\n\n"
            )
        (root / "raw" / f"Q{n}_summary.json").write_text(json.dumps(summary))
        sections.append(
            f"## Question {n}\n\n### D - Do\ntext\n\n### Y - Why\ntext\n\n### F - Find\n"
            f"{metric_line}![Q{n} figure](Q{n}_fig.png)\n\n### A - Answer\ntext\n"
        )
    (root / report_name).write_text("# Report\n\n" + "\n".join(sections))
    (root / "RAW.md").write_text("# Raw index\n")
    (root / "SUMMARY.md").write_text("# Summary\n")


def _codes(result, severity=None):
    items = result.violations if severity is None else getattr(result, severity)
    return sorted({v.code for v in items})


def _write_metric_contract(root: Path) -> None:
    (root / "METRIC_SPEC.json").write_text(json.dumps({
        "schema_version": "rrg.metric-specs.v1",
        "questions": {
            "1": {
                "metrics": [
                    {"id": "component_a", "label": "Component A", "validator_path": "component_a", "kind": "currency", "unit": "USD_billion", "nullable": False},
                    {"id": "component_b", "label": "Component B", "validator_path": "component_b", "kind": "currency", "unit": "USD_billion", "nullable": False},
                    {"id": "component_total", "label": "Component total", "validator_path": "component_total", "kind": "currency", "unit": "USD_billion", "nullable": False},
                    {"id": "bootstrap_p", "label": "Bootstrap p-value", "validator_path": "bootstrap.p", "kind": "p_value", "unit": "probability", "nullable": True},
                ],
                "relations": [
                    {"id": "components_add", "op": "sum_equals", "inputs": ["component_a", "component_b"], "output": "component_total"}
                ],
            }
        },
    }), encoding="utf-8")


def _write_metric_summary(root: Path, *, total: float = 8.2, p_value=0.047) -> None:
    path = root / "raw" / "Q1_summary.json"
    data = _summary(1)
    data.update({
        "component_a": 7.7,
        "component_b": 0.5,
        "component_total": total,
        "bootstrap": {"p": p_value},
        "_units": {
            "component_a": "USD_billion",
            "component_b": "USD_billion",
            "component_total": "USD_billion",
            "bootstrap_p": "probability",
        },
    })
    path.write_text(json.dumps(data), encoding="utf-8")
    report = root / REPORT
    text = report.read_text(encoding="utf-8")
    text = text.replace(
        "### F - Find\n![Q1 figure](Q1_fig.png)",
        "### F - Find\nMetrics: `component_a=7.7 USD_billion`; `component_b=0.5 USD_billion`; "
        f"`component_total={total} USD_billion`; `bootstrap_p={p_value if p_value is not None else 'null'} probability`\n\n"
        "![Q1 figure](Q1_fig.png)",
    )
    report.write_text(text, encoding="utf-8")


# --- Pure gate checks -------------------------------------------------------

def test_conforming_run_passes(tmp_path: Path) -> None:
    _write_conforming(tmp_path)
    result = check_gates(tmp_path, 3, REPORT)
    assert result.passed and not result.violations
    assert result.as_observation()["ok"] is True
    assert result.summary_line().startswith("PASS")


def test_empty_run_reports_every_missing_piece(tmp_path: Path) -> None:
    result = check_gates(tmp_path, 2, REPORT)
    assert not result.passed
    codes = _codes(result, "hard")
    assert codes == ["MISSING_FILE", "MISSING_INDEX", "MISSING_REPORT"]
    # Five files per question, two questions.
    assert sum(1 for v in result.hard if v.code == "MISSING_FILE") == 10
    expected = {v.expected for v in result.hard if v.code == "MISSING_FILE"}
    assert "raw/Q2_summary.json" in expected and "Q1_fig.png" in expected


def test_misnamed_and_misplaced_files_get_the_expected_name(tmp_path: Path) -> None:
    _write_conforming(tmp_path, 1)
    (tmp_path / "Q1_fig.png").rename(tmp_path / "q1_figure.png")
    (tmp_path / "raw" / "Q1_summary.json").rename(tmp_path / "Q1_summary.json")
    result = check_gates(tmp_path, 1, REPORT)
    by_code = {v.code: v for v in result.hard}
    assert by_code["MISNAMED_FILE"].path == "q1_figure.png"
    assert by_code["MISNAMED_FILE"].expected == "Q1_fig.png"
    assert by_code["MISPLACED_FILE"].path == "Q1_summary.json"
    assert by_code["MISPLACED_FILE"].expected == "raw/Q1_summary.json"
    assert "MISSING_FILE" not in by_code


def test_case_only_rename_is_still_misnamed(tmp_path: Path) -> None:
    """On case-insensitive volumes `Q1_fig.py` would match `q1_fig.py`; the gate must not."""
    _write_conforming(tmp_path, 1)
    (tmp_path / "Q1_fig.py").rename(tmp_path / "q1_FIG.py")
    result = check_gates(tmp_path, 1, REPORT)
    misnamed = [v for v in result.hard if v.code == "MISNAMED_FILE"]
    assert len(misnamed) == 1 and misnamed[0].path == "q1_FIG.py" and misnamed[0].expected == "Q1_fig.py"


def test_summary_schema_violations(tmp_path: Path) -> None:
    _write_conforming(tmp_path, 3)
    raw = tmp_path / "raw"
    # Q1: missing key + wrong question number; Q2: p = 0; Q3: not JSON
    raw.joinpath("Q1_summary.json").write_text(json.dumps({
        k: v for k, v in _summary(2).items() if k != "effect_size"
    }))
    raw.joinpath("Q2_summary.json").write_text(json.dumps(_summary(2, p_value=0.0)))
    raw.joinpath("Q3_summary.json").write_text("{not json")
    result = check_gates(tmp_path, 3, REPORT)
    hard = {(v.question, v.code) for v in result.hard}
    assert (1, "SUMMARY_MISSING_KEY") in hard
    assert (1, "SUMMARY_QUESTION_MISMATCH") in hard
    assert (2, "P_VALUE_ZERO") in hard
    assert (3, "INVALID_JSON") in hard
    key_violation = next(v for v in result.hard if v.code == "SUMMARY_MISSING_KEY")
    assert key_violation.expected == "key `effect_size`"


def test_metric_contract_enforces_completeness_type_nullability_and_units(tmp_path: Path) -> None:
    _write_conforming(tmp_path, 1)
    _write_metric_contract(tmp_path)
    _write_metric_summary(tmp_path)
    summary_path = tmp_path / "raw" / "Q1_summary.json"
    data = json.loads(summary_path.read_text())
    del data["component_b"]
    data["component_a"] = "$7.7 billion"
    data["component_total"] = None
    data["unexpected_numeric"] = 99
    data["_units"]["component_a"] = "USD_million"
    del data["_units"]["component_b"]
    summary_path.write_text(json.dumps(data))

    result = check_gates(tmp_path, 1, REPORT)
    assert {"METRIC_MISSING", "METRIC_BAD_TYPE", "METRIC_NULL_NOT_ALLOWED", "METRIC_EXTRA", "METRIC_UNIT_MISMATCH", "METRIC_UNIT_MISSING"} <= set(_codes(result, "hard"))


def test_arithmetic_and_dyfa_values_are_checked_without_origin_data(tmp_path: Path) -> None:
    _write_conforming(tmp_path, 1)
    _write_metric_contract(tmp_path)
    _write_metric_summary(tmp_path, total=8.1)

    result = check_gates(tmp_path, 1, REPORT)
    codes = set(_codes(result, "hard"))
    assert "ARITHMETIC_MISMATCH" in codes
    # Change only the DYFA marker: JSON arithmetic is now sound, narrative is stale.
    _write_metric_summary(tmp_path, total=8.2)
    report = tmp_path / REPORT
    report.write_text(report.read_text().replace("component_total=8.2", "component_total=8.1"))
    result = check_gates(tmp_path, 1, REPORT)
    assert "DYFA_METRIC_MISMATCH" in _codes(result, "hard")


def test_semantic_feedback_contains_codes_and_paths_but_no_values(tmp_path: Path) -> None:
    _write_conforming(tmp_path, 1)
    _write_metric_contract(tmp_path)
    _write_metric_summary(tmp_path, total=8.123456789)
    feedback = check_gates(tmp_path, 1, REPORT).feedback(1, 1)
    assert "ARITHMETIC_MISMATCH" in feedback
    assert "raw/Q1_summary.json" in feedback
    assert "8.123456789" not in feedback
    assert "origin" not in feedback.lower()


def test_real_world_shapes_are_advisory_not_blocking(tmp_path: Path) -> None:
    """Shapes seen in real runs: nested `groups`, a `<1e-300` bound, a `Q5: …` question string."""
    _write_conforming(tmp_path, 1)
    (tmp_path / "raw" / "Q1_summary.json").write_text(json.dumps(_summary(
        1, question="Q1: does it work?", p_value="<1e-300", groups={"a": 1, "b": 2},
    )))
    result = check_gates(tmp_path, 1, REPORT)
    assert result.passed
    assert _codes(result, "soft") == ["P_VALUE_BOUND_STRING", "SUMMARY_NOT_FLAT"]


def test_bad_png_and_empty_file(tmp_path: Path) -> None:
    _write_conforming(tmp_path, 1)
    (tmp_path / "Q1_fig.png").write_bytes(b"<svg/>")
    (tmp_path / "raw" / "Q1_raw.csv").write_text("")
    result = check_gates(tmp_path, 1, REPORT)
    assert _codes(result, "hard") == ["EMPTY_FILE", "INVALID_PNG"]


def test_report_section_checks(tmp_path: Path) -> None:
    _write_conforming(tmp_path, 3)
    (tmp_path / REPORT).write_text(
        "# Report\n\n"
        "## Q1\n\nD - Do\n\nY - Why\n\nF - Find\n\nA - Answer\n\n"      # no figure
        "## Question 2\n\n### D - Do\n\n### F - Find\n\n![f](Q2_fig.png)\n\n"  # missing Y and A
        # Q3 absent entirely
    )
    result = check_gates(tmp_path, 3, REPORT)
    hard = {(v.question, v.code) for v in result.hard}
    assert hard == {
        (1, "FIGURE_NOT_EMBEDDED"),
        (2, "MISSING_DYFA_LABELS"),
        (3, "MISSING_DYFA_SECTION"),
    }
    labels = next(v for v in result.hard if v.code == "MISSING_DYFA_LABELS")
    assert "Y - Why" in labels.message and "A - Answer" in labels.message


def test_report_under_fallback_name_is_soft(tmp_path: Path) -> None:
    _write_conforming(tmp_path, 1, report_name="REPORT.md")
    result = check_gates(tmp_path, 1, REPORT)
    assert result.passed
    assert _codes(result, "soft") == ["REPORT_MISNAMED"]
    assert result.soft[0].expected == REPORT


def test_scripts_that_never_name_their_files_are_blocking(tmp_path: Path) -> None:
    _write_conforming(tmp_path, 1)
    (tmp_path / "Q1_analysis.py").write_text("print('hi')\n")
    (tmp_path / "Q1_fig.py").write_text("print('hi')\n")
    result = check_gates(tmp_path, 1, REPORT)
    assert not result.passed
    assert _codes(result, "hard") == [
        "ANALYSIS_NO_CSV_WRITE", "FIG_SCRIPT_NO_CSV_READ", "FIG_SCRIPT_NO_PNG_WRITE",
    ]


def test_templated_filenames_in_scripts_count_as_naming_them(tmp_path: Path) -> None:
    _write_conforming(tmp_path, 1)
    (tmp_path / "Q1_analysis.py").write_text('Q = 1\ndf.to_csv(RAW / f"Q{Q}_raw.csv")\n')
    (tmp_path / "Q1_fig.py").write_text(
        'q = 1\npd.read_csv("raw/Q%d_raw.csv" % q)\nplt.savefig("Q{}_fig.png".format(q))\n'
    )
    assert check_gates(tmp_path, 1, REPORT).clean


def test_nested_output_folder_is_located(tmp_path: Path) -> None:
    nested = tmp_path / "replication_ReplicationModel"
    _write_conforming(nested, 2)
    assert locate_deliverable_root(tmp_path, "replication_ReplicationModel") == nested
    result = check_gates(tmp_path, 2, REPORT, output_folder="replication_ReplicationModel")
    assert result.passed and result.root == "replication_ReplicationModel"
    # Even without the hint, the folder holding the question files wins.
    assert check_gates(tmp_path, 2, REPORT).passed


def test_feedback_is_built_from_names_and_codes_only(tmp_path: Path) -> None:
    _write_conforming(tmp_path, 1)
    (tmp_path / "Q1_fig.png").rename(tmp_path / "q1_figure.png")
    (tmp_path / REPORT).write_text("# Report\n\n## Q1\n\nSECRET-RESULT-TEXT\n")
    result = check_gates(tmp_path, 1, REPORT)
    text = result.feedback(1, 1)
    assert "revision 1 of 1" in text
    assert "[MISNAMED_FILE]" in text and "`Q1_fig.png`" in text and "q1_figure.png" in text
    assert "Do not re-run the analysis" in text
    assert "SECRET-RESULT-TEXT" not in text  # report contents never leak into feedback


def test_observation_is_json_serializable(tmp_path: Path) -> None:
    result = check_gates(tmp_path, 1, REPORT)
    json.dumps(result.as_observation())


# --- Executable figure gate --------------------------------------------------

import sys


def _fig_script(body: str) -> str:
    # Every script names raw/Q1_raw.csv and Q1_fig.png so the static gate lets it run.
    return "import sys\nopen('raw/Q1_raw.csv').read()\n" + body + "\n# writes Q1_fig.png\n"


def test_exec_gate_identical_output_leaves_no_evidence(tmp_path: Path) -> None:
    _write_conforming(tmp_path, 1)
    (tmp_path / "Q1_fig.py").write_text(_fig_script(f"open('Q1_fig.png','wb').write({PNG!r})"))
    result = check_gates(tmp_path, 1, REPORT, exec_figures=True, exec_python=sys.executable)
    assert result.clean, [v.code for v in result.violations]
    assert result.exec_info["identical"] == [1] and result.exec_info["results"] == {"1": "identical"}
    assert not (tmp_path / "_gates").exists()
    assert (tmp_path / "Q1_fig.png").read_bytes() == PNG


def test_exec_gate_mismatch_keeps_evidence_and_restores_original(tmp_path: Path) -> None:
    _write_conforming(tmp_path, 1)
    other = PNG[:-1] + b"\x01"
    (tmp_path / "Q1_fig.py").write_text(_fig_script(f"open('Q1_fig.png','wb').write({other!r})"))
    result = check_gates(tmp_path, 1, REPORT, exec_figures=True, exec_python=sys.executable)
    assert [v.code for v in result.hard] == ["FIG_MISMATCH"]
    assert (tmp_path / "Q1_fig.png").read_bytes() == PNG            # delivered file untouched
    assert (tmp_path / "_gates" / "Q1_fig.regenerated.png").read_bytes() == other


def test_exec_gate_failure_and_missing_output(tmp_path: Path) -> None:
    _write_conforming(tmp_path, 2)
    (tmp_path / "Q1_fig.py").write_text(_fig_script("raise SystemExit('boom')"))
    (tmp_path / "Q2_fig.py").write_text("open('raw/Q2_raw.csv')\n# Q2_fig.png never written\n")
    result = check_gates(tmp_path, 2, REPORT, exec_figures=True, exec_python=sys.executable)
    codes = {(v.question, v.code) for v in result.hard}
    assert codes == {(1, "FIG_SCRIPT_FAILED"), (2, "FIG_NOT_REGENERATED")}
    assert (tmp_path / "_gates" / "Q1_fig.stderr.txt").read_text().strip() == "boom"
    for n in (1, 2):
        assert (tmp_path / f"Q{n}_fig.png").read_bytes().startswith(b"\x89PNG")


def test_exec_gate_missing_module_is_advisory(tmp_path: Path) -> None:
    _write_conforming(tmp_path, 1)
    (tmp_path / "Q1_fig.py").write_text(_fig_script("import definitely_not_installed_xyz"))
    result = check_gates(tmp_path, 1, REPORT, exec_figures=True, exec_python=sys.executable)
    assert result.passed and _codes(result, "soft") == ["FIG_SCRIPT_ENV_MISSING"]


def test_exec_gate_timeout(tmp_path: Path) -> None:
    _write_conforming(tmp_path, 1)
    (tmp_path / "Q1_fig.py").write_text(_fig_script("import time; time.sleep(5)"))
    result = check_gates(tmp_path, 1, REPORT, exec_figures=True, exec_python=sys.executable, exec_timeout=1)
    assert [v.code for v in result.hard] == ["FIG_SCRIPT_TIMEOUT"]
    assert (tmp_path / "Q1_fig.png").read_bytes() == PNG


def test_exec_gate_skips_questions_that_failed_static_checks(tmp_path: Path) -> None:
    _write_conforming(tmp_path, 2)
    (tmp_path / "Q1_fig.py").write_text(_fig_script(f"open('Q1_fig.png','wb').write({PNG!r})"))
    (tmp_path / "Q2_fig.png").write_bytes(b"not a png")
    result = check_gates(tmp_path, 2, REPORT, exec_figures=True, exec_python=sys.executable)
    assert result.exec_info["attempted"] == [1]
    assert (2, "INVALID_PNG") in {(v.question, v.code) for v in result.hard}


def test_exec_gate_without_interpreter_is_advisory(tmp_path: Path) -> None:
    _write_conforming(tmp_path, 1)
    with patch("rrg_cli.gates.resolve_gate_python", return_value=(None, "none")):
        result = check_gates(tmp_path, 1, REPORT, exec_figures=True)
    assert result.passed and _codes(result, "soft") == ["NO_GATE_INTERPRETER"]
    assert result.exec_info["skipped"] == [1]


# --- Dispatch revision loop --------------------------------------------------

def _stateful_validator(fix_on_feedback: bool):
    """A ReplayPlanner-style stand-in: writes a broken return first, fixes it when told."""
    calls: list[str] = []

    def side_effect(prompt, slug, work_dir, session_id=None):
        calls.append(prompt)
        root = Path(work_dir)
        if "[MISNAMED_FILE]" in prompt or "[MISSING_FILE]" in prompt:
            if fix_on_feedback:
                _write_conforming(root, 3)
            return ("GATES: fixed", session_id or "s1", "qwen/qwen3.7-max")
        if not (root / "raw").exists():
            _write_conforming(root, 3)
            (root / "Q2_fig.png").rename(root / "q2_figure.png")   # one deliberate deviation
        return ("Done.", session_id or "s1", "qwen/qwen3.7-max")

    return side_effect, calls


def test_dispatch_gate_failure_sends_feedback_and_revises(ready_project: Project) -> None:
    side_effect, calls = _stateful_validator(fix_on_feedback=True)
    with patch("rrg_cli.dispatch._exec_hermes_turn", side_effect=side_effect):
        result = dispatch(ready_project, "replication", "ReplicationModel",
                          validator="hermes", mode="nodiscuss")
    gates = result["gates"]
    assert gates["enabled"] and gates["passed"] and gates["revisions"] == 1
    assert len(gates["history"]) == 2
    assert gates["history"][0]["ok"] is False and gates["history"][1]["ok"] is True
    first_fail = gates["history"][0]["hard"]
    assert [v["code"] for v in first_fail] == ["MISNAMED_FILE"]
    assert first_fail[0]["expected"] == "Q2_fig.png"
    # The revision turn went to the same session and named the exact expected file.
    revision = [c for c in result["conversation"] if c["title"].startswith("Gate revision")]
    assert len(revision) == 1 and "`Q2_fig.png`" in revision[0]["prompt"]
    assert revision[0]["session_id"] == "s1"
    # Three prompt turns (nodiscuss replication) + one revision.
    assert len(calls) == len(result["prompt"]["turns"]) + 1
    # The gate record travels into the run folder and RUN_INFO.
    run_dir = Path(result["import_result"]["output_folder"])
    record = json.loads((run_dir / "GATES.json").read_text())
    assert record["passed"] is True and record["revisions"] == 1
    assert "Deliverable gates**: PASS after 1 revision(s)" in (run_dir / "RUN_INFO.md").read_text()


def test_dispatch_gate_exhausted_revisions_still_imports(ready_project: Project) -> None:
    side_effect, calls = _stateful_validator(fix_on_feedback=False)
    with patch("rrg_cli.dispatch._exec_hermes_turn", side_effect=side_effect):
        result = dispatch(ready_project, "replication", "ReplicationModel",
                          validator="hermes", mode="nodiscuss", gate_revisions=2)
    gates = result["gates"]
    assert gates["passed"] is False and gates["revisions"] == 2
    assert len(gates["history"]) == 3
    assert len(calls) == len(result["prompt"]["turns"]) + 2
    assert result["import_result"] is not None and result["import_result"]["count"] > 0
    assert result["import_result"]["gates"]["passed"] is False


def test_dispatch_gates_disabled_sends_no_extra_turn(ready_project: Project) -> None:
    side_effect, calls = _stateful_validator(fix_on_feedback=True)
    with patch("rrg_cli.dispatch._exec_hermes_turn", side_effect=side_effect):
        result = dispatch(ready_project, "replication", "ReplicationModel",
                          validator="hermes", mode="nodiscuss", gates=False)
    assert result["gates"]["enabled"] is False
    assert len(calls) == len(result["prompt"]["turns"])
    assert not any(c["title"].startswith("Gate revision") for c in result["conversation"])


def test_dispatch_gate_revisions_zero_reports_only(ready_project: Project) -> None:
    side_effect, calls = _stateful_validator(fix_on_feedback=True)
    with patch("rrg_cli.dispatch._exec_hermes_turn", side_effect=side_effect):
        result = dispatch(ready_project, "replication", "ReplicationModel",
                          validator="hermes", mode="nodiscuss", gate_revisions=0)
    gates = result["gates"]
    assert gates["enabled"] and gates["passed"] is False and gates["revisions"] == 0
    assert len(calls) == len(result["prompt"]["turns"])


def test_dispatch_gate_prefs_are_honoured(ready_project: Project) -> None:
    save_prefs(ready_project, {"gates": False})
    side_effect, calls = _stateful_validator(fix_on_feedback=True)
    with patch("rrg_cli.dispatch._exec_hermes_turn", side_effect=side_effect):
        result = dispatch(ready_project, "replication", "ReplicationModel",
                          validator="hermes", mode="nodiscuss")
    assert result["gates"]["enabled"] is False
    save_prefs(ready_project, {"gates": True, "gate_revisions": 0})
    side_effect, calls = _stateful_validator(fix_on_feedback=True)
    with patch("rrg_cli.dispatch._exec_hermes_turn", side_effect=side_effect):
        result = dispatch(ready_project, "replication", "ReplicationModel",
                          validator="hermes", mode="nodiscuss")
    assert result["gates"]["enabled"] and result["gates"]["max_revisions"] == 0


def _soft_only_validator(fix_on_feedback: bool):
    """Conforming files, except every summary nests a `groups` object (advisory only)."""
    calls: list[str] = []

    def side_effect(prompt, slug, work_dir, session_id=None):
        calls.append(prompt)
        root = Path(work_dir)
        if "[SUMMARY_NOT_FLAT]" in prompt:
            if fix_on_feedback:
                _write_conforming(root, 3)
            return ("GATES: fixed", session_id or "s1", "m")
        if not (root / "raw").exists():
            _write_conforming(root, 3)
            for n in range(1, 4):
                path = root / "raw" / f"Q{n}_summary.json"
                summary = json.loads(path.read_text())
                summary["groups"] = {"a": "annotation"}
                path.write_text(json.dumps(summary))
        return ("Done.", session_id or "s1", "m")

    return side_effect, calls


def test_advisory_only_still_earns_a_revision_but_passes(ready_project: Project) -> None:
    side_effect, calls = _soft_only_validator(fix_on_feedback=False)
    with patch("rrg_cli.dispatch._exec_hermes_turn", side_effect=side_effect):
        result = dispatch(ready_project, "replication", "ReplicationModel",
                          validator="hermes", mode="nodiscuss", gate_revisions=3,
                          gate_exec=False)
    gates = result["gates"]
    assert gates["history"][0]["ok"] is True and gates["history"][0]["clean"] is False
    # One revision was sent for the advisory items ...
    assert gates["revisions"] == 1
    assert "advisory deviation(s)" in calls[-1] and "[SUMMARY_NOT_FLAT]" in calls[-1]
    # ... the model left them, so the loop stopped rather than repeating itself,
    # and the run still passes (advisory never decides pass/fail).
    assert gates["stopped"] and gates["passed"] is True and gates["clean"] is False
    assert len(calls) == len(result["prompt"]["turns"]) + 1


def test_advisory_fixed_on_revision_ends_clean(ready_project: Project) -> None:
    side_effect, calls = _soft_only_validator(fix_on_feedback=True)
    with patch("rrg_cli.dispatch._exec_hermes_turn", side_effect=side_effect):
        result = dispatch(ready_project, "replication", "ReplicationModel",
                          validator="hermes", mode="nodiscuss", gate_exec=False)
    gates = result["gates"]
    assert gates["revisions"] == 1 and gates["clean"] is True and gates["stopped"] is None


def test_openrouter_has_nothing_to_gate(ready_project: Project) -> None:
    with patch("rrg_cli.dispatch._call_openrouter", return_value="Done."):
        result = dispatch(ready_project, "replication", "ReplicationModel",
                          validator="openrouter", mode="nodiscuss", auto_import=False)
    assert result["gates"]["enabled"] is False


# --- Import-time gate record -------------------------------------------------

def test_import_records_gates_before_normalizing(ready_project: Project, tmp_path: Path) -> None:
    returned = tmp_path / "returned"
    returned.mkdir()
    (returned / "METRIC_SPEC.json").write_text(ready_project.path("shared/METRIC_SPEC.json").read_text())
    _write_conforming(returned, 3)
    (returned / "Q1_fig.png").rename(returned / "q1_figure.png")
    result = import_run(ready_project, "replication", "ReplicationModel", returned)
    gates = result["gates"]
    assert gates["source"] == "import" and gates["passed"] is False
    assert [v["code"] for v in gates["final"]["hard"]] == ["MISNAMED_FILE"]
    run_dir = Path(result["output_folder"])
    # Normalization fixed the name afterwards, but the record shows what was delivered.
    assert (run_dir / "Q1_fig.png").is_file()
    assert json.loads((run_dir / "GATES.json").read_text())["passed"] is False


def test_eval_surfaces_gate_record(ready_project: Project, tmp_path: Path) -> None:
    from rrg_cli.eval_lite import eval_run
    returned = tmp_path / "returned"
    returned.mkdir()
    (returned / "METRIC_SPEC.json").write_text(ready_project.path("shared/METRIC_SPEC.json").read_text())
    _write_conforming(returned, 3)
    result = import_run(ready_project, "replication", "ReplicationModel", returned)
    evaluated = eval_run(ready_project, Path(result["output_folder"]))
    assert evaluated["gates"]["passed"] is True
    assert "Gates at import: PASS" in evaluated["report"]


# --- Prefs coercion -----------------------------------------------------------

def test_coerce_pref_types() -> None:
    assert coerce_pref("gates", "false") is False
    assert coerce_pref("gates", "yes") is True
    assert coerce_pref("gate_revisions", "3") == 3
    assert coerce_pref("gate_revisions", "-1") == 0
    assert coerce_pref("validator", "hermes") == "hermes"
    try:
        coerce_pref("gate_revisions", "lots")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
