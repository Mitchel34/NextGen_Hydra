"""Approval-gated hydrofabric resource manifests and downloads."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Iterable

from .config import Site, proof_download_max_total_bytes
from .download import (
    DownloadSafetyError,
    _download_one,
    download_plan_metadata,
    normalize_approval_id,
    safe_local_path,
)
from .io.s3 import head_object, public_url
from .manifest import write_jsonl
from .provenance import append_event, build_event, sha256_file


RESOURCE_MANIFEST_VERSION = 1
RESOURCE_PRODUCT_TYPE = "hydrofabric_geopackage"
REQUIRED_RESOURCE_FIELDS = (
    "resource_manifest_version",
    "created_at_utc",
    "vpu_id",
    "site_ids",
    "resource_type",
    "object_key",
    "public_url",
    "format",
    "size_bytes",
    "etag",
    "last_modified",
    "classification",
    "classification_reason",
    "approved_for_download",
)


class ResourceError(RuntimeError):
    """Raised when hydrofabric resource handling is unsafe or malformed."""


def resource_key(defaults: dict[str, Any], vpu_id: str) -> str:
    hydro = defaults["nrds"]["hydrofabric_version"]
    return f"resources/{hydro}/geopackages/VPU_{vpu_id}/nextgen_VPU_{vpu_id}.gpkg"


def resource_local_path(resource_dir: Path, object_key: str) -> Path:
    """Map an approved resource S3 key into the local resource directory."""

    if not object_key.startswith("resources/"):
        raise DownloadSafetyError(f"unsafe resource key: {object_key}")
    return safe_local_path(resource_dir, object_key.removeprefix("resources/"))


def build_resource_manifest_records(
    *,
    defaults: dict[str, Any],
    sites: list[Site],
    approved_for_download: bool = True,
) -> list[dict[str, Any]]:
    """Build a manifest for only the configured VPU hydrofabric geopackages."""

    base_url = defaults["nrds"]["public_s3_base_url"]
    bucket = defaults["nrds"]["s3_bucket"]
    created_at = datetime.now(UTC).isoformat()
    records: list[dict[str, Any]] = []
    for vpu_id in sorted({str(site.discovered_vpu_id) for site in sites if site.discovered_vpu_id}):
        key = resource_key(defaults, vpu_id)
        metadata = head_object(bucket=bucket, key=key)
        records.append(
            {
                "resource_manifest_version": RESOURCE_MANIFEST_VERSION,
                "created_at_utc": created_at,
                "vpu_id": vpu_id,
                "site_ids": sorted(
                    site.site_id for site in sites if str(site.discovered_vpu_id) == vpu_id
                ),
                "resource_type": RESOURCE_PRODUCT_TYPE,
                "object_key": key,
                "public_url": public_url(base_url, key),
                "format": "gpkg",
                "size_bytes": metadata.get("size_bytes"),
                "etag": _clean_etag(metadata.get("etag")),
                "last_modified": metadata.get("last_modified"),
                "classification": "approved",
                "classification_reason": "approved configured VPU hydrofabric geopackage",
                "approved_for_download": bool(approved_for_download),
            }
        )
    validate_resource_manifest_records(
        records,
        defaults,
        sites=sites,
        require_download_approval=approved_for_download,
    )
    return records


def build_resource_manifest_summary(
    *,
    records: Iterable[dict[str, Any]],
    defaults: dict[str, Any],
    manifest_path: Path,
) -> dict[str, Any]:
    rows = [dict(row) for row in records]
    return {
        "summary_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "manifest_path": str(manifest_path),
        "record_count": len(rows),
        "unique_object_count": len({row["object_key"] for row in rows}),
        "total_size_bytes": sum(int(row["size_bytes"]) for row in rows),
        "resource_type_counts": dict(Counter(row["resource_type"] for row in rows)),
        "vpus": sorted({str(row["vpu_id"]) for row in rows}),
        "safety_thresholds": {
            "max_total_bytes": proof_download_max_total_bytes(defaults),
        },
    }


def write_resource_manifest_summary(
    *,
    summary: dict[str, Any],
    json_path: Path,
    markdown_path: Path | None = None,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    if markdown_path is not None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_resource_manifest_summary_markdown(summary), encoding="utf-8")


def render_resource_manifest_summary_markdown(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# NextGen Hydra Resource Manifest Summary",
            "",
            f"Created UTC: `{summary['created_at_utc']}`",
            f"Manifest: `{summary['manifest_path']}`",
            f"- Records: {summary['record_count']}",
            f"- Unique objects: {summary['unique_object_count']}",
            f"- Total bytes: {summary['total_size_bytes']}",
            f"- Resource type counts: `{summary['resource_type_counts']}`",
            f"- VPUs: `{summary['vpus']}`",
            "",
        ]
    )


def validate_resource_manifest_records(
    records: Iterable[dict[str, Any]],
    defaults: dict[str, Any],
    *,
    sites: list[Site] | None = None,
    require_download_approval: bool = True,
) -> list[dict[str, Any]]:
    rows = [dict(row) for row in records]
    allowed_vpus = (
        {str(site.discovered_vpu_id) for site in sites if site.discovered_vpu_id}
        if sites is not None
        else None
    )
    errors: list[str] = []
    for index, row in enumerate(rows, start=1):
        missing = [
            field
            for field in REQUIRED_RESOURCE_FIELDS
            if field not in row or row[field] in (None, "")
        ]
        if missing:
            errors.append(f"row {index}: missing required fields: {missing}")
            continue
        vpu_id = str(row["vpu_id"])
        expected_key = resource_key(defaults, vpu_id)
        if allowed_vpus is not None and vpu_id not in allowed_vpus:
            errors.append(f"row {index}: VPU_{vpu_id} is not configured in sites")
        if row["object_key"] != expected_key:
            errors.append(
                f"row {index}: object_key must be exact approved geopackage {expected_key!r}"
            )
        if row["resource_type"] != RESOURCE_PRODUCT_TYPE:
            errors.append(f"row {index}: resource_type is not approved")
        if row["format"] != "gpkg":
            errors.append(f"row {index}: format must be gpkg")
        if row["classification"] != "approved":
            errors.append(f"row {index}: classification is not approved")
        if require_download_approval and row["approved_for_download"] is not True:
            errors.append(f"row {index}: approved_for_download is not true")
        size = _coerce_size(row.get("size_bytes"), index, errors)
        if size is not None and size < 0:
            errors.append(f"row {index}: size_bytes is negative")
    if errors:
        raise ResourceError("resource manifest validation failed:\n" + "\n".join(errors))
    if not rows:
        raise ResourceError("resource manifest contains no records")
    return rows


def plan_resource_downloads(
    records: list[dict[str, Any]],
    resource_dir: Path,
    defaults: dict[str, Any],
    *,
    sites: list[Site] | None = None,
) -> list[dict[str, Any]]:
    validated = validate_resource_manifest_records(records, defaults, sites=sites)
    plan: list[dict[str, Any]] = []
    for row in validated:
        local_path = resource_local_path(resource_dir, row["object_key"])
        if local_path.exists():
            actual_size = local_path.stat().st_size
            action = "skip_existing" if actual_size == int(row["size_bytes"]) else "replace"
            reason = (
                "existing resource matches manifest size"
                if action == "skip_existing"
                else "existing resource size differs from manifest"
            )
        else:
            action = "download"
            reason = "approved resource manifest row has no local file"
        plan.append(
            {
                "action": action,
                "reason": reason,
                "object_key": row["object_key"],
                "resource_type": row["resource_type"],
                "product_type": row["resource_type"],
                "public_url": row["public_url"],
                "local_path": str(local_path),
                "size_bytes": int(row["size_bytes"]),
                "etag": row["etag"],
                "last_modified": row["last_modified"],
                "vpu_id": row["vpu_id"],
                "site_ids": row["site_ids"],
                "manifest_row_count": 1,
            }
        )
    return plan


def download_resource_manifest_file(
    *,
    manifest_path: Path,
    resource_dir: Path,
    defaults: dict[str, Any],
    sites: list[Site],
    execute: bool = False,
    approval_id: str | None = None,
    plan_output: Path | None = None,
    provenance_path: Path | None = None,
) -> list[dict[str, Any]]:
    approval_id = normalize_approval_id(approval_id)
    if execute and not approval_id:
        raise DownloadSafetyError("resource downloads require an explicit approval_id")
    rows = _read_resource_jsonl(manifest_path)
    plan = plan_resource_downloads(rows, resource_dir, defaults, sites=sites)
    total_download_bytes = sum(
        row["size_bytes"] for row in plan if row["action"] in {"download", "replace"}
    )
    max_total = proof_download_max_total_bytes(defaults)
    if total_download_bytes > max_total and not approval_id:
        raise DownloadSafetyError(
            f"planned resource total {total_download_bytes} exceeds active threshold "
            f"{max_total} bytes; approval is required"
        )
    if plan_output is not None:
        write_jsonl(plan_output, plan)
    manifest_metadata = {
        "manifest_sha256": sha256_file(manifest_path),
        "manifest_last_modified_utc": datetime.fromtimestamp(
            manifest_path.stat().st_mtime, UTC
        ).isoformat(),
    }
    plan_metadata = download_plan_metadata(plan, plan_output)
    if not execute:
        return plan

    started_at = datetime.now(UTC).isoformat()
    executed_bytes = 0
    for row in plan:
        if row["action"] == "skip_existing":
            row["executed_size_bytes"] = 0
            _log_resource_event(
                row=row,
                manifest_path=manifest_path,
                provenance_path=provenance_path,
                decision="skipped",
                reason=row["reason"],
                approval_id=approval_id,
                manifest_metadata=manifest_metadata,
                plan_metadata=plan_metadata,
                started_at=started_at,
            )
            continue
        local_path = Path(row["local_path"])
        local_path.parent.mkdir(parents=True, exist_ok=True)
        _download_one(row["public_url"], local_path)
        actual_size = local_path.stat().st_size
        if actual_size != row["size_bytes"]:
            raise DownloadSafetyError(
                f"downloaded size mismatch for {row['object_key']}: "
                f"{actual_size} != {row['size_bytes']}"
            )
        row["local_sha256"] = sha256_file(local_path)
        row["executed_size_bytes"] = actual_size
        executed_bytes += actual_size
        _log_resource_event(
            row=row,
            manifest_path=manifest_path,
            provenance_path=provenance_path,
            decision="downloaded",
            reason=f"approved resource execution {approval_id}",
            approval_id=approval_id,
            manifest_metadata=manifest_metadata,
            plan_metadata=plan_metadata,
            started_at=started_at,
        )
    _log_resource_summary_event(
        manifest_path=manifest_path,
        provenance_path=provenance_path,
        approval_id=approval_id,
        manifest_metadata=manifest_metadata,
        plan_metadata=plan_metadata,
        executed_bytes=executed_bytes,
        started_at=started_at,
        finished_at=datetime.now(UTC).isoformat(),
    )
    return plan


def write_resource_download_summary(
    *,
    path: Path,
    markdown_path: Path | None,
    manifest_path: Path,
    plan_output: Path | None,
    provenance_path: Path | None,
    approval_id: str | None,
    mode: str,
    plan: list[dict[str, Any]],
) -> None:
    plan_metadata = download_plan_metadata(plan, plan_output)
    summary = {
        "summary_version": 1,
        "mode": mode,
        "approval_id": approval_id,
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        **plan_metadata,
        "plan_output": None if plan_output is None else str(plan_output),
        "provenance": None if provenance_path is None else str(provenance_path),
        "actions": dict(Counter(row["action"] for row in plan)),
        "executed_bytes": sum(int(row.get("executed_size_bytes") or 0) for row in plan),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    if markdown_path is not None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_resource_download_summary_markdown(summary), encoding="utf-8")


def render_resource_download_summary_markdown(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# NextGen Hydra Resource Download Summary",
            "",
            f"Mode: `{summary['mode']}`",
            f"Approval ID: `{summary.get('approval_id')}`",
            f"- Manifest: `{summary['manifest_path']}`",
            f"- Manifest SHA256: `{summary['manifest_sha256']}`",
            f"- Plan SHA256: `{summary['download_plan_sha256']}`",
            f"- Unique objects: {summary['planned_unique_object_count']}",
            f"- Planned bytes: {summary['planned_unique_bytes']}",
            f"- Executed bytes: {summary['executed_bytes']}",
            f"- Actions: `{summary['actions']}`",
            "",
        ]
    )


def _read_resource_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ResourceError(f"{path}:{line_number}: invalid JSONL: {exc}") from exc
            if not isinstance(row, dict):
                raise ResourceError(f"{path}:{line_number}: JSONL row must be an object")
            rows.append(row)
    return rows


def _log_resource_event(
    *,
    row: dict[str, Any],
    manifest_path: Path,
    provenance_path: Path | None,
    decision: str,
    reason: str,
    approval_id: str | None,
    manifest_metadata: dict[str, str],
    plan_metadata: dict[str, int | str],
    started_at: str,
) -> None:
    if provenance_path is None:
        return
    event = build_event(
        event_type="resource_download",
        command="download-resources",
        decision=decision,
        reason=reason,
        manifest_path=str(manifest_path),
        approval_id=approval_id,
        manifest_sha256=manifest_metadata["manifest_sha256"],
        manifest_last_modified_utc=manifest_metadata["manifest_last_modified_utc"],
        download_plan_sha256=str(plan_metadata["download_plan_sha256"]),
        planned_unique_object_count=int(plan_metadata["planned_unique_object_count"]),
        planned_unique_bytes=int(plan_metadata["planned_unique_bytes"]),
        executed_bytes=int(row.get("executed_size_bytes") or 0),
        download_started_at_utc=started_at,
        download_finished_at_utc=datetime.now(UTC).isoformat(),
        source_key=row["object_key"],
        source_etag=row["etag"],
        source_last_modified=row.get("last_modified"),
        source_size_bytes=row["size_bytes"],
        local_path=row["local_path"],
        local_sha256=row.get("local_sha256"),
        download_action=row["action"],
    )
    append_event(provenance_path, event)


def _log_resource_summary_event(
    *,
    manifest_path: Path,
    provenance_path: Path | None,
    approval_id: str | None,
    manifest_metadata: dict[str, str],
    plan_metadata: dict[str, int | str],
    executed_bytes: int,
    started_at: str,
    finished_at: str,
) -> None:
    if provenance_path is None:
        return
    event = build_event(
        event_type="resource_download_summary",
        command="download-resources",
        decision="completed",
        reason="resource download execution completed",
        manifest_path=str(manifest_path),
        approval_id=approval_id,
        manifest_sha256=manifest_metadata["manifest_sha256"],
        manifest_last_modified_utc=manifest_metadata["manifest_last_modified_utc"],
        download_plan_sha256=str(plan_metadata["download_plan_sha256"]),
        planned_unique_object_count=int(plan_metadata["planned_unique_object_count"]),
        planned_unique_bytes=int(plan_metadata["planned_unique_bytes"]),
        executed_bytes=executed_bytes,
        download_started_at_utc=started_at,
        download_finished_at_utc=finished_at,
    )
    append_event(provenance_path, event)


def _coerce_size(raw: Any, index: int, errors: list[str]) -> int | None:
    try:
        return int(raw)
    except (TypeError, ValueError):
        errors.append(f"row {index}: size_bytes is not an integer")
        return None


def _clean_etag(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip().strip('"')
    return text or None
