from __future__ import annotations

from nextgen_hydra.config import load_project


def test_required_project_config_loads(repo_root):
    defaults, sites = load_project(repo_root)

    assert defaults["nrds"]["s3_bucket"] == "ciroh-community-ngen-datastream"
    assert defaults["nrds"]["candidate_streams"] == ["cfe_nom", "lstm_0"]
    assert len(sites) == 4
    assert all(site.mapping_status == "unmapped" for site in sites)
    assert all(site.discovered_vpu_id is None for site in sites)
