# NextGen/NRDS Streamflow Acquisition Implementation Plan

## 1. Executive Summary

Build a reproducible Python-based data acquisition and preparation system for historical NextGen Research DataStream / NRDS streamflow simulation outputs for four Appalachian study sites. The repository must remain focused on NRDS/NextGen streamflow outputs and the minimum metadata needed to make those outputs reproducible.

The system will be manifest-driven and fail closed. Discovery will enumerate authoritative NRDS paths and object metadata, classification will approve only explicitly allowed streamflow outputs and small provenance files, and downloading will consume a validated manifest instead of hard-coded one-off URLs. No USGS or ERA5 acquisition pipeline will be implemented in this repository; those may appear only as future analysis scaffolding.

Primary approved product candidates are current NRDS output streams:

- `outputs/cfe_nom/v2.2_hydrofabric/.../ngen-run/outputs/troute/troute_output_*`
- `outputs/lstm_0/v2.2_hydrofabric/.../ngen-run/outputs/troute/troute_output_*`

All NWM v2/v3 products, forcing products, AORC, LDASIN, meteorological products, `routing_only`, `restarts`, `qkrig`, broad tarballs, and unknown artifacts are rejected by default.

## 2. Assumptions And Unknowns

Assumptions:

- The public NRDS bucket is `ciroh-community-ngen-datastream` in `us-east-1`.
- Public unauthenticated S3 listing is sufficient for discovery.
- `cfe_nom` and production `lstm_0` under `v2.2_hydrofabric` are the candidate NextGen/NRDS streamflow simulation streams.
- The four supplied hydrofabric feature IDs are the authoritative site identifiers for this project.
- Hydrofabric feature-to-VPU mapping must be discovered from authoritative hydrofabric or NRDS metadata, not inferred from geography.
- Site-level tidy outputs will be derived only after a file has passed product classification and the target feature ID is verified in the relevant output schema.

Unknowns that must be resolved during implementation:

- Exact VPU IDs for the four hydrofabric feature IDs.
- Whether all four feature IDs are present in the approved `cfe_nom` and `lstm_0` outputs.
- Exact current historical date ranges per approved stream, VPU, run type, cycle, and format.
- Whether historical NetCDF output files can be inspected safely with header-only or small-range reads before any larger download.
- Whether current NRDS naming or layout changes after the approved planning date.

## 3. Evidence-Backed Web Discovery Findings

Official and primary sources reviewed:

- NGIAB home: https://ngiab.ciroh.org/
- NRDS page: https://ngiab.ciroh.org/#/nrds
- DataStream browser: https://datastream.ciroh.org/
- DataStream browser index: https://datastream.ciroh.org/index.html
- NRDS visualizer: http://nrds.ciroh.org/
- CIROH Hub Research DataStream docs: https://hub.ciroh.org/docs/products/research-datastream/
- CIROH Hub April 2026 NRDS blog: https://hub.ciroh.org/blog/nextgen-research-datastream-april-2026/
- `ngen-datastream` repository: https://github.com/CIROH-UA/ngen-datastream
- NRDS status and metadata docs: https://github.com/CIROH-UA/ngen-datastream/blob/main/docs/nrds/STATUS_AND_METADATA.md
- Raw NRDS status and metadata docs: https://raw.githubusercontent.com/CIROH-UA/ngen-datastream/main/docs/nrds/STATUS_AND_METADATA.md
- DataStreamCLI repository: https://github.com/CIROH-UA/datastreamcli
- Forcing processor repository: https://github.com/CIROH-UA/forcingprocessor
- Hydrofabric design documentation: https://noaa-owp.github.io/hydrofabric/articles/02-design-deep-dive.html

Findings from official documentation and public listing:

