"""Manifest construction and validation."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Iterable

from .classifier import classify_object
from .config import (
    ConfigError,
    Site,
    proof_download_max_object_bytes,
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
