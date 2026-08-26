"""CLI behaviour that is easy to break silently."""

from __future__ import annotations

import sys

from typer.testing import CliRunner

from roadrisk.cli import _make_output_utf8_safe, app
from roadrisk.geo.corridor import CENTRELINE_GUIDANCE

runner = CliRunner()


class TestCentrelineGuidance:
    """The guidance is only useful if it survives rendering intact."""

    def test_the_overpass_query_is_printed_literally(self) -> None:
        """Rich treats [out:json] as a markup tag and drops it.

        The guidance is a copy-paste recipe. A query missing its first line is worse
        than no recipe, because the reader will paste it and get an error they cannot
        diagnose.
        """
        result = runner.invoke(app, ["centreline-help"])

        assert result.exit_code == 0
        assert "[out:json]" in result.output
        assert 'way["ref"="M51"]' in result.output

    def test_the_recipe_covers_the_whole_path(self) -> None:
        for step in ("overpass-turbo.eu", "GeoJSON", "Merge Lines", "latitude"):
            assert step in CENTRELINE_GUIDANCE, step

    def test_hand_drawing_rules_are_included(self) -> None:
        assert "Dense on the bends" in CENTRELINE_GUIDANCE
        assert "cut a corner" in CENTRELINE_GUIDANCE

    def test_running_corridor_without_a_centreline_offers_the_recipe(self) -> None:
        """The moment a user needs this is the moment they have no centreline."""
        result = runner.invoke(app, ["corridor"])

        assert result.exit_code != 0
        assert "[out:json]" in result.output


def _unwrapped(output: str) -> str:
    """Help text is boxed and hard-wrapped. Undo both before matching.

    Rich wraps at the panel width and pads each line to it, so an install command can be
    split across two lines with a border character between. Collapsing whitespace would
    not be enough on its own — the break can land inside the command.
    """
    return "".join(line.strip().strip("│").strip() for line in output.splitlines())


class TestInstallCommandsSurviveRendering:
    """The same Rich hazard as the class above, one command over.

    `[out:json]` was escaped in `centreline-help` back in Stage 2 and the reason was
    written down there. Then 5.1b printed `pip install "roadrisk-panel[store]"` and
    5.1c printed `pip install "roadrisk-panel[api]"`, and Rich did exactly what it had
    done before: looked for a style called `store`, found none, dropped the tag — and
    left an install command telling the reader to install the package they already have,
    with the one thing it is about removed from it.

    Nothing noticed, because help text is not usually asserted on. It is now, for every
    place this package prints an extra, so the next one that appears is covered too.
    """

    def test_the_store_group_names_the_extra_it_needs(self) -> None:
        result = runner.invoke(app, ["store", "--help"])

        assert result.exit_code == 0
        assert "roadrisk-panel[store]" in _unwrapped(result.output)

    def test_the_serve_command_names_the_extra_it_needs(self) -> None:
        result = runner.invoke(app, ["serve", "--help"])

        assert result.exit_code == 0
        assert "roadrisk-panel[api]" in _unwrapped(result.output)


class TestCorridorCommand:
    def test_demo_runs_end_to_end(self) -> None:
        result = runner.invoke(app, ["corridor", "--demo", "--periods", "6"])

        assert result.exit_code == 0
        assert "Corridor built" in result.output
        assert "MODE" in result.output

    def test_demo_reports_the_snap_rate(self) -> None:
        result = runner.invoke(app, ["corridor", "--demo", "--periods", "6"])
        assert "Snapped" in result.output
        assert "Dropped" in result.output


class TestRedirectedOutput:
    """A run must not die because the log it is being written into is cp1252.

    The mode banner carries a coloured circle and the receipts carry arrows and
    sigmas. Redirected — a CI log, a worker capturing its child, `> report.txt` —
    Python drops from the Windows console API to the locale encoding, and the first
    emoji raises UnicodeEncodeError part-way through printing an assessment.
    """

    def test_streams_are_reconfigured_to_utf8(self, monkeypatch) -> None:
        calls: list[dict] = []

        class Stream:
            def reconfigure(self, **kwargs: object) -> None:
                calls.append(kwargs)

        monkeypatch.setattr(sys, "stdout", Stream())
        monkeypatch.setattr(sys, "stderr", Stream())

        _make_output_utf8_safe()

        assert calls == [{"encoding": "utf-8"}, {"encoding": "utf-8"}]

    def test_a_stream_that_refuses_utf8_degrades_instead_of_raising(
        self, monkeypatch
    ) -> None:
        calls: list[dict] = []

        class AwkwardStream:
            def reconfigure(self, **kwargs: object) -> None:
                calls.append(kwargs)
                if "encoding" in kwargs:
                    raise ValueError("cannot reconfigure encoding")

        monkeypatch.setattr(sys, "stdout", AwkwardStream())
        monkeypatch.setattr(sys, "stderr", AwkwardStream())

        _make_output_utf8_safe()  # must not raise

        assert {"errors": "replace"} in calls

    def test_a_stream_without_reconfigure_is_left_alone(self, monkeypatch) -> None:
        monkeypatch.setattr(sys, "stdout", object())
        monkeypatch.setattr(sys, "stderr", object())

        _make_output_utf8_safe()  # must not raise


class TestTheReportSeam:
    """Step 4.7 — coordinates to a readable report in one command."""

    def test_corridor_can_reach_the_bayesian_rung(self) -> None:
        """It could not before: `corridor` called assess() with no estimator at all,
        so the whole of Stage 3's best work was unreachable from the geometry path."""
        import inspect

        from roadrisk.cli import corridor

        parameters = set(inspect.signature(corridor).parameters)
        assert {"bayes", "priors", "spatial", "shape"} <= parameters

    def test_both_commands_offer_the_same_estimator_options(self) -> None:
        import inspect

        from roadrisk.cli import assess_panel, corridor

        shared = {"bayes", "priors", "spatial", "shape", "report", "pdf"}
        assert shared <= set(inspect.signature(assess_panel).parameters)
        assert shared <= set(inspect.signature(corridor).parameters)

    def test_report_writes_the_html_and_the_json_beside_it(self, tmp_path) -> None:
        """The report's own fallback tells a reader the same numbers are in
        assessment.json. That has to be true."""
        result = runner.invoke(
            app, ["corridor", "--demo", "--periods", "6", "--report", str(tmp_path)]
        )

        assert result.exit_code == 0, result.output
        assert (tmp_path / "report.html").exists()
        assert (tmp_path / "assessment.json").exists()
        assert (tmp_path / "corridor.json").exists()

    def test_report_accepts_a_filename(self, tmp_path) -> None:
        target = tmp_path / "b9-assessment.html"

        result = runner.invoke(
            app, ["corridor", "--demo", "--periods", "6", "--report", str(target)]
        )

        assert result.exit_code == 0, result.output
        assert target.exists()
        assert (tmp_path / "assessment.json").exists()

    def test_report_alone_does_not_write_the_whole_run_record(self, tmp_path) -> None:
        """--out is the run record; --report is for when the report is all you want."""
        runner.invoke(
            app, ["corridor", "--demo", "--periods", "6", "--report", str(tmp_path)]
        )

        assert not (tmp_path / "panel.csv").exists()
        assert not (tmp_path / "snap_detail.csv").exists()