- CIROH describes NRDS as daily NextGen-based hydrologic simulations made available through the Research DataStream and the NRDS browser.
- CIROH documentation and the NRDS metadata docs identify `outputs/cfe_nom/v2.2_hydrofabric/...` and `outputs/lstm_0/v2.2_hydrofabric/...` as current output stream locations.
- The same NRDS documentation identifies `forcings/v2.2_hydrofabric/...` as forcing output, which is out of scope and rejected.
- `outputs/routing_only/...` routes NWM v3 `q_lateral`; it is rejected because the project explicitly excludes NWM v2/v3 products.
- `outputs/restarts/...` contains restart-oriented products and is rejected.
- `outputs/qkrig/...` is based on USGS-IV kriging and is rejected because it is not an approved NextGen simulation output stream.
- The public DataStream browser references S3 bucket `ciroh-community-ngen-datastream` in region `us-east-1`.
- Public S3 listings showed root prefixes including `forcings/`, `outputs/`, `parameters/`, `realizations/`, `resources/`, `restarts/`, `status/`, and `v2.2_resources/`.
- Public S3 listings showed output stream roots including `outputs/cfe_nom/`, `outputs/lstm/`, `outputs/lstm_0/`, `outputs/qkrig/`, `outputs/routing_only/`, and `outputs/test/`.
- Public S3 listings showed current `cfe_nom` and `lstm_0` output layouts under `v2.2_hydrofabric` with run type folders, cycle folders, VPU folders, and `ngen-run/outputs/troute/` output files.
- Example approved current Parquet paths were observed by metadata-only listing/HEAD, such as `outputs/cfe_nom/v2.2_hydrofabric/ngen.20260522/short_range/00/VPU_05/ngen-run/outputs/troute/troute_output_202605220100.parquet`.
- Example historical NetCDF paths were observed by metadata-only listing/HEAD, such as `outputs/cfe_nom/v2.2_hydrofabric/ngen.20251125/short_range/00/VPU_05/ngen-run/outputs/troute/troute_output_202511250100.nc`.
- DataStream standard-directory documentation identifies `datastream-metadata/`, `datastream.env`, `conf_datastream.json`, `datastream_steps.txt`, realization files, execution metadata, and related small files as provenance/config artifacts.
- Broad run artifacts such as `ngen-run.tar.gz` and `merkdir.file` were observed, but they are rejected or ambiguous by default because they can contain broad run inputs/configuration and exceed safe proof-download thresholds.
- Hydrofabric documentation defines VPU concepts and hydrolocation mapping fields such as `vpuid`, `hl_reference`, and `hl_link`. The implementation must use authoritative hydrofabric/NRDS metadata for site-to-VPU mapping.

## 4. NRDS Access Pattern And Smallest Safe Proof-Of-Access Experiment

Access pattern:

- Use unauthenticated S3 ListObjectsV2 calls against `https://ciroh-community-ngen-datastream.s3.amazonaws.com`.
- Use delimiter-based listings to enumerate only prefixes and object metadata.
- Use HEAD or listing metadata for object size, ETag, last modified time, and key.
- Do not perform object-body downloads in Milestone 1.
- Build a manifest from approved object metadata and explicit site mapping evidence.

Smallest safe proof-of-access experiment:

1. List the bucket root with delimiter `/`.
2. Confirm `outputs/` exists.
3. List `outputs/` with delimiter `/`.
4. Confirm `outputs/cfe_nom/` and `outputs/lstm_0/` exist.
5. List one date prefix for each approved stream under `v2.2_hydrofabric`.
6. Confirm that VPU folders and `ngen-run/outputs/troute/` object metadata exist.
7. Record only object keys, sizes, ETags, last-modified timestamps, and source URLs.
8. Do not read object bodies.

Stop if access requires credentials, listing is disabled, product paths differ from documented layout, or candidate objects cannot be confidently classified.

## 5. Mapping Strategy For The Four Hydrofabric Feature IDs

Canonical sites:

| Site | USGS Gage ID | Hydrofabric Feature ID |
| --- | --- | --- |
| South Fork New River near Jefferson, NC | `03161000` | `6892192` |
| New River near Galax, VA | `03164000` | `6887572` |
| Watauga River near Sugar Grove, NC | `03479000` | `19743430` |
| Watauga River at Elizabethton, TN | `03486000` | `19745222` |

