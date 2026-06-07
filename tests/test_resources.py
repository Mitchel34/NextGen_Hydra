from __future__ import annotations

from copy import deepcopy

import pytest

from nextgen_hydra.download import DownloadSafetyError
from nextgen_hydra.manifest import write_jsonl
from nextgen_hydra.resources import (
    RESOURCE_PRODUCT_TYPE,
    ResourceError,
    build_resource_manifest_records,
    download_resource_manifest_file,
    resource_local_path,
    resource_key,
    validate_resource_manifest_records,
)
from tests.test_manifest import mapped_site


def test_resource_manifest_allows_only_configured_vpu_geopackages(defaults, monkeypatch):
    sizes = {"05": 265678848, "06": 74469376}

    monkeypatch.setattr(
        "nextgen_hydra.resources.head_object",
        lambda key, **_kwargs: {
            "size_bytes": sizes["05" if "VPU_05" in key else "06"],
            "etag": "resource-etag",
            "last_modified": "2026-05-24T00:00:00Z",
        },
    )

    records = build_resource_manifest_records(
        defaults=defaults,
        sites=[mapped_site("05"), mapped_site("06")],
    )

    assert len(records) == 2
    assert {record["resource_type"] for record in records} == {RESOURCE_PRODUCT_TYPE}
    assert {record["format"] for record in records} == {"gpkg"}
    assert {record["object_key"] for record in records} == {
        resource_key(defaults, "05"),
        resource_key(defaults, "06"),
    }


def test_resource_manifest_rejects_outputs_forcings_and_non_gpkg(defaults):
    records = _resource_records(defaults)

    for edited in (
        [dict(records[0], object_key="outputs/cfe_nom/v2.2_hydrofabric/example.parquet"), records[1]],
        [dict(records[0], object_key="forcings/example.nc"), records[1]],
        [dict(records[0], format="parquet"), records[1]],
    ):
        with pytest.raises(ResourceError, match="resource manifest validation failed"):
            validate_resource_manifest_records(edited, defaults)


def test_resource_download_is_dry_run_until_approval(defaults, tmp_path):
    records = _resource_records(defaults)
    manifest_path = tmp_path / "resource_manifest.jsonl"
    write_jsonl(manifest_path, records)

    plan = download_resource_manifest_file(
        manifest_path=manifest_path,
        resource_dir=tmp_path / "resources",
        defaults=defaults,
        sites=[mapped_site("05"), mapped_site("06")],
        plan_output=tmp_path / "resource_download_plan.jsonl",
    )

    assert [row["action"] for row in plan] == ["download", "download"]
    assert plan[0]["local_path"] == str(
        resource_local_path(tmp_path / "resources", records[0]["object_key"])
    )
    assert not resource_local_path(tmp_path / "resources", records[0]["object_key"]).exists()

    with pytest.raises(DownloadSafetyError, match="approval_id"):
        download_resource_manifest_file(
            manifest_path=manifest_path,
            resource_dir=tmp_path / "resources",
            defaults=defaults,
            sites=[mapped_site("05"), mapped_site("06")],
            execute=True,
        )


def test_resource_manifest_rejects_unexpected_count_and_bytes(defaults):
    records = _resource_records(defaults)

    with pytest.raises(ResourceError, match="object count"):
        validate_resource_manifest_records(records[:1], defaults)

    edited = [dict(records[0], size_bytes=records[0]["size_bytes"] + 1), records[1]]
    with pytest.raises(ResourceError, match="total bytes"):
        validate_resource_manifest_records(edited, defaults)


def test_resource_thresholds_require_approval(defaults, tmp_path):
    restricted = deepcopy(defaults)
    restricted["resource_download"]["resource_max_object_mb"] = 1
    restricted["resource_download"]["resource_max_total_mb"] = 1
    records = _resource_records(restricted)
    manifest_path = tmp_path / "resource_manifest.jsonl"
    write_jsonl(manifest_path, records)

    with pytest.raises(DownloadSafetyError, match="approval is required"):
        download_resource_manifest_file(
            manifest_path=manifest_path,
            resource_dir=tmp_path / "resources",
            defaults=restricted,
            sites=[mapped_site("05"), mapped_site("06")],
        )

    plan = download_resource_manifest_file(
        manifest_path=manifest_path,
        resource_dir=tmp_path / "resources",
        defaults=restricted,
        sites=[mapped_site("05"), mapped_site("06")],
        approval_id="RESOURCE_APPROVAL",
    )
    assert len(plan) == 2


def _resource_records(defaults):
    rows = []
    for vpu_id, size_bytes in (("05", 265678848), ("06", 74469376)):
        rows.append(
            {
                "resource_manifest_version": 1,
                "created_at_utc": "2026-05-24T00:00:00Z",
                "vpu_id": vpu_id,
                "site_ids": ["site"],
                "resource_type": RESOURCE_PRODUCT_TYPE,
                "object_key": resource_key(defaults, vpu_id),
                "public_url": "https://example.test/resource.gpkg",
                "format": "gpkg",
                "size_bytes": size_bytes,
                "etag": "etag",
                "last_modified": "2026-05-24T00:00:00Z",
                "classification": "approved",
                "classification_reason": "fixture",
                "approved_for_download": True,
            }
        )
    return rows
