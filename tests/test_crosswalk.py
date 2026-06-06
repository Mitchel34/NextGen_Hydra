from __future__ import annotations

from pathlib import Path
import sqlite3

from nextgen_hydra.crosswalk import resolve_site_crosswalk
from nextgen_hydra.resources import resource_key, resource_local_path
from tests.test_manifest import mapped_site


def test_resolve_site_crosswalk_exact_match(defaults, tmp_path):
    _write_gpkg(
        resource_local_path(tmp_path, resource_key(defaults, "05")),
        "flowpaths",
        ["comid INTEGER", "id INTEGER"],
        [(6892192, 123456)],
    )

    crosswalk, report = resolve_site_crosswalk(
        sites=[mapped_site("05")],
        defaults=defaults,
        resource_dir=tmp_path,
    )

    assert report["status"] == "pass"
    assert crosswalk["sites"][0]["status"] == "resolved"
    assert crosswalk["sites"][0]["troute_feature_id"] == 123456
    assert crosswalk["sites"][0]["source_fields"] == {
        "match_field": "comid",
        "target_field": "id",
    }


def test_resolve_site_crosswalk_reports_missing_ids(defaults, tmp_path):
    _write_gpkg(
        resource_local_path(tmp_path, resource_key(defaults, "05")),
        "flowpaths",
        ["comid INTEGER", "id INTEGER"],
        [(1, 2)],
    )

    crosswalk, report = resolve_site_crosswalk(
        sites=[mapped_site("05")],
        defaults=defaults,
        resource_dir=tmp_path,
    )

    assert report["status"] == "fail"
    assert crosswalk["sites"][0]["status"] == "unresolved"


def test_resolve_site_crosswalk_reports_ambiguous_candidates(defaults, tmp_path):
    _write_gpkg(
        resource_local_path(tmp_path, resource_key(defaults, "05")),
        "flowpaths",
        ["comid INTEGER", "id INTEGER"],
        [(6892192, 111), (6892192, 222)],
    )

    crosswalk, report = resolve_site_crosswalk(
        sites=[mapped_site("05")],
        defaults=defaults,
        resource_dir=tmp_path,
    )

    assert report["status"] == "fail"
    assert crosswalk["sites"][0]["status"] == "ambiguous"
    assert crosswalk["sites"][0]["candidate_troute_feature_ids"] == [111, 222]


def test_resolve_site_crosswalk_accepts_field_name_variations(defaults, tmp_path):
    _write_gpkg(
        resource_local_path(tmp_path, resource_key(defaults, "05")),
        "network",
        ["nhdplus_comid INTEGER", "feature_id INTEGER"],
        [(6892192, 333)],
    )

    crosswalk, _report = resolve_site_crosswalk(
        sites=[mapped_site("05")],
        defaults=defaults,
        resource_dir=tmp_path,
    )

    assert crosswalk["sites"][0]["troute_feature_id"] == 333
    assert crosswalk["sites"][0]["source_fields"] == {
        "match_field": "nhdplus_comid",
        "target_field": "feature_id",
    }


def _write_gpkg(
    path: Path,
    table: str,
    columns: list[str],
    rows: list[tuple[int, int]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(f'CREATE TABLE "{table}" ({", ".join(columns)})')
        names = [column.split()[0] for column in columns]
        placeholders = ", ".join("?" for _name in names)
        connection.executemany(
            f'INSERT INTO "{table}" ({", ".join(names)}) VALUES ({placeholders})',
            rows,
        )
