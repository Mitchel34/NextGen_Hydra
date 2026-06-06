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


def list_datasets(root: Path | None = None) -> list[dict[str, Any]]:
    root = root or project_root()
    manifest = _read_optional_jsonl(root / "manifests/manifest.jsonl")
    catalog = _read_optional_jsonl(root / "data/tidy/catalog.jsonl")
    schema = schema_inspection(root)
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


def preview_export(payload: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    preview = _build_preview(payload, root)
    return {
        "available": preview.available,
        "reasons": preview.reasons,
        "row_count": preview.row_count,
        "record_count": len(preview.records),
        "format": preview.export_format,
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
        frames.append(_filter_time_range(frame, payload))
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
        "export_available": group["export_available"],
        "tidy_records": group["tidy_records"],
        "tidy_rows": group["tidy_rows"],
    }


def _export_id(payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"export_{digest[:16]}"


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
