# NextGen Hydra

NextGen Hydra is a reproducible, manifest-driven Python CLI for safely
discovering, classifying, downloading, inventorying, and preparing historical
NRDS NextGen streamflow simulation outputs for the four configured Appalachian
study sites.

The repository is fail-closed by design. It approves only exact NRDS
`troute_output_*` streamflow outputs and the small metadata/provenance files
listed in `configs/defaults.yaml`. NWM v2/v3, forcings, AORC, LDASIN,
meteorological products, routing-only outputs, restarts, qkrig, tarballs, and
broad run artifacts are rejected or marked ambiguous.

## Install

```bash
python3 -m venv .venv
.venv/bin/python -m pip install '.[dev]'
```

Optional schema inspection and tidy transforms for real Parquet/NetCDF files require:

```bash
.venv/bin/python -m pip install '.[data]'
```

Optional public API and React portal dependencies:

```bash
.venv/bin/python -m pip install '.[web]'
```

## Safety Status

Current `configs/sites.yaml` has verified VPU mappings for all four sites:
`03161000` and `03164000` map to `VPU_05`; `03479000` and `03486000` map to
`VPU_06`. Evidence is recorded in `docs/vpu_mapping_evidence.md`.

Milestone 2 is complete and `validate-config` now requires
`mapped_site_count == 4`. Milestone 3 builds the classifier-gated manifest from
metadata-only listings for the mapped VPUs.

Milestone 1 discovery uses public S3 `ListObjectsV2` metadata only. It does not
download object bodies.

## CLI Workflow

Validate project docs/configs:

```bash
.venv/bin/nextgen-hydra validate-config
```

Run a tightly limited no-download proof of NRDS metadata access:

```bash
.venv/bin/nextgen-hydra discover-nrds \
  --output reports/discovery_smoke.jsonl \
  --max-date-prefixes 1 \
  --max-run-types 1 \
  --max-cycles 1 \
  --max-vpus 1 \
  --max-objects-per-prefix 5
```

Classify a discovery inventory:

```bash
.venv/bin/nextgen-hydra classify-products \
  --input reports/discovery_smoke.jsonl \
  --output reports/classification.jsonl
```

Build and validate a manifest only after the four site VPUs are mapped with
evidence in `configs/sites.yaml` and explicit approval is given for Milestone 3.
When `--discovery` is omitted, `build-manifest` lists only the mapped VPUs and
approved troute/metadata prefixes; no object bodies are downloaded:

```bash
.venv/bin/nextgen-hydra build-manifest \
  --run-type short_range \
  --cycle 00 \
  --output manifests/manifest.jsonl \
  --discovery-output reports/manifest_discovery.jsonl \
  --summary-output reports/manifest_summary.json \
  --summary-markdown reports/manifest_summary.md

.venv/bin/nextgen-hydra validate-manifest \
  --manifest manifests/manifest.jsonl
```

Milestone 4 NRDS pre-download workflow:

1. Validate config.
2. Validate the manifest against `configs/sites.yaml`.
3. Run a dry-run download plan.
4. Execute only after a concrete `--approval-id` is available.
5. Inventory downloaded raw files.
6. Download approved hydrofabric resource GPKGs through the separate resource
   workflow.
7. Resolve the site crosswalk from configured COMIDs to troute feature IDs.
8. Inspect the raw troute schema with `configs/site_crosswalk.yaml`.
9. Run tidy only after schema inspection and units are approved.

Validate and dry-run:

```bash
.venv/bin/nextgen-hydra validate-config

.venv/bin/nextgen-hydra validate-manifest \
  --manifest manifests/manifest.jsonl

.venv/bin/nextgen-hydra download \
  --manifest manifests/manifest.jsonl \
  --plan-output reports/download_plan.jsonl \
  --summary-output reports/milestone4_download_summary.json \
  --summary-markdown reports/milestone4_download_summary.md
```

Real downloads require an explicit concrete `--approval-id`; without it, the
command remains dry-run-only. `--execute` is still accepted for compatibility
but is implied by `--approval-id`. Milestone 1 execution is always refused.

