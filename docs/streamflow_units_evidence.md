# Streamflow Units Evidence

Status: documented

Variable: `flow`

Documented units: `m3 s-1`

The approved local artifacts do not carry column-level units in the downloaded
Parquet schema. The units gate is documented from official NOAA-OWP/t-route
source plus approved local provenance that links the downloaded files to t-route
output conversion.

Evidence:

- NOAA-OWP/t-route `src/bmi_troute.py` maps
  `channel_exit_water_x-section__volume_flow_rate` to `streamflow_cms` with
  units `m3 s-1`.
- NOAA-OWP/t-route `src/troute-nwm/src/nwm_routing/output.py` maps t-route
  parquet `streamflow` output units to `m3/s`, equivalent to `m3 s-1`.
- Approved local `datastream_steps.txt` records that the downloaded
  `outputs/troute` Parquet files were produced by running
  `datastreamcli/nc2parquet.py` over the t-route output directory.

This evidence supports using `m3 s-1` as the canonical tidy/export units string
for the approved slice.
