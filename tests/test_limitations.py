"""Step 4.6 — the limitations page, and the fact that nothing removes it.

The done-when has two halves. The page must be *generated*: every dropped term, every
failed check, every caveat that this run actually incurred has to appear, so that it
cannot go stale and cannot describe a different run. And it must be *undisableable*:
there is no flag, no argument and no config that takes it off a report.

The second half is the harder one to test, because the thing being asserted is the
absence of a switch. So the tests here try every way a caller could plausibly reach for
one — an argument, an empty payload, a run with nothing wrong with it — and check the
page is still there.
"""

from __future__ import annotations

import inspect
import json

import pandas as pd
import pytest

from roadrisk.core.engine import assess
from roadrisk.core.ladder import Mode
from roadrisk.core.registry import Registry
from roadrisk.report import build_run, collect_limitations, render_report
from roadrisk.report.limitations import CAVEAT, CONTEXT, MATERIAL, Limitation

SEVERITIES = {MATERIAL, CAVEAT, CONTEXT}


def codes(limitations: list[Limitation]) -> set[str]:
    return {item.code for item in limitations}


@pytest.fixture(scope="module")
def corridor_run(corridor_panel) -> dict:
    assessment = assess(
        corridor_panel.panel,
        snap=corridor_panel.snap,
        corridor_units=corridor_panel.corridor_units,
    )
    return build_run(assessment, corridor_panel, generated_at="2026-08-21 09:00 UTC")


class TestItCannotBeDisabled:
    def test_collect_takes_no_argument_that_suppresses_it(self) -> None:
        """There is no flag to find, which is the point."""
        parameters = set(inspect.signature(collect_limitations).parameters)

        assert parameters == {"assessment", "corridor"}

    def test_build_run_takes_no_argument_that_suppresses_it(self) -> None:
        parameters = set(inspect.signature(build_run).parameters)

        assert "limitations" not in parameters
        assert not {p for p in parameters if "limit" in p or "skip" in p}

    def test_every_run_carries_limitations(self, corridor_run: dict) -> None:
        assert corridor_run["limitations"]

    def test_a_run_with_nothing_wrong_still_carries_them(self) -> None:
        """An empty payload is the most favourable case there is. It is not empty."""
        limitations = collect_limitations({}, None)

        assert limitations
        assert "association_not_cause" in codes(limitations)
        assert "one_corridor" in codes(limitations)

    def test_a_perfect_panel_still_carries_them(
        self, rich_panel: pd.DataFrame
    ) -> None:
        run = build_run(assess(rich_panel), None)

        assert run["limitations"]

    def test_the_page_is_rendered_without_a_condition(self) -> None:
        """No `&&`, no ternary, no prop that empties it — it is always in the tree."""
        from roadrisk.report import TEMPLATE_PATH

        bundle = TEMPLATE_PATH.read_text(encoding="utf-8")
        assert "What this assessment cannot tell you" in bundle
        assert "there is no setting that removes it" in bundle

    def test_the_page_says_so_when_it_somehow_has_nothing(self) -> None:
        """Belt and braces: an empty list renders as a defect notice, not as silence."""
        from roadrisk.report import TEMPLATE_PATH

        bundle = TEMPLATE_PATH.read_text(encoding="utf-8")
        assert "No limitations were recorded for this run" in bundle


