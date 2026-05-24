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
