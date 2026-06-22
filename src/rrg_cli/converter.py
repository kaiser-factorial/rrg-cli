from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .errors import RRGError
from .utils import sha256

DEFAULT_NA_TOKEN = "__RRG_NA__"
SUPPORTED_FORMATS = ("csv", "parquet")
LABEL_FORMATS = {".sav", ".zsav", ".por", ".dta"}


def read_source(path: Path, labeled: bool = False):
    extension = path.suffix.lower()
    if extension in {".sav", ".zsav", ".por", ".dta", ".sas7bdat", ".xpt", ".xport"}:
        try:
            import pyreadstat
        except ImportError as exc:  # pragma: no cover
            raise RRGError("pyreadstat is required for SPSS, Stata, and SAS inputs") from exc
        readers = {
            ".sav": pyreadstat.read_sav,
            ".zsav": pyreadstat.read_sav,
            ".por": pyreadstat.read_por,
            ".dta": pyreadstat.read_dta,
            ".sas7bdat": pyreadstat.read_sas7bdat,
            ".xpt": pyreadstat.read_xport,
            ".xport": pyreadstat.read_xport,
        }
        kwargs = {"apply_value_formats": labeled} if extension in LABEL_FORMATS else {}
        return readers[extension](str(path), **kwargs)
    if extension == ".csv":
        return pd.read_csv(
            path, dtype=str, keep_default_na=False, na_values=[DEFAULT_NA_TOKEN]
        ), None
    if extension == ".tsv":
        return pd.read_csv(path, sep="\t"), None
    if extension in {".xlsx", ".xls"}:
        return pd.read_excel(path), None
    if extension == ".parquet":
        return pd.read_parquet(path), None
    raise RRGError(f"unsupported source format: {extension}")


def _read_back(path: Path, na_token: str):
    if path.suffix == ".csv":
        return pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[na_token])
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    raise RRGError(f"cannot verify format: {path.suffix}")


def verify_frame(source: pd.DataFrame, path: Path, na_token: str, tolerance: float = 1e-9) -> dict[str, Any]:
    output = _read_back(path, na_token)
    if list(source.columns) != list(output.columns):
        return {"ok": False, "reason": "columns differ"}
    if source.shape != output.shape:
        return {"ok": False, "reason": f"shape differs: {source.shape} vs {output.shape}"}
    maximum = 0.0
    strings = 0
    nan_ok = True
    for column in source.columns:
        left, right = source[column], output[column]
        left_nan, right_nan = left.isna().to_numpy(), right.isna().to_numpy()
        nan_ok = nan_ok and np.array_equal(left_nan, right_nan)
        keep = ~left_nan & ~right_nan
        a, b = left[keep], right[keep]
        an, bn = pd.to_numeric(a, errors="coerce"), pd.to_numeric(b, errors="coerce")
        if len(a) and an.notna().all() and bn.notna().all():
            maximum = max(maximum, float(np.abs(an.to_numpy() - bn.to_numpy()).max()))
        else:
            strings += int((a.astype(str).to_numpy() != b.astype(str).to_numpy()).sum())
    return {
        "ok": nan_ok and strings == 0 and maximum <= tolerance,
        "max_numeric_diff": maximum,
        "exact": maximum == 0.0,
        "tolerance": tolerance,
        "string_mismatches": strings,
        "nan_pattern_ok": nan_ok,
    }


