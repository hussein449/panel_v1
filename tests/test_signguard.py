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


class TestSuppressionIsNotContradiction:
    """A named suppressor is a mechanism. A contradiction without one is a mystery.

    Measured on the A3: `curve_density` fits −0.050 beside six other terms, +0.142 on
    its own, and +0.044 beside `speed_limit` alone — drivers slow for bends, so speed
    absorbs curvature. `junction_density` fits −0.050, +0.163 alone, and −0.010 beside
    `access_density`, its only correlated partner. The first has an explanation and the
    second does not, and filing them under one heading loses that.
    """

    def finding(self, guard, name: str):
        return next(f for f in guard.findings if f.factor == name)

    def test_a_planted_reversal_is_never_called_suppression(
        self, reversed_result
    ) -> None:
        """The truth here is a genuinely negative effect. No partner may excuse it."""
        finding = self.finding(reversed_result.sign_guard, "curve_density")

        assert finding.contradicts
        assert not finding.suppressed
        assert finding.suppressed_by is None
        assert reversed_result.sign_guard.unexplained

    def test_a_wrong_univariate_sign_cannot_be_suppression(self) -> None:
        """If the factor points the wrong way alone, no partner suppressed anything."""
        from roadrisk.core.registry import load_registry
        from roadrisk.core.signguard import PairwiseRefit, _suppressor

        factor = next(
            f for f in load_registry().factors if f.name == "curve_density"
        )
        restored = [PairwiseRefit("speed_limit", -0.5, 0.3, True, True)]

        assert _suppressor(factor, univariate=-0.2, pairwise=restored) is None

    def test_a_restored_pair_names_the_suppressor(self) -> None:
        from roadrisk.core.registry import load_registry
        from roadrisk.core.signguard import PairwiseRefit, _suppressor

        factor = next(
            f for f in load_registry().factors if f.name == "curve_density"
        )
        pairwise = [
            PairwiseRefit("lanes", 0.31, -0.02, False, True),
            PairwiseRefit("speed_limit", -0.62, 0.04, True, True),
        ]

        assert _suppressor(factor, univariate=0.14, pairwise=pairwise) == "speed_limit"

    def test_the_most_correlated_restoring_partner_wins(self) -> None:
        """The partner with the most to absorb is the one being named."""
        from roadrisk.core.registry import load_registry
        from roadrisk.core.signguard import PairwiseRefit, _suppressor

        factor = next(
            f for f in load_registry().factors if f.name == "curve_density"
        )
        pairwise = [
            PairwiseRefit("lanes", 0.35, 0.01, True, True),
            PairwiseRefit("speed_limit", -0.62, 0.04, True, True),
        ]

        assert _suppressor(factor, univariate=0.14, pairwise=pairwise) == "speed_limit"

    def test_no_restoring_partner_leaves_it_unexplained(self) -> None:
        from roadrisk.core.registry import load_registry
        from roadrisk.core.signguard import PairwiseRefit, _suppressor

        factor = next(
            f for f in load_registry().factors if f.name == "junction_density"
        )
        pairwise = [PairwiseRefit("access_density", 0.45, -0.01, False, False)]

        assert _suppressor(factor, univariate=0.16, pairwise=pairwise) is None

    def test_the_verdict_names_the_suppressor_rather_than_condemning(self) -> None:
        from roadrisk.core.registry import load_registry
        from roadrisk.core.signguard import _verdict

        factor = next(
            f for f in load_registry().factors if f.name == "curve_density"
        )
        verdict = _verdict(factor, -0.05, False, suppressed_by="speed_limit")

        assert "suppression rather than a contradiction" in verdict
        assert "speed_limit" in verdict
        assert "NOT interpretable as causal" not in verdict

    def test_it_reaches_the_payload(self, reversed_result) -> None:
        payload = reversed_result.as_dict()["sign_guard"]
        flagged = next(
            f for f in payload["findings"] if f["factor"] == "curve_density"
        )

        assert "suppressed_by" in flagged
        assert "suppressed" in flagged
