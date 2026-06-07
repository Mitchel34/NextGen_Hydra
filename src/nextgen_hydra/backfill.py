"""Dry-run historical backfill planning without object-body downloads."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
from typing import Any

from .config import Site
from .discovery import run_mapped_site_manifest_discovery
from .manifest import (
    ManifestError,
    build_manifest_records,
    build_manifest_summary,
    find_candidate_issues,
    require_no_blocking_candidate_issues,
    validate_manifest_records,
)


class BackfillPlanError(RuntimeError):
    """Raised when a proposed backfill window is unsafe."""


def build_backfill_plan(
    *,
    defaults: dict[str, Any],
    sites: list[Site],
    start_date: str,
    end_date: str,
    run_type: str = "short_range",
    cycle: str = "00",
    max_days: int = 7,
    max_objects_per_prefix: int = 100,
    manifest_path: Path = Path("manifests/backfill_manifest.jsonl"),
    discovery_path: Path = Path("reports/backfill_discovery.jsonl"),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Build a bounded backfill manifest and summary from listing metadata only."""

    dates = _date_window(start_date, end_date, max_days=max_days)
    discovery_records: list[dict[str, Any]] = []
    date_errors: dict[str, str] = {}
    for day in dates:
        run_date = day.strftime("%Y%m%d")
        try:
            discovery_records.extend(
                run_mapped_site_manifest_discovery(
                    defaults,
                    sites,
                    run_date=run_date,
                    run_type=run_type,
                    cycle=cycle,
                    max_objects_per_prefix=max_objects_per_prefix,
                )
            )
        except Exception as exc:  # noqa: BLE001 - report per-date discovery failures.
            date_errors[run_date] = str(exc)
    if date_errors:
        raise BackfillPlanError(
            "backfill discovery failed for date(s): "
            + json.dumps(date_errors, sort_keys=True)
        )

    issues = find_candidate_issues(discovery_records, defaults)
    try:
        require_no_blocking_candidate_issues(issues)
    except ManifestError as exc:
        raise BackfillPlanError(str(exc)) from exc

    manifest = build_manifest_records(
        discovery_records,
        sites,
        defaults,
        approved_for_download=True,
    )
    validate_manifest_records(manifest, defaults, sites=sites)
    summary = build_manifest_summary(
        manifest_records=manifest,
        discovery_records=discovery_records,
        sites=sites,
        defaults=defaults,
        manifest_path=manifest_path,
        discovery_path=discovery_path,
        target={
            "mode": "bounded-backfill-dry-run",
            "start_date": start_date,
            "end_date": end_date,
            "run_dates": [day.strftime("%Y%m%d") for day in dates],
            "run_type": run_type,
            "cycle": cycle,
            "max_days": max_days,
            "max_objects_per_prefix": max_objects_per_prefix,
            "object_body_downloads": False,
        },
    )
    streamflow_records = [
        record for record in manifest if record["product_type"] == "troute_streamflow_output"
    ]
    summary["backfill"] = {
        "status": "planned",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "object_body_downloads": False,
        "requires_approval_id_before_download": True,
        "date_count": len(dates),
        "run_dates": [day.strftime("%Y%m%d") for day in dates],
        "streams": sorted({str(record["stream"]) for record in streamflow_records}),
        "vpus": sorted({str(record["vpu_id"]) for record in streamflow_records}),
        "streamflow_record_count": len(streamflow_records),
        "estimated_tidy_rows": len(streamflow_records) * 18,
        "estimate_note": "short_range currently contributes 18 hourly rows per site-scoped troute record after tidy",
    }
    return discovery_records, manifest, summary


def write_backfill_plan_summary(
    *,
    summary: dict[str, Any],
    json_path: Path,
    markdown_path: Path | None,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    if markdown_path is not None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_backfill_plan_markdown(summary), encoding="utf-8")


def render_backfill_plan_markdown(summary: dict[str, Any]) -> str:
    manifest = summary["manifest"]
    backfill = summary["backfill"]
    lines = [
        "# NextGen Hydra Backfill Plan",
        "",
        f"Status: `{backfill['status']}`",
        f"Object-body downloads: `{backfill['object_body_downloads']}`",
        f"Requires approval before download: `{backfill['requires_approval_id_before_download']}`",
        "",
        "## Window",
        "",
        f"- Dates: `{backfill['run_dates']}`",
        f"- Streams: `{backfill['streams']}`",
        f"- VPUs: `{backfill['vpus']}`",
        "",
        "## Planned Manifest",
        "",
        f"- Records: {manifest['record_count']}",
        f"- Unique objects: {manifest['unique_object_count']}",
        f"- Unique bytes: {manifest['unique_size_bytes']}",
        f"- Max object bytes: {manifest['max_object_size_bytes']}",
        f"- Estimated tidy rows: {backfill['estimated_tidy_rows']}",
        "",
        "No object bodies were downloaded while creating this plan.",
        "",
    ]
    return "\n".join(lines)


def _date_window(start: str, end: str, *, max_days: int) -> list[date]:
    try:
        start_day = datetime.strptime(start, "%Y%m%d").date()
        end_day = datetime.strptime(end, "%Y%m%d").date()
    except ValueError as exc:
        raise BackfillPlanError("backfill dates must use YYYYMMDD") from exc
    if end_day < start_day:
        raise BackfillPlanError("backfill end date must be on or after start date")
    count = (end_day - start_day).days + 1
    if count > max_days:
        raise BackfillPlanError(
            f"backfill window has {count} days; maximum allowed is {max_days}"
        )
    return [start_day + timedelta(days=offset) for offset in range(count)]
