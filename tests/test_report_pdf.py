"""Step 4.5 — the PDF is this report printed, not a second one rendered.

Two things are pinned here. First, that the print rules the paged document depends on
are actually in the shipped page: a running banner, page counters, table headers that
repeat across a break, and colours that survive a printer's helpful habit of removing
backgrounds. Second, that a missing browser is reported as what to do next rather than
as a failed run — the HTML is complete on its own and any reader can print it by hand.

The PDF itself is checked by printing one, when there is something to print it with.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from roadrisk.core.engine import assess
from roadrisk.report import (
    REPORT_FILENAME,
    TEMPLATE_PATH,
    BrowserNotFound,
    PdfExportFailed,
    build_run,
    find_browser,
    to_pdf,
    write_report,
)
from roadrisk.report.pdf import BASE_FLAGS

HAS_BROWSER = find_browser() is not None
needs_browser = pytest.mark.skipif(
    not HAS_BROWSER, reason="no Chrome or Edge on this machine to print with"
)


@pytest.fixture(scope="module")
def bundle() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


class TestThePrintRulesShip:
    def test_there_is_a_page_rule(self, bundle: str) -> None:
        assert "@media print" in bundle
        assert "@page" in bundle

    def test_pages_are_numbered(self, bundle: str) -> None:
        assert "counter(page)" in bundle
        assert "counter(pages)" in bundle

    def test_the_mode_banner_becomes_a_running_header(self, bundle: str) -> None:
        """Chrome has no `string-set`, so the banner is baked into a `@page` rule at
        render time. What ships is the code that writes it."""
        assert "@top-center" in bundle

    def test_colours_are_not_stripped_when_printing(self, bundle: str) -> None:
        """The risk ramp and the mode banner *are* the information, not decoration."""
        assert "print-color-adjust" in bundle

    def test_a_split_table_keeps_its_header(self, bundle: str) -> None:
        """A page of unlabelled numbers is worse than a page break."""
        assert "table-header-group" in bundle

    def test_figures_and_receipts_are_not_split(self, bundle: str) -> None:
        assert "break-inside" in bundle
        assert "page-break-inside" in bundle  # the older spelling, for older engines

    def test_the_screen_only_toolbar_is_hidden(self, bundle: str) -> None:
        assert ".no-print" in bundle

    def test_chrome_is_told_not_to_add_its_own_furniture(self) -> None:
        """`--no-pdf-header-footer` reads like the right flag and is silently ignored;
        without the real one Chrome stamps a date and the file's URL on every page."""
        assert "--print-to-pdf-no-header" in BASE_FLAGS


class TestBrowserDiscovery:
    def test_an_explicit_path_is_used_as_given(self, tmp_path: Path) -> None:
        fake = tmp_path / "browser.exe"
        fake.write_text("", encoding="utf-8")

        assert find_browser(fake) == fake

    def test_an_explicit_path_that_does_not_exist_is_not_substituted(
        self, tmp_path: Path
    ) -> None:
        """Silently falling back to a different browser than the one asked for would
        make a reproducibility claim that is not true."""
        assert find_browser(tmp_path / "missing.exe") is None

    def test_the_environment_can_name_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = tmp_path / "browser.exe"
        fake.write_text("", encoding="utf-8")
        monkeypatch.setenv("ROADRISK_BROWSER", str(fake))

        assert find_browser() == fake


class TestFailingUsefully:
    def test_printing_a_report_that_is_not_there_says_so(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="No report to print"):
            to_pdf(tmp_path / "nothing.html")

    def test_no_browser_explains_the_alternative(
        self, tmp_path: Path, rich_panel: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing browser is not a lost report — it is one keypress away by hand."""
        html = write_report(
            build_run(assess(rich_panel), None), tmp_path / REPORT_FILENAME
        )
        monkeypatch.setattr("roadrisk.report.pdf.find_browser", lambda *_, **__: None)

        with pytest.raises(BrowserNotFound) as caught:
            to_pdf(html)

        message = str(caught.value)
        assert "print it" in message
        assert "ROADRISK_BROWSER" in message
        assert str(html) in message

    def test_a_browser_that_writes_nothing_is_not_reported_as_success(
        self, tmp_path: Path, rich_panel: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        html = write_report(
            build_run(assess(rich_panel), None), tmp_path / REPORT_FILENAME
        )
        stub = tmp_path / "stub"
        stub.write_text("", encoding="utf-8")
        monkeypatch.setattr("roadrisk.report.pdf.find_browser", lambda *_, **__: stub)

        class Result:
            returncode = 3
            stdout = ""
            stderr = "could not open display"

        monkeypatch.setattr("roadrisk.report.pdf.subprocess.run", lambda *a, **k: Result())

        with pytest.raises(PdfExportFailed, match="could not open display"):
            to_pdf(html)


@needs_browser
class TestPrintingOne:
    def test_a_report_prints_to_a_pdf(
        self, tmp_path: Path, corridor_panel
    ) -> None:
        assessment = assess(
            corridor_panel.panel,
            snap=corridor_panel.snap,
            corridor_units=corridor_panel.corridor_units,
        )
        html = write_report(
            build_run(assessment, corridor_panel), tmp_path / REPORT_FILENAME
        )

        written = to_pdf(html)

        assert written.name == "report.pdf"
        assert written.read_bytes()[:5] == b"%PDF-"
        # A blank page would be a few kilobytes. This one carries figures.
        assert written.stat().st_size > 50_000

    def test_the_pdf_lands_beside_the_report_by_default(
        self, tmp_path: Path, rich_panel: pd.DataFrame
    ) -> None:
        html = write_report(
            build_run(assess(rich_panel), None), tmp_path / REPORT_FILENAME
        )

        assert to_pdf(html).parent == html.parent
