"""Step 3 — build the panel skeleton.

The cross product of units, periods and time slots, with ``n_crashes`` initialised to
zero everywhere. Crashes are added afterwards, by snapping.

That ordering is the whole point. **Zero rows are structural, not optional.** A panel
built from the crash table can only contain places where something happened, and a
count model fitted on it estimates nothing — it redescribes its own input. Building
from geography first is what makes Mode A admissible at all, and it is check 1 in the
validation gates.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pandas as pd

from roadrisk.core.contract import (
    CRASH_COLUMN,
    DURATION_COLUMN,
    LENGTH_COLUMN,
    PERIOD_COLUMN,
    TIME_SLOT_COLUMN,
    UNIT_COLUMN,
)
from roadrisk.geo.errors import GeoError
from roadrisk.geo.segmentation import Segmentation

#: Hours in an average month, used when a caller supplies periods without durations.
HOURS_PER_MONTH = 365.25 * 24.0 / 12.0

#: A single slot covering the whole period. The honest default: a panel with no
#: temporal resolution should say so rather than invent a day/night split it cannot
#: support.
WHOLE_PERIOD_SLOT = "all"


def build_skeleton(
    segmentation: Segmentation,
    *,
    periods: Sequence[str],
    time_slots: Mapping[str, float] | None = None,
) -> pd.DataFrame:
    """Cross units with periods and time slots, at zero crashes.

    Args:
        segmentation: Units covering the corridor.
        periods: Ordered period labels, e.g. ``["2024-01", "2024-02"]``. Must be unique
            — a repeated label produces duplicate panel cells, which double-count
            exposure.
        time_slots: Slot name to hours-per-period. Defaults to one slot covering a
            whole month.

    Returns:
        A contract-valid panel: ``unit_id``, ``period``, ``time_slot``, ``n_crashes``,
        ``length_km``, ``duration_hours``.

    Raises:
        GeoError: Periods or slots are unusable.
    """
    if not periods:
        raise GeoError("at least one period is required to build a panel")

    duplicates = sorted({p for p in periods if list(periods).count(p) > 1})
    if duplicates:
        raise GeoError(
            "period labels must be unique — repeated label(s) "
            f"{duplicates} would create duplicate panel cells and double-count "
            "exposure. The input contract rejects this downstream, but it is cheaper "
            "to catch here."
        )

    slots = dict(time_slots) if time_slots else {WHOLE_PERIOD_SLOT: HOURS_PER_MONTH}
    bad = {name: hours for name, hours in slots.items() if hours <= 0}
    if bad:
        raise GeoError(
            f"time slot durations must be positive; got {bad}. Exposure of zero makes "
            "ln(exposure) undefined and the panel would be rejected."
        )

    rows = [
        {
            UNIT_COLUMN: unit.unit_id,
            PERIOD_COLUMN: period,
            TIME_SLOT_COLUMN: slot,
            CRASH_COLUMN: 0,
            LENGTH_COLUMN: unit.length_km,
            DURATION_COLUMN: hours,
        }
        for unit in segmentation
        for period in periods
        for slot, hours in slots.items()
    ]

    return pd.DataFrame(rows)


def attach_factor_values(
    panel: pd.DataFrame,
    values: pd.DataFrame,
    *,
    on: str = UNIT_COLUMN,
) -> pd.DataFrame:
    """Broadcast unit-level factor values across every period and slot of that unit.

    Unit-constant factors — curvature, grade, lane count — repeat down the panel. That
    is correct and it is also why the effective sample size for such a factor is the
    number of *units*, not the number of rows. Plain NB2 does not know that, which is
    the argument for the random-intercept rung.

    Raises:
        GeoError: A unit in the panel has no value, which would leave a gap that the
            transform layer rejects with a less helpful message.
    """
    merged = panel.merge(values, on=on, how="left", validate="many_to_one")

    added = [column for column in values.columns if column != on]
    missing = [column for column in added if merged[column].isna().any()]
    if missing:
        affected = sorted(
            merged.loc[merged[missing[0]].isna(), on].unique().tolist()
        )[:5]
        raise GeoError(
            f"factor column(s) {missing} have no value for some units, first: "
            f"{affected}. An adapter must resolve a value for every unit or supply "
            "none at all — a partial column silently changes which rows the model sees."
        )

    return merged


__all__ = [
    "HOURS_PER_MONTH",
    "WHOLE_PERIOD_SLOT",
    "attach_factor_values",
    "build_skeleton",
]
