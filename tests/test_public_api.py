from __future__ import annotations

import json

import pytest
import yaml


def test_public_artifact_readers_reject_unavailable_exports(tmp_path):
    from apps.api.artifacts import load_sites, preview_export

    _write_public_fixture(tmp_path)

    sites = load_sites(tmp_path)
    preview = preview_export(
        {
            "site_ids": [sites[0]["site_id"]],
            "streams": ["cfe_nom"],
            "format": "csv",
        },
        tmp_path,
    )

    assert sites[0]["crosswalk_status"] == "resolved"
    assert preview["available"] is False
    assert "no approved tidy catalog" in preview["reasons"][0]


def test_public_datasets_surface_tidy_gates(tmp_path):
    from apps.api.artifacts import list_datasets

    _write_public_fixture(tmp_path)
    datasets = list_datasets(tmp_path)

    assert datasets[0]["crosswalk_status"] == "resolved"
    assert datasets[0]["units_status"] == "unresolved"
    assert datasets[0]["tidy_available"] is False


def test_public_export_preprocessing_and_metadata(tmp_path):
    pytest.importorskip("pandas")
    from apps.api.artifacts import create_export, export_options, preview_export

    _write_public_fixture(tmp_path, documented_units=True, with_tidy=True)

    options = export_options(tmp_path)
    assert "streamflow" in options["columns"]
    payload = {
        "site_ids": ["s"],
        "streams": ["cfe_nom"],
        "format": "csv",
        "columns": ["site_id", "time_utc", "streamflow"],
        "preprocessing": {
            "missing_streamflow": "drop",
            "aggregation": "daily_mean",
        },
    }
    preview = preview_export(payload, tmp_path)
    export = create_export(payload, tmp_path)

    assert preview["available"] is True
    assert preview["row_count"] == 2
    assert export["row_count"] == 1
    assert export["metadata_path"].endswith(".metadata.json")