Mapping steps:

1. Store the four site records exactly in `configs/sites.yaml`.
2. Discover authoritative hydrofabric feature-to-VPU mapping from hydrofabric/NRDS metadata, using documented VPU or hydrolocation fields where available.
3. Record mapping evidence for each site, including source URL or object key, metadata version, field names used, and timestamp of discovery.
4. Verify that each discovered VPU appears under the approved NRDS output streams.
5. Verify that each target hydrofabric feature ID is present in the approved output file schema or index before marking the site downloadable.
6. Keep `discovered_vpu_id` null and `mapping_status` non-final until evidence is recorded.

Do not infer VPU IDs from the site state, gage ID, river name, or approximate geography. Stop if any feature ID does not map cleanly.

## 6. Recommended Repo Tree

The implementation should eventually use this structure, but only the files listed in section 16 are created before Goal Mode implementation begins.

```text
.
├── README.md
├── pyproject.toml
├── configs/
│   ├── defaults.yaml
│   └── sites.yaml
├── docs/
│   ├── goal_contract.md
│   ├── implementation_plan.md
│   ├── product_classifier_policy.md
│   └── safety_constraints.md
├── manifests/
├── reports/
├── src/
│   └── nextgen_hydra/
│       ├── cli.py
│       ├── classifier.py
│       ├── config.py
│       ├── discovery.py
│       ├── download.py
│       ├── inventory.py
│       ├── manifest.py
│       ├── provenance.py
│       ├── qc.py
│       ├── schemas.py
│       ├── tidy.py
│       └── io/
│           └── s3.py
└── tests/
```

Data directories should be ignored by git when created later:

- `data/raw/`
- `data/tidy/`
- `data/inventory/`
- `data/provenance/`
- `data/cache/`

## 7. Config Design

### `configs/sites.yaml`

Purpose: canonical site list and mapping state.

Required fields:

- `site_id`
- `name`
- `usgs_gage_id`
- `hydrofabric_feature_id`
- `discovered_vpu_id`
- `mapping_status`
- `mapping_evidence`
- `notes`

Initial `discovered_vpu_id` values remain null. Initial `mapping_status` is `unmapped`.

### `configs/defaults.yaml`

Purpose: safe defaults for discovery, classification, manifest building, and future downloads.

Required fields:

- Public S3 bucket and region.
- Public S3 base URL.
- DataStream and NRDS browser URLs.
- Hydrofabric version `v2.2_hydrofabric`.
- Candidate streams `cfe_nom` and `lstm_0`.
- Approved troute path template.
- Approved metadata filenames.
- Reject prefixes and reject tokens.
- Safety thresholds.
- Default output directory names.
- Dry-run-first behavior.

### Manifest Schema

Manifest records should be normalized JSONL or YAML with one object per downloadable artifact.

Required fields:

- `manifest_version`
- `created_at_utc`
- `site_id`
- `usgs_gage_id`
- `hydrofabric_feature_id`
- `vpu_id`
- `stream`
- `hydrofabric_version`
- `run_date`
- `run_type`
- `cycle`
- `object_key`
- `public_url`
- `format`
- `size_bytes`
- `etag`
- `last_modified`
- `classification`
- `classification_reason`
- `mapping_evidence_ref`
- `source_listing_ref`
- `approved_for_download`

The downloader must reject manifest rows where `approved_for_download` is not true or where classification is not exactly approved.

### Provenance Schema

Required fields:

- `event_id`
- `event_type`
- `timestamp_utc`
- `command`
- `config_files`
- `manifest_path`
- `source_bucket`
- `source_key`
- `source_etag`
- `source_last_modified`
- `source_size_bytes`
- `local_path`
- `local_sha256`
- `classifier_version`
- `decision`
- `reason`
- `software_versions`

### Data Catalog Schema

Required fields for tidy outputs:

