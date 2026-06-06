from __future__ import annotations

from nextgen_hydra.manifest import build_manifest_records
from nextgen_hydra.schema_inspection import build_schema_inspection_report
from tests.test_manifest import mapped_site


def test_schema_inspection_passes_when_target_feature_is_present(
    defaults, approved_object, tmp_path, monkeypatch
):
    site = mapped_site()
    manifest = build_manifest_records([approved_object], [site], defaults)
    raw_path = tmp_path / "raw" / approved_object["key"]
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("fixture", encoding="utf-8")

    def fake_inspect(path, group):
        return {
            "object_key": group["object_key"],
            "format": group["format"],
            "local_path": str(path),
            "status": "pass",
            "errors": [],
            "columns": ["feature_id", "time", "streamflow"],
            "variables": {},
            "dtypes": {
                "feature_id": "int64",
                "time": "datetime64[ns]",
                "streamflow": "float64",
            },
            "row_count": 1,
            "candidate_feature_columns": ["feature_id"],
            "candidate_time_columns": ["time"],
            "candidate_flow_columns": ["streamflow"],
            "selected_feature_column": "feature_id",
            "selected_time_column": "time",
            "selected_flow_column": "streamflow",
            "target_feature_coverage": {
                "present_feature_ids": [site.hydrofabric_feature_id],
                "absent_feature_ids": [],
                "feature_row_counts": {str(site.hydrofabric_feature_id): 1},
            },
            "time_coverage": {
                "start_time_utc": "2026-05-22T01:00:00+00:00",
                "end_time_utc": "2026-05-22T01:00:00+00:00",
            },
            "duplicate_timestamp_count": 0,
            "null_counts": {"streamflow": 0},
            "units": {},
            "by_site": {
                site.site_id: {
                    "site_id": site.site_id,
                    "hydrofabric_feature_id": site.hydrofabric_feature_id,
                    "status": "pass",
                    "row_count": 1,
                    "time_coverage": {
                        "start_time_utc": "2026-05-22T01:00:00+00:00",
                        "end_time_utc": "2026-05-22T01:00:00+00:00",
                    },
                    "duplicate_timestamp_count": 0,
                }
            },
        }

    monkeypatch.setattr("nextgen_hydra.schema_inspection._inspect_parquet", fake_inspect)

    report = build_schema_inspection_report(
        manifest_records=manifest,
        defaults=defaults,
        sites=[site],
        raw_dir=tmp_path / "raw",
    )

    assert report["status"] == "pass"
    assert report["by_site"][site.site_id]["status"] == "pass"


def test_schema_inspection_fails_when_target_feature_is_absent(
    defaults, approved_object, tmp_path, monkeypatch
):
    site = mapped_site()
    manifest = build_manifest_records([approved_object], [site], defaults)
    raw_path = tmp_path / "raw" / approved_object["key"]
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("fixture", encoding="utf-8")

    def fake_inspect(path, group):
        return {
            "object_key": group["object_key"],
            "format": group["format"],
            "local_path": str(path),
            "status": "fail",
            "errors": [
                f"{group['object_key']}: target feature IDs absent: "
                f"[{site.hydrofabric_feature_id}]"
            ],
            "columns": ["feature_id", "time", "streamflow"],
            "variables": {},
            "dtypes": {},
            "row_count": 1,
            "candidate_feature_columns": ["feature_id"],
            "candidate_time_columns": ["time"],
            "candidate_flow_columns": ["streamflow"],
            "selected_feature_column": "feature_id",
            "selected_time_column": "time",
            "selected_flow_column": "streamflow",
            "target_feature_coverage": {
                "present_feature_ids": [],
                "absent_feature_ids": [site.hydrofabric_feature_id],
                "feature_row_counts": {str(site.hydrofabric_feature_id): 0},
            },
            "time_coverage": {},
            "duplicate_timestamp_count": 0,
            "null_counts": {},
            "units": {},
            "by_site": {
                site.site_id: {
                    "site_id": site.site_id,
                    "hydrofabric_feature_id": site.hydrofabric_feature_id,
                    "status": "fail",
                    "row_count": 0,
                    "time_coverage": {},
                    "duplicate_timestamp_count": 0,
                }
            },
        }

    monkeypatch.setattr("nextgen_hydra.schema_inspection._inspect_parquet", fake_inspect)

    report = build_schema_inspection_report(
        manifest_records=manifest,
        defaults=defaults,
        sites=[site],
        raw_dir=tmp_path / "raw",
    )

    assert report["status"] == "fail"
    assert "target feature IDs absent" in "\n".join(report["errors"])


