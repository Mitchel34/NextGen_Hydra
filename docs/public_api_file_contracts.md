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

## Public Dataset Contract

`GET /api/datasets` groups troute manifest/catalog rows by:

- `stream`
- `run_date`
- `run_type`
- `cycle`

Each dataset reports site IDs, VPUs, raw object counts, schema status, tidy row
counts, and whether cached export generation is available.

## Export Contract

`POST /api/exports/preview` and `POST /api/exports` accept:

- `site_ids`: list of configured site IDs.
- `streams`: list of stream names, for example `cfe_nom`.
- `start_time_utc`: optional inclusive UTC start.
- `end_time_utc`: optional inclusive UTC end.
- `format`: `csv` or `parquet`.

Exports are created only from existing tidy catalog entries whose files exist
under the project root and have `coverage_status: pass`. The API rejects export
requests when no approved tidy files are available.

## Forbidden Public Operations

The public API intentionally has no routes for:

- NRDS discovery.
- NRDS object-body download.
- Hydrofabric resource download.
- Approval ID submission.
- Crosswalk resolution.
- Full historical expansion.

Those remain CLI/admin workflows with explicit approval IDs and provenance.
