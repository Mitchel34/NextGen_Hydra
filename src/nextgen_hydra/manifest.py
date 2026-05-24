"""Manifest construction and validation."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Iterable

from .classifier import classify_object
from .config import (
    ConfigError,
    Site,
    proof_download_max_object_bytes,
    proof_download_max_total_bytes,
    require_all_sites_mapped,
)
from .io.s3 import public_url
from .schemas import MANIFEST_VERSION, REQUIRED_MANIFEST_FIELDS


class ManifestError(ValueError):
    """Raised when a manifest is unsafe or malformed."""


def build_manifest_records(
    discovery_records: Iterable[dict[str, Any]],
    sites: list[Site],
    defaults: dict[str, Any],
    *,
    approved_for_download: bool = True,
) -> list[dict[str, Any]]:
    try:
        require_all_sites_mapped(sites)
    except ConfigError as exc:
        raise ManifestError(str(exc)) from exc

    mapped_sites = [site for site in sites if site.is_mapped]
    if len(mapped_sites) != len(sites):
        unmapped = [site.site_id for site in sites if not site.is_mapped]
        raise ManifestError(
            "Hydrofabric feature IDs must map cleanly to VPUs before manifest "
            f"creation. Unmapped sites: {', '.join(unmapped)}"
        )

    by_vpu: dict[str, list[Site]] = {}
    for site in mapped_sites:
        by_vpu.setdefault(str(site.discovered_vpu_id), []).append(site)
    created_at = datetime.now(UTC).isoformat()
    base_url = defaults["nrds"]["public_s3_base_url"]
    records: list[dict[str, Any]] = []

    for discovery in discovery_records:
        if discovery.get("record_type") not in (None, "object"):
            continue
        classification = classify_object(discovery, defaults)
        if classification.classification != "approved":
            continue
        parsed = classification.parsed
        sites_for_vpu = by_vpu.get(str(parsed["vpu_id"]), [])
        if not sites_for_vpu:
            continue
        key = discovery.get("key") or discovery.get("object_key")
        for site in sites_for_vpu:
            record = {
                "manifest_version": MANIFEST_VERSION,
                "created_at_utc": created_at,
                "site_id": site.site_id,
                "usgs_gage_id": site.usgs_gage_id,
                "hydrofabric_feature_id": site.hydrofabric_feature_id,
                "vpu_id": parsed["vpu_id"],
                "stream": parsed["stream"],
                "hydrofabric_version": parsed["hydrofabric_version"],
                "run_date": parsed["run_date"],
                "run_type": parsed["run_type"],
                "cycle": parsed["cycle"],
                "object_key": key,
                "public_url": discovery.get("public_url") or public_url(base_url, key),
                "format": classification.format,
                "size_bytes": discovery.get("size_bytes", discovery.get("size")),
                "etag": _clean_etag(discovery.get("etag", discovery.get("ETag"))),
                "last_modified": discovery.get("last_modified"),
                "classification": classification.classification,
                "classification_reason": classification.reason,
                "mapping_evidence_ref": _mapping_evidence_ref(site),
                "source_listing_ref": discovery.get("source_listing_ref"),
                "approved_for_download": bool(approved_for_download),
            }
            records.append(record)
    return records


def find_candidate_issues(
    discovery_records: Iterable[dict[str, Any]],
    defaults: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Find fail-closed issues in targeted manifest candidate records."""

    ambiguous: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    streamflow_by_unit: dict[tuple[str, str, str, str, str, str], list[dict[str, Any]]]
    streamflow_by_unit = defaultdict(list)

    for discovery in discovery_records:
        if discovery.get("record_type") not in (None, "object"):
            continue
        classification = classify_object(discovery, defaults)
        issue = {
            "object_key": discovery.get("key") or discovery.get("object_key"),
            "size_bytes": discovery.get("size_bytes", discovery.get("size")),
            "etag": _clean_etag(discovery.get("etag", discovery.get("ETag"))),
            "classification": classification.classification,
            "classification_reason": classification.reason,
            "source_listing_ref": discovery.get("source_listing_ref"),
        }
        if classification.classification == "ambiguous":
            ambiguous.append(issue)
            continue
        if classification.classification == "rejected":
            rejected.append(issue)
            continue
        parsed = classification.parsed
        if parsed.get("product_type") == "troute_streamflow_output":
            unit = (
                parsed["stream"],
                parsed["hydrofabric_version"],
                parsed["run_date"],
                parsed["run_type"],
                parsed["cycle"],
                parsed["vpu_id"],
            )
            streamflow_by_unit[unit].append(issue)

    conflicts: list[dict[str, Any]] = []
    for unit, records in streamflow_by_unit.items():
        if len(records) <= 1:
            continue
        stream, hydrofabric_version, run_date, run_type, cycle, vpu_id = unit
        conflicts.append(
            {
                "stream": stream,
                "hydrofabric_version": hydrofabric_version,
                "run_date": run_date,
                "run_type": run_type,
                "cycle": cycle,
                "vpu_id": vpu_id,
                "object_keys": [str(record["object_key"]) for record in records],
            }
        )
    return {"ambiguous": ambiguous, "rejected": rejected, "conflicts": conflicts}


