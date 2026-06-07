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
- `data/catalog/site_directory.jsonl`: optional local site directory containing
  searchable NextGen/NWM/ERA5/USGS availability records.
- `data/requests/acquisition_requests.jsonl`: public acquisition request queue
  written by the API for admin review.

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

`GET /api/site-directory` searches the local site directory by COMID, USGS gage,
site ID, name, troute feature ID, or VPU. When
`data/catalog/site_directory.jsonl` is missing, the API falls back to the
configured project sites.

`GET /api/site-directory/{identifier}` returns one directory record by site ID,
COMID, troute feature ID, hydrofabric feature ID, or USGS gage ID.

Directory records should use this shape:

- `site_id`: stable site identifier.
- `name`: display name.
- `comid` or `hydrofabric_feature_id`: NHD/hydrofabric feature ID when known.
- `troute_feature_id`: resolved t-route feature ID when known.
- `usgs_gage_id`: USGS station ID when known.
- `vpu_id`: hydrofabric VPU when known.
- `availability.nextgen`, `availability.nwm`, `availability.era5`,
  `availability.usgs`: booleans indicating local/cataloged availability.
- `status`: for example `available`, `configured`, `unresolved`, or `review`.

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

## Acquisition Request Contract

`POST /api/acquisition-requests` creates an intake record only. It does not
discover keys, download objects, resolve crosswalks, or submit approval IDs.

Accepted fields:

- `site_ids`: optional directory site IDs.
- `comids`: optional numeric COMIDs/hydrofabric feature IDs.
- `usgs_gage_ids`: optional numeric USGS station IDs.
- `query`: optional free-form search text.
- `sources`: one or more of `nextgen`, `nwm`, `era5`, `usgs`.
- `streams`: requested streams where relevant, for example `cfe_nom`.
- `start_time_utc` and `end_time_utc`: requested UTC time bounds.
- `formats`: `csv` or `parquet`.
- `preprocessing`: same deterministic export preprocessing object.

The response has `status: queued_for_admin_review`, `public_execution: false`,
`object_body_downloads: false`, and `requires_admin_cli: true`. Admin workflows
must still validate identifiers, build dry-run plans, require approval IDs, and
write provenance before any acquisition.

## Forbidden Public Operations

The public API intentionally has no routes for:

- NRDS discovery.
- NRDS object-body download.
- Hydrofabric resource download.
- Approval ID submission.
- Crosswalk resolution.
- Full historical expansion.
- Public execution of acquisition requests.

Those remain CLI/admin workflows with explicit approval IDs and provenance.
