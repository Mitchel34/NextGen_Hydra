from __future__ import annotations

from nextgen_hydra.cli import main
from nextgen_hydra.manifest import build_manifest_records, write_jsonl
from tests.test_manifest import mapped_site


def test_validate_config_cli(repo_root, capsys):
    code = main(["--root", str(repo_root), "validate-config"])

    assert code == 0
    output = capsys.readouterr().out
    assert '"status": "ok"' in output
    assert '"mapped_site_count": 4' in output


def test_download_cli_approval_id_implies_execute(
    repo_root, defaults, approved_object, tmp_path, monkeypatch
):
    manifest_path = tmp_path / "manifest.jsonl"
    write_jsonl(
        manifest_path,
        build_manifest_records([approved_object], [mapped_site()], defaults),
    )
    calls = {}

    def fake_download_manifest_file(**kwargs):
        calls.update(kwargs)
        return [{"action": "download", "size_bytes": 3}]

    monkeypatch.setattr(
        "nextgen_hydra.cli.download_manifest_file",
        fake_download_manifest_file,
    )
    monkeypatch.setattr("nextgen_hydra.cli.inventory_raw_files", lambda *_args: [])

    code = main(
        [
            "--root",
            str(repo_root),
            "download",
            "--manifest",
            str(manifest_path),
            "--raw-dir",
            str(tmp_path / "raw"),
            "--approval-id",
            "M4_TEST_APPROVAL",
            "--plan-output",
            str(tmp_path / "download_plan.jsonl"),
            "--provenance",
            str(tmp_path / "download_provenance.jsonl"),
            "--inventory-output",
            str(tmp_path / "inventory.jsonl"),
            "--summary-output",
            str(tmp_path / "download_summary.json"),
            "--summary-markdown",
            str(tmp_path / "download_summary.md"),
        ]
    )

    assert code == 0
    assert calls["execute"] is True
    assert calls["approval_id"] == "M4_TEST_APPROVAL"
    assert (tmp_path / "inventory.jsonl").is_file()
    assert (tmp_path / "download_summary.json").is_file()
    assert (tmp_path / "download_summary.md").is_file()


def test_resource_download_cli_approval_id_implies_execute(
    repo_root, tmp_path, monkeypatch
):
    manifest_path = tmp_path / "resource_manifest.jsonl"
    manifest_path.write_text("", encoding="utf-8")
    calls = {}

    def fake_download_resource_manifest_file(**kwargs):
        calls.update(kwargs)
        return [
            {
                "action": "download",
                "size_bytes": 9,
                "object_key": "resources/example.gpkg",
            }
        ]

    monkeypatch.setattr(
        "nextgen_hydra.cli.download_resource_manifest_file",
        fake_download_resource_manifest_file,
    )

    code = main(
        [
            "--root",
            str(repo_root),
            "download-resources",
            "--manifest",
            str(manifest_path),
            "--resource-dir",
            str(tmp_path / "resources"),
            "--approval-id",
            "RESOURCE_APPROVAL",
            "--plan-output",
            str(tmp_path / "resource_download_plan.jsonl"),
            "--provenance",
            str(tmp_path / "resource_download_provenance.jsonl"),
            "--summary-output",
            str(tmp_path / "resource_download_summary.json"),
            "--summary-markdown",
            str(tmp_path / "resource_download_summary.md"),
        ]
    )

    assert code == 0
    assert calls["execute"] is True
    assert calls["approval_id"] == "RESOURCE_APPROVAL"
    assert (tmp_path / "resource_download_summary.json").is_file()
    assert (tmp_path / "resource_download_summary.md").is_file()


def test_plan_backfill_cli_writes_dry_run_outputs(repo_root, tmp_path, monkeypatch):
    def fake_build_backfill_plan(**kwargs):
        return (
            [{"record_type": "object", "key": "k"}],
            [{"object_key": "k"}],
            {
                "manifest": {
                    "unique_object_count": 1,
                    "unique_size_bytes": 9,
                    "record_count": 1,
                    "max_object_size_bytes": 9,
                },
                "backfill": {
                    "status": "planned",
                    "estimated_tidy_rows": 18,
                    "object_body_downloads": False,
                    "requires_approval_id_before_download": True,
                    "run_dates": ["20260517"],
                    "streams": ["cfe_nom"],
                    "vpus": ["05"],
                },
            },
        )

    monkeypatch.setattr("nextgen_hydra.cli.build_backfill_plan", fake_build_backfill_plan)

    code = main(
        [
            "--root",
            str(repo_root),
            "plan-backfill",
            "--start-date",
            "20260517",
            "--end-date",
            "20260517",
            "--manifest-output",
            str(tmp_path / "backfill_manifest.jsonl"),
            "--discovery-output",
            str(tmp_path / "backfill_discovery.jsonl"),
            "--summary-output",
            str(tmp_path / "backfill_summary.json"),
            "--summary-markdown",
            str(tmp_path / "backfill_summary.md"),
        ]
    )

    assert code == 0
    assert (tmp_path / "backfill_manifest.jsonl").is_file()
    assert (tmp_path / "backfill_discovery.jsonl").is_file()
    assert (tmp_path / "backfill_summary.json").is_file()
    assert (tmp_path / "backfill_summary.md").is_file()


def test_build_resource_manifest_cli_all_vpus(repo_root, tmp_path, monkeypatch):
    def fake_build_resource_manifest_records(**kwargs):
        assert kwargs["all_vpus"] is True
        return [
            {
                "object_key": "resources/v2.2_hydrofabric/geopackages/VPU_01/nextgen_VPU_01.gpkg",
                "resource_type": "hydrofabric_geopackage",
                "resource_scope": "all_conus_vpus",
                "vpu_id": "01",
                "size_bytes": 1,
            }
        ]

    monkeypatch.setattr(
        "nextgen_hydra.cli.build_resource_manifest_records",
        fake_build_resource_manifest_records,
    )

    code = main(
        [
            "--root",
            str(repo_root),
            "build-resource-manifest",
            "--all-vpus",
            "--output",
            str(tmp_path / "resource_manifest_all_vpus.jsonl"),
            "--summary-output",
            str(tmp_path / "resource_manifest_summary.json"),
            "--summary-markdown",
            str(tmp_path / "resource_manifest_summary.md"),
        ]
    )

    assert code == 0
    assert (tmp_path / "resource_manifest_all_vpus.jsonl").is_file()
    assert (tmp_path / "resource_manifest_summary.json").is_file()
