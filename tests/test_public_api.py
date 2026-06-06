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


def test_public_api_has_no_download_execution_routes(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from apps.api.main import app

    _write_public_fixture(tmp_path)
    monkeypatch.setenv("NEXTGEN_HYDRA_ROOT", str(tmp_path))
    client = TestClient(app)

    assert client.get("/api/sites").status_code == 200
    assert client.get("/api/datasets").status_code == 200
    assert client.post("/api/exports", json={"site_ids": ["s"], "format": "csv"}).status_code == 409
    route_paths = {route.path for route in app.routes}
    assert not any(
        token in path
        for path in route_paths
        for token in ("download", "discover", "execute", "resource")
    )


def _write_public_fixture(root):
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
        json.dumps({"status": "fail", "object_count": 0, "errors": ["fixture"]}),
        encoding="utf-8",
    )
