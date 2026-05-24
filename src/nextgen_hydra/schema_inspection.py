"""Raw troute output schema inspection before tidy transforms."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any, Iterable

from .config import Site
from .download import safe_local_path
from .manifest import validate_manifest_records


class SchemaInspectionError(RuntimeError):
    """Raised when raw output schema inspection cannot prove coverage."""


def build_schema_inspection_report(
    *,
    manifest_records: list[dict[str, Any]],
    defaults: dict[str, Any],
    sites: list[Site],
    raw_dir: Path,
) -> dict[str, Any]:
    validated = validate_manifest_records(manifest_records, defaults, sites=sites)
    troute_records = [
        record
        for record in validated
        if record["product_type"] == "troute_streamflow_output"
    ]
    errors: list[str] = []
    if not troute_records:
        errors.append("manifest contains no troute_streamflow_output records")

    objects: list[dict[str, Any]] = []
    for group in _group_by_object(troute_records):
        local_path = safe_local_path(raw_dir, group["object_key"])
        if not local_path.exists():
            message = f"raw file is missing for schema inspection: {local_path}"
            errors.append(message)
            objects.append(_failed_object(group, local_path, [message]))
            continue
        try:
            if group["format"] == "parquet":
                inspected = _inspect_parquet(local_path, group)
            elif group["format"] == "nc":
                inspected = _inspect_netcdf(local_path, group)
            else:
                raise SchemaInspectionError(
                    f"unsupported source format for schema inspection: {group['format']}"
                )
        except SchemaInspectionError as exc:
            errors.append(str(exc))
            objects.append(_failed_object(group, local_path, [str(exc)]))
            continue
        objects.append(inspected)
        errors.extend(inspected["errors"])

    by_site = _summarize_sites(troute_records, objects)
    for site_id, site_report in by_site.items():
        if site_report["status"] != "pass":
            errors.append(f"schema inspection failed for site {site_id}")

    unique_errors = sorted(dict.fromkeys(errors))
    return {
        "report_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "status": "pass" if not unique_errors else "fail",
        "errors": unique_errors,
        "object_count": len(objects),
        "objects": objects,
        "by_site": by_site,
    }


def assert_schema_inspection_passed(report: dict[str, Any]) -> None:
    if report.get("status") != "pass":
        errors = report.get("errors") or ["schema inspection failed"]
        raise SchemaInspectionError("schema inspection failed:\n" + "\n".join(errors))


def write_schema_inspection_report(
    *,
    report: dict[str, Any],
    json_path: Path,
    markdown_path: Path | None = None,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    if markdown_path is not None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_schema_inspection_markdown(report), encoding="utf-8")


def render_schema_inspection_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# NextGen Hydra Schema Inspection",
        "",
        f"Created UTC: `{report['created_at_utc']}`",
        f"Status: `{report['status']}`",
        f"Objects: {report['object_count']}",
        "",
        "## By Site",
        "",
    ]
    for site_id, site_report in sorted(report["by_site"].items()):
        lines.append(
            "- "
            + f"`{site_id}`: status={site_report['status']}, "
            + f"objects_present={site_report['objects_present']}/"
            + f"{site_report['objects_expected']}, rows={site_report['row_count']}, "
            + f"time={site_report['start_time_utc']}..{site_report['end_time_utc']}"
        )
    lines.extend(["", "## Objects", ""])
    for obj in report["objects"]:
        lines.append(
            "- "
            + f"`{obj['object_key']}`: status={obj['status']}, "
            + f"format={obj['format']}, rows={obj.get('row_count')}, "
            + f"feature={obj.get('selected_feature_column')}, "
            + f"time={obj.get('selected_time_column')}, "
            + f"flow={obj.get('selected_flow_column')}"
        )
    if report["errors"]:
        lines.extend(["", "## Errors", ""])
        for error in report["errors"]:
            lines.append(f"- {error}")
    lines.append("")
    return "\n".join(lines)


def _group_by_object(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for record in records:
        group = grouped.setdefault(
            str(record["object_key"]),
            {
                "object_key": record["object_key"],
                "format": record["format"],
                "stream": record["stream"],
                "run_date": record["run_date"],
                "run_type": record["run_type"],
                "cycle": record["cycle"],
                "vpu_id": record["vpu_id"],
                "sites": [],
            },
        )
        group["sites"].append(
            {
                "site_id": record["site_id"],
                "usgs_gage_id": record["usgs_gage_id"],
                "hydrofabric_feature_id": int(record["hydrofabric_feature_id"]),
            }
        )
    return list(grouped.values())


def _failed_object(
    group: dict[str, Any],
    local_path: Path,
    errors: list[str],
) -> dict[str, Any]:
    return {
        "object_key": group["object_key"],
        "format": group["format"],
        "local_path": str(local_path),
        "status": "fail",
        "errors": errors,
        "columns": [],
        "variables": {},
        "dtypes": {},
        "row_count": None,
        "candidate_feature_columns": [],
        "candidate_time_columns": [],
        "candidate_flow_columns": [],
        "selected_feature_column": None,
        "selected_time_column": None,
        "selected_flow_column": None,
        "target_feature_coverage": {
            "present_feature_ids": [],
            "absent_feature_ids": [
                site["hydrofabric_feature_id"] for site in group["sites"]
            ],
            "feature_row_counts": {},
        },
        "time_coverage": {"start_time_utc": None, "end_time_utc": None},
        "null_counts": {},
        "units": {},
        "by_site": {},
    }


def _inspect_parquet(path: Path, group: dict[str, Any]) -> dict[str, Any]:
    try:
        import pandas as pd  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise SchemaInspectionError(
            "Parquet schema inspection requires pandas and pyarrow"
        ) from exc

    frame = pd.read_parquet(path)
    columns = [str(column) for column in frame.columns]
    dtypes = {str(column): str(dtype) for column, dtype in frame.dtypes.items()}
    null_counts = {
        str(column): int(value) for column, value in frame.isna().sum().items()
    }
    return _inspect_table(
        path=path,
        group=group,
        columns=columns,
        variables={},
        dtypes=dtypes,
        row_count=len(frame),
        null_counts=null_counts,
        units=_pandas_units(frame),
        table=frame,
    )


def _inspect_netcdf(path: Path, group: dict[str, Any]) -> dict[str, Any]:
    try:
        import xarray as xr  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise SchemaInspectionError(
            "NetCDF schema inspection requires xarray and netCDF4"
        ) from exc

    dataset = xr.open_dataset(path)
    try:
        variables = {
            name: {
                "dims": list(value.dims),
                "dtype": str(value.dtype),
            }
            for name, value in {**dataset.coords, **dataset.data_vars}.items()
        }
        units = {
            name: str(value.attrs["units"])
            for name, value in {**dataset.coords, **dataset.data_vars}.items()
            if value.attrs.get("units")
        }
        frame = dataset.to_dataframe().reset_index()
        columns = [str(column) for column in frame.columns]
        dtypes = {str(column): str(dtype) for column, dtype in frame.dtypes.items()}
        null_counts = {
            str(column): int(value) for column, value in frame.isna().sum().items()
        }
        return _inspect_table(
            path=path,
            group=group,
            columns=columns,
            variables=variables,
            dtypes=dtypes,
            row_count=len(frame),
            null_counts=null_counts,
            units=units,
            table=frame,
        )
    finally:
        dataset.close()


def _inspect_table(
    *,
    path: Path,
    group: dict[str, Any],
    columns: list[str],
    variables: dict[str, Any],
    dtypes: dict[str, str],
    row_count: int,
    null_counts: dict[str, int],
    units: dict[str, str],
    table: Any,
) -> dict[str, Any]:
    feature_candidates = _candidate_feature_columns(columns)
    time_candidates = _candidate_time_columns(columns, dtypes)
    flow_candidates = _candidate_flow_columns(columns)
    errors = _candidate_errors(
        object_key=group["object_key"],
        feature_candidates=feature_candidates,
        time_candidates=time_candidates,
        flow_candidates=flow_candidates,
    )
    feature_column = feature_candidates[0] if len(feature_candidates) == 1 else None
    time_column = time_candidates[0] if len(time_candidates) == 1 else None
    flow_column = flow_candidates[0] if len(flow_candidates) == 1 else None

    target_ids = [site["hydrofabric_feature_id"] for site in group["sites"]]
    coverage = _empty_coverage(target_ids)
    site_reports: dict[str, Any] = {}
    duplicate_timestamp_count = None
    if feature_column is not None:
        coverage = _feature_coverage(table[feature_column], target_ids)
        absent = coverage["absent_feature_ids"]
        if absent:
            errors.append(
                f"{group['object_key']}: target feature IDs absent: {absent}"
            )
        if time_column is not None:
            duplicate_timestamp_count = int(
                table.duplicated(subset=[feature_column, time_column]).sum()
            )
        for site in group["sites"]:
            site_reports[site["site_id"]] = _site_schema_report(
                table=table,
                site=site,
                feature_column=feature_column,
                time_column=time_column,
            )

    return {
        "object_key": group["object_key"],
        "format": group["format"],
        "local_path": str(path),
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "columns": columns,
        "variables": variables,
        "dtypes": dtypes,
        "row_count": row_count,
        "candidate_feature_columns": feature_candidates,
        "candidate_time_columns": time_candidates,
        "candidate_flow_columns": flow_candidates,
        "selected_feature_column": feature_column,
        "selected_time_column": time_column,
        "selected_flow_column": flow_column,
        "target_feature_coverage": coverage,
        "time_coverage": _time_coverage(table[time_column]) if time_column else {},
        "duplicate_timestamp_count": duplicate_timestamp_count,
        "null_counts": null_counts,
        "units": units,
        "by_site": site_reports,
    }


def _candidate_errors(
    *,
    object_key: str,
    feature_candidates: list[str],
    time_candidates: list[str],
    flow_candidates: list[str],
) -> list[str]:
    errors: list[str] = []
    if len(feature_candidates) != 1:
        errors.append(
            f"{object_key}: ambiguous feature column candidates: {feature_candidates}"
        )
    if len(time_candidates) != 1:
        errors.append(
            f"{object_key}: ambiguous time column candidates: {time_candidates}"
        )
    if len(flow_candidates) != 1:
        errors.append(
            f"{object_key}: ambiguous streamflow column candidates: {flow_candidates}"
        )
    return errors


def _candidate_feature_columns(columns: Iterable[str]) -> list[str]:
    approved = {
        "feature_id",
        "featureid",
        "hydrofabric_feature_id",
        "hydrofabric_featureid",
        "comid",
        "nwm_feature_id",
        "link",
    }
    return [column for column in columns if _normalise_name(column) in approved]


def _candidate_time_columns(columns: Iterable[str], dtypes: dict[str, str]) -> list[str]:
    approved = {"time", "time_utc", "timestamp", "datetime", "valid_time"}
    candidates = []
    for column in columns:
        dtype = dtypes.get(column, "").lower()
        if _normalise_name(column) in approved or "datetime" in dtype:
            candidates.append(column)
    return candidates


def _candidate_flow_columns(columns: Iterable[str]) -> list[str]:
    approved = {
        "streamflow",
        "stream_flow",
        "flow",
        "flow_rate",
        "discharge",
        "q",
    }
    return [column for column in columns if _normalise_name(column) in approved]


def _feature_coverage(feature_values: Any, target_ids: list[int]) -> dict[str, Any]:
    as_text = feature_values.astype(str)
    counts = {
        str(feature_id): int((as_text == str(feature_id)).sum())
        for feature_id in target_ids
    }
    return {
        "present_feature_ids": [
            int(feature_id) for feature_id, count in counts.items() if count > 0
        ],
        "absent_feature_ids": [
            int(feature_id) for feature_id, count in counts.items() if count == 0
        ],
        "feature_row_counts": counts,
    }


def _empty_coverage(target_ids: list[int]) -> dict[str, Any]:
    return {
        "present_feature_ids": [],
        "absent_feature_ids": target_ids,
        "feature_row_counts": {str(feature_id): 0 for feature_id in target_ids},
    }


def _site_schema_report(
    *,
    table: Any,
    site: dict[str, Any],
    feature_column: str,
    time_column: str | None,
) -> dict[str, Any]:
    feature_id = str(site["hydrofabric_feature_id"])
    rows = table[table[feature_column].astype(str) == feature_id]
    time_coverage = _time_coverage(rows[time_column]) if time_column else {}
    duplicate_count = (
        int(rows.duplicated(subset=[time_column]).sum()) if time_column else None
    )
    return {
        "site_id": site["site_id"],
        "hydrofabric_feature_id": int(site["hydrofabric_feature_id"]),
        "status": "pass" if len(rows) > 0 else "fail",
        "row_count": int(len(rows)),
        "time_coverage": time_coverage,
        "duplicate_timestamp_count": duplicate_count,
    }


def _time_coverage(values: Any) -> dict[str, str | None]:
    non_null = values.dropna()
    if len(non_null) == 0:
        return {"start_time_utc": None, "end_time_utc": None}
    try:
        import pandas as pd  # type: ignore

        parsed = pd.to_datetime(non_null, errors="coerce", utc=True).dropna()
        if len(parsed) > 0:
            return {
                "start_time_utc": parsed.min().isoformat(),
                "end_time_utc": parsed.max().isoformat(),
            }
    except ImportError:  # pragma: no cover - pandas is already required here
        pass
    text_values = sorted(str(value) for value in non_null)
    return {"start_time_utc": text_values[0], "end_time_utc": text_values[-1]}


def _summarize_sites(
    records: list[dict[str, Any]],
    objects: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    expected_counts: defaultdict[str, int] = defaultdict(int)
    for record in records:
        expected_counts[str(record["site_id"])] += 1
        summary.setdefault(
            str(record["site_id"]),
            {
                "usgs_gage_id": record["usgs_gage_id"],
                "hydrofabric_feature_id": int(record["hydrofabric_feature_id"]),
                "vpu_id": record["vpu_id"],
                "objects_expected": 0,
                "objects_present": 0,
                "row_count": 0,
                "start_time_utc": None,
                "end_time_utc": None,
                "duplicate_timestamp_count": 0,
                "status": "fail",
            },
        )
    for site_id, count in expected_counts.items():
        summary[site_id]["objects_expected"] = count

    for obj in objects:
        for site_id, site_report in obj.get("by_site", {}).items():
            target = summary[site_id]
            if site_report["status"] == "pass":
                target["objects_present"] += 1
            target["row_count"] += int(site_report.get("row_count") or 0)
            target["duplicate_timestamp_count"] += int(
                site_report.get("duplicate_timestamp_count") or 0
            )
            coverage = site_report.get("time_coverage") or {}
            start = coverage.get("start_time_utc")
            end = coverage.get("end_time_utc")
            if start and (target["start_time_utc"] is None or start < target["start_time_utc"]):
                target["start_time_utc"] = start
            if end and (target["end_time_utc"] is None or end > target["end_time_utc"]):
                target["end_time_utc"] = end

    for site_id, site_report in summary.items():
        site_report["status"] = (
            "pass"
            if site_report["objects_expected"] > 0
            and site_report["objects_present"] == site_report["objects_expected"]
            and site_report["row_count"] > 0
            else "fail"
        )
    return summary


def _pandas_units(frame: Any) -> dict[str, str]:
    units = frame.attrs.get("units") if hasattr(frame, "attrs") else None
    if isinstance(units, dict):
        return {str(key): str(value) for key, value in units.items()}
    return {}


def _normalise_name(name: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", name.lower())).strip("_")
