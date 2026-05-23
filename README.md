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

Optional tidy transforms for real Parquet/NetCDF files require:

```bash
.venv/bin/python -m pip install '.[data]'
```

## Safety Status

Current `configs/sites.yaml` intentionally has `discovered_vpu_id: null` for
all four sites. Manifest creation and downloads are blocked until authoritative
feature-to-VPU mapping evidence is added.

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
evidence in `configs/sites.yaml`:

```bash
.venv/bin/nextgen-hydra build-manifest \
  --discovery reports/classification.jsonl \
  --output manifests/manifest.jsonl

.venv/bin/nextgen-hydra validate-manifest \
  --manifest manifests/manifest.jsonl
```

Dry-run downloader plan:

```bash
.venv/bin/nextgen-hydra download \
  --manifest manifests/manifest.jsonl \
  --plan-output reports/download_plan.jsonl
```

Real downloads require `--execute` and an explicit `--approval-id`. Milestone 1
execution is always refused.

```bash
.venv/bin/nextgen-hydra download \
  --manifest manifests/manifest.jsonl \
  --execute \
  --approval-id APPROVED_SMALL_SLICE_YYYYMMDD
```

Inventory, tidy, and QC commands consume validated manifests and local raw
files:

```bash
.venv/bin/nextgen-hydra inventory \
  --manifest manifests/manifest.jsonl \
  --output data/inventory/inventory.jsonl

.venv/bin/nextgen-hydra tidy \
  --manifest manifests/manifest.jsonl \
  --feature-id-column feature_id \
  --time-column time \
  --flow-column streamflow \
  --flow-units "m3 s-1"

.venv/bin/nextgen-hydra qc-report \
  --manifest manifests/manifest.jsonl \
  --inventory data/inventory/inventory.jsonl \
  --catalog data/tidy/catalog.jsonl
```

## Tests

```bash
.venv/bin/python -m pytest
```

The test suite verifies classifier allow/reject/ambiguous behavior, manifest
validation, dry-run downloader behavior, milestone-1 download refusal, S3
listing parsing, config validation, tidy schema normalization, and QC summaries.
