"""Provenance event helpers."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import platform
import uuid
from typing import Any

from .schemas import CLASSIFIER_VERSION


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_event(
    *,
    event_type: str,
    command: str,
    decision: str,
    reason: str,
    config_files: list[str] | None = None,
    manifest_path: str | None = None,
    source_bucket: str | None = None,
    source_key: str | None = None,
    source_etag: str | None = None,
    source_last_modified: str | None = None,
    source_size_bytes: int | None = None,
    local_path: str | None = None,
    local_sha256: str | None = None,
    approval_id: str | None = None,
    manifest_sha256: str | None = None,
    manifest_last_modified_utc: str | None = None,
    download_plan_sha256: str | None = None,
    planned_unique_object_count: int | None = None,
    planned_unique_bytes: int | None = None,
    executed_bytes: int | None = None,
    download_started_at_utc: str | None = None,
    download_finished_at_utc: str | None = None,
    download_action: str | None = None,
) -> dict[str, Any]:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "command": command,
        "approval_id": approval_id,
        "config_files": config_files or [],
        "manifest_path": manifest_path,
        "manifest_sha256": manifest_sha256,
        "manifest_last_modified_utc": manifest_last_modified_utc,
        "download_plan_sha256": download_plan_sha256,
        "planned_unique_object_count": planned_unique_object_count,
        "planned_unique_bytes": planned_unique_bytes,
        "executed_bytes": executed_bytes,
        "download_started_at_utc": download_started_at_utc,
        "download_finished_at_utc": download_finished_at_utc,
        "source_bucket": source_bucket,
        "source_key": source_key,
        "source_etag": source_etag,
        "source_last_modified": source_last_modified,
        "source_size_bytes": source_size_bytes,
        "local_path": local_path,
        "local_sha256": local_sha256,
        "download_action": download_action,
        "classifier_version": CLASSIFIER_VERSION,
        "decision": decision,
        "reason": reason,
        "software_versions": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
    }


def append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
