"""Tier B adapter — roadside fixed objects, from Mapillary map features.

This is the cheap half of the moat. Mapillary's *map features* layer is already
extracted: somebody else has run the vision model over the street-level imagery and
published the resulting point detections. Reading it costs an HTTP request, not a GPU,
which is what separates it from :mod:`mapillary_vision` — the same imagery with our own
inference on it, at 50-150 USD of VLM calls per corridor and the main cost trap in the
pipeline.

**What the layer actually contains, versus what the registry hoped.** The registry note
on ``roadside_object_density`` said "poles, trees, walls". Only the first of those is
true. Map features are *point* detections of manufactured objects — poles, street
lights, sign supports, bollards, fire hydrants — because those are what a detector can
localise to a point. Trees and walls are segmentation classes with no point geometry and
are not in this layer at any price. The note has been corrected, and the objects counted
here are named in the source string rather than implied.

**Why this adapter refuses to produce ``roadside_hazard_score``.** The registry declares
``mapillary_detections`` against that factor too, and it is not built, deliberately. The
factor's units are the HSM roadside hazard rating: an integer 1 to 7 whose weight is
meaningless on any other scale. Turning a count of poles per kilometre into an RHR is a
modelling decision requiring a study that maps one to the other, and the registry says
so in its own note. Inventing the mapping here would put a fabricated number behind a
cited weight, which is the single worst thing this package could do.

**A token is required and is not a licence.** Mapillary's API needs a free access token;
the data is CC-BY-SA. Share-alike binds a redistributed derived *database*, not a report
with attribution — but a client who wants the panel as a dataset needs to know, so the
licence travels with the values like every other.
"""

from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import pandas as pd
from shapely.geometry import Point
from shapely.ops import substring

from roadrisk.core.contract import UNIT_COLUMN
from roadrisk.core.registry import Registry
from roadrisk.geo.adapters.base import (
    AdapterResult,
    SkippedFactor,
    require_slots,
    resolve,
)
from roadrisk.geo.adapters.osm_density import count_per_unit
from roadrisk.geo.corridor import Corridor
from roadrisk.geo.errors import CorridorError
from roadrisk.geo.segmentation import Segmentation

FACTOR = "roadside_object_density"
ADAPTER = "mapillary_detections"
SLOTS: tuple[tuple[str, str], ...] = ((FACTOR, ADAPTER),)

#: The factor this module deliberately does not fill. See the module docstring.
HAZARD_FACTOR = "roadside_hazard_score"

ENDPOINT = "https://graph.mapillary.com/map_features"
TOKEN_ENV = "MAPILLARY_ACCESS_TOKEN"

#: Object classes counted as roadside fixed objects.
#:
#: **Rigid things standing in the verge, and nothing else.** The factor exists to price
#: struck-object risk: what a vehicle leaving the carriageway hits. A pole qualifies. A
#: bench and a bin do not, and neither — after looking at real data — does signage.
#:
#: The first version of this list included ``object--sign--store``,
#: ``object--sign--advertisement``, ``object--sign--information`` and
#: ``object--banner``. Validated over central Amsterdam, those four were **591 of 1,088
#: detections — 54% of the column**. Almost all of them are mounted on building facades
#: or on frangible posts, so they are not struck-object hazards at all; what they measure
#: is shopfront density. That would have made ``roadside_object_density`` a second, noisier
#: copy of ``poi_density``, collinear with it by construction — the same trap the three
#: OSM conflict-point densities were built to avoid. Mapillary cannot distinguish a
#: freestanding billboard on a steel post from a sign screwed to a wall, so the whole
#: group is excluded rather than half-counted.
HAZARD_OBJECTS: tuple[str, ...] = (
    "object--support--utility-pole",
    "object--support--pole",
    "object--street-light",
    "object--phone-booth",
    "object--fire-hydrant",
    "object--parking-meter",
    "object--mailbox",
)

#: How far from the centreline an object counts as a roadside hazard.
#:
#: Narrower than the 50 m used for POIs and buildings, and deliberately so: those
#: measure *roadside activity*, which genuinely extends a block back, while this measures
#: *what you would hit*. The AASHTO clear zone on a rural road is roughly 9-10 m, and
#: beyond it an object is not a struck-object risk however many of them there are. The
#: allowance above that covers GPS error in the detection and the offset between our
#: centreline and the actual carriageway edge.
#:
#: Measured consequence: at 50 m in central Amsterdam this factor was counting objects on
#: parallel streets, and reported a median of 136 objects per kilometre — one every seven
#: metres, which is a description of a neighbourhood rather than of a verge.
OBJECT_TOLERANCE_M = 15.0

