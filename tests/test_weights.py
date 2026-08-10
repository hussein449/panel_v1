"""Weight selection, agreement scoring, and the concerns both raise."""

from __future__ import annotations

import pandas as pd
import pytest

from roadrisk.core.context import RunContext
from roadrisk.core.engine import assess
from roadrisk.core.registry import (
    Adapter,
    CrashScope,
    FacilityType,
    Factor,
    Licence,
    Region,
    Severity,
    Sign,
    Tier,
    Transform,
    Weight,
    WeightFamily,
)
from roadrisk.core.weights import (
    WeightSelection,
    assess_agreement,
    region_distance,
    select_weight,
)

ADAPTER = Adapter(name="osm", tier=Tier.A, licence=Licence.ODBL)


def make_factor(*weights: Weight, sign: Sign = Sign.POSITIVE) -> Factor:
    return Factor(
        name="grade_pct",
        label="Gradient",
        column="grade_pct",
        transform=Transform.LN1P,
        expected_sign=sign,
        drop_priority=10,
        missing_behaviour="Vertical alignment leaves the model.",
        adapters=[ADAPTER],
        weights=list(weights),
    )


def make_weight(
    value: float,
    *,
    family: WeightFamily = WeightFamily.HSM,
    facility: FacilityType = FacilityType.ANY,
    region: Region = Region.GLOBAL,
    severity: Severity = Severity.ALL,
    scope: CrashScope = CrashScope.TOTAL,
    assumes: dict[str, float] | None = None,
    caveat: str | None = None,
) -> Weight:
    return Weight(
        value=value,
        source="test citation",
        family=family,
        facility_type=facility,
        region=region,
        severity=severity,
        scope=scope,
        assumes=assumes or {},
        caveat=caveat,
    )


class TestAdmissibility:
    def test_facility_restricted_weight_is_inadmissible_elsewhere(self) -> None:
        factor = make_factor(
            make_weight(0.2, facility=FacilityType.RURAL_TWO_LANE)
        )
        context = RunContext(facility_type=FacilityType.URBAN_ARTERIAL)

        assert select_weight(factor, context) is None

    def test_unrestricted_weight_is_admissible_anywhere(self) -> None:
        factor = make_factor(make_weight(0.2, facility=FacilityType.ANY))
        context = RunContext(facility_type=FacilityType.URBAN_ARTERIAL)

        selection = select_weight(factor, context)
        assert selection is not None
        assert selection.selected.value == 0.2

    def test_undeclared_facility_admits_only_unrestricted_weights(self) -> None:
        """The engine does not guess what kind of road it was handed."""
        factor = make_factor(
            make_weight(0.2, facility=FacilityType.RURAL_TWO_LANE)
        )
        assert select_weight(factor, RunContext()) is None

    def test_fatal_weight_never_scores_an_injury_panel(self) -> None:
        """1.6 versus 4.1 is a factor-of-two error, not a nuance."""
        factor = make_factor(make_weight(4.1, severity=Severity.FATAL))
        assert select_weight(factor, RunContext(severity=Severity.INJURY)) is None

    def test_all_severity_weight_applies_to_any_panel(self) -> None:
        factor = make_factor(make_weight(0.2, severity=Severity.ALL))
        selection = select_weight(factor, RunContext(severity=Severity.FATAL))
        assert selection is not None

    def test_region_is_not_a_filter(self) -> None:
        """Filtering on region would leave nothing usable outside North America."""
        factor = make_factor(make_weight(0.2, region=Region.NORTH_AMERICA))
        selection = select_weight(factor, RunContext(region=Region.EUROPE))

        assert selection is not None
        assert any(c.code == "region_transfer" for c in selection.concerns)


