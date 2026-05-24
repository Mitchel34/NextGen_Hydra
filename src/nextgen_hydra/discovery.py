"""Discovery-only public NRDS metadata workflow."""

from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Any

from .classifier import classify_object
from .config import Site, require_all_sites_mapped
from .io.s3 import S3ListResult, list_objects_v2, public_url


class DiscoveryError(RuntimeError):
    """Raised when metadata-only discovery hits a stop condition."""


def run_proof_of_access(
    defaults: dict[str, Any],
    *,
    max_date_prefixes: int = 1,
    max_run_types: int = 2,
    max_cycles: int = 1,
    max_vpus: int = 2,
    max_objects_per_prefix: int = 25,
) -> list[dict[str, Any]]:
    """Run the Milestone 1 discovery proof without object-body downloads."""

    if defaults["safety"].get("milestone_1_allow_object_body_downloads") is not False:
        raise DiscoveryError("milestone 1 config must forbid object-body downloads")

    nrds = defaults["nrds"]
    bucket = nrds["s3_bucket"]
    base_url = nrds["public_s3_base_url"]
    records: list[dict[str, Any]] = []

    root = _list(bucket=bucket, prefix="", delimiter="/")
    records.append(_listing_record(root, "bucket-root"))
    _require_prefix(root, "outputs/")

    outputs = _list(bucket=bucket, prefix="outputs/", delimiter="/")
    records.append(_listing_record(outputs, "outputs-root"))
    for stream in nrds["candidate_streams"]:
        _require_prefix(outputs, f"outputs/{stream}/")

    for stream in nrds["candidate_streams"]:
        stream_root = _list(bucket=bucket, prefix=f"outputs/{stream}/", delimiter="/")
        records.append(_listing_record(stream_root, f"{stream}-root"))
        hydro_prefix = f"outputs/{stream}/{nrds['hydrofabric_version']}/"
        _require_prefix(stream_root, hydro_prefix)

        hydro = _list(bucket=bucket, prefix=hydro_prefix, delimiter="/")
        records.append(_listing_record(hydro, f"{stream}-hydrofabric-root"))
        date_prefixes = _latest_prefixes(hydro.common_prefixes, max_date_prefixes)
        if not date_prefixes:
            raise DiscoveryError(f"no date prefixes found under {hydro_prefix}")

        for date_prefix in date_prefixes:
            date_listing = _list(bucket=bucket, prefix=date_prefix, delimiter="/")
            records.append(_listing_record(date_listing, f"{stream}-date"))
            for run_prefix in date_listing.common_prefixes[:max_run_types]:
                cycle_root = _list(bucket=bucket, prefix=run_prefix, delimiter="/")
                records.append(_listing_record(cycle_root, f"{stream}-run-type"))
                for cycle_prefix in cycle_root.common_prefixes[:max_cycles]:
                    vpu_root = _list(bucket=bucket, prefix=cycle_prefix, delimiter="/")
                    records.append(_listing_record(vpu_root, f"{stream}-cycle"))
                    for vpu_prefix in vpu_root.common_prefixes[:max_vpus]:
                        troute_prefix = vpu_prefix + "ngen-run/outputs/troute/"
                        troute = _list(
                            bucket=bucket,
                            prefix=troute_prefix,
                            delimiter=None,
                            max_keys=max_objects_per_prefix,
                        )
                        records.append(_listing_record(troute, f"{stream}-troute"))
                        records.extend(
                            _object_records(
                                troute,
                                defaults=defaults,
                                base_url=base_url,
                                listing_ref=troute_prefix,
                            )
                        )

                        metadata_prefix = (
                            vpu_prefix + defaults["metadata"]["approved_directory"] + "/"
                        )
                        metadata = _list(
                            bucket=bucket,
                            prefix=metadata_prefix,
                            delimiter=None,
                            max_keys=max_objects_per_prefix,
                        )
                        records.append(_listing_record(metadata, f"{stream}-metadata"))
                        records.extend(
                            _object_records(
                                metadata,
                                defaults=defaults,
                                base_url=base_url,
                                listing_ref=metadata_prefix,
                            )
                        )

    object_count = sum(1 for record in records if record.get("record_type") == "object")
    if object_count == 0:
        raise DiscoveryError("metadata-only discovery found no candidate objects")
    return records


