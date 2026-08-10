"""Exercise the raster adapters against the live buckets, on a real road.

The test suite hands the DEM and land-cover adapters analytic surfaces, which is the
only way to assert that a 5% ramp reads 5%. What it cannot check is the part that talks
to the network: tile naming, window arithmetic, nodata, and whether the products are
still where they were. This script does that, and it is a script rather than a test
because a suite that reaches AWS is a suite that fails for reasons unrelated to the code.

    python tools/validate_rasters.py

Needs the raster extra:  pip install "roadrisk-panel[raster]"
"""

from __future__ import annotations

import sys
import time

from roadrisk.core.context import RunContext
from roadrisk.core.engine import assess
from roadrisk.core.registry import FacilityType, Region, Severity
from roadrisk.geo import build_corridor_panel, elevation_sampler, landcover_sampler
from roadrisk.geo.adapters.rasters import copernicus_dem_url, worldcover_url
from roadrisk.geo.demo import monthly_periods
from roadrisk.geo.osm import BoundingBox, HttpOverpassClient, fetch_corridor

#: Cyprus B9, Limassol up into the Troodos mountains. The corridor every other live
#: check in this repository uses, and it climbs from sea level to about 1,500 m — so a
#: DEM adapter that returns nothing, or returns flat, is obviously broken.
REF = "B9"
BBOX = BoundingBox(south=34.80, west=32.80, north=35.05, east=33.05)


def main() -> int:
    print(f"Resolving ref={REF!r} from OpenStreetMap…")
    fetched = fetch_corridor(REF, BBOX)
    print(
        f"  {fetched.n_fragments} fragments -> {fetched.n_vertices:,} vertices, "
        f"longest share {fetched.longest_share:.1%}"
    )

    first = fetched.points[0]
    print(f"\nTiles this corridor needs:\n  {copernicus_dem_url(*first)}")
    print(f"  {worldcover_url(*first)}")

    print("\nBuilding the panel with every Tier A source…")
    started = time.time()
    built = build_corridor_panel(
        fetched.points,
        periods=monthly_periods(24),
        name=REF,
        ref=REF,
        osm_client=HttpOverpassClient(),
        elevation=elevation_sampler(),
        landcover=landcover_sampler(),
    )
    print(f"  {built.summary()}   [{time.time() - started:.1f}s]")

    print("\nProvenance")
    print(built.provenance.to_string(index=False, max_colwidth=44))

    if built.skipped:
        print("\nLooked for, not found")
        for factor, adapter, reason in built.skipped:
            print(f"  {factor} via {adapter}\n    {reason}.")

    for column in ("grade_pct", "landuse_urban"):
        if column not in built.panel.columns:
            print(f"\n!! {column} did not resolve")
            continue
        per_unit = built.panel.drop_duplicates("unit_id")[column]
        print(
            f"\n{column}: min {per_unit.min():.3f}  median {per_unit.median():.3f}  "
            f"max {per_unit.max():.3f}"
        )

    print("\nAssessing…")
    assessment = assess(
        built.panel,
        snap=built.snap,
        context=RunContext(
            facility_type=FacilityType.RURAL_TWO_LANE,
            region=Region.EUROPE,
            severity=Severity.INJURY,
        ),
    )
    print(f"  {assessment.banner}")
    print(f"  factors in the model: {', '.join(assessment.factor_names) or 'none'}")
    print(f"  constant, dropped:    {', '.join(assessment.constant_factors) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
