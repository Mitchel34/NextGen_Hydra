from __future__ import annotations

from nextgen_hydra.config import load_project


def test_required_project_config_loads(repo_root):
    defaults, sites = load_project(repo_root)

    assert defaults["nrds"]["s3_bucket"] == "ciroh-community-ngen-datastream"
    assert defaults["nrds"]["candidate_streams"] == ["cfe_nom", "lstm_0"]
    assert len(sites) == 4
    assert all(site.mapping_status == "verified" for site in sites)
    assert {site.site_id: site.discovered_vpu_id for site in sites} == {
        "south_fork_new_river_near_jefferson_nc": "05",
        "new_river_near_galax_va": "05",
        "watauga_river_near_sugar_grove_nc": "06",
        "watauga_river_at_elizabethton_tn": "06",
    }
