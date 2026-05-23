from __future__ import annotations

from nextgen_hydra.classifier import classify_object


def test_approved_troute_outputs(defaults):
    examples = [
        (
            "outputs/cfe_nom/v2.2_hydrofabric/ngen.20260522/short_range/00/"
            "VPU_05/ngen-run/outputs/troute/troute_output_202605220100.parquet"
        ),
        (
            "outputs/lstm_0/v2.2_hydrofabric/ngen.20251125/short_range/00/"
            "VPU_05/ngen-run/outputs/troute/troute_output_202511250100.nc"
        ),
    ]

    for key in examples:
        result = classify_object(
            {"key": key, "size_bytes": 1024, "etag": "etag"},
            defaults,
        )
        assert result.classification == "approved"
        assert result.parsed["product_type"] == "troute_streamflow_output"


def test_approved_metadata_can_include_nwmurl_filename(defaults):
    key = (
        "outputs/cfe_nom/v2.2_hydrofabric/ngen.20260522/short_range/00/"
        "VPU_05/datastream-metadata/conf_nwmurl.json"
    )

    result = classify_object(
        {"key": key, "size_bytes": 100, "etag": "etag"},
        defaults,
    )

    assert result.classification == "approved"
    assert result.parsed["product_type"] == "metadata_provenance"


def test_forbidden_products_are_rejected(defaults):
    examples = [
        "forcings/v2.2_hydrofabric/ngen.20260522/short_range/00/VPU_05/file.nc",
        "outputs/routing_only/v2.2_hydrofabric/ngen.20260522/short_range/00/VPU_05/file.nc",
        "outputs/restarts/v2.2_hydrofabric/ngen.20260522/file.nc",
        "restarts/v2.2_hydrofabric/ngen.20260522/file.nc",
        "outputs/qkrig/qkrig.20260522/file.nc",
        (
            "outputs/cfe_nom/v2.2_hydrofabric/ngen.20260522/short_range/00/"
            "VPU_05/ngen-run.tar.gz"
        ),
        (
            "outputs/cfe_nom/v2.2_hydrofabric/ngen.20260522/short_range/00/"
            "VPU_05/merkdir.file"
        ),
        (
            "outputs/cfe_nom/v2.2_hydrofabric/ngen.20260522/short_range/00/"
            "VPU_05/ngen-run/outputs/troute/nwm.t00z.medium_range.channel_rt.nc"
        ),
    ]

    for key in examples:
        result = classify_object(
            {"key": key, "size_bytes": 1024, "etag": "etag"},
            defaults,
        )
        assert result.classification == "rejected", key


def test_ambiguous_products_fail_closed(defaults):
    examples = [
        (
            "outputs/lstm/v2.2_hydrofabric/ngen.20260213/short_range/00/"
            "VPU_05/ngen-run/outputs/troute/troute_output_202602130100.parquet"
        ),
        (
            "outputs/cfe_nom/v2.2_hydrofabric/ngen.20260522/short_range/00/"
            "VPU_05/ngen-run/outputs/troute/troute_output_202605220100.csv"
        ),
        (
            "outputs/cfe_nom/v2.2_hydrofabric/ngen.20260522/short_range/00/"
            "VPU_05/unknown.file"
        ),
    ]

    for key in examples:
        result = classify_object(
            {"key": key, "size_bytes": 1024, "etag": "etag"},
            defaults,
        )
        assert result.classification == "ambiguous", key


def test_missing_metadata_and_oversize_are_ambiguous(defaults, approved_object_key):
    missing_size = classify_object({"key": approved_object_key, "etag": "etag"}, defaults)
    missing_etag = classify_object(
        {"key": approved_object_key, "size_bytes": 1024},
        defaults,
    )
    oversized = classify_object(
        {"key": approved_object_key, "size_bytes": 26 * 1024 * 1024, "etag": "etag"},
        defaults,
    )

    assert missing_size.classification == "ambiguous"
    assert missing_etag.classification == "ambiguous"
    assert oversized.classification == "ambiguous"