def test_schema_inspection_uses_resolved_troute_feature_ids(
    defaults, approved_object, tmp_path, monkeypatch
):
    site = mapped_site()
    troute_feature_id = 123456
    manifest = build_manifest_records([approved_object], [site], defaults)
    raw_path = tmp_path / "raw" / approved_object["key"]
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("fixture", encoding="utf-8")

    def fake_inspect(path, group):
        assert group["sites"][0]["hydrofabric_feature_id"] == site.hydrofabric_feature_id
        assert group["sites"][0]["target_feature_id"] == troute_feature_id
        return {
            "object_key": group["object_key"],
            "format": group["format"],
            "local_path": str(path),
            "status": "pass",
            "errors": [],
            "columns": ["feature_id", "time", "flow"],
            "variables": {},
            "dtypes": {},
            "row_count": 1,
            "candidate_feature_columns": ["feature_id"],
            "candidate_time_columns": ["time"],
            "candidate_flow_columns": ["flow"],
            "selected_feature_column": "feature_id",
            "selected_time_column": "time",
            "selected_flow_column": "flow",
            "target_feature_coverage": {
                "present_feature_ids": [troute_feature_id],
                "absent_feature_ids": [],
                "feature_row_counts": {str(troute_feature_id): 1},
            },
            "time_coverage": {},
            "duplicate_timestamp_count": 0,
            "null_counts": {},
            "units": {},
            "by_site": {
                site.site_id: {
                    "site_id": site.site_id,
                    "hydrofabric_feature_id": site.hydrofabric_feature_id,
                    "troute_feature_id": troute_feature_id,
                    "target_feature_id": troute_feature_id,
                    "crosswalk_status": "resolved",
                    "status": "pass",
                    "row_count": 1,
                    "time_coverage": {},
                    "duplicate_timestamp_count": 0,
                }
            },
        }

    monkeypatch.setattr("nextgen_hydra.schema_inspection._inspect_parquet", fake_inspect)

    report = build_schema_inspection_report(
        manifest_records=manifest,
        defaults=defaults,
        sites=[site],
        raw_dir=tmp_path / "raw",
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
    )

    assert report["status"] == "pass"
    assert report["by_site"][site.site_id]["target_feature_id"] == troute_feature_id


def test_schema_inspection_fails_when_crosswalk_is_unresolved(
    defaults, approved_object, tmp_path, monkeypatch
):
    site = mapped_site()
    manifest = build_manifest_records([approved_object], [site], defaults)
    raw_path = tmp_path / "raw" / approved_object["key"]
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("fixture", encoding="utf-8")

    monkeypatch.setattr(
        "nextgen_hydra.schema_inspection._inspect_parquet",
        lambda path, group: {
            "object_key": group["object_key"],
            "format": group["format"],
            "local_path": str(path),
            "status": "pass",
            "errors": [],
            "columns": ["feature_id", "time", "flow"],
            "variables": {},
            "dtypes": {},
            "row_count": 1,
            "candidate_feature_columns": ["feature_id"],
            "candidate_time_columns": ["time"],
            "candidate_flow_columns": ["flow"],
            "selected_feature_column": "feature_id",
            "selected_time_column": "time",
            "selected_flow_column": "flow",
            "target_feature_coverage": {},
            "time_coverage": {},
            "duplicate_timestamp_count": 0,
            "null_counts": {},
            "units": {},
            "by_site": {
                site.site_id: {
                    "site_id": site.site_id,
                    "hydrofabric_feature_id": site.hydrofabric_feature_id,
                    "status": "pass",
                    "row_count": 1,
                    "time_coverage": {},
                    "duplicate_timestamp_count": 0,
                }
            },
        },
    )

    report = build_schema_inspection_report(
        manifest_records=manifest,
        defaults=defaults,
        sites=[site],
        raw_dir=tmp_path / "raw",
        site_crosswalk={
            "version": 1,
            "status": "unresolved",
            "sites": [
                {
                    "site_id": site.site_id,
                    "troute_feature_id": None,
                    "status": "unresolved",
                }
            ],
        },
    )

    assert report["status"] == "fail"
    assert "troute_feature_id is not resolved" in "\n".join(report["errors"])
