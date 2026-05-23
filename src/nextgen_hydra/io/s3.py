"""Unauthenticated public S3 listing helpers.

Only bucket-listing XML and HEAD metadata are read here. Object-body downloads
are implemented separately and guarded by the downloader.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


class S3AccessError(RuntimeError):
    """Raised when public S3 metadata access fails."""


@dataclass(frozen=True)
class S3ListResult:
    bucket: str
    prefix: str
    delimiter: str | None
    common_prefixes: list[str]
    objects: list[dict[str, Any]]
    is_truncated: bool
    next_token: str | None


def public_url(base_url: str, key: str) -> str:
    return base_url.rstrip("/") + "/" + quote(key, safe="/")


def list_objects_v2(
    *,
    bucket: str,
    prefix: str = "",
    delimiter: str | None = "/",
    max_keys: int = 1000,
    continuation_token: str | None = None,
    timeout: int = 30,
) -> S3ListResult:
    query: dict[str, str] = {
        "list-type": "2",
        "prefix": prefix,
        "max-keys": str(max_keys),
    }
    if delimiter is not None:
        query["delimiter"] = delimiter
    if continuation_token:
        query["continuation-token"] = continuation_token
    url = f"https://{bucket}.s3.amazonaws.com/?{urlencode(query)}"
    request = Request(url, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
    except Exception as exc:  # pragma: no cover - exact urllib errors vary
        raise S3AccessError(f"public S3 listing failed for prefix {prefix!r}: {exc}") from exc
    return parse_list_objects_v2_xml(body, bucket=bucket, prefix=prefix, delimiter=delimiter)


def head_object(
    *,
    bucket: str,
    key: str,
    timeout: int = 30,
) -> dict[str, Any]:
    url = f"https://{bucket}.s3.amazonaws.com/{quote(key, safe='/')}"
    request = Request(url, method="HEAD")
    try:
        with urlopen(request, timeout=timeout) as response:
            headers = response.headers
    except Exception as exc:  # pragma: no cover - exact urllib errors vary
        raise S3AccessError(f"public S3 HEAD failed for key {key!r}: {exc}") from exc
    size = headers.get("Content-Length")
    last_modified = headers.get("Last-Modified")
    parsed_last_modified = None
    if last_modified:
        parsed_last_modified = (
            parsedate_to_datetime(last_modified).astimezone(UTC).isoformat()
        )
    return {
        "record_type": "object",
        "key": key,
        "size_bytes": int(size) if size is not None else None,
        "etag": (headers.get("ETag") or "").strip('"') or None,
        "last_modified": parsed_last_modified,
        "metadata_source": "head-object",
    }


def parse_list_objects_v2_xml(
    xml_body: bytes | str,
    *,
    bucket: str,
    prefix: str,
    delimiter: str | None,
) -> S3ListResult:
    root = ET.fromstring(xml_body)
    ns = _namespace(root.tag)

    def find_text(element: ET.Element, name: str) -> str | None:
        found = element.find(f"{ns}{name}")
        return None if found is None else found.text

    common_prefixes = [
        text
        for node in root.findall(f"{ns}CommonPrefixes")
        for text in [find_text(node, "Prefix")]
        if text
    ]
    objects: list[dict[str, Any]] = []
    listed_at = datetime.now(UTC).isoformat()
    for node in root.findall(f"{ns}Contents"):
        key = find_text(node, "Key")
        if not key:
            continue
        size_text = find_text(node, "Size")
        objects.append(
            {
                "record_type": "object",
                "key": key,
                "size_bytes": int(size_text) if size_text is not None else None,
                "etag": (find_text(node, "ETag") or "").strip('"') or None,
                "last_modified": find_text(node, "LastModified"),
                "source_listing_ref": prefix,
                "metadata_source": "list-objects-v2",
                "listed_at_utc": listed_at,
            }
        )
    return S3ListResult(
        bucket=bucket,
        prefix=prefix,
        delimiter=delimiter,
        common_prefixes=common_prefixes,
        objects=objects,
        is_truncated=(find_text(root, "IsTruncated") or "").lower() == "true",
        next_token=find_text(root, "NextContinuationToken"),
    )


def _namespace(tag: str) -> str:
    if tag.startswith("{"):
        return tag[: tag.index("}") + 1]
    return ""
