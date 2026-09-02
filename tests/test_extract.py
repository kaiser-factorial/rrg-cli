from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from rrg_cli import extract
from rrg_cli.project import Project
from rrg_cli.scaffold import init_project


def test_flatten_and_value_matching():
    assert extract.flatten({"a": 1, "b": {"c": 2}}) == [("a", 1), ("b.c", 2)]
    found, matched, _ctx = extract.find_value(3003, "sample N = 3,003 retained")
    assert found is True and matched == "3,003"
    assert extract.find_value(0.44, "the correlation r = 0.44 here")[0] is True
    assert extract.find_value(12.34, "only r = 0.44 reported")[0] is False
    assert extract._format_value(1815.722742556713) == "1815.7227"
    assert extract._format_value(3003.0) == "3,003"


def test_structural_comparison_is_exact_by_default_and_unit_aware():
    origin = """## Q1
- **statistic** — Benefit gap $7.7 billion; net gap $8.2 billion; MY1–2 cost $65.7 million.
- **p_value** — not reported.
"""
    exact = extract.compare_value("benefit_component_billions", 7.7, origin)
    assert exact["status"] == "exact" and exact["origin_value"] == "$7.7 billion"

    rounding = extract.compare_value("component_sum_billions", 8.1, origin)
    assert rounding["status"] == "different"
    assert rounding["tolerance"] == 0 and rounding["delta_display"] == "-0.1 billion USD"

    scaled = extract.compare_value("bpci_advanced.my1_2_net_usd", 65_500_000, origin)
    assert scaled["status"] == "different"
    assert scaled["origin_value"] == "$65.7 million"
    assert scaled["delta_display"] == "-$200,000"


def test_only_p_values_receive_pipeline_owned_tolerance_and_remain_flagged():
    origin = """## Q1
- **p_value** — bootstrap p=0.050.
- **statistic** — estimate 8.2.
"""
    close_p = extract.compare_value("p_value", 0.047, origin)
    assert close_p["status"] == "within_tolerance"
    assert close_p["within_tolerance"] is True and close_p["exact"] is False
    assert close_p["tolerance"] == 0.005

    far_p = extract.compare_value("bootstrap_p_value", 0.044, origin)
    assert far_p["status"] == "different" and far_p["tolerance"] == 0.005

    close_stat = extract.compare_value("statistic", 8.199, origin)
    assert close_stat["status"] == "different" and close_stat["tolerance"] == 0


def test_number_forms_and_matching_are_order_stable():
    # Equal-length forms keep a fixed precedence (plain decimal, then comma-grouped, then
    # percent) rather than set iteration order, so the origin rendering that find_value
    # reports does not depend on PYTHONHASHSEED.
    assert extract._number_forms(0.25) == ["0.2500", "0.250", "25.00", "0.25", "25.0", "0.2", "25"]
    assert extract.find_value(0.25, "share 25.0 of 0.25 total")[1] == "0.25"
    assert extract._highlight_forms([0.44, 100]) == [
        "100.0000", "100.000", "0.4400", "100.00", "0.440", "44.00", "100.0", "0.44", "44.0", "0.4", "100", "44",
    ]


def test_extraction_helpers_do_not_depend_on_hash_seed():
    # Regression guard for run-to-run drift: the same inputs must produce byte-identical
    # results in fresh interpreters started with different hash seeds.
    origin = "## Q1\n- **p_value** — bootstrap p=0.050.\n- **statistic** — estimate 8.2.\n"
    code = (
        "import json\n"
        "from rrg_cli import extract\n"
        f"origin = {origin!r}\n"
        "print(json.dumps({\n"
        "    'forms': extract._number_forms(0.25),\n"
        "    'matched': extract.find_value(0.25, 'share 25.0 of 0.25 total')[1],\n"
        "    'highlights': extract._highlight_forms([0.44, 100, 0.5, 'chi2']),\n"
        "    'status': extract.compare_value('statistic', 8.199, origin)['status'],\n"
        "}))\n"
    )
    src_dir = str(Path(extract.__file__).resolve().parents[1])
    outputs = set()
    for seed in ("0", "1", "2", "3"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": src_dir}
        completed = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True
        )
        outputs.add(completed.stdout.strip())
    assert len(outputs) == 1, outputs
    assert json.loads(outputs.pop())["status"] == "different"


def test_origin_only_surfaces_unreported_numbers():
    extra = extract.origin_only("N = 100, but 37 rows were excluded (8.4%).", [100])
    values = {item["value"] for item in extra}
    assert "37" in values and "8.4%" in values
    assert "100" not in values  # already reported by the validator


def _project_with_run(root: Path) -> Project:
    init_project(root)
    origin = root / "operator/origin"
    origin.mkdir(parents=True, exist_ok=True)
    (origin / "q1_results.txt").write_text("N = 100 complete rows. r = 0.44. Excluded 37 rows.", encoding="utf-8")
    (origin / "SUMMARY.md").write_text("## Q1 - sample\nOrigin narrative for Q1.\n", encoding="utf-8")
    run = root / "operator/replication_RunModel"
    (run / "raw").mkdir(parents=True, exist_ok=True)
    (run / "raw" / "Q1_summary.json").write_text(
        json.dumps({"n": 100, "r": 0.44, "p": 0.001}), encoding="utf-8"
    )
    (run / "DYFA.md").write_text("## Q1. Sample\nValidator narrative for Q1.\n", encoding="utf-8")
    return Project.load(root)


def test_question_extraction_against_origin(tmp_path: Path):
    project = _project_with_run(tmp_path / "study")
    result = extract.question_extraction(project, "operator/replication_RunModel", 1, 1, stage="replication")

    assert result["has_validator_stats"] and result["stats_source"] == "Q1_summary.json"
    by_label = {row["label"]: row for row in result["stats"]}
    assert by_label["n"]["in_origin"] is True and by_label["n"]["origin_value"] == "100"
    assert by_label["r"]["in_origin"] is True and by_label["r"]["origin_value"] == "0.44"
    assert by_label["p"]["in_origin"] is False and by_label["p"]["origin_value"] == ""
    assert result["expect_exact"] is True  # replication reveals the methodology

    assert any(item["value"] == "37" for item in result["origin_only"])
    assert result["origin_narrative_source"] == "SUMMARY.md" and result["origin_narrative"].strip()
    assert result["validator_narrative_source"] == "DYFA.md" and result["validator_narrative"].strip()
