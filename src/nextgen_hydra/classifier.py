"""Fail-closed product classifier for NRDS object keys."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
import re
from typing import Any

from .config import proof_download_max_object_bytes
from .schemas import CLASSIFIER_VERSION


class ClassificationError(ValueError):
    """Raised when classifier inputs are malformed."""


@dataclass(frozen=True)
class ClassificationResult:
    key: str
    classification: str
    reason: str
    classifier_version: str
    parsed: dict[str, Any]
    format: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_object(
    obj: dict[str, Any],
    defaults: dict[str, Any],
    *,
    allow_oversized: bool = False,
    max_object_bytes: int | None = None,
) -> ClassificationResult:
    """Classify one S3 object metadata record.

    Approval is based on structured path parsing. Missing size/ETag and
    oversized objects become ambiguous so downstream code fails closed.
    """

    key = _get_key(obj)
    classifier_cfg = defaults["classifier"]
    metadata_cfg = defaults["metadata"]
    nrds_cfg = defaults["nrds"]
    max_bytes = (
        proof_download_max_object_bytes(defaults)
        if max_object_bytes is None
        else max_object_bytes
    )

    filename = PurePosixPath(key).name
    lowered_key = key.lower()
    lowered_filename = filename.lower()

    for prefix in classifier_cfg.get("reject_prefixes", []):
        if key.startswith(prefix):
            return _result(key, "rejected", f"rejected prefix: {prefix}")

    for rejected_filename in classifier_cfg.get("reject_filenames", []):
        if lowered_filename == rejected_filename.lower():
            return _result(key, "rejected", f"rejected filename: {filename}")

    if _is_archive_filename(lowered_filename):
        return _result(key, "rejected", f"rejected archive/bundle filename: {filename}")

    parts = key.split("/")
    if len(parts) > 1 and parts[0] == "outputs":
        stream = parts[1]
        if stream in classifier_cfg.get("ambiguous_streams", []):
            return _result(key, "ambiguous", f"stream is not approved: {stream}")

    output_parse = _parse_troute_output(parts, nrds_cfg, classifier_cfg)
    if output_parse is not None:
        metadata_problem = _metadata_problem(obj, defaults, max_bytes, allow_oversized)
        if metadata_problem:
            return _result(
                key,
                "ambiguous",
                metadata_problem,
                parsed=output_parse,
                fmt=output_parse["format"],
            )
        return _result(
            key,
            "approved",
            "approved troute streamflow output under exact allowlist",
            parsed=output_parse,
            fmt=output_parse["format"],
        )

    metadata_parse = _parse_metadata(parts, nrds_cfg, classifier_cfg, metadata_cfg)
    if metadata_parse is not None:
        metadata_problem = _metadata_problem(obj, defaults, max_bytes, allow_oversized)
        if metadata_problem:
            return _result(
                key,
                "ambiguous",
                metadata_problem,
                parsed=metadata_parse,
                fmt=metadata_parse["format"],
            )
        return _result(
            key,
            "approved",
            "approved small NRDS metadata/provenance file under exact allowlist",
            parsed=metadata_parse,
            fmt=metadata_parse["format"],
        )

    reject_token = _reject_token(lowered_key, classifier_cfg.get("reject_tokens", []))
    if reject_token:
        return _result(key, "rejected", f"rejected token: {reject_token}")

    return _result(key, "ambiguous", "object is outside the exact approved allowlist")


def classify_records(
    records: list[dict[str, Any]],
    defaults: dict[str, Any],
    *,
    allow_oversized: bool = False,
) -> list[dict[str, Any]]:
    classified: list[dict[str, Any]] = []
    for record in records:
        if record.get("record_type") not in (None, "object"):
            continue
        result = classify_object(record, defaults, allow_oversized=allow_oversized)
        enriched = dict(record)
        enriched.update(
            {
                "classification": result.classification,
                "classification_reason": result.reason,
                "classifier_version": result.classifier_version,
                "parsed": result.parsed,
                "format": result.format,
            }
        )
        classified.append(enriched)
    return classified


def _parse_troute_output(
    parts: list[str],
    nrds_cfg: dict[str, Any],
    classifier_cfg: dict[str, Any],
) -> dict[str, Any] | None:
    if len(parts) != 11:
        return None
    (
        root,
        stream,
        hydrofabric_version,
        run_date_folder,
        run_type,
        cycle,
        vpu_folder,
        ngen_run,
        outputs_dir,
        troute_dir,
        filename,
    ) = parts
    if root != "outputs":
        return None
    if stream not in classifier_cfg.get("approved_streams", []):
        return None
    if hydrofabric_version != nrds_cfg["hydrofabric_version"]:
        return None
    run_date = _parse_run_date(run_date_folder)
    vpu_id = _parse_vpu(vpu_folder)
    if not run_date or not run_type or not cycle or not vpu_id:
        return None
    if (ngen_run, outputs_dir, troute_dir) != ("ngen-run", "outputs", "troute"):
        return None
    if not filename.startswith(nrds_cfg["approved_output_filename_glob"].rstrip("*")):
        return None
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix not in set(nrds_cfg["approved_output_extensions"]):
        return None
    return {
        "product_type": "troute_streamflow_output",
        "stream": stream,
        "hydrofabric_version": hydrofabric_version,
        "run_date": run_date,
        "run_type": run_type,
        "cycle": cycle,
        "vpu_id": vpu_id,
        "filename": filename,
        "format": suffix.lstrip("."),
    }


def _parse_metadata(
    parts: list[str],
    nrds_cfg: dict[str, Any],
    classifier_cfg: dict[str, Any],
    metadata_cfg: dict[str, Any],
) -> dict[str, Any] | None:
    if len(parts) != 9:
        return None
    (
        root,
        stream,
        hydrofabric_version,
        run_date_folder,
        run_type,
        cycle,
        vpu_folder,
        metadata_dir,
        filename,
    ) = parts
    if root != "outputs":
        return None
    if stream not in classifier_cfg.get("approved_streams", []):
        return None
    if hydrofabric_version != nrds_cfg["hydrofabric_version"]:
        return None
    run_date = _parse_run_date(run_date_folder)
    vpu_id = _parse_vpu(vpu_folder)
    if not run_date or not run_type or not cycle or not vpu_id:
        return None
    if metadata_dir != metadata_cfg["approved_directory"]:
        return None
    if filename not in set(metadata_cfg["approved_filenames"]):
        return None
    return {
        "product_type": "metadata_provenance",
        "stream": stream,
        "hydrofabric_version": hydrofabric_version,
        "run_date": run_date,
        "run_type": run_type,
        "cycle": cycle,
        "vpu_id": vpu_id,
        "filename": filename,
        "format": PurePosixPath(filename).suffix.lower().lstrip(".") or "text",
    }


def _parse_run_date(folder: str) -> str | None:
    match = re.fullmatch(r"ngen\.(\d{8})", folder)
    return match.group(1) if match else None


def _parse_vpu(folder: str) -> str | None:
    match = re.fullmatch(r"VPU_([A-Za-z0-9]+)", folder)
    return match.group(1) if match else None


def _metadata_problem(
    obj: dict[str, Any],
    defaults: dict[str, Any],
    max_bytes: int,
    allow_oversized: bool,
) -> str | None:
    if defaults["classifier"].get("require_s3_size", True):
        size = _get_size(obj)
        if size is None:
            return "missing S3 size metadata"
        if size < 0:
            return "invalid negative S3 size metadata"
        if size > max_bytes and not allow_oversized:
            return (
                f"object size {size} exceeds active safety threshold "
                f"{max_bytes} bytes"
            )
    if defaults["classifier"].get("require_s3_etag", True) and not _get_etag(obj):
        return "missing S3 ETag metadata"
    return None


def _get_key(obj: dict[str, Any]) -> str:
    key = obj.get("key", obj.get("object_key"))
    if not isinstance(key, str) or not key:
        raise ClassificationError("object metadata record is missing key/object_key")
    if key.startswith("/") or ".." in key.split("/"):
        raise ClassificationError(f"unsafe object key: {key}")
    return key


def _get_size(obj: dict[str, Any]) -> int | None:
    raw = obj.get("size_bytes", obj.get("size"))
    if raw is None or raw == "":
        return None
    return int(raw)


def _get_etag(obj: dict[str, Any]) -> str | None:
    raw = obj.get("etag", obj.get("ETag"))
    if raw is None:
        return None
    text = str(raw).strip().strip('"')
    return text or None


def _reject_token(lowered_key: str, tokens: list[str]) -> str | None:
    key_tokens = set(re.split(r"[^a-z0-9]+", lowered_key))
    for token in tokens:
        lowered = token.lower()
        if lowered in key_tokens:
            return token
    return None


def _is_archive_filename(lowered_filename: str) -> bool:
    archive_suffixes = (
        ".tar",
        ".tar.gz",
        ".tgz",
        ".zip",
        ".gz",
        ".bz2",
        ".xz",
        ".7z",
    )
    return lowered_filename.endswith(archive_suffixes)


def _result(
    key: str,
    classification: str,
    reason: str,
    *,
    parsed: dict[str, Any] | None = None,
    fmt: str | None = None,
) -> ClassificationResult:
    return ClassificationResult(
        key=key,
        classification=classification,
        reason=reason,
        classifier_version=CLASSIFIER_VERSION,
        parsed=parsed or {},
        format=fmt,
    )
