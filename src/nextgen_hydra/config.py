"""Configuration loading and project guardrails."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


REQUIRED_PROJECT_FILES = (
    "docs/goal_contract.md",
    "docs/implementation_plan.md",
    "docs/safety_constraints.md",
    "docs/product_classifier_policy.md",
    "configs/sites.yaml",
    "configs/defaults.yaml",
)

CANONICAL_FEATURE_IDS = {
    "south_fork_new_river_near_jefferson_nc": ("03161000", 6892192),
    "new_river_near_galax_va": ("03164000", 6887572),
    "watauga_river_near_sugar_grove_nc": ("03479000", 19743430),
    "watauga_river_at_elizabethton_tn": ("03486000", 19745222),
}


class ConfigError(ValueError):
    """Raised when project configuration violates the contract."""


@dataclass(frozen=True)
class Site:
    site_id: str
    name: str
    usgs_gage_id: str
    hydrofabric_feature_id: int
    discovered_vpu_id: str | None
    mapping_status: str
    mapping_evidence: Any
    notes: str | None = None

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> "Site":
        required = {
            "site_id",
            "name",
            "usgs_gage_id",
            "hydrofabric_feature_id",
            "discovered_vpu_id",
            "mapping_status",
            "mapping_evidence",
            "notes",
        }
        missing = sorted(required - raw.keys())
        if missing:
            raise ConfigError(f"site record missing required fields: {missing}")
        return cls(
            site_id=str(raw["site_id"]),
            name=str(raw["name"]),
            usgs_gage_id=str(raw["usgs_gage_id"]),
            hydrofabric_feature_id=int(raw["hydrofabric_feature_id"]),
            discovered_vpu_id=(
                None
                if raw["discovered_vpu_id"] in (None, "")
                else str(raw["discovered_vpu_id"])
            ),
            mapping_status=str(raw["mapping_status"]),
            mapping_evidence=raw["mapping_evidence"],
            notes=None if raw["notes"] is None else str(raw["notes"]),
        )

    @property
    def is_mapped(self) -> bool:
        return (
            self.discovered_vpu_id is not None
            and self.mapping_status in {"mapped", "verified", "downloadable"}
            and self.mapping_evidence not in (None, "")
        )


def assert_required_project_files(root: Path) -> None:
    missing = [name for name in REQUIRED_PROJECT_FILES if not (root / name).is_file()]
    if missing:
        raise ConfigError(
            "required project files are missing; stopping immediately: "
            + ", ".join(missing)
        )


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"configuration file does not exist: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ConfigError(f"configuration file must contain a mapping: {path}")
    return data


def load_defaults(path: Path) -> dict[str, Any]:
    defaults = load_yaml(path)
    for section in ("nrds", "metadata", "classifier", "safety", "download", "paths"):
        if section not in defaults or not isinstance(defaults[section], dict):
            raise ConfigError(f"defaults missing required section: {section}")
    nrds = defaults["nrds"]
    if nrds.get("hydrofabric_version") != "v2.2_hydrofabric":
        raise ConfigError("hydrofabric_version must be v2.2_hydrofabric")
    streams = nrds.get("candidate_streams")
    if streams != ["cfe_nom", "lstm_0"]:
        raise ConfigError("candidate_streams must be exactly ['cfe_nom', 'lstm_0']")
    return defaults


def load_sites(path: Path) -> list[Site]:
    raw = load_yaml(path)
    if raw.get("version") != 1:
        raise ConfigError("sites config version must be 1")
    records = raw.get("sites")
    if not isinstance(records, list):
        raise ConfigError("sites config must contain a sites list")
    sites = [Site.from_mapping(record) for record in records]
    validate_canonical_sites(sites)
    return sites


def validate_canonical_sites(sites: list[Site]) -> None:
    if len(sites) != 4:
        raise ConfigError(f"expected exactly 4 canonical sites, found {len(sites)}")
    seen = {site.site_id for site in sites}
    if seen != set(CANONICAL_FEATURE_IDS):
        raise ConfigError(
            "site IDs do not match canonical project sites: "
            + ", ".join(sorted(seen))
        )
    for site in sites:
        expected_gage, expected_feature_id = CANONICAL_FEATURE_IDS[site.site_id]
        if site.usgs_gage_id != expected_gage:
            raise ConfigError(
                f"{site.site_id} has USGS gage {site.usgs_gage_id}, "
                f"expected {expected_gage}"
            )
        if site.hydrofabric_feature_id != expected_feature_id:
            raise ConfigError(
                f"{site.site_id} has feature ID {site.hydrofabric_feature_id}, "
                f"expected {expected_feature_id}"
            )


def proof_download_max_object_bytes(defaults: dict[str, Any]) -> int:
    mb = defaults["safety"]["proof_download_max_object_mb"]
    return int(mb) * 1024 * 1024


def proof_download_max_total_bytes(defaults: dict[str, Any]) -> int:
    mb = defaults["safety"]["proof_download_max_total_mb"]
    return int(mb) * 1024 * 1024


def load_project(
    root: Path,
    defaults_path: Path | None = None,
    sites_path: Path | None = None,
) -> tuple[dict[str, Any], list[Site]]:
    assert_required_project_files(root)
    defaults = load_defaults(defaults_path or root / "configs/defaults.yaml")
    sites = load_sites(sites_path or root / "configs/sites.yaml")
    return defaults, sites