def require_no_blocking_candidate_issues(issues: dict[str, list[dict[str, Any]]]) -> None:
    errors: list[str] = []
    if issues["ambiguous"]:
        errors.append(
            "targeted discovery produced ambiguous product records; "
            "approval is required before continuing:\n"
            + "\n".join(_format_issue(issue) for issue in issues["ambiguous"])
        )
    if issues["conflicts"]:
        errors.append(
            "targeted discovery produced conflicting streamflow output records; "
            "approval is required before choosing one:\n"
            + "\n".join(_format_conflict(issue) for issue in issues["conflicts"])
        )
    if errors:
        raise ManifestError("\n".join(errors))


def build_manifest_summary(
    *,
    manifest_records: Iterable[dict[str, Any]],
    discovery_records: Iterable[dict[str, Any]],
    sites: list[Site],
    defaults: dict[str, Any],
    manifest_path: Path,
    discovery_path: Path | None = None,
    target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = [dict(record) for record in manifest_records]
    discovery = [dict(record) for record in discovery_records]
    object_discovery = [
        record for record in discovery if record.get("record_type") in (None, "object")
    ]
    issues = find_candidate_issues(object_discovery, defaults)
    site_counts: dict[str, dict[str, Any]] = {}
    for site in sites:
        site_records = [record for record in manifest if record["site_id"] == site.site_id]
        site_counts[site.site_id] = {
            "usgs_gage_id": site.usgs_gage_id,
            "hydrofabric_feature_id": site.hydrofabric_feature_id,
            "vpu_id": site.discovered_vpu_id,
            "record_count": len(site_records),
            "total_size_bytes": sum(int(record["size_bytes"]) for record in site_records),
            "mapping_evidence_ref": _mapping_evidence_ref(site),
        }

    by_vpu: dict[str, dict[str, Any]] = {}
    for vpu_id in sorted({str(record["vpu_id"]) for record in manifest}):
        rows = [record for record in manifest if str(record["vpu_id"]) == vpu_id]
        unique = _unique_objects(rows)
        by_vpu[vpu_id] = {
            "site_ids": sorted({str(record["site_id"]) for record in rows}),
            "record_count": len(rows),
            "unique_object_count": len(unique),
            "site_scoped_size_bytes": sum(int(record["size_bytes"]) for record in rows),
            "unique_size_bytes": sum(int(record["size_bytes"]) for record in unique),
        }

    by_vpu_stream: dict[str, dict[str, Any]] = {}
    for record in manifest:
        key = f"{record['vpu_id']}::{record['stream']}"
        bucket = by_vpu_stream.setdefault(
            key,
            {
                "vpu_id": record["vpu_id"],
                "stream": record["stream"],
                "record_count": 0,
                "site_scoped_size_bytes": 0,
                "object_keys": set(),
                "unique_size_bytes": 0,
            },
        )
        bucket["record_count"] += 1
        bucket["site_scoped_size_bytes"] += int(record["size_bytes"])
        if record["object_key"] not in bucket["object_keys"]:
            bucket["object_keys"].add(record["object_key"])
            bucket["unique_size_bytes"] += int(record["size_bytes"])
    by_vpu_stream = {
        key: {
            **value,
            "unique_object_count": len(value["object_keys"]),
            "object_keys": sorted(value["object_keys"]),
        }
        for key, value in sorted(by_vpu_stream.items())
    }

    unique_manifest = _unique_objects(manifest)
    classification_counts = Counter(
        _classification_for_summary(record, defaults) for record in object_discovery
    )
    total_size = sum(int(record["size_bytes"]) for record in manifest)
    unique_size = sum(int(record["size_bytes"]) for record in unique_manifest)
    max_size = max((int(record["size_bytes"]) for record in unique_manifest), default=0)
    return {
        "summary_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "manifest_path": str(manifest_path),
        "discovery_path": None if discovery_path is None else str(discovery_path),
        "target": target or {},
        "site_count": len(sites),
        "mapped_site_count": sum(1 for site in sites if site.is_mapped),
        "manifest": {
            "record_count": len(manifest),
            "unique_object_count": len(unique_manifest),
            "site_scoped_size_bytes": total_size,
            "unique_size_bytes": unique_size,
            "max_object_size_bytes": max_size,
            "classification_counts": dict(Counter(record["classification"] for record in manifest)),
            "approved_for_download_count": sum(
                1 for record in manifest if record.get("approved_for_download") is True
            ),
            "run_dates": sorted({str(record["run_date"]) for record in manifest}),
            "run_types": sorted({str(record["run_type"]) for record in manifest}),
            "cycles": sorted({str(record["cycle"]) for record in manifest}),
            "streams": sorted({str(record["stream"]) for record in manifest}),
            "vpus": sorted({str(record["vpu_id"]) for record in manifest}),
        },
        "safety_thresholds": {
            "max_object_bytes": proof_download_max_object_bytes(defaults),
            "max_total_bytes": proof_download_max_total_bytes(defaults),
        },
        "discovery": {
            "listing_record_count": sum(
                1 for record in discovery if record.get("record_type") == "listing"
            ),
            "object_record_count": len(object_discovery),
            "classification_counts": dict(classification_counts),
            "ambiguous_records": issues["ambiguous"],
            "rejected_records": issues["rejected"],
            "conflicting_records": issues["conflicts"],
        },
        "by_site": site_counts,
        "by_vpu": by_vpu,
        "by_vpu_stream": by_vpu_stream,
    }


def write_manifest_summary(
    *,
    summary: dict[str, Any],
    json_path: Path,
    markdown_path: Path | None = None,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    if markdown_path is not None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_manifest_summary_markdown(summary), encoding="utf-8")


def validate_manifest_records(
    records: Iterable[dict[str, Any]],
    defaults: dict[str, Any],
    *,
    require_download_approval: bool = True,
    allow_oversized: bool = False,
) -> list[dict[str, Any]]:
    errors: list[str] = []
    validated: list[dict[str, Any]] = []
    max_bytes = proof_download_max_object_bytes(defaults)
    for index, record in enumerate(records, start=1):
        missing = [
            field
            for field in REQUIRED_MANIFEST_FIELDS
            if field not in record or record[field] in (None, "")
        ]
        if missing:
            errors.append(f"row {index}: missing required fields: {missing}")
            continue
        if record["manifest_version"] != MANIFEST_VERSION:
            errors.append(f"row {index}: unsupported manifest_version")
        if record["classification"] != "approved":
            errors.append(f"row {index}: classification is not approved")
        if require_download_approval and record["approved_for_download"] is not True:
            errors.append(f"row {index}: approved_for_download is not true")
        size = _coerce_size(record.get("size_bytes"), index, errors)
        if size is not None and size > max_bytes and not allow_oversized:
            errors.append(
                f"row {index}: size {size} exceeds active threshold {max_bytes} bytes"
            )
        reclassified = classify_object(
            {
                "key": record["object_key"],
                "size_bytes": record["size_bytes"],
                "etag": record["etag"],
            },
            defaults,
            allow_oversized=allow_oversized,
        )
        if reclassified.classification != "approved":
            errors.append(
                f"row {index}: classifier no longer approves object "
                f"{record['object_key']}: {reclassified.reason}"
            )
        parsed = reclassified.parsed
        for field in ("stream", "hydrofabric_version", "run_date", "run_type", "cycle", "vpu_id"):
            if parsed.get(field) != str(record[field]):
                errors.append(
                    f"row {index}: parsed {field}={parsed.get(field)!r} "
                    f"does not match manifest value {record[field]!r}"
                )
        validated.append(dict(record))
    if errors:
        raise ManifestError("manifest validation failed:\n" + "\n".join(errors))
    if not validated:
        raise ManifestError("manifest contains no records")
    return validated


def render_manifest_summary_markdown(summary: dict[str, Any]) -> str:
    manifest = summary["manifest"]
    discovery = summary["discovery"]
    thresholds = summary["safety_thresholds"]
    lines = [
        "# NextGen Hydra Manifest Summary",
        "",
        f"Created UTC: `{summary['created_at_utc']}`",
        f"Manifest: `{summary['manifest_path']}`",
        f"Discovery inventory: `{summary.get('discovery_path')}`",
        "",
        "## Manifest",
        "",
        f"- Records: {manifest['record_count']}",
        f"- Unique objects: {manifest['unique_object_count']}",
        f"- Site-scoped bytes: {manifest['site_scoped_size_bytes']}",
        f"- Unique object bytes: {manifest['unique_size_bytes']}",
        f"- Max object bytes: {manifest['max_object_size_bytes']}",
        f"- Classification counts: `{manifest['classification_counts']}`",
        f"- Streams: `{manifest['streams']}`",
        f"- VPUs: `{manifest['vpus']}`",
        f"- Run dates: `{manifest['run_dates']}`",
        f"- Run types: `{manifest['run_types']}`",
        f"- Cycles: `{manifest['cycles']}`",
        "",
        "## Safety",
        "",
        f"- Max object threshold bytes: {thresholds['max_object_bytes']}",
        f"- Max total threshold bytes: {thresholds['max_total_bytes']}",
        "",
        "## Discovery",
        "",
        f"- Listing records: {discovery['listing_record_count']}",
        f"- Object records: {discovery['object_record_count']}",
        f"- Classification counts: `{discovery['classification_counts']}`",
        f"- Ambiguous records: {len(discovery['ambiguous_records'])}",
        f"- Rejected records: {len(discovery['rejected_records'])}",
        f"- Conflicting records: {len(discovery['conflicting_records'])}",
        "",
        "## By VPU",
        "",
    ]
    for vpu_id, record in summary["by_vpu"].items():
        lines.append(
            "- "
            + f"`VPU_{vpu_id}`: records={record['record_count']}, "
            + f"unique_objects={record['unique_object_count']}, "
            + f"site_scoped_bytes={record['site_scoped_size_bytes']}, "
            + f"unique_bytes={record['unique_size_bytes']}, "
            + f"sites=`{record['site_ids']}`"
        )
    lines.extend(["", "## By Site", ""])
    for site_id, record in summary["by_site"].items():
        lines.append(
            "- "
            + f"`{site_id}` (`{record['usgs_gage_id']}`, VPU_{record['vpu_id']}): "
            + f"records={record['record_count']}, bytes={record['total_size_bytes']}, "
            + f"evidence=`{record['mapping_evidence_ref']}`"
        )
    if discovery["ambiguous_records"] or discovery["rejected_records"] or discovery["conflicting_records"]:
        lines.extend(["", "## Candidate Issues", ""])
        for label in ("ambiguous_records", "rejected_records", "conflicting_records"):
            for issue in discovery[label]:
                lines.append(f"- `{label}`: `{issue}`")
    lines.append("")
    return "\n".join(lines)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ManifestError(f"{path}:{line_number}: invalid JSONL: {exc}") from exc
            if not isinstance(row, dict):
                raise ManifestError(f"{path}:{line_number}: JSONL row must be an object")
            rows.append(row)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _mapping_evidence_ref(site: Site) -> str:
    evidence = site.mapping_evidence
    if isinstance(evidence, dict):
        for key in ("ref", "source_url", "source_key", "source"):
            if evidence.get(key):
                return str(evidence[key])
        return json.dumps(evidence, sort_keys=True)
    return str(evidence)


def _clean_etag(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip().strip('"')
    return text or None


def _coerce_size(raw: Any, index: int, errors: list[str]) -> int | None:
    try:
        size = int(raw)
    except (TypeError, ValueError):
        errors.append(f"row {index}: size_bytes is not an integer")
        return None
    if size < 0:
        errors.append(f"row {index}: size_bytes is negative")
        return None
    return size


def _format_issue(issue: dict[str, Any]) -> str:
    return (
        f"- {issue.get('classification')}: {issue.get('object_key')} "
        f"({issue.get('classification_reason')})"
    )


def _format_conflict(issue: dict[str, Any]) -> str:
    return (
        f"- {issue['stream']} {issue['run_date']} {issue['run_type']} "
        f"{issue['cycle']} VPU_{issue['vpu_id']}: {issue['object_keys']}"
    )


def _unique_objects(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for record in records:
        by_key.setdefault(str(record["object_key"]), record)
    return list(by_key.values())


def _classification_for_summary(record: dict[str, Any], defaults: dict[str, Any]) -> str:
    if record.get("classification"):
        return str(record["classification"])
    return classify_object(record, defaults).classification
