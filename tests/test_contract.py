"""Contract failures reject the job. They are never downgraded to Mode B."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from roadrisk.core.contract import (
    EXPOSURE_COLUMN,
    LOG_EXPOSURE_COLUMN,
    prepare_panel,
)
from roadrisk.core.errors import ContractViolation


def minimal_panel() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "unit_id": ["U1", "U1", "U2", "U2"],
            "period": ["2024-01", "2024-02", "2024-01", "2024-02"],
            "time_slot": ["day", "day", "day", "day"],
            "n_crashes": [0, 2, 1, 0],
            "length_km": [0.5, 0.5, 0.4, 0.4],
            "duration_hours": [720.0, 720.0, 720.0, 720.0],
        }
    )


class TestAcceptance:
    def test_derives_exposure_and_offset(self) -> None:
        prepared, report = prepare_panel(minimal_panel())

        assert prepared[EXPOSURE_COLUMN].iloc[0] == pytest.approx(0.5 * 720.0)
        assert prepared[LOG_EXPOSURE_COLUMN].iloc[0] == pytest.approx(np.log(360.0))
        assert report.n_rows == 4
        assert report.n_units == 2
        assert report.total_crashes == 3
        assert report.zero_crash_rows == 2

    def test_does_not_mutate_the_callers_frame(self) -> None:
        panel = minimal_panel()
        prepare_panel(panel)
        assert EXPOSURE_COLUMN not in panel.columns

    def test_optional_columns_are_reported(self) -> None:
        panel = minimal_panel()
        panel["curve_density"] = 1.0
        _, report = prepare_panel(panel)
        assert report.optional_columns == ["curve_density"]


class TestRejection:
    @pytest.mark.parametrize(
        "column",
        ["unit_id", "period", "time_slot", "n_crashes", "length_km", "duration_hours"],
    )
    def test_missing_required_column_names_it(self, column: str) -> None:
        panel = minimal_panel().drop(columns=[column])
        with pytest.raises(ContractViolation, match=column):
            prepare_panel(panel)

    def test_empty_panel(self) -> None:
        with pytest.raises(ContractViolation, match="empty"):
            prepare_panel(minimal_panel().iloc[0:0])

    def test_zero_length_breaks_the_offset(self) -> None:
        panel = minimal_panel()
        panel.loc[0, "length_km"] = 0.0
        with pytest.raises(ContractViolation, match="strictly positive"):
            prepare_panel(panel)

    def test_negative_duration(self) -> None:
        panel = minimal_panel()
        panel.loc[2, "duration_hours"] = -5.0
        with pytest.raises(ContractViolation, match="strictly positive"):
            prepare_panel(panel)

    def test_null_crash_count_is_not_zero(self) -> None:
        panel = minimal_panel()
        panel.loc[1, "n_crashes"] = None
        with pytest.raises(ContractViolation, match="not the same as zero"):
            prepare_panel(panel)

    def test_negative_crash_count(self) -> None:
        panel = minimal_panel()
        panel.loc[1, "n_crashes"] = -1
        with pytest.raises(ContractViolation, match="negative"):
            prepare_panel(panel)

    def test_fractional_crash_count_is_a_rate_not_a_count(self) -> None:
        panel = minimal_panel()
        panel["n_crashes"] = panel["n_crashes"].astype(float)
        panel.loc[1, "n_crashes"] = 1.5
        with pytest.raises(ContractViolation, match="whole counts"):
            prepare_panel(panel)

    def test_duplicate_panel_cell(self) -> None:
        panel = pd.concat([minimal_panel(), minimal_panel().iloc[[0]]])
        with pytest.raises(ContractViolation, match="must be unique"):
            prepare_panel(panel)

    def test_null_identifier(self) -> None:
        panel = minimal_panel()
        panel.loc[0, "unit_id"] = None
        with pytest.raises(ContractViolation, match="identifiers must be"):
            prepare_panel(panel)

    def test_reserved_column_supplied_by_caller(self) -> None:
        panel = minimal_panel()
        panel[EXPOSURE_COLUMN] = 1.0
        with pytest.raises(ContractViolation, match="reserved column"):
            prepare_panel(panel)