- `site_id`
- `usgs_gage_id`
- `hydrofabric_feature_id`
- `vpu_id`
- `stream`
- `run_date`
- `run_type`
- `cycle`
- `source_format`
- `tidy_path`
- `row_count`
- `start_time_utc`
- `end_time_utc`
- `time_step_seconds`
- `flow_variable`
- `flow_units`
- `missing_count`
- `qc_status`
- `source_manifest_ref`

## 8. Product Classifier Policy

The classifier must fail closed. Anything not explicitly approved is rejected or ambiguous and cannot be downloaded.

### Approved

Approved simulation outputs:

- `outputs/cfe_nom/v2.2_hydrofabric/.../ngen-run/outputs/troute/troute_output_*.parquet`
- `outputs/cfe_nom/v2.2_hydrofabric/.../ngen-run/outputs/troute/troute_output_*.nc`
- `outputs/lstm_0/v2.2_hydrofabric/.../ngen-run/outputs/troute/troute_output_*.parquet`
- `outputs/lstm_0/v2.2_hydrofabric/.../ngen-run/outputs/troute/troute_output_*.nc`

Historical `.nc` files require a separate safe schema/header validation step before any large download.

Approved metadata/provenance files are only small files under the same approved `cfe_nom` or `lstm_0` VPU/run prefix:

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

### Rejected

Reject by prefix, token, filename, or classification:

- `forcings/`
- NWM v2/v3 products or any key containing NWM as a product source.
- AORC products.
- LDASIN files.
- Meteorological forcing products, including precipitation, temperature, pressure, humidity, and wind.
- `outputs/routing_only/`
- `outputs/restarts/`
- `restarts/`
- `outputs/qkrig/`
- `ngen-run.tar.gz`
- `merkdir.file`
- Broad run-input artifacts.
- Unknown tarballs, archives, bundles, and cache files.
- Any product requiring a forcing download to obtain streamflow outputs.

Run type path tokens such as `short_range`, `medium_range`, or `analysis_assim_extend` are not sufficient for approval. Only the exact approved troute output path under an approved stream can pass.

### Ambiguous

Classify as ambiguous:

- Anything outside the exact allowlist.
- Unknown extensions.
- Missing S3 size.
- Missing ETag.
- Oversized objects.
- `outputs/lstm/` until explicitly approved.
- Any path where stream, hydrofabric version, run date, run type, cycle, VPU, output directory, filename, or extension cannot be parsed.

### Fail-Closed Behavior

- Ambiguous artifacts are not downloaded.
- Rejected artifacts are not downloaded.
- Missing metadata prevents download.
- Oversized artifacts require explicit user approval.
- The downloader consumes only a validated manifest.
- The downloader never approves a path by substring match alone.

### Examples

Accepted example:

```text
outputs/cfe_nom/v2.2_hydrofabric/ngen.20260522/short_range/00/VPU_05/ngen-run/outputs/troute/troute_output_202605220100.parquet
```

Rejected examples:

```text
forcings/v2.2_hydrofabric/ngen.20260522/short_range/00/VPU_05/...
outputs/routing_only/v2.2_hydrofabric/ngen.20260522/...
outputs/qkrig/qkrig.20260522/...
outputs/cfe_nom/v2.2_hydrofabric/ngen.20260522/short_range/00/VPU_05/ngen-run.tar.gz
outputs/cfe_nom/v2.2_hydrofabric/ngen.20260522/short_range/00/VPU_05/merkdir.file
```

Ambiguous example:

```text
outputs/lstm/v2.2_hydrofabric/ngen.20260213/short_range/00/VPU_05/ngen-run/outputs/troute/troute_output_202602130100.parquet
```

## 9. CLI Design

Planned commands:

