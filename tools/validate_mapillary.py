"""Exercise the Mapillary adapter against the live API. Needs a free access token.

Unlike every other source in this pipeline, Mapillary requires a credential, so the
tests can only use fakes. Two corridors, because they validate different halves:

    python tools/validate_mapillary.py            # Cyprus B9 — the "no coverage" path
    python tools/validate_mapillary.py amsterdam  # dense city — the parsing path

**Run the Amsterdam one.** B9 has no street-level imagery at all, so it exercises the
refusal and nothing else: it cannot tell a corridor with no poles from a bug that drops
every pole. Amsterdam is the one that proves the class names in ``HAZARD_OBJECTS`` are
real and the geometry is read the right way round.

Create a token at https://www.mapillary.com/dashboard/developers, and **tick the `read`
scope** — a token without it authenticates fine and returns an empty result for every
query, which looks exactly like an area with no coverage. It is a credential, so it is
read from the environment and never written to the run record.
"""

from __future__ import annotations

import os
import sys
import time
from collections import Counter

from roadrisk.geo import build_corridor_panel
from roadrisk.geo.adapters.mapillary import (
    HAZARD_OBJECTS,
    TOKEN_ENV,
    HttpMapillaryClient,
    bounding_box,
    fetch_features,
)
from roadrisk.geo.corridor import Corridor
from roadrisk.geo.demo import monthly_periods
from roadrisk.geo.osm import BoundingBox, fetch_corridor

REF = "B9"
BBOX = BoundingBox(south=34.80, west=32.80, north=35.05, east=33.05)

#: A kilometre through central Amsterdam. NOT a road — a straight line across the
#: canals. Good enough to prove the adapter can read detections, and useless for
#: judging whether the density it reports is plausible, because most of it runs over
#: water and rooftops.
AMSTERDAM_LINE = [(52.3660, 4.8850), (52.3740, 4.8950)]

#: A real road in a country with dense Mapillary coverage. This is the one that says
#: whether the number is believable, because the corridor is somewhere a camera car
#: actually drove.
DUTCH_REF = "N200"
DUTCH_BBOX = BoundingBox(south=52.33, west=4.70, north=52.43, east=4.92)


def resolve_corridor(place: str) -> Corridor:
    if place == "line":
        print("Building a 1 km straight line across central Amsterdam…")
        return Corridor.from_latlon(AMSTERDAM_LINE, name="line")

    if place == "amsterdam":
        print(f"Resolving ref={DUTCH_REF!r} around Amsterdam…")
        fetched = fetch_corridor(DUTCH_REF, DUTCH_BBOX)
        print(f"  {fetched.n_fragments} fragment(s), {fetched.longest_share:.0%} longest")
        return Corridor.from_latlon(fetched.points, name=DUTCH_REF)

    print(f"Resolving ref={REF!r} from OpenStreetMap…")
    return Corridor.from_latlon(fetch_corridor(REF, BBOX).points, name=REF)


def main() -> int:
    if not os.environ.get(TOKEN_ENV):
        print(
            f"No ${TOKEN_ENV} in the environment.\n"
            "Create a free token at https://www.mapillary.com/dashboard/developers, "
            "tick the `read` scope, and set it, then run this again."
        )
        return 1

    place = sys.argv[1].lower() if len(sys.argv) > 1 else "b9"
    corridor = resolve_corridor(place)
    points = [
        corridor.projector.point_to_wgs84(x, y) for x, y in corridor.geometry.coords
    ]
    print(f"  {corridor.length_km:.2f} km")
    print(f"  bounding box (W,S,E,N) {tuple(round(v, 4) for v in bounding_box(corridor))}")

    print("\nFetching Mapillary map features…")
    started = time.time()
    features = fetch_features(corridor, client=HttpMapillaryClient())
    print(
        f"  {features.n_returned:,} feature(s) returned, {features.n_counted:,} were "
        f"roadside objects   [{time.time() - started:.1f}s]"
    )
    for note in features.warnings:
        print(f"  ! {note}")

    if features.object_values:
        print("\n  counted by class:")
        for value, count in Counter(features.object_values).most_common():
            print(f"    {count:6,}  {value}")
        unseen = sorted(set(HAZARD_OBJECTS) - set(features.object_values))
        if unseen:
            print("\n  in our list but not seen here: " + ", ".join(unseen))
    else:
        print(f"\n  none of the {len(HAZARD_OBJECTS)} counted classes appeared.")
        print(
            "  If this is a city centre, the class names are wrong and the adapter is "
            "silently counting nothing. If it is a rural road, there is simply no "
            "imagery."
        )

    built = build_corridor_panel(
        points,
        periods=monthly_periods(12),
        name=corridor.name,
        mapillary_client=HttpMapillaryClient(),
    )
    if "roadside_object_density" in built.panel.columns:
        per_unit = built.panel.drop_duplicates("unit_id")["roadside_object_density"]
        print(
            f"\nroadside_object_density: min {per_unit.min():.2f}  median "
            f"{per_unit.median():.2f}  max {per_unit.max():.2f} per km"
        )
        confidence = built.confidence
        objects = confidence[confidence["factor"] == "roadside_object_density"]
        print(f"  confidence: {sorted(set(objects['confidence']))} (Tier B caps at medium)")
    else:
        for factor, _adapter, reason in built.skipped:
            if factor == "roadside_object_density":
                print(f"\nREFUSED: {reason}.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