def run_mapped_site_manifest_discovery(
    defaults: dict[str, Any],
    sites: list[Site],
    *,
    run_type: str,
    cycle: str,
    run_date: str | None = None,
    max_objects_per_prefix: int = 100,
) -> list[dict[str, Any]]:
    """List only approved candidate prefixes for the configured mapped site VPUs.

    This is the Milestone 3 metadata-only manifest discovery path. It reads S3
    listing metadata only; object bodies are not requested.
    """

    require_all_sites_mapped(sites)
    if not run_type:
        raise DiscoveryError("targeted manifest discovery requires an explicit run_type")
    if not cycle:
        raise DiscoveryError("targeted manifest discovery requires an explicit cycle")
    if run_date is not None and re.fullmatch(r"\d{8}", run_date) is None:
        raise DiscoveryError("run_date must be YYYYMMDD when provided")
    if max_objects_per_prefix <= 0:
        raise DiscoveryError("max_objects_per_prefix must be positive")

    nrds = defaults["nrds"]
    bucket = nrds["s3_bucket"]
    base_url = nrds["public_s3_base_url"]
    target_vpus = sorted({str(site.discovered_vpu_id) for site in sites if site.is_mapped})
    records: list[dict[str, Any]] = []

    for stream in nrds["candidate_streams"]:
        hydro_prefix = f"outputs/{stream}/{nrds['hydrofabric_version']}/"
        hydro_listing = _list(bucket=bucket, prefix=hydro_prefix, delimiter="/")
        records.append(_listing_record(hydro_listing, f"{stream}-manifest-dates"))
        date_prefix = _select_manifest_date_prefix(
            hydro_listing=hydro_listing,
            hydro_prefix=hydro_prefix,
            run_date=run_date,
        )

        date_listing = _list(bucket=bucket, prefix=date_prefix, delimiter="/")
        records.append(_listing_record(date_listing, f"{stream}-manifest-run-types"))
        run_prefix = f"{date_prefix}{run_type}/"
        _require_prefix(date_listing, run_prefix)

        run_listing = _list(bucket=bucket, prefix=run_prefix, delimiter="/")
        records.append(_listing_record(run_listing, f"{stream}-manifest-cycles"))
        cycle_prefix = f"{run_prefix}{cycle}/"
        _require_prefix(run_listing, cycle_prefix)

        cycle_listing = _list(bucket=bucket, prefix=cycle_prefix, delimiter="/")
        records.append(_listing_record(cycle_listing, f"{stream}-manifest-vpus"))
        for vpu_id in target_vpus:
            vpu_prefix = f"{cycle_prefix}VPU_{vpu_id}/"
            _require_prefix(cycle_listing, vpu_prefix)
            records.extend(
                _manifest_object_records(
                    bucket=bucket,
                    base_url=base_url,
                    defaults=defaults,
                    prefix=vpu_prefix + "ngen-run/outputs/troute/",
                    label=f"{stream}-manifest-troute-vpu-{vpu_id}",
                    max_objects_per_prefix=max_objects_per_prefix,
                    expected_filenames=None,
                )
            )
            records.extend(
                _manifest_object_records(
                    bucket=bucket,
                    base_url=base_url,
                    defaults=defaults,
                    prefix=vpu_prefix + defaults["metadata"]["approved_directory"] + "/",
                    label=f"{stream}-manifest-metadata-vpu-{vpu_id}",
                    max_objects_per_prefix=max_objects_per_prefix,
                    expected_filenames=set(defaults["metadata"]["approved_filenames"]),
                )
            )

    object_count = sum(1 for record in records if record.get("record_type") == "object")
    if object_count == 0:
        raise DiscoveryError("targeted manifest discovery found no candidate objects")
    return records


def _list(
    *,
    bucket: str,
    prefix: str,
    delimiter: str | None,
    max_keys: int = 1000,
) -> S3ListResult:
    return list_objects_v2(
        bucket=bucket,
        prefix=prefix,
        delimiter=delimiter,
        max_keys=max_keys,
    )


def _listing_record(result: S3ListResult, label: str) -> dict[str, Any]:
    return {
        "record_type": "listing",
        "label": label,
        "bucket": result.bucket,
        "prefix": result.prefix,
        "delimiter": result.delimiter,
        "common_prefixes": result.common_prefixes,
        "object_count": len(result.objects),
        "is_truncated": result.is_truncated,
        "next_token_present": result.next_token is not None,
        "listed_at_utc": datetime.now(UTC).isoformat(),
    }


def _manifest_object_records(
    *,
    bucket: str,
    base_url: str,
    defaults: dict[str, Any],
    prefix: str,
    label: str,
    max_objects_per_prefix: int,
    expected_filenames: set[str] | None,
) -> list[dict[str, Any]]:
    listing = _list(
        bucket=bucket,
        prefix=prefix,
        delimiter=None,
        max_keys=max_objects_per_prefix,
    )
    listing_record = _listing_record(listing, label)
    if listing.is_truncated:
        raise DiscoveryError(
            f"targeted manifest prefix {prefix!r} was truncated; "
            "increase max_objects_per_prefix before building a manifest"
        )
    if not listing.objects:
        raise DiscoveryError(f"targeted manifest prefix {prefix!r} contains no objects")
    if expected_filenames is not None:
        found = {obj["key"].rsplit("/", 1)[-1] for obj in listing.objects}
        missing = sorted(expected_filenames - found)
        if missing:
            raise DiscoveryError(
                f"targeted metadata prefix {prefix!r} is missing approved files: "
                + ", ".join(missing)
            )
    return [
        listing_record,
        *_object_records(
            listing,
            defaults=defaults,
            base_url=base_url,
            listing_ref=prefix,
        ),
    ]


def _object_records(
    result: S3ListResult,
    *,
    defaults: dict[str, Any],
    base_url: str,
    listing_ref: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for obj in result.objects:
        row = dict(obj)
        row["bucket"] = result.bucket
        row["public_url"] = public_url(base_url, row["key"])
        row["source_listing_ref"] = listing_ref
        classification = classify_object(row, defaults)
        row.update(
            {
                "classification": classification.classification,
                "classification_reason": classification.reason,
                "classifier_version": classification.classifier_version,
                "parsed": classification.parsed,
                "format": classification.format,
            }
        )
        rows.append(row)
    return rows


def _require_prefix(result: S3ListResult, prefix: str) -> None:
    if prefix not in result.common_prefixes:
        raise DiscoveryError(
            f"expected public S3 prefix {prefix!r} was not found under "
            f"{result.prefix!r}; NRDS access pattern may have changed"
        )


def _latest_prefixes(prefixes: list[str], limit: int) -> list[str]:
    return sorted(prefixes, reverse=True)[:limit]


def _select_manifest_date_prefix(
    *,
    hydro_listing: S3ListResult,
    hydro_prefix: str,
    run_date: str | None,
) -> str:
    if run_date is not None:
        selected = f"{hydro_prefix}ngen.{run_date}/"
        _require_prefix(hydro_listing, selected)
        return selected
    latest = _latest_prefixes(hydro_listing.common_prefixes, 1)
    if not latest:
        raise DiscoveryError(f"no date prefixes found under {hydro_prefix}")
    return latest[0]