class TestRegionPreference:
    """Where the corridor is beats which body of evidence we would otherwise prefer."""

    def test_local_evidence_beats_global(self) -> None:
        factor = make_factor(
            make_weight(0.1, family=WeightFamily.IRAP, region=Region.GLOBAL),
            make_weight(0.9, family=WeightFamily.HSM, region=Region.EUROPE),
        )
        selection = select_weight(factor, RunContext(region=Region.EUROPE))

        assert selection is not None
        assert selection.selected.value == 0.9

    def test_global_beats_another_regions_evidence(self) -> None:
        """A Cyprus road must not be scored on US evidence when a global one exists.

        This was a real bug: region ranked as a flat exact/not-exact, so global and
        North American tied on a European run and the family preference broke the tie.
        """
        factor = make_factor(
            make_weight(0.1, family=WeightFamily.HSM, region=Region.NORTH_AMERICA),
            make_weight(0.9, family=WeightFamily.ELVIK, region=Region.GLOBAL),
        )
        selection = select_weight(factor, RunContext(region=Region.EUROPE))

        assert selection is not None
        assert selection.selected.region is Region.GLOBAL
        assert not any(c.code == "region_transfer" for c in selection.concerns)

    def test_foreign_evidence_is_used_only_as_a_last_resort(self) -> None:
        factor = make_factor(make_weight(0.2, region=Region.NORTH_AMERICA))
        selection = select_weight(factor, RunContext(region=Region.MIDDLE_EAST))

        assert selection is not None
        concern = next(c for c in selection.concerns if c.code == "region_transfer")
        assert "middle_east" in concern.message
        assert "reached for another region's evidence" in concern.message

    def test_region_outranks_family_preference(self) -> None:
        """iRAP is the default family, but not at the cost of using foreign evidence."""
        factor = make_factor(
            make_weight(0.1, family=WeightFamily.IRAP, region=Region.NORTH_AMERICA),
            make_weight(0.9, family=WeightFamily.HSM, region=Region.EUROPE),
        )
        selection = select_weight(factor, RunContext(region=Region.EUROPE))

        assert selection is not None
        assert selection.selected.family is WeightFamily.HSM

    def test_distance_ordering(self) -> None:
        assert region_distance(Region.EUROPE, Region.EUROPE) == 0
        assert region_distance(Region.GLOBAL, Region.EUROPE) == 1
        assert region_distance(Region.NORTH_AMERICA, Region.EUROPE) == 2

    def test_region_outranks_facility_specificity(self) -> None:
        """A global unrestricted weight beats a foreign facility-exact one.

        Facility mismatch is already caught by admissibility, so this dimension only
        separates "exact" from "unrestricted" — and unrestricted is not wrong, just
        less specific. Region transfer is a real error, so it wins.
        """
        factor = make_factor(
            make_weight(
                0.1,
                family=WeightFamily.HSM,
                facility=FacilityType.RURAL_TWO_LANE,
                region=Region.NORTH_AMERICA,
            ),
            make_weight(
                0.9,
                family=WeightFamily.IRAP,
                facility=FacilityType.ANY,
                region=Region.GLOBAL,
            ),
        )
        selection = select_weight(
            factor,
            RunContext(
                facility_type=FacilityType.RURAL_TWO_LANE, region=Region.EUROPE
            ),
        )

        assert selection is not None
        assert selection.selected.family is WeightFamily.IRAP
        assert not any(c.code == "region_transfer" for c in selection.concerns)

    def test_a_us_run_still_gets_the_us_weight(self) -> None:
        """The mirror case — region preference must cut both ways."""
        factor = make_factor(
            make_weight(
                0.1,
                family=WeightFamily.HSM,
                facility=FacilityType.RURAL_TWO_LANE,
                region=Region.NORTH_AMERICA,
            ),
            make_weight(0.9, family=WeightFamily.IRAP, region=Region.GLOBAL),
        )
        selection = select_weight(
            factor,
            RunContext(
                facility_type=FacilityType.RURAL_TWO_LANE,
                region=Region.NORTH_AMERICA,
            ),
        )

        assert selection is not None
        assert selection.selected.family is WeightFamily.HSM

    def test_uncited_factor_selects_nothing(self) -> None:
        assert select_weight(make_factor(), RunContext()) is None


