"""Corridor resolution from OSM.

Every test here uses a **fake Overpass client**. A test suite that reaches the network
is slow, flaky, and fails for reasons that have nothing to do with the code — and the
real mirrors return 504 under load often enough to guarantee it.
"""

from __future__ import annotations

import math

import pytest

from roadrisk.geo.errors import CorridorError
from roadrisk.geo.osm import (
    BoundingBox,
    Selector,
    build_query,
    fetch_corridor,
    fetch_corridor_by,
)

# A patch of Cyprus, so the UTM zone and metre-per-degree scaling are realistic.
ORIGIN_LAT = 34.90
ORIGIN_LON = 32.85

#: Degrees per metre at this latitude, near enough for building fixtures.
LAT_PER_M = 1.0 / 111_320.0
LON_PER_M = 1.0 / (111_320.0 * math.cos(math.radians(ORIGIN_LAT)))


def at(east_m: float, north_m: float) -> tuple[float, float]:
    """A (longitude, latitude) pair offset from the origin by metres."""
    return (ORIGIN_LON + east_m * LON_PER_M, ORIGIN_LAT + north_m * LAT_PER_M)


def way(points: list[tuple[float, float]], **tags: str) -> dict:
    """One Overpass way element, in the shape `out geom;` returns."""
    return {
        "type": "way",
        "id": abs(hash(tuple(points))) % 10**9,
        "tags": {"highway": "primary", "ref": "B9", **tags},
        "geometry": [{"lon": lon, "lat": lat} for lon, lat in points],
    }


def client_returning(*ways: dict):
    """A fake Overpass client. Records the query it was given."""

    def fake(query: str) -> dict:
        fake.last_query = query  # type: ignore[attr-defined]
        return {"elements": list(ways)}

    fake.last_query = None  # type: ignore[attr-defined]
    return fake


def straight(start_m: float, end_m: float, *, step_m: float = 50.0) -> list:
    """A straight run along the easting axis, from start_m to end_m."""
    count = max(int((end_m - start_m) / step_m) + 1, 2)
    return [
        at(start_m + i * (end_m - start_m) / (count - 1), 0.0) for i in range(count)
    ]


BBOX = BoundingBox(south=34.85, west=32.80, north=34.95, east=32.95)


class TestBoundingBox:
    def test_rejects_inverted_latitude(self) -> None:
        with pytest.raises(CorridorError, match="south"):
            BoundingBox(south=35.0, west=32.0, north=34.0, east=33.0)

    def test_rejects_inverted_longitude(self) -> None:
        with pytest.raises(CorridorError, match="west"):
            BoundingBox(south=34.0, west=33.0, north=35.0, east=32.0)

    def test_around_encloses_the_points_with_margin(self) -> None:
        box = BoundingBox.around([(34.9, 32.85), (35.0, 32.95)], margin_deg=0.01)

        assert box.south < 34.9
        assert box.north > 35.0
        assert box.west < 32.85
        assert box.east > 32.95

    def test_overpass_order_is_south_west_north_east(self) -> None:
        assert BBOX.as_overpass() == "34.85,32.8,34.95,32.95"


class TestQuery:
    def test_asks_for_the_reference_and_geometry(self) -> None:
        query = build_query("I 95", BBOX)

        assert '"ref"="I 95"' in query
        assert '["highway"]' in query
        assert "out geom;" in query, "without geom the ways come back without vertices"


class TestStitching:
    def test_joins_fragments_into_one_line(self) -> None:
        client = client_returning(
            way(straight(0, 500)), way(straight(500, 1000)), way(straight(1000, 1500))
        )
        result = fetch_corridor("B9", BBOX, client=client)

        assert result.n_fragments == 3
        assert result.n_pieces_after_merge == 1
        assert result.longest_share == pytest.approx(1.0, abs=0.01)

    def test_order_does_not_matter(self) -> None:
        """OSM returns fragments in whatever order it likes."""
        forward = fetch_corridor(
            "B9",
            BBOX,
            client=client_returning(way(straight(0, 500)), way(straight(500, 1000))),
        )
        shuffled = fetch_corridor(
            "B9",
            BBOX,
            client=client_returning(way(straight(500, 1000)), way(straight(0, 500))),
        )

        assert forward.n_vertices == shuffled.n_vertices

    def test_direction_does_not_matter(self) -> None:
        """Some ways are drawn against the direction of travel."""
        backwards = list(reversed(straight(500, 1000)))
        result = fetch_corridor(
            "B9", BBOX, client=client_returning(way(straight(0, 500)), way(backwards))
        )

        assert result.n_pieces_after_merge == 1


