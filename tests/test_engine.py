"""End-to-end behaviour: mode selection, descent, refusal, reproducibility."""

from __future__ import annotations

import pandas as pd
import pytest

from roadrisk.core.engine import assess
from roadrisk.core.errors import ContractViolation
from roadrisk.core.ladder import Mode, Rung, _screen_for_variation
from roadrisk.core.registry import (
    Adapter,
    Factor,
    Licence,
    Sign,
    Tier,
    Transform,
)
from roadrisk.core.runlog import RunLog
from roadrisk.demo import TRUE_EFFECTS, synthetic_panel


class TestModeA:
    def test_rich_panel_reaches_the_top_rung(self, rich_panel: pd.DataFrame) -> None:
        result = assess(rich_panel)

        assert result.mode is Mode.A
        assert result.rung is Rung.A_FULL
        assert result.fit is not None
        assert result.fit.converged
        assert result.descent_receipt is None
        assert "MODE A" in result.banner

    def test_recovers_the_planted_coefficients(self, rich_panel: pd.DataFrame) -> None:
        """If a planted sign comes back wrong, that is an engine bug, not a finding."""
        result = assess(rich_panel)
        assert result.fit is not None

        for coefficient in result.fit.coefficients:
            truth = TRUE_EFFECTS[coefficient.factor]
            assert coefficient.sign == (1 if truth > 0 else -1), coefficient.factor

    def test_top_rung_caps_the_specification_at_seven_factors(
        self, rich_panel: pd.DataFrame
    ) -> None:
        result = assess(rich_panel)
        assert len(result.factor_names) == 7
        assert len(result.available_factors) == 8

    def test_poisson_reference_is_fitted_but_not_shipped(
        self, rich_panel: pd.DataFrame
    ) -> None:
        result = assess(rich_panel)
        assert result.ladder.reference_poisson is not None
        assert result.ladder.reference_poisson.converged
        assert result.fit is not None
        assert "Negative binomial" in result.fit.specification

    def test_absent_columns_are_reported_with_what_was_lost(
        self, rich_panel: pd.DataFrame
    ) -> None:
        result = assess(rich_panel)
        assert result.missing_factors
        assert all(f.missing_behaviour for f in result.missing_factors)

        absences = [e for e in result.log if e.code == "column_absent"]
        assert len(absences) == len(result.missing_factors)


class TestDescent:
    def test_sparse_panel_steps_down_and_says_why(
        self, sparse_panel: pd.DataFrame
    ) -> None:
        result = assess(sparse_panel)

        assert result.mode is Mode.A
        assert result.rung in {Rung.A_REDUCED, Rung.A_MINIMAL}
        assert result.descent_receipt is not None
        assert "Attempted A-full" in result.descent_receipt
        assert "crashes available" in result.descent_receipt
        assert "by registry priority" in result.descent_receipt

    def test_descent_drops_by_registry_priority(
        self, sparse_panel: pd.DataFrame
    ) -> None:
        result = assess(sparse_panel)
        # Among factors that vary here. A factor demoted for holding one value along
        # most of the corridor is ordered by that, not by its registry priority.
        demoted = set(result.ladder.demoted_for_no_variation)
        kept = {f.drop_priority for f in result.ladder.factors if f.name not in demoted}
        dropped = {
            f.drop_priority
            for f in result.available_factors
            if f.name not in result.ladder.factor_names and f.name not in demoted
        }
        assert min(kept) > max(dropped)

    def test_every_descent_is_logged(self, sparse_panel: pd.DataFrame) -> None:
        result = assess(sparse_panel)
        descents = [e for e in result.log if e.level.value == "descent"]
        assert len(descents) == len(result.ladder.descent)