#: Margin added to each request box. Small — this is a roadside measure, and a wide box
#: would pull in the next street's poles for nothing.
DEFAULT_BBOX_MARGIN_M = 120.0

#: Largest span, in degrees, of a single map-features request.
#:
#: Measured against the live API, because it is not documented. A 0.053 x 0.137 degree
#: box — the bounding box of a 25 km corridor — is refused; the same request over a
#: 0.02 x 0.02 box succeeds. Neither ``limit`` nor ``object_values`` has anything to do
#: with it.
#:
#: **This is a starting size, not a safe one.** The real limit is the volume of data in
#: the answer, not the area of the question, so the same box that is comfortable through
#: farmland is refused in a city centre. See :class:`TooMuchData`.
MAX_TILE_SPAN_DEG = 0.02

#: How many times a refused tile may be halved before giving up. Three halvings turn one
#: tile into at most eight, which was enough for central Amsterdam.
MAX_SPLIT_DEPTH = 3

#: Degrees of latitude per metre. Longitude shrinks with latitude and is computed.
_DEG_PER_M_LAT = 1.0 / 111_320.0

#: Refuse rather than fire this many requests at a volunteer-funded API. A corridor
#: needing more tiles than this should be assessed in pieces.
MAX_TILES = 400


class TooMuchData(CorridorError):
    """The API refused because the answer would be too large, not because we are wrong.

    Mapillary's own words, verbatim: *"Please reduce the amount of data you're asking
    for, then retry your request"* — returned as HTTP 500, which is not what a 500
    usually means. The distinction matters because the remedy is automatic: ask for a
    smaller piece of the same thing. Every other failure needs a human.
    """