class TestGapBridging:
    def test_bridges_a_small_gap(self) -> None:
        """OSM is not perfectly noded; a few metres is an editing artefact."""
        client = client_returning(way(straight(0, 500)), way(straight(510, 1000)))
        result = fetch_corridor("B9", BBOX, client=client, max_gap_m=25.0)

        assert result.gaps_bridged == 1
        assert result.discarded_pieces == 0

    def test_does_not_bridge_a_real_gap(self) -> None:
        client = client_returning(way(straight(0, 3000)), way(straight(3400, 3800)))
        result = fetch_corridor("B9", BBOX, client=client, max_gap_m=25.0)

        assert result.gaps_bridged == 0
        assert result.discarded_pieces == 1
        assert any("do not connect" in w for w in result.warnings)

    def test_a_larger_allowance_bridges_more(self) -> None:
        ways = (way(straight(0, 3000)), way(straight(3200, 3600)))
        tight = fetch_corridor("B9", BBOX, client=client_returning(*ways), max_gap_m=25.0)
        loose = fetch_corridor(
            "B9", BBOX, client=client_returning(*ways), max_gap_m=300.0
        )

        assert tight.discarded_pieces == 1
        assert loose.discarded_pieces == 0
        assert loose.gaps_bridged == 1

    def test_a_gap_too_big_to_bridge_can_fail_the_fragmentation_gate(self) -> None:
        """Refusing beats silently returning half a corridor.

        Two nearly equal pieces with an unbridgeable gap is not a corridor. Handing
        back the longer half would look like success while quietly dropping the rest.
        """
        client = client_returning(way(straight(0, 1000)), way(straight(1400, 2300)))
        with pytest.raises(CorridorError, match="fragmented collection"):
            fetch_corridor("B9", BBOX, client=client, max_gap_m=25.0)


class TestDividedCarriageway:
    def test_the_two_carriageways_are_never_welded_together(self) -> None:
        """The bug this class exists for.

        A divided road's carriageways end about 20 m apart — inside any sensible gap
        tolerance. A distance-only bridger welds them into a line that runs out along
        one side and back along the other, doubling the corridor length and making
        chainage meaningless. The turn check is what prevents it.
        """
        northbound = way(straight(0, 2000), oneway="yes")
        southbound = way(
            [(lon, lat + 20 * LAT_PER_M) for lon, lat in straight(0, 2000)],
            oneway="yes",
        )

        result = fetch_corridor(
            "A1", BBOX, client=client_returning(northbound, southbound)
        )

        assert result.gaps_bridged == 0, "the carriageways must not be joined"
        assert result.discarded_pieces == 1

        # One carriageway, not an out-and-back of both, which would double the length
        # and make every chainage — and therefore every crash location — wrong.
        from roadrisk.geo import Corridor

        assert Corridor.from_latlon(result.points).length_km == pytest.approx(2.0, abs=0.1)

    def test_an_undivided_road_with_a_parallel_twin_is_flagged(self) -> None:
        """A service road or duplicated trace beside a two-way road.

        No `oneway` tag to rely on here, so geometry is the only signal.
        """
        main = way(straight(0, 3000))
        twin = way([(lon, lat + 20 * LAT_PER_M) for lon, lat in straight(0, 1400)])

        result = fetch_corridor("B9", BBOX, client=client_returning(main, twin))

        assert not result.divided
        assert any("ONE direction of travel" in w for w in result.warnings)

    def test_a_bridged_piece_is_not_called_a_rival_carriageway(self) -> None:
        """A piece welded into the corridor is part of it, not a competitor."""
        client = client_returning(way(straight(0, 2000)), way(straight(2010, 4000)))
        result = fetch_corridor("B9", BBOX, client=client, max_gap_m=25.0)

        assert result.gaps_bridged == 1
        assert not any("ONE direction of travel" in w for w in result.warnings)

    def test_a_short_offshoot_is_not_called_a_carriageway(self) -> None:
        main = way(straight(0, 3000))
        slip = way([(lon, lat + 30 * LAT_PER_M) for lon, lat in straight(0, 200)])

        result = fetch_corridor("B9", BBOX, client=client_returning(main, slip))

        assert not any("ONE direction of travel" in w for w in result.warnings)


