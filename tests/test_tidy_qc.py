from __future__ import annotations

import pytest

from nextgen_hydra.qc import build_qc_report
from nextgen_hydra.tidy import TidyError, build_catalog_record, normalise_rows, tidy_manifest_records
from nextgen_hydra.units import UnitsError, require_documented_flow_units
from nextgen_hydra.manifest import build_manifest_records
from tests.test_manifest import mapped_site


def test_normalise_rows_requires_explicit_schema(defaults):
    manifest = {
        "object_key": "source.parquet",
        "vpu_id": "05",
        "product_type": "troute_streamflow_output",
        "stream": "cfe_nom",
        "run_date": "20260522",
        "run_type": "short_range",
        "cycle": "00",
        "format": "parquet",
    }
    site = {
        "site_id": "south_fork_new_river_near_jefferson_nc",
        "usgs_gage_id": "03161000",
        "hydrofabric_feature_id": 6892192,
    }
    rows = [
        {"feature_id": 6892192, "time": "2026-05-22T01:00:00Z", "flow": 1.2},
        {"feature_id": 1, "time": "2026-05-22T01:00:00Z", "flow": 5.0},
    ]

    tidy = normalise_rows(
        rows,
        site=site,
        manifest_record=manifest,
        feature_id_column="feature_id",
        time_column="time",
        flow_column="flow",
        flow_units="m3 s-1",
    )

    assert len(tidy) == 1
    assert tidy[0]["streamflow"] == 1.2
    assert tidy[0]["troute_feature_id"] == 6892192
    assert tidy[0]["source_manifest_ref"] == "source.parquet"


def test_qc_report_counts_manifest_inventory_and_catalog():
    manifest = [
        {
            "site_id": "s",
            "usgs_gage_id": "g",
            "hydrofabric_feature_id": 1,
            "vpu_id": "05",
            "product_type": "troute_streamflow_output",
            "stream": "cfe_nom",
            "classification": "approved",
            "approved_for_download": True,
        }
    ]
    inventory = [{"manifest_match": True, "size_matches_manifest": True}]
    catalog = [
        build_catalog_record(
            record={
                "site_id": "s",
                "usgs_gage_id": "g",
                "hydrofabric_feature_id": 1,
                "vpu_id": "05",
                "product_type": "troute_streamflow_output",
                "stream": "cfe_nom",
                "run_date": "20260522",
                "run_type": "short_range",
                "cycle": "00",
                "format": "parquet",
                "object_key": "source.parquet",
            },
            tidy_path=__import__("pathlib").Path("tidy.parquet"),
            tidy_rows=[{"time_utc": "2026-05-22T01:00:00Z", "streamflow": 1.0}],
            flow_variable="flow",
            flow_units="m3 s-1",
        )
    ]

    report = build_qc_report(
        manifest_records=manifest,
        inventory_records=inventory,
        catalog_records=catalog,
        schema_inspection={
            "status": "pass",
            "object_count": 1,
            "errors": [],
            "by_site": {
                "s": {
                    "status": "pass",
                    "row_count": 1,
                }
            },
        },
        download_summary={"approval_id": "M4_TEST_APPROVAL"},
    )

    assert report["manifest"]["classification_counts"] == {"approved": 1}
    assert report["inventory"]["manifest_match_count"] == 1
    assert report["tidy_catalog"]["row_count"] == 1
    assert report["approval_id"] == "M4_TEST_APPROVAL"
    assert report["per_site"]["s"]["row_count"] == 1


def test_tidy_skips_metadata_rows(defaults, approved_object, approved_metadata_object, tmp_path, monkeypatch):
    site = mapped_site()
    manifest = build_manifest_records(
        [approved_object, approved_metadata_object],
        [site],
        defaults,
    )
    raw_path = tmp_path / "raw" / approved_object["key"]
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("fixture", encoding="utf-8")
    read_paths = []

    def fake_read_source_rows(path, _source_format):
        read_paths.append(path)
        return [
            {
                "feature_id": site.hydrofabric_feature_id,
                "time": "2026-05-22T01:00:00Z",
                "streamflow": 1.0,
            }
        ]

    monkeypatch.setattr("nextgen_hydra.tidy._read_source_rows", fake_read_source_rows)

    catalog = tidy_manifest_records(
        manifest_records=manifest,
        defaults=defaults,
        raw_dir=tmp_path / "raw",
        output_dir=tmp_path / "tidy",
        feature_id_column="feature_id",
        time_column="time",
        flow_column="streamflow",
        flow_units="m3 s-1",
        output_format="csv",
        sites=[site],
    )

    assert len(catalog) == 1
    assert read_paths == [raw_path]
    assert catalog[0]["product_type"] == "troute_streamflow_output"