class TestSelectionOrder:
    def test_exact_facility_beats_unrestricted(self) -> None:
        factor = make_factor(
            make_weight(0.1, facility=FacilityType.ANY, family=WeightFamily.IRAP),
            make_weight(0.9, facility=FacilityType.RURAL_TWO_LANE),
        )
        selection = select_weight(
            factor, RunContext(facility_type=FacilityType.RURAL_TWO_LANE)
        )

        assert selection is not None
        assert selection.selected.value == 0.9

    def test_irap_wins_a_tie_on_context(self) -> None:
        """Global and cross-sectional by construction — the right default."""
        factor = make_factor(
            make_weight(0.1, family=WeightFamily.HSM),
            make_weight(0.9, family=WeightFamily.IRAP),
        )
        selection = select_weight(factor, RunContext())

        assert selection is not None
        assert selection.selected.family is WeightFamily.IRAP

    def test_alternatives_and_rejections_are_kept_separate(self) -> None:
        factor = make_factor(
            make_weight(0.1, family=WeightFamily.IRAP),
            make_weight(0.2, family=WeightFamily.HSM),
            make_weight(0.3, family=WeightFamily.ELVIK, severity=Severity.FATAL),
        )
        selection = select_weight(factor, RunContext(severity=Severity.INJURY))

        assert selection is not None
        assert len(selection.alternatives) == 1
        assert len(selection.rejected) == 1


class TestAgreement:
    def test_single_source_has_no_agreement(self) -> None:
        """A lone source cannot corroborate itself, and 1.0 would imply it had."""
        factor = make_factor(make_weight(0.2))
        selection = select_weight(factor, RunContext())

        assert selection is not None
        assert assess_agreement(selection) is None

    def test_close_values_score_high(self) -> None:
        factor = make_factor(
            make_weight(0.20, family=WeightFamily.IRAP),
            make_weight(0.18, family=WeightFamily.HSM),
        )
        agreement = assess_agreement(select_weight(factor, RunContext()))

        assert agreement is not None
        assert agreement.comparable
        assert agreement.score == pytest.approx(0.9)

    def test_distant_values_score_low(self) -> None:
        factor = make_factor(
            make_weight(0.48, family=WeightFamily.IRAP),
            make_weight(0.12, family=WeightFamily.HSM),
        )
        agreement = assess_agreement(select_weight(factor, RunContext()))

        assert agreement is not None
        assert agreement.score == pytest.approx(0.25)

    def test_sign_conflict_scores_zero_and_is_flagged(self) -> None:
        """Two sources pointing opposite ways scores zero and is never averaged.

        The selection is built directly rather than loaded from a registry, because a
        registry *cannot* produce this state: every weight is validated against the
        factor's `expected_sign` at load, so a source contradicting the declared
        mechanism is refused before it gets here (see
        `test_checks_every_weight_not_just_the_first`). This path is defence in depth
        for programmatic construction — cheap, and the alternative is silently
        averaging a contradiction if that validator is ever relaxed.
        """
        selection = WeightSelection(
            factor="grade_pct",
            selected=make_weight(0.2, family=WeightFamily.IRAP),
            alternatives=[make_weight(-0.2, family=WeightFamily.HSM)],
        )
        agreement = assess_agreement(selection)

        assert agreement is not None
        assert agreement.score == 0.0
        assert agreement.signs_conflict
        assert "do not average" in agreement.note

    def test_the_registry_cannot_produce_a_sign_conflict(self) -> None:
        """Stated as a test so the guarantee is visible, not just implied."""
        with pytest.raises(Exception, match="must not ship a contradiction"):
            make_factor(
                make_weight(0.2, family=WeightFamily.IRAP),
                make_weight(-0.2, family=WeightFamily.HSM),
                sign=Sign.POSITIVE,
            )

    def test_different_scopes_are_not_comparable(self) -> None:
        """HSM prices total crashes; iRAP's grade factor prices run-off and head-on."""
        factor = make_factor(
            make_weight(0.12, family=WeightFamily.HSM, scope=CrashScope.TOTAL),
            make_weight(
                0.48, family=WeightFamily.IRAP, scope=CrashScope.RUN_OFF_HEAD_ON
            ),
        )
        agreement = assess_agreement(select_weight(factor, RunContext()))

        assert agreement is not None
        assert not agreement.comparable
        assert agreement.score is None
        assert not agreement.signs_conflict
        assert "not measuring the same quantity" in agreement.note


