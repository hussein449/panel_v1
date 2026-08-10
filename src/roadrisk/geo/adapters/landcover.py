"""Tier A adapter — what is beside the road, from ESA WorldCover.

Feeds ``landuse_urban``: the share of the roadside classified built-up, 0 to 1. It is
the urban/rural context factor that ``population_density`` was supposed to share the job
with, and currently carries it alone.

**Sampled beside the road, never on it.** WorldCover classifies a sealed road as
built-up. Sampling the centreline would therefore report almost any paved corridor as
100% urban — a measurement of the road surface, not of its surroundings, and one that
would correlate with ``surface_paved`` instead of with land use. So each station is
sampled at four perpendicular offsets, two either side, and the centreline pixel is
never read.

Offsets start beyond the carriageway and stop before the next street: 40 m clears a
road and its shoulders at 10 m resolution, and 80 m still describes the frontage rather
than the block behind it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from roadrisk.core.contract import UNIT_COLUMN
from roadrisk.core.registry import Registry
from roadrisk.geo.adapters.base import (
    AdapterResult,
    SkippedFactor,
    require_slots,
    resolve,
)
from roadrisk.geo.adapters.rasters import (
    ESA_WORLDCOVER,
    WORLDCOVER_BUILT_UP,
    PointSampler,
)
from roadrisk.geo.adapters.sampling import stations_along, to_latlon
from roadrisk.geo.segmentation import Segmentation

FACTOR = "landuse_urban"
ADAPTER = "esa_worldcover"
SLOTS: tuple[tuple[str, str], ...] = ((FACTOR, ADAPTER),)

#: Spacing of stations along the centreline. Coarser than the tag sampler because land
#: use does not change every ten metres, and each station costs four raster reads.
STATION_INTERVAL_M = 100.0

#: Perpendicular distances sampled either side. Signed: the sign only has to be
#: consistent so the two sides do not land on the same pixel.
OFFSETS_M: tuple[float, ...] = (-80.0, -40.0, 40.0, 80.0)


def compute_landcover(
    segmentation: Segmentation,
    sampler: PointSampler,
    *,
    registry: Registry,
    station_interval_m: float = STATION_INTERVAL_M,
    offsets_m: tuple[float, ...] = OFFSETS_M,
) -> AdapterResult:
    """Built-up share of the roadside, per unit.

    Args:
        segmentation: Units covering the corridor.
        sampler: Anything returning a WorldCover class per (latitude, longitude).
        registry: Supplies the tier and licence for the adapter slot.
        station_interval_m: Spacing of stations along the centreline.
        offsets_m: Perpendicular offsets sampled at each station.

    Returns:
        An :class:`AdapterResult` carrying ``landuse_urban``, or naming why it could not.
    """
    require_slots(registry, SLOTS)

    stations = stations_along(segmentation, station_interval_m)

    classes = np.vstack(
        [
            np.asarray(
                sampler(to_latlon(segmentation, stations.chainages, offset_m=offset)),
                dtype=float,
            )
            for offset in offsets_m
        ]
    )

    valid = np.isfinite(classes)
    built = valid & (classes == float(WORLDCOVER_BUILT_UP))

    per_station_valid = valid.sum(axis=0).astype(float)
    per_station_built = built.sum(axis=0).astype(float)
    coverage = float(valid.mean()) if valid.size else 0.0

    totals = np.bincount(
        stations.unit_index, weights=per_station_built, minlength=stations.n_units
    ).astype(float)
    counted = np.bincount(
        stations.unit_index, weights=per_station_valid, minlength=stations.n_units
    ).astype(float)

    blank = int((counted == 0).sum())
    if blank:
        reason = (
            f"{blank} of {stations.n_units} unit(s) have no usable land-cover sample "
            f"({coverage:.0%} of {classes.size:,} offset samples returned a class). "
            "WorldCover leaves water and the poles unclassified; a corridor over either "
            "cannot be described this way"
            if coverage
            else f"{ESA_WORLDCOVER.name} returned no class anywhere along this "
            "centreline — the corridor is outside coverage, or the tiles it needs are "
            "not reachable"
        )
        return AdapterResult(
            name="landcover",
            skipped=[SkippedFactor(FACTOR, ADAPTER, reason)],
            notes=[
                f"landuse_urban: {coverage:.0%} of roadside samples carried a class, "
                f"but {blank} unit(s) had none. The factor is absent, not zero."
            ],
        )

    unit_ids = pd.Index(segmentation.unit_ids, name=UNIT_COLUMN)
    values = pd.Series(totals / counted, index=unit_ids, dtype=float)

    source = (
        f"{ESA_WORLDCOVER.name}, class {WORLDCOVER_BUILT_UP} (built-up), sampled at "
        f"{', '.join(f'{abs(o):.0f} m' for o in offsets_m[len(offsets_m) // 2:])} either "
        f"side of the centreline every {stations.interval_m:.0f} m. The centreline "
        "itself is never sampled — WorldCover classifies a sealed road as built-up. "
        "Read as COG windows over HTTPS range requests."
    )

    notes = [
        "landuse_urban is measured BESIDE the road, at "
        f"{'/'.join(f'{abs(o):.0f}' for o in offsets_m[len(offsets_m) // 2:])} m either "
        "side. Sampling the centreline would report any paved corridor as almost "
        "entirely built-up, because that is how WorldCover classifies a road surface — "
        "the column would then track surface_paved rather than land use.",
        f"ATTRIBUTION REQUIRED. {ESA_WORLDCOVER.attribution}",
    ]
    if coverage < 1.0:
        notes.append(
            f"landuse_urban: {1.0 - coverage:.0%} of roadside samples were unclassified "
            "(WorldCover leaves permanent water blank) and were excluded from the "
            "denominator rather than counted as not-built-up."
        )

    return AdapterResult(
        name="landcover",
        resolved=[
            resolve(
                registry,
                FACTOR,
                ADAPTER,
                source=source,
                values=values,
                coverage=coverage,
                unit_coverage=pd.Series(
                    counted / np.maximum(stations.counts() * len(offsets_m), 1.0),
                    index=unit_ids,
                    dtype=float,
                ),
            )
        ],
        notes=notes,
    )


__all__ = ["OFFSETS_M", "SLOTS", "STATION_INTERVAL_M", "compute_landcover"]
