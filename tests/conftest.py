from __future__ import annotations

from pathlib import Path

import pytest

from nextgen_hydra.config import load_defaults


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def defaults(repo_root: Path):
    return load_defaults(repo_root / "configs/defaults.yaml")


@pytest.fixture
def approved_object_key() -> str:
    return (
        "outputs/cfe_nom/v2.2_hydrofabric/ngen.20260522/short_range/00/"
        "VPU_05/ngen-run/outputs/troute/troute_output_202605220100.parquet"
    )


@pytest.fixture
def approved_object(approved_object_key: str):
    return {
        "record_type": "object",
        "key": approved_object_key,
        "size_bytes": 1024,
        "etag": "abc123",
        "last_modified": "2026-05-22T01:00:00.000Z",
        "source_listing_ref": "fixture",
    }
