"""Step 4.3 — the report page, and the seam that puts a run inside it.

The page itself is React, compiled to one self-contained file. These tests cover the
Python half — the injection — plus the two properties that make the whole approach
work: the document must carry its run rather than fetch it, and it must not reach the
network for anything at all. Both are what let a report open from a run directory with
nothing running, on a machine that has never been online.

The page's own rendering is verified by opening the built file in a browser; what is
pinned here is everything that would silently produce a report with no run in it.
"""

from __future__ import annotations

import json
import re

import pandas as pd
import pytest

from roadrisk.core.engine import assess
from roadrisk.core.ladder import Mode
from roadrisk.core.registry import Registry
from roadrisk.report import (
    PLACEHOLDER,
    REPORT_FILENAME,
    TEMPLATE_PATH,
    ReportTemplateError,
    build_run,
    render_report,
    write_report,
)

RUN_BLOCK = re.compile(
    r'<script id="roadrisk-run" type="application/json">(.*?)</script>', re.DOTALL
)


def embedded(html: str) -> dict:
    """Pull the run back out of a rendered report, the way the page does."""
    match = RUN_BLOCK.search(html)
    assert match is not None, "the rendered report carries no run block"
    return json.loads(match.group(1))


@pytest.fixture(scope="module")
def report_html(corridor_panel) -> str:
    assessment = assess(
        corridor_panel.panel,
        snap=corridor_panel.snap,
        corridor_units=corridor_panel.corridor_units,
    )
    return render_report(
        build_run(assessment, corridor_panel, generated_at="2026-08-20 12:00 UTC")
    )


class TestTheCompiledPage:
    def test_it_ships_with_the_package(self) -> None:
        """Committed, so installing this package never needs a JavaScript toolchain."""
        assert TEMPLATE_PATH.exists()
        assert TEMPLATE_PATH.stat().st_size > 10_000

    def test_it_still_has_somewhere_to_put_a_run(self) -> None:
        assert PLACEHOLDER in TEMPLATE_PATH.read_text(encoding="utf-8")

    def test_a_drifted_template_fails_loudly(self, tmp_path, monkeypatch) -> None:
        """Silently producing a report with no run in it is the failure that matters."""
        broken = tmp_path / "broken.html"
        broken.write_text("<html><body>no placeholder here</body></html>", "utf-8")
        monkeypatch.setattr("roadrisk.report.TEMPLATE_PATH", broken)

        with pytest.raises(ReportTemplateError, match="no longer contains"):
            render_report({"assessment": {}})


class TestTheReportCarriesItsRun:
    def test_the_placeholder_is_replaced(self, report_html: str) -> None:
        assert PLACEHOLDER not in report_html

    def test_the_run_survives_the_round_trip(self, report_html: str) -> None:
        run = embedded(report_html)

        assert run["assessment"]["mode"] == "A"
        assert run["corridor"]["corridor"]["name"] == "demo"
        assert run["assessment"]["ranking"]["units"]
        assert run["generated_at"] == "2026-08-20 12:00 UTC"

    def test_provenance_reaches_the_page(self, report_html: str) -> None:
        """The report's central promise, checked at the last seam it crosses."""
        provenance = embedded(report_html)["corridor"]["provenance"]

        assert provenance
        for row in provenance:
            assert row["source"] and row["tier"] and row["licence"]

    def test_a_panel_with_no_geography_still_renders(
        self, rich_panel: pd.DataFrame
    ) -> None:
        """A panel handed straight to the engine has no corridor half. That is not an
        error — the page drops the map and provenance rather than inventing them."""
        html = render_report(build_run(assess(rich_panel), None))

        assert embedded(html)["corridor"] is None


class TestInjectionIsSafe:
    def test_a_corridor_named_like_a_closing_tag_cannot_break_out(self) -> None:
        """`</script>` in any value would end the block early and spill the run into
        the document as markup. Escaping `<` closes it without losing the character."""
        hostile = "</script><img src=x onerror=alert(1)>"
        html = render_report({"assessment": {"banner": hostile}})

        assert "<img src=x" not in html
        assert embedded(html)["assessment"]["banner"] == hostile

    def test_the_payload_is_ascii_only(self, report_html: str) -> None:
        """The document's encoding cannot change what the page parses."""
        match = RUN_BLOCK.search(report_html)
        assert match is not None
        match.group(1).encode("ascii")


