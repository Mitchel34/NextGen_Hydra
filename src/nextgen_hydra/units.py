"""Streamflow units evidence gate for tidy transforms."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class UnitsError(RuntimeError):
    """Raised when streamflow units are not documented enough for tidy output."""


def load_streamflow_units(path: Path) -> dict[str, Any]:
    """Load the streamflow units evidence file."""

    if not path.is_file():
        raise UnitsError(f"streamflow units file does not exist: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise UnitsError(f"streamflow units file must contain a mapping: {path}")
    if int(data.get("version") or 0) != 1:
        raise UnitsError("streamflow units file version must be 1")
    return data


def require_documented_flow_units(
    *,
    units_config: dict[str, Any],
    flow_column: str,
    requested_units: str,
) -> str:
    """Return documented units or fail closed."""

    status = str(units_config.get("status") or "missing")
    variable = str(units_config.get("variable") or "")
    units = str(units_config.get("units") or "")
    evidence = units_config.get("evidence")

    errors: list[str] = []
    if status != "documented":
        errors.append(f"status is {status!r}, expected 'documented'")
    if variable != flow_column:
        errors.append(f"variable is {variable!r}, expected {flow_column!r}")
    if not units:
        errors.append("units is missing")
    if requested_units and units and requested_units != units:
        errors.append(
            f"requested --flow-units {requested_units!r} does not match documented units {units!r}"
        )
    if not isinstance(evidence, list) or not evidence:
        errors.append("authoritative evidence is missing")
    else:
        for index, item in enumerate(evidence, start=1):
            if not isinstance(item, dict):
                errors.append(f"evidence item {index} must be a mapping")
                continue
            if not item.get("source") or not item.get("citation"):
                errors.append(
                    f"evidence item {index} must include source and citation"
                )

    if errors:
        raise UnitsError("streamflow units are not documented:\n" + "\n".join(errors))
    return units
