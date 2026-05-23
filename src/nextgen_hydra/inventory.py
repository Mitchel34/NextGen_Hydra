"""Local raw-file inventory and manifest comparison."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .provenance import sha256_file


def inventory_raw_files(
    raw_dir: Path,
    manifest_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    expected = {
        record["object_key"]: record for record in manifest_records or []
    }
    rows: list[dict[str, Any]] = []
    if not raw_dir.exists():
        return rows
    for path in sorted(raw_dir.rglob("*")):
        if not path.is_file() or path.name.endswith(".part"):
            continue
        rel = path.relative_to(raw_dir).as_posix()
        manifest = expected.get(rel)
        size = path.stat().st_size
        rows.append(
            {
                "inventory_version": 1,
                "inventoried_at_utc": datetime.now(UTC).isoformat(),
                "relative_path": rel,
                "local_path": str(path),
                "size_bytes": size,
                "sha256": sha256_file(path),
                "manifest_match": manifest is not None,
                "expected_size_bytes": (
                    None if manifest is None else int(manifest["size_bytes"])
                ),
                "size_matches_manifest": (
                    None if manifest is None else size == int(manifest["size_bytes"])
                ),
                "source_etag": None if manifest is None else manifest["etag"],
                "source_last_modified": (
                    None if manifest is None else manifest["last_modified"]
                ),
            }
        )
    return rows
