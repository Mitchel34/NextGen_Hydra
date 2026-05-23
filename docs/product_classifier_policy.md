# Product Classifier Policy

## Policy Summary

The product classifier is the safety gate for discovery, manifest building, and downloading. It must classify every object as `approved`, `rejected`, or `ambiguous`. Only `approved` objects may enter a downloadable manifest, and the downloader must refuse all other classes.

The policy is fail closed. Anything outside the exact allowlist is not downloadable.

## Approved Product Classes

Approved streamflow simulation outputs:

- `outputs/cfe_nom/v2.2_hydrofabric/.../ngen-run/outputs/troute/troute_output_*.parquet`
- `outputs/cfe_nom/v2.2_hydrofabric/.../ngen-run/outputs/troute/troute_output_*.nc`
- `outputs/lstm_0/v2.2_hydrofabric/.../ngen-run/outputs/troute/troute_output_*.parquet`
- `outputs/lstm_0/v2.2_hydrofabric/.../ngen-run/outputs/troute/troute_output_*.nc`

Required parsed fields for approved streamflow outputs:

- Stream is exactly `cfe_nom` or `lstm_0`.
- Hydrofabric version is exactly `v2.2_hydrofabric`.
- Run date folder matches `ngen.YYYYMMDD`.
- Run type, cycle, and VPU folder are parseable.
- Output directory is exactly `ngen-run/outputs/troute/`.
- Filename matches `troute_output_*`.
- Extension is `.parquet` or `.nc`.
- S3 size and ETag are present.
- Object size is within the active safety threshold or has explicit approval.

Approved metadata/provenance files:

Only small files under an approved `cfe_nom` or `lstm_0` VPU/run prefix are approved:

- `datastream-metadata/conf_datastream.json`
- `datastream-metadata/conf_fp.json`
- `datastream-metadata/conf_nwmurl.json`
- `datastream-metadata/datastream.env`
- `datastream-metadata/datastream_steps.txt`
- `datastream-metadata/docker_hashes.txt`
- `datastream-metadata/execution.json`
- `datastream-metadata/profile.txt`
- `datastream-metadata/realization_datastream.json`
- `datastream-metadata/realization_user.json`

## Rejected Product Classes

Reject by exact prefix, parsed product type, filename, token, or source classification:

- `forcings/`.
- NWM v2 products.
- NWM v3 products.
- Any product whose source is NWM v2/v3 rather than approved NextGen/NRDS simulation output.
- AORC products.
- LDASIN files.
- Meteorological forcing products, including precipitation, temperature, pressure, humidity, and wind.
- `outputs/routing_only/`.
- `outputs/restarts/`.
- `restarts/`.
- `outputs/qkrig/`.
- `ngen-run.tar.gz`.
- `merkdir.file`.
- Broad run-input artifacts.
- Unknown tarballs, archives, bundles, cache files, and broad run directories.
- Any object that requires downloading forcing data to extract the target streamflow series.

Rejected examples:

```text
forcings/v2.2_hydrofabric/ngen.20260522/short_range/00/VPU_05/...
outputs/routing_only/v2.2_hydrofabric/ngen.20260522/short_range/00/VPU_05/...
outputs/restarts/v2.2_hydrofabric/ngen.20260522/...
outputs/qkrig/qkrig.20260522/...
outputs/cfe_nom/v2.2_hydrofabric/ngen.20260522/short_range/00/VPU_05/ngen-run.tar.gz
outputs/cfe_nom/v2.2_hydrofabric/ngen.20260522/short_range/00/VPU_05/merkdir.file
```

## Ambiguous Product Classes

Classify as `ambiguous` when the object is not explicitly approved or explicitly rejected, including:

- Anything outside the exact allowlist.
- Unknown file extensions.
- Missing S3 size.
- Missing ETag.
- Oversized objects without explicit approval.
- `outputs/lstm/` until explicitly approved.
- Any path where stream, hydrofabric version, run date, run type, cycle, VPU, output directory, filename, or extension cannot be parsed.
- Any metadata file not on the approved metadata filename list.
- Any path where product identity depends on undocumented assumptions.

Ambiguous examples:

```text
outputs/lstm/v2.2_hydrofabric/ngen.20260213/short_range/00/VPU_05/ngen-run/outputs/troute/troute_output_202602130100.parquet
outputs/cfe_nom/v2.2_hydrofabric/ngen.20260522/short_range/00/VPU_05/ngen-run/outputs/troute/troute_output_202605220100.csv
outputs/cfe_nom/v2.2_hydrofabric/ngen.20260522/short_range/00/VPU_05/unknown.file
```

## Approved Examples

These examples show shape only. They do not assert site mapping.

```text
outputs/cfe_nom/v2.2_hydrofabric/ngen.20260522/short_range/00/VPU_05/ngen-run/outputs/troute/troute_output_202605220100.parquet
outputs/lstm_0/v2.2_hydrofabric/ngen.20260522/short_range/00/VPU_05/ngen-run/outputs/troute/troute_output_202605220100.parquet
outputs/cfe_nom/v2.2_hydrofabric/ngen.20251125/short_range/00/VPU_05/ngen-run/outputs/troute/troute_output_202511250100.nc
outputs/cfe_nom/v2.2_hydrofabric/ngen.20260522/short_range/00/VPU_05/datastream-metadata/conf_datastream.json
```

## Downloader Contract

- The classifier must run before manifest creation.
- Manifest validation must reject `rejected` and `ambiguous` records.
- The downloader must refuse records without `approved_for_download: true`.
- The downloader must enforce configured size thresholds.
- The downloader must log provenance for every accepted, skipped, rejected, and failed artifact.
