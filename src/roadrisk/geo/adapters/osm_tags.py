"""Tier A adapters — the road's own attributes, read from OSM way tags.

Six factors come from here: posted speed limit, lane count, lit proportion, sealed
proportion, footway presence and median presence. Each is a tag on the ways that carry
the corridor, and each is under-tagged somewhere in the world.

**How a tag becomes a per-unit number.** The centreline is sampled every 10 m; each
sample is attributed to the nearest OSM way that could plausibly *be* the corridor; the
unit's value is the mean over its own samples that carry the tag. Sampling by distance
rather than by way keeps the answer a length-weighted one — a 900 m way and a 40 m stub
do not get an equal vote — and it is the same trick that stopped the demo corridor
manufacturing a curvature signal out of vertex spacing.

**Missing tags are not zeros.** This is the whole difficulty of the module. OSM ``lit``
is absent on most of the target market's roads, and reading absence as "unlit" would
manufacture a lighting effect out of mapper attention. So a sample without the tag is
*no evidence*, a unit's value is the mean over the part of it that is tagged, and a
factor whose tag covers less than half the corridor is not emitted at all. The report
says which factors failed that test and by how much.

**A short untagged gap is carried across; a long one is not.** The first version of this
module refused any factor with a single unit lacking evidence, which sounded principled
and was wrong. On the real Cyprus B9, ``maxspeed`` covers 92% of the corridor and
``lanes`` 84% — and both were being discarded because three and five units out of fifty
had none. That is not caution: the registry's own note records that losing ``speed_limit``
*biases what remains*, because on the M51 adding speed doubled the curvature coefficient
rather than shrinking it. Dropping a 92%-observed factor to avoid carrying a value
across 500 m trades a small, reported approximation for a large, silent one.

So a unit with no tag of its own takes the value of the nearest unit that has one, up to
:data:`MAX_GAP_FILL_M`, and every such unit is counted in the notes and carries zero unit
coverage. Beyond that distance the gap is not a gap in tagging but a genuinely different
piece of road, and the factor drops.

**The paved-by-default convention is deliberately not applied.** Routers assume an
untagged ``highway=primary`` is sealed, and they are usually right. The iRAP sealed
versus unsealed weight is the largest in the registry at −1.0986, so being usually right
is not good enough: a corridor wrongly assumed sealed would carry a three-fold risk
factor in the wrong direction. Explicit tags only.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from shapely import STRtree
from shapely.geometry import Point

from roadrisk.core.contract import UNIT_COLUMN
from roadrisk.core.registry import Registry
from roadrisk.geo.adapters.base import (
    AdapterResult,
    SkippedFactor,
    require_slots,
    resolve,
)
from roadrisk.geo.adapters.osmdata import OsmExtract, OsmWay
from roadrisk.geo.segmentation import Segmentation

#: Spacing at which the centreline is sampled before tags are attributed. Fine enough
#: that a 50 m stretch of a different tag is visible, coarse enough that a 100 km
#: corridor is ten thousand samples rather than a million.
SAMPLE_INTERVAL_M = 10.0

#: How far a sample may sit from a way and still be carried by it. Wider than the
#: crash-snapping tolerance because the two carriageways of a divided road, and any
#: centreline exported from a slightly different OSM snapshot, both sit further out.
CARRIER_TOLERANCE_M = 20.0

#: A factor is not emitted below this share of the corridor carrying the tag. Below a
#: half, the column would be describing mapper attention more than it describes road.
MIN_CORRIDOR_COVERAGE = 0.5

#: A unit below this share of its own length tagged is reported as thin. It still gets a
#: value — the mean over what evidence there is — but a reader deserves to know that the
#: number rests on a quarter of the segment.
MIN_UNIT_COVERAGE = 0.25

#: How far a unit with no tag of its own may reach along the corridor for a value.
#: Three units at the default 500 m length: far enough to bridge the stretch where a
#: mapper stopped tagging, short enough that a value is never carried across the sort of
#: distance over which a road genuinely changes character.
MAX_GAP_FILL_M = 1500.0

#: Below this share of samples matched to any OSM way, the centreline is probably not on
#: the road it claims to be.
MIN_CARRIER_MATCH = 0.9

_MPH_TO_KMH = 1.609344

#: ``maxspeed`` values that are legal tags but carry no number.
_UNPOSTED = frozenset({"none", "walk", "signals", "variable", "unposted", "no"})

_LIT_YES = frozenset({"yes", "24/7", "automatic", "sunset-sunrise", "dusk-dawn"})
_LIT_NO = frozenset({"no", "disused"})

_PAVED = frozenset(
    {
        "paved",
        "asphalt",
        "chipseal",
        "concrete",
        "concrete:lanes",
        "concrete:plates",
        "paving_stones",
        "sett",
        "cobblestone",
        "unhewn_cobblestone",
        "metal",
        "wood",
    }
)
_UNPAVED = frozenset(
    {
        "unpaved",
        "compacted",
        "fine_gravel",
        "gravel",
        "shells",
        "rock",
        "pebblestone",
        "ground",
        "dirt",
        "earth",
        "grass",
        "grass_paver",
        "mud",
        "sand",
        "woodchips",
    }
)

_SIDEWALK_YES = frozenset({"both", "left", "right", "yes", "separate"})
_SIDEWALK_NO = frozenset({"no", "none"})

_DIVIDED_NO = frozenset({"no", "none"})


@dataclass(frozen=True)
class _TagSpec:
    """One factor, the registry slot it fills, and how to read it off a way."""

    factor: str
    adapter: str
    read: Callable[[Mapping[str, str]], float | None]
    source: str
    notes: tuple[str, ...] = ()


def _maxspeed_kmh(tags: Mapping[str, str]) -> float | None:
    """Posted limit in km/h, or None where OSM does not state a number.

    ``maxspeed=RO:urban`` and friends encode a national default rather than a sign.
    Resolving those needs a country-by-country table of implicit limits, which is a
    real piece of work and is not this; they read as untagged.
    """
    raw = str(tags.get("maxspeed", "")).strip().lower()
    if not raw or raw in _UNPOSTED:
        return None

    factor = 1.0
    if raw.endswith("mph"):
        raw, factor = raw[:-3].strip(), _MPH_TO_KMH
    elif raw.endswith("km/h"):
        raw = raw[:-4].strip()
    elif raw.endswith("kph"):
        raw = raw[:-3].strip()

    try:
        value = float(raw) * factor
    except ValueError:
        return None
    return value if 0.0 < value <= 200.0 else None


def _lanes(tags: Mapping[str, str]) -> float | None:
    try:
        value = float(str(tags.get("lanes", "")).strip())
    except ValueError:
        return None
    return value if 1.0 <= value <= 12.0 else None


def _lit(tags: Mapping[str, str]) -> float | None:
    raw = str(tags.get("lit", "")).strip().lower()
    if raw in _LIT_YES:
        return 1.0
    if raw in _LIT_NO:
        return 0.0
    return None


def _paved(tags: Mapping[str, str]) -> float | None:
    raw = str(tags.get("surface", "")).strip().lower()
    if raw in _PAVED:
        return 1.0
    if raw in _UNPAVED:
        return 0.0
    return None


def _sidewalk(tags: Mapping[str, str]) -> float | None:
    raw = str(tags.get("sidewalk", "")).strip().lower()
    if raw in _SIDEWALK_YES:
        return 1.0
    if raw in _SIDEWALK_NO:
        return 0.0

    sided = [
        str(tags.get(f"sidewalk:{side}", "")).strip().lower()
        for side in ("both", "left", "right")
    ]
    stated = [value for value in sided if value]
    if not stated:
        return None
    return 1.0 if any(value not in _SIDEWALK_NO for value in stated) else 0.0


def _median(tags: Mapping[str, str]) -> float | None:
    """Median presence from an explicit tag only.

    The reliable signal for a divided road is not a tag at all — it is the opposite
    carriageway existing as its own way, which :func:`roadrisk.geo.osm.fetch_corridor`
    already detects and reports at corridor level. That signal cannot vary along the
    corridor, so it could not feed a per-unit column even if it were read here: a
    constant column is dropped before fitting. What is left is the handful of ways that
    state it directly, which on most corridors will not clear the coverage floor — and
    that outcome, reported, is the honest one.
    """
    divider = str(tags.get("divider", "")).strip().lower()
    if divider:
        return 0.0 if divider in _DIVIDED_NO else 1.0

    dual = str(tags.get("dual_carriageway", "")).strip().lower()
    if dual in {"yes", "true"}:
        return 1.0
    if dual in _DIVIDED_NO:
        return 0.0
    return None


_SPECS: tuple[_TagSpec, ...] = (
    _TagSpec(
        factor="speed_limit",
        adapter="osm_maxspeed",
        read=_maxspeed_kmh,
        source=(
            "OpenStreetMap `maxspeed` on the ways carrying the corridor, sampled every "
            f"{SAMPLE_INTERVAL_M:.0f} m and averaged over the tagged part of each unit. "
            "mph values converted; implicit national defaults (`maxspeed=XX:urban`) "
            "read as untagged."
        ),
        notes=(
            "speed_limit is the POSTED limit. Its Mode B weight carries a permanent "
            "caveat because the Power Model exponent applies to operating speed, and "
            "posted moves operating speed by less than 1:1.",
        ),
    ),
    _TagSpec(
        factor="lanes",
        adapter="osm_lanes",
        read=_lanes,
        source=(
            "OpenStreetMap `lanes` on the ways carrying the corridor, sampled every "
            f"{SAMPLE_INTERVAL_M:.0f} m and averaged over the tagged part of each unit."
        ),
        notes=(
            "On a divided road OSM tags `lanes` per carriageway, and the corridor is "
            "one carriageway, so the count is per direction. That matches the factor's "
            "definition and does not match a total-lanes inventory.",
        ),
    ),
    _TagSpec(
        factor="lit",
        adapter="osm_lit",
        read=_lit,
        source=(
            "OpenStreetMap `lit` on the ways carrying the corridor, sampled every "
            f"{SAMPLE_INTERVAL_M:.0f} m. The unit value is the lit share of the part of "
            "the unit that states the tag; untagged road is excluded, never counted as "
            "unlit."
        ),
        notes=(
            "OSM `lit` is badly under-tagged in most of the target market. The VIIRS "
            "night-lights cross-check declared in the registry is not built yet, so "
            "this number has nothing to disagree with.",
        ),
    ),
    _TagSpec(
        factor="surface_paved",
        adapter="osm_surface",
        read=_paved,
        source=(
            "OpenStreetMap `surface` on the ways carrying the corridor, sampled every "
            f"{SAMPLE_INTERVAL_M:.0f} m and read as the sealed share of the tagged part "
            "of each unit. Explicit tags only — the paved-by-default convention for "
            "major road classes is deliberately not applied."
        ),
        notes=(
            "The sealed/unsealed weight is the largest in the registry, so assuming "
            "'paved' where OSM is silent would be the most expensive guess available. "
            "A corridor that fails this factor's coverage floor is a corridor where "
            "the surface is genuinely unknown.",
        ),
    ),
    _TagSpec(
        factor="sidewalk_present",
        adapter="osm_sidewalk",
        read=_sidewalk,
        source=(
            "OpenStreetMap `sidewalk` and `sidewalk:*` on the ways carrying the "
            f"corridor, sampled every {SAMPLE_INTERVAL_M:.0f} m; the unit value is the "
            "share of its tagged length with a footway on at least one side."
        ),
        notes=(
            "Footways mapped as separate `highway=footway` ways rather than as a tag on "
            "the road are not counted. That under-reports provision in cities mapped in "
            "detail, which is the opposite of the direction the factor's expected sign "
            "would flatter.",
        ),
    ),
    _TagSpec(
        factor="median_present",
        adapter="osm_divided",
        read=_median,
        source=(
            "OpenStreetMap `divider` / `dual_carriageway` on the ways carrying the "
            f"corridor, sampled every {SAMPLE_INTERVAL_M:.0f} m."
        ),
    ),
)


#: Every (factor, registry adapter) slot this module fills. Checked against the
#: registry before any work is done.
SLOTS: tuple[tuple[str, str], ...] = tuple(
    (spec.factor, spec.adapter) for spec in _SPECS
)


@dataclass(frozen=True)
class CarrierMatch:
    """Which OSM way carries each sample of the centreline."""

    ways: tuple[OsmWay, ...]
    chainages: np.ndarray
    unit_index: np.ndarray
    way_index: np.ndarray  # -1 where no way was within tolerance
    n_units: int
    tolerance_m: float

    @property
    def n_samples(self) -> int:
        return int(len(self.chainages))

    @property
    def match_rate(self) -> float:
        return float((self.way_index >= 0).mean()) if self.n_samples else 0.0


def carrier_candidates(extract: OsmExtract, ref: str | None) -> tuple[OsmWay, ...]:
    """Ways that could plausibly *be* the corridor.

    Narrowed to the road reference whenever one is known and anything carries it.
    Without that narrowing a frontage road 15 m away can win a sample on distance
    alone and lend the corridor its 30 km/h limit.
    """
    candidates = extract.carriers
    if ref:
        on_ref = tuple(way for way in candidates if ref in way.refs)
        if on_ref:
            return on_ref
    return candidates


def match_carriers(
    extract: OsmExtract,
    segmentation: Segmentation,
    *,
    ref: str | None = None,
    interval_m: float = SAMPLE_INTERVAL_M,
    tolerance_m: float = CARRIER_TOLERANCE_M,
) -> CarrierMatch:
    """Attribute every sample of the centreline to the OSM way that carries it.

    Samples sit at the midpoint of each interval so that every one falls strictly
    inside a unit — a sample landing exactly on a unit boundary would be ambiguous
    under the half-open chainage convention.
    """
    corridor = segmentation.corridor
    total = corridor.length_m

    count = max(int(math.ceil(total / interval_m)), 1)
    step = total / count
    chainages = (np.arange(count) + 0.5) * step

    edges = np.array(
        [unit.start_m for unit in segmentation] + [segmentation.units[-1].end_m]
    )
    unit_index = np.clip(
        np.searchsorted(edges, chainages, side="right") - 1, 0, len(segmentation) - 1
    )

    candidates = carrier_candidates(extract, ref)

    way_index = np.full(count, -1, dtype=int)
    if candidates:
        tree = STRtree([way.geometry for way in candidates])
        for position, chainage in enumerate(chainages):
            point = corridor.geometry.interpolate(float(chainage))
            hits = tree.query_nearest(point, max_distance=tolerance_m)
            if len(hits):
                way_index[position] = int(hits[0])

    return CarrierMatch(
        ways=candidates,
        chainages=chainages,
        unit_index=unit_index,
        way_index=way_index,
        n_units=len(segmentation),
        tolerance_m=tolerance_m,
    )


def read_tags(
    extract: OsmExtract,
    segmentation: Segmentation,
    *,
    registry: Registry,
    ref: str | None = None,
    interval_m: float = SAMPLE_INTERVAL_M,
    tolerance_m: float = CARRIER_TOLERANCE_M,
    min_corridor_coverage: float = MIN_CORRIDOR_COVERAGE,
    min_unit_coverage: float = MIN_UNIT_COVERAGE,
    max_gap_fill_m: float = MAX_GAP_FILL_M,
) -> AdapterResult:
    """Resolve every OSM-tag factor this corridor can support.

    Args:
        extract: A fetched :class:`~roadrisk.geo.adapters.osmdata.OsmExtract`.
        segmentation: Units covering the corridor.
        registry: Supplies the tier and licence for each adapter slot.
        ref: Road reference, used to break ties between candidate carrier ways.
        interval_m: Centreline sampling interval.
        tolerance_m: How far a sample may sit from its carrier way.
        min_corridor_coverage: Share of the corridor that must carry a tag.
        min_unit_coverage: Share of a unit below which its value is called thin.
        max_gap_fill_m: How far an untagged unit may reach along the corridor for a
            value. Beyond it the factor drops rather than being carried.

    Returns:
        An :class:`AdapterResult` naming both what resolved and what did not.
    """
    require_slots(registry, SLOTS)

    match = match_carriers(
        extract, segmentation, ref=ref, interval_m=interval_m, tolerance_m=tolerance_m
    )
    candidates = match.ways

    notes: list[str] = []
    if not candidates:
        return AdapterResult(
            name="osm_tags",
            skipped=[
                SkippedFactor(
                    spec.factor,
                    spec.adapter,
                    "no OSM way of a road class runs along this centreline, so there "
                    "are no tags to read",
                )
                for spec in _SPECS
            ],
            notes=[
                "No OSM road way was found along the centreline. Every tag-derived "
                "factor is absent, not zero."
            ],
        )

    if match.match_rate < MIN_CARRIER_MATCH:
        notes.append(
            f"Only {match.match_rate:.0%} of the centreline sits within "
            f"{tolerance_m:.0f} m of an OSM road way. Below {MIN_CARRIER_MATCH:.0%} "
            "that usually means the centreline is not the road it claims to be, or the "
            "OSM extract was fetched with too narrow a radius. Every tag-derived "
            "factor below is measured on the part that did match."
        )

    unit_ids = pd.Index(segmentation.unit_ids, name=UNIT_COLUMN)
    counts = np.bincount(match.unit_index, minlength=match.n_units).astype(float)
    midpoints = np.array([unit.midpoint_m for unit in segmentation], dtype=float)
    resolved = []
    skipped = []

    for spec in _SPECS:
        per_way = np.array(
            [_as_float(spec.read(way.tags)) for way in candidates], dtype=float
        )
        sampled = np.where(
            match.way_index >= 0, per_way[np.clip(match.way_index, 0, None)], np.nan
        )

        totals, evidence = _aggregate(sampled, match.unit_index, match.n_units)
        unit_coverage = np.divide(
            evidence, counts, out=np.zeros_like(evidence), where=counts > 0
        )
        corridor_coverage = float(evidence.sum() / match.n_samples)

        if corridor_coverage == 0.0:
            skipped.append(
                SkippedFactor(
                    spec.factor,
                    spec.adapter,
                    "no way carrying this corridor states the tag anywhere along it, "
                    "so there is nothing to measure and nothing to carry",
                )
            )
            continue

        if corridor_coverage < min_corridor_coverage:
            skipped.append(
                SkippedFactor(
                    spec.factor,
                    spec.adapter,
                    f"only {corridor_coverage:.0%} of the corridor carries the tag, "
                    f"below the {min_corridor_coverage:.0%} floor. The column would "
                    "describe mapper attention more than it describes road",
                )
            )
            continue

        means, carried, stranded = _fill_gaps(
            totals, evidence, midpoints, max_gap_fill_m
        )
        if stranded:
            skipped.append(
                SkippedFactor(
                    spec.factor,
                    spec.adapter,
                    f"{len(stranded)} of {match.n_units} unit(s) carry no tag and sit "
                    f"more than {max_gap_fill_m:.0f} m from any unit that does "
                    f"({corridor_coverage:.0%} of the corridor is tagged overall). Over "
                    "that distance a road changes character, so the value is not "
                    "carried and the factor is absent rather than invented",
                )
            )
            continue

        spec_notes = list(spec.notes)
        if carried:
            spec_notes.append(
                f"{spec.factor}: {carried} of {match.n_units} unit(s) carry no tag of "
                "their own and take the value of the nearest unit that does, within "
                f"{max_gap_fill_m:.0f} m. Those units report zero coverage — they are "
                "carried, not measured."
            )
        thin = int(((unit_coverage < min_unit_coverage) & (unit_coverage > 0)).sum())
        if thin:
            spec_notes.append(
                f"{spec.factor}: {thin} of {match.n_units} unit(s) rest on less than "
                f"{min_unit_coverage:.0%} of their length being tagged. The value is "
                "the mean over that fraction, which is honest but thin."
            )

        resolved.append(
            resolve(
                registry,
                spec.factor,
                spec.adapter,
                source=spec.source,
                values=pd.Series(means, index=unit_ids, dtype=float),
                coverage=corridor_coverage,
                unit_coverage=pd.Series(unit_coverage, index=unit_ids, dtype=float),
                notes=spec_notes,
            )
        )

    notes.append(
        f"OSM tags attributed from {len(candidates):,} candidate way(s) over "
        f"{match.n_samples:,} centreline samples at {interval_m:.0f} m spacing"
        + (f", restricted to ways carrying ref='{ref}'" if ref else "")
        + f". {len(resolved)} of {len(_SPECS)} tag factors cleared the coverage floor."
    )

    return AdapterResult(
        name="osm_tags", resolved=resolved, skipped=skipped, notes=notes
    )


def _as_float(value: float | None) -> float:
    return float("nan") if value is None else float(value)


def _fill_gaps(
    totals: np.ndarray,
    evidence: np.ndarray,
    midpoints: np.ndarray,
    max_gap_fill_m: float,
) -> tuple[np.ndarray, int, list[int]]:
    """Give every unit a value, carrying short gaps along the corridor.

    Nearest *along the corridor*, not nearest in space, and only from a unit that has
    its own evidence — so a value is never carried through a second gap and never
    borrowed from the other side of a hairpin.

    Returns the values, how many were carried, and any unit left too far from evidence
    to be given one at all.
    """
    values = np.divide(
        totals, evidence, out=np.full(len(totals), np.nan), where=evidence > 0
    )

    blanks = np.flatnonzero(evidence == 0)
    if not blanks.size:
        return values, 0, []

    donors = np.flatnonzero(evidence > 0)
    stranded: list[int] = []

    for blank in blanks:
        distances = np.abs(midpoints[donors] - midpoints[blank])
        nearest = int(np.argmin(distances))
        if distances[nearest] > max_gap_fill_m:
            stranded.append(int(blank))
        else:
            values[blank] = values[donors[nearest]]

    return values, int(blanks.size - len(stranded)), stranded


def _aggregate(
    sampled: np.ndarray,
    unit_index: np.ndarray,
    n_units: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Sum and count the samples carrying evidence, per unit."""
    present = ~np.isnan(sampled)
    totals = np.bincount(
        unit_index[present], weights=sampled[present], minlength=n_units
    ).astype(float)
    evidence = np.bincount(unit_index[present], minlength=n_units).astype(float)
    return totals, evidence


def sample_points(
    segmentation: Segmentation, interval_m: float = SAMPLE_INTERVAL_M
) -> Sequence[Point]:
    """The sample points tags are read at. Exposed for diagnostics and tests."""
    corridor = segmentation.corridor
    count = max(int(math.ceil(corridor.length_m / interval_m)), 1)
    step = corridor.length_m / count
    return [
        corridor.geometry.interpolate(float((index + 0.5) * step))
        for index in range(count)
    ]


__all__ = [
    "CARRIER_TOLERANCE_M",
    "MAX_GAP_FILL_M",
    "MIN_CARRIER_MATCH",
    "MIN_CORRIDOR_COVERAGE",
    "MIN_UNIT_COVERAGE",
    "SAMPLE_INTERVAL_M",
    "SLOTS",
    "CarrierMatch",
    "carrier_candidates",
    "match_carriers",
    "read_tags",
    "sample_points",
]