```bash
.venv/bin/nextgen-hydra download \
  --manifest manifests/manifest.jsonl \
  --approval-id APPROVED_SMALL_SLICE_YYYYMMDD \
  --plan-output reports/download_plan.jsonl \
  --summary-output reports/milestone4_download_summary.json \
  --summary-markdown reports/milestone4_download_summary.md
```

Execution writes the plan to `reports/download_plan.jsonl`, provenance to
`reports/download_provenance.jsonl`, summaries to
`reports/milestone4_download_summary.json` and
`reports/milestone4_download_summary.md`, and an inventory to the configured
inventory directory. Do not commit downloaded files from `data/raw/`.

Inventory and schema inspection:

```bash
.venv/bin/nextgen-hydra inventory \
  --manifest manifests/manifest.jsonl \
  --output data/inventory/inventory.jsonl
```

Hydrofabric resource workflow for site crosswalk resolution. This is separate
from NRDS output/metadata downloads and allows only the configured
`VPU_05`/`VPU_06` geopackages:

```bash
.venv/bin/nextgen-hydra build-resource-manifest \
  --output manifests/resource_manifest.jsonl \
  --summary-output reports/resource_manifest_summary.json \
  --summary-markdown reports/resource_manifest_summary.md

.venv/bin/nextgen-hydra download-resources \
  --manifest manifests/resource_manifest.jsonl \
  --plan-output reports/resource_download_plan.jsonl \
  --summary-output reports/resource_download_summary.json \
  --summary-markdown reports/resource_download_summary.md
```

Real resource downloads also require a concrete approval ID:

```bash
.venv/bin/nextgen-hydra download-resources \
  --manifest manifests/resource_manifest.jsonl \
  --approval-id APPROVED_RESOURCE_DOWNLOAD_YYYYMMDD \
  --plan-output reports/resource_download_plan.jsonl \
  --summary-output reports/resource_download_summary.json \
  --summary-markdown reports/resource_download_summary.md
```

Resolve the crosswalk only after the approved GPKGs are present:

```bash
.venv/bin/nextgen-hydra resolve-site-crosswalk \
  --sites configs/sites.yaml \
  --resource-dir data/resources \
  --output configs/site_crosswalk.yaml \
  --report reports/site_crosswalk_report.json
```

Inspect raw troute schema with resolved troute feature IDs:

```bash
.venv/bin/nextgen-hydra inspect-schema \
  --manifest manifests/manifest.jsonl \
  --raw-dir data/raw \
  --site-crosswalk configs/site_crosswalk.yaml \
  --output reports/schema_inspection.json \
  --markdown reports/schema_inspection.md
```

Run tidy only after `reports/schema_inspection.json` has status `pass` and the
feature/time/flow column choices and streamflow units are approved:

```bash
.venv/bin/nextgen-hydra tidy \
  --manifest manifests/manifest.jsonl \
  --raw-dir data/raw \
  --catalog-output data/tidy/catalog.jsonl \
  --site-crosswalk configs/site_crosswalk.yaml \
  --feature-id-column feature_id \
  --time-column time \
  --flow-column flow \
  --flow-units "m3 s-1"
```

QC consumes the manifest, inventory, tidy catalog, schema inspection, and
download summary:

```bash
.venv/bin/nextgen-hydra qc-report \
  --manifest manifests/manifest.jsonl \
  --inventory data/inventory/inventory.jsonl \
  --catalog data/tidy/catalog.jsonl \
  --schema-inspection reports/schema_inspection.json \
  --download-summary reports/milestone4_download_summary.json
```

## Public Portal

The public portal starts as local-file-backed FastAPI plus React/Vite. It serves
only CLI-produced artifacts and cached tidy/export files; it has no public route
that can run discovery, resource download, NRDS download, approval submission, or
crosswalk resolution. The file contracts are documented in
`docs/public_api_file_contracts.md`.

Run the API:

```bash
.venv/bin/python -m uvicorn apps.api.main:app --reload --host 127.0.0.1 --port 8000
```

Run the web app:

```bash
cd apps/web
npm install
npm run dev
```

## Tests

```bash
.venv/bin/python -m pytest
```

The test suite verifies classifier allow/reject/ambiguous behavior, manifest
validation, dry-run downloader behavior, milestone-1 download refusal, S3
listing parsing, config validation, tidy schema normalization, and QC summaries.
