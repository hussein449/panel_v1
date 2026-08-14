"""Step 2.9 — caching by geography, and never hiding the age of what it serves.

The step's own test is *"a second corridor in the same country hits cache"*, and it is
asserted here literally: two different roads, one network fetch.

Nothing touches the network. The clients are the same fakes the adapter tests use, with
a counter on them — which is the point of caching a call rather than a result: the
question "did we go out to the internet" has a definite answer.
"""

from __future__ import annotations

import math
import time

import pytest

from roadrisk.geo import build_corridor_panel
from roadrisk.geo.adapters.graph import build_network_query
from roadrisk.geo.cache import (
    DEFAULT_MAX_AGE_DAYS,
    STALE_WARNING_DAYS,
    CacheEntry,
    CacheReport,
    FileCache,
    NullCache,
    digest,
    quantise_bbox,
)
from roadrisk.geo.cached import cached_mapillary, cached_overpass
from roadrisk.geo.corridor import Corridor

ORIGIN_LAT = 34.90
ORIGIN_LON = 32.85
LAT_PER_M = 1.0 / 111_320.0
LON_PER_M = 1.0 / (111_320.0 * math.cos(math.radians(ORIGIN_LAT)))

CORRIDOR_M = 3000.0


def at(east_m: float, north_m: float = 0.0) -> tuple[float, float]:
    return (ORIGIN_LON + east_m * LON_PER_M, ORIGIN_LAT + north_m * LAT_PER_M)


def straight(
    start_m: float = 0.0, end_m: float = CORRIDOR_M, north_m: float = 0.0
) -> list:
    count = max(int(abs(end_m - start_m) / 50.0) + 1, 2)
    return [
        at(start_m + i * (end_m - start_m) / (count - 1), north_m) for i in range(count)
    ]


def way(points: list[tuple[float, float]], **tags: str) -> dict:
    return {
        "type": "way",
        "id": abs(hash(tuple(points))) % 10**9,
        "tags": {"highway": "primary", **tags},
        "geometry": [{"lon": lon, "lat": lat} for lon, lat in points],
    }


class CountingOverpass:
    """A fake Overpass that records how many times it actually went out."""

    def __init__(self, *elements: dict) -> None:
        self.elements = list(elements)
        self.calls: list[str] = []

    def __call__(self, query: str) -> dict:
        self.calls.append(query)
        return {"elements": self.elements}


class CountingMapillary:
    def __init__(self) -> None:
        self.calls: list[tuple[float, float, float, float]] = []

    def __call__(self, bbox):
        self.calls.append(bbox)
        return {"data": []}


@pytest.fixture
def store(tmp_path) -> FileCache:
    return FileCache(directory=tmp_path / "cache")


# ---- the store ---------------------------------------------------------------


class TestFileCache:
    def test_a_stored_answer_comes_back(self, store: FileCache) -> None:
        store.put("abc", "overpass", {"elements": [1, 2, 3]})
        entry = store.get("abc")

        assert entry is not None
        assert entry.payload == {"elements": [1, 2, 3]}
        assert entry.source == "overpass"

    def test_an_unknown_key_is_a_miss(self, store: FileCache) -> None:
        assert store.get("never-stored") is None

    def test_an_entry_past_its_source_s_expiry_is_a_miss(self, store: FileCache) -> None:
        """OSM changes. A year-old road network is not this road."""
        store.put("old", "overpass", {"elements": []})

        path = store.path_for("old")
        assert path.exists()

        store.max_age_days = {"overpass": -1.0}
        assert store.get("old") is None
        assert not path.exists(), "an expired entry is removed, not left to rot"

    def test_a_corrupt_entry_is_a_miss_and_repairs_itself(self, store: FileCache) -> None:
        """A run killed mid-write must not poison every run after it."""
        store.put("broken", "overpass", {"elements": []})
        store.path_for("broken").write_bytes(b"not gzip at all")

        assert store.get("broken") is None
        assert not store.path_for("broken").exists()

    def test_an_unwritable_cache_is_a_slow_pipeline_not_a_broken_one(
        self, tmp_path
    ) -> None:
        blocked = tmp_path / "a-file-not-a-directory"
        blocked.write_text("in the way", encoding="utf-8")

        cache = FileCache(directory=blocked)
        cache.put("k", "overpass", {"elements": []})

        assert cache.get("k") is None

    def test_the_null_cache_remembers_nothing(self) -> None:
        cache = NullCache()
        cache.put("k", "overpass", {"elements": []})

        assert cache.get("k") is None


