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
