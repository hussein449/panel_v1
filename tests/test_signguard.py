"""The sign guard must catch a planted reversal, and must not invent one."""

from __future__ import annotations

import pandas as pd
import pytest

from roadrisk.core.engine import assess
from roadrisk.core.ladder import Mode
from roadrisk.demo import TRUE_EFFECTS, synthetic_panel


@pytest.fixture(scope="module")
def reversed_panel() -> pd.DataFrame:
    """Curve density genuinely reduces crashes here — the registry declares '+'.

    This reproduces the shape of the M51 failure on data where the truth is known.
    """
    return synthetic_panel(
        n_units=80,
        n_periods=18,
        seed=17,
        effects={**TRUE_EFFECTS, "curve_density": -0.45},
    )


@pytest.fixture(scope="module")
def reversed_result(reversed_panel: pd.DataFrame):
    return assess(reversed_panel, max_leave_one_out=5)


class TestCleanRun:
    def test_no_flags_when_every_sign_agrees(self, rich_panel: pd.DataFrame) -> None:
        result = assess(rich_panel)

        assert result.sign_guard is not None
        assert result.sign_guard.clean
        assert result.sign_guard.contradictions == []

    def test_clean_run_is_logged(self, rich_panel: pd.DataFrame) -> None:
        result = assess(rich_panel)
        assert any(e.code == "signs_agree" for e in result.log)

    def test_no_flag_events_on_a_clean_run(self, rich_panel: pd.DataFrame) -> None:
        result = assess(rich_panel)
        assert [e for e in result.log if e.level.value == "flag"] == []


class TestContradiction:
    def test_planted_reversal_is_caught(self, reversed_result) -> None:
        assert reversed_result.mode is Mode.A
        assert reversed_result.sign_guard is not None
        assert not reversed_result.sign_guard.clean

        flagged = {f.factor for f in reversed_result.sign_guard.contradictions}
        assert "curve_density" in flagged

    def test_verdict_refuses_a_causal_reading(self, reversed_result) -> None:
        finding = next(
            f
            for f in reversed_result.sign_guard.contradictions
            if f.factor == "curve_density"
        )
        assert "NOT interpretable as causal" in finding.verdict

    def test_contradiction_is_flagged_in_the_log(self, reversed_result) -> None:
        flags = [e for e in reversed_result.log if e.level.value == "flag"]
        assert any(e.data.get("factor") == "curve_density" for e in flags)

    def test_diagnostics_run_automatically(self, reversed_result) -> None:
        """The tool runs the diagnostics that found the original problem, unprompted."""
        finding = next(
            f
            for f in reversed_result.sign_guard.contradictions
            if f.factor == "curve_density"
        )
        assert finding.univariate_estimate is not None
        assert finding.leave_one_out is not None
        assert not reversed_result.sign_guard.correlations.empty

    def test_leave_one_out_respects_the_cap_and_reports_it(
        self, reversed_result
    ) -> None:
        louo = next(
            f
            for f in reversed_result.sign_guard.contradictions
            if f.factor == "curve_density"
        ).leave_one_out

        assert louo is not None
        assert louo.capped is True
        assert louo.n_refits <= 5
        assert louo.n_units == 80

    def test_univariate_fit_also_points_the_wrong_way(self, reversed_result) -> None:
        """Here the reversal is real in the data, so it survives dropping the others."""
        finding = next(
            f
            for f in reversed_result.sign_guard.contradictions
            if f.factor == "curve_density"
        )
        assert finding.univariate_estimate is not None
        assert finding.univariate_estimate < 0

    def test_agreeing_factors_are_still_reported(self, reversed_result) -> None:
        """Findings cover every fitted term, not only the contradictions."""
        guard = reversed_result.sign_guard
        assert len(guard.findings) == len(reversed_result.fit.coefficients)
        assert any(not f.contradicts for f in guard.findings)

    def test_contradiction_reaches_the_serialised_payload(
        self, reversed_result
    ) -> None:
        payload = reversed_result.as_dict()["sign_guard"]
        assert payload["clean"] is False
        assert payload["n_contradictions"] >= 1
        flagged = [f for f in payload["findings"] if f["contradicts"]]
        assert any(f["factor"] == "curve_density" for f in flagged)