class TestKeys:
    def test_the_same_question_gives_the_same_key(self) -> None:
        assert digest("overpass", {"a": 1, "b": 2}) == digest("overpass", {"b": 2, "a": 1})

    def test_a_different_question_gives_a_different_key(self) -> None:
        assert digest("overpass", "way[highway]") != digest("overpass", "way[railway]")

    def test_a_number_and_its_string_do_not_collide(self) -> None:
        assert digest(1) != digest("1")

    def test_floating_point_noise_does_not_split_one_key_in_two(self) -> None:
        """Two boxes differing in the twelfth decimal are the same question."""
        assert digest(32.85) == digest(32.85 + 1e-12)


class TestQuantisation:
    def test_a_box_only_ever_grows(self) -> None:
        """Fetching more than asked is a cost. Fetching less would be a wrong answer."""
        box = (32.8412, 34.9013, 32.9317, 35.0579)
        west, south, east, north = quantise_bbox(box, 0.1)

        assert west <= box[0]
        assert south <= box[1]
        assert east >= box[2]
        assert north >= box[3]

    def test_two_nearby_boxes_become_one(self) -> None:
        assert quantise_bbox((32.81, 34.91, 32.93, 35.05), 0.1) == quantise_bbox(
            (32.84, 34.93, 32.96, 35.02), 0.1
        )

    def test_two_distant_boxes_stay_apart(self) -> None:
        assert quantise_bbox((32.8, 34.9, 32.9, 35.0), 0.1) != quantise_bbox(
            (5.1, 51.2, 5.3, 51.4), 0.1
        )

    def test_a_grid_of_zero_is_refused(self) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            quantise_bbox((0.0, 0.0, 1.0, 1.0), 0.0)


# ---- the wrappers ----------------------------------------------------------------


class TestCachedClients:
    def test_the_second_identical_query_never_leaves_the_disk(
        self, store: FileCache
    ) -> None:
        real = CountingOverpass(way(straight()))
        client = cached_overpass(real, store)

        first = client("[out:json];way[highway](1,2,3,4);out geom;")
        second = client("[out:json];way[highway](1,2,3,4);out geom;")

        assert len(real.calls) == 1
        assert first == second
        assert client.report.hits == 1
        assert client.report.misses == 1

    def test_a_different_query_still_goes_out(self, store: FileCache) -> None:
        real = CountingOverpass()
        client = cached_overpass(real, store)

        client("[out:json];way[highway](1,2,3,4);out geom;")
        client("[out:json];way[railway](1,2,3,4);out geom;")

        assert len(real.calls) == 2

    def test_the_network_query_is_grid_aligned_before_the_cache_sees_it(self) -> None:
        """The rounding belongs to the adapter, not the cache.

        An earlier version rewrote the bounding box inside the query text on its way
        through the cache. It worked, and it meant a cached run fetched a different
        region from an uncached one — so the cache changed the answer, which is the one
        thing a cache must never do.
        """
        near = Corridor.from_latlon([(34.90, 32.85), (34.95, 32.95)], name="near")
        also = Corridor.from_latlon([(34.88, 32.90), (34.99, 33.02)], name="also")

        assert build_network_query(near) == build_network_query(also)

    def test_mapillary_tiles_are_quantised_so_neighbours_share_them(
        self, store: FileCache
    ) -> None:
        real = CountingMapillary()
        client = cached_mapillary(real, store, grid_deg=0.01)

        client((4.8851, 52.3661, 4.8869, 52.3679))
        client((4.8853, 52.3663, 4.8867, 52.3677))

        assert len(real.calls) == 1, "both round to the same tile"

    def test_nothing_is_cached_without_a_cache(self) -> None:
        real = CountingOverpass()
        client = cached_overpass(real, NullCache())

        client("[out:json];a;out;")
        client("[out:json];a;out;")

        assert len(real.calls) == 2


# ---- honesty about age -------------------------------------------------------