class TestSelfContained:
    def test_nothing_is_loaded_from_the_network(self, report_html: str) -> None:
        """A report that needed a CDN would stop working the moment it was emailed."""
        assert "<script src=" not in report_html
        assert 'src="http' not in report_html
        assert 'href="http' not in report_html
        assert "@import" not in report_html

    def test_there_are_no_link_elements_at_all(self, report_html: str) -> None:
        """Stylesheets, preloads and icons are all inlined.

        This also disarms Vite's module-preload polyfill, which is the one thing in
        the bundle that can call `fetch`: with no `<link>` to walk, it never fires.
        """
        assert "<link" not in report_html

    def test_the_page_reads_its_run_out_of_its_own_document(
        self, report_html: str
    ) -> None:
        """The whole reason the run is injected: `file://` cannot fetch a sibling."""
        assert 'getElementById("roadrisk-run")' in report_html


class TestNeverBlank:
    """A report that fails must say it failed.

    Every pixel is drawn by JavaScript, so anywhere scripts do not run — a sandboxed
    preview pane, an email viewer, a locked-down browser — an empty root would be a
    blank white page telling the reader nothing at all.
    """

    def test_the_root_is_not_empty_before_scripts_run(self, report_html: str) -> None:
        assert '<div id="root"></div>' not in report_html
        assert "needs JavaScript to draw itself" in report_html

    def test_the_fallback_says_what_to_do_about_it(self, report_html: str) -> None:
        assert "open it in a web browser" in report_html
        # And where the same numbers are, for a reader who cannot.
        assert "assessment.json" in report_html
        assert "ranking.csv" in report_html


class TestModeBStaysModeB:
    def test_no_count_reaches_the_page(
        self, starved_panel: pd.DataFrame, sourced_registry: Registry
    ) -> None:
        assessment = assess(starved_panel, registry=sourced_registry)
        assert assessment.mode is Mode.B

        run = embedded(render_report(build_run(assessment, None)))

        assert run["assessment"]["predictions"] is None
        for row in run["assessment"]["ranking"]["units"]:
            assert "expected" not in row
            assert "observed" not in row


class TestWrittenToDisk:
    def test_write_report_creates_the_directory(self, tmp_path, rich_panel) -> None:
        target = tmp_path / "nested" / REPORT_FILENAME

        written = write_report(build_run(assess(rich_panel), None), target)

        assert written.exists()
        assert written.read_text(encoding="utf-8").startswith("<!doctype html>")

    def test_a_run_directory_contains_a_readable_report(
        self, tmp_path, corridor_panel
    ) -> None:
        """The done-when: what `roadrisk corridor --out` leaves behind."""
        from roadrisk.cli import _write_run

        assessment = assess(
            corridor_panel.panel,
            snap=corridor_panel.snap,
            corridor_units=corridor_panel.corridor_units,
        )
        _write_run(assessment, tmp_path, corridor_panel)

        report = tmp_path / REPORT_FILENAME
        assert report.exists()
        assert embedded(report.read_text(encoding="utf-8"))["assessment"]["banner"]


class TestFiguresHaveSomethingToDraw:
    """Step 4.4 — the figures are SVG over arrays already in the payload.

    Python cannot render React, so what is pinned here is the contract the figures
    draw from. A missing array is a blank rectangle in front of a client, and it
    would otherwise only be discovered by looking.
    """

    def test_the_strip_and_map_have_per_unit_geometry(self, report_html: str) -> None:
        units = embedded(report_html)["corridor"]["segmentation"]["units"]

        assert units
        for unit in units:
            assert unit["start_m"] < unit["end_m"]
            assert len(unit["geometry"]) > 1
            longitude, latitude = unit["geometry"][0]
            assert -180 <= longitude <= 180
            assert -90 <= latitude <= 90

    def test_the_ranking_carries_a_percentile_for_every_unit(
        self, report_html: str
    ) -> None:
        """The strip and the map colour by percentile, so every unit needs one."""
        for unit in embedded(report_html)["assessment"]["ranking"]["units"]:
            assert 0.0 <= unit["percentile"] <= 1.0

    def test_cure_curves_carry_their_bounds(self, rich_panel: pd.DataFrame) -> None:
        validation = embedded(
            render_report(build_run(assess(rich_panel), None))
        )["assessment"]["validation"]

        assert validation["cure"]
        for cure in validation["cure"]:
            assert len(cure["x"]) == len(cure["cumulative"]) == len(cure["bound"])
            assert len(cure["x"]) > 1

    def test_a_requested_spline_carries_its_curve(self, rich_panel: pd.DataFrame) -> None:
        assessment = assess(rich_panel, shape_factors=["curve_density"])
        shapes = embedded(render_report(build_run(assessment, None)))["assessment"][
            "reference"
        ]["shapes"]

        assert shapes
        curve = shapes[0]["curve"]
        assert len(curve["x"]) == len(curve["y"]) == len(curve["lower"])
        assert all(lo <= hi for lo, hi in zip(curve["lower"], curve["upper"], strict=True))

    def test_no_figure_asks_the_network_for_an_image(self, report_html: str) -> None:
        """The done-when for 4.4. Every mark is drawn, none is fetched."""
        assert "<img" not in report_html
        assert "url(http" not in report_html