class TestDividedDetection:
    """OSM states divided-ness in the `oneway` tag. Trust it over geometry.

    Carriageways routinely separate by hundreds of metres around terrain, so any
    distance rule is wrong exactly where the road is most interesting. Cyprus A1
    returns 49 ways, every one `oneway=yes`, with the two carriageways 11 km apart
    at their furthest.
    """

    def test_oneway_ways_mark_the_road_as_divided(self) -> None:
        north = way(straight(0, 4000), oneway="yes")
        south = way(
            [(lon, lat + 25 * LAT_PER_M) for lon, lat in straight(0, 3800)],
            oneway="yes",
        )
        result = fetch_corridor("A1", BBOX, client=client_returning(north, south))

        assert result.divided
        assert any("DIVIDED road" in w for w in result.warnings)
        assert any("ONE carriageway" in w for w in result.warnings)

    def test_a_two_way_road_is_not_divided(self) -> None:
        result = fetch_corridor(
            "B9", BBOX, client=client_returning(way(straight(0, 4000)))
        )
        assert not result.divided

    def test_divided_roads_survive_the_fragmentation_gate(self) -> None:
        """Half of what comes back is the other carriageway, so ~50% is healthy.

        A single threshold would reject every motorway — which is how this was found.
        """
        north = way(straight(0, 4000), oneway="yes")
        south = way(
            [(lon, lat + 25 * LAT_PER_M) for lon, lat in straight(0, 3900)],
            oneway="yes",
        )
        result = fetch_corridor("A1", BBOX, client=client_returning(north, south))

        assert result.longest_share < 0.6, "would fail the undivided threshold"
        assert result.divided

    def test_the_same_split_is_refused_when_the_road_is_not_divided(self) -> None:
        north = way(straight(0, 4000))
        south = way([(lon, lat + 3000 * LAT_PER_M) for lon, lat in straight(0, 3900)])

        with pytest.raises(CorridorError, match="fragmented collection"):
            fetch_corridor("B9", BBOX, client=client_returning(north, south))

    def test_excluded_length_is_reported(self) -> None:
        north = way(straight(0, 4000), oneway="yes")
        south = way(
            [(lon, lat + 25 * LAT_PER_M) for lon, lat in straight(0, 2000)],
            oneway="yes",
        )
        result = fetch_corridor("A1", BBOX, client=client_returning(north, south))

        assert result.excluded_km == pytest.approx(2.0, abs=0.1)
        assert any("2.00 km" in w for w in result.warnings)

    def test_a_badly_broken_divided_road_is_still_refused(self) -> None:
        """The relaxed threshold is a floor, not an amnesty."""
        scattered = [way(straight(i * 4000, i * 4000 + 300), oneway="yes") for i in range(8)]
        with pytest.raises(CorridorError, match="divided road"):
            fetch_corridor("A1", BBOX, client=client_returning(*scattered))


class TestGates:
    def test_refuses_when_nothing_is_returned(self) -> None:
        with pytest.raises(CorridorError, match="no ways tagged"):
            fetch_corridor("B9", BBOX, client=client_returning())

    def test_names_the_spelling_trap(self) -> None:
        """OSM spellings vary and a wrong ref returns nothing, silently."""
        with pytest.raises(CorridorError, match="I 95"):
            fetch_corridor("B9", BBOX, client=client_returning())

    def test_refuses_geometry_free_ways(self) -> None:
        client = client_returning({"type": "way", "id": 1, "tags": {}, "geometry": []})
        with pytest.raises(CorridorError, match="out geom"):
            fetch_corridor("B9", BBOX, client=client)

    def test_refuses_a_fragmented_mess(self) -> None:
        """The equivalent of 'reject if the route leaves the named road'.

        Fetching by ref cannot return the wrong road, so the failure that matters is
        a scatter of disconnected pieces rather than a corridor.
        """
        scattered = [
            way(straight(i * 3000, i * 3000 + 400)) for i in range(6)
        ]
        with pytest.raises(CorridorError, match="fragmented collection"):
            fetch_corridor("B9", BBOX, client=client_returning(*scattered))


