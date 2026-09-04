"""The crash-type decomposition: shares, dilution, and what must not change."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from roadrisk.core.context import RunContext
from roadrisk.core.crashmix import (
    BUCKETS,
    DEFAULT_CRASH_MIX,
    CrashMix,
    uniform_mix,
)
from roadrisk.core.engine import assess
from roadrisk.core.errors import RoadRiskError
from roadrisk.core.models.index import score_index
from roadrisk.core.registry import (
    Adapter,
    CrashScope,
    FacilityType,
    Factor,
    Licence,
    Sign,
    Tier,
    Transform,
    Weight,
    WeightFamily,
)

ADAPTER = Adapter(name="osm", tier=Tier.A, licence=Licence.ODBL)


def factor(name: str, weight_value: float, scope: CrashScope, priority: int) -> Factor:
    return Factor(
        name=name,
        label=name,
        column=name,
        transform=Transform.IDENTITY,
        expected_sign=Sign.POSITIVE,
        drop_priority=priority,
        missing_behaviour="lost",
        adapters=[ADAPTER],
        weights=[
            Weight(
                value=weight_value,
                source="SYNTHETIC test weight",
                family=WeightFamily.IRAP,
                scope=scope,
            )
        ],
    )


def design(**columns: list[float]) -> pd.DataFrame:
    return pd.DataFrame(columns)


class TestCrashMixValidation:
    def test_default_is_a_valid_partition(self) -> None:
        total = sum(DEFAULT_CRASH_MIX.share(b) for b in BUCKETS)
        assert total == pytest.approx(1.0)

    def test_default_carries_a_citation(self) -> None:
        assert "HSM Table 10-4" in DEFAULT_CRASH_MIX.source

    def test_run_off_dominates_on_rural_two_lane(self) -> None:
        """Sanity check against the source table: ran-off-road alone is 54.5%."""
        assert DEFAULT_CRASH_MIX.share(CrashScope.RUN_OFF_HEAD_ON) > 0.5

    def test_rejects_shares_that_do_not_sum_to_one(self) -> None:
        with pytest.raises(RoadRiskError, match="sum to"):
            CrashMix(shares=dict.fromkeys(BUCKETS, 0.1), source="bad")

    def test_rejects_a_missing_bucket(self) -> None:
        shares = {b: 0.25 for b in BUCKETS if b is not CrashScope.OTHER}
        with pytest.raises(RoadRiskError, match="missing share"):
            CrashMix(shares=shares, source="bad")

    def test_rejects_a_negative_share(self) -> None:
        shares = dict.fromkeys(BUCKETS, 0.5)
        shares[CrashScope.OTHER] = -0.5
        with pytest.raises(RoadRiskError, match="negative share"):
            CrashMix(shares=shares, source="bad")

    def test_uniform_mix_says_what_it_is(self) -> None:
        assert "no crash type distribution" in uniform_mix().source.lower()


class TestBackwardsCompatibility:
    """The decomposition must be a correction, not a silent re-scaling."""

    def test_a_total_only_registry_scores_exactly_as_a_flat_sum(self) -> None:
        """A total-scope weight enters every bucket, so it survives combination intact.

        This is the property that makes the change safe: nothing that was already
        correct moves.
        """
        factors = [
            factor("a", 0.5, CrashScope.TOTAL, 10),
            factor("b", 0.25, CrashScope.TOTAL, 20),
        ]
        matrix = design(a=[1.0, 2.0, 3.0], b=[4.0, 0.0, 1.0])
        units = pd.Series(["U1", "U2", "U3"])

        result = score_index(matrix, factors, units)
        flat = matrix["a"] * 0.5 + matrix["b"] * 0.25

        np.testing.assert_allclose(result.row_scores.to_numpy(), flat.to_numpy())

    def test_the_crash_mix_does_not_matter_when_every_weight_is_total(self) -> None:
        factors = [factor("a", 0.5, CrashScope.TOTAL, 10)]
        matrix = design(a=[1.0, 2.0])
        units = pd.Series(["U1", "U2"])

        default = score_index(matrix, factors, units)
        uniform = score_index(
            matrix, factors, units, RunContext(crash_mix=uniform_mix())
        )

        np.testing.assert_allclose(
            default.row_scores.to_numpy(), uniform.row_scores.to_numpy()
        )


class TestDilution:
    """The actual fix: a crash-type-specific weight must not move every crash."""

    def test_a_scoped_weight_is_diluted_by_its_share(self) -> None:
        factors = [factor("a", 0.8, CrashScope.RUN_OFF_HEAD_ON, 10)]
        matrix = design(a=[1.0])
        units = pd.Series(["U1"])

        result = score_index(matrix, factors, units)

        share = DEFAULT_CRASH_MIX.share(CrashScope.RUN_OFF_HEAD_ON)
        expected = math.log(share * math.exp(0.8) + (1 - share))

        assert result.row_scores.iloc[0] == pytest.approx(expected)
        assert 0 < result.row_scores.iloc[0] < 0.8, "must be diluted, but still present"

    def test_a_bigger_share_means_less_dilution(self) -> None:
        factors = [factor("a", 0.8, CrashScope.RUN_OFF_HEAD_ON, 10)]
        matrix = design(a=[1.0])
        units = pd.Series(["U1"])

        small = CrashMix(
            shares={
                CrashScope.RUN_OFF_HEAD_ON: 0.1,
                CrashScope.INTERSECTION: 0.3,
                CrashScope.PEDESTRIAN: 0.3,
                CrashScope.OTHER: 0.3,
            },
            source="test",
        )
        large = CrashMix(
            shares={
                CrashScope.RUN_OFF_HEAD_ON: 0.9,
                CrashScope.INTERSECTION: 0.0,
                CrashScope.PEDESTRIAN: 0.0,
                CrashScope.OTHER: 0.1,
            },
            source="test",
        )

        low = score_index(matrix, factors, units, RunContext(crash_mix=small))
        high = score_index(matrix, factors, units, RunContext(crash_mix=large))

        assert high.row_scores.iloc[0] > low.row_scores.iloc[0]

    def test_weights_in_different_buckets_do_not_contaminate_each_other(self) -> None:
        factors = [
            factor("a", 1.0, CrashScope.RUN_OFF_HEAD_ON, 10),
            factor("b", 1.0, CrashScope.INTERSECTION, 20),
        ]
        matrix = design(a=[1.0], b=[0.0])
        units = pd.Series(["U1"])

        result = score_index(matrix, factors, units)

        assert result.bucket_mean_scores[CrashScope.RUN_OFF_HEAD_ON] == pytest.approx(1.0)
        assert result.bucket_mean_scores[CrashScope.INTERSECTION] == pytest.approx(0.0)

    def test_total_scope_weights_reach_every_bucket(self) -> None:
        factors = [factor("a", 0.5, CrashScope.TOTAL, 10)]
        matrix = design(a=[2.0])
        units = pd.Series(["U1"])

        result = score_index(matrix, factors, units)

        for bucket in BUCKETS:
            assert result.bucket_mean_scores[bucket] == pytest.approx(1.0)


class TestReporting:
    def test_ranking_carries_a_column_per_crash_type(
        self, crash_only_panel: pd.DataFrame
    ) -> None:
        result = assess(crash_only_panel)
        assert result.index is not None

        for bucket in BUCKETS:
            assert f"score_{bucket.value}" in result.index.unit_ranking.columns

    def test_terms_declare_which_bucket_they_enter(
        self, crash_only_panel: pd.DataFrame
    ) -> None:
        result = assess(crash_only_panel)
        assert result.index is not None
        assert all(t.scope is not None for t in result.index.terms)

    def test_scoped_terms_are_identifiable(self, crash_only_panel: pd.DataFrame) -> None:
        """The shipped registry has at least one crash-type-specific weight."""
        result = assess(crash_only_panel)
        assert result.index is not None
        assert result.index.scoped_terms

    def test_crash_mix_is_logged(self, crash_only_panel: pd.DataFrame) -> None:
        result = assess(crash_only_panel)
        assert any(e.code == "crash_mix" for e in result.log)

    def test_default_mix_is_flagged_as_borrowed(
        self, crash_only_panel: pd.DataFrame
    ) -> None:
        result = assess(crash_only_panel)
        event = next(e for e in result.log if e.code == "crash_mix")
        assert "regional transfer problem" in event.message

    def test_crash_mix_reaches_the_payload(self, crash_only_panel: pd.DataFrame) -> None:
        payload = assess(crash_only_panel).as_dict()

        assert payload["context"]["crash_mix_is_default"] is True
        assert payload["index"]["crash_mix"]["source"]
        assert payload["index"]["bucket_mean_scores"]

    def test_changing_the_mix_changes_the_fingerprint(
        self, crash_only_panel: pd.DataFrame
    ) -> None:
        """Two runs that combined crash types differently must not look identical."""
        default = assess(crash_only_panel)
        uniform = assess(crash_only_panel, context=RunContext(crash_mix=uniform_mix()))

        assert default.manifest.fingerprint != uniform.manifest.fingerprint


class TestTheMixKnowsWhichRoadItCameFrom:
    """The A3 bug: a rural two-lane split applied, silently, to a Paris motorway."""

    def test_the_default_declares_the_facility_it_was_measured_on(self) -> None:
        assert DEFAULT_CRASH_MIX.facility_type is FacilityType.RURAL_TWO_LANE

    def test_a_split_describes_the_road_it_was_measured_on(self) -> None:
        assert DEFAULT_CRASH_MIX.describes(FacilityType.RURAL_TWO_LANE)

    def test_a_split_does_not_describe_a_different_road(self) -> None:
        assert not DEFAULT_CRASH_MIX.describes(FacilityType.MOTORWAY)

    def test_an_unrestricted_split_describes_anything(self) -> None:
        assert uniform_mix().describes(FacilityType.MOTORWAY)

    def test_an_undeclared_corridor_has_no_mismatch_to_report(self) -> None:
        """Nothing was claimed, so nothing is contradicted."""
        assert DEFAULT_CRASH_MIX.describes(FacilityType.ANY)

    def test_context_reports_the_mismatch(self) -> None:
        motorway = RunContext(facility_type=FacilityType.MOTORWAY)
        rural = RunContext(facility_type=FacilityType.RURAL_TWO_LANE)

        assert motorway.crash_mix_facility_mismatch
        assert not rural.crash_mix_facility_mismatch

    def test_the_mismatch_reaches_the_payload(
        self, crash_only_panel: pd.DataFrame
    ) -> None:
        payload = assess(
            crash_only_panel, context=RunContext(facility_type=FacilityType.MOTORWAY)
        ).as_dict()

        assert payload["context"]["crash_mix_facility_mismatch"] is True
