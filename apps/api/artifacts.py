"""Local artifact readers for the public API.

The public portal intentionally reads CLI-produced files only. Discovery,
approval-gated downloads, and crosswalk resolution remain CLI/admin actions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

import yaml


class ArtifactError(RuntimeError):
    """Raised when a cached public artifact is unavailable or unsafe."""


@dataclass(frozen=True)
class ExportPreview:
    available: bool
    reasons: list[str]
    records: list[dict[str, Any]]
    row_count: int
    export_format: str


SOURCE_KEYS = {"nextgen", "nwm", "era5", "usgs"}


def project_root() -> Path:
    return Path(os.environ.get("NEXTGEN_HYDRA_ROOT", Path.cwd())).resolve()


def load_sites(root: Path | None = None) -> list[dict[str, Any]]:
    root = root or project_root()
    data = _read_yaml(root / "configs/sites.yaml")
    crosswalk = _read_optional_yaml(root / "configs/site_crosswalk.yaml")
    by_site = {
        str(record.get("site_id")): record
        for record in (crosswalk.get("sites") or [])
        if isinstance(record, dict) and record.get("site_id")
    }
    rows: list[dict[str, Any]] = []
    for site in data.get("sites", []):
        crosswalk_record = by_site.get(str(site["site_id"]), {})
        rows.append(
            {
                "site_id": site["site_id"],
                "name": site["name"],
                "usgs_gage_id": str(site["usgs_gage_id"]),
                "hydrofabric_feature_id": int(site["hydrofabric_feature_id"]),
                "vpu_id": site["discovered_vpu_id"],
                "mapping_status": site["mapping_status"],
                "troute_feature_id": crosswalk_record.get("troute_feature_id"),
                "crosswalk_status": crosswalk_record.get("status", "missing"),
            }
        )
    return rows


def site_directory(
    root: Path | None = None,
    *,
    query: str | None = None,
    source: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Search local site directory records.

    The directory is a local catalog contract, not a live remote search. Large
    external inventories can be materialized to data/catalog/site_directory.jsonl
    by an admin workflow later; until then the configured sites are the fallback.
    """
    root = root or project_root()
    rows = _site_directory_records(root)
    source_key = str(source or "").lower().strip()
    if source_key and source_key not in SOURCE_KEYS:
        raise ArtifactError(f"unsupported source: {source}")
    needle = str(query or "").lower().strip()
    if source_key:
        rows = [
            row for row in rows if bool((row.get("availability") or {}).get(source_key))
        ]
    if needle:
        rows = [row for row in rows if _directory_match(row, needle)]
    limit = max(1, min(int(limit or 50), 250))
    return {
        "status": "available",
        "directory_source": _site_directory_source(root),
        "query": query,
        "source": source_key or None,
        "limit": limit,
        "count": len(rows[:limit]),
        "sites": rows[:limit],
        "supported_sources": sorted(SOURCE_KEYS),
    }


