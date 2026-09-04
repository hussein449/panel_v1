"""The nine checks, and the failure types that decide what happens next."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from roadrisk.core.contract import prepare_panel
from roadrisk.core.diagnostics import (
    Family,
    compute_dispersion,
    compute_vif,
    zero_variance_columns,
)
from roadrisk.core.engine import _shipped_checks
from roadrisk.core.gates import (
    CheckResult,
    CheckStatus,
    FailureType,
    SnapReport,
    check_convergence,
    check_crashes_per_parameter,
    check_dispersion,
    check_snap_rate,
    check_vif,
    check_zero_crash_rows,
    run_pre_fit_gates,
)


class TestCheckOne:
    """The check that matters. Everything else is hygiene."""

    def test_fails_without_zero_rows(self, crash_only_panel: pd.DataFrame) -> None:
        _, contract = prepare_panel(crash_only_panel)
        result = check_zero_crash_rows(contract)

        assert result.status is CheckStatus.FAILED
        assert result.failure_type is FailureType.HARD
        assert result.blocks_mode_a
        assert "whole road" in result.message

    def test_passes_with_zero_rows(self, rich_panel: pd.DataFrame) -> None:
        _, contract = prepare_panel(rich_panel)
        assert check_zero_crash_rows(contract).status is CheckStatus.PASSED


class TestCheckSix:
    def test_is_skipped_not_passed_when_snapping_was_not_performed(self) -> None:
        """Degrade loudly. An unmeasured snap rate is never assumed to be good."""
        result = check_snap_rate(None)
        assert result.status is CheckStatus.SKIPPED
        assert not result.forces_descent
        assert "not assumed to be good" in result.message

    def test_fails_below_threshold_and_reports_the_reasons(self) -> None:
        snap = SnapReport(
            n_supplied=1000,
            n_snapped=600,
            dropped_reasons={"beyond_tolerance": 300, "no_timestamp": 100},
        )
        result = check_snap_rate(snap)

        assert result.status is CheckStatus.FAILED
        assert result.failure_type is FailureType.SOFT
        assert "beyond_tolerance: 300" in result.message

    def test_passes_above_threshold(self) -> None:
        snap = SnapReport(n_supplied=1000, n_snapped=850)
        assert check_snap_rate(snap).status is CheckStatus.PASSED
        assert snap.n_dropped == 150

    def test_crashes_on_another_road_do_not_count_against_the_rate(self) -> None:
        """The A6 case: a national extract handed to one 48 km corridor.

        284 crashes in, 150 on the road, 129 of them kilometres away on stretches the
        fetch never returned. Counting those as failures produced *"the panel is not a
        faithful record of what happened on this road"* — about a panel that was an
        entirely faithful record of the corridor. The table was wider than the corridor,
        which is the ordinary way to use this, not a fault in either.
        """
        snap = SnapReport(
            n_supplied=284,
            n_snapped=150,
            dropped_reasons={"beyond_tolerance": 5, "not_on_this_corridor": 129},
        )
        result = check_snap_rate(snap)

        # 150 of the 155 that were anywhere near the road — not 150 of 284.
        assert result.status is CheckStatus.PASSED
        assert "150" in result.observed and "155" in result.observed
        assert "not on this corridor at all" in result.message
        assert "not a faithful record" not in result.message

    def test_genuinely_bad_geocoding_still_fails(self) -> None:
        """The other half. Excluding distant crashes must not excuse near-misses."""
        snap = SnapReport(
            n_supplied=200,
            n_snapped=100,
            dropped_reasons={"beyond_tolerance": 90, "not_on_this_corridor": 10},
        )
        result = check_snap_rate(snap)

        assert result.status is CheckStatus.FAILED
        assert result.forces_descent
        assert "not a faithful record" in result.message

    def test_no_crash_table_is_not_described_as_a_pre_built_panel(self) -> None:
        """Two ways to have no snap report, and they are not the same fact.

        Found in a real report: a corridor assessed from geography with no crash file
        printed *"the panel was supplied pre-built"*, which was simply untrue — this
        engine built that panel. The sentence reads plausibly, which is exactly what
        makes it expensive in a document whose whole claim is that it says what
        actually happened.
        """
        result = check_snap_rate(None, total_crashes=0)

        assert result.status is CheckStatus.SKIPPED
        assert not result.forces_descent
        assert "nothing to snap" in result.message
        assert "pre-built" not in result.message
        assert "unknown" not in result.message

    def test_a_pre_built_panel_still_says_so(self) -> None:
        """The other branch, which was right all along and must not be lost."""
        result = check_snap_rate(None, total_crashes=2_412)

        assert result.status is CheckStatus.SKIPPED
        assert "pre-built" in result.message
        assert "not assumed to be good" in result.message


class TestCheckSeven:
    def test_flags_collinear_design(self) -> None:
        rng = np.random.default_rng(3)
        base = rng.normal(size=400)
        design = pd.DataFrame(
            {"a": base, "b": base + rng.normal(scale=0.01, size=400), "c": rng.normal(size=400)}
        )
        result = check_vif(compute_vif(design))

        assert result.status is CheckStatus.FAILED
        assert result.failure_type is FailureType.SOFT
        assert "not separately interpretable" in result.message

    def test_passes_on_independent_design(self) -> None:
        rng = np.random.default_rng(3)
        design = pd.DataFrame({name: rng.normal(size=400) for name in "abc"})
        assert check_vif(compute_vif(design)).status is CheckStatus.PASSED

    def test_single_column_has_no_collinearity(self) -> None:
        design = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
        assert compute_vif(design).max_vif == pytest.approx(1.0)

    def test_message_says_which_design_it_measured(self) -> None:
        """The A3 bug: a failure against candidates read as a failure of the result."""
        rng = np.random.default_rng(3)
        base = rng.normal(size=400)
        design = pd.DataFrame(
            {"a": base, "b": base + rng.normal(scale=0.01, size=400)}
        )
        vif = compute_vif(design)

        assert "candidate factors" in check_vif(vif).message
        assert "fitted model" in check_vif(vif, fitted=True).message

    def test_the_fitted_check_supersedes_the_candidate_one(self) -> None:
        """Only one check 7 ships, and it is the one describing what was fitted."""
        candidate = CheckResult(
            number=7,
            name="Collinearity (VIF)",
            status=CheckStatus.FAILED,
            failure_type=FailureType.SOFT,
            message="candidate factors are collinear",
        )
        fitted = CheckResult(
            number=7,
            name="Collinearity (VIF)",
            status=CheckStatus.PASSED,
            failure_type=FailureType.SOFT,
            message="fitted model is clean",
        )
        other = CheckResult(
            number=8,
            name="Variance-to-mean",
            status=CheckStatus.PASSED,
            failure_type=FailureType.INFO,
            message="fine",
        )

        shipped = _shipped_checks([other, candidate], [fitted])

        assert [c.number for c in shipped] == [8, 7]
        assert shipped[1] is fitted

    def test_the_candidate_check_stands_when_nothing_was_fitted(self) -> None:
        """Mode B scores every available factor, so its check 7 is the right one."""
        candidate = CheckResult(
            number=7,
            name="Collinearity (VIF)",
            status=CheckStatus.FAILED,
            failure_type=FailureType.SOFT,
            message="candidate factors are collinear",
        )

        assert _shipped_checks([candidate], []) == [candidate]


class TestCheckEight:
    """The family check, and the empty panel it used to answer confidently."""

    def test_an_empty_panel_measures_no_dispersion(self) -> None:
        """`0 / 0` is not a large ratio, and a green tick over it is a false claim.

        Found in a real report: *"Mean 0.000, variance 0.000, ratio inf — fitting as
        negative binomial"*, marked PASSED. `compute_dispersion` returns `inf` when the
        mean is zero because the division has to produce something; printing that as a
        passed check turned an impossibility into a measurement.
        """
        result = check_dispersion(compute_dispersion(pd.Series([0, 0, 0, 0])))

        assert result.status is CheckStatus.SKIPPED
        assert "undefined rather than large" in result.message
        assert "negative binomial" not in result.message
        assert "inf" not in result.observed

    def test_a_panel_with_counts_still_reports_its_family(self) -> None:
        """The ordinary path, unchanged — this must not have gone quiet."""
        counts = pd.Series([0, 1, 0, 4, 2, 0, 9, 1, 0, 3])
        result = check_dispersion(compute_dispersion(counts))

        assert result.status is CheckStatus.PASSED
        assert "Mean" in result.message
        assert "fitting as" in result.message

    def test_it_never_blocks_or_descends_either_way(self) -> None:
        """Check 8 sets the family, not the mode. Skipping it changes no outcome."""
        for counts in (pd.Series([0, 0, 0]), pd.Series([1, 5, 0, 2])):
            result = check_dispersion(compute_dispersion(counts))
            assert result.failure_type is FailureType.INFO
            assert not result.blocks_mode_a
            assert not result.forces_descent


class TestOtherChecks:
    def test_crashes_per_parameter(self) -> None:
        assert check_crashes_per_parameter(100, 5).status is CheckStatus.PASSED
        failed = check_crashes_per_parameter(30, 9)
        assert failed.status is CheckStatus.FAILED
        assert failed.forces_descent

    def test_dispersion_sets_family_not_mode(self, rich_panel: pd.DataFrame) -> None:
        _, contract = prepare_panel(rich_panel)
        gates = run_pre_fit_gates(
            contract=contract,
            vif=compute_vif(pd.DataFrame()),
            dispersion=compute_dispersion(rich_panel["n_crashes"]),
            n_parameters=5,
        )
        check = gates.by_number(8)
        assert check is not None
        assert check.failure_type is FailureType.INFO
        assert check.status is CheckStatus.PASSED

    def test_overdispersed_counts_select_negative_binomial(self) -> None:
        rng = np.random.default_rng(5)
        counts = pd.Series(rng.negative_binomial(2, 0.2, size=2000))
        assert compute_dispersion(counts).family is Family.NEGATIVE_BINOMIAL

    def test_equidispersed_counts_select_poisson(self) -> None:
        rng = np.random.default_rng(5)
        counts = pd.Series(rng.poisson(3.0, size=5000))
        assert compute_dispersion(counts).family is Family.POISSON

    def test_convergence_is_soft(self) -> None:
        result = check_convergence(False, "A-full (7 factors)")
        assert result.forces_descent
        assert not result.blocks_mode_a


class TestConstantColumns:
    def test_detects_an_exactly_constant_column(self) -> None:
        design = pd.DataFrame({"a": [1.0, 2.0, 3.0], "flat": [5.0, 5.0, 5.0]})
        assert zero_variance_columns(design) == ["flat"]

    def test_detects_a_column_constant_only_to_floating_point(self) -> None:
        """pandas returns ~1e-15, not 0, for a genuinely constant column.

        A corridor with one posted speed limit end to end produces exactly this, and
        an exact `== 0` test lets a singular design through to the fit.
        """
        constant = np.full(500, np.log(80.0))
        design = pd.DataFrame({"speed_limit": constant, "other": np.arange(500.0)})

        assert design["speed_limit"].std(ddof=0) > 0
        assert zero_variance_columns(design) == ["speed_limit"]

    def test_does_not_flag_a_genuinely_varying_column(self) -> None:
        rng = np.random.default_rng(1)
        design = pd.DataFrame({"lit": rng.uniform(0.0, 1.0, size=200)})
        assert zero_variance_columns(design) == []


class TestGateReport:
    def test_runs_all_eight_pre_fit_checks(self, rich_panel: pd.DataFrame) -> None:
        prepared, contract = prepare_panel(rich_panel)
        gates = run_pre_fit_gates(
            contract=contract,
            vif=compute_vif(pd.DataFrame()),
            dispersion=compute_dispersion(prepared["n_crashes"]),
            n_parameters=5,
        )
        assert [c.number for c in gates.checks] == [1, 2, 3, 4, 5, 6, 7, 8]
        assert gates.mode_a_admissible

    def test_hard_failure_blocks_mode_a(self, crash_only_panel: pd.DataFrame) -> None:
        prepared, contract = prepare_panel(crash_only_panel)
        gates = run_pre_fit_gates(
            contract=contract,
            vif=compute_vif(pd.DataFrame()),
            dispersion=compute_dispersion(prepared["n_crashes"]),
            n_parameters=5,
        )
        assert not gates.mode_a_admissible
        assert [c.number for c in gates.hard_failures] == [1]
