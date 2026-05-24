"""QC and provenance report generation."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from .schemas import REQUIRED_DATA_CATALOG_FIELDS, REQUIRED_MANIFEST_FIELDS


def build_qc_report(
    *,
    manifest_records: list[dict[str, Any]] | None = None,
    inventory_records: list[dict[str, Any]] | None = None,
    catalog_records: list[dict[str, Any]] | None = None,
    schema_inspection: dict[str, Any] | None = None,
    download_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest_records = manifest_records or []
    inventory_records = inventory_records or []
    catalog_records = catalog_records or []
    schema_inspection = schema_inspection or {}
    download_summary = download_summary or {}
    manifest_missing = _missing_required(manifest_records, REQUIRED_MANIFEST_FIELDS)
    catalog_missing = _missing_required(catalog_records, REQUIRED_DATA_CATALOG_FIELDS)
    per_site = _per_site_report(manifest_records, catalog_records, schema_inspection)
    return {
        "report_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "approval_id": download_summary.get("approval_id"),
        "manifest": {
            "record_count": len(manifest_records),
            "classification_counts": dict(
                Counter(record.get("classification") for record in manifest_records)
            ),
            "product_type_counts": dict(
                Counter(record.get("product_type") for record in manifest_records)
            ),
            "approved_for_download_count": sum(
                1 for record in manifest_records if record.get("approved_for_download")
            ),
            "missing_required_fields": manifest_missing,
        },
        "inventory": {
            "record_count": len(inventory_records),
            "manifest_match_count": sum(
                1 for record in inventory_records if record.get("manifest_match")
            ),
            "size_mismatch_count": sum(
                1
                for record in inventory_records
                if record.get("size_matches_manifest") is False
            ),
        },
        "tidy_catalog": {
            "record_count": len(catalog_records),
            "row_count": sum(int(record.get("row_count") or 0) for record in catalog_records),
            "missing_value_count": sum(
                int(record.get("missing_count") or 0) for record in catalog_records
            ),
            "qc_status_counts": dict(
                Counter(record.get("qc_status") for record in catalog_records)
            ),
            "missing_required_fields": catalog_missing,
        },
        "schema_inspection": {
            "status": schema_inspection.get("status"),
            "object_count": schema_inspection.get("object_count", 0),
            "errors": schema_inspection.get("errors", []),
        },
        "per_site": per_site,
    }


def write_qc_report(
    *,
    report: dict[str, Any],
    markdown_path: Path,
    json_path: Path | None = None,
) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    if json_path:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    manifest = report["manifest"]
    inventory = report["inventory"]
    tidy = report["tidy_catalog"]
    lines = [
            "# NextGen Hydra QC Report",
            "",
            f"Created UTC: `{report['created_at_utc']}`",
            f"Approval ID: `{report.get('approval_id')}`",
            "",
            "## Manifest",
            "",
            f"- Records: {manifest['record_count']}",
            f"- Classification counts: `{manifest['classification_counts']}`",
            f"- Product type counts: `{manifest['product_type_counts']}`",
            f"- Approved for download: {manifest['approved_for_download_count']}",
            f"- Missing required fields: `{manifest['missing_required_fields']}`",
            "",
            "## Raw Inventory",
            "",
            f"- Records: {inventory['record_count']}",
            f"- Manifest matches: {inventory['manifest_match_count']}",
            f"- Size mismatches: {inventory['size_mismatch_count']}",
            "",
            "## Tidy Catalog",
            "",
            f"- Catalog records: {tidy['record_count']}",
            f"- Tidy rows: {tidy['row_count']}",
            f"- Missing streamflow values: {tidy['missing_value_count']}",
            f"- QC status counts: `{tidy['qc_status_counts']}`",
            f"- Missing required fields: `{tidy['missing_required_fields']}`",
            "",
            "## Schema Inspection",
            "",
            f"- Status: `{report['schema_inspection']['status']}`",
            f"- Objects: {report['schema_inspection']['object_count']}",
            f"- Errors: `{report['schema_inspection']['errors']}`",
            "",
            "## Per Site",
            "",
    ]
    for site_id, site in sorted(report["per_site"].items()):
        lines.append(
            "- "
            + f"`{site_id}`: rows={site['row_count']}, "
            + f"features={site['feature_coverage']}, "
            + f"time={site['start_time_utc']}..{site['end_time_utc']}, "
            + f"duplicates={site['duplicate_timestamp_count']}, "
            + f"missing_streamflow={site['missing_streamflow_count']}, "
            + f"streams=`{site['stream_coverage']}`, "
            + f"schema={site['schema_inspection_status']}"
        )
    lines.append("")
    return "\n".join(lines)


def _missing_required(
    records: list[dict[str, Any]],
    required_fields: tuple[str, ...],
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for record in records:
        for field in required_fields:
            if field not in record or record[field] in (None, ""):
                counts[field] += 1
    return dict(counts)


def _per_site_report(
    manifest_records: list[dict[str, Any]],
    catalog_records: list[dict[str, Any]],
    schema_inspection: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    per_site: dict[str, dict[str, Any]] = {}
    schema_by_site = schema_inspection.get("by_site") or {}
    for record in manifest_records:
        site_id = str(record.get("site_id"))
        site = per_site.setdefault(site_id, _empty_site_report(record))
        site["manifest_record_count"] += 1
        if record.get("product_type") == "troute_streamflow_output":
            site["stream_coverage"].add(str(record.get("stream")))
    for record in catalog_records:
        site_id = str(record.get("site_id"))
        site = per_site.setdefault(site_id, _empty_site_report(record))
        site["row_count"] += int(record.get("row_count") or 0)
        site["missing_streamflow_count"] += int(record.get("missing_count") or 0)
        site["duplicate_timestamp_count"] += int(
            record.get("duplicate_timestamp_count") or 0
        )
        if record.get("target_feature_present") is True or int(record.get("row_count") or 0) > 0:
            site["feature_coverage"] = "present"
        start = record.get("start_time_utc")
        end = record.get("end_time_utc")
        if start and (site["start_time_utc"] is None or start < site["start_time_utc"]):
            site["start_time_utc"] = start
        if end and (site["end_time_utc"] is None or end > site["end_time_utc"]):
            site["end_time_utc"] = end
        if record.get("stream"):
            site["stream_coverage"].add(str(record.get("stream")))
    for site_id, schema_site in schema_by_site.items():
        site = per_site.setdefault(site_id, _empty_site_report(schema_site))
        site["schema_inspection_status"] = schema_site.get("status")
        if schema_site.get("row_count"):
            site["schema_row_count"] = int(schema_site.get("row_count") or 0)
    for site in per_site.values():
        site["stream_coverage"] = sorted(site["stream_coverage"])
        if site["feature_coverage"] == "absent" and site.get("schema_row_count", 0) > 0:
            site["feature_coverage"] = "present"
    return per_site


def _empty_site_report(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "usgs_gage_id": record.get("usgs_gage_id"),
        "hydrofabric_feature_id": record.get("hydrofabric_feature_id"),
        "vpu_id": record.get("vpu_id"),
        "manifest_record_count": 0,
        "row_count": 0,
        "schema_row_count": 0,
        "feature_coverage": "absent",
        "start_time_utc": None,
        "end_time_utc": None,
        "duplicate_timestamp_count": 0,
        "missing_streamflow_count": 0,
        "schema_inspection_status": None,
        "stream_coverage": set(),
    }
