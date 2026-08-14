"""Prove the step's own test against the live network: a second corridor is free.

    python tools/validate_cache.py

Fetches the strategic network for Cyprus B9, then for a *different* road a few
kilometres away, into a fresh cache directory — and times both. The suite asserts this
with fakes and a call counter, which proves the logic; this proves the saving, which is
the only reason the cache exists.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

from roadrisk.geo import build_corridor_panel
from roadrisk.geo.cache import FileCache
from roadrisk.geo.demo import monthly_periods
from roadrisk.geo.osm import BoundingBox, HttpOverpassClient, fetch_corridor

BBOX = BoundingBox(south=34.80, west=32.80, north=35.05, east=33.05)

#: Two real roads in the same part of Cyprus. Different corridors, one region — which
#: is exactly the case the quantised bounding box is built to collapse.
ROADS = ("B9", "E601")


def run(label: str, points, cache: FileCache) -> float:
    started = time.time()
    built = build_corridor_panel(
        points,
        periods=monthly_periods(12),
        name=label,
        network_client=HttpOverpassClient(timeout_s=240.0),
        cache=cache,
    )
    elapsed = time.time() - started
    print(
        f"  {label:6s} {elapsed:6.1f}s   cache hits {built.cache.hits}, "
        f"misses {built.cache.misses}"
    )
    for note in built.warnings:
        if "cache" in note.lower():
            print(f"         {note}")
    return elapsed


def main() -> int:
    directory = Path(tempfile.mkdtemp(prefix="roadrisk-cache-"))
    cache = FileCache(directory=directory)
    print(f"Fresh cache at {directory}\n")

    try:
        corridors = []
        for ref in ROADS:
            print(f"Resolving ref={ref!r}…")
            try:
                fetched = fetch_corridor(ref, BBOX)
            except Exception as exc:  # noqa: BLE001 - a probe
                print(f"  could not resolve {ref}: {type(exc).__name__}: {exc}")
                continue
            print(f"  {len(fetched.points):,} vertices")
            corridors.append((ref, fetched.points))

        if len(corridors) < 2:
            print("\nNeed two resolvable roads in one region to demonstrate sharing.")
            return 1

        print("\nCold cache:")
        first = run(corridors[0][0], corridors[0][1], cache)

        print("\nSecond corridor, same region:")
        second = run(corridors[1][0], corridors[1][1], cache)

        print("\nSame corridor again:")
        third = run(corridors[0][0], corridors[0][1], cache)

        print(
            f"\nFirst {first:.1f}s -> second {second:.1f}s -> repeat {third:.1f}s. "
            "The second and third should be a fraction of the first; if the second is "
            "not, the two corridors did not round to the same grid cell."
        )
        return 0
    finally:
        shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
