# Current Artifact Status

Status: approved slice ready

Last verified: 2026-06-07

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

## Public Portal Readiness

- `tidy_available`: true
- `export_available`: true
- Public API remains read-only over CLI-produced artifacts.
- Discovery, downloads, resource downloads, approvals, and crosswalk resolution
  remain CLI/admin workflows.

## Next Expansion

The next historical expansion should start with a dry-run-only backfill plan for
at most seven calendar days. Do not execute object-body downloads until a new
approval ID is issued for the resulting manifest and byte totals.
