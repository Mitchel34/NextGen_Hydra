from __future__ import annotations

from nextgen_hydra.config import Site
from nextgen_hydra.manifest import (
    ManifestError,
    build_manifest_records,
    validate_manifest_records,
)

import pytest


def mapped_site(vpu_id: str = "05") -> Site:
    return Site(
        site_id="south_fork_new_river_near_jefferson_nc",
        name="South Fork New River near Jefferson, NC",
        usgs_gage_id="03161000",
        hydrofabric_feature_id=6892192,
        discovered_vpu_id=vpu_id,
        mapping_status="verified",
        mapping_evidence={
            "ref": "fixture",
            "feature_id_field": "comid",
            "vpu_field": "vpuid",
            "returned_feature_id": 6892192,
            "returned_vpu_id": vpu_id,
            "sources": [{"url": "https://example.test/source"}],
        },
        notes=None,
    )


def test_build_and_validate_manifest(defaults, approved_object):
    records = build_manifest_records([approved_object], [mapped_site()], defaults)

    assert len(records) == 1
    assert records[0]["classification"] == "approved"
    assert records[0]["approved_for_download"] is True
    assert records[0]["vpu_id"] == "05"
    assert validate_manifest_records(records, defaults) == records


def test_manifest_allows_multiple_sites_in_same_vpu(defaults, approved_object):
    first = mapped_site()
    second = Site(
        site_id="new_river_near_galax_va",
        name="New River near Galax, VA",
        usgs_gage_id="03164000",
        hydrofabric_feature_id=6887572,
        discovered_vpu_id="05",
        mapping_status="verified",
        mapping_evidence={
            "ref": "fixture",
            "feature_id_field": "comid",
            "vpu_field": "vpuid",
            "returned_feature_id": 6887572,
            "returned_vpu_id": "05",
            "sources": [{"url": "https://example.test/source"}],
        },
        notes=None,
    )

    records = build_manifest_records([approved_object], [first, second], defaults)

    assert {record["site_id"] for record in records} == {
        "south_fork_new_river_near_jefferson_nc",
        "new_river_near_galax_va",
    }


def test_manifest_requires_clean_vpu_mapping(defaults, approved_object):
    site = mapped_site()
    unmapped = Site(
        site_id=site.site_id,
        name=site.name,
        usgs_gage_id=site.usgs_gage_id,
        hydrofabric_feature_id=site.hydrofabric_feature_id,
        discovered_vpu_id=None,
        mapping_status="unmapped",
        mapping_evidence=None,
        notes=None,
    )

    with pytest.raises(ManifestError, match="site VPU mapping validation failed"):
        build_manifest_records([approved_object], [unmapped], defaults)


def test_manifest_validation_rejects_unsafe_rows(defaults, approved_object):
    records = build_manifest_records([approved_object], [mapped_site()], defaults)

    ambiguous = dict(records[0], classification="ambiguous")
    with pytest.raises(ManifestError, match="classification is not approved"):
        validate_manifest_records([ambiguous], defaults)

    not_approved = dict(records[0], approved_for_download=False)
    with pytest.raises(ManifestError, match="approved_for_download"):
        validate_manifest_records([not_approved], defaults)

    missing = dict(records[0])
    missing.pop("etag")
    with pytest.raises(ManifestError, match="missing required fields"):
        validate_manifest_records([missing], defaults)