def test_public_status_qc_units_and_options_routes(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from apps.api.main import app

    _write_public_fixture(tmp_path, documented_units=True, with_tidy=True)
    monkeypatch.setenv("NEXTGEN_HYDRA_ROOT", str(tmp_path))
    client = TestClient(app)

    assert client.get("/api/status").status_code == 200
    assert client.get("/api/qc").status_code == 200
    assert client.get("/api/units").json()["status"] == "documented"
    assert client.get("/api/export-options").status_code == 200
    assert client.get("/api/catalog").status_code == 200


def test_site_directory_search_and_acquisition_request_are_non_executing(tmp_path):
    from apps.api.artifacts import create_acquisition_request, site_directory

    _write_public_fixture(tmp_path, documented_units=True)

    directory = site_directory(tmp_path, query="00000000", source="usgs")
    request = create_acquisition_request(
        {
            "site_ids": ["s"],
            "comids": [1],
            "usgs_gage_ids": ["00000000"],
            "sources": ["nextgen", "usgs"],
            "streams": ["cfe_nom"],
            "formats": ["csv"],
            "start_time_utc": "2026-05-24T00:00:00Z",
            "end_time_utc": "2026-05-25T00:00:00Z",
        },
        tmp_path,
    )

    assert directory["count"] == 1
    assert directory["sites"][0]["availability"]["usgs"] is True
    assert request["status"] == "queued_for_admin_review"
    assert request["object_body_downloads"] is False
    assert request["public_execution"] is False
    assert (tmp_path / "data/requests/acquisition_requests.jsonl").is_file()


def test_acquisition_request_rejects_unsupported_sources(tmp_path):
    from apps.api.artifacts import ArtifactError, create_acquisition_request

    _write_public_fixture(tmp_path)

    with pytest.raises(ArtifactError, match="unsupported acquisition sources"):
        create_acquisition_request(
            {"comids": [1], "sources": ["nextgen", "forbidden"]},
            tmp_path,
        )


def test_public_api_has_no_download_execution_routes(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from apps.api.main import app

    _write_public_fixture(tmp_path)
    monkeypatch.setenv("NEXTGEN_HYDRA_ROOT", str(tmp_path))
    client = TestClient(app)

    assert client.get("/api/sites").status_code == 200
    assert client.get("/api/site-directory").status_code == 200
    response = client.post(
        "/api/acquisition-requests",
        json={"comids": [1], "sources": ["nextgen"]},
    )
    assert response.status_code == 200
    assert response.json()["object_body_downloads"] is False
    assert client.get("/api/datasets").status_code == 200
    assert client.post("/api/exports", json={"site_ids": ["s"], "format": "csv"}).status_code == 409
    route_paths = {route.path for route in app.routes}
    assert not any(
        token in path
        for path in route_paths
        for token in ("download", "discover", "execute", "resource")
    )


def _write_public_fixture(root, *, documented_units=False, with_tidy=False):
    (root / "configs").mkdir(parents=True)
    (root / "manifests").mkdir()
    (root / "reports").mkdir()
    (root / "configs/sites.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "sites": [
                    {
                        "site_id": "s",
                        "name": "Fixture Site",
                        "usgs_gage_id": "00000000",
                        "hydrofabric_feature_id": 1,
                        "discovered_vpu_id": "05",
                        "mapping_status": "verified",
                        "mapping_evidence": {},
                        "notes": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "configs/site_crosswalk.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "status": "resolved",
                "sites": [
                    {
                        "site_id": "s",
                        "troute_feature_id": 10,
                        "status": "resolved",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = {
        "site_id": "s",
        "product_type": "troute_streamflow_output",
        "stream": "cfe_nom",
        "run_date": "20260524",
        "run_type": "short_range",
        "cycle": "00",
        "vpu_id": "05",
        "object_key": "outputs/example.parquet",
    }
    (root / "manifests/manifest.jsonl").write_text(
        json.dumps(manifest) + "\n",
        encoding="utf-8",
    )
    (root / "reports/schema_inspection.json").write_text(
        json.dumps({"status": "pass" if documented_units else "fail", "object_count": 1, "errors": []}),
        encoding="utf-8",
    )
    (root / "configs/streamflow_units.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "status": "documented" if documented_units else "unresolved",
                "variable": "flow",
                "units": "m3 s-1" if documented_units else None,
                "evidence": [{"source": "fixture", "citation": "fixture"}]
                if documented_units
                else [],
            }
        ),
        encoding="utf-8",
    )
    if with_tidy:
        (root / "data/tidy").mkdir(parents=True)
        tidy_path = root / "data/tidy/s_cfe_nom.csv"
        pytest.importorskip("pandas")
        import pandas as pd

        pd.DataFrame(
            [
                {
                    "site_id": "s",
                    "usgs_gage_id": "00000000",
                    "hydrofabric_feature_id": 1,
                    "troute_feature_id": 10,
                    "vpu_id": "05",
                    "stream": "cfe_nom",
                    "run_date": "20260524",
                    "run_type": "short_range",
                    "cycle": "00",
                    "time_utc": "2026-05-24T01:00:00Z",
                    "streamflow": 1.0,
                    "streamflow_units": "m3 s-1",
                },
                {
                    "site_id": "s",
                    "usgs_gage_id": "00000000",
                    "hydrofabric_feature_id": 1,
                    "troute_feature_id": 10,
                    "vpu_id": "05",
                    "stream": "cfe_nom",
                    "run_date": "20260524",
                    "run_type": "short_range",
                    "cycle": "00",
                    "time_utc": "2026-05-24T02:00:00Z",
                    "streamflow": None,
                    "streamflow_units": "m3 s-1",
                },
            ]
        ).to_csv(tidy_path, index=False)
        catalog = {
            "site_id": "s",
            "usgs_gage_id": "00000000",
            "hydrofabric_feature_id": 1,
            "troute_feature_id": 10,
            "vpu_id": "05",
            "product_type": "troute_streamflow_output",
            "stream": "cfe_nom",
            "run_date": "20260524",
            "run_type": "short_range",
            "cycle": "00",
            "tidy_path": str(tidy_path),
            "row_count": 2,
            "start_time_utc": "2026-05-24T01:00:00Z",
            "end_time_utc": "2026-05-24T02:00:00Z",
            "flow_units": "m3 s-1",
            "missing_count": 1,
            "duplicate_timestamp_count": 0,
            "coverage_status": "pass",
            "qc_status": "review",
        }
        (root / "data/tidy/catalog.jsonl").write_text(
            json.dumps(catalog) + "\n",
            encoding="utf-8",
        )
        (root / "reports/qc_report.json").write_text(
            json.dumps(
                {
                    "approval_id": "FIXTURE_APPROVAL",
                    "per_site": {
                        "s": {
                            "row_count": 2,
                            "missing_streamflow_count": 1,
                            "duplicate_timestamp_count": 0,
                        }
                    },
                    "tidy_catalog": {"row_count": 2},
                    "inventory": {"record_count": 1},
                }
            ),
            encoding="utf-8",
        )
