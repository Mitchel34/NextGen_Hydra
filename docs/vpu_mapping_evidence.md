# VPU Mapping Evidence

Discovery date: 2026-05-23

This log records authoritative evidence for mapping the four canonical
hydrofabric feature IDs to Vector Processing Units (VPUs). No NRDS or
hydrofabric object bodies were downloaded during this mapping discovery. The
evidence came from public API responses and public S3 listing metadata only.

## Method

Authoritative source roles:

- USGS NLDI linked-data endpoints confirmed each USGS gage is indexed to the
  configured `comid`, which matches this repository's `hydrofabric_feature_id`.
- USGS Fabric `nhdflowline_network` records directly expose `comid`, `rpuid`,
  and `vpuid` for the same feature IDs.
- USGS Fabric documentation identifies the `nhdflowline_network` collection,
  `comid` filtering, single-feature item endpoints, and `vpuid` as a queryable
  property.
- NOAA-OWP Hydrofabric documentation describes VPU as Vector Processing Unit
  and shows hydrofabric access patterns that use `vpuid` for hydrolocation and
  VPU fabric retrieval.
- NRDS public S3 listings confirmed that `VPU_05` and `VPU_06` exist under the
  approved `outputs/cfe_nom/v2.2_hydrofabric` and
  `outputs/lstm_0/v2.2_hydrofabric` troute output prefixes.

Primary documentation:

- https://api.water.usgs.gov/docs/fabric-pygeoapi/
- https://noaa-owp.github.io/hydrofabric/articles/02-design-deep-dive.html
- https://noaa-owp.github.io/hydrofabric/articles/data.html

## Results

| Site | USGS gage | Feature ID / COMID | Reachcode | RPU | VPU |
| --- | --- | ---: | --- | --- | --- |
| South Fork New River near Jefferson, NC | `03161000` | `6892192` | `05050001000408` | `05d` | `05` |
| New River near Galax, VA | `03164000` | `6887572` | `05050001002694` | `05d` | `05` |
| Watauga River near Sugar Grove, NC | `03479000` | `19743430` | `06010103000146` | `06a` | `06` |
| Watauga River at Elizabethton, TN | `03486000` | `19745222` | `06010103000036` | `06a` | `06` |

## Site Evidence

### South Fork New River Near Jefferson NC

- NLDI: `https://api.water.usgs.gov/nldi/linked-data/nwissite/USGS-03161000`
  returned `identifier=USGS-03161000`, `comid=6892192`,
  `reachcode=05050001000408`, and the expected gage name.
- USGS Fabric item:
  `https://api.water.usgs.gov/fabric/pygeoapi/collections/nhdflowline_network/items/6892192?f=json`
  returned `comid=6892192`, `reachcode=05050001000408`, `rpuid=05d`,
  and `vpuid=05`.
- USGS legacy WFS cross-check:
  `https://api.water.usgs.gov/geoserver/wmadata/ows?service=WFS&version=1.0.0&request=GetFeature&typeName=wmadata:nhdflowline_network&outputFormat=application/json&CQL_FILTER=comid%3D6892192`
  returned the same `comid`, `reachcode`, `rpuid`, and `vpuid`.

### New River Near Galax VA

- NLDI: `https://api.water.usgs.gov/nldi/linked-data/nwissite/USGS-03164000`
  returned `identifier=USGS-03164000`, `comid=6887572`,
  `reachcode=05050001002694`, and the expected gage name.
- USGS Fabric item:
  `https://api.water.usgs.gov/fabric/pygeoapi/collections/nhdflowline_network/items/6887572?f=json`
  returned `comid=6887572`, `reachcode=05050001002694`, `rpuid=05d`,
  and `vpuid=05`.
- USGS legacy WFS cross-check:
  `https://api.water.usgs.gov/geoserver/wmadata/ows?service=WFS&version=1.0.0&request=GetFeature&typeName=wmadata:nhdflowline_network&outputFormat=application/json&CQL_FILTER=comid%3D6887572`
  returned the same `comid`, `reachcode`, `rpuid`, and `vpuid`.

### Watauga River Near Sugar Grove NC

- NLDI: `https://api.water.usgs.gov/nldi/linked-data/nwissite/USGS-03479000`
  returned `identifier=USGS-03479000`, `comid=19743430`,
  `reachcode=06010103000146`, and the expected gage name.
