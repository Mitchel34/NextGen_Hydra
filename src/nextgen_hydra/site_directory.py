"""Build searchable paired NextGen/USGS site directories from hydrofabric GPKGs."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re
import sqlite3
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from .crosswalk import _extract_troute_feature_id


class SiteDirectoryError(RuntimeError):
    """Raised when a paired site directory cannot be built safely."""


def build_paired_site_directory(
    *,
    resource_dir: Path,
    output: Path,
    report_output: Path,
    markdown_output: Path | None = None,
    vpu_ids: list[str] | None = None,
    enrich_usgs: bool = False,
    usgs_chunk_size: int = 100,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    gpkg_paths = _resource_paths(resource_dir, vpu_ids)
    if not gpkg_paths:
        raise SiteDirectoryError(f"no hydrofabric geopackages found under {resource_dir}")
    records: list[dict[str, Any]] = []
    source_summaries = []
    for path in gpkg_paths:
        rows = _records_from_gpkg(path)
        records.extend(rows)
        source_summaries.append(
            {
                "path": str(path),
                "record_count": len(rows),
                "vpu_ids": sorted({row["vpu_id"] for row in rows if row.get("vpu_id")}),
            }
        )
    records = _dedupe_records(records)
    if enrich_usgs:
        _apply_usgs_enrichment(records, usgs_chunk_size=usgs_chunk_size)
    _finalize_records(records)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    report = _build_report(
        records=records,
        source_summaries=source_summaries,
        output=output,
        enriched_usgs=enrich_usgs,
    )
    report_output.parent.mkdir(parents=True, exist_ok=True)
    report_output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    if markdown_output is not None:
        markdown_output.parent.mkdir(parents=True, exist_ok=True)
        markdown_output.write_text(_render_markdown(report), encoding="utf-8")
    return records, report


def _resource_paths(resource_dir: Path, vpu_ids: list[str] | None) -> list[Path]:
    if vpu_ids:
        paths = [
            resource_dir
            / "v2.2_hydrofabric"
            / "geopackages"
            / f"VPU_{str(vpu).zfill(2)}"
            / f"nextgen_VPU_{str(vpu).zfill(2)}.gpkg"
            for vpu in vpu_ids
        ]
        missing = [str(path) for path in paths if not path.is_file()]
        if missing:
            raise SiteDirectoryError("missing requested hydrofabric resources: " + ", ".join(missing))
        return paths
    return sorted(resource_dir.glob("v2.2_hydrofabric/geopackages/VPU_*/nextgen_VPU_*.gpkg"))


def _records_from_gpkg(path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        _require_tables(connection, path)
        network_by_id = _network_comids_by_troute_id(connection)
        network_by_gage = _network_comids_by_gage(connection)
        hydrolocations_by_gage = _hydrolocation_comids_by_gage(connection)
        rows = connection.execute(
            """
            SELECT gage, gage_nex_id, id, link, toid, vpuid, Length_m
            FROM "flowpath-attributes"
            WHERE gage IS NOT NULL AND CAST(gage AS TEXT) != ''
            ORDER BY vpuid, gage, id
            """
        ).fetchall()
    records: list[dict[str, Any]] = []
    for row in rows:
        usgs_gage_id = _normalise_gage(row["gage"])
        troute_feature_id = _extract_troute_feature_id(row["id"] or row["link"])
        if not usgs_gage_id or troute_feature_id is None:
            continue
        comid_candidates = sorted(
            set(network_by_id.get(str(row["id"]), []))
            | set(network_by_gage.get(usgs_gage_id, []))
            | set(hydrolocations_by_gage.get(usgs_gage_id, []))
        )
        records.append(
            {
                "site_id": f"usgs_{usgs_gage_id}_troute_{troute_feature_id}",
                "name": f"USGS {usgs_gage_id}",
                "usgs_gage_id": usgs_gage_id,
                "comid": comid_candidates[0] if len(comid_candidates) == 1 else None,
                "hydrofabric_feature_id": comid_candidates[0] if len(comid_candidates) == 1 else None,
                "comid_candidates": comid_candidates,
                "comid_status": (
                    "single_match"
                    if len(comid_candidates) == 1
                    else "multiple_candidates"
                    if comid_candidates
                    else "missing"
                ),
                "troute_feature_id": troute_feature_id,
                "troute_id": row["id"],
                "nexus_id": row["toid"] or row["gage_nex_id"],
                "vpu_id": str(row["vpuid"]),
                "availability": {
                    "nextgen": True,
                    "nwm": True,
                    "era5": False,
                    "usgs": True,
                },
                "latitude": None,
                "longitude": None,
                "huc": None,
                "state_code": None,
                "marker_status": "paired",
                "search_tokens": [],
                "status": "paired",
                "source": str(path),
                "source_table": "flowpath-attributes",
                "source_fields": {
                    "usgs_gage_id": "gage",
                    "troute_id": "id",
                    "comid_candidates": (
                        "network.hf_id joined on network.id = flowpath-attributes.id; "
                        "network.hf_id joined on USGS gage URI; "
                        "hydrolocations.hf_id joined on USGS gage"
                    ),
                },
            }
        )
    return records


def _require_tables(connection: sqlite3.Connection, path: Path) -> None:
    tables = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    missing = {"flowpath-attributes", "network"} - tables
    if missing:
        raise SiteDirectoryError(f"{path} is missing required table(s): {sorted(missing)}")


def _network_comids_by_troute_id(connection: sqlite3.Connection) -> dict[str, list[int]]:
    rows = connection.execute(
        """
        SELECT id, hf_id
        FROM network
        WHERE id IS NOT NULL AND hf_id IS NOT NULL
        """
    ).fetchall()
    grouped: dict[str, set[int]] = {}
    for row in rows:
        try:
            hf_id = int(float(row["hf_id"]))
        except (TypeError, ValueError):
            continue
        grouped.setdefault(str(row["id"]), set()).add(hf_id)
    return {key: sorted(values) for key, values in grouped.items()}


def _network_comids_by_gage(connection: sqlite3.Connection) -> dict[str, list[int]]:
    columns = {
        str(row[1])
        for row in connection.execute('PRAGMA table_info("network")')
    }
    if not {"hl_uri", "hf_id"}.issubset(columns):
        return {}
    rows = connection.execute(
        """
        SELECT hl_uri, hf_id
        FROM network
        WHERE hl_uri IS NOT NULL AND hf_id IS NOT NULL
        """
    ).fetchall()
    grouped: dict[str, set[int]] = {}
    for row in rows:
        gage = _normalise_gage(row["hl_uri"])
        if not gage:
            continue
        try:
            hf_id = int(float(row["hf_id"]))
        except (TypeError, ValueError):
            continue
        grouped.setdefault(gage, set()).add(hf_id)
    return {key: sorted(values) for key, values in grouped.items()}


def _hydrolocation_comids_by_gage(connection: sqlite3.Connection) -> dict[str, list[int]]:
    tables = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if "hydrolocations" not in tables:
        return {}
    rows = connection.execute(
        """
        SELECT hl_link, hl_uri, hf_id
        FROM hydrolocations
        WHERE hf_id IS NOT NULL
        """
    ).fetchall()
    grouped: dict[str, set[int]] = {}
    for row in rows:
        gage = _normalise_gage(row["hl_link"]) or _normalise_gage(row["hl_uri"])
        if not gage:
            continue
        try:
            hf_id = int(float(row["hf_id"]))
        except (TypeError, ValueError):
            continue
        grouped.setdefault(gage, set()).add(hf_id)
    return {key: sorted(values) for key, values in grouped.items()}


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, int, str], dict[str, Any]] = {}
    for record in records:
        key = (record["usgs_gage_id"], int(record["troute_feature_id"]), record["vpu_id"])
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = record
            continue
        candidates = sorted(
            set(existing.get("comid_candidates") or []) | set(record.get("comid_candidates") or [])
        )
        existing["comid_candidates"] = candidates
        existing["comid"] = candidates[0] if len(candidates) == 1 else None
        existing["hydrofabric_feature_id"] = existing["comid"]
        existing["comid_status"] = "single_match" if len(candidates) == 1 else "multiple_candidates"
    return sorted(
        deduped.values(),
        key=lambda row: (str(row.get("vpu_id")), str(row.get("usgs_gage_id")), int(row.get("troute_feature_id"))),
    )


def _apply_usgs_enrichment(records: list[dict[str, Any]], *, usgs_chunk_size: int) -> None:
    site_ids = sorted({record["usgs_gage_id"] for record in records})
    metadata = _fetch_usgs_site_metadata(site_ids, chunk_size=usgs_chunk_size)
    for record in records:
        info = metadata.get(record["usgs_gage_id"], {})
        if info.get("station_nm"):
            record["name"] = info["station_nm"]
        record["latitude"] = _optional_float(info.get("dec_lat_va"))
        record["longitude"] = _optional_float(info.get("dec_long_va"))
        record["huc"] = info.get("huc_cd")
        record["state_code"] = info.get("state_cd")
        record["usgs"] = info


def _finalize_records(records: list[dict[str, Any]]) -> None:
    for record in records:
        record["marker_status"] = "paired"
        record["search_tokens"] = _search_tokens(record)


def _search_tokens(record: dict[str, Any]) -> list[str]:
    values: list[Any] = [
        record.get("site_id"),
        record.get("name"),
        record.get("usgs_gage_id"),
        record.get("comid"),
        record.get("hydrofabric_feature_id"),
        record.get("troute_feature_id"),
        record.get("troute_id"),
        record.get("vpu_id"),
        record.get("huc"),
        record.get("state_code"),
    ]
    values.extend(record.get("comid_candidates") or [])
    return sorted({str(value) for value in values if value not in (None, "")})


def _fetch_usgs_site_metadata(site_ids: list[str], *, chunk_size: int) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for start in range(0, len(site_ids), chunk_size):
        chunk = site_ids[start : start + chunk_size]
        query = urlencode(
            {
                "format": "rdb",
                "sites": ",".join(chunk),
                "siteOutput": "expanded",
            }
        )
        url = f"https://waterservices.usgs.gov/nwis/site/?{query}"
        with urlopen(url, timeout=60) as response:  # nosec B310 - official public USGS API.
            text = response.read().decode("utf-8", errors="replace")
        metadata.update(_parse_usgs_rdb(text))
    return metadata


def _parse_usgs_rdb(text: str) -> dict[str, dict[str, Any]]:
    lines = [
        line
        for line in text.splitlines()
        if line and not line.startswith("#")
    ]
    if len(lines) < 3:
        return {}
    header = lines[0].split("\t")
    rows: dict[str, dict[str, Any]] = {}
    for line in lines[2:]:
        values = line.split("\t")
        record = dict(zip(header, values, strict=False))
        site_no = record.get("site_no")
        if site_no:
            rows[site_no] = {
                "site_no": site_no,
                "station_nm": record.get("station_nm"),
                "site_tp_cd": record.get("site_tp_cd"),
                "dec_lat_va": record.get("dec_lat_va"),
                "dec_long_va": record.get("dec_long_va"),
                "huc_cd": record.get("huc_cd"),
                "state_cd": record.get("state_cd"),
                "county_cd": record.get("county_cd"),
                "source_url": "https://waterservices.usgs.gov/nwis/site/",
            }
    return rows


def _build_report(
    *,
    records: list[dict[str, Any]],
    source_summaries: list[dict[str, Any]],
    output: Path,
    enriched_usgs: bool,
) -> dict[str, Any]:
    return {
        "report_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "status": "pass",
        "scope": "local approved hydrofabric geopackages",
        "output": str(output),
        "record_count": len(records),
        "unique_usgs_gage_count": len({record["usgs_gage_id"] for record in records}),
        "unique_troute_feature_count": len({record["troute_feature_id"] for record in records}),
        "vpu_ids": sorted({record["vpu_id"] for record in records}),
        "vpu_counts": _count_by(records, "vpu_id"),
        "state_counts": _count_by(records, "state_code"),
        "map_ready_record_count": sum(
            1 for record in records if record.get("latitude") is not None and record.get("longitude") is not None
        ),
        "comid_status_counts": _count_by(records, "comid_status"),
        "enriched_usgs": enriched_usgs,
        "usgs_enrichment": "enabled" if enriched_usgs else "disabled",
        "source_resource_count": len(source_summaries),
        "source_resources": source_summaries,
    }


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Site Directory Summary",
        "",
        f"- Status: {report['status']}",
        f"- Scope: {report['scope']}",
        f"- Output: `{report['output']}`",
        f"- Records: {report['record_count']}",
        f"- Unique USGS gages: {report['unique_usgs_gage_count']}",
        f"- Unique t-route features: {report['unique_troute_feature_count']}",
        f"- Map-ready records: {report['map_ready_record_count']}",
        f"- VPUs: {', '.join(report['vpu_ids'])}",
        f"- USGS enrichment: {report['usgs_enrichment']}",
        "",
        "## COMID Status",
    ]
    for key, value in sorted(report["comid_status_counts"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## VPU Counts"])
    for key, value in sorted(report["vpu_counts"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## State Counts"])
    for key, value in sorted(report["state_counts"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Source Resources"])
    for source in report["source_resources"]:
        lines.append(f"- `{source['path']}`: {source['record_count']} records")
    lines.append("")
    return "\n".join(lines)


def _count_by(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = str(record.get(key) or "missing")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _normalise_gage(value: Any) -> str:
    gage = str(value or "").strip()
    match = re.search(r"(\d{7,15})", gage)
    return match.group(1) if match else ""


def _optional_float(raw: Any) -> float | None:
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
