"""Tier D adapter — whatever the client already measured.

*Client-supplied data is simply the highest-priority adapter — same code path, no
special case.* That line from the pipeline brief is the whole design, and this module is
the smallest possible amount of code that honours it: a client column becomes a
:class:`~roadrisk.geo.adapters.base.FactorValues` like any other, carrying the tier and
licence the registry declares for that factor's client slot, and fusion prefers it
because the registry declares it first — not because anything here says so.

That has a consequence worth stating: a client value can be *wrong*, and the pipeline
will notice. Supplying a speed inventory that disagrees with OSM on nine units does not
silently overwrite OSM; it wins those units and marks them low confidence, and the run
names the nine. Client data is authoritative, not infallible, and the difference is
exactly what the agreement machinery is for.

**Keyed by unit id.** The client supplies one row per unit of *this* segmentation, which
means they have to run the pipeline once to get the unit ids. Accepting a shapefile of
their own segments and apportioning it onto ours is a real piece of work — it is the
same overlay problem as conflating any two linear referencing systems — and it is not
built.

**A gap in client data is not filled.** The OSM tag adapter carries a value across a
short untagged stretch because a missing tag means nobody wrote it down. A missing row
in a client inventory is different: they surveyed the corridor and this unit is not in
the answer. That is a question for them, not a gap for us to paper over, so the factor
is refused with the units named.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from roadrisk.core.contract import UNIT_COLUMN
from roadrisk.core.registry import Factor, Registry, Tier
from roadrisk.geo.adapters.base import AdapterResult, SkippedFactor, resolve
from roadrisk.geo.errors import GeoError
from roadrisk.geo.segmentation import Segmentation


def client_slot(factor: Factor) -> str | None:
    """The name of this factor's client adapter, if the registry declares one.

    Tier D is the definition — *cannot be derived, the customer must supply it* — so it
    identifies the client slot exactly, without matching on the adapter's name. That
    matters because the slots are named for what is being supplied (``client_survey``,
    ``client_alignment``, ``client_speed_survey``) rather than uniformly.
    """
    for adapter in factor.adapters:
        if adapter.tier is Tier.D:
            return adapter.name
    return None


def read_client_values(
    values: pd.DataFrame,
    segmentation: Segmentation,
    *,
    registry: Registry,
    unit_column: str = UNIT_COLUMN,
    source: str | None = None,
) -> AdapterResult:
    """Turn a client's per-unit table into adapter values.

    Args:
        values: One row per unit. Must carry ``unit_column``; every other column whose
            name matches a registry factor's ``column`` is read, and the rest are
            reported as ignored rather than dropped in silence.
        segmentation: The units the corridor was cut into. Client rows are checked
            against these, because a unit id that is not in the segmentation means the
            table belongs to a different corridor or a different unit length.
        registry: Declares each factor's client slot, and its tier and licence.
        unit_column: Name of the unit id column in ``values``.
        source: Provenance text for the report. Defaults to a generic description;
            supply something specific — "2024 asset inventory, surveyed March" — and it
            reaches the client's own report.

    Raises:
        GeoError: The unit column is missing, unit ids are repeated, or the table
            refers to units this corridor does not have.
    """
    if unit_column not in values.columns:
        raise GeoError(
            f"client values must carry a '{unit_column}' column naming the unit each "
            f"row describes. Columns present: {', '.join(map(str, values.columns))}. "
            "Run the pipeline once without client data to obtain the unit ids."
        )

    frame = values.set_index(unit_column)
    if frame.index.has_duplicates:
        repeated = sorted(frame.index[frame.index.duplicated()].unique())[:5]
        raise GeoError(
            f"client values repeat unit id(s) {repeated}. One row per unit — two rows "
            "would make the value for that unit arbitrary."
        )

    known = pd.Index(segmentation.unit_ids)
    strangers = frame.index.difference(known)
    if len(strangers):
        raise GeoError(
            f"client values name {len(strangers)} unit id(s) this corridor does not "
            f"have, first: {sorted(map(str, strangers))[:5]}. The table belongs to a "
            "different corridor, or was produced at a different unit length."
        )

    by_column = {factor.column: factor for factor in registry.factors}
    provenance = source or (
        "Supplied by the client for this corridor, one value per unit. Client data is "
        "the highest-priority adapter in every registry chain."
    )

    resolved = []
    skipped = []
    ignored = []

    for column in frame.columns:
        factor = by_column.get(str(column))
        if factor is None:
            ignored.append(str(column))
            continue

        slot = client_slot(factor)
        if slot is None:
            skipped.append(
                SkippedFactor(
                    factor.name,
                    "client",
                    f"the registry declares no Tier D adapter for '{factor.name}', so a "
                    "client value has no slot to occupy and no licence to travel under. "
                    "Declaring one is a two-line registry change",
                )
            )
            continue

        series = pd.to_numeric(frame[column], errors="coerce").astype(float)
        series = series.reindex(known)
        missing = series.index[~np.isfinite(series)]

        if len(missing):
            skipped.append(
                SkippedFactor(
                    factor.name,
                    slot,
                    f"{len(missing)} of {len(known)} unit(s) have no client value, "
                    f"first: {sorted(map(str, missing))[:3]}. A survey that covers most "
                    "of a corridor is still a survey with holes in it, and those holes "
                    "are a question for whoever produced it rather than a gap to fill",
                )
            )
            continue

        series.index.name = UNIT_COLUMN
        resolved.append(
            resolve(
                registry,
                factor.name,
                slot,
                source=provenance,
                values=series,
                coverage=1.0,
                notes=(
                    f"{factor.name} came from the client, so it outranks every open "
                    "source in the chain. Where an open source also resolved it, the "
                    "two are compared and the units they differ on are named — client "
                    "data is authoritative, not infallible.",
                ),
            )
        )

    notes: list[str] = []
    if resolved:
        notes.append(
            f"Client data supplied {len(resolved)} factor(s): "
            + ", ".join(value.factor for value in resolved)
            + "."
        )
    if ignored:
        notes.append(
            f"{len(ignored)} client column(s) match no factor in registry "
            f"v{registry.version} and were ignored: {', '.join(sorted(ignored))}. "
            "Adding a factor to the registry is the only step needed to use one."
        )

    return AdapterResult(
        name="client", resolved=resolved, skipped=skipped, notes=notes
    )


__all__ = ["client_slot", "read_client_values"]
