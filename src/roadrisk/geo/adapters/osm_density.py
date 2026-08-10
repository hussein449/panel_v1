"""Tier A adapters — conflict points and roadside activity, counted per kilometre.

Four factors: junction density, access density, ramp density and POI density. All four
are counts of things near the corridor, divided by unit length, and all four use the
same rule — **a feature belongs to the unit containing the point on the centreline
nearest to it**, provided that nearest approach is within the feature's own tolerance.

**The four counts are defined so they cannot overlap.** A T-junction with a residential
street is a junction; a driveway is an access; a slip road is a ramp. Each highway class
belongs to exactly one of those three sets, so a motorway off-ramp is counted once as a
ramp and never again as a junction. That matters more than the precise class boundaries:
the registry already records that ``ramp_density`` and ``access_density`` correlate at
r = 0.365 on the M51 and that the sign on ``ramp_density`` inverts between
specifications. Counting the same feature into two columns would guarantee that
collinearity rather than merely permitting it.

**A density of zero is a statement about OSM, not about the road.** A corridor where
nobody has mapped the driveways reports zero accesses per kilometre, and that column is
then constant, and a constant column is dropped before fitting. The system arrives at
the right answer — the factor does not enter the model — but the route matters: the
report must say the data was absent, not that the road has no driveways.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

from roadrisk.core.contract import UNIT_COLUMN
from roadrisk.core.registry import Registry
from roadrisk.geo.adapters.base import (
    AdapterResult,
    SkippedFactor,
    require_slots,
    resolve,
)
from roadrisk.geo.adapters.osmdata import OsmExtract
from roadrisk.geo.segmentation import Segmentation

#: How close a degree-3 vertex must come to the centreline to be a junction *on* it.
#: Tight, because a junction is a point where the corridor's own geometry meets
#: something; anything further out belongs to a different road.
JUNCTION_TOLERANCE_M = 20.0

#: How close a service road or track must come to be treated as an access onto the
#: corridor. Wider than the junction tolerance because driveways are frequently drawn
#: stopping a few metres short of the carriageway they serve.
ACCESS_TOLERANCE_M = 25.0

#: Ramps diverge from the carriageway gradually and are often drawn from the gore point
#: rather than from the running lane, so they need the widest road tolerance.
RAMP_TOLERANCE_M = 35.0

#: Roadside activity: a shop set back 40 m still generates turning movements and
#: pedestrians. Beyond about 50 m it belongs to the next street.
POI_TOLERANCE_M = 50.0


@dataclass(frozen=True)
class _DensitySpec:
    """One count-per-kilometre factor and the registry slot it fills."""

    factor: str
    adapter: str
    tolerance_m: float
    source: str
    notes: tuple[str, ...] = ()


_JUNCTION = _DensitySpec(
    factor="junction_density",
    adapter="osm_graph_nodes",
    tolerance_m=JUNCTION_TOLERANCE_M,
    source=(
        "OpenStreetMap graph: vertices where three or more road edges meet, counted "
        f"within {JUNCTION_TOLERANCE_M:.0f} m of the centreline and divided by unit "
        "length. Degree is computed over through-traffic classes only, so slip roads "
        "and driveways are not counted here — they are ramp_density and access_density."
    ),
    notes=(
        "Two ways of the same road split at a vertex give degree 2 and are correctly "
        "not a junction. A side road ending on the corridor gives degree 3 and is.",
    ),
)

_ACCESS = _DensitySpec(
    factor="access_density",
    adapter="osm_service_driveway",
    tolerance_m=ACCESS_TOLERANCE_M,
    source=(
        "OpenStreetMap `highway=service` and `highway=track` ways whose nearest "
        f"approach to the centreline is within {ACCESS_TOLERANCE_M:.0f} m, counted once "
        "each and divided by unit length. Both sides of the road."
    ),
    notes=(
        "UNITS: accesses per kilometre, which is what the HSM-derived weight expects — "
        "the per-mile conversion is already inside the weight and must not be applied "
        "to the column as well.",
        "Minor public roads joining the corridor are counted as junctions, not as "
        "accesses, so this column is driveways and service roads only. The registry's "
        "older description said 'plus minor-road joins'; counting them both ways would "
        "have made access_density and junction_density collinear by construction.",
    ),
)

_RAMP = _DensitySpec(
    factor="ramp_density",
    adapter="osm_link_ways",
    tolerance_m=RAMP_TOLERANCE_M,
    source=(
        "OpenStreetMap `highway=*_link` ways whose nearest approach to the centreline "
        f"is within {RAMP_TOLERANCE_M:.0f} m, counted once each and divided by unit "
        "length."
    ),
    notes=(
        "ramp_density is an open blocker in the registry: its sign inverts between "
        "specifications on the M51 and it is deliberately uncited. Measuring it is not "
        "the same as trusting it.",
    ),
)

_POI = _DensitySpec(
    factor="poi_density",
    adapter="osm_poi",
    tolerance_m=POI_TOLERANCE_M,
    source=(
        "OpenStreetMap nodes tagged amenity, shop, tourism, office or leisure within "
        f"{POI_TOLERANCE_M:.0f} m of the centreline, divided by unit length."
    ),
    notes=(
        "Nodes only. A supermarket mapped as a building polygon rather than a point is "
        "not counted, which under-reports activity in well-mapped areas — the opposite "
        "of the bias that would flatter this factor's expected sign.",
    ),
)

_SPECS: tuple[_DensitySpec, ...] = (_JUNCTION, _ACCESS, _RAMP, _POI)

#: Every (factor, registry adapter) slot this module fills.
SLOTS: tuple[tuple[str, str], ...] = tuple(
    (spec.factor, spec.adapter) for spec in _SPECS
)


def count_densities(
    extract: OsmExtract,
    segmentation: Segmentation,
    *,
    registry: Registry,
) -> AdapterResult:
    """Resolve the four count-per-kilometre factors from one OSM extract.

    Args:
        extract: A fetched :class:`~roadrisk.geo.adapters.osmdata.OsmExtract`.
        segmentation: Units covering the corridor.
        registry: Supplies the tier and licence for each adapter slot.

    Returns:
        An :class:`AdapterResult`. Every factor resolves whenever the extract carries
        any ways at all — a zero count is a measurement, not a gap — but an extract
        with nothing in it skips all four rather than reporting a corridor with no
        junctions.
    """
    require_slots(registry, SLOTS)

    if extract.is_empty:
        return AdapterResult(
            name="osm_density",
            skipped=[
                SkippedFactor(
                    spec.factor,
                    spec.adapter,
                    "the OSM extract is empty, so a count of zero would mean 'not "
                    "fetched' rather than 'not there'",
                )
                for spec in _SPECS
            ],
            notes=[
                "The OSM extract returned nothing along this corridor. No density "
                "factor is emitted; zero would have been a claim about the road."
            ],
        )

    features: dict[str, Sequence[BaseGeometry]] = {
        _JUNCTION.factor: extract.junction_points(),
        _ACCESS.factor: [way.geometry for way in extract.ways if way.is_access],
        _RAMP.factor: [way.geometry for way in extract.ways if way.is_link],
        _POI.factor: [node.point for node in extract.poi_nodes],
    }

    unit_ids = pd.Index(segmentation.unit_ids, name=UNIT_COLUMN)
    lengths = np.array([unit.length_km for unit in segmentation], dtype=float)

    resolved = []
    notes: list[str] = []

    for spec in _SPECS:
        counts = count_per_unit(features[spec.factor], segmentation, spec.tolerance_m)
        densities = counts / lengths

        spec_notes = list(spec.notes)
        if counts.sum() == 0:
            spec_notes.append(
                f"{spec.factor}: nothing matched anywhere on this corridor. That is a "
                "statement about what OSM has mapped here, not about the road. The "
                "column is constant and will be dropped before fitting."
            )

        resolved.append(
            resolve(
                registry,
                spec.factor,
                spec.adapter,
                source=spec.source,
                values=pd.Series(densities, index=unit_ids, dtype=float),
                coverage=1.0,
                notes=spec_notes,
            )
        )
        notes.append(
            f"{spec.factor}: {int(counts.sum()):,} feature(s) within "
            f"{spec.tolerance_m:.0f} m of the centreline, "
            f"{densities.mean():.2f} per km on average."
        )

    return AdapterResult(name="osm_density", resolved=resolved, notes=notes)


def count_per_unit(
    features: Sequence[BaseGeometry],
    segmentation: Segmentation,
    tolerance_m: float,
) -> np.ndarray:
    """Count features against the unit their nearest point on the centreline falls in.

    A feature further than ``tolerance_m`` from the corridor is not counted at all. A
    long feature — a track running beside the road for a kilometre — is counted once,
    at its closest approach, because it is one access rather than one per unit it
    passes.
    """
    counts = np.zeros(len(segmentation), dtype=float)
    corridor = segmentation.corridor
    index = {unit.unit_id: position for position, unit in enumerate(segmentation)}

    for feature in features:
        if feature.is_empty:
            continue
        on_line, on_feature = nearest_points(corridor.geometry, feature)
        if on_line.distance(on_feature) > tolerance_m:
            continue
        unit = segmentation.unit_for_chainage(corridor.geometry.project(on_line))
        if unit is not None:
            counts[index[unit.unit_id]] += 1.0

    return counts


__all__ = [
    "ACCESS_TOLERANCE_M",
    "JUNCTION_TOLERANCE_M",
    "POI_TOLERANCE_M",
    "RAMP_TOLERANCE_M",
    "SLOTS",
    "count_densities",
    "count_per_unit",
]
