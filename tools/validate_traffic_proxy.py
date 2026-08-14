"""Exercise the graph-centrality traffic proxy against the live OSM network.

The suite builds small graphs by hand so betweenness can be checked against an answer
worked out on paper. What it cannot check is whether a real regional network produces a
proxy that means anything — in particular whether the result survives the window-artefact
gate, which is the whole reason this adapter is more than twenty lines.

    python tools/validate_traffic_proxy.py

Reaches Overpass, so it is a script rather than a test.
"""

from __future__ import annotations

import sys
import time

import numpy as np

from roadrisk.geo import build_corridor_panel
from roadrisk.geo.adapters.graph import fetch_network
from roadrisk.geo.corridor import Corridor
from roadrisk.geo.demo import monthly_periods
from roadrisk.geo.osm import BoundingBox, HttpOverpassClient, fetch_corridor
from roadrisk.geo.segmentation import segment

REF = "B9"
BBOX = BoundingBox(south=34.80, west=32.80, north=35.05, east=33.05)


def main() -> int:
    print(f"Resolving ref={REF!r} from OpenStreetMap…")
    fetched = fetch_corridor(REF, BBOX)
    corridor = Corridor.from_latlon(fetched.points, name=REF)
    units = segment(corridor, target_length_m=500.0)
    print(f"  {corridor.length_km:.2f} km in {len(units)} units")

    for margin_km in (5.0, 10.0, 20.0):
        print(f"\n--- margin {margin_km:.0f} km " + "-" * 40)
        started = time.time()
        try:
            graph = fetch_network(
                corridor,
                client=HttpOverpassClient(timeout_s=240.0),
                margin_m=margin_km * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001 - a probe, report and continue
            print(f"  fetch failed: {type(exc).__name__}: {exc}")
            continue
        print(f"  {graph.summary()}   [fetch {time.time() - started:.1f}s]")

        started = time.time()
        built = build_corridor_panel(
            fetched.points,
            periods=monthly_periods(12),
            name=REF,
            network=graph,
        )
        print(f"  scored in {time.time() - started:.1f}s")

        if "traffic_proxy" not in built.panel.columns:
            for factor, _adapter, reason in built.skipped:
                if factor == "traffic_proxy":
                    print(f"  REFUSED: {reason}.")
            continue

        per_unit = built.panel.drop_duplicates("unit_id")["traffic_proxy"].to_numpy()
        midpoints = np.array([unit.midpoint_m for unit in units])
        centre = (midpoints[0] + midpoints[-1]) / 2.0
        template = -((midpoints - centre) ** 2)
        artefact = abs(np.corrcoef(per_unit, template)[0, 1])

        print(
            f"  traffic_proxy  min {per_unit.min():.3g}  median "
            f"{np.median(per_unit):.3g}  max {per_unit.max():.3g}"
        )
        print(f"  window-artefact correlation {artefact:.2f}")
        print(f"  peaks at unit {int(np.argmax(per_unit))} of {len(per_unit) - 1}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