class TestVariationScreen:
    """A rung's seats should not go to a factor that is flat on this corridor.

    The A3 through Paris spent one on `poi_density`, zero across 84% of the road and
    correlating with crashes at 0.05, while `landuse_urban` — varying on every segment,
    correlating at 0.46 — never entered the model.
    """

    def factor(self, name: str, priority: int) -> Factor:
        return Factor(
            name=name,
            label=name,
            column=name,
            transform=Transform.IDENTITY,
            expected_sign=Sign.POSITIVE,
            drop_priority=priority,
            missing_behaviour="lost",
            adapters=[Adapter(name="osm", tier=Tier.A, licence=Licence.ODBL)],
        )

    def test_a_flat_factor_loses_its_seat_to_one_that_varies(self) -> None:
        """Higher registry priority no longer beats having something to say."""
        flat = self.factor("flat", priority=90)
        varied = self.factor("varied", priority=10)
        design = pd.DataFrame(
            {"flat": [0.0] * 17 + [1.0, 2.0, 3.0], "varied": list(range(20))}
        )

        order, demoted = _screen_for_variation(design, [flat, varied], RunLog())

        assert [f.name for f in order] == ["varied", "flat"]
        assert demoted == ["flat"]

    def test_a_factor_that_varies_keeps_its_registry_place(self) -> None:
        high = self.factor("high", priority=90)
        low = self.factor("low", priority=10)
        design = pd.DataFrame({"high": list(range(20)), "low": list(range(20))})

        order, demoted = _screen_for_variation(design, [high, low], RunLog())

        assert [f.name for f in order] == ["high", "low"]
        assert demoted == []

    def test_a_concentrated_factor_is_not_dropped_only_moved(self) -> None:
        """Demotion must never shrink a model that had room for the term."""
        flat = self.factor("flat", priority=90)
        design = pd.DataFrame({"flat": [0.0] * 19 + [1.0]})

        order, demoted = _screen_for_variation(design, [flat], RunLog())

        assert [f.name for f in order] == ["flat"], "still available to fit"
        assert demoted == ["flat"]

    def test_the_threshold_sits_above_the_strongest_term_the_a3_had(self) -> None:
        """`access_density` held one value on 76% of the A3 and was still its best term.

        A threshold at or below that would have thrown away the finding the corridor
        exists to demonstrate, so concentration alone can never be disqualifying.
        """
        best = self.factor("access_density", priority=90)
        design = pd.DataFrame({"access_density": [0.0] * 28 + [1.0] * 9})

        _, demoted = _screen_for_variation(design, [best], RunLog())

        assert demoted == [], "76% concentration must survive the screen"

    def test_a_balanced_flag_is_never_demoted(self) -> None:
        lit = self.factor("lit", priority=45)
        design = pd.DataFrame({"lit": [0.0] * 13 + [1.0] * 24})

        _, demoted = _screen_for_variation(design, [lit], RunLog())

        assert demoted == []

    def test_the_demotion_is_logged_with_the_share(self) -> None:
        flat = self.factor("flat", priority=90)
        design = pd.DataFrame({"flat": [0.0] * 19 + [1.0]})
        log = RunLog()

        _screen_for_variation(design, [flat], log)

        event = next(e for e in log if e.code == "low_variation")
        assert "95%" in event.message
        assert "still fitted if the rung has room" in event.message

    def test_it_reaches_the_payload(self, rich_panel: pd.DataFrame) -> None:
        payload = assess(rich_panel).as_dict()

        assert "demoted_for_no_variation" in payload["factors"]


class TestRefusal:
    def test_crash_only_panel_is_refused(self, crash_only_panel: pd.DataFrame) -> None:
        result = assess(crash_only_panel)

        assert result.mode is Mode.B
        assert result.rung is Rung.B
        assert result.fit is None
        assert result.refusal_receipt is not None
        assert "Mode A was not available" in result.refusal_receipt
        assert "supply the full corridor extent" in result.refusal_receipt.lower()

    def test_refusal_is_recorded_in_the_log(
        self, crash_only_panel: pd.DataFrame
    ) -> None:
        result = assess(crash_only_panel)
        refusals = [e for e in result.log if e.level.value == "refusal"]
        assert any(e.code == "mode_a_refused" for e in refusals)

    def test_starved_panel_falls_to_the_mode_b_floor(
        self, starved_panel: pd.DataFrame
    ) -> None:
        result = assess(starved_panel)

        assert result.mode is Mode.B
        assert result.fit is None
        assert result.descent_receipt is not None
        assert "The result is Mode B" in result.descent_receipt

    def test_there_is_no_mode_override(self) -> None:
        """The absence of this parameter is a product decision, not an oversight."""
        import inspect

        parameters = inspect.signature(assess).parameters
        assert not {"mode", "force_mode", "rung"} & set(parameters)