- USGS Fabric item:
  `https://api.water.usgs.gov/fabric/pygeoapi/collections/nhdflowline_network/items/19743430?f=json`
  returned `comid=19743430`, `reachcode=06010103000146`, `rpuid=06a`,
  and `vpuid=06`.
- USGS legacy WFS cross-check:
  `https://api.water.usgs.gov/geoserver/wmadata/ows?service=WFS&version=1.0.0&request=GetFeature&typeName=wmadata:nhdflowline_network&outputFormat=application/json&CQL_FILTER=comid%3D19743430`
  returned the same `comid`, `reachcode`, `rpuid`, and `vpuid`.

### Watauga River At Elizabethton TN

- NLDI: `https://api.water.usgs.gov/nldi/linked-data/nwissite/USGS-03486000`
  returned `identifier=USGS-03486000`, `comid=19745222`,
  `reachcode=06010103000036`, and the expected gage name.
- USGS Fabric item:
  `https://api.water.usgs.gov/fabric/pygeoapi/collections/nhdflowline_network/items/19745222?f=json`
  returned `comid=19745222`, `reachcode=06010103000036`, `rpuid=06a`,
  and `vpuid=06`.
- USGS legacy WFS cross-check:
  `https://api.water.usgs.gov/geoserver/wmadata/ows?service=WFS&version=1.0.0&request=GetFeature&typeName=wmadata:nhdflowline_network&outputFormat=application/json&CQL_FILTER=comid%3D19745222`
  returned the same `comid`, `reachcode`, `rpuid`, and `vpuid`.

## NRDS VPU Prefix Verification

Public S3 listing metadata confirmed the approved stream prefixes include both
target VPUs for the latest listed date checked, `ngen.20260523`, under
`short_range/00/`:

| Stream | VPU | Example approved troute object from listing metadata | Size bytes |
| --- | --- | --- | ---: |
| `cfe_nom` | `05` | `outputs/cfe_nom/v2.2_hydrofabric/ngen.20260523/short_range/00/VPU_05/ngen-run/outputs/troute/troute_output_202605230100.parquet` | `9929607` |
| `cfe_nom` | `06` | `outputs/cfe_nom/v2.2_hydrofabric/ngen.20260523/short_range/00/VPU_06/ngen-run/outputs/troute/troute_output_202605230100.parquet` | `3245772` |
| `lstm_0` | `05` | `outputs/lstm_0/v2.2_hydrofabric/ngen.20260523/short_range/00/VPU_05/ngen-run/outputs/troute/troute_output_202605230100.parquet` | `9002702` |
| `lstm_0` | `06` | `outputs/lstm_0/v2.2_hydrofabric/ngen.20260523/short_range/00/VPU_06/ngen-run/outputs/troute/troute_output_202605230100.parquet` | `2932666` |

Example listing URLs:

- `https://ciroh-community-ngen-datastream.s3.amazonaws.com/?list-type=2&prefix=outputs/cfe_nom/v2.2_hydrofabric/ngen.20260523/short_range/00/VPU_05/ngen-run/outputs/troute/&max-keys=5`
- `https://ciroh-community-ngen-datastream.s3.amazonaws.com/?list-type=2&prefix=outputs/cfe_nom/v2.2_hydrofabric/ngen.20260523/short_range/00/VPU_06/ngen-run/outputs/troute/&max-keys=5`
- `https://ciroh-community-ngen-datastream.s3.amazonaws.com/?list-type=2&prefix=outputs/lstm_0/v2.2_hydrofabric/ngen.20260523/short_range/00/VPU_05/ngen-run/outputs/troute/&max-keys=5`
- `https://ciroh-community-ngen-datastream.s3.amazonaws.com/?list-type=2&prefix=outputs/lstm_0/v2.2_hydrofabric/ngen.20260523/short_range/00/VPU_06/ngen-run/outputs/troute/&max-keys=5`

## Limitations

This milestone verifies feature-to-VPU mappings and approved VPU prefix
availability. It does not verify that the target feature IDs are present inside
the listed troute output files because that would require object-body access.
That check belongs to the next explicitly approved download/schema-inspection
milestone.
