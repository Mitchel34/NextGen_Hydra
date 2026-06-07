"""Approved raw-output to tidy site-level time series transforms."""

from __future__ import annotations

from datetime import UTC, datetime
import csv
from pathlib import Path
from typing import Any, Iterable

from .config import Site
from .crosswalk import crosswalk_by_site, require_resolved_crosswalk
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

    feature_id = str(site.get("troute_feature_id") or site["hydrofabric_feature_id"])
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
                "troute_feature_id": int(site.get("troute_feature_id") or site["hydrofabric_feature_id"]),
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
    units_evidence: dict[str, Any] | None = None,
    output_format: str = "parquet",
    sites: list[Site] | None = None,
    site_crosswalk: dict[str, Any] | None = None,
    require_crosswalk: bool = False,
) -> list[dict[str, Any]]:
    """Transform validated approved raw records using explicit schema arguments."""

    if units_evidence is not None:
        _require_tidy_units_evidence(
            units_evidence=units_evidence,
            flow_column=flow_column,
            flow_units=flow_units,
        )
    validated = validate_manifest_records(manifest_records, defaults, sites=sites)
    data_records = _tidy_data_records(validated)
    if require_crosswalk:
        require_resolved_crosswalk(
            crosswalk=site_crosswalk or {},
            site_ids={str(record["site_id"]) for record in data_records},
        )
    crosswalk_records = crosswalk_by_site(site_crosswalk)
    output_dir.mkdir(parents=True, exist_ok=True)
    catalog: list[dict[str, Any]] = []
    for record in data_records:
        local_path = safe_local_path(raw_dir, record["object_key"])
        if not local_path.exists():
            raise TidyError(f"raw file is missing for manifest row: {local_path}")
        source_rows = _read_source_rows(local_path, record["format"])
        site = {
            "site_id": record["site_id"],
            "usgs_gage_id": record["usgs_gage_id"],
            "hydrofabric_feature_id": record["hydrofabric_feature_id"],
            "troute_feature_id": _troute_feature_id_for_record(record, crosswalk_records),
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
    _require_per_site_coverage(catalog, data_records)
    return catalog


def _require_tidy_units_evidence(
    *,
    units_evidence: dict[str, Any],
    flow_column: str,
    flow_units: str,
) -> None:
    status = str(units_evidence.get("status") or "missing")
    variable = str(units_evidence.get("variable") or "")
    units = str(units_evidence.get("units") or "")
    evidence = units_evidence.get("evidence")
    errors: list[str] = []
    if status != "documented":
        errors.append(f"status is {status!r}")
    if variable != flow_column:
        errors.append(f"variable is {variable!r}, expected {flow_column!r}")
    if units != flow_units:
        errors.append(f"units are {units!r}, expected {flow_units!r}")
    if not isinstance(evidence, list) or not evidence:
        errors.append("authoritative evidence is missing")
    if errors:
        raise TidyError("tidy requires documented streamflow units:\n" + "\n".join(errors))


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
        "troute_feature_id": _catalog_troute_feature_id(record, tidy_rows),
        "vpu_id": record["vpu_id"],
        "product_type": record["product_type"],
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
        "duplicate_timestamp_count": _duplicate_timestamp_count(tidy_rows),
        "target_feature_present": bool(tidy_rows),
        "coverage_status": "pass" if tidy_rows else "fail",
        "qc_status": "pass" if tidy_rows and missing_count == 0 else "review",
        "source_manifest_ref": record["object_key"],
    }


def _tidy_data_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    data_records: list[dict[str, Any]] = []
    for record in records:
        product_type = record.get("product_type")
        if product_type == "metadata_provenance":
            continue
        if product_type != "troute_streamflow_output":
            raise TidyError(
                "tidy requires product_type == troute_streamflow_output; "
                f"found {product_type!r} for {record.get('object_key')}"
            )
        data_records.append(record)
    if not data_records:
        raise TidyError("manifest contains no troute_streamflow_output rows to tidy")
    return data_records


def _troute_feature_id_for_record(
    record: dict[str, Any],
    crosswalk_records: dict[str, dict[str, Any]],
) -> int:
    crosswalk_record = crosswalk_records.get(str(record["site_id"]))
    if crosswalk_record and crosswalk_record.get("status") == "resolved":
        return int(crosswalk_record["troute_feature_id"])
    return int(record["hydrofabric_feature_id"])


def _catalog_troute_feature_id(
    record: dict[str, Any],
    tidy_rows: list[dict[str, Any]],
) -> int:
    if tidy_rows and tidy_rows[0].get("troute_feature_id") not in (None, ""):
        return int(tidy_rows[0]["troute_feature_id"])
    return int(record.get("troute_feature_id") or record["hydrofabric_feature_id"])


def _require_per_site_coverage(
    catalog: list[dict[str, Any]],
    data_records: list[dict[str, Any]],
) -> None:
    expected_sites = sorted({str(record["site_id"]) for record in data_records})
    row_counts = {site_id: 0 for site_id in expected_sites}
    for record in catalog:
        row_counts[str(record["site_id"])] += int(record.get("row_count") or 0)
    missing = [site_id for site_id, row_count in row_counts.items() if row_count <= 0]
    if missing:
        raise TidyError(
            "tidy coverage failed; no target feature rows for site(s): "
            + ", ".join(missing)
        )


def _duplicate_timestamp_count(tidy_rows: list[dict[str, Any]]) -> int:
    seen: set[str] = set()
    duplicates = 0
    for row in tidy_rows:
        timestamp = str(row.get("time_utc"))
        if timestamp in seen:
            duplicates += 1
        seen.add(timestamp)
    return duplicates


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
