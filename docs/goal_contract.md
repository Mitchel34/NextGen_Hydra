# Goal Contract

## Persistent Objective

Build a reproducible, Python-based, manifest-driven data acquisition and preparation system for historical NextGen Research DataStream / NRDS streamflow simulation outputs for four Appalachian study sites.

The system must answer:

- What historical NextGen/NRDS streamflow data is available now for the four sites?
- What identifiers, paths, date ranges, VPUs, model stream names, and file formats are needed to download it?
- Can the system safely download only approved NextGen/NRDS simulation outputs, not NWM v2/v3 or forcing datasets?
- Can the system create clean, analysis-ready site-level streamflow time series?
- Later, can these outputs be compared with externally supplied USGS observations to estimate bias?
- Later, can externally supplied NextGen outputs, ERA5 covariates, and USGS observations support missing-data imputation models?

## In Scope

- NRDS discovery through public metadata listings.
- Product classification.
- Manifest building and validation.
- Dry-run-first, classifier-gated downloading.
- Raw inventory.
- Raw-to-tidy streamflow transformation.
- QC reporting.
- Provenance logging.
- Future scaffolding for bias and imputation workflows.

## Out Of Scope

- USGS acquisition pipeline implementation.
- ERA5 acquisition pipeline implementation.
- NWM v2/v3 acquisition.
- Forcing acquisition.
- AORC, LDASIN, meteorological forcing, and forecast-system data acquisition.
- Forecasting or statistical modeling implementation.

## Milestones

1. Discovery-only proof of access.
2. Manifest for the four sites.
3. Dry-run downloader.
4. Real download of a small approved date slice after explicit approval.
5. Full historical download after explicit approval.
6. Tidy outputs and QC report.
7. Bias/imputation scaffolding only.

## Verification Criteria

- Public NRDS access pattern is verified from official documentation and public S3 listing metadata.
- Approved stream names, hydrofabric version, output path pattern, date ranges, VPU IDs, and file formats are evidence-backed.
- Each of the four hydrofabric feature IDs is mapped to a VPU using authoritative metadata.
- Product classifier accepts only approved troute streamflow outputs and small approved metadata/provenance files.
- Product classifier rejects NWM v2/v3, forcing, AORC, LDASIN, meteorological, routing-only, restart, qkrig, tarball, and broad artifact paths.
- Manifest rows include source key, URL, size, ETag, last modified time, classification reason, mapping evidence, and approval state.
- Downloader refuses to run without a validated manifest.
- Downloader dry run reports planned actions without writing data files.
- Real proof downloads stay within 25 MB/object and 100 MB total unless explicitly approved.
- Tidy outputs are traceable to manifest rows and source provenance.
- QC reports summarize coverage, missingness, units, inventory, and provenance completeness.

## Completion Criteria

The Goal Mode work is complete when:

- The four canonical sites are represented in config with evidence-backed mappings.
- Approved NRDS availability for those sites is documented in a validated manifest.
- The classifier and manifest validator enforce fail-closed behavior.
- A dry-run downloader can show exactly what would be downloaded.
- After explicit approval, a small approved date slice can be downloaded and inventoried.
- Tidy site-level streamflow outputs can be generated from approved raw files.
- QC and provenance reports can be generated.
- Future bias/imputation scaffolding exists without implementing USGS or ERA5 acquisition.

## Stop Conditions

Stop and ask for approval if:

- NRDS access pattern is ambiguous or changes.
- NRDS access requires credentials or paid access.
- Download would require NWM v2/v3 or forcing products.
- Hydrofabric IDs do not map cleanly to NRDS outputs.
- VPUs, date ranges, model stream names, or formats cannot be verified.
- File formats require large downloads to inspect.
- Product classification is ambiguous.
- Any download exceeds the configured safe threshold.
- The work would drift into USGS acquisition, ERA5 acquisition, forecasting, or modeling.
- Current documentation is insufficient to proceed safely.