class TestItIsGeneratedFromTheRun:
    def test_every_limitation_is_well_formed(self, corridor_run: dict) -> None:
        for item in corridor_run["limitations"]:
            assert item["code"]
            assert item["severity"] in SEVERITIES
            assert item["title"]
            assert len(item["detail"]) > 30

    def test_material_limitations_come_first(self, corridor_run: dict) -> None:
        rank = {MATERIAL: 0, CAVEAT: 1, CONTEXT: 2}
        order = [rank[item["severity"]] for item in corridor_run["limitations"]]

        assert order == sorted(order)

    def test_no_two_limitations_share_a_title(self, corridor_run: dict) -> None:
        """A repeated heading with different text under it reads as a bug."""
        titles = [item["title"] for item in corridor_run["limitations"]]

        assert len(titles) == len(set(titles))

    def test_a_failed_check_becomes_a_limitation(self) -> None:
        assessment = {
            "checks": [
                {
                    "number": 4,
                    "name": "Crash count versus estimated parameters",
                    "status": "failed",
                    "failure_type": "soft",
                    "message": "312 crashes available, 700 required.",
                }
            ]
        }

        limitations = collect_limitations(assessment, None)

        found = next(item for item in limitations if item.code == "check_failed_4")
        assert "700 required" in found.detail

    def test_a_skipped_check_is_not_reported_as_a_pass(self) -> None:
        assessment = {
            "checks": [
                {
                    "number": 6,
                    "name": "Crash snap rate",
                    "status": "skipped",
                    "failure_type": "soft",
                    "message": "The panel was supplied pre-built.",
                }
            ]
        }

        found = next(
            item
            for item in collect_limitations(assessment, None)
            if item.code == "check_skipped_6"
        )
        assert "is not a check that passed" in found.detail

    def test_dropped_terms_are_named(self) -> None:
        assessment = {
            "factors": {
                "missing": [{"name": "lanes", "missing_behaviour": "x"}],
                "dropped_for_collinearity": ["junction_density"],
                "constant": ["lit"],
            }
        }

        found = codes(collect_limitations(assessment, None))

        assert {"factors_absent", "factors_collinear", "factors_constant"} <= found

    def test_the_registry_prose_is_not_pasted_into_the_client_report(self) -> None:
        """`missing_behaviour` is developer documentation. Twenty of them concatenated
        is a wall of text no client will read, and some of it names other corridors."""
        assessment = {
            "factors": {
                "missing": [
                    {"name": "lanes", "missing_behaviour": "On M51, adding speed doubled"}
                ]
            }
        }

        found = next(
            item
            for item in collect_limitations(assessment, None)
            if item.code == "factors_absent"
        )
        assert "M51" not in found.detail
        assert "lanes" in found.detail

    def test_a_sign_contradiction_is_material_and_named(self) -> None:
        assessment = {
            "sign_guard": {"findings": [{"factor": "curve_density", "contradicts": True}]}
        }

        found = next(
            item
            for item in collect_limitations(assessment, None)
            if item.code == "sign_contradiction"
        )
        assert found.severity == MATERIAL
        assert "curve_density" in found.detail

    def test_dropped_crashes_are_reported_with_their_reasons(self) -> None:
        corridor = {
            "snap": {
                "n_supplied": 1000,
                "n_snapped": 700,
                "n_dropped": 300,
                "snap_rate": 0.7,
                "dropped_reasons": {"beyond_tolerance": 300},
            }
        }

        found = next(
            item
            for item in collect_limitations({}, corridor)
            if item.code == "crashes_dropped"
        )
        assert found.severity == MATERIAL
        assert "beyond tolerance" in found.detail

    def test_a_good_snap_rate_raises_nothing(self) -> None:
        corridor = {
            "snap": {
                "n_supplied": 1000,
                "n_snapped": 990,
                "n_dropped": 10,
                "snap_rate": 0.99,
                "dropped_reasons": {},
            }
        }

        assert "crashes_dropped" not in codes(collect_limitations({}, corridor))

    def test_inferred_factors_are_not_called_measurements(self) -> None:
        corridor = {
            "provenance": [
                {"factor": "traffic_proxy", "tier": "B", "confidence_high": 1.0,
                 "coverage": 1.0}
            ]
        }

        found = next(
            item
            for item in collect_limitations({}, corridor)
            if item.code == "inferred_factors"
        )
        assert "are not measurements" in found.detail


class TestTheStandingCaveats:
    def test_mode_b_is_told_it_is_a_ranking(
        self, starved_panel: pd.DataFrame, sourced_registry: Registry
    ) -> None:
        assessment = assess(starved_panel, registry=sourced_registry)
        assert assessment.mode is Mode.B

        found = next(
            item
            for item in collect_limitations(assessment.as_dict(), None)
            if item.code == "mode_b_is_a_ranking"
        )
        assert found.severity == MATERIAL
        assert "not estimate how many crashes" in found.detail

    def test_posted_speed_carries_its_permanent_caveat(self) -> None:
        assessment = {"factors": {"in_model": ["speed_limit"]}}

        assert "posted_speed_stands_in" in codes(collect_limitations(assessment, None))

    def test_hsm_weights_carry_the_edition_caveat(self) -> None:
        assessment = {"index": {"terms": [{"family": "hsm", "factor": "lanes"}]}}

        assert "hsm_edition_unpinned" in codes(collect_limitations(assessment, None))

    def test_a_supplied_panel_says_its_provenance_is_unknown(
        self, rich_panel: pd.DataFrame
    ) -> None:
        run = build_run(assess(rich_panel), None)
        found = {item["code"] for item in run["limitations"]}

        assert "panel_supplied" in found

    def test_a_corridor_run_does_not_claim_unknown_provenance(
        self, corridor_run: dict
    ) -> None:
        found = {item["code"] for item in corridor_run["limitations"]}

        assert "panel_supplied" not in found


class TestItReachesTheReport:
    def test_the_limitations_travel_in_the_rendered_report(
        self, corridor_run: dict
    ) -> None:
        import re

        html = render_report(corridor_run)
        block = re.search(
            r'<script id="roadrisk-run" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        assert block is not None

        payload = json.loads(block.group(1))
        assert payload["limitations"] == corridor_run["limitations"]

    def test_the_print_stylesheet_gives_them_their_own_sheet(self) -> None:
        from roadrisk.report import TEMPLATE_PATH

        bundle = TEMPLATE_PATH.read_text(encoding="utf-8")
        assert "#limitations" in bundle
        assert "page-break-before" in bundle
