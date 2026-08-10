"""The geometry path, end to end.

    centreline → corridor → segment → skeleton → snap crashes → factor values → panel

The output is a contract-valid panel that :func:`roadrisk.core.assess` consumes
directly, together with the snap report that activates gate check 6. This is the seam
between Stage 2 and Stage 1: geography produces the panel, the engine judges it, and
neither knows how the other works.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import pandas as pd

from roadrisk.core.gates import SnapReport
from roadrisk.geo.corridor import Corridor
from roadrisk.geo.geometry import CurvatureResult, compute_curvature
from roadrisk.geo.panel import attach_factor_values, build_skeleton
from roadrisk.geo.segmentation import (
    DEFAULT_TARGET_LENGTH_M,
    Segmentation,
    segment,
)
from roadrisk.geo.snapping import (
    DEFAULT_TOLERANCE_M,
    SnapOutcome,
    apply_counts,
    snap_crashes,
)


@dataclass(frozen=True)
class CorridorPanel:
    """A panel built from geography, and everything needed to defend it."""

    panel: pd.DataFrame
    corridor: Corridor
    segmentation: Segmentation
    snap: SnapReport | None = None
    snap_detail: pd.DataFrame | None = None
    curvature: CurvatureResult | None = None
    factor_columns: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def n_units(self) -> int:
        return len(self.segmentation)

    @property
    def n_rows(self) -> int:
        return int(len(self.panel))

    @property
    def total_crashes(self) -> int:
        return int(self.panel["n_crashes"].sum())

    @property
    def zero_crash_rows(self) -> int:
        return int((self.panel["n_crashes"] == 0).sum())

    def summary(self) -> str:
        return (
            f"{self.corridor.name}: {self.corridor.length_km:.2f} km in "
            f"{self.n_units:,} units, {self.n_rows:,} panel rows, "
            f"{self.total_crashes:,} crashes, "
            f"{self.zero_crash_rows:,} zero-crash rows"
        )


def build_corridor_panel(
    points: Sequence[tuple[float, float]],
    *,
    periods: Sequence[str],
    name: str = "corridor",
    crashes: pd.DataFrame | None = None,
    time_slots: Mapping[str, float] | None = None,
    target_length_m: float = DEFAULT_TARGET_LENGTH_M,
    tolerance_m: float = DEFAULT_TOLERANCE_M,
    with_curvature: bool = True,
    latitude_column: str = "latitude",
    longitude_column: str = "longitude",
    period_column: str = "period",
    time_slot_column: str | None = None,
) -> CorridorPanel:
    """Turn a centreline and a crash table into a panel the engine can assess.

    Args:
        points: Ordered centreline vertices as (latitude, longitude).
        periods: Period labels, e.g. ``["2024-01", ...]``. Must be unique.
        name: Corridor identifier, used to prefix unit ids.
        crashes: Crash table. When None the panel is all zeros — useful for Mode B,
            which needs no crash data at all.
        time_slots: Slot name to hours per period. Defaults to one whole-month slot.
        target_length_m: Nominal unit length.
        tolerance_m: Snapping tolerance from the centreline.
        with_curvature: Compute the geometry-derived factors. No network required.
        latitude_column, longitude_column, period_column, time_slot_column: Column
            names in ``crashes``.

    Returns:
        A :class:`CorridorPanel`. Pass ``.panel`` and ``.snap`` to
        :func:`roadrisk.core.assess`.
    """
    corridor = Corridor.from_latlon(points, name=name)
    segmentation = segment(corridor, target_length_m=target_length_m)
    warnings = list(corridor.warnings)

    slots = dict(time_slots) if time_slots else None
    panel = build_skeleton(segmentation, periods=periods, time_slots=slots)
    slot_names = sorted(panel["time_slot"].unique().tolist())

    outcome: SnapOutcome | None = None
    if crashes is not None and len(crashes):
        outcome = snap_crashes(
            segmentation,
            crashes,
            periods=list(periods),
            time_slots=slot_names,
            latitude_column=latitude_column,
            longitude_column=longitude_column,
            period_column=period_column,
            time_slot_column=time_slot_column,
            tolerance_m=tolerance_m,
        )
        panel = apply_counts(panel, outcome.counts)
        warnings.extend(outcome.warnings)

    factor_columns: list[str] = []
    curvature: CurvatureResult | None = None
    if with_curvature:
        curvature = compute_curvature(segmentation)
        panel = attach_factor_values(panel, curvature.values)
        factor_columns.extend(curvature.columns)
        warnings.extend(curvature.notes)

    return CorridorPanel(
        panel=panel,
        corridor=corridor,
        segmentation=segmentation,
        snap=outcome.report if outcome else None,
        snap_detail=outcome.detail if outcome else None,
        curvature=curvature,
        factor_columns=factor_columns,
        warnings=warnings,
    )


__all__ = ["CorridorPanel", "build_corridor_panel"]
