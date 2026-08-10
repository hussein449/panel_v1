"""Step 2.7 — fusion, agreement, and the confidence tier.

Client data is the realistic overlap today: it is declared first in almost every chain,
so supplying an inventory immediately puts two sources on one factor and makes every
part of this machinery live. The tests use it that way rather than inventing a second
open source that does not exist yet.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from roadrisk.core.registry import Licence, Registry, Tier
from roadrisk.geo import build_corridor_panel
from roadrisk.geo.adapters import (
    AdapterResult,
    Confidence,
    fuse,
    provenance_frame,
    read_client_values,
    resolve,
)
from roadrisk.geo.adapters.client import client_slot
from roadrisk.geo.adapters.fusion import (
    REASON_CARRIED,
    REASON_CONTRADICTED,
    REASON_MEASURED,
    REASON_THIN,
)
from roadrisk.geo.corridor import Corridor
from roadrisk.geo.errors import GeoError
from roadrisk.geo.segmentation import segment

ORIGIN_LAT = 34.90
ORIGIN_LON = 32.85
LAT_PER_M = 1.0 / 111_320.0
LON_PER_M = 1.0 / (111_320.0 * math.cos(math.radians(ORIGIN_LAT)))

CORRIDOR_M = 3000.0
UNIT_M = 500.0


def at(east_m: float, north_m: float = 0.0) -> tuple[float, float]:
    return (ORIGIN_LON + east_m * LON_PER_M, ORIGIN_LAT + north_m * LAT_PER_M)


def straight(length_m: float = CORRIDOR_M, step_m: float = 50.0) -> list:
    count = int(length_m / step_m) + 1
    return [at(index * step_m) for index in range(count)]


def way(points: list[tuple[float, float]], **tags: str) -> dict:
    return {
        "type": "way",
        "id": abs(hash((tuple(points), tuple(sorted(tags.items()))))) % 10**9,
        "tags": {"highway": "primary", **tags},
        "geometry": [{"lon": lon, "lat": lat} for lon, lat in points],
    }


def client_returning(*elements: dict):
    def fake(query: str) -> dict:
        return {"elements": list(elements)}

    return fake


@pytest.fixture(scope="module")
def corridor() -> Corridor:
    return Corridor.from_latlon([(lat, lon) for lon, lat in straight()], name="B9")


@pytest.fixture(scope="module")
def units(corridor: Corridor):
    return segment(corridor, target_length_m=UNIT_M)


def values(
    registry: Registry,
    factor: str,
    adapter: str,
    numbers: list[float],
    *,
    unit_ids: list[str] | None = None,
    coverage: list[float] | None = None,
):
    index = pd.Index(unit_ids or [f"u-{i}" for i in range(len(numbers))], name="unit_id")
    return resolve(
        registry,
        factor,
        adapter,
        source=f"{adapter} said so",
        values=pd.Series(numbers, index=index, dtype=float),
        unit_coverage=(
            pd.Series(coverage, index=index, dtype=float) if coverage else None
        ),
    )


def result(*factor_values) -> AdapterResult:
    return AdapterResult(name="test", resolved=list(factor_values))


def fused_for(fusion, factor: str):
    for item in fusion.factors:
        if item.factor == factor:
            return item
    raise AssertionError(f"'{factor}' is not in the fusion result")


# ---- priority ----------------------------------------------------------------


class TestPriority:
    def test_the_registry_chain_decides_the_winner_not_the_call_order(
        self, shipped_registry: Registry
    ) -> None:
        """`client_speed_survey` is declared before `osm_maxspeed`, so it wins.

        Passed second here on purpose: if call order mattered, OSM would win.
        """
        osm = result(values(shipped_registry, "speed_limit", "osm_maxspeed", [50.0]))
        client = result(
            values(shipped_registry, "speed_limit", "client_speed_survey", [80.0])
        )

        fusion = fuse([osm, client], shipped_registry)
        chosen = fused_for(fusion, "speed_limit").chosen

        assert chosen.adapter == "client_speed_survey"
        assert chosen.values.iloc[0] == 80.0

    def test_reversing_the_call_order_changes_nothing(
        self, shipped_registry: Registry
    ) -> None:
        osm = result(values(shipped_registry, "speed_limit", "osm_maxspeed", [50.0]))
        client = result(
            values(shipped_registry, "speed_limit", "client_speed_survey", [80.0])
        )

        assert (
            fused_for(fuse([client, osm], shipped_registry), "speed_limit").chosen.adapter
            == fused_for(fuse([osm, client], shipped_registry), "speed_limit").chosen.adapter
        )

    def test_the_loser_is_kept_not_discarded(self, shipped_registry: Registry) -> None:
        """A rejected source is what makes agreement measurable at all."""
        fusion = fuse(
            [
                result(values(shipped_registry, "speed_limit", "osm_maxspeed", [50.0])),
                result(
                    values(shipped_registry, "speed_limit", "client_speed_survey", [80.0])
                ),
            ],
            shipped_registry,
        )
        fused = fused_for(fusion, "speed_limit")

        assert fused.contested
        assert [other.adapter for other in fused.rejected] == ["osm_maxspeed"]

    def test_one_adapter_resolving_a_factor_twice_is_a_bug_not_a_disagreement(
        self, shipped_registry: Registry
    ) -> None:
        twice = result(
            values(shipped_registry, "lit", "osm_lit", [1.0]),
            values(shipped_registry, "lit", "osm_lit", [0.0]),
        )
        with pytest.raises(GeoError, match="resolved 'lit' twice"):
            fuse([twice], shipped_registry)

    def test_factors_come_out_in_registry_priority_order(
        self, shipped_registry: Registry
    ) -> None:
        """A provenance table is read top-down, so it must not be alphabetical."""
        fusion = fuse(
            [
                result(
                    values(shipped_registry, "curve_radius_min", "osm_geometry", [500.0]),
                    values(shipped_registry, "access_density", "osm_service_driveway", [2.0]),
                    values(shipped_registry, "lit", "osm_lit", [1.0]),
                )
            ],
            shipped_registry,
        )

        priorities = [
            shipped_registry.by_name(item.factor).drop_priority
            for item in fusion.factors
        ]
        assert priorities == sorted(priorities, reverse=True)


# ---- agreement ---------------------------------------------------------------


class TestAgreement:
    def test_a_single_source_scores_no_agreement_at_all(
        self, shipped_registry: Registry
    ) -> None:
        """Reporting 1.0 for one source would imply a corroboration that is not there."""
        fusion = fuse(
            [result(values(shipped_registry, "lit", "osm_lit", [1.0, 0.0]))],
            shipped_registry,
        )
        assert fused_for(fusion, "lit").agreements == ()

    def test_two_sources_that_match_agree(self, shipped_registry: Registry) -> None:
        fusion = fuse(
            [
                result(
                    values(shipped_registry, "speed_limit", "osm_maxspeed", [80.0, 60.0])
                ),
                result(
                    values(
                        shipped_registry,
                        "speed_limit",
                        "client_speed_survey",
                        [80.0, 62.0],
                    )
                ),
            ],
            shipped_registry,
        )
        agreement = fused_for(fusion, "speed_limit").agreements[0]

        assert agreement.score == pytest.approx(1.0)
        assert not agreement.disagrees

    def test_agreement_is_reported_as_consistency_not_corroboration(
        self, shipped_registry: Registry
    ) -> None:
        """Open sources copy from each other; matching can be an echo."""
        fusion = fuse(
            [
                result(values(shipped_registry, "lanes", "osm_lanes", [2.0])),
                result(values(shipped_registry, "lanes", "client_inventory", [2.0])),
            ],
            shipped_registry,
        )
        assert "echo" in fused_for(fusion, "lanes").agreements[0].note

    def test_a_material_difference_is_named_unit_by_unit(
        self, shipped_registry: Registry
    ) -> None:
        fusion = fuse(
            [
                result(
                    values(
                        shipped_registry,
                        "speed_limit",
                        "osm_maxspeed",
                        [80.0, 80.0, 80.0],
                    )
                ),
                result(
                    values(
                        shipped_registry,
                        "speed_limit",
                        "client_speed_survey",
                        [80.0, 40.0, 78.0],
                    )
                ),
            ],
            shipped_registry,
        )
        agreement = fused_for(fusion, "speed_limit").agreements[0]

        assert agreement.n_compared == 3
        assert agreement.n_agreeing == 2
        assert agreement.disagreeing_units == ("u-1",)
        assert agreement.max_absolute_difference == pytest.approx(40.0)

    def test_a_near_zero_pair_is_not_a_disagreement(
        self, shipped_registry: Registry
    ) -> None:
        """0.0 versus 0.1 accesses per km is nothing, but a naive ratio calls it total.

        The spread floor is what stops the denominator collapsing toward zero.
        """
        fusion = fuse(
            [
                result(
                    values(
                        shipped_registry,
                        "access_density",
                        "osm_service_driveway",
                        [0.0, 3.0, 6.0],
                    )
                ),
                result(
                    values(
                        shipped_registry,
                        "access_density",
                        "client_inventory",
                        [0.1, 3.0, 6.0],
                    )
                ),
            ],
            shipped_registry,
        )
        assert not fused_for(fusion, "access_density").agreements[0].disagrees

    def test_carried_values_are_left_out_of_the_comparison(
        self, shipped_registry: Registry
    ) -> None:
        """Comparing an imputation measures the imputation, not the sources."""
        fusion = fuse(
            [
                result(
                    values(
                        shipped_registry,
                        "speed_limit",
                        "osm_maxspeed",
                        [80.0, 80.0],
                        coverage=[1.0, 0.0],
                    )
                ),
                result(
                    values(
                        shipped_registry,
                        "speed_limit",
                        "client_speed_survey",
                        [80.0, 30.0],
                    )
                ),
            ],
            shipped_registry,
        )
        agreement = fused_for(fusion, "speed_limit").agreements[0]

        assert agreement.n_compared == 1, "the carried unit is not evidence either way"
        assert not agreement.disagrees

    def test_two_sources_that_never_overlap_are_not_corroboration(
        self, shipped_registry: Registry
    ) -> None:
        fusion = fuse(
            [
                result(
                    values(
                        shipped_registry,
                        "speed_limit",
                        "osm_maxspeed",
                        [80.0, 80.0],
                        coverage=[0.0, 0.0],
                    )
                ),
                result(
                    values(
                        shipped_registry,
                        "speed_limit",
                        "client_speed_survey",
                        [80.0, 80.0],
                        coverage=[0.0, 0.0],
                    )
                ),
            ],
            shipped_registry,
        )
        agreement = fused_for(fusion, "speed_limit").agreements[0]

        assert agreement.score is None
        assert "not corroboration" in agreement.note


# ---- confidence --------------------------------------------------------------


class TestConfidence:
    def test_a_measured_unit_is_high(self, shipped_registry: Registry) -> None:
        fusion = fuse(
            [result(values(shipped_registry, "lit", "osm_lit", [1.0], coverage=[1.0]))],
            shipped_registry,
        )
        fused = fused_for(fusion, "lit")

        assert fused.confidence.iloc[0] is Confidence.HIGH
        assert fused.reason.iloc[0] == REASON_MEASURED

    def test_a_carried_unit_is_low(self, shipped_registry: Registry) -> None:
        fusion = fuse(
            [
                result(
                    values(
                        shipped_registry, "lit", "osm_lit", [1.0, 1.0], coverage=[1.0, 0.0]
                    )
                )
            ],
            shipped_registry,
        )
        fused = fused_for(fusion, "lit")

        assert fused.confidence.iloc[1] is Confidence.LOW
        assert fused.reason.iloc[1] == REASON_CARRIED

    def test_a_thinly_covered_unit_is_medium(self, shipped_registry: Registry) -> None:
        fusion = fuse(
            [
                result(
                    values(
                        shipped_registry, "lit", "osm_lit", [1.0, 1.0], coverage=[1.0, 0.3]
                    )
                )
            ],
            shipped_registry,
        )
        fused = fused_for(fusion, "lit")

        assert fused.confidence.iloc[1] is Confidence.MEDIUM
        assert fused.reason.iloc[1] == REASON_THIN

    def test_a_contradicted_unit_is_low_even_though_it_was_measured(
        self, shipped_registry: Registry
    ) -> None:
        """Disagreement is strong evidence: one of the two is definitely wrong."""
        fusion = fuse(
            [
                result(
                    values(
                        shipped_registry, "speed_limit", "osm_maxspeed", [80.0, 80.0]
                    )
                ),
                result(
                    values(
                        shipped_registry,
                        "speed_limit",
                        "client_speed_survey",
                        [80.0, 30.0],
                    )
                ),
            ],
            shipped_registry,
        )
        fused = fused_for(fusion, "speed_limit")

        assert fused.confidence.iloc[0] is Confidence.HIGH
        assert fused.confidence.iloc[1] is Confidence.LOW
        assert fused.reason.iloc[1] == REASON_CONTRADICTED

    def test_agreement_does_not_promote_a_unit(
        self, shipped_registry: Registry
    ) -> None:
        """Asymmetric on purpose. Agreement between open sources can be an echo."""
        alone = fuse(
            [result(values(shipped_registry, "lanes", "osm_lanes", [2.0]))],
            shipped_registry,
        )
        corroborated = fuse(
            [
                result(values(shipped_registry, "lanes", "osm_lanes", [2.0])),
                result(values(shipped_registry, "lanes", "client_inventory", [2.0])),
            ],
            shipped_registry,
        )

        assert fused_for(alone, "lanes").confidence.iloc[0] is Confidence.HIGH
        assert fused_for(corroborated, "lanes").confidence.iloc[0] is Confidence.HIGH

    def test_a_tier_b_value_is_never_high(self, shipped_registry: Registry) -> None:
        """Nobody stated it; we inferred it. That is a different kind of number."""
        fusion = fuse(
            [
                result(
                    values(
                        shipped_registry,
                        "roadside_object_density",
                        "mapillary_detections",
                        [4.0],
                    )
                )
            ],
            shipped_registry,
        )
        fused = fused_for(fusion, "roadside_object_density")

        assert fused.chosen.tier is Tier.B
        assert fused.confidence.iloc[0] is Confidence.MEDIUM

    def test_the_confidence_frame_is_one_row_per_factor_per_unit(
        self, shipped_registry: Registry
    ) -> None:
        """The literal deliverable of step 2.7."""
        fusion = fuse(
            [
                result(
                    values(shipped_registry, "lit", "osm_lit", [1.0, 0.0]),
                    values(shipped_registry, "lanes", "osm_lanes", [2.0, 2.0]),
                )
            ],
            shipped_registry,
        )
        frame = fusion.confidence_frame()

        assert len(frame) == 4
        assert set(frame["factor"]) == {"lit", "lanes"}
        assert set(frame.columns) >= {"unit_id", "confidence", "reason", "tier", "value"}


# ---- client data ---------------------------------------------------------------


class TestClientValues:
    def test_the_client_slot_is_identified_by_tier_not_by_name(
        self, shipped_registry: Registry
    ) -> None:
        """The slots are named for what is supplied, so the name cannot be matched on."""
        assert client_slot(shipped_registry.by_name("speed_limit")) == "client_speed_survey"
        assert client_slot(shipped_registry.by_name("grade_pct")) == "client_survey"
        assert client_slot(shipped_registry.by_name("curve_density")) == "client_alignment"

    def test_night_ratio_has_no_client_slot(self, shipped_registry: Registry) -> None:
        """Its only adapter is licensed `client` but is Tier A — derived, not supplied.

        Matching on the licence rather than the tier would wrongly pick it up.
        """
        assert client_slot(shipped_registry.by_name("night_ratio")) is None

    def test_a_client_column_becomes_a_tier_d_value(
        self, units, shipped_registry: Registry
    ) -> None:
        frame = pd.DataFrame(
            {
                "unit_id": units.unit_ids,
                "speed_limit": [90.0] * len(units),
            }
        )
        outcome = read_client_values(frame, units, registry=shipped_registry)

        assert len(outcome.resolved) == 1
        assert outcome.resolved[0].tier is Tier.D
        assert outcome.resolved[0].licence is Licence.CLIENT

    def test_columns_that_match_no_factor_are_reported_not_dropped_silently(
        self, units, shipped_registry: Registry
    ) -> None:
        frame = pd.DataFrame(
            {
                "unit_id": units.unit_ids,
                "speed_limit": [90.0] * len(units),
                "pavement_colour": ["grey"] * len(units),
            }
        )
        outcome = read_client_values(frame, units, registry=shipped_registry)

        assert any("pavement_colour" in note for note in outcome.notes)

    def test_a_hole_in_a_client_survey_is_a_question_not_a_gap_to_fill(
        self, units, shipped_registry: Registry
    ) -> None:
        """OSM carries a short gap because nobody wrote the tag down.

        A survey that skipped a unit is different: they went and looked, and this unit
        is not in the answer.
        """
        speeds: list[float | None] = [90.0] * len(units)
        speeds[2] = None
        frame = pd.DataFrame({"unit_id": units.unit_ids, "speed_limit": speeds})

        outcome = read_client_values(frame, units, registry=shipped_registry)

        assert outcome.resolved == []
        assert "no client value" in outcome.skipped[0].reason

    def test_a_factor_with_no_client_slot_says_so(
        self, units, shipped_registry: Registry
    ) -> None:
        frame = pd.DataFrame(
            {"unit_id": units.unit_ids, "population_density": [100.0] * len(units)}
        )
        outcome = read_client_values(frame, units, registry=shipped_registry)

        assert "no Tier D adapter" in outcome.skipped[0].reason

    def test_unit_ids_from_another_corridor_are_refused(
        self, units, shipped_registry: Registry
    ) -> None:
        frame = pd.DataFrame({"unit_id": ["somewhere-else-0001"], "lanes": [2.0]})

        with pytest.raises(GeoError, match="does not have"):
            read_client_values(frame, units, registry=shipped_registry)

    def test_a_repeated_unit_id_is_refused(
        self, units, shipped_registry: Registry
    ) -> None:
        repeated = units.unit_ids[0]
        frame = pd.DataFrame({"unit_id": [repeated, repeated], "lanes": [2.0, 3.0]})

        with pytest.raises(GeoError, match="repeat unit id"):
            read_client_values(frame, units, registry=shipped_registry)

    def test_a_missing_unit_column_names_the_fix(
        self, units, shipped_registry: Registry
    ) -> None:
        with pytest.raises(GeoError, match="Run the pipeline once"):
            read_client_values(
                pd.DataFrame({"lanes": [2.0]}), units, registry=shipped_registry
            )


# ---- the pipeline ----------------------------------------------------------------


class TestPipelineIntegration:
    def test_client_data_beats_osm_and_the_disagreement_is_named(
        self, units
    ) -> None:
        """The whole of 2.7 in one run: two sources, a winner, and a named difference."""
        client = pd.DataFrame(
            {
                "unit_id": units.unit_ids,
                "speed_limit": [90.0, 90.0, 90.0, 40.0, 90.0, 90.0],
            }
        )
        built = build_corridor_panel(
            [(lat, lon) for lon, lat in straight()],
            periods=["2024-01"],
            name="B9",
            target_length_m=UNIT_M,
            ref="B9",
            osm_client=client_returning(
                way(straight(), ref="B9", maxspeed="90", lanes="2")
            ),
            client_values=client,
            client_source="2024 asset inventory",
        )

        speeds = built.panel.drop_duplicates("unit_id")["speed_limit"]
        assert speeds.tolist() == [90.0, 90.0, 90.0, 40.0, 90.0, 90.0]
        assert "speed_limit" in built.contested

        provenance = built.provenance.set_index("column")
        assert provenance.loc["speed_limit", "adapter"] == "client_speed_survey"
        assert provenance.loc["speed_limit", "contested_by"] == "osm_maxspeed"
        # The provenance table rounds to 4dp - it is a display frame, not a fixture.
        assert provenance.loc["speed_limit", "agreement"] == pytest.approx(
            5 / 6, abs=1e-4
        )

        disagreement = built.fusion.disagreements[0]
        assert disagreement.column == "speed_limit"
        assert disagreement.disagreeing_units == (units.unit_ids[3],)

    def test_the_disagreeing_unit_is_the_only_low_confidence_one(self, units) -> None:
        client = pd.DataFrame(
            {
                "unit_id": units.unit_ids,
                "speed_limit": [90.0, 90.0, 90.0, 40.0, 90.0, 90.0],
            }
        )
        built = build_corridor_panel(
            [(lat, lon) for lon, lat in straight()],
            periods=["2024-01"],
            name="B9",
            target_length_m=UNIT_M,
            ref="B9",
            osm_client=client_returning(way(straight(), ref="B9", maxspeed="90")),
            client_values=client,
        )

        confidence = built.confidence
        speed = confidence[confidence["factor"] == "speed_limit"].set_index("unit_id")

        assert speed.loc[units.unit_ids[3], "confidence"] == "low"
        assert speed.loc[units.unit_ids[3], "reason"] == REASON_CONTRADICTED
        assert (speed.drop(units.unit_ids[3])["confidence"] == "high").all()

    def test_a_confidence_row_exists_for_every_factor_and_unit(self, units) -> None:
        built = build_corridor_panel(
            [(lat, lon) for lon, lat in straight()],
            periods=["2024-01"],
            name="B9",
            target_length_m=UNIT_M,
        )
        confidence = built.confidence

        assert len(confidence) == len(built.factor_columns) * built.n_units
        assert set(confidence["unit_id"]) == set(units.unit_ids)

    def test_provenance_shows_the_uncontested_factors_as_uncontested(
        self, units
    ) -> None:
        built = build_corridor_panel(
            [(lat, lon) for lon, lat in straight()],
            periods=["2024-01"],
            name="B9",
            target_length_m=UNIT_M,
        )
        provenance = built.provenance

        assert (provenance["contested_by"] == "").all()
        assert provenance["agreement"].isna().all()
        assert built.fusion.disagreements == []


def test_provenance_frame_reports_confidence_alongside_licence(
    shipped_registry: Registry,
) -> None:
    fusion = fuse(
        [
            result(
                values(
                    shipped_registry, "lit", "osm_lit", [1.0, 1.0], coverage=[1.0, 0.0]
                )
            )
        ],
        shipped_registry,
    )
    row = provenance_frame(fusion).iloc[0]

    assert row["licence"] == "ODbL"
    assert row["confidence_high"] == pytest.approx(0.5)
    assert row["confidence_low"] == pytest.approx(0.5)