def test_tidy_uses_resolved_troute_feature_id(
    defaults, approved_object, tmp_path, monkeypatch
):
    site = mapped_site()
    troute_feature_id = 123456
    manifest = build_manifest_records([approved_object], [site], defaults)
    raw_path = tmp_path / "raw" / approved_object["key"]
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("fixture", encoding="utf-8")

    monkeypatch.setattr(
        "nextgen_hydra.tidy._read_source_rows",
        lambda *_args: [
            {
                "feature_id": troute_feature_id,
                "time": "2026-05-22T01:00:00Z",
                "streamflow": 1.0,
            },
            {
                "feature_id": site.hydrofabric_feature_id,
                "time": "2026-05-22T01:00:00Z",
                "streamflow": 99.0,
            },
        ],
    )

    catalog = tidy_manifest_records(
        manifest_records=manifest,
        defaults=defaults,
        raw_dir=tmp_path / "raw",
        output_dir=tmp_path / "tidy",
        feature_id_column="feature_id",
        time_column="time",
        flow_column="streamflow",
        flow_units="m3 s-1",
        output_format="csv",
        sites=[site],
        site_crosswalk={
            "version": 1,
            "status": "resolved",
            "sites": [
                {
                    "site_id": site.site_id,
                    "troute_feature_id": troute_feature_id,
                    "status": "resolved",
                }
            ],
        },
        require_crosswalk=True,
    )

    assert catalog[0]["hydrofabric_feature_id"] == site.hydrofabric_feature_id
    assert catalog[0]["troute_feature_id"] == troute_feature_id
    assert catalog[0]["row_count"] == 1


def test_tidy_requires_per_site_feature_coverage(defaults, approved_object, tmp_path, monkeypatch):
    site = mapped_site()
    manifest = build_manifest_records([approved_object], [site], defaults)
    raw_path = tmp_path / "raw" / approved_object["key"]
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("fixture", encoding="utf-8")

    monkeypatch.setattr(
        "nextgen_hydra.tidy._read_source_rows",
        lambda *_args: [
            {
                "feature_id": 999,
                "time": "2026-05-22T01:00:00Z",
                "streamflow": 1.0,
            }
        ],
    )

    with pytest.raises(TidyError, match="coverage failed"):
        tidy_manifest_records(
            manifest_records=manifest,
            defaults=defaults,
            raw_dir=tmp_path / "raw",
            output_dir=tmp_path / "tidy",
            feature_id_column="feature_id",
            time_column="time",
            flow_column="streamflow",
            flow_units="m3 s-1",
            output_format="csv",
            sites=[site],
        )


def test_tidy_refuses_undocumented_units_evidence(defaults, approved_object, tmp_path, monkeypatch):
    site = mapped_site()
    manifest = build_manifest_records([approved_object], [site], defaults)
    raw_path = tmp_path / "raw" / approved_object["key"]
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr(
        "nextgen_hydra.tidy._read_source_rows",
        lambda *_args: [
            {
                "feature_id": site.hydrofabric_feature_id,
                "time": "2026-05-22T01:00:00Z",
                "streamflow": 1.0,
            }
        ],
    )

    with pytest.raises(TidyError, match="documented streamflow units"):
        tidy_manifest_records(
            manifest_records=manifest,
            defaults=defaults,
            raw_dir=tmp_path / "raw",
            output_dir=tmp_path / "tidy",
            feature_id_column="feature_id",
            time_column="time",
            flow_column="streamflow",
            flow_units="m3 s-1",
            units_evidence={
                "version": 1,
                "status": "unresolved",
                "variable": "streamflow",
                "units": None,
                "evidence": [],
            },
            output_format="csv",
            sites=[site],
        )


def test_units_gate_requires_authoritative_evidence():
    with pytest.raises(UnitsError, match="not documented"):
        require_documented_flow_units(
            units_config={
                "version": 1,
                "status": "unresolved",
                "variable": "flow",
                "units": None,
                "evidence": [],
            },
            flow_column="flow",
            requested_units="m3 s-1",
        )

    units = require_documented_flow_units(
        units_config={
            "version": 1,
            "status": "documented",
            "variable": "flow",
            "units": "m3 s-1",
            "evidence": [{"source": "fixture", "citation": "fixture docs"}],
        },
        flow_column="flow",
        requested_units="m3 s-1",
    )
    assert units == "m3 s-1"