class MapillaryClient(Protocol):
    """Anything that can answer a Mapillary map-features query with parsed JSON."""

    def __call__(self, bbox: tuple[float, float, float, float]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class HttpMapillaryClient:
    """The default client. Reads its token from the environment, never from a file.

    A token in a config file ends up in a repository. Reading it from the environment
    keeps it out of the run record, out of the manifest, and out of git.
    """

    token: str | None = None
    timeout_s: float = 60.0
    limit: int = 2000

    def __call__(self, bbox: tuple[float, float, float, float]) -> dict[str, Any]:
        token = self.token or os.environ.get(TOKEN_ENV)
        if not token:
            raise CorridorError(
                f"Mapillary needs an access token and none was found in ${TOKEN_ENV}. "
                "The data is free and the token is free — create one at "
                "https://www.mapillary.com/dashboard/developers — but it is a "
                "credential, so it is read from the environment and never written to "
                "the run record."
            )

        west, south, east, north = bbox
        query = urllib.parse.urlencode(
            {
                "access_token": token,
                "fields": "id,object_value,geometry",
                "bbox": f"{west:.6f},{south:.6f},{east:.6f},{north:.6f}",
                "limit": self.limit,
            }
        )
        request = urllib.request.Request(
            f"{ENDPOINT}?{query}",
            headers={"User-Agent": "roadrisk-panel (road safety assessment)"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            # The status alone is close to useless here: Mapillary answers "your
            # question is too big" with 500, the same code it would use for its own
            # failure, and puts the actual complaint in the body. The first version of
            # this reported only the exception type and guessed "check the token",
            # which sent a real user looking in the wrong place twice over.
            # Never echo the URL — it carries the access token.
            detail = _error_detail(exc)
            if exc.code >= 500:
                raise TooMuchData(
                    f"Mapillary answered HTTP {exc.code} for this box. It said: "
                    f"{detail}"
                ) from exc
            raise CorridorError(
                f"Mapillary refused the map-features request with HTTP {exc.code}. "
                f"It said: {detail}"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            raise CorridorError(
                f"the Mapillary map-features request failed: {type(exc).__name__}. "
                "That is a transport failure rather than a refusal — check the network."
            ) from exc


def _error_detail(exc: urllib.error.HTTPError) -> str:
    """Whatever the API put in the body, trimmed and stripped of any token echo."""
    try:
        raw = exc.read().decode("utf-8", "replace").strip()
    except Exception:  # noqa: BLE001 - the body is a nicety, not a requirement
        return "(no response body)"

    if not raw:
        return "(empty response body)"

    try:
        message = json.loads(raw).get("error", {})
        if isinstance(message, dict) and message.get("message"):
            raw = str(message["message"])
    except (ValueError, AttributeError):
        pass

    return raw[:400].replace(TOKEN_ENV, "").strip() or "(empty response body)"


@dataclass(frozen=True)
class MapillaryFeatures:
    """Point detections along a corridor, projected into its CRS."""

    points: tuple[Point, ...]
    object_values: tuple[str, ...]
    n_returned: int
    bbox: tuple[float, float, float, float]
    n_tiles: int = 1
    limit_reached: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def n_counted(self) -> int:
        return len(self.points)


def bounding_box(
    corridor: Corridor, margin_m: float = DEFAULT_BBOX_MARGIN_M
) -> tuple[float, float, float, float]:
    """The corridor's whole bounding box in (west, south, east, north) degrees.

    Too large to request in one go on any real corridor — see :data:`MAX_TILE_SPAN_DEG`
    and :func:`tile_boxes`. Kept because it is what the report shows as the extent that
    was searched.
    """
    return _box(corridor, 0.0, corridor.geometry.length, margin_m)


def tile_length_m(corridor: Corridor, margin_m: float) -> float:
    """Longest run of corridor whose box is certainly under the API's limit.

    A run of length L spans at most L in each axis, so the bound is a matter of
    arithmetic rather than trial: at 60 degrees north a degree of longitude is half a
    degree of latitude in metres, and the same run needs half the tile.
    """
    latitude, _ = corridor.projector.point_to_wgs84(*corridor.geometry.coords[0])
    metres_per_degree = min(
        1.0 / _DEG_PER_M_LAT,
        (1.0 / _DEG_PER_M_LAT) * max(math.cos(math.radians(latitude)), 0.05),
    )
    usable = MAX_TILE_SPAN_DEG * metres_per_degree - 2.0 * margin_m
    return max(usable, 100.0)


def tile_boxes(
    corridor: Corridor, margin_m: float = DEFAULT_BBOX_MARGIN_M
) -> list[tuple[float, float, float, float]]:
    """The corridor's extent as a run of small boxes, each safely requestable.

    Tiled *along the corridor* rather than as a grid over its bounding box. A road is a
    line, so its bounding box is mostly empty field: gridding a 25 km diagonal corridor
    would spend four requests in five on ground the road never touches.
    """
    total = corridor.geometry.length
    step = tile_length_m(corridor, margin_m)
    count = max(int(math.ceil(total / step)), 1)

    if count > MAX_TILES:
        raise CorridorError(
            f"this corridor needs {count:,} Mapillary requests at "
            f"{step / 1000:.1f} km per tile, over the {MAX_TILES:,} cap. Mapillary's "
            "map-features endpoint refuses a box much larger than "
            f"{MAX_TILE_SPAN_DEG} degrees, so a long corridor genuinely costs this many "
            "calls — assess it in pieces rather than firing them all at a free API."
        )

    edges = [min(index * step, total) for index in range(count + 1)]
    return [
        _box(corridor, start, end, margin_m)
        for start, end in zip(edges[:-1], edges[1:], strict=True)
        if end > start
    ]


def _box(
    corridor: Corridor, start_m: float, end_m: float, margin_m: float
) -> tuple[float, float, float, float]:
    """(west, south, east, north) around one run of the corridor."""
    if end_m - start_m < 1e-6:  # pragma: no cover - guarded by the caller
        run = corridor.geometry
    else:
        run = substring(corridor.geometry, start_m, end_m)

    min_x, min_y, max_x, max_y = run.bounds
    south, west = corridor.projector.point_to_wgs84(min_x - margin_m, min_y - margin_m)
    north, east = corridor.projector.point_to_wgs84(max_x + margin_m, max_y + margin_m)
    return west, south, east, north


def fetch_features(
    corridor: Corridor,
    *,
    client: MapillaryClient | None = None,
    margin_m: float = DEFAULT_BBOX_MARGIN_M,
    objects: Sequence[str] = HAZARD_OBJECTS,
    limit: int = 2000,
) -> MapillaryFeatures:
    """Fetch roadside object detections along a corridor.

    Raises:
        CorridorError: No token, a request failed, or the corridor needs more tiles
            than :data:`MAX_TILES`.
    """
    active = client if client is not None else HttpMapillaryClient(limit=limit)
    tiles = tile_boxes(corridor, margin_m)
    wanted = set(objects)

    points: list[Point] = []
    values: list[str] = []
    seen: set[str] = set()
    n_returned = 0
    limit_reached = False

    warnings: list[str] = []
    n_requests = 0

    for tile in tiles:
        data, requests, split = _fetch_tile(active, tile)
        n_requests += requests
        if split:
            warnings.append(
                f"One tile held more data than Mapillary would return in one answer and "
                f"was split into {split} pieces. That is a dense stretch, not a fault."
            )

        n_returned += len(data)
        limit_reached = limit_reached or len(data) >= limit

        for feature in data:
            # Tiles are padded, so they overlap and a pole near a boundary comes back
            # twice. Counting it twice would inflate the density of exactly the units
            # that sit on a tile edge — an artefact of our own tiling.
            identifier = str(feature.get("id", ""))
            if identifier and identifier in seen:
                continue
            seen.add(identifier)

            value = str(feature.get("object_value", ""))
            if value not in wanted:
                continue
            geometry = feature.get("geometry") or {}
            coordinates = geometry.get("coordinates")
            if not coordinates or len(coordinates) < 2:
                continue
            longitude, latitude = float(coordinates[0]), float(coordinates[1])
            x, y = corridor.projector.point_to_metric(latitude, longitude)
            points.append(Point(x, y))
            values.append(value)

    if limit_reached:
        warnings.append(
            f"At least one request returned {limit:,} features, which is the page "
            "limit. That stretch is denser than one page, so the count is a floor "
            "rather than a total. Paging within a tile is not implemented."
        )

    return MapillaryFeatures(
        points=tuple(points),
        object_values=tuple(values),
        n_returned=n_returned,
        bbox=bounding_box(corridor, margin_m),
        n_tiles=n_requests,
        limit_reached=limit_reached,
        warnings=warnings,
    )


def _fetch_tile(
    client: MapillaryClient,
    bbox: tuple[float, float, float, float],
    depth: int = 0,
) -> tuple[list[dict[str, Any]], int, int]:
    """One tile's features, halving and retrying if the answer would be too large.

    The tile size is chosen from the *area* Mapillary will accept, but what it actually
    refuses on is the *volume of the answer* — so the box that is comfortable through
    farmland is refused in a city centre. Rather than pick a tile small enough for
    Manhattan and fire a thousand requests at a rural road, the size starts generous and
    only the tiles that need it are subdivided.

    Returns the features, how many requests it took, and how many pieces it split into.
    """
    try:
        return list(client(bbox).get("data", [])), 1, 0
    except TooMuchData:
        if depth >= MAX_SPLIT_DEPTH:
            raise

    west, south, east, north = bbox
    if east - west >= north - south:
        middle = (west + east) / 2.0
        halves = [(west, south, middle, north), (middle, south, east, north)]
    else:
        middle = (south + north) / 2.0
        halves = [(west, south, east, middle), (west, middle, east, north)]

    data: list[dict[str, Any]] = []
    requests = 0
    for half in halves:
        part, part_requests, _ = _fetch_tile(client, half, depth + 1)
        data.extend(part)
        requests += part_requests
    return data, requests, len(halves)


def compute_object_density(
    segmentation: Segmentation,
    features: MapillaryFeatures,
    *,
    registry: Registry,
    tolerance_m: float = OBJECT_TOLERANCE_M,
) -> AdapterResult:
    """Roadside fixed objects per kilometre, per unit.

    Args:
        segmentation: Units covering the corridor.
        features: Detections from :func:`fetch_features`.
        registry: Supplies the tier and licence for the adapter slot.
        tolerance_m: How far from the centreline an object still counts as roadside.

    Returns:
        An :class:`AdapterResult` carrying ``roadside_object_density``, and always a
        skip entry for ``roadside_hazard_score`` explaining why it is not derived here.
    """
    require_slots(registry, SLOTS)

    hazard_refusal = SkippedFactor(
        HAZARD_FACTOR,
        ADAPTER,
        "the registry declares this adapter against it, and deriving it from detections "
        "is deliberately not implemented. The factor's units are the HSM roadside "
        "hazard rating, an integer 1 to 7 whose cited weight is meaningless on any "
        "other scale. Mapping a count of poles per kilometre onto that scale needs a "
        "study relating the two; inventing the mapping here would put a fabricated "
        "number behind a cited weight",
    )

    if not features.points:
        return AdapterResult(
            name="mapillary",
            skipped=[
                SkippedFactor(
                    FACTOR,
                    ADAPTER,
                    f"Mapillary returned {features.n_returned:,} map feature(s) for this "
                    "bounding box and none of them were roadside objects. Coverage is "
                    "street-level imagery, so it follows where people have driven with "
                    "a camera; absence here is absence of imagery, not of poles",
                ),
                hazard_refusal,
            ],
            notes=[
                "roadside_object_density: no detections along this corridor. The factor "
                "is absent, not zero — Mapillary coverage is contributed, not global."
            ],
        )

    counts = count_per_unit(list(features.points), segmentation, tolerance_m)
    lengths = pd.Series(
        [unit.length_km for unit in segmentation],
        index=pd.Index(segmentation.unit_ids, name=UNIT_COLUMN),
        dtype=float,
    )
    values = pd.Series(counts, index=lengths.index, dtype=float) / lengths

    counted = sorted(set(features.object_values))
    source = (
        f"Mapillary map features within {tolerance_m:.0f} m of the centreline, per "
        f"kilometre: {features.n_counted:,} detection(s) of "
        f"{', '.join(counted)}. Already-extracted point detections — no inference was "
        "run and no imagery was downloaded."
    )

    notes = [
        "roadside_object_density counts RIGID POINT OBJECTS IN THE VERGE — poles, "
        "lighting columns, hydrants — within "
        f"{tolerance_m:.0f} m of the centreline, which is the clear zone plus an "
        "allowance for positional error. Signage is deliberately excluded: Mapillary "
        "cannot tell a freestanding billboard from a sign on a shopfront, and counting "
        "both would turn this column into a second copy of poi_density.",
        "Trees and walls are segmentation classes with no point geometry and are not in "
        "this layer at any price, so the column under-reports roadside hazard on a "
        "treed or walled corridor.",
        "Mapillary coverage is contributed, not global: it follows where somebody has "
        "driven with a camera. A low count can mean a clear roadside or an unphotographed "
        "one, and this cannot tell them apart. Cross-check the imagery date and density "
        "before reading anything into a low value.",
        "A unit reporting ZERO is the sharp end of that: it means no detections, which "
        "is either an empty verge or an unphotographed one. Separating the two needs a "
        "second query against the imagery endpoint to ask whether a camera ever passed, "
        "which is not built — so a zero here is reported at the same coverage as any "
        "other value, and should not be read as a safe roadside.",
        "CC-BY-SA. Share-alike binds a redistributed derived DATABASE, not a report with "
        "attribution — but a client who wants the panel itself as a dataset inherits it.",
        "Tier B: this value was inferred by a model rather than stated by anyone, so "
        "fusion caps its confidence at medium by construction.",
    ]
    notes.extend(features.warnings)

    return AdapterResult(
        name="mapillary",
        resolved=[
            resolve(
                registry,
                FACTOR,
                ADAPTER,
                source=source,
                values=values,
                coverage=1.0,
                notes=notes,
            )
        ],
        skipped=[hazard_refusal],
        notes=[
            f"roadside_object_density: {features.n_counted:,} of "
            f"{features.n_returned:,} returned feature(s) were roadside objects, "
            f"{values.mean():.2f} per km on average."
        ],
    )


__all__ = [
    "DEFAULT_BBOX_MARGIN_M",
    "ENDPOINT",
    "MAX_SPLIT_DEPTH",
    "MAX_TILES",
    "MAX_TILE_SPAN_DEG",
    "HAZARD_OBJECTS",
    "OBJECT_TOLERANCE_M",
    "SLOTS",
    "TOKEN_ENV",
    "HttpMapillaryClient",
    "MapillaryClient",
    "MapillaryFeatures",
    "TooMuchData",
    "bounding_box",
    "compute_object_density",
    "fetch_features",
    "tile_boxes",
    "tile_length_m",
]
