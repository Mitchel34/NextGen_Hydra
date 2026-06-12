"""Manifest-driven dry-run-first downloader."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any
from urllib.request import Request
from urllib.request import urlopen

from .config import proof_download_max_total_bytes
from .config import Site
from .manifest import read_jsonl, validate_manifest_records, write_jsonl
from .provenance import append_event, build_event, sha256_file


class DownloadSafetyError(RuntimeError):
    """Raised when a download would violate project safety constraints."""


PLACEHOLDER_APPROVAL_IDS = {
    "<APPROVAL_ID>",
    "APPROVAL_ID",
    "approval_id",
    "TODO",
    "TBD",
}
DOWNLOAD_READ_TIMEOUT_SECONDS = 60
DOWNLOAD_RETRY_COUNT = 3
DOWNLOAD_RETRY_BACKOFF_SECONDS = 5
DOWNLOAD_CHUNK_SIZE = 1024 * 1024


def normalize_approval_id(approval_id: str | None) -> str | None:
    if approval_id is None:
        return None
    normalized = approval_id.strip()
    if not normalized:
        raise DownloadSafetyError("approval_id must be non-empty")
    if (
        normalized in PLACEHOLDER_APPROVAL_IDS
        or (normalized.startswith("<") and normalized.endswith(">"))
    ):
        raise DownloadSafetyError(
            "approval_id must be a concrete identifier, not a placeholder"
        )
    return normalized


def manifest_file_metadata(manifest_path: Path) -> dict[str, str]:
    stat = manifest_path.stat()
    return {
        "manifest_sha256": sha256_file(manifest_path),
        "manifest_last_modified_utc": datetime.fromtimestamp(
            stat.st_mtime, UTC
        ).isoformat(),
    }


def plan_downloads(
    records: list[dict[str, Any]],
    raw_dir: Path,
    defaults: dict[str, Any],
    *,
    sites: list[Site] | None = None,
    allow_oversized: bool = False,
) -> list[dict[str, Any]]:
    validated = validate_manifest_records(
        records,
        defaults,
        sites=sites,
        require_download_approval=True,
        allow_oversized=allow_oversized,
    )
    plan: list[dict[str, Any]] = []
    for record in _unique_download_records(validated):
        local_path = safe_local_path(raw_dir, record["object_key"])
        if local_path.exists():
            actual_size = local_path.stat().st_size
            action = "skip_existing" if actual_size == int(record["size_bytes"]) else "replace"
            reason = (
                "existing file matches manifest size"
                if action == "skip_existing"
                else "existing file size differs from manifest"
            )
        else:
            action = "download"
            reason = "approved manifest row has no local file"
        plan.append(
            {
                "action": action,
                "reason": reason,
                "object_key": record["object_key"],
                "product_type": record["product_type"],
                "public_url": record["public_url"],
                "local_path": str(local_path),
                "size_bytes": int(record["size_bytes"]),
                "etag": record["etag"],
                "last_modified": record["last_modified"],
                "site_ids": record["site_ids"],
                "manifest_row_count": record["manifest_row_count"],
            }
        )
    return plan


def download_manifest_file(
    *,
    manifest_path: Path,
    raw_dir: Path,
    defaults: dict[str, Any],
    execute: bool = False,
    approval_id: str | None = None,
    milestone: int | None = None,
    allow_oversized: bool = False,
    sites: list[Site] | None = None,
    plan_output: Path | None = None,
    provenance_path: Path | None = None,
) -> list[dict[str, Any]]:
    approval_id = normalize_approval_id(approval_id)
    if milestone == 1 and execute:
        raise DownloadSafetyError("milestone 1 forbids object-body downloads")
    if execute and not approval_id:
        raise DownloadSafetyError(
            "real downloads require an explicit approval_id; rerun dry-run first"
        )
    if execute and allow_oversized:
        raise DownloadSafetyError(
            "real downloads cannot bypass configured size thresholds; "
            "raise the configured thresholds after approval instead"
        )
    if allow_oversized and not approval_id:
        raise DownloadSafetyError("oversized downloads require an explicit approval_id")

    records = read_jsonl(manifest_path)
    plan = plan_downloads(
        records,
        raw_dir,
        defaults,
        sites=sites,
        allow_oversized=allow_oversized,
    )
    total_download_bytes = sum(
        row["size_bytes"] for row in plan if row["action"] in {"download", "replace"}
    )
    max_total = proof_download_max_total_bytes(defaults)
    if total_download_bytes > max_total and not allow_oversized:
        raise DownloadSafetyError(
            f"planned download total {total_download_bytes} exceeds active threshold "
            f"{max_total} bytes"
        )
    if plan_output:
        write_jsonl(plan_output, plan)
    manifest_metadata = manifest_file_metadata(manifest_path)
    plan_metadata = download_plan_metadata(plan, plan_output)
    if not execute:
        return plan

    started_at = datetime.now(UTC).isoformat()
    executed_bytes = 0
    for row in plan:
        if row["action"] == "skip_existing":
            row["executed_size_bytes"] = 0
            _log_download_event(
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
        try:
            _download_one(row["public_url"], local_path)
        except Exception as exc:
            _log_download_event(
                row=row,
                manifest_path=manifest_path,
                provenance_path=provenance_path,
                decision="failed",
                reason=str(exc),
                approval_id=approval_id,
                manifest_metadata=manifest_metadata,
                plan_metadata=plan_metadata,
                started_at=started_at,
            )
            raise
        actual_size = local_path.stat().st_size
        if actual_size != row["size_bytes"]:
            _log_download_event(
                row=row,
                manifest_path=manifest_path,
                provenance_path=provenance_path,
                decision="failed",
                reason=(
                    f"downloaded size mismatch: {actual_size} != "
                    f"{row['size_bytes']}"
                ),
                approval_id=approval_id,
                manifest_metadata=manifest_metadata,
                plan_metadata=plan_metadata,
                started_at=started_at,
            )
            raise DownloadSafetyError(
                f"downloaded size mismatch for {row['object_key']}: "
                f"{actual_size} != {row['size_bytes']}"
            )
        digest = sha256_file(local_path)
        row["local_sha256"] = digest
        row["executed_size_bytes"] = actual_size
        executed_bytes += actual_size
        _log_download_event(
            row=row,
            manifest_path=manifest_path,
            provenance_path=provenance_path,
            decision="downloaded",
            reason=f"approved execution {approval_id}",
            approval_id=approval_id,
            manifest_metadata=manifest_metadata,
            plan_metadata=plan_metadata,
            started_at=started_at,
        )
    finished_at = datetime.now(UTC).isoformat()
    _log_download_summary_event(
        manifest_path=manifest_path,
        provenance_path=provenance_path,
        approval_id=approval_id,
        manifest_metadata=manifest_metadata,
        plan_metadata=plan_metadata,
        executed_bytes=executed_bytes,
        started_at=started_at,
        finished_at=finished_at,
    )
    return plan


def safe_local_path(root: Path, object_key: str) -> Path:
    if object_key.startswith("/") or ".." in object_key.split("/"):
        raise DownloadSafetyError(f"unsafe object key: {object_key}")
    return root / object_key


def _unique_download_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for record in records:
        key = str(record["object_key"])
        existing = unique.get(key)
        if existing is None:
            row = dict(record)
            row["site_ids"] = [record["site_id"]]
            row["manifest_row_count"] = 1
            unique[key] = row
            continue
        for field in ("size_bytes", "etag", "public_url", "format", "product_type"):
            if str(existing[field]) != str(record[field]):
                raise DownloadSafetyError(
                    f"manifest contains conflicting metadata for {key}: {field}"
                )
        if record["site_id"] not in existing["site_ids"]:
            existing["site_ids"].append(record["site_id"])
            existing["site_ids"].sort()
        existing["manifest_row_count"] += 1
    return list(unique.values())


def _download_one(url: str, local_path: Path) -> None:
    last_error: Exception | None = None
    for attempt in range(1, DOWNLOAD_RETRY_COUNT + 1):
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "wb", delete=False, dir=str(local_path.parent), suffix=".part"
            ) as tmp:
                tmp_path = Path(tmp.name)
                request = Request(url, headers={"User-Agent": "nextgen-hydra/1"})
                with urlopen(request, timeout=DOWNLOAD_READ_TIMEOUT_SECONDS) as response:
                    while True:
                        chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                        if not chunk:
                            break
                        tmp.write(chunk)
            tmp_path.replace(local_path)
            return
        except Exception as exc:
            last_error = exc
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink()
            if attempt < DOWNLOAD_RETRY_COUNT:
                time.sleep(DOWNLOAD_RETRY_BACKOFF_SECONDS * attempt)
    raise DownloadSafetyError(
        f"download failed after {DOWNLOAD_RETRY_COUNT} attempts: {last_error}"
    ) from last_error


def _log_download_event(
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
        event_type="download",
        command="download",
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


def download_plan_metadata(
    plan: list[dict[str, Any]],
    plan_output: Path | None = None,
) -> dict[str, int | str]:
    return {
        "download_plan_sha256": (
            sha256_file(plan_output)
            if plan_output is not None and plan_output.exists()
            else _sha256_jsonl(plan)
        ),
        "planned_unique_object_count": len(plan),
        "planned_unique_bytes": sum(int(row["size_bytes"]) for row in plan),
    }


def _sha256_jsonl(rows: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(json.dumps(row, sort_keys=True, separators=(",", ":")).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _log_download_summary_event(
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
        event_type="download_summary",
        command="download",
        decision="completed",
        reason="download execution completed",
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