def _metadata(frame: pd.DataFrame, metadata: Any, source: Path, labeled: bool) -> dict[str, Any]:
    labels: dict[str, Any] = {}
    values: dict[str, Any] = {}
    measures: dict[str, Any] = {}
    missing: dict[str, Any] = {}
    if metadata is not None:
        labels = dict(zip(metadata.column_names, metadata.column_labels or []))
        variable_to_label = getattr(metadata, "variable_to_label", {}) or {}
        value_labels = getattr(metadata, "value_labels", {}) or {}
        for column in metadata.column_names:
            label_set = variable_to_label.get(column)
            if label_set and label_set in value_labels:
                values[column] = {str(k): v for k, v in value_labels[label_set].items()}
        measures = getattr(metadata, "variable_measure", {}) or {}
        missing = getattr(metadata, "missing_ranges", {}) or {}
    variables = {
        column: {
            "dtype": str(frame[column].dtype),
            "label": labels.get(column) or None,
            "measure": measures.get(column),
            "value_labels": values.get(column) or None,
            "missing_ranges": missing.get(column) or None,
        }
        for column in frame.columns
    }
    return {
        "source_file": source.name,
        "source_sha256": sha256(source),
        "source_format": source.suffix.lower(),
        "n_rows": int(frame.shape[0]),
        "n_cols": int(frame.shape[1]),
        "mode": "labeled" if labeled else "coded",
        "encoding": "utf-8",
        "columns": list(frame.columns),
        "variables": variables,
    }


def _validate_na_token(frame: pd.DataFrame, token: str) -> None:
    if not token:
        raise RRGError("CSV missing-value token must be non-empty")
    if any(frame[column].dropna().eq(token).any() for column in frame.columns):
        raise RRGError(f"CSV missing-value token collides with source data: {token!r}")


def convert_dataset(
    source: Path,
    output_stem: Path,
    formats: list[str] | tuple[str, ...] = SUPPORTED_FORMATS,
    labeled: bool = False,
    na_token: str = DEFAULT_NA_TOKEN,
    float_format: str | None = None,
) -> dict[str, Any]:
    source, output_stem = source.resolve(), output_stem.resolve()
    if not source.is_file():
        raise RRGError(f"source not found: {source}")
    unknown = sorted(set(formats) - set(SUPPORTED_FORMATS))
    if unknown:
        raise RRGError(f"unsupported output format(s): {', '.join(unknown)}")
    frame, source_metadata = read_source(source, labeled=labeled)
    output_stem.parent.mkdir(parents=True, exist_ok=True)
    if "csv" in formats:
        _validate_na_token(frame, na_token)
    outputs: list[dict[str, Any]] = []
    for format_name in formats:
        path = Path(f"{output_stem}.{format_name}")
        if format_name == "csv":
            frame.to_csv(
                path,
                index=False,
                encoding="utf-8",
                na_rep=na_token,
                float_format=float_format,
                lineterminator="\n",
            )
        else:
            frame.to_parquet(path, index=False)
        verification = verify_frame(frame, path, na_token)
        outputs.append(
            {"format": format_name, "path": str(path), "name": path.name, "verify": verification}
        )
    metadata = _metadata(frame, source_metadata, source, labeled)
    metadata["na_token"] = na_token
    metadata["outputs"] = [entry["name"] for entry in outputs]
    metadata["verification"] = {entry["format"]: entry["verify"] for entry in outputs}
    meta_path = Path(f"{output_stem}.meta.json")
    meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    rows = []
    for column in metadata["columns"]:
        variable = metadata["variables"][column]
        labels = variable["value_labels"] or {}
        rows.append(
            {
                "variable": column,
                "label": variable["label"] or "",
                "dtype": variable["dtype"],
                "measure": variable["measure"] or "",
                "value_labels": "; ".join(f"{key}={value}" for key, value in labels.items()),
                "missing": json.dumps(variable["missing_ranges"] or ""),
            }
        )
    codebook_path = Path(f"{output_stem}.codebook.csv")
    pd.DataFrame(rows).to_csv(codebook_path, index=False, encoding="utf-8", lineterminator="\n")
    return {
        "source": source.name,
        "source_sha256": metadata["source_sha256"],
        "source_format": metadata["source_format"],
        "n_rows": metadata["n_rows"],
        "n_cols": metadata["n_cols"],
        "mode": metadata["mode"],
        "outputs": outputs,
        "sidecar": str(meta_path),
        "codebook": str(codebook_path),
        "all_verified": all(entry["verify"].get("ok") for entry in outputs),
    }
