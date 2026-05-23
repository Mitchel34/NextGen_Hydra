from __future__ import annotations

from nextgen_hydra.qc import build_qc_report
from nextgen_hydra.tidy import build_catalog_record, normalise_rows


def test_normalise_rows_requires_explicit_schema(defaults):
    manifest = {
        "object_key": "source.parquet",
        "vpu_id": "05",
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
    assert tidy[0]["source_manifest_ref"] == "source.parquet"


def test_qc_report_counts_manifest_inventory_and_catalog():
    manifest = [{"classification": "approved", "approved_for_download": True}]
    inventory = [{"manifest_match": True, "size_matches_manifest": True}]
    catalog = [
        build_catalog_record(
            record={
                "site_id": "s",
                "usgs_gage_id": "g",
                "hydrofabric_feature_id": 1,
                "vpu_id": "05",
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
    )

    assert report["manifest"]["classification_counts"] == {"approved": 1}
    assert report["inventory"]["manifest_match_count"] == 1
    assert report["tidy_catalog"]["row_count"] == 1
