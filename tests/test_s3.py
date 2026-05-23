from __future__ import annotations

from nextgen_hydra.io.s3 import parse_list_objects_v2_xml


def test_parse_list_objects_v2_xml():
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
  <Name>ciroh-community-ngen-datastream</Name>
  <Prefix>outputs/</Prefix>
  <Delimiter>/</Delimiter>
  <IsTruncated>false</IsTruncated>
  <CommonPrefixes><Prefix>outputs/cfe_nom/</Prefix></CommonPrefixes>
  <Contents>
    <Key>outputs/cfe_nom/example.parquet</Key>
    <LastModified>2026-05-22T00:00:00.000Z</LastModified>
    <ETag>&quot;abc&quot;</ETag>
    <Size>10</Size>
  </Contents>
</ListBucketResult>
"""

    result = parse_list_objects_v2_xml(
        xml,
        bucket="ciroh-community-ngen-datastream",
        prefix="outputs/",
        delimiter="/",
    )

    assert result.common_prefixes == ["outputs/cfe_nom/"]
    assert result.objects[0]["key"] == "outputs/cfe_nom/example.parquet"
    assert result.objects[0]["size_bytes"] == 10
    assert result.objects[0]["etag"] == "abc"
