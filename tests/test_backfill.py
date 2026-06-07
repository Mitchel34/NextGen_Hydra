from __future__ import annotations

import pytest

from nextgen_hydra.backfill import BackfillPlanError, build_backfill_plan


def test_backfill_rejects_windows_over_max_days(defaults):
    with pytest.raises(BackfillPlanError, match="maximum allowed"):
        build_backfill_plan(
            defaults=defaults,
            sites=[],
            start_date="20260501",
            end_date="20260508",
            max_days=7,
        )
