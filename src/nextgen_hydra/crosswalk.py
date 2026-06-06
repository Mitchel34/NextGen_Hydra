"""Resolve site COMIDs to troute feature IDs from hydrofabric geopackages."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sqlite3
from typing import Any

import yaml

from .config import Site
from .resources import resource_key, resource_local_path


class CrosswalkError(RuntimeError):
    """Raised when site crosswalk records are missing or unsafe."""


MATCH_FIELD_HINTS = {
    "comid",
    "nhdplus_comid",
    "hydrofabric_feature_id",
    "feature_id",
    "hl_link",
    "hl_reference",
}
TARGET_FIELD_PRIORITY = (
    "id",
    "feature_id",
    "divide_id",
    "toid",
    "link",
    "comid",
)


def load_site_crosswalk(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise CrosswalkError(f"site crosswalk file does not exist: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise CrosswalkError(f"site crosswalk must contain a mapping: {path}")
    if data.get("version") != 1:
        raise CrosswalkError("site crosswalk version must be 1")
    records = data.get("sites")
    if not isinstance(records, list):
        raise CrosswalkError("site crosswalk must contain a sites list")
    return data


def write_site_crosswalk(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False)


def crosswalk_by_site(crosswalk: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not crosswalk:
        return {}
    return {
        str(record.get("site_id")): record
        for record in crosswalk.get("sites", [])
        if isinstance(record, dict) and record.get("site_id")
    }


def target_feature_id_for_site(
    site: dict[str, Any],
    crosswalk: dict[str, Any] | None,
) -> int:
    if crosswalk is None:
        return int(site["hydrofabric_feature_id"])
    record = crosswalk_by_site(crosswalk).get(str(site["site_id"]))
    if not record or record.get("status") != "resolved":
        raise CrosswalkError(
            f"site {site['site_id']} does not have a resolved troute_feature_id"
        )
    return int(record["troute_feature_id"])


def require_resolved_crosswalk(
    *,
    crosswalk: dict[str, Any],
    site_ids: set[str],
) -> None:
    by_site = crosswalk_by_site(crosswalk)
    errors: list[str] = []
    for site_id in sorted(site_ids):
        record = by_site.get(site_id)
        if record is None:
            errors.append(f"{site_id}: missing crosswalk record")
            continue
        if record.get("status") != "resolved" or record.get("troute_feature_id") in (None, ""):
            errors.append(f"{site_id}: troute_feature_id is not resolved")
    if errors:
        raise CrosswalkError("site crosswalk is not resolved:\n" + "\n".join(errors))


def resolve_site_crosswalk(
    *,
    sites: list[Site],
    defaults: dict[str, Any],
    resource_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for site in sites:
        records.append(_resolve_one_site(site=site, defaults=defaults, resource_dir=resource_dir))
    status = "pass" if all(record["status"] == "resolved" for record in records) else "fail"
    data = {
        "version": 1,
        "status": "resolved" if status == "pass" else "unresolved",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "sites": records,
    }
    report = {
        "report_version": 1,
        "created_at_utc": data["generated_at_utc"],
        "status": status,
        "resolved_count": sum(1 for record in records if record["status"] == "resolved"),
        "site_count": len(records),
        "errors": [
            f"{record['site_id']}: {record['evidence']}"
            for record in records
            if record["status"] != "resolved"
        ],
        "sites": records,
    }
    return data, report


def write_crosswalk_report(path: Path, report: dict[str, Any]) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def _resolve_one_site(
    *,
    site: Site,
    defaults: dict[str, Any],
    resource_dir: Path,
) -> dict[str, Any]:
    vpu_id = str(site.discovered_vpu_id)
    key = resource_key(defaults, vpu_id)
    path = resource_local_path(resource_dir, key)
    base = {
        "site_id": site.site_id,
        "usgs_gage_id": site.usgs_gage_id,
        "hydrofabric_feature_id": site.hydrofabric_feature_id,
        "vpu_id": vpu_id,
        "troute_feature_id": None,
        "status": "unresolved",
        "confidence": "none",
        "source_resource_key": key,
        "source_table": None,
        "source_fields": {},
    }
    if not path.is_file():
        return {
            **base,
            "evidence": f"resource geopackage is missing: {path}",
            "candidate_count": 0,
        }
    candidates = _find_candidates(path, site.hydrofabric_feature_id)
    unique_targets = sorted({candidate["troute_feature_id"] for candidate in candidates})
    if len(unique_targets) == 1:
        candidate = next(
            candidate
            for candidate in candidates
            if candidate["troute_feature_id"] == unique_targets[0]
        )
        return {
            **base,
            "troute_feature_id": int(unique_targets[0]),
            "status": "resolved",
            "confidence": "exact-row-match",
            "source_table": candidate["table"],
            "source_fields": {
                "match_field": candidate["match_field"],
                "target_field": candidate["target_field"],
            },
            "evidence": (
                f"{candidate['table']}.{candidate['match_field']} matched "
                f"{site.hydrofabric_feature_id}; "
                f"{candidate['target_field']}={unique_targets[0]}"
            ),
            "candidate_count": len(candidates),
        }
    if not candidates:
        return {
            **base,
            "evidence": f"no geopackage row matched hydrofabric_feature_id {site.hydrofabric_feature_id}",
            "candidate_count": 0,
        }
    return {
        **base,
        "status": "ambiguous",
        "evidence": (
            f"multiple troute feature candidates found for "
            f"hydrofabric_feature_id {site.hydrofabric_feature_id}: {unique_targets}"
        ),
        "candidate_count": len(candidates),
        "candidate_troute_feature_ids": unique_targets,
    }


def _find_candidates(path: Path, hydrofabric_feature_id: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        for table in _user_tables(connection):
            columns = _table_columns(connection, table)
            match_fields = _match_fields(columns)
            target_fields = _target_fields(columns)
            if not match_fields or not target_fields:
                continue
            for match_field in match_fields:
                query = (
                    f'SELECT * FROM "{table}" '
                    f'WHERE CAST("{match_field}" AS TEXT) = ? LIMIT 20'
                )
                for row in connection.execute(query, (str(hydrofabric_feature_id),)):
                    for target_field in target_fields:
                        target = _coerce_int(row[target_field])
                        if target is not None:
                            candidates.append(
                                {
                                    "table": table,
                                    "match_field": match_field,
                                    "target_field": target_field,
                                    "troute_feature_id": target,
                                }
                            )
                            break
    return candidates


def _user_tables(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [
        str(row[0])
        for row in rows
        if not str(row[0]).startswith(("sqlite_", "gpkg_", "rtree_"))
    ]


def _table_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    rows = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    return [str(row[1]) for row in rows]


def _match_fields(columns: list[str]) -> list[str]:
    normalised = {_normalise(column): column for column in columns}
    exact = [normalised[name] for name in MATCH_FIELD_HINTS if name in normalised]
    if exact:
        return sorted(dict.fromkeys(exact))
    return [
        column
        for column in columns
        if any(token in _normalise(column) for token in ("comid", "feature", "hl_link"))
    ]


def _target_fields(columns: list[str]) -> list[str]:
    normalised = {_normalise(column): column for column in columns}
    ordered = [
        normalised[name]
        for name in TARGET_FIELD_PRIORITY
        if name in normalised
    ]
    return list(dict.fromkeys(ordered + columns))


def _normalise(value: str) -> str:
    return value.lower().replace("-", "_")


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