class TestARoadThatIsNotOpen:
    """The Cyprus A10, and the report it should never have produced.

    Every one of the A10's 22 OSM ways is `highway=construction`. The pipeline assessed
    it end to end anyway: 8.53 km, 17 segments, a ranked table and a blackspot list for
    a motorway nobody has driven on. Each symptom was reported correctly and separately
    — 30% centreline coverage, zero of six tag factors clearing their floor, no ramps
    and no POIs anywhere, and a 95 m vertex spacing that made curvature untrustworthy —
    and the one sentence explaining all of them was never said.
    """

    def test_a_road_under_construction_is_refused(self) -> None:
        pieces = [way(straight(0, 3000), highway="construction")]
        with pytest.raises(CorridorError, match="not a road that is open"):
            fetch_corridor("A10", BBOX, client=client_returning(*pieces))

    def test_the_refusal_names_the_tag_it_found(self) -> None:
        """Not "this road is unsuitable". The tag, so it can be checked in OSM."""
        pieces = [way(straight(0, 3000), highway="construction")]
        with pytest.raises(CorridorError, match="highway=construction"):
            fetch_corridor("A10", BBOX, client=client_returning(*pieces))

    @pytest.mark.parametrize(
        "state", ["construction", "proposed", "abandoned", "razed", "disused"]
    )
    def test_every_not_open_state_is_refused(self, state: str) -> None:
        """Planned, being built and gone are different facts, and none is a road."""
        pieces = [way(straight(0, 3000), highway=state)]
        with pytest.raises(CorridorError, match="not a road that is open"):
            fetch_corridor("A10", BBOX, client=client_returning(*pieces))

    def test_a_partly_built_road_keeps_the_built_part_and_says_so(self) -> None:
        """A motorway being extended is ordinary. The open carriageway is real road."""
        result = fetch_corridor(
            "A10",
            BBOX,
            client=client_returning(
                way(straight(0, 4000)),
                way(straight(4000, 5000), highway="construction"),
            ),
        )
        assert result.points, "the built section should still produce a corridor"
        assert any("EXCLUDED" in warning for warning in result.warnings), (
            "excluding unbuilt road silently would leave the chainage short of the "
            "route with nothing on the report to explain it"
        )
        assert any("highway=construction" in warning for warning in result.warnings)

    def test_an_ordinary_road_is_untouched(self) -> None:
        """The gate must cost nothing on every road that is open."""
        result = fetch_corridor(
            "B9", BBOX, client=client_returning(way(straight(0, 4000)))
        )
        assert not any("EXCLUDED" in warning for warning in result.warnings)


class TestTrimming:
    def test_trims_to_the_requested_extent(self) -> None:
        client = client_returning(way(straight(0, 4000)))
        full = fetch_corridor("B9", BBOX, client=client)

        lon_a, lat_a = at(1000.0, 0.0)
        lon_b, lat_b = at(3000.0, 0.0)
        trimmed = fetch_corridor(
            "B9",
            BBOX,
            client=client_returning(way(straight(0, 4000))),
            start=(lat_a, lon_a),
            end=(lat_b, lon_b),
        )

        assert trimmed.n_vertices < full.n_vertices

    def test_endpoints_may_be_given_in_either_order(self) -> None:
        lon_a, lat_a = at(1000.0, 0.0)
        lon_b, lat_b = at(3000.0, 0.0)

        forward = fetch_corridor(
            "B9",
            BBOX,
            client=client_returning(way(straight(0, 4000))),
            start=(lat_a, lon_a),
            end=(lat_b, lon_b),
        )
        reversed_ = fetch_corridor(
            "B9",
            BBOX,
            client=client_returning(way(straight(0, 4000))),
            start=(lat_b, lon_b),
            end=(lat_a, lon_a),
        )

        assert forward.n_vertices == reversed_.n_vertices

    def test_refuses_an_endpoint_on_a_different_road(self) -> None:
        lon, lat = at(1000.0, 5000.0)
        with pytest.raises(CorridorError, match="beyond the"):
            fetch_corridor(
                "B9",
                BBOX,
                client=client_returning(way(straight(0, 4000))),
                start=(lat, lon),
            )

    def test_refuses_endpoints_that_collapse(self) -> None:
        lon, lat = at(1000.0, 0.0)
        with pytest.raises(CorridorError, match="same point"):
            fetch_corridor(
                "B9",
                BBOX,
                client=client_returning(way(straight(0, 4000))),
                start=(lat, lon),
                end=(lat, lon),
            )


class TestResultFeedsThePipeline:
    def test_points_are_latitude_longitude_ordered(self) -> None:
        result = fetch_corridor(
            "B9", BBOX, client=client_returning(way(straight(0, 2000)))
        )
        latitude, longitude = result.points[0]

        assert 34.8 < latitude < 35.0, "latitude first"
        assert 32.8 < longitude < 33.0

    def test_survives_a_round_trip_through_the_projection(self) -> None:
        result = fetch_corridor(
            "B9", BBOX, client=client_returning(way(straight(0, 2000)))
        )
        first = result.points[0]

        assert first[0] == pytest.approx(ORIGIN_LAT, abs=1e-4)
        assert first[1] == pytest.approx(ORIGIN_LON, abs=1e-4)

    def test_builds_a_panel(self) -> None:
        from roadrisk.core.contract import prepare_panel
        from roadrisk.geo import build_corridor_panel

        result = fetch_corridor(
            "B9", BBOX, client=client_returning(way(straight(0, 5000, step_m=20.0)))
        )
        built = build_corridor_panel(
            result.points, periods=["2024-01", "2024-02"], name=result.ref
        )

        _, report = prepare_panel(built.panel)
        assert report.n_units > 1
        assert report.zero_crash_rows == report.n_rows

    def test_tags_are_carried_through(self) -> None:
        result = fetch_corridor(
            "B9",
            BBOX,
            client=client_returning(way(straight(0, 2000), name="Troodos Road")),
        )
        assert result.tags["name"] == "Troodos Road"