class TestNonFiniteNumbers:
    """`NaN` in the payload is the failure that looks like nothing being wrong.

    Python writes it as a bare `NaN` token, which JavaScript's `JSON.parse` rejects.
    The page cannot tell an unparseable run from an absent one, so it quietly shows a
    file picker where the report should be — a blank-looking report with no error.
    """

    def test_a_nan_becomes_null_rather_than_breaking_the_page(self) -> None:
        html = render_report(
            {"assessment": {"banner": "x", "deviation": float("nan")}}
        )

        assert embedded(html)["assessment"]["deviation"] is None

    def test_infinities_are_nulled_too(self) -> None:
        html = render_report(
            {"assessment": {"a": float("inf"), "b": float("-inf")}}
        )
        run = embedded(html)

        assert run["assessment"]["a"] is None
        assert run["assessment"]["b"] is None

    def test_nested_non_finite_values_are_reached(self) -> None:
        html = render_report(
            {"assessment": {"cure": [{"bound": [1.0, float("nan"), 3.0]}]}}
        )

        assert embedded(html)["assessment"]["cure"][0]["bound"] == [1.0, None, 3.0]

    def test_a_real_run_parses_under_a_strict_json_reader(
        self, report_html: str
    ) -> None:
        """`json.loads` accepts `NaN` by default; a browser never does."""
        match = RUN_BLOCK.search(report_html)
        assert match is not None

        def refuse(constant: str) -> None:
            raise AssertionError(f"{constant} is not valid JSON")

        json.loads(match.group(1), parse_constant=refuse)


class TestThePosteriorContract:
    """The page reads credible intervals out of the posterior by factor name.

    `coefficients` is a **mapping**, not a list. Typing it as an array is not a
    harmless slip: `.find()` on it returns nothing, every row silently falls back to
    the frequentist interval, and the column keeps its "credible interval" heading.
    Frequentist numbers under a Bayesian label is the one mislabelling this report
    must never make, and it shipped that way until a real `--bayes` run was rendered
    and read.
    """

    def test_coefficients_are_keyed_by_factor_name(self) -> None:
        from roadrisk.core.contract import prepare_panel
        from roadrisk.core.models import fit_bayesian_glmm
        from roadrisk.core.registry import load_registry
        from roadrisk.core.transforms import build_design
        from roadrisk.demo import synthetic_panel

        narrow = synthetic_panel(n_units=40, n_periods=12, seed=7)[
            ["unit_id", "period", "time_slot", "n_crashes", "length_km",
             "duration_hours", "curve_density"]
        ]
        frame, _ = prepare_panel(narrow)
        registry = load_registry()
        design = build_design(frame, registry.available(frame.columns))
        fit = fit_bayesian_glmm(
            frame["n_crashes"],
            design,
            frame["log_exposure"],
            frame["unit_id"],
            allow_mcmc=False,
            seed=3,
        )

        coefficients = fit.as_dict()["coefficients"]

        assert isinstance(coefficients, dict)
        assert "curve_density" in coefficients
        assert set(coefficients["curve_density"]) >= {"mean", "hdi_low", "hdi_high"}

    def test_the_page_does_not_search_the_coefficients_as_a_list(self) -> None:
        """A `.find(` over `coefficients` would be the bug returning."""
        bundle = TEMPLATE_PATH.read_text(encoding="utf-8")

        assert "coefficients.find(" not in bundle