- `discover-nrds`: list public NRDS prefixes and object metadata without object-body downloads.
- `classify-products`: classify discovered keys as approved, rejected, or ambiguous.
- `build-manifest`: build a manifest for approved stream/site/date/VPU combinations.
- `validate-manifest`: validate schema, required metadata, classification decisions, and safety thresholds.
- `download`: dry-run first, then download only approved manifest rows after explicit approval.
- `inventory`: inventory local raw files and compare against manifest and provenance.
- `tidy`: transform approved raw outputs into site-level time series.
- `qc-report`: generate completeness, coverage, classification, and provenance reports.

Every command should support structured logs, explicit config paths, and a dry-run mode where relevant.

## 10. End-To-End Workflow

1. Load `configs/sites.yaml` and `configs/defaults.yaml`.
2. Run discovery with no object-body downloads.
3. Build a discovery inventory of public S3 keys and metadata.
4. Classify every discovered object.
5. Resolve feature-to-VPU mapping from authoritative hydrofabric/NRDS metadata.
6. Build a manifest for approved artifacts only.
7. Validate the manifest and fail on rejected or ambiguous rows.
8. Run downloader in dry-run mode.
9. After explicit approval, download a small approved date slice within safety thresholds.
10. Inventory downloaded files and verify hashes, sizes, ETags, and provenance.
11. Transform approved raw outputs into tidy site-level time series.
12. Produce QC and provenance reports.
13. Add only future scaffolding for USGS bias evaluation and missing-data imputation.

## 11. Testing Strategy

Unit tests:

- Classifier accepts only exact approved output and metadata patterns.
- Classifier rejects all forcing, NWM, AORC, LDASIN, routing-only, restart, qkrig, tarball, and broad artifact examples.
- Classifier returns ambiguous for unknown paths, unknown extensions, missing size, missing ETag, and oversized objects.
- Manifest schema validation rejects missing required fields and non-approved classifications.
- Config loading validates the four canonical site records and null initial VPU fields.

Integration tests with fixtures:

- Simulated S3 listing pages are parsed into discovery records.
- Discovery records flow through classifier and manifest builder.
- Downloader dry-run reports exact actions without writing data files.
- Inventory compares fixture files to manifest rows.
- Tidy transform handles fixture Parquet and NetCDF-like schemas only after classifier approval.

Safety tests:

- Downloader refuses to run without a validated manifest.
- Downloader refuses ambiguous and rejected rows.
- Downloader enforces object and total byte thresholds.
- Milestone 1 mode refuses all object-body downloads.

## 12. Milestone Plan

### Milestone 1: Discovery-Only Proof Of Access

- Implement config loading, S3 listing, discovery records, and classifier fixtures.
- Perform no object-body downloads.
- Acceptance: bucket root, approved stream roots, and candidate output metadata can be listed and recorded.

### Milestone 2: Manifest For Four Sites

- Resolve feature-to-VPU mapping with evidence.
- Verify candidate outputs exist for mapped VPUs.
- Acceptance: manifest rows exist only for approved objects and mapped sites.

### Milestone 3: Dry-Run Downloader

- Implement idempotent dry-run downloader against a validated manifest.
- Acceptance: downloader reports exact planned downloads and refuses unsafe rows.

### Milestone 4: Real Download Of A Small Approved Date Slice

- After explicit approval, download only a small approved date slice.
- Enforce 25 MB/object and 100 MB total cap unless separately approved.
- Acceptance: local files match manifest size, ETag where applicable, and SHA256 provenance.

### Milestone 5: Full Historical Download After Approval

- Expand manifest by approved date range and stream after approval.
- Acceptance: resumable downloads, inventory, and provenance cover every approved artifact.

### Milestone 6: Tidy Outputs And QC Report

- Transform raw approved outputs into site-level tidy time series.
- Acceptance: tidy Parquet outputs and QC reports include coverage, missingness, units, and source provenance.

### Milestone 7: Bias/Imputation Scaffolding Only

- Add interfaces for later USGS bias evaluation and missing-data imputation.
- Do not implement USGS or ERA5 acquisition.
- Acceptance: scaffolding documents inputs expected from external pipelines.

## 13. Exact Coding Tasks For Implementation Mode

