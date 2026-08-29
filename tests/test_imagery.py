"""Street-level imagery as a second opinion on whether a road is a road.

Every test uses a fake client. The real endpoint needs a credential and a network, and
a suite that reaches either is one that fails for reasons unrelated to the code.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from roadrisk.geo.adapters.imagery import (
    HttpImageryClient,
    ImagerySurvey,
    describe,
    survey_imagery,
)
from roadrisk.geo.corridor import Corridor
from roadrisk.geo.errors import CorridorError

ORIGIN_LAT = 34.90
ORIGIN_LON = 32.85
LAT_PER_M = 1.0 / 111_320.0
LON_PER_M = 1.0 / (111_320.0 * math.cos(math.radians(ORIGIN_LAT)))


@pytest.fixture
def corridor() -> Corridor:
    """A straight 3 km corridor running north from the origin."""
    return Corridor.from_latlon(
        [(ORIGIN_LAT + metres * LAT_PER_M, ORIGIN_LON) for metres in (0, 1500, 3000)]
    )


def at(corridor: Corridor, chainage_m: float, offset_m: float = 0.0):
    """A (longitude, latitude) pair on the corridor, pushed `offset_m` to the side."""
    return (ORIGIN_LON + offset_m * LON_PER_M, ORIGIN_LAT + chainage_m * LAT_PER_M)


def image(lon: float, lat: float, when: datetime | None, identifier: str) -> dict:
    """One Mapillary image, in the shape the images endpoint returns it."""
    return {
        "id": identifier,
        # Milliseconds. The whole point of `_captured`.
        "captured_at": None if when is None else when.timestamp() * 1000.0,
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
    }


def client_returning(*images: dict):
    def fake(bbox):  # noqa: ARG001 - the fake answers every tile the same way
        return {"data": list(images)}

    return fake


def days_ago(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


class TestTheEvidenceIsAsymmetric:
    """The design rule: a photograph proves presence, silence proves nothing."""

    def test_recent_photographs_say_the_road_is_driven(self, corridor: Corridor) -> None:
        survey = survey_imagery(
            corridor,
            client=client_returning(
                image(*at(corridor, 500), days_ago(30), "a"),
                image(*at(corridor, 1500), days_ago(31), "b"),
            ),
        )
        assert survey.verdict == "driven"
        assert survey.n_on_road == 2
        assert "confirms this road is driven" in survey.note()
        assert "direct evidence" in survey.note()

    def test_no_photographs_is_reported_as_an_absence_of_information(
        self, corridor: Corridor
    ) -> None:
        """**The load-bearing test.**

        Mapillary's coverage is absent across whole regions, and this method exists for
        the places with the least data. If silence were read as "no road here", the
        product would refuse precisely the corridors it was built for. So the sentence
        has to be about the imagery, not about the road.
        """
        survey = survey_imagery(corridor, client=client_returning())

        assert survey.verdict == "unseen"
        note = survey.note()
        assert "only weakly informative" in note
        assert "not a road that is not there" in note
        # It must never make the claim the construction gate is allowed to make.
        assert "does not exist" not in note

    def test_old_photographs_date_themselves_and_claim_nothing_about_today(
        self, corridor: Corridor
    ) -> None:
        survey = survey_imagery(
            corridor,
            client=client_returning(image(*at(corridor, 900), days_ago(2200), "a")),
        )
        assert survey.verdict == "stale"
        assert "Nothing here says whether it still is" in survey.note()


class TestWhatCountsAsOnThisRoad:
    def test_a_photograph_from_the_next_street_is_not_this_road(
        self, corridor: Corridor
    ) -> None:
        survey = survey_imagery(
            corridor,
            client=client_returning(image(*at(corridor, 800, 400), days_ago(10), "a")),
        )
        # `n_returned` counts what the API handed back over every tile, and the tiles are
        # padded so they overlap — the same photograph legitimately arrives more than
        # once. What matters is that none of them was counted as being on this road.
        assert survey.n_returned >= 1, "it was returned by the query"
        assert survey.n_on_road == 0, "but it is 400 m away and is not this corridor"
        assert survey.verdict == "unseen"

    def test_poor_gps_beside_a_mountain_road_still_counts(
        self, corridor: Corridor
    ) -> None:
        """A phone in a valley is metres out. Rejecting that loses real drives."""
        survey = survey_imagery(
            corridor,
            client=client_returning(image(*at(corridor, 800, 15), days_ago(10), "a")),
        )
        assert survey.n_on_road == 1

    def test_the_same_photograph_from_two_tiles_is_counted_once(
        self, corridor: Corridor
    ) -> None:
        """Tiles are padded and overlap, so a boundary photograph arrives twice."""
        duplicate = image(*at(corridor, 1500), days_ago(10), "same-id")
        survey = survey_imagery(corridor, client=client_returning(duplicate, duplicate))
        assert survey.n_on_road == 1


class TestTheTimestampTrap:
    def test_captured_at_is_milliseconds_not_seconds(self, corridor: Corridor) -> None:
        """Read as seconds, every photograph lands in 1970 and every road looks dead.

        A confident wrong answer rather than an error, which is why it is converted in
        one place and pinned here.
        """
        when = days_ago(10)
        survey = survey_imagery(
            corridor, client=client_returning(image(*at(corridor, 500), when, "a"))
        )
        assert survey.latest is not None
        assert abs((survey.latest - when).total_seconds()) < 2
        assert survey.verdict == "driven"

    def test_an_undated_photograph_still_proves_somebody_was_there(
        self, corridor: Corridor
    ) -> None:
        survey = survey_imagery(
            corridor, client=client_returning(image(*at(corridor, 500), None, "a"))
        )
        assert survey.verdict == "driven", "the where is known even when the when is not"
        assert survey.latest is None
        assert any("no capture date" in w for w in survey.warnings)

    def test_a_corrupt_timestamp_is_ignored_rather_than_raising(
        self, corridor: Corridor
    ) -> None:
        broken = image(*at(corridor, 500), None, "a")
        broken["captured_at"] = "not a number"
        survey = survey_imagery(corridor, client=client_returning(broken))
        assert survey.n_on_road == 1
        assert survey.latest is None


class TestItNeverCostsTheCorridorItsAssessment:
    """A corroborating opinion that could fail a run would be worse than none."""

    def test_a_missing_token_becomes_a_note(self, corridor: Corridor, monkeypatch) -> None:
        monkeypatch.delenv("MAPILLARY_ACCESS_TOKEN", raising=False)
        notes = describe(corridor)
        assert len(notes) == 1
        assert "did not run" in notes[0]

    def test_a_failing_request_becomes_a_note(self, corridor: Corridor) -> None:
        def broken(bbox):  # noqa: ARG001
            raise CorridorError("Mapillary was busy.")

        notes = describe(corridor, client=broken)
        assert "did not run" in notes[0]
        assert "nothing corroborates the OSM tags" in notes[0]

    def test_the_token_is_never_echoed_in_an_error(self) -> None:
        """The URL carries the credential, so no failure may quote it."""
        client = HttpImageryClient(token=None)
        with pytest.raises(CorridorError) as caught:
            client((32.8, 34.8, 32.9, 34.9))
        assert "access_token" not in str(caught.value)


class TestTheNoteItself:
    def test_a_driven_road_names_the_date_a_reader_can_check(self) -> None:
        when = datetime(2026, 5, 4, tzinfo=UTC)
        survey = ImagerySurvey(
            n_on_road=42, n_returned=50, latest=when, verdict="driven"
        )
        assert "2026-05-04" in survey.note()
        assert "42" in survey.note()
