"""Command line interface for NextGen Hydra."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .classifier import classify_records
from .config import ConfigError, load_project
from .discovery import DiscoveryError, run_proof_of_access
from .download import DownloadSafetyError, download_manifest_file
from .future import write_future_scaffold
from .inventory import inventory_raw_files
from .manifest import (
    ManifestError,
    build_manifest_records,
    read_jsonl,
    validate_manifest_records,
    write_jsonl,
)
from .qc import build_qc_report, write_qc_report
from .tidy import TidyError, tidy_manifest_records


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, DiscoveryError, ManifestError, DownloadSafetyError, TidyError) as exc:
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
    manifest.add_argument("--discovery", type=Path, required=True)
    manifest.add_argument("--output", type=Path, default=Path("manifests/manifest.jsonl"))
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
    download.add_argument("--execute", action="store_true")
    download.add_argument("--approval-id", default=None)
    download.add_argument("--milestone", type=int, default=None)
    download.add_argument("--allow-oversized", action="store_true")
    download.set_defaults(func=cmd_download)

    inventory = subcommands.add_parser("inventory")
    inventory.add_argument("--manifest", type=Path, required=False)
    inventory.add_argument("--raw-dir", type=Path, default=None)
    inventory.add_argument("--output", type=Path, default=Path("data/inventory/inventory.jsonl"))
    inventory.set_defaults(func=cmd_inventory)

    tidy = subcommands.add_parser("tidy")
    tidy.add_argument("--manifest", type=Path, required=True)
    tidy.add_argument("--raw-dir", type=Path, default=None)
    tidy.add_argument("--output-dir", type=Path, default=None)
    tidy.add_argument("--catalog-output", type=Path, default=Path("data/tidy/catalog.jsonl"))
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
    summary = {
        "status": "ok",
        "site_count": len(sites),
        "mapped_site_count": sum(1 for site in sites if site.is_mapped),
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
    rows = read_jsonl(args.discovery)
    manifest = build_manifest_records(
        rows,
        sites,
        defaults,
        approved_for_download=not args.not_approved_for_download,
    )
    validate_manifest_records(manifest, defaults)
    write_jsonl(args.output, manifest)
    print(json.dumps({"output": str(args.output), "records": len(manifest)}, indent=2, sort_keys=True))
    return 0


def cmd_validate_manifest(args: argparse.Namespace) -> int:
    defaults, _sites = _load(args)
    rows = read_jsonl(args.manifest)
    validated = validate_manifest_records(
        rows,
        defaults,
        allow_oversized=args.allow_oversized,
    )
    print(json.dumps({"status": "ok", "records": len(validated)}, indent=2, sort_keys=True))
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    defaults, _sites = _load(args)
    raw_dir = args.raw_dir or Path(defaults["paths"]["raw_data_dir"])
    provenance = args.provenance
    if provenance is None and args.execute:
        provenance = Path(defaults["paths"]["provenance_dir"]) / "download_events.jsonl"
    plan = download_manifest_file(
        manifest_path=args.manifest,
        raw_dir=raw_dir,
        defaults=defaults,
        execute=args.execute,
        approval_id=args.approval_id,
        milestone=args.milestone,
        allow_oversized=args.allow_oversized,
        plan_output=args.plan_output,
        provenance_path=provenance,
    )
    print(
        json.dumps(
            {
                "mode": "execute" if args.execute else "dry-run",
                "plan_output": str(args.plan_output) if args.plan_output else None,
                "actions": _count_actions(plan),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def cmd_inventory(args: argparse.Namespace) -> int:
    defaults, _sites = _load(args)
    raw_dir = args.raw_dir or Path(defaults["paths"]["raw_data_dir"])
    manifest = read_jsonl(args.manifest) if args.manifest else None
    rows = inventory_raw_files(raw_dir, manifest)
    write_jsonl(args.output, rows)
    print(json.dumps({"output": str(args.output), "records": len(rows)}, indent=2, sort_keys=True))
    return 0


def cmd_tidy(args: argparse.Namespace) -> int:
    defaults, _sites = _load(args)
    raw_dir = args.raw_dir or Path(defaults["paths"]["raw_data_dir"])
    output_dir = args.output_dir or Path(defaults["paths"]["tidy_data_dir"])
    manifest = read_jsonl(args.manifest)
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
    _defaults, _sites = _load(args)
    manifest = read_jsonl(args.manifest) if args.manifest else []
    inventory = read_jsonl(args.inventory) if args.inventory else []
    catalog = read_jsonl(args.catalog) if args.catalog else []
    report = build_qc_report(
        manifest_records=manifest,
        inventory_records=inventory,
        catalog_records=catalog,
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


def _count_actions(plan: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in plan:
        action = str(row["action"])
        counts[action] = counts.get(action, 0) + 1
    return counts


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
