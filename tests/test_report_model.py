"""Step 4.1 — the report model.

The report renders from JSON, never from a live Python object. That is not a style
preference: it is what lets a run stored today be re-rendered tomorrow without
refitting anything, and what lets one payload serve the report page, the API and the
worker without three serialisation paths drifting apart.

So the tests here are mostly about a boundary rather than a calculation. Does the
payload survive `json.dumps` with no `default=` escape hatch? Is everything a report
needs reachable *after* the round trip, with no engine object in scope? And does
Mode B stay Mode B on the way through — a mode that has no predicted count must not
acquire one by being serialised.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import pytest

from roadrisk.core.engine import _predictions, assess
from roadrisk.core.ladder import Mode
from roadrisk.core.models.base import Family, FitResult
from roadrisk.core.registry import Licence, Registry, Tier
from roadrisk.geo.adapters.base import FactorValues
from roadrisk.geo.adapters.fusion import Confidence, FusedFactor, FusionResult
from roadrisk.geo.attribution import ATTRIBUTION_PREFIX, collect_attributions

JSON_PRIMITIVES = (str, int, float, bool, type(None))


def only_json_primitives(payload: Any, path: str = "$") -> None:
    """Assert a payload is JSON all the way down, naming the first thing that is not.

    `json.dumps(..., default=str)` would hide a DataFrame, an enum or a Timestamp by
    stringifying it, and the report would then be reading a repr. This walks the
    structure instead, so the failure names the path rather than the symptom.
    """
    if isinstance(payload, dict):
        for key, value in payload.items():
            assert isinstance(key, str), f"{path}: non-string key {key!r}"
            only_json_primitives(value, f"{path}.{key}")
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            only_json_primitives(value, f"{path}[{index}]")
    else:
        assert isinstance(payload, JSON_PRIMITIVES), (
            f"{path}: {type(payload).__name__} is not JSON"
        )


def values(
    factor: str,
    *,
    licence: Licence,
    adapter: str = "an_adapter",
    notes: tuple[str, ...] = (),
) -> FactorValues:
    index = pd.Index(["U0000", "U0001"], name="unit_id")
    return FactorValues(
        factor=factor,
        column=factor,
        adapter=adapter,
        tier=Tier.A,
        licence=licence,
        source=f"{adapter} resolved {factor}.",
        values=pd.Series([1.0, 2.0], index=index),
        notes=notes,
    )


def fused(*resolved: FactorValues, rejected: tuple[FactorValues, ...] = ()) -> FusionResult:
    return FusionResult(
        factors=[
            FusedFactor(
                factor=item.factor,
                column=item.column,
                chosen=item,
                rejected=rejected,
                confidence=pd.Series(
                    [Confidence.HIGH, Confidence.HIGH], index=item.values.index
                ),
                reason=pd.Series(["measured", "measured"], index=item.values.index),
            )
            for item in resolved
        ]
    )


class TestAttribution:
    def test_odbl_requires_credit_and_warns_about_the_database(self) -> None:
        report = collect_attributions(fused(values("curvature", licence=Licence.ODBL)))

        assert report.credit_required
        assert report.share_alike_database
        warning = report.database_warning()
        assert warning is not None
        assert "share-alike" in warning
        # The distinction the whole module exists for: the report is fine, the
        # dataset is not.
        assert "Reporting the numbers is not redistributing the database." in warning

    def test_cc_by_requires_credit_without_share_alike(self) -> None:
        """CC-BY-4.0 is a separate rung precisely so it is not read as CC-BY-SA."""
        report = collect_attributions(fused(values("grade", licence=Licence.CC_BY)))

        assert report.credit_required
        assert not report.share_alike_database
        assert report.database_warning() is None

    @pytest.mark.parametrize("licence", [Licence.PUBLIC_DOMAIN, Licence.CLIENT])
    def test_open_and_client_data_owe_nothing(self, licence: Licence) -> None:
        report = collect_attributions(fused(values("speed_limit", licence=licence)))

        assert not report.credit_required
        assert not report.share_alike_database
        assert report.credit_lines() == []

    def test_an_unknown_licence_is_flagged_not_assumed_permissive(self) -> None:
        """Failing safe: an unrecognised licence is credited and named, never waved through."""
        item = values("curvature", licence=Licence.ODBL)
        odd = FactorValues(**{**item.__dict__, "licence": "Some-Bespoke-Licence-2.0"})

        report = collect_attributions(fused(odd))

        assert report.unrecognised == ("Some-Bespoke-Licence-2.0",)
        assert report.credit_required
        obligation = report.obligations[0]
        assert not obligation.recognised
        assert "check its terms" in obligation.note

    def test_an_explicit_credit_line_travels_from_the_adapter(self) -> None:
        report = collect_attributions(
            fused(
                values(
                    "grade",
                    licence=Licence.CC_BY,
                    notes=(f"{ATTRIBUTION_PREFIX} Contains modified Copernicus data.",),
                )
            )
        )

        assert report.credit_lines() == ["Contains modified Copernicus data."]

    def test_a_rejected_source_is_owed_nothing(self) -> None:
        """Fusion's loser never reached the report, so it creates no obligation."""
        winner = values("curvature", licence=Licence.CLIENT, adapter="client")
        loser = values("curvature", licence=Licence.ODBL, adapter="osm_tags")

        report = collect_attributions(fused(winner, rejected=(loser,)))

        assert not report.share_alike_database
        assert [o.licence for o in report.obligations] == [Licence.CLIENT.value]

    def test_nothing_resolved_is_an_empty_report_not_an_error(self) -> None:
        report = collect_attributions(FusionResult())

        assert report.obligations == ()
        assert report.credit_lines() == []
        assert report.database_warning() is None