class TestReporting:
    def test_a_run_that_used_no_cache_says_nothing(self) -> None:
        assert CacheReport().notes() == []

    def test_a_hit_is_reported_with_the_age_of_what_it_served(self) -> None:
        report = CacheReport()
        report.record_hit(
            CacheEntry(key="k", source="overpass", payload={}, fetched_at=time.time())
        )
        report.record_miss()

        note = report.notes()[0]
        assert "1 of 2 source fetch(es) were served from the cache" in note
        assert "overpass" in note

    def test_stale_data_is_called_out_not_merely_dated(self) -> None:
        """A cache that lets a run look fresher than it is defeats the whole package."""
        old = time.time() - (STALE_WARNING_DAYS + 5) * 86_400
        report = CacheReport()
        report.record_hit(
            CacheEntry(key="k", source="overpass", payload={}, fetched_at=old)
        )

        note = report.notes()[0]
        assert "the road may have changed since" in note
        assert "Clear the cache" in note

    def test_fresh_data_is_dated_but_not_scolded(self) -> None:
        report = CacheReport()
        report.record_hit(
            CacheEntry(key="k", source="overpass", payload={}, fetched_at=time.time())
        )

        assert "may have changed since" not in report.notes()[0]

    def test_the_oldest_entry_is_the_one_reported(self) -> None:
        report = CacheReport()
        now = time.time()
        for age_days in (1.0, 9.0, 3.0):
            report.record_hit(
                CacheEntry(
                    key="k",
                    source="overpass",
                    payload={},
                    fetched_at=now - age_days * 86_400,
                )
            )

        assert report.oldest_days == pytest.approx(9.0, abs=0.01)
        assert "9 day(s) ago" in report.notes()[0]

    def test_sources_expire_on_their_own_clocks(self) -> None:
        """A DEM never changes; OSM changes daily. One policy would be wrong for one."""
        from roadrisk.geo.cache import MAX_AGE_DAYS

        assert MAX_AGE_DAYS["mapillary"] > MAX_AGE_DAYS["overpass"]
        assert DEFAULT_MAX_AGE_DAYS > 0


# ---- the step's own test -----------------------------------------------------


class TestSecondCorridorHitsCache:
    """*"Second corridor in the same country hits cache"* — the literal done-when."""

    def build(self, cache, centre_offset: float, client) -> None:
        points = [
            (lat + centre_offset, lon + centre_offset)
            for lon, lat in straight()
        ]
        build_corridor_panel(
            points,
            periods=["2024-01"],
            name=f"corridor-{centre_offset}",
            network_client=client,
            cache=cache,
        )

    def test_a_second_corridor_nearby_costs_no_network_fetch(
        self, store: FileCache
    ) -> None:
        real = CountingOverpass(way(straight()), way(straight(north_m=400.0)))

        self.build(store, 0.0, real)
        assert len(real.calls) == 1, "the first corridor pays"

        self.build(store, 0.004, real)
        assert len(real.calls) == 1, "the second, 400 m away, is free"

    def test_a_corridor_in_another_country_still_pays(self, store: FileCache) -> None:
        real = CountingOverpass(way(straight()))

        self.build(store, 0.0, real)
        self.build(store, 12.0, real)

        assert len(real.calls) == 2

    def test_the_run_says_it_used_the_cache(self, store: FileCache) -> None:
        real = CountingOverpass(way(straight()))
        self.build(store, 0.0, real)

        built = build_corridor_panel(
            [(lat, lon) for lon, lat in straight()],
            periods=["2024-01"],
            name="again",
            network_client=real,
            cache=store,
        )

        assert built.cache.hits == 1
        assert any("served from the cache" in note for note in built.warnings)

    def test_without_a_cache_every_run_pays(self) -> None:
        real = CountingOverpass(way(straight()))

        self.build(None, 0.0, real)
        self.build(None, 0.0, real)

        assert len(real.calls) == 2

    def test_the_cached_and_uncached_panels_agree(self, store: FileCache) -> None:
        """A cache that changes the answer is not a cache."""
        real = CountingOverpass(way(straight()))
        points = [(lat, lon) for lon, lat in straight()]

        fresh = build_corridor_panel(
            points, periods=["2024-01"], name="c", network_client=real
        )
        warmed = build_corridor_panel(
            points, periods=["2024-01"], name="c", network_client=real, cache=store
        )
        served = build_corridor_panel(
            points, periods=["2024-01"], name="c", network_client=real, cache=store
        )

        assert served.cache.hits == 1
        assert fresh.panel.equals(warmed.panel)
        assert warmed.panel.equals(served.panel)


def test_the_network_query_is_the_thing_that_gets_quantised() -> None:
    """Only the region-shaped fetch can be shared, and it is the expensive one."""
    corridor = Corridor.from_latlon([(lat, lon) for lon, lat in straight()], name="q")
    query = build_network_query(corridor)

    assert "around" not in query, "a corridor-shaped query could not be shared"
    assert query.count("(") >= 1
