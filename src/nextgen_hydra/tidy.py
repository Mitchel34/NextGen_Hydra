"""Approved raw-output to tidy site-level time series transforms."""

from __future__ import annotations

from datetime import UTC, datetime
import csv
from pathlib import Path
from typing import Any, Iterable

from .download import safe_local_path
from .manifest import validate_manifest_records


class TidyError(RuntimeError):
    """Raised when raw outputs cannot be safely transformed."""


def normalise_rows(
    source_rows: Iterable[dict[str, Any]],
    *,
    site: dict[str, Any],
    manifest_record: dict[str, Any],
    feature_id_column: str,
    time_column: str,
    flow_column: str,
    flow_units: str,
) -> list[dict[str, Any]]:
    """Filter explicit-schema rows to one site and normalize column names."""

    feature_id = str(site["hydrofabric_feature_id"])
    tidy_rows: list[dict[str, Any]] = []
    for row in source_rows:
        missing = [
            column
            for column in (feature_id_column, time_column, flow_column)
            if column not in row
        ]
        if missing:
            raise TidyError(f"source row missing required schema columns: {missing}")
        if str(row[feature_id_column]) != feature_id:
            continue
        tidy_rows.append(
            {
                "site_id": site["site_id"],
                "usgs_gage_id": site["usgs_gage_id"],
                "hydrofabric_feature_id": int(site["hydrofabric_feature_id"]),
                "vpu_id": manifest_record["vpu_id"],
                "stream": manifest_record["stream"],
                "run_date": manifest_record["run_date"],
                "run_type": manifest_record["run_type"],
                "cycle": manifest_record["cycle"],
                "time_utc": _normalize_time(row[time_column]),
                "streamflow": row[flow_column],
                "streamflow_units": flow_units,
                "source_manifest_ref": manifest_record["object_key"],
                "source_object_key": manifest_record["object_key"],
            }
        )
    return tidy_rows


def tidy_manifest_records(
    *,
    manifest_records: list[dict[str, Any]],
    defaults: dict[str, Any],
    raw_dir: Path,
    output_dir: Path,
    feature_id_column: str,
    time_column: str,
    flow_column: str,
    flow_units: str,
    output_format: str = "parquet",
) -> list[dict[str, Any]]:
    """Transform validated approved raw records using explicit schema arguments."""

    validated = validate_manifest_records(manifest_records, defaults)
    output_dir.mkdir(parents=True, exist_ok=True)
    catalog: list[dict[str, Any]] = []
    for record in validated:
        local_path = safe_local_path(raw_dir, record["object_key"])
        if not local_path.exists():
            raise TidyError(f"raw file is missing for manifest row: {local_path}")
        source_rows = _read_source_rows(local_path, record["format"])
        site = {
            "site_id": record["site_id"],
            "usgs_gage_id": record["usgs_gage_id"],
            "hydrofabric_feature_id": record["hydrofabric_feature_id"],
        }
        tidy_rows = normalise_rows(
            source_rows,
            site=site,
            manifest_record=record,
            feature_id_column=feature_id_column,
            time_column=time_column,
            flow_column=flow_column,
            flow_units=flow_units,
        )
        tidy_name = (
            f"{record['site_id']}_{record['stream']}_{record['run_date']}_"
            f"{record['run_type']}_{record['cycle']}.{output_format}"
        )
        tidy_path = output_dir / tidy_name
        _write_tidy_rows(tidy_path, tidy_rows, output_format)
        catalog.append(
            build_catalog_record(
                record=record,
                tidy_path=tidy_path,
                tidy_rows=tidy_rows,
                flow_variable=flow_column,
                flow_units=flow_units,
            )
        )
    return catalog


def build_catalog_record(
    *,
    record: dict[str, Any],
    tidy_path: Path,
    tidy_rows: list[dict[str, Any]],
    flow_variable: str,
    flow_units: str,
) -> dict[str, Any]:
    times = [row["time_utc"] for row in tidy_rows if row.get("time_utc")]
    missing_count = sum(
        1 for row in tidy_rows if row.get("streamflow") in (None, "")
    )
    return {
        "site_id": record["site_id"],
        "usgs_gage_id": record["usgs_gage_id"],
        "hydrofabric_feature_id": record["hydrofabric_feature_id"],
        "vpu_id": record["vpu_id"],
        "stream": record["stream"],
        "run_date": record["run_date"],
        "run_type": record["run_type"],
        "cycle": record["cycle"],
        "source_format": record["format"],
        "tidy_path": str(tidy_path),
        "row_count": len(tidy_rows),
        "start_time_utc": min(times) if times else None,
        "end_time_utc": max(times) if times else None,
        "time_step_seconds": _infer_time_step_seconds(times),
        "flow_variable": flow_variable,
        "flow_units": flow_units,
        "missing_count": missing_count,
        "qc_status": "pass" if tidy_rows and missing_count == 0 else "review",
        "source_manifest_ref": record["object_key"],
    }


def _read_source_rows(local_path: Path, source_format: str) -> list[dict[str, Any]]:
    if source_format == "parquet":
        try:
            import pandas as pd  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise TidyError("parquet transform requires pandas and pyarrow") from exc
        return pd.read_parquet(local_path).to_dict(orient="records")
    if source_format == "nc":
        try:
            import xarray as xr  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise TidyError("NetCDF transform requires xarray and netCDF4") from exc
        dataset = xr.open_dataset(local_path)
        try:
            return dataset.to_dataframe().reset_index().to_dict(orient="records")
        finally:
            dataset.close()
    raise TidyError(f"unsupported source format for tidy transform: {source_format}")


def _write_tidy_rows(path: Path, rows: list[dict[str, Any]], output_format: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "parquet":
        try:
            import pandas as pd  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise TidyError("writing parquet requires pandas and pyarrow") from exc
        pd.DataFrame(rows).to_parquet(path, index=False)
        return
    if output_format == "csv":
        fieldnames = sorted({key for row in rows for key in row})
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return
    raise TidyError(f"unsupported tidy output format: {output_format}")


def _normalize_time(value: Any) -> str:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()
    return str(value)


def _infer_time_step_seconds(times: list[str]) -> int | None:
    if len(times) < 2:
        return None
    parsed: list[datetime] = []
    for value in sorted(times[:3]):
        try:
            parsed.append(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    if len(parsed) < 2:
        return None
    return int((parsed[1] - parsed[0]).total_seconds())
