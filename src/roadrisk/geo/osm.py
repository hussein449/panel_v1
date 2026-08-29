"""Step 2.2b — resolve a corridor from OpenStreetMap by road reference or name.

    selector + bounding box  →  fetch  →  stitch  →  bridge gaps  →  trim  →  gate

Fetching **by tag** rather than routing between two points is deliberate. A routing
engine returns the *fastest* path, which will happily leave the road you asked about and
continue on a motorway — and you would not know. Asking OSM for ``ref="B9"`` cannot
return anything that is not the B9.

**A name is the same query with a weaker guarantee, not a different mechanism.** Most
roads this product is aimed at carry a ``ref``; residential and urban streets often carry
only a ``name``, and refusing those outright put a whole class of corridor out of reach.
So a selector is a tag key and a value, and everything downstream of the query is
identical.

What makes that safe is a gate that was already here. A reference is effectively unique
inside a sensible box; a name is emphatically not, and two unrelated *High Street*s in
one box is the obvious failure. But two unrelated roads produce a **fragmented
collection** — precisely what :data:`MIN_LONGEST_SHARE` exists to refuse, with a message
that says why. The rule that makes ``ref`` trustworthy protects ``name`` too. A name is
simply held to a higher share (:data:`MIN_LONGEST_SHARE_NAME`), because it has less claim
to the benefit of the doubt — not because it is checked differently.

**The network is injectable.** :class:`OverpassClient` is a protocol; the default
implementation uses the stdlib, and tests supply a fake. Nothing here touches the
network unless a caller asks it to.

Measured against Cyprus B9 (Troodos): 69 fragments in, one line carrying 99.9% of the
length out.
"""

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge, substring

from roadrisk.geo.crs import Projector
from roadrisk.geo.errors import CorridorError

OVERPASS_ENDPOINTS: tuple[str, ...] = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)

USER_AGENT = "roadrisk-panel (road safety assessment; contact via repository)"

#: `highway` values that are not a road anybody drives on.
#:
#: **A road that does not exist cannot have a crash record, and must not be assessed.**
#: Found the expensive way: the Cyprus **A10** — Αυτοκινητόδρομος Λευκωσίας-Παλαιχωρίου
#: — is tagged `highway=construction` on all 22 of its ways, and the pipeline assessed it
#: end to end and produced a nine-page report ranking the segments of a motorway nobody
#: has driven on. Every downstream symptom traced back here: the tag adapters found
#: almost nothing to attribute because a construction way is not a road way, so **zero of
#: six tag factors cleared the coverage floor**; `ramp_density` and `poi_density` matched
#: nothing anywhere; and the geometry carried a 93.7 m median vertex spacing with hops up
#: to a kilometre, which made the curvature — the largest weight in the model — read
#: tighter than the real road.
#:
#: The report said all of those things, correctly and separately. **What it never said
#: was the one sentence that explains them: the road is not built.** So this is checked
#: at the fetch, where the tag is, rather than being left to be re-derived from six
#: symptoms further down.
#:
#: `proposed` and `planned` are roads that may never be built. `abandoned`, `disused`,
#: `razed` and `demolished` are roads that were and no longer are. Neither kind carries
#: traffic, and both are ordinary OSM tagging rather than an error.
NOT_OPEN_HIGHWAY_VALUES: frozenset[str] = frozenset(
    {
        "construction",
        "proposed",
        "planned",
        "abandoned",
        "disused",
        "razed",
        "demolished",
    }
)

#: Fragments whose ends fall within this distance are treated as continuous. OSM
#: geometry is not perfectly noded — a way can end a few metres from its neighbour,
#: usually where an editor split it. Larger than this is a genuine gap, not noise.
DEFAULT_MAX_GAP_M = 25.0

#: The longest continuous piece must carry at least this share of everything returned.
#: Below it, the fetch produced a fragmented mess rather than a corridor, and the
#: brief's "reject if the route leaves the named road" gate has its equivalent here.
MIN_LONGEST_SHARE = 0.6

#: The same test when the selector was a **name** rather than a reference.
#:
#: Higher, and deliberately so. `ref="B9"` is close enough to unique inside a sensible
#: box that anything else coming back is a data error. A name is not: "High Street"
#: matches every High Street in the box, and two of them are two corridors welded into
#: one answer. That failure looks exactly like fragmentation, so the existing gate
#: catches it — this only decides how much fragmentation is forgiven first, and a name
#: has less claim to be forgiven than a reference does.
MIN_LONGEST_SHARE_NAME = 0.8