class TestPredictions:
    def test_mode_a_predicts_one_row_per_panel_row(
        self, rich_panel: pd.DataFrame
    ) -> None:
        result = assess(rich_panel)
        assert result.mode is Mode.A
        assert result.predictions is not None

        assert len(result.predictions) == len(rich_panel)
        assert list(result.predictions.columns) == [
            "unit_id",
            "period",
            "time_slot",
            "observed",
            "expected",
            "exposure",
        ]
        assert (result.predictions["expected"] > 0).all()

    def test_predictions_are_keyed_so_they_can_be_grouped(
        self, rich_panel: pd.DataFrame
    ) -> None:
        """4.2 ranks by unit. Unkeyed numbers would be a list nothing can aggregate."""
        result = assess(rich_panel)
        assert result.predictions is not None

        assert set(result.predictions["unit_id"]) == set(rich_panel["unit_id"])
        assert result.predictions["observed"].sum() == rich_panel["n_crashes"].sum()

    def test_mode_b_has_no_predictions_and_gains_none_by_serialising(
        self, starved_panel: pd.DataFrame, sourced_registry: Registry
    ) -> None:
        """Mode B ranks. It does not predict, and JSON is not a loophole."""
        result = assess(starved_panel, registry=sourced_registry)

        assert result.mode is Mode.B
        assert result.predictions is None
        assert result.as_dict()["predictions"] is None

    def test_a_fit_that_did_not_converge_predicts_nothing(
        self, rich_panel: pd.DataFrame
    ) -> None:
        failed = FitResult(
            specification="broken",
            family=Family.NEGATIVE_BINOMIAL,
            converged=False,
            n_observations=len(rich_panel),
            n_parameters=2,
            fitted_values=pd.Series(1.0, index=rich_panel.index),
        )

        assert _predictions(rich_panel, failed) is None