# -- selecting a road by name --------------------------------------------------
#
# A name is the same query with a weaker guarantee. What makes it safe is the
# fragmentation gate that was already here: two unrelated roads sharing one name are a
# fragmented collection, which is exactly what that gate refuses. These tests hold that
# claim rather than restate it.


def named(points: list[tuple[float, float]], road: str) -> dict:
    """A way carrying a name and NO ref — the case ref-only selection cannot reach."""
    element = way(points, name=road)
    del element["tags"]["ref"]
    return element


def two_roads_one_name(road: str) -> list[dict]:
    """Two equal runs 4 km apart. Unbridgeable, so the longest carries about half."""
    return [
        named(straight(0, 2000), road),
        named([at(east, 4000.0) for east in range(6000, 8001, 50)], road),
    ]


class TestSelectingByName:
    def test_the_query_asks_for_the_name_tag(self) -> None:
        query = build_query(Selector.by_name("High Street"), BBOX)

        assert '"name"="High Street"' in query
        assert '"ref"' not in query
        assert "out geom;" in query

    def test_a_bare_string_still_means_a_reference(self) -> None:
        """Every caller that passed a string kept its meaning when names arrived."""
        assert build_query("B9", BBOX) == build_query(Selector.by_ref("B9"), BBOX)

    def test_it_resolves_a_road_that_has_no_reference(self) -> None:
        client = client_returning(
            named(straight(0, 800), "Kings Road"),
            named(straight(800, 1600), "Kings Road"),
        )
        result = fetch_corridor_by(Selector.by_name("Kings Road"), BBOX, client=client)

        assert result.ref == "Kings Road"
        assert result.selector_key == "name"
        assert result.selector == Selector("name", "Kings Road")
        assert result.n_pieces_after_merge == 1

    def test_two_unrelated_roads_of_the_same_name_are_refused(self) -> None:
        """The whole reason a name may be trusted less than a reference."""
        client = client_returning(*two_roads_one_name("High Street"))

        with pytest.raises(CorridorError, match="fragmented collection"):
            fetch_corridor_by(Selector.by_name("High Street"), BBOX, client=client)

    def test_that_refusal_explains_what_is_specific_to_a_name(self) -> None:
        client = client_returning(*two_roads_one_name("High Street"))

        with pytest.raises(CorridorError, match="not unique the way a reference"):
            fetch_corridor_by(Selector.by_name("High Street"), BBOX, client=client)

    def test_a_name_is_held_to_a_higher_share_than_a_reference(self) -> None:
        assert (
            Selector.by_name("High Street").min_longest_share
            > Selector.by_ref("B9").min_longest_share
        )

    def test_nothing_found_says_the_name_is_matched_exactly(self) -> None:
        with pytest.raises(CorridorError, match="exact match"):
            fetch_corridor_by(
                Selector.by_name("Nowhere Lane"), BBOX, client=client_returning()
            )


class TestTheSelectorItself:
    def test_a_quote_in_a_name_cannot_end_the_query_string(self) -> None:
        """Unescaped, this closes the string early and matches something else.

        It could not arise while only references were selectable, because a reference
        is alphanumeric. It can now, and it fails quietly rather than loudly.
        """
        query = build_query(Selector.by_name('Bill "Bojangles" Way'), BBOX)

        assert '\\"Bojangles\\"' in query
        assert query.count('"name"=') == 1
        assert query.endswith("out geom;")

    def test_a_backslash_is_escaped_too(self) -> None:
        query = build_query(Selector.by_name("Back\\slash Road"), BBOX)

        assert "Back\\\\slash" in query

    def test_only_ref_and_name_select_a_road(self) -> None:
        with pytest.raises(CorridorError, match="'ref' or 'name'"):
            Selector("highway", "primary")

    def test_an_empty_value_is_refused(self) -> None:
        with pytest.raises(CorridorError, match="cannot be empty"):
            Selector.by_name("   ")
