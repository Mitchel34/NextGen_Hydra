from __future__ import annotations

from nextgen_hydra.download import DownloadSafetyError, download_manifest_file, plan_downloads
from nextgen_hydra.manifest import build_manifest_records, write_jsonl
from tests.test_manifest import mapped_site

import pytest


def test_dry_run_plan_does_not_write_data(defaults, approved_object, tmp_path):
    manifest = build_manifest_records([approved_object], [mapped_site()], defaults)

    plan = plan_downloads(manifest, tmp_path / "raw", defaults)

    assert plan[0]["action"] == "download"
    assert not (tmp_path / "raw").exists()


def test_existing_matching_file_is_skipped(defaults, approved_object, tmp_path):
    approved_object = dict(approved_object, size_bytes=3)
    manifest = build_manifest_records([approved_object], [mapped_site()], defaults)
    local_path = tmp_path / "raw" / approved_object["key"]
    local_path.parent.mkdir(parents=True)
    local_path.write_bytes(b"abc")

    plan = plan_downloads(manifest, tmp_path / "raw", defaults)

    assert plan[0]["action"] == "skip_existing"


def test_milestone_1_refuses_body_download(defaults, approved_object, tmp_path):
    manifest = build_manifest_records([approved_object], [mapped_site()], defaults)
    manifest_path = tmp_path / "manifest.jsonl"
    write_jsonl(manifest_path, manifest)

    with pytest.raises(DownloadSafetyError, match="milestone 1 forbids"):
        download_manifest_file(
            manifest_path=manifest_path,
            raw_dir=tmp_path / "raw",
            defaults=defaults,
            execute=True,
            approval_id="approved-by-test",
            milestone=1,
        )


def test_execute_requires_approval(defaults, approved_object, tmp_path):
    manifest = build_manifest_records([approved_object], [mapped_site()], defaults)
    manifest_path = tmp_path / "manifest.jsonl"
    write_jsonl(manifest_path, manifest)

    with pytest.raises(DownloadSafetyError, match="approval_id"):
        download_manifest_file(
            manifest_path=manifest_path,
            raw_dir=tmp_path / "raw",
            defaults=defaults,
            execute=True,
        )