#: The same test on a divided road, where roughly half of what comes back is the other
#: carriageway and a 0.6 threshold would reject every motorway.
#:
#: Cyprus A1 is the case that forced this: 49 ways, every one ``oneway=yes``, the
#: longest run carrying 52%. Perfectly healthy data, rejected as "fragmented". The
#: floor still catches genuinely broken input.
MIN_LONGEST_SHARE_DIVIDED = 0.25

#: Share of ways tagged one-way above which the road is treated as divided. OSM stores
#: each carriageway of a divided road as its own one-way way, so the tag is a direct
#: statement of the fact — far more dependable than inferring it from geometry, which
#: fails wherever the carriageways separate around terrain.
DIVIDED_ONEWAY_SHARE = 0.5

#: A discarded piece at least this fraction of the kept line's length is more likely a
#: parallel carriageway than a stray offshoot.
CARRIAGEWAY_SHARE = 0.4

#: Largest direction change permitted at a join between fragments.
#:
#: Without this the gap bridger will happily weld the two carriageways of a divided
#: road together, because their ends sit about 20 m apart — inside any sensible gap
#: tolerance. The result runs up one carriageway and back down the other, doubling the
#: corridor length and making linear referencing meaningless. A genuine continuation
#: barely changes direction; a hairpin can reach 120 degrees; a reversal is 180.
MAX_JOIN_TURN_DEG = 120.0

#: How far a requested start or end may sit from the assembled line.
DEFAULT_ENDPOINT_TOLERANCE_M = 250.0

#: A discarded piece whose average distance from the corridor is below this is running
#: alongside it — the opposite carriageway, a service road, or a duplicate trace.
#:
#: The distinction matters for the fragmentation gate. A dual carriageway returns two
#: runs of near-equal length, so the longest carries only ~50% of everything returned
#: and a naive gate would reject a perfectly good corridor. Duplicate coverage is not
#: missing coverage, so parallel pieces are excluded from that test and reported
#: instead.
PARALLEL_TOLERANCE_M = 60.0


@dataclass(frozen=True)
class BoundingBox:
    """A geographic box. Named fields because Overpass and GeoJSON disagree on order."""

    south: float
    west: float
    north: float
    east: float

    def __post_init__(self) -> None:
        if self.south >= self.north:
            raise CorridorError(
                f"bounding box south ({self.south}) must be below north ({self.north})"
            )
        if self.west >= self.east:
            raise CorridorError(
                f"bounding box west ({self.west}) must be left of east ({self.east})"
            )

    @classmethod
    def around(
        cls,
        points: Sequence[tuple[float, float]],
        *,
        margin_deg: float = 0.05,
    ) -> BoundingBox:
        """A box enclosing the given (latitude, longitude) points, with margin."""
        if not points:
            raise CorridorError("cannot build a bounding box from no points")
        latitudes = [lat for lat, _ in points]
        longitudes = [lon for _, lon in points]
        return cls(
            south=min(latitudes) - margin_deg,
            west=min(longitudes) - margin_deg,
            north=max(latitudes) + margin_deg,
            east=max(longitudes) + margin_deg,
        )

    def as_overpass(self) -> str:
        return f"{self.south},{self.west},{self.north},{self.east}"