class TestModeB:
    def test_refuses_outright_when_nothing_is_cited(
        self, crash_only_panel: pd.DataFrame, unsourced_registry
    ) -> None:
        result = assess(crash_only_panel, registry=unsourced_registry)

        assert result.index is None
        assert result.index_refusal is not None
        assert "no available factor yields a usable weight" in result.index_refusal

    def test_scores_on_the_cited_subset_and_names_the_skips(
        self, crash_only_panel: pd.DataFrame
    ) -> None:
        """Degrade loudly: an uncited factor is absent, not silently weighted zero."""
        result = assess(crash_only_panel)

        assert result.index is not None
        assert result.index_refusal is None

        scored = set(result.index.factor_names)
        skipped = set(result.index.skipped_unsourced)

        assert scored, "the shipped registry should now carry some cited weights"
        assert skipped, "the shipped registry still has uncited factors"
        assert not scored & skipped

    def test_skipped_factors_are_warned_about_in_the_log(
        self, crash_only_panel: pd.DataFrame
    ) -> None:
        result = assess(crash_only_panel)
        assert any(e.code == "unsourced_skipped" for e in result.log)

    def test_every_scored_term_carries_a_citation(
        self, crash_only_panel: pd.DataFrame
    ) -> None:
        result = assess(crash_only_panel)
        assert result.index is not None
        assert all(term.weight_source.strip() for term in result.index.terms)

    def test_scores_when_weights_carry_citations(
        self, crash_only_panel: pd.DataFrame, sourced_registry
    ) -> None:
        result = assess(crash_only_panel, registry=sourced_registry)

        assert result.mode is Mode.B
        assert result.index is not None
        assert result.index_refusal is None
        assert result.index.n_units == crash_only_panel["unit_id"].nunique()
        assert all(term.weight_source for term in result.index.terms)

    def test_ranking_is_ordered_worst_first(
        self, crash_only_panel: pd.DataFrame, sourced_registry
    ) -> None:
        result = assess(crash_only_panel, registry=sourced_registry)
        assert result.index is not None

        scores = result.index.unit_ranking["score"].tolist()
        assert scores == sorted(scores, reverse=True)
        assert result.index.unit_ranking["rank"].iloc[0] == 1

    def test_mode_b_result_cannot_carry_a_count(
        self, crash_only_panel: pd.DataFrame, sourced_registry
    ) -> None:
        """Structural, not conventional — there is no field to put one in.

        The invariant is *no counts and no uncertainty*, not a fixed column list. The
        ranking also carries a per-crash-type score column so a bad unit can be read
        for which kind of problem it has; those are scores, not predictions.
        """
        result = assess(crash_only_panel, registry=sourced_registry)
        assert result.index is not None

        fields = set(vars(result.index))
        assert not fields & {"predicted_counts", "confidence_intervals", "p_values"}

        columns = set(result.index.unit_ranking.columns)
        assert {"unit_id", "score", "rank", "percentile"} <= columns
        assert not columns & {
            "predicted",
            "predicted_crashes",
            "expected_crashes",
            "ci_low",
            "ci_high",
            "p_value",
            "std_error",
        }
        extra = columns - {"unit_id", "score", "rank", "percentile"}
        assert all(name.startswith("score_") for name in extra), extra


class TestReproducibility:
    def test_identical_inputs_fingerprint_identically(
        self, rich_panel: pd.DataFrame
    ) -> None:
        first = assess(rich_panel)
        second = assess(rich_panel)
        assert first.manifest.fingerprint == second.manifest.fingerprint

    def test_changed_data_changes_the_fingerprint(
        self, rich_panel: pd.DataFrame
    ) -> None:
        altered = rich_panel.copy()
        altered.loc[0, "n_crashes"] = altered.loc[0, "n_crashes"] + 1

        assert (
            assess(rich_panel).manifest.fingerprint
            != assess(altered).manifest.fingerprint
        )

    def test_changed_registry_changes_the_fingerprint(
        self, crash_only_panel: pd.DataFrame, sourced_registry
    ) -> None:
        assert (
            assess(crash_only_panel).manifest.fingerprint
            != assess(crash_only_panel, registry=sourced_registry).manifest.fingerprint
        )

    def test_manifest_pins_the_registry_checksum(
        self, rich_panel: pd.DataFrame
    ) -> None:
        manifest = assess(rich_panel).manifest
        assert manifest.registry_sha256
        assert manifest.package_versions["statsmodels"]


class TestSerialisation:
    def test_assessment_round_trips_to_json(self, rich_panel: pd.DataFrame) -> None:
        import json

        payload = assess(rich_panel).as_dict()
        text = json.dumps(payload, default=str)

        assert json.loads(text)["mode"] == "A"
        assert payload["receipts"]["refusal"] is None
        assert len(payload["checks"]) >= 8
        assert payload["manifest"]["fingerprint"]

    def test_every_check_reaches_the_payload(self, sparse_panel: pd.DataFrame) -> None:
        payload = assess(sparse_panel).as_dict()
        numbers = {check["number"] for check in payload["checks"]}
        assert {1, 2, 3, 4, 5, 6, 7, 8, 9} <= numbers


class TestJobRejection:
    def test_contract_violation_is_raised_not_downgraded(self) -> None:
        """A broken contract cannot be ranked either. It is a rejection, not Mode B."""
        panel = synthetic_panel(n_units=10, n_periods=4).drop(columns=["length_km"])
        with pytest.raises(ContractViolation):
            assess(panel)

    def test_constant_column_is_dropped_and_logged(self) -> None:
        panel = synthetic_panel(n_units=40, n_periods=12, seed=2)
        panel["speed_limit"] = 80.0

        result = assess(panel)
        assert "speed_limit" in result.constant_factors
        assert "speed_limit" not in result.factor_names
        assert any(e.code == "constant_column" for e in result.log)
