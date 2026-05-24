from __future__ import annotations

from nextgen_hydra.cli import main


def test_validate_config_cli(repo_root, capsys):
    code = main(["--root", str(repo_root), "validate-config"])

    assert code == 0
    output = capsys.readouterr().out
    assert '"status": "ok"' in output
    assert '"mapped_site_count": 4' in output
