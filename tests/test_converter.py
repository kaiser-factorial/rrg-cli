from pathlib import Path

import pandas as pd

from rrg_cli.converter import DEFAULT_NA_TOKEN, convert_dataset, verify_frame


def test_conversion_preserves_strings_missing_and_boolean_like_text(tmp_path: Path):
    source = tmp_path / "source.csv"
    frame = pd.DataFrame({"text": ["", "true", "NA", None], "number": [1.0, None, 3.5, 4.0]})
    frame.to_csv(source, index=False, na_rep=DEFAULT_NA_TOKEN)
    result = convert_dataset(source, tmp_path / "analysis")
    assert result["all_verified"]
    assert all(output["verify"]["string_mismatches"] == 0 for output in result["outputs"])
    assert all(output["verify"]["nan_pattern_ok"] for output in result["outputs"])
    assert Path(result["sidecar"]).exists()
    assert Path(result["codebook"]).exists()


def test_csv_is_deterministic(ready_project, tmp_path: Path):
    source = ready_project.root / "data/source.csv"
    first = convert_dataset(source, tmp_path / "first", formats=["csv"])
    second = convert_dataset(source, tmp_path / "second", formats=["csv"])
    assert Path(first["outputs"][0]["path"]).read_bytes() == Path(second["outputs"][0]["path"]).read_bytes()
