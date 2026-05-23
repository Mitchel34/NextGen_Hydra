"""Manifest-driven dry-run-first downloader."""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
from typing import Any
from urllib.request import urlopen

from .config import proof_download_max_total_bytes
from .manifest import read_jsonl, validate_manifest_records, write_jsonl
from .provenance import append_event, build_event, sha256_file


class DownloadSafetyError(RuntimeError):
    """Raised when a download would violate project safety constraints."""


def plan_downloads(
    records: list[dict[str, Any]],
    raw_dir: Path,
    defaults: dict[str, Any],
    *,
    allow_oversized: bool = False,
) -> list[dict[str, Any]]:
    validated = validate_manifest_records(
        records,
        defaults,
        require_download_approval=True,
        allow_oversized=allow_oversized,
    )
    plan: list[dict[str, Any]] = []
    for record in validated:
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
                "public_url": record["public_url"],
                "local_path": str(local_path),
                "size_bytes": int(record["size_bytes"]),
                "etag": record["etag"],
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
    plan_output: Path | None = None,
    provenance_path: Path | None = None,
) -> list[dict[str, Any]]:
    if milestone == 1 and execute:
        raise DownloadSafetyError("milestone 1 forbids object-body downloads")
    if execute and not approval_id:
        raise DownloadSafetyError(
            "real downloads require an explicit approval_id; rerun dry-run first"
        )
    if allow_oversized and not approval_id:
        raise DownloadSafetyError("oversized downloads require an explicit approval_id")

    records = read_jsonl(manifest_path)
    plan = plan_downloads(records, raw_dir, defaults, allow_oversized=allow_oversized)
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
    if not execute:
        return plan

    for row in plan:
        if row["action"] == "skip_existing":
            _log_download_event(
                row=row,
                manifest_path=manifest_path,
                provenance_path=provenance_path,
                decision="skipped",
                reason=row["reason"],
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
        digest = sha256_file(local_path)
        row["local_sha256"] = digest
        _log_download_event(
            row=row,
            manifest_path=manifest_path,
            provenance_path=provenance_path,
            decision="downloaded",
            reason=f"approved execution {approval_id}",
        )
    return plan


def safe_local_path(root: Path, object_key: str) -> Path:
    if object_key.startswith("/") or ".." in object_key.split("/"):
        raise DownloadSafetyError(f"unsafe object key: {object_key}")
    return root / object_key


def _download_one(url: str, local_path: Path) -> None:
    with tempfile.NamedTemporaryFile(
        "wb", delete=False, dir=str(local_path.parent), suffix=".part"
    ) as tmp:
        tmp_path = Path(tmp.name)
        with urlopen(url, timeout=60) as response:
            shutil.copyfileobj(response, tmp)
    tmp_path.replace(local_path)


def _log_download_event(
    *,
    row: dict[str, Any],
    manifest_path: Path,
    provenance_path: Path | None,
    decision: str,
    reason: str,
) -> None:
    if provenance_path is None:
        return
    event = build_event(
        event_type="download",
        command="download",
        decision=decision,
        reason=reason,
        manifest_path=str(manifest_path),
        source_key=row["object_key"],
        source_etag=row["etag"],
        source_size_bytes=row["size_bytes"],
        local_path=row["local_path"],
        local_sha256=row.get("local_sha256"),
    )
    append_event(provenance_path, event)
