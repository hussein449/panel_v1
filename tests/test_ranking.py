"""Step 4.2 — one ranked table, and runs that break where the road breaks.

Two modes, two different quantities, one question: which bit of road first. The tests
here are about the join — that both modes fill the same table, that Mode B does not
quietly acquire a count on the way into it, and that a blackspot describes road the
panel actually covers rather than stepping over the gap in the middle of it.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from roadrisk.core.engine import assess
from roadrisk.core.ladder import Mode
from roadrisk.core.ranking import (
    ASSUMED_ORDER_NOTE,
    UnitRisk,
    find_blackspots,
    rank_mode_a,
)
from roadrisk.core.registry import Registry

COUNT_FIELDS = {
    "observed",
    "expected",
    "expected_low",
    "expected_high",
    "exposure",
    "rate",
}


def risks(n: int, *, flagged: set[int] | None = None) -> list[UnitRisk]:
    """`n` units, worst first. Everything is flagged unless `flagged` says otherwise."""
    return [
        UnitRisk(
            unit_id=f"U{i:04d}",
            rank=i + 1,
            percentile=1.0 if flagged is None or i in flagged else 0.0,
            score=float(n - i),
        )
        for i in range(n)
    ]


def chainage(unit_ids: list[str], *, length: float = 500.0, gap_after: str | None = None):
    """Contiguous chainage, optionally with one gap opened after a named unit."""
    order: list[tuple[str, float, float]] = []
    cursor = 0.0
    for unit_id in unit_ids:
        order.append((unit_id, cursor, cursor + length))
        cursor += length
        if unit_id == gap_after:
            cursor += 2_000.0
    return order


@pytest.fixture(scope="module")
def mode_a(rich_panel: pd.DataFrame):
    return assess(rich_panel)


@pytest.fixture(scope="module")
def mode_b(starved_panel: pd.DataFrame, sourced_registry: Registry):
    return assess(starved_panel, registry=sourced_registry)


class TestOneTableForBothModes:
    def test_both_modes_produce_a_ranking(self, mode_a, mode_b) -> None:
        assert mode_a.mode is Mode.A
        assert mode_b.mode is Mode.B
        assert mode_a.ranking is not None
        assert mode_b.ranking is not None

    def test_both_carry_the_same_core_columns(self, mode_a, mode_b) -> None:
        core = {"unit_id", "rank", "percentile", "score"}

        for ranking in (mode_a.ranking, mode_b.ranking):
            assert core <= set(ranking.units[0].as_dict())

    def test_both_are_ordered_worst_first(self, mode_a, mode_b) -> None:
        for ranking in (mode_a.ranking, mode_b.ranking):
            scores = [unit.score for unit in ranking.units]
            assert scores == sorted(scores, reverse=True)
            assert [u.rank for u in ranking.units] == list(
                range(1, len(ranking.units) + 1)
            )

    def test_each_mode_says_what_it_ranked_on(self, mode_a, mode_b) -> None:
        """A rate and an index score are not the same number and must not read alike."""
        assert "fitted model" in mode_a.ranking.basis
        assert "not a rate" in mode_b.ranking.basis


class TestModeBCarriesNoCount:
    def test_rows_have_no_count_and_no_interval(self, mode_b) -> None:
        """Not null — absent. A null count is still a count-shaped hole."""
        for unit in mode_b.ranking.units:
            assert COUNT_FIELDS & set(unit.as_dict()) == set()

    def test_the_ranking_declares_it_has_no_intervals(self, mode_b) -> None:
        assert mode_b.ranking.has_intervals is False

    def test_blackspots_carry_no_count_either(self, mode_b) -> None:
        for spot in mode_b.ranking.blackspots:
            payload = spot.as_dict()
            assert "observed" not in payload
            assert "expected" not in payload

    def test_the_serialised_payload_has_no_count_anywhere(self, mode_b) -> None:
        payload = json.loads(json.dumps(mode_b.as_dict()))["ranking"]

        for row in payload["units"]:
            assert COUNT_FIELDS & set(row) == set()

    def test_crash_type_components_ride_along(self, mode_b) -> None:
        """A unit that ranks badly can be read for *why*."""
        assert mode_b.ranking.units[0].components


class TestModeAIntervals:
    def test_every_unit_carries_an_interval_around_its_expected_count(
        self, mode_a
    ) -> None:
        assert mode_a.ranking.has_intervals

        for unit in mode_a.ranking.units:
            assert unit.expected_low < unit.expected < unit.expected_high
            assert unit.expected_low > 0

    def test_expected_counts_sum_to_the_model_total(self, mode_a) -> None:
        total = sum(unit.expected for unit in mode_a.ranking.units)

        assert total == pytest.approx(mode_a.predictions["expected"].sum())

    def test_observed_counts_sum_to_the_panel(self, mode_a, rich_panel) -> None:
        total = sum(unit.observed for unit in mode_a.ranking.units)

        assert total == rich_panel["n_crashes"].sum()

    def test_the_score_is_a_rate_not_a_count(self, mode_a) -> None:
        """Ranking on the raw count would just rank on segment length."""
        for unit in mode_a.ranking.units:
            assert unit.score == pytest.approx(unit.expected / unit.exposure)

    def test_a_fit_without_a_covariance_ranks_without_inventing_one(
        self, mode_a
    ) -> None:
        ranking = rank_mode_a(mode_a.predictions, fit=None)

        assert ranking.units
        assert ranking.has_intervals is False
        assert all(unit.expected_low is None for unit in ranking.units)
        assert any("without an interval" in note for note in ranking.notes)


class TestBlackspots:
    def test_contiguous_flagged_units_become_one_run(self) -> None:
        units = risks(4)

        spots = find_blackspots(
            units,
            corridor_units=chainage([u.unit_id for u in units]),
            threshold_percentile=0.0,
        )

        assert len(spots) == 1
        assert spots[0].n_units == 4
        assert spots[0].start_m == 0.0
        assert spots[0].end_m == 2000.0
        assert spots[0].length_m == 2000.0

    def test_a_run_never_spans_a_chainage_gap(self) -> None:
        """The done-when. A blackspot that stepped over the gap would describe road
        the panel does not cover."""
        units = risks(4)

        spots = find_blackspots(
            units,
            corridor_units=chainage(
                [u.unit_id for u in units], gap_after="U0001"
            ),
            threshold_percentile=0.0,
        )

        assert [spot.unit_ids for spot in spots] == [
            ("U0000", "U0001"),
            ("U0002", "U0003"),
        ]

    def test_a_unit_missing_from_the_panel_breaks_the_run(self) -> None:
        units = risks(3)
        order = chainage(["U0000", "U0001", "U9999", "U0002"])

        spots = find_blackspots(units, corridor_units=order, threshold_percentile=0.0)

        assert [spot.unit_ids for spot in spots] == [("U0000", "U0001"), ("U0002",)]

    def test_an_unflagged_unit_breaks_the_run(self) -> None:
        units = risks(4, flagged={0, 1, 3})

        spots = find_blackspots(
            units,
            corridor_units=chainage([u.unit_id for u in units]),
            threshold_percentile=0.5,
        )

        assert [spot.unit_ids for spot in spots] == [("U0000", "U0001"), ("U0003",)]

    def test_runs_are_ordered_by_their_worst_unit(self) -> None:
        units = risks(4, flagged={0, 3})

        spots = find_blackspots(
            units,
            corridor_units=chainage([u.unit_id for u in units]),
            threshold_percentile=0.5,
        )

        assert [spot.worst_rank for spot in spots] == [1, 4]
        assert [spot.rank for spot in spots] == [1, 2]

    def test_nothing_flagged_is_no_blackspots_not_an_error(self) -> None:
        assert find_blackspots(risks(3), threshold_percentile=1.5) == ()

    def test_without_corridor_order_adjacency_is_assumed_and_declared(
        self, mode_a
    ) -> None:
        """The assumption the spatial field also makes. Recorded, not left implicit."""
        assert ASSUMED_ORDER_NOTE in mode_a.ranking.notes
        assert all(spot.start_m is None for spot in mode_a.ranking.blackspots)


class TestCorridorWiring:
    def test_real_chainage_reaches_the_blackspots(self, corridor_panel) -> None:
        assessment = assess(
            corridor_panel.panel,
            snap=corridor_panel.snap,
            corridor_units=corridor_panel.corridor_units,
        )
        ranking = assessment.ranking

        assert ranking.blackspots
        assert ASSUMED_ORDER_NOTE not in ranking.notes
        for spot in ranking.blackspots:
            assert spot.start_m is not None
            assert spot.length_m > 0

    def test_a_blackspot_covers_exactly_the_road_its_units_cover(
        self, corridor_panel
    ) -> None:
        extents = dict(
            (unit_id, (start, end))
            for unit_id, start, end in corridor_panel.corridor_units
        )
        assessment = assess(
            corridor_panel.panel,
            snap=corridor_panel.snap,
            corridor_units=corridor_panel.corridor_units,
        )

        for spot in assessment.ranking.blackspots:
            covered = [extents[unit_id] for unit_id in spot.unit_ids]
            assert spot.start_m == min(start for start, _ in covered)
            assert spot.end_m == max(end for _, end in covered)


class TestSerialisation:
    def test_the_ranking_survives_a_round_trip(self, mode_a) -> None:
        payload = json.loads(json.dumps(mode_a.as_dict()))["ranking"]

        assert payload["mode"] == "A"
        assert payload["n_units"] == len(mode_a.ranking.units)
        assert payload["has_intervals"] is True
        assert payload["units"][0]["rank"] == 1
        assert "basis" in payload
