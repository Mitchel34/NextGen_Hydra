# Public API File Contracts

The public API is a read-only facade over local artifacts produced by the
admin CLI. It must not discover NRDS keys, download NRDS object bodies, download
hydrofabric resources, or resolve crosswalks.

## Inputs Read By The API

- `configs/sites.yaml`: canonical public site metadata.
- `configs/site_crosswalk.yaml`: resolved troute feature IDs when available.
- `manifests/manifest.jsonl`: approved NRDS troute manifest rows.
- `reports/schema_inspection.json`: schema and coverage status.
- `data/tidy/catalog.jsonl`: approved tidy file catalog.
- `data/tidy/**`: cached tidy CSV/Parquet files referenced by the catalog.
- `data/exports/**`: public export files generated from cached tidy files.
- `reports/qc_report.json`: QC status and per-site coverage.
- `reports/artifact_catalog.json`: optional prebuilt public artifact catalog.

## Public Dataset Contract

`GET /api/datasets` groups troute manifest/catalog rows by:

- `stream`
- `run_date`
- `run_type`
- `cycle`

Each dataset reports site IDs, VPUs, raw object counts, schema status, tidy row
counts, and whether cached export generation is available.

`GET /api/status` reports overall readiness, schema/units/QC status, and
explicitly lists forbidden public operations.

`GET /api/qc` returns the CLI-produced QC report when available.

`GET /api/units` returns the documented streamflow units and evidence count.

`GET /api/export-options` returns available sites, streams, formats,
preprocessing options, columns, and time coverage.

## Export Contract

`POST /api/exports/preview` and `POST /api/exports` accept:

- `site_ids`: list of configured site IDs.
- `streams`: list of stream names, for example `cfe_nom`.
- `start_time_utc`: optional inclusive UTC start.
- `end_time_utc`: optional inclusive UTC end.
- `format`: `csv` or `parquet`.
- `columns`: optional list of columns to include.
- `preprocessing.missing_streamflow`: `keep` or `drop`.
- `preprocessing.aggregation`: `none` or `daily_mean`.

Exports are created only from existing tidy catalog entries whose files exist
under the project root and have `coverage_status: pass`. The API rejects export
requests when no approved tidy files are available.

Each created export writes a sidecar metadata file next to the export containing
the request payload, preprocessing choices, source tidy files, and row count.

## Forbidden Public Operations

The public API intentionally has no routes for:

- NRDS discovery.
- NRDS object-body download.
- Hydrofabric resource download.
- Approval ID submission.
- Crosswalk resolution.
- Full historical expansion.

Those remain CLI/admin workflows with explicit approval IDs and provenance.
