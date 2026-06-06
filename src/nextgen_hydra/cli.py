"""Command line interface for NextGen Hydra."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .classifier import classify_records
from .config import (
    ConfigError,
    load_project,
    mapped_site_count,
    proof_download_max_object_bytes,
    proof_download_max_total_bytes,
    require_all_sites_mapped,
)
from .crosswalk import (
    CrosswalkError,
    load_site_crosswalk,
    resolve_site_crosswalk,
    write_crosswalk_report,
    write_site_crosswalk,
)
from .discovery import (
    DiscoveryError,
    run_mapped_site_manifest_discovery,
    run_proof_of_access,
)
from .download import (
    DownloadSafetyError,
    download_plan_metadata,
    download_manifest_file,
    manifest_file_metadata,
    normalize_approval_id,
)
from .future import write_future_scaffold
from .inventory import inventory_raw_files
from .manifest import (
    ManifestError,
    build_manifest_records,
    build_manifest_summary,
    find_candidate_issues,
    read_jsonl,
    require_no_blocking_candidate_issues,
    validate_manifest_records,
    write_manifest_summary,
    write_jsonl,
)
from .qc import build_qc_report, write_qc_report
from .resources import (
    ResourceError,
    build_resource_manifest_records,
    build_resource_manifest_summary,
    download_resource_manifest_file,
    write_resource_download_summary,
    write_resource_manifest_summary,
)
from .schema_inspection import (
    SchemaInspectionError,
    assert_schema_inspection_passed,
    build_schema_inspection_report,
    write_schema_inspection_report,
)
from .tidy import TidyError, tidy_manifest_records


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (
        ConfigError,
        DiscoveryError,
        ManifestError,
        DownloadSafetyError,
        ResourceError,
        CrosswalkError,
        SchemaInspectionError,
        TidyError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nextgen-hydra",
        description="Manifest-driven NRDS NextGen streamflow acquisition CLI",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="project root containing docs/ and configs/",
    )
    parser.add_argument(
        "--defaults",
        type=Path,
        default=None,
        help="defaults YAML path; defaults to configs/defaults.yaml",
    )
    parser.add_argument(
        "--sites",
        type=Path,
        default=None,
        help="sites YAML path; defaults to configs/sites.yaml",
    )
    subcommands = parser.add_subparsers(required=True)

    validate_config = subcommands.add_parser("validate-config")
    validate_config.set_defaults(func=cmd_validate_config)

    discover = subcommands.add_parser("discover-nrds")
    discover.add_argument("--output", type=Path, default=Path("reports/discovery.jsonl"))
    discover.add_argument("--max-date-prefixes", type=int, default=1)
    discover.add_argument("--max-run-types", type=int, default=2)
    discover.add_argument("--max-cycles", type=int, default=1)
    discover.add_argument("--max-vpus", type=int, default=2)
    discover.add_argument("--max-objects-per-prefix", type=int, default=25)
    discover.set_defaults(func=cmd_discover)

    classify = subcommands.add_parser("classify-products")
    classify.add_argument("--input", type=Path, required=True)
    classify.add_argument("--output", type=Path, required=True)
    classify.add_argument(
        "--allow-oversized",
        action="store_true",
        help="classify oversized approved-shape objects as approved; requires later approval to download",
    )
    classify.set_defaults(func=cmd_classify)

    manifest = subcommands.add_parser("build-manifest")
    manifest.add_argument(
        "--discovery",
        type=Path,
        required=False,
        help="existing discovery/classification JSONL; omit to run targeted mapped-VPU metadata discovery",
    )
    manifest.add_argument("--output", type=Path, default=Path("manifests/manifest.jsonl"))
    manifest.add_argument("--run-date", default=None, help="YYYYMMDD; defaults to latest listed date per stream")
    manifest.add_argument("--run-type", default=None, help="required for targeted discovery, for example short_range")
    manifest.add_argument("--cycle", default=None, help="required for targeted discovery, for example 00")
    manifest.add_argument("--max-objects-per-prefix", type=int, default=100)
    manifest.add_argument(
        "--discovery-output",
        type=Path,
        default=Path("reports/manifest_discovery.jsonl"),
        help="where targeted discovery metadata is written",
    )
    manifest.add_argument(
        "--summary-output",
        type=Path,
        default=Path("reports/manifest_summary.json"),
    )
    manifest.add_argument(
        "--summary-markdown",
        type=Path,
        default=Path("reports/manifest_summary.md"),
    )
    manifest.add_argument(
        "--not-approved-for-download",
        action="store_true",
        help="write approved products with approved_for_download=false",
    )
    manifest.set_defaults(func=cmd_build_manifest)

    validate_manifest = subcommands.add_parser("validate-manifest")
    validate_manifest.add_argument("--manifest", type=Path, required=True)
    validate_manifest.add_argument("--allow-oversized", action="store_true")
    validate_manifest.set_defaults(func=cmd_validate_manifest)

    download = subcommands.add_parser("download")
    download.add_argument("--manifest", type=Path, required=True)
    download.add_argument("--raw-dir", type=Path, default=None)
    download.add_argument("--plan-output", type=Path, default=Path("reports/download_plan.jsonl"))
    download.add_argument("--provenance", type=Path, default=None)
    download.add_argument(
        "--execute",
        action="store_true",
        help="execute the approved plan; also implied by --approval-id",
    )
    download.add_argument("--approval-id", default=None)
    download.add_argument("--milestone", type=int, default=None)
    download.add_argument("--allow-oversized", action="store_true")
    download.add_argument("--inventory-output", type=Path, default=None)
    download.add_argument(
        "--summary-output",
        type=Path,
        default=Path("reports/milestone4_download_summary.json"),
    )
    download.add_argument(
        "--summary-markdown",
        type=Path,
        default=Path("reports/milestone4_download_summary.md"),
    )
    download.set_defaults(func=cmd_download)

    resource_manifest = subcommands.add_parser("build-resource-manifest")
    resource_manifest.add_argument(
        "--output",
        type=Path,
        default=Path("manifests/resource_manifest.jsonl"),
    )
    resource_manifest.add_argument(
        "--summary-output",
        type=Path,
        default=Path("reports/resource_manifest_summary.json"),
    )
    resource_manifest.add_argument(
        "--summary-markdown",
        type=Path,
        default=Path("reports/resource_manifest_summary.md"),
    )
    resource_manifest.add_argument(
        "--not-approved-for-download",
        action="store_true",
        help="write approved resources with approved_for_download=false",
    )
    resource_manifest.set_defaults(func=cmd_build_resource_manifest)

    resource_download = subcommands.add_parser("download-resources")
    resource_download.add_argument(
        "--manifest",
        type=Path,
        default=Path("manifests/resource_manifest.jsonl"),
    )
    resource_download.add_argument("--resource-dir", type=Path, default=None)
    resource_download.add_argument(
        "--plan-output",
        type=Path,
        default=Path("reports/resource_download_plan.jsonl"),
    )
    resource_download.add_argument("--provenance", type=Path, default=None)
    resource_download.add_argument(
        "--execute",
        action="store_true",
        help="execute the approved resource plan; also implied by --approval-id",
    )
    resource_download.add_argument("--approval-id", default=None)
    resource_download.add_argument(
        "--summary-output",
        type=Path,
        default=Path("reports/resource_download_summary.json"),
    )
    resource_download.add_argument(
        "--summary-markdown",
        type=Path,
        default=Path("reports/resource_download_summary.md"),
    )
    resource_download.set_defaults(func=cmd_download_resources)

    crosswalk = subcommands.add_parser("resolve-site-crosswalk")
    crosswalk.add_argument(
        "--sites",
        type=Path,
        dest="crosswalk_sites",
        default=None,
        help="sites YAML path; defaults to configs/sites.yaml",
    )
    crosswalk.add_argument("--resource-dir", type=Path, default=None)
    crosswalk.add_argument(
        "--output",
        type=Path,
        default=Path("configs/site_crosswalk.yaml"),
    )
    crosswalk.add_argument(
        "--report",
        type=Path,
        default=Path("reports/site_crosswalk_report.json"),
    )
    crosswalk.set_defaults(func=cmd_resolve_site_crosswalk)

    inventory = subcommands.add_parser("inventory")
    inventory.add_argument("--manifest", type=Path, required=False)
    inventory.add_argument("--raw-dir", type=Path, default=None)
    inventory.add_argument("--output", type=Path, default=Path("data/inventory/inventory.jsonl"))
    inventory.set_defaults(func=cmd_inventory)

    inspect_schema = subcommands.add_parser("inspect-schema")
    inspect_schema.add_argument("--manifest", type=Path, required=True)
    inspect_schema.add_argument("--raw-dir", type=Path, default=None)
    inspect_schema.add_argument(
        "--site-crosswalk",
        type=Path,
        default=Path("configs/site_crosswalk.yaml"),
    )
    inspect_schema.add_argument(
        "--output",
        type=Path,
        default=Path("reports/schema_inspection.json"),
    )
    inspect_schema.add_argument(
        "--markdown",
        type=Path,
        default=Path("reports/schema_inspection.md"),
    )
    inspect_schema.set_defaults(func=cmd_inspect_schema)

    tidy = subcommands.add_parser("tidy")
    tidy.add_argument("--manifest", type=Path, required=True)
    tidy.add_argument("--raw-dir", type=Path, default=None)
    tidy.add_argument("--output-dir", type=Path, default=None)
    tidy.add_argument("--catalog-output", type=Path, default=Path("data/tidy/catalog.jsonl"))
    tidy.add_argument(
        "--site-crosswalk",
        type=Path,
        default=Path("configs/site_crosswalk.yaml"),
    )
    tidy.add_argument("--feature-id-column", required=True)
    tidy.add_argument("--time-column", required=True)
    tidy.add_argument("--flow-column", required=True)
    tidy.add_argument("--flow-units", required=True)
    tidy.add_argument("--output-format", choices=["parquet", "csv"], default="parquet")
    tidy.set_defaults(func=cmd_tidy)

    qc = subcommands.add_parser("qc-report")
    qc.add_argument("--manifest", type=Path, required=False)
    qc.add_argument("--inventory", type=Path, required=False)
    qc.add_argument("--catalog", type=Path, required=False)
    qc.add_argument("--schema-inspection", type=Path, required=False)
    qc.add_argument("--download-summary", type=Path, required=False)
    qc.add_argument("--output", type=Path, default=Path("reports/qc_report.md"))
    qc.add_argument("--json-output", type=Path, default=Path("reports/qc_report.json"))
    qc.set_defaults(func=cmd_qc)

    future = subcommands.add_parser("future-scaffold")
    future.add_argument(
        "--output",
        type=Path,
        default=Path("docs/future_external_inputs.md"),
    )
    future.set_defaults(func=cmd_future)
    return parser


def cmd_validate_config(args: argparse.Namespace) -> int:
    defaults, sites = _load(args)
    require_all_sites_mapped(sites)
    summary = {
        "status": "ok",
        "site_count": len(sites),
        "mapped_site_count": mapped_site_count(sites),
        "bucket": defaults["nrds"]["s3_bucket"],
        "candidate_streams": defaults["nrds"]["candidate_streams"],
        "hydrofabric_version": defaults["nrds"]["hydrofabric_version"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    defaults, _sites = _load(args)
    rows = run_proof_of_access(
        defaults,
        max_date_prefixes=args.max_date_prefixes,
        max_run_types=args.max_run_types,
        max_cycles=args.max_cycles,
        max_vpus=args.max_vpus,
        max_objects_per_prefix=args.max_objects_per_prefix,
    )
    write_jsonl(args.output, rows)
    object_rows = [row for row in rows if row.get("record_type") == "object"]
    print(
        json.dumps(
            {
                "output": str(args.output),
                "listing_records": len(rows) - len(object_rows),
                "object_records": len(object_rows),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def cmd_classify(args: argparse.Namespace) -> int:
    defaults, _sites = _load(args)
    rows = read_jsonl(args.input)
    classified = classify_records(
        rows,
        defaults,
        allow_oversized=args.allow_oversized,
    )
    write_jsonl(args.output, classified)
    counts: dict[str, int] = {}
    for row in classified:
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1
    print(json.dumps({"output": str(args.output), "counts": counts}, indent=2, sort_keys=True))
    return 0


def cmd_build_manifest(args: argparse.Namespace) -> int:
    defaults, sites = _load(args)
    require_all_sites_mapped(sites)
    discovery_path = args.discovery
    target: dict[str, object] = {}
    if discovery_path is None:
        if not args.run_type or not args.cycle:
            raise ManifestError(
                "targeted build-manifest requires --run-type and --cycle; "
                "provide --discovery to build from an existing discovery JSONL"
            )
        rows = run_mapped_site_manifest_discovery(
            defaults,
            sites,
            run_date=args.run_date,
            run_type=args.run_type,
            cycle=args.cycle,
            max_objects_per_prefix=args.max_objects_per_prefix,
        )
        write_jsonl(args.discovery_output, rows)
        discovery_path = args.discovery_output
        target = {
            "mode": "targeted-mapped-site-discovery",
            "run_date": args.run_date or "latest-listed-per-stream",
            "run_type": args.run_type,
            "cycle": args.cycle,
            "max_objects_per_prefix": args.max_objects_per_prefix,
        }
        require_no_blocking_candidate_issues(find_candidate_issues(rows, defaults))
    else:
        rows = read_jsonl(discovery_path)
        target = {"mode": "existing-discovery"}
    manifest = build_manifest_records(
        rows,
        sites,
        defaults,
        approved_for_download=not args.not_approved_for_download,
    )
    validate_manifest_records(manifest, defaults, sites=sites)
    summary = build_manifest_summary(
        manifest_records=manifest,
        discovery_records=rows,
        sites=sites,
        defaults=defaults,
        manifest_path=args.output,
        discovery_path=discovery_path,
        target=target,
    )
    max_total = proof_download_max_total_bytes(defaults)
    if summary["manifest"]["site_scoped_size_bytes"] > max_total:
        raise ManifestError(
            "manifest site-scoped byte total "
            f"{summary['manifest']['site_scoped_size_bytes']} exceeds active "
            f"download threshold {max_total}; approval is required before continuing"
        )
    write_jsonl(args.output, manifest)
    write_manifest_summary(
        summary=summary,
        json_path=args.summary_output,
        markdown_path=args.summary_markdown,
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "records": len(manifest),
                "unique_objects": summary["manifest"]["unique_object_count"],
                "site_scoped_size_bytes": summary["manifest"]["site_scoped_size_bytes"],
                "unique_size_bytes": summary["manifest"]["unique_size_bytes"],
                "discovery_output": str(discovery_path) if discovery_path else None,
                "summary_output": str(args.summary_output),
                "summary_markdown": str(args.summary_markdown),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def cmd_validate_manifest(args: argparse.Namespace) -> int:
    defaults, sites = _load(args)
    require_all_sites_mapped(sites)
    rows = read_jsonl(args.manifest)
    validated = validate_manifest_records(
        rows,
        defaults,
        sites=sites,
        allow_oversized=args.allow_oversized,
    )
    print(json.dumps({"status": "ok", "records": len(validated)}, indent=2, sort_keys=True))
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    defaults, sites = _load(args)
    require_all_sites_mapped(sites)
    raw_dir = args.raw_dir or Path(defaults["paths"]["raw_data_dir"])
    approval_id = normalize_approval_id(args.approval_id)
    execute = args.execute or approval_id is not None
    provenance = args.provenance
    if provenance is None and execute:
        provenance = Path(defaults["paths"]["reports_dir"]) / "download_provenance.jsonl"
    started_at = _utc_now()
    plan = download_manifest_file(
        manifest_path=args.manifest,
        raw_dir=raw_dir,
        defaults=defaults,
        execute=execute,
        approval_id=approval_id,
        milestone=args.milestone,
        allow_oversized=args.allow_oversized,
        sites=sites,
        plan_output=args.plan_output,
        provenance_path=provenance,
    )
    finished_at = _utc_now()
    inventory_output = None
    inventory_records = None
    if execute:
        inventory_output = args.inventory_output or (
            Path(defaults["paths"]["inventory_dir"]) / "inventory.jsonl"
        )
        inventory_records = inventory_raw_files(raw_dir, read_jsonl(args.manifest))
        write_jsonl(inventory_output, inventory_records)
    _write_download_summary(
        path=args.summary_output,
        markdown_path=args.summary_markdown,
        mode="execute" if execute else "dry-run",
        approval_id=approval_id if execute else None,
        manifest_path=args.manifest,
        plan_output=args.plan_output,
        provenance_path=provenance,
        inventory_output=inventory_output,
        inventory_records=inventory_records,
        plan=plan,
        defaults=defaults,
        started_at=started_at,
        finished_at=finished_at,
    )
    print(
        json.dumps(
            {
                "mode": "execute" if execute else "dry-run",
                "plan_output": str(args.plan_output) if args.plan_output else None,
                "summary_output": str(args.summary_output) if args.summary_output else None,
                "summary_markdown": str(args.summary_markdown) if args.summary_markdown else None,
                "provenance": str(provenance) if provenance else None,
                "inventory_output": str(inventory_output) if inventory_output else None,
                "actions": _count_actions(plan),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def cmd_build_resource_manifest(args: argparse.Namespace) -> int:
    defaults, sites = _load(args)
    require_all_sites_mapped(sites)
    records = build_resource_manifest_records(
        defaults=defaults,
        sites=sites,
        approved_for_download=not args.not_approved_for_download,
    )
    write_jsonl(args.output, records)
    summary = build_resource_manifest_summary(
        records=records,
        defaults=defaults,
        manifest_path=args.output,
    )
    write_resource_manifest_summary(
        summary=summary,
        json_path=args.summary_output,
        markdown_path=args.summary_markdown,
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "records": len(records),
                "unique_objects": summary["unique_object_count"],
                "total_size_bytes": summary["total_size_bytes"],
                "summary_output": str(args.summary_output),
                "summary_markdown": str(args.summary_markdown),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def cmd_download_resources(args: argparse.Namespace) -> int:
    defaults, sites = _load(args)
    require_all_sites_mapped(sites)
    resource_dir = args.resource_dir or Path(defaults["paths"]["resources_data_dir"])
    approval_id = normalize_approval_id(args.approval_id)
    execute = args.execute or approval_id is not None
    provenance = args.provenance
    if provenance is None and execute:
        provenance = Path(defaults["paths"]["reports_dir"]) / "resource_download_provenance.jsonl"
    plan = download_resource_manifest_file(
        manifest_path=args.manifest,
        resource_dir=resource_dir,
        defaults=defaults,
        sites=sites,
        execute=execute,
        approval_id=approval_id,
        plan_output=args.plan_output,
        provenance_path=provenance,
    )
    write_resource_download_summary(
        path=args.summary_output,
        markdown_path=args.summary_markdown,
        manifest_path=args.manifest,
        plan_output=args.plan_output,
        provenance_path=provenance,
        approval_id=approval_id if execute else None,
        mode="execute" if execute else "dry-run",
        plan=plan,
    )
    print(
        json.dumps(
            {
                "mode": "execute" if execute else "dry-run",
                "plan_output": str(args.plan_output),
                "summary_output": str(args.summary_output),
                "summary_markdown": str(args.summary_markdown),
                "provenance": str(provenance) if provenance else None,
                "actions": _count_actions(plan),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def cmd_resolve_site_crosswalk(args: argparse.Namespace) -> int:
    defaults, sites = load_project(
        args.root,
        args.defaults,
        args.crosswalk_sites or args.sites,
    )
    require_all_sites_mapped(sites)
    resource_dir = args.resource_dir or Path(defaults["paths"]["resources_data_dir"])
    crosswalk, report = resolve_site_crosswalk(
        sites=sites,
        defaults=defaults,
        resource_dir=resource_dir,
    )
    write_site_crosswalk(args.output, crosswalk)
    write_crosswalk_report(args.report, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "output": str(args.output),
                "report": str(args.report),
                "resolved_count": report["resolved_count"],
                "site_count": report["site_count"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def cmd_inventory(args: argparse.Namespace) -> int:
    defaults, sites = _load(args)
    require_all_sites_mapped(sites)
    raw_dir = args.raw_dir or Path(defaults["paths"]["raw_data_dir"])
    manifest = read_jsonl(args.manifest) if args.manifest else None
    rows = inventory_raw_files(raw_dir, manifest)
    write_jsonl(args.output, rows)
    print(json.dumps({"output": str(args.output), "records": len(rows)}, indent=2, sort_keys=True))
    return 0


def cmd_inspect_schema(args: argparse.Namespace) -> int:
    defaults, sites = _load(args)
    require_all_sites_mapped(sites)
    raw_dir = args.raw_dir or Path(defaults["paths"]["raw_data_dir"])
    site_crosswalk = _load_crosswalk_if_present(args.site_crosswalk)
    report = build_schema_inspection_report(
        manifest_records=read_jsonl(args.manifest),
        defaults=defaults,
        sites=sites,
        raw_dir=raw_dir,
        site_crosswalk=site_crosswalk,
    )
    write_schema_inspection_report(
        report=report,
        json_path=args.output,
        markdown_path=args.markdown,
    )
    assert_schema_inspection_passed(report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "output": str(args.output),
                "markdown": str(args.markdown),
                "objects": report["object_count"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def cmd_tidy(args: argparse.Namespace) -> int:
    defaults, sites = _load(args)
    require_all_sites_mapped(sites)
    raw_dir = args.raw_dir or Path(defaults["paths"]["raw_data_dir"])
    output_dir = args.output_dir or Path(defaults["paths"]["tidy_data_dir"])
    manifest = read_jsonl(args.manifest)
    site_crosswalk = load_site_crosswalk(args.site_crosswalk)
    catalog = tidy_manifest_records(
        manifest_records=manifest,
        defaults=defaults,
        raw_dir=raw_dir,
        output_dir=output_dir,
        feature_id_column=args.feature_id_column,
        time_column=args.time_column,
        flow_column=args.flow_column,
        flow_units=args.flow_units,
        output_format=args.output_format,
        sites=sites,
        site_crosswalk=site_crosswalk,
        require_crosswalk=True,
    )
    write_jsonl(args.catalog_output, catalog)
    print(
        json.dumps(
            {"catalog_output": str(args.catalog_output), "records": len(catalog)},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def cmd_qc(args: argparse.Namespace) -> int:
    _defaults, sites = _load(args)
    require_all_sites_mapped(sites)
    manifest = read_jsonl(args.manifest) if args.manifest else []
    inventory = read_jsonl(args.inventory) if args.inventory else []
    catalog = read_jsonl(args.catalog) if args.catalog else []
    schema_inspection = _read_json(args.schema_inspection) if args.schema_inspection else None
    download_summary = _read_json(args.download_summary) if args.download_summary else None
    report = build_qc_report(
        manifest_records=manifest,
        inventory_records=inventory,
        catalog_records=catalog,
        schema_inspection=schema_inspection,
        download_summary=download_summary,
    )
    write_qc_report(report=report, markdown_path=args.output, json_path=args.json_output)
    print(json.dumps({"output": str(args.output), "json_output": str(args.json_output)}, indent=2, sort_keys=True))
    return 0


def cmd_future(args: argparse.Namespace) -> int:
    _defaults, _sites = _load(args)
    write_future_scaffold(args.output)
    print(json.dumps({"output": str(args.output)}, indent=2, sort_keys=True))
    return 0


def _load(args: argparse.Namespace):
    return load_project(args.root, args.defaults, args.sites)


def _load_crosswalk_if_present(path: Path | None) -> dict[str, object] | None:
    if path is None or not path.exists():
        return None
    return load_site_crosswalk(path)


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _count_actions(plan: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in plan:
        action = str(row["action"])
        counts[action] = counts.get(action, 0) + 1
    return counts


def _write_download_summary(
    *,
    path: Path | None,
    markdown_path: Path | None,
    mode: str,
    approval_id: str | None,
    manifest_path: Path,
    plan_output: Path | None,
    provenance_path: Path | None,
    inventory_output: Path | None,
    inventory_records: list[dict[str, object]] | None,
    plan: list[dict[str, object]],
    defaults: dict[str, object],
    started_at: str,
    finished_at: str,
) -> None:
    if path is None and markdown_path is None:
        return
    metadata = manifest_file_metadata(manifest_path)
    plan_metadata = download_plan_metadata(plan, plan_output)
    pending_actions = {"download", "replace"}
    summary = {
        "summary_version": 1,
        "mode": mode,
        "approval_id": approval_id,
        "download_started_at_utc": started_at,
        "download_finished_at_utc": finished_at,
        "manifest_path": str(manifest_path),
        **metadata,
        **plan_metadata,
        "plan_output": str(plan_output) if plan_output else None,
        "provenance": str(provenance_path) if provenance_path else None,
        "inventory_output": str(inventory_output) if inventory_output else None,
        "actions": _count_actions(plan),
        "executed_bytes": sum(int(row.get("executed_size_bytes") or 0) for row in plan),
        "projected_download_bytes": sum(
            int(row["size_bytes"])
            for row in plan
            if row["action"] in pending_actions
        ),
        "max_planned_object_bytes": max(
            (int(row["size_bytes"]) for row in plan if row["action"] in pending_actions),
            default=0,
        ),
        "inventory_record_count": 0 if inventory_records is None else len(inventory_records),
        "safety_thresholds": {
            "max_object_bytes": proof_download_max_object_bytes(defaults),
            "max_total_bytes": proof_download_max_total_bytes(defaults),
        },
    }
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    if markdown_path is not None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(_render_download_summary(summary), encoding="utf-8")


def _render_download_summary(summary: dict[str, object]) -> str:
    return "\n".join(
        [
            "# NextGen Hydra Milestone 4 Download Summary",
            "",
            f"Mode: `{summary['mode']}`",
            f"Approval ID: `{summary.get('approval_id')}`",
            f"Started UTC: `{summary['download_started_at_utc']}`",
            f"Finished UTC: `{summary['download_finished_at_utc']}`",
            "",
            "## Manifest and Plan",
            "",
            f"- Manifest: `{summary['manifest_path']}`",
            f"- Manifest SHA256: `{summary['manifest_sha256']}`",
            f"- Plan: `{summary.get('plan_output')}`",
            f"- Plan SHA256: `{summary['download_plan_sha256']}`",
            f"- Unique objects: {summary['planned_unique_object_count']}",
            f"- Planned unique bytes: {summary['planned_unique_bytes']}",
            f"- Projected download bytes: {summary['projected_download_bytes']}",
            f"- Executed bytes: {summary['executed_bytes']}",
            f"- Actions: `{summary['actions']}`",
            "",
        ]
    )


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
