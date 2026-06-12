from __future__ import annotations

import json
import sqlite3


def test_build_paired_site_directory_from_geopackage(tmp_path):
    from nextgen_hydra.site_directory import build_paired_site_directory

    gpkg = tmp_path / "resources/v2.2_hydrofabric/geopackages/VPU_05/nextgen_VPU_05.gpkg"
    gpkg.parent.mkdir(parents=True)
    with sqlite3.connect(gpkg) as connection:
        connection.execute(
            """
            CREATE TABLE "flowpath-attributes" (
                gage TEXT,
                gage_nex_id TEXT,
                id TEXT,
                link TEXT,
                toid TEXT,
                vpuid TEXT,
                Length_m REAL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE network (
                id TEXT,
                hf_id REAL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO "flowpath-attributes"
            VALUES ('03161000', 'nex-1', 'wb-797343', 'wb-797343', 'nex-1', '05', 10.0)
            """
        )
        connection.execute("INSERT INTO network VALUES ('wb-797343', 6892192)")
        connection.execute("INSERT INTO network VALUES ('wb-797343', 6892194)")

    records, report = build_paired_site_directory(
        resource_dir=tmp_path / "resources",
        output=tmp_path / "data/catalog/site_directory.jsonl",
        report_output=tmp_path / "reports/site_directory_summary.json",
        markdown_output=tmp_path / "reports/site_directory_summary.md",
    )

    rows = [
        json.loads(line)
        for line in (tmp_path / "data/catalog/site_directory.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 1
    assert rows[0]["usgs_gage_id"] == "03161000"
    assert rows[0]["troute_feature_id"] == 797343
    assert rows[0]["comid_candidates"] == [6892192, 6892194]
    assert rows[0]["comid_status"] == "multiple_candidates"
    assert report["record_count"] == 1
    assert report["map_ready_record_count"] == 0
    assert report["source_resource_count"] == 1
    assert report["enriched_usgs"] is False
    assert report["vpu_counts"] == {"05": 1}
    assert report["state_counts"] == {"missing": 1}
    assert report["comid_status_counts"] == {"multiple_candidates": 1}
