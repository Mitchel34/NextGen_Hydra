"""Future workflow scaffolding that explicitly avoids acquisition."""

from __future__ import annotations

from pathlib import Path


FUTURE_SCAFFOLD_MARKDOWN = """# Future External Analysis Inputs

This project does not acquire USGS, ERA5, AORC, forcing, NWM v2/v3, or
meteorological products.

Future bias evaluation may consume externally supplied USGS observation files
with documented provenance, units, timestamps, and site IDs.

Future imputation experiments may consume externally supplied NextGen tidy
outputs, externally supplied ERA5-derived covariates, and externally supplied
USGS observations. Acquisition, forecasting, and statistical modeling remain
outside this repository until a separate approved contract changes scope.
"""


def write_future_scaffold(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(FUTURE_SCAFFOLD_MARKDOWN, encoding="utf-8")