class TestConcerns:
    def test_intrinsic_caveat_always_surfaces(self) -> None:
        factor = make_factor(make_weight(1.6, caveat="posted is not operating speed"))
        selection = select_weight(factor, RunContext())

        assert selection is not None
        assert any(c.code == "weight_caveat" for c in selection.concerns)

    def test_assumption_mismatch_is_flagged(self) -> None:
        factor = make_factor(make_weight(0.19, assumes={"segment_length_km": 0.5}))
        selection = select_weight(
            factor, RunContext(segment_length_km=2.0)
        )

        assert selection is not None
        concern = next(
            c for c in selection.concerns if c.code == "assumption_segment_length_km"
        )
        assert "300%" in concern.message

    def test_assumption_within_tolerance_is_silent(self) -> None:
        factor = make_factor(make_weight(0.19, assumes={"segment_length_km": 0.5}))
        selection = select_weight(factor, RunContext(segment_length_km=0.55))

        assert selection is not None
        assert not any(c.code.startswith("assumption_") for c in selection.concerns)

    def test_unmeasured_assumption_cannot_be_checked(self) -> None:
        factor = make_factor(make_weight(0.17, assumes={"reference_aadt": 10000}))
        selection = select_weight(factor, RunContext())

        assert selection is not None
        assert not any(c.code.startswith("assumption_") for c in selection.concerns)


class TestContextInTheEngine:
    def test_segment_length_is_measured_not_declared(
        self, crash_only_panel: pd.DataFrame
    ) -> None:
        """So the assumption check cannot be gamed by declaring a convenient value."""
        result = assess(crash_only_panel)
        assert result.context.segment_length_km == pytest.approx(0.5)

    def test_declaring_a_facility_admits_better_matched_weights(
        self, crash_only_panel: pd.DataFrame
    ) -> None:
        undeclared = assess(crash_only_panel)
        declared = assess(
            crash_only_panel,
            context=RunContext(
                facility_type=FacilityType.RURAL_TWO_LANE,
                region=Region.NORTH_AMERICA,
            ),
        )

        assert undeclared.index is not None
        assert declared.index is not None
        assert len(declared.index.terms) > len(undeclared.index.terms)

    def test_context_reaches_the_manifest_and_the_payload(
        self, crash_only_panel: pd.DataFrame
    ) -> None:
        result = assess(
            crash_only_panel,
            context=RunContext(facility_type=FacilityType.RURAL_TWO_LANE),
        )
        payload = result.as_dict()

        assert payload["context"]["facility_type"] == "rural_two_lane"
        assert payload["context"]["declared"] is True
        assert result.manifest.settings["facility_type"] == "rural_two_lane"

    def test_context_changes_the_run_fingerprint(
        self, crash_only_panel: pd.DataFrame
    ) -> None:
        """Two runs that used different weights must not fingerprint identically."""
        a = assess(crash_only_panel)
        b = assess(
            crash_only_panel,
            context=RunContext(facility_type=FacilityType.RURAL_TWO_LANE),
        )
        assert a.manifest.fingerprint != b.manifest.fingerprint

    def test_severity_selects_the_right_speed_exponent(
        self, crash_only_panel: pd.DataFrame
    ) -> None:
        injury = assess(crash_only_panel, context=RunContext(severity=Severity.INJURY))
        fatal = assess(crash_only_panel, context=RunContext(severity=Severity.FATAL))

        assert injury.index is not None
        assert fatal.index is not None
        injury_speed = next(t for t in injury.index.terms if t.factor == "speed_limit")
        fatal_speed = next(t for t in fatal.index.terms if t.factor == "speed_limit")

        assert injury_speed.weight == pytest.approx(1.6)
        assert fatal_speed.weight == pytest.approx(4.1)

    def test_undeclared_severity_admits_neither_speed_exponent(
        self, crash_only_panel: pd.DataFrame
    ) -> None:
        """Both Elvik weights are severity-specific, so 'all' matches neither."""
        result = assess(crash_only_panel)

        assert result.index is not None
        assert "speed_limit" in result.index.skipped_inadmissible

    def test_weight_selection_is_logged_per_factor(
        self, crash_only_panel: pd.DataFrame
    ) -> None:
        result = assess(crash_only_panel, context=RunContext(severity=Severity.INJURY))
        selections = [e for e in result.log if e.code == "weight_selected"]

        assert result.index is not None
        assert len(selections) == len(result.index.terms)
