"""Step 4 — snap the client's crashes onto the corridor.

Police crash coordinates are frequently bad: geocoded to a town centre, to the nearest
named junction, or to a road that merely sounds similar. Snapping is where that quality
becomes visible instead of becoming a silent bias.

**Every crash that does not land is counted and given a reason.** A corridor where 40%
of the crash table failed to snap has not produced a lower risk estimate — it has
produced an unreliable one, and the gate that refuses Mode A on a poor snap rate
(check 6) only works because this module reports honestly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import pandas as pd

from roadrisk.core.contract import (
    CRASH_COLUMN,
    PERIOD_COLUMN,
    TIME_SLOT_COLUMN,
    UNIT_COLUMN,
)
from roadrisk.core.gates import SnapReport
from roadrisk.geo.errors import SnapError
from roadrisk.geo.segmentation import Segmentation

#: How far from the centreline a crash may sit and still be counted. Wide enough for
#: ordinary GPS error and a dual carriageway; narrow enough to reject a crash geocoded
#: to a parallel street.
DEFAULT_TOLERANCE_M = 30.0

#: Past this, a crash is not a near miss — it is somewhere else.
#:
#: **The two are different facts and were reported as one.** On the A6 test, 134 of 284
#: crashes were dropped as `beyond_tolerance`, which reads as poor geocoding and provoked
#: exactly the wrong response: raise the tolerance. Measured, the distances were bimodal —
#: a median of **9 m**, and a 75th percentile of **9.2 km**. Half the table was sitting on
#: the carriageway, and 129 crashes were kilometres away, on stretches of the same road
#: that the fetch had not returned. Widening the tolerance from 30 m to 150 m recovered
#: **two** of them.
#:
#: 500 m because nothing legitimate reaches it. Ordinary GPS error is metres; a dual
#: carriageway separates by tens; a parallel service road by less than a hundred. A crash
#: half a kilometre off the line is on a different road, or on a different part of this
#: one, and no tolerance that admitted it would be placing it correctly.
FAR_FROM_CORRIDOR_M = 500.0

REASON_MISSING_COORDINATES = "missing_coordinates"
REASON_BEYOND_TOLERANCE = "beyond_tolerance"
#: Not a quality problem with the crash table — a mismatch between what was supplied and
#: what was assessed. Usually a national extract handed to one corridor.
REASON_OFF_CORRIDOR = "not_on_this_corridor"
REASON_MISSING_PERIOD = "missing_period"
REASON_UNKNOWN_PERIOD = "period_not_in_panel"
REASON_UNKNOWN_TIME_SLOT = "time_slot_not_in_panel"


@dataclass(frozen=True)
class SnapOutcome:
    """Crash counts per panel cell, the audit trail, and the quality report."""

    counts: pd.DataFrame
    report: SnapReport
    detail: pd.DataFrame
    tolerance_m: float
    warnings: list[str] = field(default_factory=list)

    @property
    def n_snapped(self) -> int:
        return self.report.n_snapped

    @property
    def snap_rate(self) -> float:
        return self.report.snap_rate


def snap_crashes(
    segmentation: Segmentation,
    crashes: pd.DataFrame,
    *,
    periods: Sequence[str],
    time_slots: Sequence[str],
    latitude_column: str = "latitude",
    longitude_column: str = "longitude",
    period_column: str = "period",
    time_slot_column: str | None = None,
    tolerance_m: float = DEFAULT_TOLERANCE_M,
) -> SnapOutcome:
    """Project each crash onto the corridor and assign it to a panel cell.

    Args:
        segmentation: Units covering the corridor.
        crashes: One row per crash, with coordinates and a period label.
        periods: Period labels present in the panel.
        time_slots: Time slot labels present in the panel.
        latitude_column, longitude_column: Coordinate columns, in degrees.
        period_column: Column holding the period label each crash belongs to.
        time_slot_column: Column holding the time slot. When None, and the panel has
            exactly one slot, every crash goes to that slot.
        tolerance_m: Maximum perpendicular distance from the centreline.

    Raises:
        SnapError: Required columns are absent, or the time slot is ambiguous.
    """
    _require_columns(crashes, latitude_column, longitude_column, period_column)

    if time_slot_column is None and len(time_slots) != 1:
        raise SnapError(
            f"the panel has {len(time_slots)} time slots, so each crash must carry one. "
            "Supply time_slot_column, or build the panel with a single slot."
        )

    corridor = segmentation.corridor
    known_periods = set(periods)
    known_slots = set(time_slots)
    default_slot = time_slots[0] if time_slot_column is None else None

    records: list[dict[str, object]] = []
    dropped: dict[str, int] = {}

    for position, row in enumerate(crashes.itertuples(index=False)):
        latitude = getattr(row, latitude_column, None)
        longitude = getattr(row, longitude_column, None)
        period = getattr(row, period_column, None)
        slot = default_slot if time_slot_column is None else getattr(row, time_slot_column, None)

        reason = None
        unit_id = None
        chainage = None
        distance = None

        if pd.isna(latitude) or pd.isna(longitude):
            reason = REASON_MISSING_COORDINATES
        else:
            x, y = corridor.projector.point_to_metric(float(latitude), float(longitude))
            distance = corridor.distance_to(x, y)
            chainage = corridor.chainage_of(x, y)

            if distance > FAR_FROM_CORRIDOR_M:
                reason = REASON_OFF_CORRIDOR
            elif distance > tolerance_m:
                reason = REASON_BEYOND_TOLERANCE
            elif pd.isna(period):
                reason = REASON_MISSING_PERIOD
            elif period not in known_periods:
                reason = REASON_UNKNOWN_PERIOD
            elif pd.isna(slot) or slot not in known_slots:
                reason = REASON_UNKNOWN_TIME_SLOT
            else:
                unit = segmentation.unit_for_chainage(chainage)
                if unit is None:  # pragma: no cover - chainage is always in range
                    reason = REASON_BEYOND_TOLERANCE
                else:
                    unit_id = unit.unit_id

        if reason is not None:
            dropped[reason] = dropped.get(reason, 0) + 1

        records.append(
            {
                "crash_row": position,
                UNIT_COLUMN: unit_id,
                PERIOD_COLUMN: period,
                TIME_SLOT_COLUMN: slot,
                "chainage_m": chainage,
                "distance_m": distance,
                "snapped": reason is None,
                "drop_reason": reason,
            }
        )

    detail = pd.DataFrame(records)
    snapped = detail.loc[detail["snapped"]]

    counts = (
        snapped.groupby([UNIT_COLUMN, PERIOD_COLUMN, TIME_SLOT_COLUMN], sort=False)
        .size()
        .reset_index(name=CRASH_COLUMN)
        if len(snapped)
        else pd.DataFrame(
            columns=[UNIT_COLUMN, PERIOD_COLUMN, TIME_SLOT_COLUMN, CRASH_COLUMN]
        )
    )

    report = SnapReport(
        n_supplied=int(len(crashes)),
        n_snapped=int(len(snapped)),
        dropped_reasons=dict(sorted(dropped.items())),
    )

    return SnapOutcome(
        counts=counts,
        report=report,
        detail=detail,
        tolerance_m=tolerance_m,
        warnings=_warnings(report, snapped, tolerance_m),
    )


def apply_counts(skeleton: pd.DataFrame, counts: pd.DataFrame) -> pd.DataFrame:
    """Add snapped crash counts onto the zero-initialised skeleton.

    The skeleton is the source of truth for which cells exist. A count for a cell that
    is not in the skeleton is a bug in snapping, not a new row, and it raises rather
    than quietly appearing.
    """
    if counts.empty:
        return skeleton.copy()

    keys = [UNIT_COLUMN, PERIOD_COLUMN, TIME_SLOT_COLUMN]
    merged = skeleton.merge(
        counts.rename(columns={CRASH_COLUMN: "_snapped"}),
        on=keys,
        how="left",
        validate="one_to_one",
    )

    if len(merged) != len(skeleton):  # pragma: no cover - guarded by validate=
        raise SnapError("applying crash counts changed the number of panel rows")

    unmatched = len(counts) - int(merged["_snapped"].notna().sum())
    if unmatched:
        raise SnapError(
            f"{unmatched} crash count group(s) do not correspond to any panel cell. "
            "Snapping produced a (unit, period, slot) combination the skeleton does "
            "not contain."
        )

    merged[CRASH_COLUMN] = (
        merged[CRASH_COLUMN] + merged["_snapped"].fillna(0)
    ).astype("int64")
    return merged.drop(columns=["_snapped"])


def _require_columns(crashes: pd.DataFrame, *columns: str) -> None:
    if not isinstance(crashes, pd.DataFrame):
        raise SnapError(f"crashes must be a DataFrame, got {type(crashes).__name__}")
    missing = [column for column in columns if column not in crashes.columns]
    if missing:
        raise SnapError(
            f"crash table is missing column(s): {', '.join(missing)}. "
            f"Available: {', '.join(map(str, crashes.columns))}"
        )


def _warnings(
    report: SnapReport,
    snapped: pd.DataFrame,
    tolerance_m: float,
) -> list[str]:
    notes: list[str] = []

    if report.n_supplied and report.snap_rate < 0.8:
        notes.append(
            f"Only {report.snap_rate:.1%} of crashes snapped. Below 80% the panel is "
            "not a faithful record of what happened on this road, and the mode gate "
            "will step down accordingly."
        )

    if len(snapped):
        near_limit = int((snapped["distance_m"] > 0.8 * tolerance_m).sum())
        if near_limit > 0.1 * len(snapped):
            notes.append(
                f"{near_limit:,} snapped crashes ({near_limit / len(snapped):.0%}) sit "
                f"within 20% of the {tolerance_m:.0f} m tolerance. The result is "
                "sensitive to that tolerance — try a sweep before trusting the counts."
            )

    return notes


__all__ = [
    "DEFAULT_TOLERANCE_M",
    "FAR_FROM_CORRIDOR_M",
    "REASON_BEYOND_TOLERANCE",
    "REASON_MISSING_COORDINATES",
    "REASON_MISSING_PERIOD",
    "REASON_OFF_CORRIDOR",
    "REASON_UNKNOWN_PERIOD",
    "REASON_UNKNOWN_TIME_SLOT",
    "SnapOutcome",
    "apply_counts",
    "snap_crashes",
]
