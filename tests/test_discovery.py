from __future__ import annotations

from nextgen_hydra.discovery import run_mapped_site_manifest_discovery
from nextgen_hydra.io.s3 import S3ListResult
from tests.test_manifest import mapped_site


def test_mapped_site_manifest_discovery_targets_configured_vpus(defaults, monkeypatch):
    bucket = defaults["nrds"]["s3_bucket"]
    hydro = defaults["nrds"]["hydrofabric_version"]
    metadata_files = defaults["metadata"]["approved_filenames"]

    def result(prefix, delimiter, common_prefixes=None, objects=None):
        return S3ListResult(
            bucket=bucket,
            prefix=prefix,
            delimiter=delimiter,
            common_prefixes=common_prefixes or [],
            objects=objects or [],
            is_truncated=False,
            next_token=None,
        )

    def fake_list(*, bucket, prefix, delimiter, max_keys=1000):
        if prefix.endswith(f"{hydro}/"):
            return result(prefix, delimiter, [prefix + "ngen.20260523/"])
        if prefix.endswith("ngen.20260523/"):
            return result(prefix, delimiter, [prefix + "short_range/"])
        if prefix.endswith("short_range/"):
            return result(prefix, delimiter, [prefix + "00/"])
        if prefix.endswith("short_range/00/"):
            return result(
                prefix,
                delimiter,
                [prefix + "VPU_05/", prefix + "VPU_06/"],
            )
        if prefix.endswith("ngen-run/outputs/troute/"):
            return result(
                prefix,
                delimiter,
                objects=[
                    {
                        "record_type": "object",
                        "key": prefix + "troute_output_202605230100.parquet",
                        "size_bytes": 1024,
                        "etag": "etag",
                        "last_modified": "2026-05-23T01:00:00.000Z",
                        "source_listing_ref": prefix,
                    }
                ],
            )
        if prefix.endswith("datastream-metadata/"):
            return result(
                prefix,
                delimiter,
                objects=[
                    {
                        "record_type": "object",
                        "key": prefix + filename,
                        "size_bytes": 10,
                        "etag": f"etag-{filename}",
                        "last_modified": "2026-05-23T01:00:00.000Z",
                        "source_listing_ref": prefix,
                    }
                    for filename in metadata_files
                ],
            )
        raise AssertionError(f"unexpected prefix: {prefix}")

    monkeypatch.setattr("nextgen_hydra.discovery._list", fake_list)

    rows = run_mapped_site_manifest_discovery(
        defaults,
        [mapped_site("05"), mapped_site("06")],
        run_type="short_range",
        cycle="00",
    )

    objects = [row for row in rows if row.get("record_type") == "object"]
    assert len(objects) == 2 * 2 * (1 + len(metadata_files))
    assert {
        row["parsed"]["vpu_id"]
        for row in objects
        if row["parsed"]["product_type"] == "troute_streamflow_output"
    } == {"05", "06"}
