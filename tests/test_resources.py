from __future__ import annotations

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
    monkeypatch.setattr(
        "nextgen_hydra.resources.head_object",
        lambda **_kwargs: {
            "size_bytes": 1234,
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
    valid = {
        "resource_manifest_version": 1,
        "created_at_utc": "2026-05-24T00:00:00Z",
        "vpu_id": "05",
        "site_ids": ["south_fork_new_river_near_jefferson_nc"],
        "resource_type": RESOURCE_PRODUCT_TYPE,
        "object_key": resource_key(defaults, "05"),
        "public_url": "https://example.test/resource.gpkg",
        "format": "gpkg",
        "size_bytes": 1234,
        "etag": "etag",
        "last_modified": "2026-05-24T00:00:00Z",
        "classification": "approved",
        "classification_reason": "fixture",
        "approved_for_download": True,
    }

    for edited in (
        dict(valid, object_key="outputs/cfe_nom/v2.2_hydrofabric/example.parquet"),
        dict(valid, object_key="forcings/example.nc"),
        dict(valid, format="parquet"),
    ):
        with pytest.raises(ResourceError, match="resource manifest validation failed"):
            validate_resource_manifest_records([edited], defaults)


def test_resource_download_is_dry_run_until_approval(defaults, tmp_path):
    record = {
        "resource_manifest_version": 1,
        "created_at_utc": "2026-05-24T00:00:00Z",
        "vpu_id": "05",
        "site_ids": ["south_fork_new_river_near_jefferson_nc"],
        "resource_type": RESOURCE_PRODUCT_TYPE,
        "object_key": resource_key(defaults, "05"),
        "public_url": "https://example.test/resource.gpkg",
        "format": "gpkg",
        "size_bytes": 1234,
        "etag": "etag",
        "last_modified": "2026-05-24T00:00:00Z",
        "classification": "approved",
        "classification_reason": "fixture",
        "approved_for_download": True,
    }
    manifest_path = tmp_path / "resource_manifest.jsonl"
    write_jsonl(manifest_path, [record])

    plan = download_resource_manifest_file(
        manifest_path=manifest_path,
        resource_dir=tmp_path / "resources",
        defaults=defaults,
        sites=[mapped_site("05")],
        plan_output=tmp_path / "resource_download_plan.jsonl",
    )

    assert plan[0]["action"] == "download"
    assert plan[0]["local_path"] == str(
        resource_local_path(tmp_path / "resources", record["object_key"])
    )
    assert not resource_local_path(tmp_path / "resources", record["object_key"]).exists()

    with pytest.raises(DownloadSafetyError, match="approval_id"):
        download_resource_manifest_file(
            manifest_path=manifest_path,
            resource_dir=tmp_path / "resources",
            defaults=defaults,
            sites=[mapped_site("05")],
            execute=True,
        )
