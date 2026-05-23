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
) -> dict[str, Any]:
    manifest_records = manifest_records or []
    inventory_records = inventory_records or []
    catalog_records = catalog_records or []
    manifest_missing = _missing_required(manifest_records, REQUIRED_MANIFEST_FIELDS)
    catalog_missing = _missing_required(catalog_records, REQUIRED_DATA_CATALOG_FIELDS)
    return {
        "report_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "manifest": {
            "record_count": len(manifest_records),
            "classification_counts": dict(
                Counter(record.get("classification") for record in manifest_records)
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
    return "\n".join(
        [
            "# NextGen Hydra QC Report",
            "",
            f"Created UTC: `{report['created_at_utc']}`",
            "",
            "## Manifest",
            "",
            f"- Records: {manifest['record_count']}",
            f"- Classification counts: `{manifest['classification_counts']}`",
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
        ]
    )


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