Expected files to add after approval:

- `pyproject.toml`
- `README.md`
- `src/nextgen_hydra/config.py`
- `src/nextgen_hydra/discovery.py`
- `src/nextgen_hydra/classifier.py`
- `src/nextgen_hydra/manifest.py`
- `src/nextgen_hydra/download.py`
- `src/nextgen_hydra/inventory.py`
- `src/nextgen_hydra/tidy.py`
- `src/nextgen_hydra/qc.py`
- `src/nextgen_hydra/provenance.py`
- `src/nextgen_hydra/schemas.py`
- `src/nextgen_hydra/cli.py`
- `tests/`

Inputs:

- `configs/sites.yaml`
- `configs/defaults.yaml`
- Public S3 listing metadata from `ciroh-community-ngen-datastream`
- Authoritative hydrofabric/NRDS mapping metadata

Outputs:

- Discovery inventory
- Product classification report
- Validated manifest
- Dry-run download plan
- Raw inventory
- Tidy site-level Parquet outputs
- QC report
- Provenance log

Acceptance criteria:

- No implementation downloads forcing, NWM v2/v3, AORC, LDASIN, routing-only, restart, qkrig, tarball, or broad run-input artifacts.
- Manifest validation fails closed on ambiguity.
- Downloader runs only from a validated manifest.
- Milestone 1 performs no object-body downloads.
- Proof downloads remain within explicit safety thresholds.
- Site VPU mapping is evidence-backed.
- Tidy outputs are traceable to manifest rows and source object metadata.

## 14. Recommended Subagent Prompts

Agent A - NRDS Documentation and Web Discovery:

> Find authoritative evidence for NRDS structure, public access pattern, output products, metadata, public S3/HTTP/index layout, file formats, date coverage, and how the four hydrofabric feature IDs map to downloadable data. Do not download object bodies.

Agent B - Data Product Classifier:

> Design fail-closed include, exclude, and ambiguous rules for NRDS products. Ensure NWM v2/v3, forcing, AORC, LDASIN, meteorological products, routing_only, restarts, qkrig, and broad artifacts are rejected by default.

Agent C - Repo Architecture:

> Propose the Python package layout, dependency approach, configs, CLI, tests, logging, provenance, and data handling rules for a manifest-driven NRDS streamflow acquisition system.

Agent D - Downloader Engineering:

> Plan dry-run-first, idempotent, resumable, size-limited, classifier-gated download behavior. Avoid credentials unless official evidence proves they are required.

Agent E - Tidy Hydrology Data Model:

> Plan site-level streamflow time-series schema, timestamp handling, units, feature IDs, model run IDs, missing flags, Parquet partitioning, and data catalog entries.

Agent F - QC and Provenance:

> Plan inventory, completeness checks, provenance schema, reproducibility metadata, and human-readable QC reporting.

Agent G - Future Analysis:

> Plan only future scaffolding for USGS bias evaluation and missing-data imputation. Do not implement USGS or ERA5 acquisition.

## 15. Stop Conditions

Stop and ask for approval if:

- NRDS access pattern is ambiguous or changes from documented public S3 listing.
- NRDS access requires credentials or paid access.
- Download would require NWM v2/v3 or forcing products.
- Hydrofabric IDs do not map cleanly to NRDS outputs.
- VPUs, date ranges, model stream names, or formats cannot be verified.
- File formats require large downloads to inspect.
- Product classification is ambiguous.
- Any download exceeds the proposed safe threshold.
- The plan drifts into USGS acquisition, ERA5 acquisition, forecasting, or modeling.
- Current documentation is insufficient to proceed safely.

## 16. Files That Should Be Created After Approval

These durable planning and configuration files should be created before Goal Mode implementation:

- `docs/implementation_plan.md`
- `docs/safety_constraints.md`
- `docs/product_classifier_policy.md`
- `docs/goal_contract.md`
- `configs/sites.yaml`
- `configs/defaults.yaml`
