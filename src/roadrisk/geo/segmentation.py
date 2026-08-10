"""Step 2 — cut the corridor into homogeneous units.

**This is where zero-crash rows are born.** The panel comes from the segmentation, never
from the crash table. Every unit exists because a piece of road exists, whether or not
anything ever happened on it — which is precisely what lets a count model estimate a
rate instead of redescribing the crashes it was given.

Fixed-length segmentation is implemented. Breaking at junctions, road-class changes or
admin boundaries needs OSM attributes and belongs with the adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from shapely.geometry import LineString

from roadrisk.geo.corridor import Corridor
from roadrisk.geo.errors import SegmentationError

DEFAULT_TARGET_LENGTH_M = 500.0

#: A trailing offcut shorter than this fraction of the target is merged into the unit
#: before it. Without the rule a 502 m corridor yields a 500 m unit and a 2 m unit whose
#: exposure is near zero and whose crash rate, if anything lands on it, is absurd.
RUNT_FRACTION = 0.5


@dataclass(frozen=True)
class Unit:
    """One homogeneous segment of corridor, with its chainage extent."""

    unit_id: str
    index: int
    start_m: float
    end_m: float
    geometry: LineString

    @property
    def length_m(self) -> float:
        return self.end_m - self.start_m

    @property
    def length_km(self) -> float:
        return self.length_m / 1000.0

    @property
    def midpoint_m(self) -> float:
        return (self.start_m + self.end_m) / 2.0

    def contains_chainage(self, chainage_m: float) -> bool:
        """Half-open on the right, so a boundary point belongs to exactly one unit."""
        return self.start_m <= chainage_m < self.end_m


@dataclass(frozen=True)
class Segmentation:
    """The complete set of units covering a corridor."""

    corridor: Corridor
    units: list[Unit]
    target_length_m: float

    def __len__(self) -> int:
        return len(self.units)

    def __iter__(self):
        return iter(self.units)

    @cached_property
    def total_length_km(self) -> float:
        return sum(unit.length_km for unit in self.units)

    def unit_for_chainage(self, chainage_m: float) -> Unit | None:
        """The unit containing this chainage, or None if it falls outside."""
        for unit in self.units:
            if unit.contains_chainage(chainage_m):
                return unit
        # The corridor end is the one chainage no half-open interval contains.
        if self.units and chainage_m == self.units[-1].end_m:
            return self.units[-1]
        return None

    @property
    def unit_ids(self) -> list[str]:
        return [unit.unit_id for unit in self.units]


def segment(
    corridor: Corridor,
    *,
    target_length_m: float = DEFAULT_TARGET_LENGTH_M,
    runt_fraction: float = RUNT_FRACTION,
) -> Segmentation:
    """Cut a corridor into fixed-length units.

    Chainage is continuous and exhaustive: unit *n* ends exactly where unit *n+1*
    begins, the first starts at 0, and the last ends at the corridor length. No gaps,
    no overlaps, nothing double-counted.

    Args:
        corridor: The linearly-referenced centreline.
        target_length_m: Nominal unit length.
        runt_fraction: Trailing offcuts below this fraction of the target are merged
            into the preceding unit.

    Raises:
        SegmentationError: The target length is not usable for this corridor.
    """
    if target_length_m <= 0:
        raise SegmentationError(
            f"target_length_m must be positive, got {target_length_m}"
        )

    total = corridor.length_m
    if target_length_m > total:
        raise SegmentationError(
            f"target unit length {target_length_m:.0f} m exceeds the whole corridor "
            f"({total:.0f} m). Choose a shorter unit length, or a longer corridor."
        )

    boundaries = _boundaries(total, target_length_m, runt_fraction)
    units = [
        Unit(
            unit_id=f"{corridor.name}-{index:04d}",
            index=index,
            start_m=start,
            end_m=end,
            geometry=corridor.between(start, end),
        )
        for index, (start, end) in enumerate(
            zip(boundaries[:-1], boundaries[1:], strict=True)
        )
    ]

    _check_invariants(units, total)
    return Segmentation(
        corridor=corridor, units=units, target_length_m=target_length_m
    )


def _boundaries(
    total_m: float,
    target_length_m: float,
    runt_fraction: float,
) -> list[float]:
    """Chainage breakpoints, with any trailing runt folded into the previous unit."""
    cuts = [0.0]
    position = target_length_m
    while position < total_m:
        cuts.append(position)
        position += target_length_m
    cuts.append(total_m)

    if len(cuts) > 2:
        tail = cuts[-1] - cuts[-2]
        if tail < runt_fraction * target_length_m:
            cuts.pop(-2)

    return cuts


def _check_invariants(units: list[Unit], total_m: float) -> None:
    """Assert continuity explicitly rather than trusting the arithmetic above.

    A gap or overlap here would silently change total exposure, and exposure is the
    offset every Mode A coefficient is measured against.
    """
    if not units:
        raise SegmentationError("segmentation produced no units")

    if units[0].start_m != 0.0:
        raise SegmentationError(
            f"first unit starts at {units[0].start_m:.3f} m, not 0"
        )

    if abs(units[-1].end_m - total_m) > 1e-6:
        raise SegmentationError(
            f"last unit ends at {units[-1].end_m:.3f} m, corridor is {total_m:.3f} m"
        )

    for current, following in zip(units[:-1], units[1:], strict=True):
        if abs(current.end_m - following.start_m) > 1e-6:
            raise SegmentationError(
                f"discontinuity between {current.unit_id} (ends {current.end_m:.3f}) "
                f"and {following.unit_id} (starts {following.start_m:.3f})"
            )

    for unit in units:
        if unit.length_m <= 0:
            raise SegmentationError(
                f"{unit.unit_id} has non-positive length {unit.length_m:.3f} m"
            )


__all__ = [
    "DEFAULT_TARGET_LENGTH_M",
    "RUNT_FRACTION",
    "Segmentation",
    "Unit",
    "segment",
]
