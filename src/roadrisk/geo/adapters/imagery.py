"""Has anybody actually driven this road? — street-level imagery as a second opinion.

**This is not a factor adapter.** It produces no column, enters no panel and carries no
weight. It answers one question about the corridor as a whole, and the answer is a
sentence in the report rather than a number in the model.

**Why it exists.** The Cyprus A10 was assessed end to end — 8.53 km, 17 segments, a
ranked table, a blackspot list — for a motorway that is still being built. Every one of
its OSM ways is `highway=construction`, and that tag is now refused at the fetch. But a
tag is a label somebody typed, and it can be wrong in both directions: a road that opened
last month may still be tagged as construction, and a road tagged as open may have been
closed for years. A second, *independent* source was wanted.

**Why Mapillary and not a commercial map.** The obvious cross-check is somebody else's
map, and the licence forbids it: this panel is an ODbL-derived database, and building or
correcting it from a proprietary map is exactly what those terms prohibit — which is also
why the OpenStreetMap project itself refuses that data. Mapillary is free, its imagery is
CC-BY-SA, and this package already talks to it for `roadside_object_density`. A photograph
is also better evidence than another map's opinion: somebody was physically there, in a
vehicle, on a date.

**The evidence is asymmetric, and this module is built around saying so.**

* **Photographs on the road are strong evidence it is open.** A vehicle drove it and a
  camera recorded where and when. That is close to observation.
* **No photographs are very weak evidence of anything.** Mapillary's coverage is uneven
  to the point of being absent across whole countries, and *this product exists for the
  places with the worst data*. Treating silence as "the road is not there" would refuse
  exactly the corridors it was built to serve.

So a positive result is reported as a finding and a negative result is reported as an
absence of information. **Nothing here ever refuses a corridor**, unlike the construction
gate in :mod:`roadrisk.geo.osm` — that one reads a fact somebody asserted about the road,
this one reads the absence of a photograph, and those do not deserve the same power.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from shapely.geometry import Point

from roadrisk.geo.adapters.mapillary import TOKEN_ENV, tile_boxes
from roadrisk.geo.corridor import Corridor
from roadrisk.geo.errors import CorridorError

#: The images endpoint. `map_features` — what :mod:`.mapillary` uses — is the *detections*
#: layer: what a vision model found. This is the photographs themselves, which is the
#: question here: not what is beside the road, but whether anyone was on it.
IMAGES_ENDPOINT = "https://graph.mapillary.com/images"

#: How far from the centreline a photograph still counts as taken *on* this road.
#:
#: Generous on purpose. A phone on a dashboard is GPS-located to within a few metres on a
#: good day and considerably worse in a valley or under trees, which is where these
#: corridors are. A photograph from the next street over is a false positive; one from
#: 25 m off a mountain road is the same drive with poorer reception.
DEFAULT_ON_ROAD_M = 25.0

#: Newer than this and the road was open when the picture was taken, for any purpose this
#: report has. Three years is long enough to cover thin coverage in places nobody
#: re-drives often, and short enough that a road closed since would usually show it.
RECENT_YEARS = 3


class ImageryClient(Protocol):
    """Anything that can answer a Mapillary images query with parsed JSON."""

    def __call__(self, bbox: tuple[float, float, float, float]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class HttpImageryClient:
    """The default client. Token from the environment, never from a file or a record.

    Same rule as :class:`~roadrisk.geo.adapters.mapillary.HttpMapillaryClient`, and the
    same token: a credential in a config file ends up in a repository, and one in the run
    record ends up in a report somebody forwards.
    """

    token: str | None = None
    timeout_s: float = 60.0
    limit: int = 1000

    def __call__(self, bbox: tuple[float, float, float, float]) -> dict[str, Any]:
        token = self.token or os.environ.get(TOKEN_ENV)
        if not token:
            raise CorridorError(
                f"Mapillary needs an access token and none was found in ${TOKEN_ENV}. "
                "The imagery check is skipped without one; the assessment is unaffected."
            )

        west, south, east, north = bbox
        query = urllib.parse.urlencode(
            {
                "access_token": token,
                "fields": "id,captured_at,geometry",
                "bbox": f"{west:.6f},{south:.6f},{east:.6f},{north:.6f}",
                "limit": self.limit,
            }
        )
        request = urllib.request.Request(
            f"{IMAGES_ENDPOINT}?{query}",
            headers={"User-Agent": "roadrisk-panel (road safety assessment)"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            # Never echo the URL: it carries the token.
            raise CorridorError(
                f"the Mapillary imagery request was refused with HTTP {exc.code}."
            ) from exc
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            raise CorridorError(
                f"the Mapillary imagery request failed: {type(exc).__name__}."
            ) from exc


Verdict = Literal["driven", "stale", "unseen"]


@dataclass(frozen=True)
class ImagerySurvey:
    """What street-level imagery says about whether this corridor is a working road."""

    n_on_road: int
    n_returned: int
    latest: datetime | None
    verdict: Verdict
    on_road_m: float = DEFAULT_ON_ROAD_M
    warnings: list[str] = field(default_factory=list)

    @property
    def years_since_latest(self) -> float | None:
        if self.latest is None:
            return None
        return (datetime.now(UTC) - self.latest).days / 365.25

    def note(self) -> str:
        """One sentence for the report, weighted the way the evidence is."""
        if self.verdict == "driven":
            when = self.latest.date().isoformat() if self.latest else "an unknown date"
            return (
                f"Street-level imagery confirms this road is driven: "
                f"{self.n_on_road:,} photograph(s) were taken within "
                f"{self.on_road_m:.0f} m of the centreline, the most recent on {when}. "
                "Somebody drove this corridor with a camera, which is direct evidence "
                "it was open and passable on that date."
            )
        if self.verdict == "stale":
            when = self.latest.date().isoformat() if self.latest else "an unknown date"
            years = self.years_since_latest or 0.0
            return (
                f"Street-level imagery exists for this road but is old: "
                f"{self.n_on_road:,} photograph(s) within {self.on_road_m:.0f} m of the "
                f"centreline, none newer than {when} — about {years:.0f} years ago. "
                "The road was open then. Nothing here says whether it still is."
            )
        return (
            "No street-level imagery was found along this corridor, and that is only "
            "weakly informative. Mapillary's coverage is uneven and absent across whole "
            "regions, and this method is built for exactly the places with the least "
            "data — so an unphotographed road is usually an unphotographed road, not a "
            "road that is not there. Read this beside the OSM tags rather than instead "
            "of them."
        )


def _captured(feature: dict[str, Any]) -> datetime | None:
    """Mapillary's `captured_at`, which is milliseconds since the epoch, not seconds.

    Read as seconds it puts every photograph in 1970, which would make every corridor
    look abandoned — a failure that produces a confident wrong answer rather than an
    error, so it is converted in one place and tested.
    """
    raw = feature.get("captured_at")
    if raw is None:
        return None
    try:
        return datetime.fromtimestamp(float(raw) / 1000.0, tz=UTC)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def survey_imagery(
    corridor: Corridor,
    *,
    client: ImageryClient | None = None,
    on_road_m: float = DEFAULT_ON_ROAD_M,
    recent_years: int = RECENT_YEARS,
    margin_m: float = DEFAULT_ON_ROAD_M,
) -> ImagerySurvey:
    """Ask whether anybody has driven this corridor with a camera, and when.

    Tiled along the corridor by the same helper the detections adapter uses, so a long
    road costs the same number of requests it already costs there and no new cap is
    invented.

    Raises:
        CorridorError: No token, or a request failed. Callers treat that as *not
            surveyed* rather than as a failed corridor — see :func:`describe`.
    """
    active = client if client is not None else HttpImageryClient()

    n_returned = 0
    on_road: list[datetime | None] = []
    seen: set[str] = set()
    warnings: list[str] = []

    for tile in tile_boxes(corridor, margin_m):
        payload = active(tile)
        features: Sequence[dict[str, Any]] = payload.get("data") or []
        n_returned += len(features)

        for feature in features:
            # Tiles are padded and therefore overlap; a photograph near a boundary comes
            # back twice and would be counted twice.
            identifier = str(feature.get("id", ""))
            if identifier and identifier in seen:
                continue
            seen.add(identifier)

            coordinates = (feature.get("geometry") or {}).get("coordinates")
            if not coordinates or len(coordinates) < 2:
                continue
            longitude, latitude = float(coordinates[0]), float(coordinates[1])
            x, y = corridor.projector.point_to_metric(latitude, longitude)
            if corridor.geometry.distance(Point(x, y)) > on_road_m:
                continue
            on_road.append(_captured(feature))

    dated = [when for when in on_road if when is not None]
    latest = max(dated) if dated else None

    if not on_road:
        verdict: Verdict = "unseen"
    elif latest is None:
        # Photographs on the road, none of them dated. They still prove somebody was
        # there; only the "when" is missing, so this is not treated as stale.
        verdict = "driven"
        warnings.append(
            f"{len(on_road):,} photograph(s) on this corridor carry no capture date, so "
            "how recently it was driven cannot be said."
        )
    else:
        age_years = (datetime.now(UTC) - latest).days / 365.25
        verdict = "driven" if age_years <= recent_years else "stale"

    return ImagerySurvey(
        n_on_road=len(on_road),
        n_returned=n_returned,
        latest=latest,
        verdict=verdict,
        on_road_m=on_road_m,
        warnings=warnings,
    )


def describe(
    corridor: Corridor,
    *,
    client: ImageryClient | None = None,
    on_road_m: float = DEFAULT_ON_ROAD_M,
) -> list[str]:
    """The survey as notes for the run, degrading to a note rather than an exception.

    **A missing token or a busy API must not cost a corridor its assessment.** This is a
    corroborating opinion on one question; the panel, the crashes, the factors and every
    number in the report are unaffected by whether it could be asked. So the failure is
    reported in the same place the answer would have gone.
    """
    try:
        return [survey_imagery(corridor, client=client, on_road_m=on_road_m).note()]
    except CorridorError as exc:
        return [
            f"The street-level imagery check did not run, so nothing corroborates the "
            f"OSM tags on whether this road is open: {exc}"
        ]


__all__ = [
    "DEFAULT_ON_ROAD_M",
    "IMAGES_ENDPOINT",
    "RECENT_YEARS",
    "HttpImageryClient",
    "ImageryClient",
    "ImagerySurvey",
    "Verdict",
    "describe",
    "survey_imagery",
]
