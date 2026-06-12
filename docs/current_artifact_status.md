# Current Artifact Status

Status: approved slice and national directory ready

Last verified: 2026-06-12

## Approved Slice

- Approval ID: `APPROVED_M4_NRDS_SMALL_DOWNLOAD_20260524`
- Run date: `20260523`
- Run type: `short_range`
- Cycle: `00`
- Streams: `cfe_nom`, `lstm_0`
- VPUs: `05`, `06`
- Raw inventory records: 44
- Schema status: `pass`
- Feature/time/flow columns: `feature_id`, `time`, `flow`
- Flow units: `m3 s-1`

## Tidy Data

- Catalog: `data/tidy/catalog.jsonl`
- Tidy records: 8
- Tidy rows: 144
- Per-site rows: 36
- Missing streamflow rows: 0
- Duplicate timestamps: 0
- Time coverage: `2026-05-23T02:00:00+00:00` to `2026-05-23T19:00:00+00:00`

## Cached Exports

- CSV export ID: `export_f9cdf68a18a5373c`
- Parquet export ID: `export_5d281eccc8ba81e2`
- Export rows: 144

## Hydrofabric Resources

- Approval ID: `APPROVED_HYDROFABRIC_ALL_VPUS_DIRECTORY_20260607`
- Resource manifest: `manifests/resource_manifest_all_vpus.jsonl`
- Resource scope: all configured CONUS VPUs
- GPKG resources: 21 of 21 present
- Local resource bytes: 4,588,531,712
- Size verification: all local files match manifest `size_bytes`
- Locality verification: no `.part` files and no dataless GPKG placeholders
- SQLite verification: all 21 GPKGs open and include required directory tables
- Last replacement run: 4 downloaded, 17 skipped, 1,147,105,280 executed bytes

## National Site Directory

- Directory: `data/catalog/site_directory.jsonl`
- Report: `reports/site_directory_summary.json`
- Paired rows: 17,639
- Unique USGS gages: 17,638
- Unique t-route features: 17,238
- Map-ready rows: 17,639
- Source resources: 21 GPKGs
- VPUs: `01`, `02`, `03N`, `03S`, `03W`, `04`, `05`, `06`, `07`, `08`, `09`, `10L`, `10U`, `11`, `12`, `13`, `14`, `15`, `16`, `17`, `18`
- COMID status counts: `multiple_candidates`: 17,639
- USGS enrichment: enabled

## Public Portal Readiness

- `tidy_available`: true
- `export_available`: true
- `/api/site-map` and `/api/site-map/summary` serve the national paired-site directory.
- The React portal includes a Leaflet map over cached paired-site artifacts.
- Public API remains read-only over CLI-produced artifacts.
- Discovery, downloads, resource downloads, approvals, and crosswalk resolution
  remain CLI/admin workflows.

## Next Expansion

The next historical expansion should start with a dry-run-only backfill plan for
at most seven calendar days. Do not execute object-body downloads until a new
approval ID is issued for the resulting manifest and byte totals.
