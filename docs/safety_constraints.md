# Safety Constraints

## Project Scope

This project targets only approved NextGen Research DataStream / NRDS streamflow simulation outputs and the minimum metadata, configuration, index, and provenance files needed to make those downloads reproducible.

The project must not build or operate USGS, ERA5, NWM v2, NWM v3, AORC, meteorological forcing, or general forecast-product acquisition pipelines. Future USGS bias evaluation and ERA5/imputation work may be represented only as scaffolding that consumes external datasets produced elsewhere.

## Rejected By Default

The following are rejected by default and must not be downloaded unless a later explicit approval changes the policy:

- NWM v2 products.
- NWM v3 products.
- Forcing products.
- AORC products.
- LDASIN files.
- Meteorological products, including precipitation, temperature, pressure, humidity, and wind.
- `forcings/` prefixes.
- `outputs/routing_only/`.
- `outputs/restarts/`.
- `restarts/`.
- `outputs/qkrig/`.
- `ngen-run.tar.gz`.
- `merkdir.file`.
- Broad run-input artifacts, tarballs, archives, bundles, cache files, and unknown run directories.
- Any product requiring forcing downloads to obtain streamflow outputs.

Path tokens such as `short_range`, `medium_range`, and `analysis_assim_extend` do not approve a product. Only exact approved troute streamflow outputs under approved `cfe_nom` or `lstm_0` stream prefixes can pass classification.

## Fail-Closed Behavior

The system must fail closed:

- Unknown products are not downloaded.
- Ambiguous products are not downloaded.
- Rejected products are not downloaded.
- Missing S3 size prevents download.
- Missing ETag prevents download.
- Unknown file extension prevents download.
- Oversized objects require explicit approval.
- A manifest row is downloadable only when classification is exactly `approved` and `approved_for_download` is true.
- The downloader must consume a validated manifest and must not hard-code one-off URLs.
- Product classification must use structured path parsing and explicit allowlists, not substring approval alone.

## Safety Thresholds

Milestone 1:

- No object-body downloads.
- Discovery may use public listings and object metadata only.
- HEAD/list metadata may be recorded for key, size, ETag, last modified time, and source URL.

Later proof downloads:

- Maximum object size: 25 MB per object.
- Maximum total proof-download size: 100 MB.
- Any larger object or total download requires explicit approval before execution.

Full historical download:

- Requires explicit approval after discovery, mapping, classification, manifest validation, and dry-run reporting are complete.

## Stop Conditions

Stop and ask for approval if:

- NRDS access pattern is ambiguous or changes.
- NRDS access requires credentials or paid access.
- The desired streamflow data can be obtained only by downloading NWM v2/v3 or forcing products.
- Hydrofabric feature IDs do not map cleanly to NRDS outputs.
- VPUs, date ranges, stream names, or formats cannot be verified.
- File formats require large object-body downloads to inspect.
- Product classification is ambiguous.
- Download size exceeds the configured safety thresholds.
- Work begins drifting into USGS acquisition, ERA5 acquisition, forecasting, or modeling.