def site_directory_detail(identifier: str, root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    needle = str(identifier).lower().strip()
    for row in _site_directory_records(root):
        if _directory_identifier_match(row, needle):
            return row
    raise ArtifactError(f"site directory entry is not available: {identifier}")


def create_acquisition_request(
    payload: dict[str, Any],
    root: Path | None = None,
) -> dict[str, Any]:
    """Create a public acquisition request without executing acquisition work."""
    root = root or project_root()
    request = _normalise_acquisition_request(payload, root)
    request_id = _acquisition_request_id(request)
    created_at = datetime.now(UTC).isoformat()
    record = {
        "id": request_id,
        "created_at_utc": created_at,
        "status": "queued_for_admin_review",
        "request": request,
        "public_execution": False,
        "object_body_downloads": False,
        "requires_admin_cli": True,
        "next_admin_steps": [
            "validate requested identifiers against approved source directories",
            "resolve NextGen COMIDs to VPUs and troute feature IDs when applicable",
            "build classifier-gated manifest or source-specific dry-run plan",
            "require explicit approval ID before any object-body download",
        ],
    }
    request_dir = root / "data/requests"
    request_dir.mkdir(parents=True, exist_ok=True)
    request_path = request_dir / f"{request_id}.json"
    request_path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    with (request_dir / "acquisition_requests.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return {**record, "path": str(request_path)}


def public_status(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    catalog = artifact_catalog(root)
    return {
        "status": catalog["status"],
        "generated_at_utc": catalog["generated_at_utc"],
        "site_count": len(catalog["sites"]),
        "dataset_count": len(catalog["datasets"]),
        "schema_status": catalog["schema"].get("status"),
        "units_status": catalog["units"].get("status"),
        "qc_status": catalog["qc"].get("status"),
        "tidy_available": any(row.get("tidy_available") for row in catalog["datasets"]),
        "export_available": any(row.get("export_available") for row in catalog["datasets"]),
        "forbidden_public_operations": [
            "discover",
            "download",
            "download-resources",
            "approval-submission",
            "resolve-site-crosswalk",
        ],
        "public_acquisition_requests": True,
    }


def artifact_catalog(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    catalog_path = root / "reports/artifact_catalog.json"
    if catalog_path.is_file():
        return _read_json(catalog_path)
    return build_artifact_catalog(root)


def build_artifact_catalog(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    datasets = list_datasets(root)
    sites = _sites_with_qc(load_sites(root), quality_report(root))
    qc = quality_report(root)
    units = streamflow_units_status(root)
    schema = schema_inspection(root)
    exports = _available_exports(root)
    status = "ready" if datasets and all(row.get("export_available") for row in datasets) else "incomplete"
    return {
        "catalog_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "status": status,
        "sites": sites,
        "datasets": datasets,
        "schema": {
            "status": schema.get("status", "missing"),
            "object_count": schema.get("object_count", 0),
            "errors": schema.get("errors", []),
        },
        "units": units,
        "qc": _qc_summary(qc),
        "exports": exports,
    }


def write_artifact_catalog(path: Path, root: Path | None = None) -> dict[str, Any]:
    catalog = build_artifact_catalog(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalog, indent=2, sort_keys=True), encoding="utf-8")
    return catalog


def list_datasets(root: Path | None = None) -> list[dict[str, Any]]:
    root = root or project_root()
    manifest = _read_optional_jsonl(root / "manifests/manifest.jsonl")
    catalog = _read_optional_jsonl(root / "data/tidy/catalog.jsonl")
    schema = schema_inspection(root)
    units = streamflow_units_status(root)
    crosswalk_ready = all(
        site.get("crosswalk_status") == "resolved" for site in load_sites(root)
    )
    tidy_available = (
        schema.get("status") == "pass"
        and crosswalk_ready
        and units.get("status") == "documented"
    )
    catalog_by_group = _catalog_groups(catalog, root)
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for record in manifest:
        if record.get("product_type") != "troute_streamflow_output":
            continue
        key = (
            str(record.get("stream")),
            str(record.get("run_date")),
            str(record.get("run_type")),
            str(record.get("cycle")),
        )
        group = grouped.setdefault(
            key,
            {
                "stream": key[0],
                "run_date": key[1],
                "run_type": key[2],
                "cycle": key[3],
                "site_ids": set(),
                "vpu_ids": set(),
                "raw_object_keys": set(),
                "raw_manifest_records": 0,
                "schema_status": schema.get("status"),
                "crosswalk_status": "resolved" if crosswalk_ready else "incomplete",
                "units_status": units.get("status"),
                "tidy_available": tidy_available,
                "export_available": False,
                "tidy_records": 0,
                "tidy_rows": 0,
            },
        )
        group["site_ids"].add(str(record.get("site_id")))
        group["vpu_ids"].add(str(record.get("vpu_id")))
        group["raw_object_keys"].add(str(record.get("object_key")))
        group["raw_manifest_records"] += 1
    for key, catalog_group in catalog_by_group.items():
        group = grouped.setdefault(
            key,
            {
                "stream": key[0],
                "run_date": key[1],
                "run_type": key[2],
                "cycle": key[3],
                "site_ids": set(),
                "vpu_ids": set(),
                "raw_object_keys": set(),
                "raw_manifest_records": 0,
                "schema_status": schema.get("status"),
                "crosswalk_status": "resolved" if crosswalk_ready else "incomplete",
                "units_status": units.get("status"),
                "tidy_available": tidy_available,
                "export_available": False,
                "tidy_records": 0,
                "tidy_rows": 0,
            },
        )
        group["site_ids"].update(catalog_group["site_ids"])
        group["vpu_ids"].update(catalog_group["vpu_ids"])
        group["tidy_records"] = catalog_group["record_count"]
        group["tidy_rows"] = catalog_group["row_count"]
        group["export_available"] = catalog_group["available"]
    return [_serialise_dataset(group) for group in grouped.values()]


def schema_inspection(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    path = root / "reports/schema_inspection.json"
    if not path.is_file():
        return {"status": "missing", "object_count": 0, "errors": []}
    return _read_json(path)


def streamflow_units_status(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    data = _read_optional_yaml(root / "configs/streamflow_units.yaml")
    if not data:
        return {"status": "missing", "variable": "flow", "units": None}
    return {
        "status": data.get("status", "missing"),
        "variable": data.get("variable"),
        "units": data.get("units"),
        "evidence_count": len(data.get("evidence") or []),
        "evidence": data.get("evidence") or [],
    }


def quality_report(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    path = root / "reports/qc_report.json"
    if not path.is_file():
        return {"status": "missing", "per_site": {}, "errors": []}
    data = _read_json(path)
    return {"status": "available", **data}


def export_options(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    datasets = list_datasets(root)
    catalog = _read_optional_jsonl(root / "data/tidy/catalog.jsonl")
    available_columns = sorted(_tidy_columns(root, catalog))
    return {
        "sites": load_sites(root),
        "streams": sorted({row["stream"] for row in datasets}),
        "formats": ["csv", "parquet"],
        "preprocessing": {
            "missing_streamflow": ["keep", "drop"],
            "aggregation": ["none", "daily_mean"],
        },
        "columns": available_columns,
        "defaults": {
            "format": "csv",
            "missing_streamflow": "keep",
            "aggregation": "none",
            "columns": available_columns,
        },
        "time_coverage": _time_coverage(catalog),
    }


def preview_export(payload: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    preview = _build_preview(payload, root)
    return {
        "available": preview.available,
        "reasons": preview.reasons,
        "row_count": preview.row_count,
        "record_count": len(preview.records),
        "format": preview.export_format,
        "preprocessing": _preprocessing_options(payload),
        "columns": _requested_columns(payload),
        "files": [record["tidy_path"] for record in preview.records],
    }


def create_export(payload: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    preview = _build_preview(payload, root)
    if not preview.available:
        raise ArtifactError("; ".join(preview.reasons))
    export_id = _export_id(payload)
    export_dir = root / "data/exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    extension = "parquet" if preview.export_format == "parquet" else "csv"
    output = export_dir / f"{export_id}.{extension}"
    if not output.exists():
        _write_export(output, preview.records, payload, preview.export_format)
    return {
        "id": export_id,
        "format": preview.export_format,
        "path": str(output),
        "row_count": _export_row_count(output, preview.export_format),
        "metadata_path": str(_write_export_metadata(output, payload, preview)),
    }


def export_path(export_id: str, root: Path | None = None) -> Path:
    root = root or project_root()
    if not export_id or any(char in export_id for char in "/\\"):
        raise ArtifactError("invalid export id")
    export_dir = (root / "data/exports").resolve()
    for suffix in ("csv", "parquet"):
        path = (export_dir / f"{export_id}.{suffix}").resolve()
        if path.is_file() and export_dir in path.parents:
            return path
    raise ArtifactError(f"export is not available: {export_id}")


def _build_preview(payload: dict[str, Any], root: Path) -> ExportPreview:
    export_format = str(payload.get("format") or "csv").lower()
    if export_format not in {"csv", "parquet"}:
        return ExportPreview(False, [f"unsupported export format: {export_format}"], [], 0, export_format)
    catalog = _read_optional_jsonl(root / "data/tidy/catalog.jsonl")
    if not catalog:
        return ExportPreview(False, ["no approved tidy catalog is available"], [], 0, export_format)
    site_ids = {str(value) for value in payload.get("site_ids", []) if value}
    streams = {str(value) for value in payload.get("streams", []) if value}
    preprocessing = _preprocessing_options(payload)
    columns = _requested_columns(payload)
    if preprocessing["missing_streamflow"] not in {"keep", "drop"}:
        return ExportPreview(False, ["unsupported missing streamflow option"], [], 0, export_format)
    if preprocessing["aggregation"] not in {"none", "daily_mean"}:
        return ExportPreview(False, ["unsupported aggregation option"], [], 0, export_format)
    start = payload.get("start_time_utc")
    end = payload.get("end_time_utc")
    if start and end and str(start) > str(end):
        return ExportPreview(False, ["start_time_utc must be before end_time_utc"], [], 0, export_format)
    if columns:
        available_columns = _tidy_columns(root, catalog)
        if preprocessing["aggregation"] == "daily_mean":
            available_columns = set(available_columns)
            available_columns.add("streamflow_daily_mean")
        invalid = sorted(set(columns) - available_columns)
        if invalid:
            return ExportPreview(False, [f"unsupported columns: {invalid}"], [], 0, export_format)
    records = []
    reasons: list[str] = []
    for record in catalog:
        if site_ids and str(record.get("site_id")) not in site_ids:
            continue
        if streams and str(record.get("stream")) not in streams:
            continue
        if record.get("coverage_status") != "pass":
            continue
        tidy_path = _safe_project_path(root, str(record.get("tidy_path") or ""))
        if not tidy_path.is_file():
            reasons.append(f"tidy file missing for {record.get('site_id')}")
            continue
        records.append({**record, "tidy_path": str(tidy_path)})
    if not records:
        reasons.append("no cached approved tidy files match the request")
    row_count = sum(int(record.get("row_count") or 0) for record in records)
    return ExportPreview(not reasons and bool(records), reasons, records, row_count, export_format)


def _write_export(
    output: Path,
    records: list[dict[str, Any]],
    payload: dict[str, Any],
    export_format: str,
) -> None:
    try:
        import pandas as pd  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional data dependency
        raise ArtifactError("export generation requires pandas") from exc
    frames = []
    for record in records:
        path = Path(record["tidy_path"])
        if path.suffix == ".parquet":
            frame = pd.read_parquet(path)
        elif path.suffix == ".csv":
            frame = pd.read_csv(path)
        else:
            raise ArtifactError(f"unsupported tidy file format: {path}")
        frames.append(_apply_preprocessing(frame, payload))
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if export_format == "parquet":
        combined.to_parquet(output, index=False)
    else:
        combined.to_csv(output, index=False)


def _filter_time_range(frame: Any, payload: dict[str, Any]) -> Any:
    if "time_utc" not in frame.columns:
        return frame
    try:
        import pandas as pd  # type: ignore
    except ImportError:  # pragma: no cover
        return frame
    times = pd.to_datetime(frame["time_utc"], errors="coerce", utc=True)
    start = payload.get("start_time_utc")
    end = payload.get("end_time_utc")
    mask = times.notna()
    if start:
        mask &= times >= pd.to_datetime(start, utc=True)
    if end:
        mask &= times <= pd.to_datetime(end, utc=True)
    return frame[mask]


def _apply_preprocessing(frame: Any, payload: dict[str, Any]) -> Any:
    frame = _filter_time_range(frame, payload)
    preprocessing = _preprocessing_options(payload)
    if preprocessing["missing_streamflow"] == "drop" and "streamflow" in frame.columns:
        frame = frame[frame["streamflow"].notna()]
    if preprocessing["aggregation"] == "daily_mean":
        frame = _daily_mean(frame)
    columns = _requested_columns(payload)
    if columns:
        if preprocessing["aggregation"] == "daily_mean":
            columns = [
                "streamflow_daily_mean" if column == "streamflow" else column
                for column in columns
            ]
        frame = frame[[column for column in columns if column in frame.columns]]
    return frame


def _daily_mean(frame: Any) -> Any:
    if "time_utc" not in frame.columns or "streamflow" not in frame.columns:
        return frame
    try:
        import pandas as pd  # type: ignore
    except ImportError:  # pragma: no cover
        return frame
    grouped = frame.copy()
    grouped["time_utc"] = pd.to_datetime(grouped["time_utc"], errors="coerce", utc=True)
    grouped = grouped[grouped["time_utc"].notna()]
    if grouped.empty:
        return grouped
    grouped["date_utc"] = grouped["time_utc"].dt.strftime("%Y-%m-%d")
    keys = [
        column
        for column in (
            "site_id",
            "usgs_gage_id",
            "hydrofabric_feature_id",
            "troute_feature_id",
            "vpu_id",
            "stream",
            "run_date",
            "run_type",
            "cycle",
            "streamflow_units",
        )
        if column in grouped.columns
    ]
    aggregated = (
        grouped.groupby([*keys, "date_utc"], dropna=False, as_index=False)["streamflow"]
        .mean()
        .rename(columns={"streamflow": "streamflow_daily_mean"})
    )
    return aggregated


def _export_row_count(path: Path, export_format: str) -> int:
    try:
        import pandas as pd  # type: ignore
    except ImportError:  # pragma: no cover
        return 0
    if export_format == "parquet":
        return int(len(pd.read_parquet(path)))
    return int(len(pd.read_csv(path)))


def _catalog_groups(records: list[dict[str, Any]], root: Path) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for record in records:
        key = (
            str(record.get("stream")),
            str(record.get("run_date")),
            str(record.get("run_type")),
            str(record.get("cycle")),
        )
        group = grouped.setdefault(
            key,
            {
                "site_ids": set(),
                "vpu_ids": set(),
                "record_count": 0,
                "row_count": 0,
                "available": True,
            },
        )
        group["site_ids"].add(str(record.get("site_id")))
        group["vpu_ids"].add(str(record.get("vpu_id")))
        group["record_count"] += 1
        group["row_count"] += int(record.get("row_count") or 0)
        tidy_path = _safe_project_path(root, str(record.get("tidy_path") or ""))
        if record.get("coverage_status") != "pass" or not tidy_path.is_file():
            group["available"] = False
    return grouped


def _serialise_dataset(group: dict[str, Any]) -> dict[str, Any]:
    return {
        "stream": group["stream"],
        "run_date": group["run_date"],
        "run_type": group["run_type"],
        "cycle": group["cycle"],
        "site_ids": sorted(group["site_ids"]),
        "vpu_ids": sorted(group["vpu_ids"]),
        "raw_object_count": len(group["raw_object_keys"]),
        "raw_manifest_records": group["raw_manifest_records"],
        "schema_status": group["schema_status"],
        "crosswalk_status": group["crosswalk_status"],
        "units_status": group["units_status"],
        "tidy_available": group["tidy_available"],
        "export_available": group["export_available"],
        "tidy_records": group["tidy_records"],
        "tidy_rows": group["tidy_rows"],
    }


def _export_id(payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"export_{digest[:16]}"


def _preprocessing_options(payload: dict[str, Any]) -> dict[str, str]:
    preprocessing = payload.get("preprocessing")
    if not isinstance(preprocessing, dict):
        preprocessing = {}
    return {
        "missing_streamflow": str(preprocessing.get("missing_streamflow") or "keep"),
        "aggregation": str(preprocessing.get("aggregation") or "none"),
    }


def _requested_columns(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("columns")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ArtifactError("columns must be a list")
    return [str(column) for column in raw if column]


def _write_export_metadata(
    output: Path,
    payload: dict[str, Any],
    preview: ExportPreview,
) -> Path:
    metadata_path = output.with_suffix(output.suffix + ".metadata.json")
    metadata = {
        "metadata_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "export_id": output.stem,
        "export_path": str(output),
        "format": preview.export_format,
        "row_count": _export_row_count(output, preview.export_format),
        "record_count": len(preview.records),
        "payload": payload,
        "preprocessing": _preprocessing_options(payload),
        "columns": _requested_columns(payload),
        "source_tidy_files": [record["tidy_path"] for record in preview.records],
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    return metadata_path


def _tidy_columns(root: Path, catalog: list[dict[str, Any]]) -> set[str]:
    for record in catalog:
        tidy_path = _safe_project_path(root, str(record.get("tidy_path") or ""))
        if not tidy_path.is_file():
            continue
        try:
            import pandas as pd  # type: ignore
        except ImportError:  # pragma: no cover
            return set()
        if tidy_path.suffix == ".parquet":
            return set(pd.read_parquet(tidy_path, columns=None).columns)
        if tidy_path.suffix == ".csv":
            return set(pd.read_csv(tidy_path, nrows=0).columns)
    return set()


def _time_coverage(catalog: list[dict[str, Any]]) -> dict[str, str | None]:
    starts = [str(record["start_time_utc"]) for record in catalog if record.get("start_time_utc")]
    ends = [str(record["end_time_utc"]) for record in catalog if record.get("end_time_utc")]
    return {
        "start_time_utc": min(starts) if starts else None,
        "end_time_utc": max(ends) if ends else None,
    }


def _sites_with_qc(sites: list[dict[str, Any]], qc: dict[str, Any]) -> list[dict[str, Any]]:
    per_site = qc.get("per_site") or {}
    return [
        {
            **site,
            "qc": per_site.get(site["site_id"], {}),
        }
        for site in sites
    ]


def _qc_summary(qc: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": qc.get("status", "missing"),
        "approval_id": qc.get("approval_id"),
        "per_site": qc.get("per_site", {}),
        "tidy_catalog": qc.get("tidy_catalog", {}),
        "inventory": qc.get("inventory", {}),
    }


def _available_exports(root: Path) -> list[dict[str, Any]]:
    export_dir = root / "data/exports"
    if not export_dir.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(export_dir.glob("export_*.*")):
        if path.name.endswith(".metadata.json"):
            continue
        metadata_path = path.with_suffix(path.suffix + ".metadata.json")
        metadata = _read_json(metadata_path) if metadata_path.is_file() else {}
        rows.append(
            {
                "id": path.stem,
                "format": path.suffix.lstrip("."),
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "metadata": metadata,
            }
        )
    return rows


def _site_directory_source(root: Path) -> str:
    if (root / "data/catalog/site_directory.jsonl").is_file():
        return "data/catalog/site_directory.jsonl"
    return "configs/sites.yaml"


def _site_directory_records(root: Path) -> list[dict[str, Any]]:
    path = root / "data/catalog/site_directory.jsonl"
    if path.is_file():
        return [_normalise_directory_row(row) for row in _read_optional_jsonl(path)]
    rows = []
    for site in load_sites(root):
        rows.append(
            {
                "site_id": site["site_id"],
                "name": site["name"],
                "comid": site["hydrofabric_feature_id"],
                "hydrofabric_feature_id": site["hydrofabric_feature_id"],
                "troute_feature_id": site.get("troute_feature_id"),
                "usgs_gage_id": site["usgs_gage_id"],
                "vpu_id": site["vpu_id"],
                "availability": {
                    "nextgen": site.get("crosswalk_status") == "resolved",
                    "nwm": True,
                    "era5": False,
                    "usgs": bool(site.get("usgs_gage_id")),
                },
                "status": "configured",
                "source": "configs/sites.yaml",
            }
        )
    return rows


def _normalise_directory_row(row: dict[str, Any]) -> dict[str, Any]:
    availability = row.get("availability")
    if not isinstance(availability, dict):
        availability = row.get("sources") if isinstance(row.get("sources"), dict) else {}
    return {
        "site_id": str(row.get("site_id") or row.get("id") or ""),
        "name": str(row.get("name") or row.get("description") or ""),
        "comid": _optional_int(row.get("comid") or row.get("hydrofabric_feature_id")),
        "hydrofabric_feature_id": _optional_int(row.get("hydrofabric_feature_id") or row.get("comid")),
        "troute_feature_id": _optional_int(row.get("troute_feature_id")),
        "usgs_gage_id": None if row.get("usgs_gage_id") in (None, "") else str(row.get("usgs_gage_id")),
        "vpu_id": None if row.get("vpu_id") in (None, "") else str(row.get("vpu_id")),
        "availability": {key: bool(availability.get(key)) for key in SOURCE_KEYS},
        "status": str(row.get("status") or "available"),
        "source": str(row.get("source") or "data/catalog/site_directory.jsonl"),
    }


def _directory_match(row: dict[str, Any], needle: str) -> bool:
    haystack = " ".join(
        str(value)
        for value in (
            row.get("site_id"),
            row.get("name"),
            row.get("comid"),
            row.get("hydrofabric_feature_id"),
            row.get("troute_feature_id"),
            row.get("usgs_gage_id"),
            row.get("vpu_id"),
        )
        if value not in (None, "")
    ).lower()
    return needle in haystack


def _directory_identifier_match(row: dict[str, Any], needle: str) -> bool:
    return needle in {
        str(value).lower()
        for value in (
            row.get("site_id"),
            row.get("comid"),
            row.get("hydrofabric_feature_id"),
            row.get("troute_feature_id"),
            row.get("usgs_gage_id"),
        )
        if value not in (None, "")
    }


def _normalise_acquisition_request(payload: dict[str, Any], root: Path) -> dict[str, Any]:
    sources = _string_list(payload.get("sources"))
    if not sources:
        sources = ["nextgen"]
    invalid_sources = sorted(set(sources) - SOURCE_KEYS)
    if invalid_sources:
        raise ArtifactError(f"unsupported acquisition sources: {invalid_sources}")
    streams = _string_list(payload.get("streams")) or ["cfe_nom", "lstm_0"]
    formats = _string_list(payload.get("formats")) or ["parquet"]
    invalid_formats = sorted(set(formats) - {"csv", "parquet"})
    if invalid_formats:
        raise ArtifactError(f"unsupported requested formats: {invalid_formats}")
    site_ids = _string_list(payload.get("site_ids"))
    comids = [_coerce_identifier(value, "COMID") for value in _raw_list(payload.get("comids"))]
    usgs_gage_ids = [_coerce_usgs_gage(value) for value in _raw_list(payload.get("usgs_gage_ids"))]
    freeform_query = str(payload.get("query") or "").strip()
    matched_sites = _matched_directory_sites(root, site_ids, comids, usgs_gage_ids, freeform_query)
    if not matched_sites and not (comids or usgs_gage_ids or freeform_query):
        raise ArtifactError("request must include site_ids, comids, usgs_gage_ids, or query")
    start = _optional_string(payload.get("start_time_utc"))
    end = _optional_string(payload.get("end_time_utc"))
    if start and end and start > end:
        raise ArtifactError("start_time_utc must be before end_time_utc")
    return {
        "site_ids": site_ids,
        "comids": comids,
        "usgs_gage_ids": usgs_gage_ids,
        "query": freeform_query or None,
        "sources": sources,
        "streams": streams,
        "start_time_utc": start,
        "end_time_utc": end,
        "formats": formats,
        "preprocessing": _preprocessing_options(payload),
        "matched_directory_sites": matched_sites,
        "notes": _optional_string(payload.get("notes")),
    }


def _matched_directory_sites(
    root: Path,
    site_ids: list[str],
    comids: list[int],
    usgs_gage_ids: list[str],
    query: str,
) -> list[dict[str, Any]]:
    rows = _site_directory_records(root)
    needles = {value.lower() for value in site_ids}
    needles.update(str(value) for value in comids)
    needles.update(value.lower() for value in usgs_gage_ids)
    if query:
        q = query.lower()
        return [row for row in rows if _directory_match(row, q)]
    return [
        row
        for row in rows
        if any(_directory_identifier_match(row, needle) for needle in needles)
    ]


def _acquisition_request_id(request: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"acq_{digest[:16]}"


def _string_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ArtifactError("list-valued request fields must be lists")
    return [str(value).strip() for value in raw if str(value).strip()]


def _raw_list(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ArtifactError("list-valued request fields must be lists")
    return raw


def _optional_string(raw: Any) -> str | None:
    if raw in (None, ""):
        return None
    return str(raw).strip() or None


def _coerce_identifier(raw: Any, label: str) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise ArtifactError(f"{label} must be numeric: {raw}") from exc


def _coerce_usgs_gage(raw: Any) -> str:
    value = str(raw).strip()
    if not re.fullmatch(r"\d{7,15}", value):
        raise ArtifactError(f"USGS gage ID must be numeric: {raw}")
    return value


def _optional_int(raw: Any) -> int | None:
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _safe_project_path(root: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    if root.resolve() not in resolved.parents and resolved != root.resolve():
        raise ArtifactError(f"path escapes project root: {raw_path}")
    return resolved


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _read_optional_yaml(path: Path) -> dict[str, Any]:
    return _read_yaml(path) if path.is_file() else {}


def _read_optional_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
    return rows
