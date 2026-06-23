from __future__ import annotations

from pathlib import Path

import pytest

from rrg_cli import figures

REPO = Path(__file__).resolve().parents[1]
EXAMPLE_ORIGIN = REPO / "examples" / "MovieRatings" / "operator" / "origin"

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def test_file_figures_match_by_question_with_boundary(tmp_path: Path):
    (tmp_path / "q1_fig_main.png").write_bytes(PNG)
    (tmp_path / "q11_fig.png").write_bytes(PNG)  # must NOT match question 1
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "q1_extra.png").write_bytes(PNG)  # subfolders are searched

    names = {fig["name"] for fig in figures.resolve_figures(tmp_path, 1)}
    assert "q1_fig_main.png" in names
    assert "sub/q1_extra.png" in names
    assert "q11_fig.png" not in names


def test_reference_token_pulls_referenced_figure(tmp_path: Path):
    (tmp_path / "plate_q3_fig2_special.png").write_bytes(PNG)
    figs = figures.resolve_figures(tmp_path, 3, text="as shown in `q3_fig2`")
    assert any(fig["name"] == "plate_q3_fig2_special.png" for fig in figs)


@pytest.mark.skipif(not (EXAMPLE_ORIGIN / "ORIGIN_REPORT.pdf").is_file(), reason="example PDF missing")
def test_pdf_appendix_caption_matching():
    pdf = EXAMPLE_ORIGIN / "ORIGIN_REPORT.pdf"
    # the example origin has no figure files — figures live in the PDF appendix, and the
    # figure numbers do NOT line up with question numbers, so we match by caption content.
    assert not list(EXAMPLE_ORIGIN.glob("*.png"))
    pop = figures.resolve_figures(EXAMPLE_ORIGIN, 1, report_path=pdf, match_text="popularity high popularity movies")
    assert pop and pop[0]["source"] == "pdf" and pop[0]["data_url"].startswith("data:image/")

    lion = figures.resolve_figures(EXAMPLE_ORIGIN, 5, report_path=pdf, match_text="Lion King only children siblings")
    assert lion and lion[0]["data_url"] != pop[0]["data_url"]  # a different (correct) figure

    # an unrelated query must not false-match any figure
    assert figures.resolve_figures(EXAMPLE_ORIGIN, 99, report_path=pdf, match_text="quantum chromodynamics elephant") == []