class OverpassClient(Protocol):
    """Anything that can answer an Overpass QL query with parsed JSON."""

    def __call__(self, query: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class HttpOverpassClient:
    """The default client. Tries each mirror in turn.

    Overpass mirrors return 504 under load often enough that a single endpoint is not
    dependable — the Cyprus B9 fetch failed on the primary and succeeded on a mirror.
    """

    endpoints: tuple[str, ...] = OVERPASS_ENDPOINTS
    timeout_s: float = 90.0

    def __call__(self, query: str) -> dict[str, Any]:
        failures: list[str] = []
        for endpoint in self.endpoints:
            try:
                data = urllib.parse.urlencode({"data": query}).encode()
                request = urllib.request.Request(
                    endpoint, data=data, headers={"User-Agent": USER_AGENT}
                )
                with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                    return json.loads(response.read().decode())
            except Exception as exc:  # noqa: BLE001 - try the next mirror
                failures.append(f"{endpoint}: {type(exc).__name__}")

        raise CorridorError(
            "every Overpass mirror failed — "
            + "; ".join(failures)
            + ". Mirrors return 504 under load; retry, or export the road manually "
            "(run `roadrisk centreline-help`)."
        )


@dataclass(frozen=True)
class CorridorFetch:
    """An assembled centreline and everything that happened to it on the way."""

    points: list[tuple[float, float]]
    #: The selector's *value* — "B9", or "High Street". Named `ref` because it was a
    #: reference for five stages and renaming it would churn every caller to say the
    #: same thing; `selector_key` below says which tag it came from.
    ref: str
    n_fragments: int
    n_pieces_after_merge: int
    longest_share: float
    gaps_bridged: int
    discarded_pieces: int
    divided: bool = False
    excluded_km: float = 0.0
    tags: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    #: "ref" or "name". Last and defaulted so that every existing construction of this
    #: dataclass — the tests included — keeps meaning exactly what it meant.
    selector_key: str = "ref"

    @property
    def n_vertices(self) -> int:
        return len(self.points)

    @property
    def selector(self) -> Selector:
        """How this corridor was asked for, back in one piece."""
        return Selector(self.selector_key, self.ref)


@dataclass(frozen=True)
class Selector:
    """Which OSM tag identifies the road, and what it has to equal.

    Two of them exist and there will not be a third without a reason: `ref`, which is
    what a road authority calls a road, and `name`, which is what everybody else calls
    it. Both are exact matches — no regex, no fuzzy match. A near-match that silently
    returned a different road is the failure this whole module is arranged to prevent.
    """

    key: str
    value: str

    @classmethod
    def by_ref(cls, ref: str) -> Selector:
        return cls("ref", ref)

    @classmethod
    def by_name(cls, name: str) -> Selector:
        return cls("name", name)

    def __post_init__(self) -> None:
        if self.key not in ("ref", "name"):
            raise CorridorError(
                f"a road is selected by 'ref' or 'name', not {self.key!r}."
            )
        if not self.value.strip():
            raise CorridorError(f"the {self.key} to fetch cannot be empty.")

    @property
    def min_longest_share(self) -> float:
        """How much fragmentation this selector is forgiven. See the constants."""
        return MIN_LONGEST_SHARE if self.key == "ref" else MIN_LONGEST_SHARE_NAME

    def __str__(self) -> str:
        return f"{self.key}='{self.value}'"


def _quote(value: str) -> str:
    r"""Escape a tag value for an Overpass QL double-quoted string.

    Overpass takes backslash escapes inside `"..."`, so a road actually named
    ``Bill "Bojangles" Way`` — or any name carrying a backslash — has to be escaped
    rather than interpolated. Before names were selectable this could not arise, because
    a `ref` is alphanumeric; now it can, and an unescaped quote does not fail loudly. It
    ends the string early and builds a query that either errors obscurely at the mirror
    or, far worse, matches something else.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_query(
    selector: Selector | str, bbox: BoundingBox, *, timeout_s: int = 60
) -> str:
    """Overpass QL for every highway way matching this selector inside the box.

    A bare string is read as a `ref`, so every existing caller keeps working.
    """
    chosen = (
        selector if isinstance(selector, Selector) else Selector.by_ref(selector)
    )
    return (
        f"[out:json][timeout:{timeout_s}];"
        f'way["{chosen.key}"="{_quote(chosen.value)}"]["highway"]'
        f"({bbox.as_overpass()});"
        f"out geom;"
    )


def fetch_corridor(
    ref: str,
    bbox: BoundingBox,
    *,
    client: OverpassClient | None = None,
    start: tuple[float, float] | None = None,
    end: tuple[float, float] | None = None,
    max_gap_m: float = DEFAULT_MAX_GAP_M,
    endpoint_tolerance_m: float = DEFAULT_ENDPOINT_TOLERANCE_M,
) -> CorridorFetch:
    """Resolve a corridor centreline from OSM by road reference.

    The original entry point, and the one every caller that knows it wants a reference
    should keep using. :func:`fetch_corridor_by` is the same thing for a name.

    Args:
        ref: Road reference as tagged in OSM, e.g. ``"B9"``, ``"I 95"``, ``"A1"``.
        bbox: Area to search.
        client: Overpass client. Defaults to the HTTP one; inject a fake to avoid
            the network.
        start, end: Optional (latitude, longitude) to trim the corridor to.
        max_gap_m: Largest gap between fragments that will be bridged.
        endpoint_tolerance_m: How far a requested start/end may sit from the line.

    Raises:
        CorridorError: Nothing was returned, the result is too fragmented to be a
            corridor, or a requested endpoint is nowhere near the road.
    """
    return fetch_corridor_by(
        Selector.by_ref(ref),
        bbox,
        client=client,
        start=start,
        end=end,
        max_gap_m=max_gap_m,
        endpoint_tolerance_m=endpoint_tolerance_m,
    )


def fetch_corridor_by(
    selector: Selector,
    bbox: BoundingBox,
    *,
    client: OverpassClient | None = None,
    start: tuple[float, float] | None = None,
    end: tuple[float, float] | None = None,
    max_gap_m: float = DEFAULT_MAX_GAP_M,
    endpoint_tolerance_m: float = DEFAULT_ENDPOINT_TOLERANCE_M,
) -> CorridorFetch:
    """Resolve a corridor centreline from OSM by any supported selector.

    Identical to :func:`fetch_corridor` in everything but which tag is matched and how
    much fragmentation is forgiven — see :class:`Selector` and the note at the top of
    this module for why that is the whole of the difference.

    Args:
        selector: :meth:`Selector.by_ref` or :meth:`Selector.by_name`.
        bbox: Area to search.
        client: Overpass client. Defaults to the HTTP one; inject a fake to avoid
            the network.
        start, end: Optional (latitude, longitude) to trim the corridor to.
        max_gap_m: Largest gap between fragments that will be bridged.
        endpoint_tolerance_m: How far a requested start/end may sit from the line.

    Raises:
        CorridorError: Nothing was returned, the result is too fragmented to be a
            corridor, or a requested endpoint is nowhere near the road.
    """
    active = client if client is not None else HttpOverpassClient()
    payload = active(build_query(selector, bbox))
    ways = [e for e in payload.get("elements", []) if e.get("type") == "way"]

    if not ways:
        raise CorridorError(
            f"OSM returned no ways tagged {selector} inside {bbox.as_overpass()}. "
            + (
                "Check the reference is exactly as OSM spells it (they vary: 'I 95' "
                "not 'I-95', 'A1' not 'A 1') and that the box actually covers the road."
                if selector.key == "ref"
                else "Check the name is exactly as OSM spells it — it is an exact "
                "match, including case, punctuation and any language prefix — and that "
                "the box actually covers the road."
            )
        )

    ways, not_open = _drop_ways_that_are_not_a_road(ways, selector)

    lines = [
        LineString([(node["lon"], node["lat"]) for node in way["geometry"]])
        for way in ways
        if len(way.get("geometry", [])) >= 2
    ]
    if not lines:
        raise CorridorError(
            f"OSM returned {len(ways)} way(s) for {selector} but none carried "
            "geometry. The query must use 'out geom;'."
        )

    projector = Projector.for_point(lines[0].coords[0][1], lines[0].coords[0][0])
    metric = [
        LineString([projector.point_to_metric(lat, lon) for lon, lat in line.coords])
        for line in lines
    ]

    divided = _is_divided(ways)

    pieces = _merge(metric)
    line, gaps_bridged, leftovers, warnings = _assemble(pieces, max_gap_m)

    total = line.length + sum(piece.length for piece in leftovers)
    longest_share = (line.length / total) if total else 0.0
    threshold = (
        MIN_LONGEST_SHARE_DIVIDED if divided else selector.min_longest_share
    )

    if longest_share < threshold:
        raise CorridorError(
            f"the longest continuous run of {selector} carries only "
            f"{longest_share:.0%} of the {total / 1000:.1f} km returned"
            + (" (divided road)" if divided else "")
            + ". That is a fragmented collection, not a corridor. Widen the bounding "
            "box so the road is not clipped, raise max_gap_m if the road is genuinely "
            "broken into pieces, or check the "
            + ("reference" if selector.key == "ref" else "name")
            + " is right."
            + (
                ""
                if selector.key == "ref"
                else " A name is not unique the way a reference is: if this box "
                "contains two unrelated roads of the same name, this is what that "
                "looks like, and a smaller box is the fix."
            )
        )

    if not_open:
        states = sorted(
            {
                str(way.get("tags", {}).get("highway", "")).strip().lower()
                for way in not_open
            }
        )
        warnings.append(
            f"{len(not_open)} OSM way(s) carrying {selector} are tagged "
            f"{', '.join(f'highway={state}' for state in states)} and were EXCLUDED — "
            "they are not open road. The corridor assessed here is the built part only, "
            "so its chainage does not run the length of the road as it is planned, and "
            "a crash table covering the whole route will have rows that land nowhere."
        )

    excluded_km = sum(piece.length for piece in leftovers) / 1000.0
    if divided:
        warnings.append(
            f"{selector} is a DIVIDED road — {_oneway_count(ways)} of {len(ways)} "
            "OSM ways are one-way, which is how each carriageway is stored. The "
            f"corridor here is ONE carriageway ({line.length / 1000:.2f} km); "
            f"{excluded_km:.2f} km carrying the same tag was excluded, most of "
            "it the opposite direction. If the crash table covers both directions, "
            "assess each carriageway separately or widen the snapping tolerance to "
            "take in both — and say in the report which you did."
        )
    else:
        # Undivided roads can still have a parallel twin — a service road, or a
        # duplicated trace. Geometry is the only signal available there.
        parallel, _ = _classify_leftovers(leftovers, line)
        warnings.extend(_carriageway_warning(parallel, line, str(selector)))

    if start is not None or end is not None:
        line = _trim(
            line, projector, start, end, endpoint_tolerance_m, str(selector)
        )

    points = [projector.point_to_wgs84(x, y) for x, y in line.coords]
    return CorridorFetch(
        points=points,
        ref=selector.value,
        selector_key=selector.key,
        n_fragments=len(lines),
        n_pieces_after_merge=len(pieces),
        longest_share=longest_share,
        gaps_bridged=gaps_bridged,
        discarded_pieces=len(leftovers),
        divided=divided,
        excluded_km=excluded_km,
        tags=dict(ways[0].get("tags", {})),
        warnings=warnings,
    )


def _oneway_count(ways: list[dict[str, Any]]) -> int:
    return sum(
        1 for way in ways if str(way.get("tags", {}).get("oneway", "")).lower() == "yes"
    )


def _drop_ways_that_are_not_a_road(
    ways: list[dict[str, Any]], selector: Selector
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Separate the road from what is only planned, being built, or gone.

    **Refuses outright when nothing is left.** That is the A10 case in
    :data:`NOT_OPEN_HIGHWAY_VALUES`: every way under construction, no open carriageway
    anywhere, and a corridor that cannot have had a crash on it. Assessing it is not a
    degraded answer, it is an answer about a road that does not exist — so this is one
    of the few places that raises rather than warning and continuing.

    **Excludes and reports when only part is.** A motorway being extended is ordinary,
    and the built part is a real corridor worth assessing. Dropping the unbuilt part can
    leave a gap the remaining pieces cannot bridge; that is not decided here, it is left
    to the fragmentation gate, which already exists to say when what came back is not a
    corridor.
    """
    open_ways, closed = [], []
    for way in ways:
        value = str(way.get("tags", {}).get("highway", "")).strip().lower()
        (closed if value in NOT_OPEN_HIGHWAY_VALUES else open_ways).append(way)

    if not closed:
        return ways, []

    states = sorted(
        {
            str(way.get("tags", {}).get("highway", "")).strip().lower()
            for way in closed
        }
    )
    described = ", ".join(f"highway={state}" for state in states)

    if not open_ways:
        raise CorridorError(
            f"{selector} is not a road that is open: all {len(closed)} OSM way(s) "
            f"carrying it are tagged {described}. A road that has not been built — or "
            "is no longer there — cannot have a crash record, and every factor measured "
            "along it would describe a construction site rather than traffic. "
            "Assessing it would produce a confident-looking report about a road nobody "
            "has driven on. Pick a road that is open, or wait until this one is."
        )

    return open_ways, closed


def _is_divided(ways: list[dict[str, Any]]) -> bool:
    """Whether OSM says this road has separate carriageways.

    Read from the ``oneway`` tag rather than inferred from geometry. Carriageways
    routinely separate by hundreds of metres around terrain, so any distance-based
    rule is wrong exactly where the road is most interesting.
    """
    return bool(ways) and _oneway_count(ways) / len(ways) > DIVIDED_ONEWAY_SHARE


# ---- internals ---------------------------------------------------------------


def _merge(lines: list[LineString]) -> list[LineString]:
    """Join fragments sharing endpoints, longest first.

    ``linemerge`` does the whole jigsaw: it handles fragments arriving in arbitrary
    order and pointing in arbitrary directions. This was the step expected to be hard
    and turned out to be one call.
    """
    merged = linemerge(MultiLineString(lines)) if len(lines) > 1 else lines[0]
    pieces = list(merged.geoms) if merged.geom_type == "MultiLineString" else [merged]
    return sorted(pieces, key=lambda piece: piece.length, reverse=True)


def _assemble(
    pieces: list[LineString],
    max_gap_m: float,
) -> tuple[LineString, int, list[LineString], list[str]]:
    """Grow the longest piece by absorbing neighbours across small gaps.

    OSM geometry is not perfectly noded: an editor splitting a way can leave its ends
    a few metres apart. Those are not real gaps in the road and bridging them is what
    turns a handful of pieces into one corridor.
    """
    line = pieces[0]
    remaining = list(pieces[1:])
    bridged = 0

    progress = True
    while progress and remaining:
        progress = False
        for candidate in list(remaining):
            joined = _join(line, candidate, max_gap_m)
            if joined is not None:
                line = joined
                remaining.remove(candidate)
                bridged += 1
                progress = True

    warnings: list[str] = []
    if remaining:
        lost_km = sum(piece.length for piece in remaining) / 1000.0
        warnings.append(
            f"{len(remaining)} piece(s) totalling {lost_km:.2f} km carry the same road "
            f"reference but do not connect to the main line within {max_gap_m:.0f} m. "
            "They are excluded. This is usually a parallel carriageway, a slip road, "
            "or a section whose tags were edited inconsistently."
        )

    return line, bridged, remaining, warnings


def _join(line: LineString, other: LineString, max_gap_m: float) -> LineString | None:
    """Concatenate two lines if their ends are close **and** the road continues.

    Proximity alone is not enough. The two carriageways of a divided road have ends
    roughly 20 m apart, well inside any usable gap tolerance, so a distance-only test
    welds them into a line that runs out and back. The turn check is what makes the
    difference between a corridor and a hairpin loop of double the true length.
    """
    line_coords = list(line.coords)
    other_coords = list(other.coords)

    head, tail = Point(line_coords[0]), Point(line_coords[-1])
    other_head, other_tail = Point(other_coords[0]), Point(other_coords[-1])

    # Each option carries its own join index. When the other fragment is PREPENDED
    # the weld sits at len(other_coords), not len(line_coords) — getting that wrong
    # measures the turn in the middle of one of the fragments, where it is naturally
    # near zero, and waves every bad join through.
    options = [
        (tail.distance(other_head), line_coords + other_coords, len(line_coords)),
        (tail.distance(other_tail), line_coords + other_coords[::-1], len(line_coords)),
        (head.distance(other_tail), other_coords + line_coords, len(other_coords)),
        (head.distance(other_head), other_coords[::-1] + line_coords, len(other_coords)),
    ]

    for gap, coords, boundary in sorted(options, key=lambda option: option[0]):
        if gap > max_gap_m:
            return None
        if _turn_at_join(coords, boundary) <= MAX_JOIN_TURN_DEG:
            return LineString(coords)
    return None


def _turn_at_join(coords: list[tuple[float, float]], boundary: int) -> float:
    """Direction change in degrees between the two fragments being welded.

    Compares the heading of the first fragment as it ends with the heading of the
    second as it begins, **skipping the connector between them**. Measuring the
    connector instead would read the 20 m hop between two carriageways as a 90-degree
    turn and wave it through — which is precisely the bug this exists to stop.
    """
    if boundary < 2 or boundary + 1 >= len(coords):
        return 0.0

    before = _direction(coords[boundary - 2], coords[boundary - 1])
    after = _direction(coords[boundary], coords[boundary + 1])

    if before is None or after is None:
        return 0.0

    dot = max(-1.0, min(1.0, before[0] * after[0] + before[1] * after[1]))
    return math.degrees(math.acos(dot))


def _direction(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float] | None:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    return (dx / length, dy / length) if length > 0 else None


def _trim(
    line: LineString,
    projector: Projector,
    start: tuple[float, float] | None,
    end: tuple[float, float] | None,
    tolerance_m: float,
    label: str,
) -> LineString:
    """Cut the assembled line down to the requested extent.

    `label` arrives already formatted as ``ref='B9'`` or ``name='High Street'`` — see
    :meth:`Selector.__str__` — so nothing here has to know which kind it was.
    """
    start_m = 0.0
    end_m = line.length

    if start is not None:
        start_m = _chainage_of(line, projector, start, tolerance_m, label, "start")
    if end is not None:
        end_m = _chainage_of(line, projector, end, tolerance_m, label, "end")

    if start_m > end_m:
        start_m, end_m = end_m, start_m

    if end_m - start_m < 1.0:
        raise CorridorError(
            f"the start and end supplied resolve to the same point on {label}. "
            "They may both be nearest the same spot, or the wrong way round."
        )

    return substring(line, start_m, end_m)


def _chainage_of(
    line: LineString,
    projector: Projector,
    point: tuple[float, float],
    tolerance_m: float,
    selector_label: str,
    end_label: str,
) -> float:
    x, y = projector.point_to_metric(*point)
    projected = Point(x, y)
    distance = line.distance(projected)

    if distance > tolerance_m:
        raise CorridorError(
            f"the {end_label} coordinate is {distance:,.0f} m from {selector_label}, "
            f"beyond the {tolerance_m:,.0f} m tolerance. It is probably on a different "
            "road, or the road selected is not the one you meant."
        )
    return float(line.project(projected))


def _classify_leftovers(
    leftovers: list[LineString],
    line: LineString,
) -> tuple[list[LineString], list[LineString]]:
    """Split discarded pieces into ones alongside the corridor and ones elsewhere.

    A piece whose vertices sit within a median width of the corridor is covering the
    same stretch of road from the other direction. A piece a kilometre away is a
    different stretch that failed to connect.
    """
    parallel: list[LineString] = []
    detached: list[LineString] = []

    for piece in leftovers:
        coords = list(piece.coords)
        sampled = coords[:: max(len(coords) // 10, 1)] or coords
        mean_distance = sum(
            line.distance(Point(x, y)) for x, y in sampled
        ) / len(sampled)
        (parallel if mean_distance <= PARALLEL_TOLERANCE_M else detached).append(piece)

    return parallel, detached


def _carriageway_warning(
    discarded: list[LineString],
    line: LineString,
    label: str,
) -> list[str]:
    """Flag a discarded piece long enough to be the other carriageway.

    A divided road is two separate ways in OSM, both carrying the same tag. They never
    merge, because they never touch, and the turn check in :func:`_join` stops them
    being welded end to end. Taking the longest gives one direction of travel — usually
    what is wanted, but never silently.

    `label` arrives already formatted — see :meth:`Selector.__str__`.
    """
    rivals = [
        piece for piece in discarded if piece.length >= CARRIAGEWAY_SHARE * line.length
    ]
    if not rivals:
        return []

    return [
        f"A separate run of {label} is {rivals[0].length / line.length:.0%} as long "
        "as the corridor selected. On a divided road that is the opposite carriageway, "
        "which OSM stores as its own way. The corridor here is ONE direction of travel. "
        "If the crash table covers both directions, either assess each carriageway "
        "separately or widen the snapping tolerance to take in both — and say which "
        "you did."
    ]


__all__ = [
    "CARRIAGEWAY_SHARE",
    "DEFAULT_ENDPOINT_TOLERANCE_M",
    "DEFAULT_MAX_GAP_M",
    "MIN_LONGEST_SHARE",
    "MIN_LONGEST_SHARE_NAME",
    "OVERPASS_ENDPOINTS",
    "BoundingBox",
    "CorridorFetch",
    "HttpOverpassClient",
    "OverpassClient",
    "Selector",
    "build_query",
    "fetch_corridor",
    "fetch_corridor_by",
]
