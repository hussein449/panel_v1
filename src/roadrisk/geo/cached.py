"""Caching wrappers for the network clients.

Every remote source in this pipeline is reached through an injectable protocol — that
was done so the tests could supply fakes, and it pays a second time here: a cache is
just another implementation of the same protocol, wrapping the real one. Nothing in
:mod:`roadrisk.geo.osm`, :mod:`~roadrisk.geo.adapters.graph` or
:mod:`~roadrisk.geo.adapters.mapillary` knows a cache exists.

**The sharing is not done here.** An earlier version of this module rewrote the bounding
box inside the Overpass query text on its way past, which worked and was the wrong place
for it: it meant a run with a cache fetched a different region from a run without one,
and it put string-parsing of somebody else's query language in the caching layer. The
adapters now round their own requests to a grid — see
:data:`~roadrisk.geo.adapters.graph.NETWORK_GRID_DEG` — so two corridors in the same
county produce a byte-identical query on their own, and this module can stay what it
should always have been: a dictionary with a clock.

What is left is the difference between requests that *can* be shared and requests that
cannot. The strategic-network query is built from a grid cell, so any two corridors in
that cell hit. A corridor ribbon — Overpass ``around`` on a polyline — cannot be shared
between two different roads, because the polylines differ; caching it still turns a
re-run from a minute into nothing, which is most of what a person iterating on one
corridor actually needs, and this module does not pretend it is more than that.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from roadrisk.geo.cache import (
    Cache,
    CacheReport,
    NullCache,
    SingleFlight,
    digest,
    quantise_bbox,
)
from roadrisk.geo.osm import OverpassClient

SOURCE_OVERPASS = "overpass"
SOURCE_MAPILLARY = "mapillary"

#: One registry of in-flight fetches for the whole process, shared by every cached
#: client built in it.
#:
#: Shared rather than per-client, because the race this exists to stop is *between
#: corridors*: step 5.1d runs two jobs at once in a thread pool, each builds its own
#: wrappers, and two corridors in the same county both miss on the same grid-rounded
#: network query. A registry per wrapper would leave exactly that case uncoordinated,
#: which is the only case that costs anything.
#:
#: Keys are content-addressed digests, so two caches in different directories that share
#: a key would serialise unnecessarily. That is a rare and harmless wait for an
#: identical question.
_PROCESS_FLIGHT = SingleFlight()


def _through_cache(
    cache: Cache,
    report: CacheReport,
    flight: SingleFlight,
    key: str,
    source: str,
    fetch: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Answer from the cache, or fetch once however many callers are asking.

    The first `get` is outside the lock, so a hit — the overwhelmingly common case —
    never waits for anybody. Only a miss takes the lock, and re-reads under it: the
    thread that lost the race wakes to an answer somebody else has already paid for, and
    records it as the hit it now is.
    """
    entry = cache.get(key)
    if entry is not None:
        report.record_hit(entry)
        return entry.payload

    with flight.lock_for(key):
        entry = cache.get(key)
        if entry is not None:
            report.record_hit(entry)
            return entry.payload

        report.record_miss()
        payload = fetch()
        cache.put(key, source, payload)
        return payload


@dataclass
class CachedOverpass:
    """An Overpass client that remembers its answers, keyed by the query text."""

    client: OverpassClient
    cache: Cache = field(default_factory=NullCache)
    report: CacheReport = field(default_factory=CacheReport)
    label: str = "overpass"
    flight: SingleFlight = field(default_factory=lambda: _PROCESS_FLIGHT, repr=False)

    def __call__(self, query: str) -> dict[str, Any]:
        key = digest(self.label, SOURCE_OVERPASS, query)
        return _through_cache(
            self.cache,
            self.report,
            self.flight,
            key,
            SOURCE_OVERPASS,
            lambda: self.client(query),
        )


@dataclass
class CachedMapillary:
    """A Mapillary client that remembers each tile, keyed by a quantised box.

    Mapillary is already asked tile by tile, so quantising those tiles is the cheapest
    possible sharing: two corridors that run down the same street ask for the same
    squares. The grid is finer than the network one because these tiles are small to
    begin with — snapping them to a tenth of a degree would multiply the area fetched
    many times over, which is the opposite of a saving.
    """

    client: Callable[[tuple[float, float, float, float]], dict[str, Any]]
    cache: Cache = field(default_factory=NullCache)
    report: CacheReport = field(default_factory=CacheReport)
    grid_deg: float = 0.005
    flight: SingleFlight = field(default_factory=lambda: _PROCESS_FLIGHT, repr=False)

    def __call__(self, bbox: tuple[float, float, float, float]) -> dict[str, Any]:
        snapped = quantise_bbox(bbox, self.grid_deg)
        key = digest("mapillary", SOURCE_MAPILLARY, snapped)
        return _through_cache(
            self.cache,
            self.report,
            self.flight,
            key,
            SOURCE_MAPILLARY,
            lambda: self.client(snapped),
        )


def cached_overpass(
    client: OverpassClient,
    cache: Cache,
    *,
    report: CacheReport | None = None,
    label: str = "overpass",
) -> CachedOverpass:
    """Wrap an Overpass client so identical queries are answered from disk."""
    return CachedOverpass(
        client=client, cache=cache, report=report or CacheReport(), label=label
    )


def cached_mapillary(
    client: Callable[[tuple[float, float, float, float]], dict[str, Any]],
    cache: Cache,
    *,
    report: CacheReport | None = None,
    grid_deg: float = 0.005,
) -> CachedMapillary:
    """Wrap a Mapillary client so each quantised tile is fetched once."""
    return CachedMapillary(
        client=client, cache=cache, report=report or CacheReport(), grid_deg=grid_deg
    )


__all__ = [
    "SOURCE_MAPILLARY",
    "SOURCE_OVERPASS",
    "CachedMapillary",
    "CachedOverpass",
    "cached_mapillary",
    "cached_overpass",
]