class TestAssessmentPayload:
    def test_is_json_all_the_way_down(self, rich_panel: pd.DataFrame) -> None:
        payload = assess(rich_panel).as_dict()

        only_json_primitives(payload)
        json.dumps(payload)  # no default= escape hatch

    def test_survives_a_round_trip_with_no_engine_object_in_scope(
        self, rich_panel: pd.DataFrame
    ) -> None:
        """The done-when for 4.1, written as the thing a renderer actually does."""
        payload = json.loads(json.dumps(assess(rich_panel).as_dict()))

        assert payload["mode"] == "A"
        assert "MODE A" in payload["banner"]
        assert payload["factors"]["in_model"]
        assert payload["fit"]["coefficients"]
        assert payload["predictions"]
        assert payload["checks"]
        assert payload["manifest"]["panel_sha256"]
        assert isinstance(payload["log"], list)


class TestCorridorPayload:
    def test_is_json_all_the_way_down(self, corridor_panel) -> None:
        payload = corridor_panel.as_dict()

        only_json_primitives(payload)
        json.dumps(payload)

    def test_carries_geometry_for_the_map_in_geojson_order(self, corridor_panel) -> None:
        payload = corridor_panel.as_dict()

        line = payload["corridor"]["geometry"]
        assert len(line) > 1
        longitude, latitude = line[0]
        # Cyprus. Longitude near 33, latitude near 35 — if these were swapped the map
        # would put the corridor in the Mediterranean off Libya and look plausible.
        assert 32.0 < longitude < 34.0
        assert 34.0 < latitude < 36.0

        units = payload["segmentation"]["units"]
        assert len(units) == payload["segmentation"]["n_units"]
        assert all(len(unit["geometry"]) > 1 for unit in units)

    def test_every_factor_carries_source_tier_licence_and_confidence(
        self, corridor_panel
    ) -> None:
        """The promise the report is built on, checked at the seam it crosses."""
        provenance = corridor_panel.as_dict()["provenance"]

        assert provenance
        for row in provenance:
            assert row["source"]
            assert row["tier"]
            assert row["licence"]
            assert row["confidence_high"] is not None

    def test_reports_what_the_snapping_dropped(self, corridor_panel) -> None:
        snap = corridor_panel.as_dict()["snap"]

        assert snap is not None
        assert snap["n_supplied"] > snap["n_snapped"]
        assert snap["n_dropped"] == snap["n_supplied"] - snap["n_snapped"]
        assert sum(snap["dropped_reasons"].values()) == snap["n_dropped"]

    def test_attribution_reaches_the_payload(self, corridor_panel) -> None:
        attribution = corridor_panel.as_dict()["attribution"]

        assert attribution["credit_required"]
        assert attribution["credit_lines"]
        assert attribution["obligations"]

    def test_both_payloads_together_render_a_report_from_disk(
        self, corridor_panel, tmp_path
    ) -> None:
        """Coordinates in, two JSON files out, and nothing Python in between."""
        assessment = assess(corridor_panel.panel, snap=corridor_panel.snap)

        (tmp_path / "assessment.json").write_text(
            json.dumps(assessment.as_dict()), encoding="utf-8"
        )
        (tmp_path / "corridor.json").write_text(
            json.dumps(corridor_panel.as_dict()), encoding="utf-8"
        )

        report = {
            "assessment": json.loads(
                (tmp_path / "assessment.json").read_text(encoding="utf-8")
            ),
            "corridor": json.loads(
                (tmp_path / "corridor.json").read_text(encoding="utf-8")
            ),
        }

        assert report["assessment"]["banner"]
        assert report["assessment"]["receipts"] is not None
        assert report["corridor"]["corridor"]["name"] == "demo"
        assert report["corridor"]["attribution"]["database_warning"]
        only_json_primitives(report)


class TestNoInvalidJson:
    def test_misaligned_fitted_values_predict_nothing_rather_than_nan(
        self, rich_panel: pd.DataFrame
    ) -> None:
        """A NaN would serialise as literal `NaN`, which is not JSON at all."""
        misaligned = FitResult(
            specification="misaligned",
            family=Family.NEGATIVE_BINOMIAL,
            converged=True,
            n_observations=len(rich_panel),
            n_parameters=2,
            fitted_values=pd.Series(1.0, index=rich_panel.index[:-5]),
        )

        assert _predictions(rich_panel, misaligned) is None
