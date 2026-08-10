"""CLI behaviour that is easy to break silently."""

from __future__ import annotations

from typer.testing import CliRunner

from roadrisk.cli import app
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
