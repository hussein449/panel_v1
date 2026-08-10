"""The adapter contract — what a source must hand back to enter the panel.

Step 4 of the pipeline brief in one sentence: *each adapter returns value, source, tier
and licence*. This module is that sentence made executable, and it is the seam that
step 2.7 will fuse across.

Three rules, each present because the alternative is a quiet lie.

**Tier and licence are read from the registry, never asserted by the adapter.** A module
names the registry slot it fills — ``osm_maxspeed``, ``osm_graph_nodes`` — and the tier
and licence travel from that declaration onto every value it produces. So an adapter
cannot promote itself from Tier B to Tier A, invent a licence, or fill a slot the
registry never declared for that factor. The declaration is the single source of truth
and the code is checked against it, not the other way round.

**A partial column is refused.** A factor column resolved for some units and not others
silently changes which rows the model sees, and the effect looks like a finding. An
adapter either resolves every unit or resolves the factor for none of them.

**An unresolved factor is named, with the reason.** Absence must be visible: a report
that says "``surface_paved``: OSM ``surface`` tagged on 12% of the corridor, below the
50% floor" is useful. A report that just omits the row is not.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from roadrisk.core.contract import UNIT_COLUMN
from roadrisk.core.registry import Licence, Registry, Tier
from roadrisk.geo.errors import GeoError


@dataclass(frozen=True)
class FactorValues:
    """One factor resolved for every unit, and everything needed to defend it.

    ``coverage`` is the share of the corridor backed by direct evidence. It is 1.0 for a
    computed factor such as curvature, and materially below 1.0 for anything read from
    OSM tags, where the honest answer is usually "part of the road says so".
    """

    factor: str
    column: str
    adapter: str
    tier: Tier
    licence: Licence
    source: str
    values: pd.Series
    coverage: float = 1.0
    unit_coverage: pd.Series | None = None
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        values = self.values
        if not isinstance(values, pd.Series):
            raise GeoError(
                f"adapter '{self.adapter}' returned {type(values).__name__} for "
                f"'{self.factor}'; a Series indexed by {UNIT_COLUMN} is required"
            )
        if values.empty:
            raise GeoError(
                f"adapter '{self.adapter}' resolved no units for '{self.factor}'. "
                "Skip the factor with a reason rather than returning an empty column."
            )
        if values.index.has_duplicates:
            repeated = sorted(values.index[values.index.duplicated()].unique())[:5]
            raise GeoError(
                f"adapter '{self.adapter}' returned repeated unit id(s) {repeated} for "
                f"'{self.factor}'. One value per unit, or the merge multiplies rows."
            )
        if not np.isfinite(values.to_numpy(dtype=float)).all():
            gaps = sorted(values.index[~np.isfinite(values.to_numpy(dtype=float))])[:5]
            raise GeoError(
                f"adapter '{self.adapter}' left '{self.factor}' unresolved on unit(s) "
                f"{gaps}. A partial column silently changes which rows the model sees — "
                "resolve every unit, or skip the factor and say why."
            )
        if not 0.0 <= self.coverage <= 1.0:
            raise GeoError(
                f"adapter '{self.adapter}' reported coverage {self.coverage} for "
                f"'{self.factor}'; coverage is a share and must lie in [0, 1]"
            )

    @property
    def n_units(self) -> int:
        return int(len(self.values))

    def as_frame(self) -> pd.DataFrame:
        """Unit id and value, in the shape :func:`attach_factor_values` consumes."""
        frame = self.values.rename(self.column).to_frame()
        frame.index.name = UNIT_COLUMN
        return frame.reset_index()

    def describe(self) -> str:
        return (
            f"{self.column} ← {self.adapter} (tier {self.tier.value}, "
            f"{self.licence.value}), {self.coverage:.0%} coverage"
        )


@dataclass(frozen=True)
class SkippedFactor:
    """A factor this adapter could have filled and deliberately did not.

    Carried through to the report. "We looked and the data is not there" and "we did
    not look" are different statements, and only one of them is honest here.
    """

    factor: str
    adapter: str
    reason: str


@dataclass(frozen=True)
class AdapterResult:
    """Everything one adapter module produced on one corridor."""

    name: str
    resolved: list[FactorValues] = field(default_factory=list)
    skipped: list[SkippedFactor] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def columns(self) -> list[str]:
        return [value.column for value in self.resolved]

    @property
    def factor_names(self) -> list[str]:
        return [value.factor for value in self.resolved]


def resolve(
    registry: Registry,
    factor_name: str,
    adapter_name: str,
    *,
    source: str,
    values: pd.Series,
    coverage: float = 1.0,
    unit_coverage: pd.Series | None = None,
    notes: Sequence[str] = (),
) -> FactorValues:
    """Build a :class:`FactorValues`, taking tier and licence from the registry.

    Raises:
        GeoError: The registry does not declare ``adapter_name`` for ``factor_name``.
            That is a code-versus-registry mismatch, not a data problem: either the
            adapter is filling a slot nobody declared, or the declaration was renamed
            and the implementation was not.
    """
    try:
        factor = registry.by_name(factor_name)
    except KeyError as exc:
        raise GeoError(
            f"adapter '{adapter_name}' produced values for '{factor_name}', which is "
            f"not a factor in registry v{registry.version}"
        ) from exc

    declared = next((a for a in factor.adapters if a.name == adapter_name), None)
    if declared is None:
        raise GeoError(
            f"registry v{registry.version} does not declare an adapter named "
            f"'{adapter_name}' for factor '{factor_name}'. Declared: "
            + ", ".join(a.name for a in factor.adapters)
            + ". Tier and licence come from the declaration, so an undeclared adapter "
            "has no provenance to attach and cannot contribute a value."
        )

    return FactorValues(
        factor=factor.name,
        column=factor.column,
        adapter=declared.name,
        tier=declared.tier,
        licence=declared.licence,
        source=source,
        values=values,
        coverage=coverage,
        unit_coverage=unit_coverage,
        notes=tuple(notes),
    )


def require_slots(registry: Registry, slots: Iterable[tuple[str, str]]) -> None:
    """Fail before doing any work if the registry does not declare these slots.

    :func:`resolve` already refuses an undeclared slot, but only for a factor that
    resolved. A factor that always skips — because the tag is never present — would
    otherwise carry a typo'd or renamed adapter name indefinitely and only announce it
    on the one corridor where the data finally appears.
    """
    for factor_name, adapter_name in slots:
        try:
            factor = registry.by_name(factor_name)
        except KeyError as exc:
            raise GeoError(
                f"adapter slot '{adapter_name}' targets factor '{factor_name}', which "
                f"registry v{registry.version} does not declare"
            ) from exc
        if not any(a.name == adapter_name for a in factor.adapters):
            raise GeoError(
                f"registry v{registry.version} does not declare an adapter named "
                f"'{adapter_name}' for factor '{factor_name}'. Declared: "
                + ", ".join(a.name for a in factor.adapters)
            )


def unit_frame(results: Iterable[AdapterResult]) -> pd.DataFrame | None:
    """Merge every resolved factor into one unit-keyed frame.

    Raises:
        GeoError: Two adapters resolved the same factor. Choosing between them is
            fusion — step 2.7 — and guessing here would hide the disagreement that
            step exists to measure.
    """
    frames: list[pd.DataFrame] = []
    seen: dict[str, str] = {}

    for result in results:
        for value in result.resolved:
            if value.column in seen:
                raise GeoError(
                    f"'{value.column}' was resolved by both '{seen[value.column]}' and "
                    f"'{value.adapter}'. Picking a winner and scoring their agreement "
                    "is step 2.7 (fusion); until it lands, run one adapter per factor."
                )
            seen[value.column] = value.adapter
            frames.append(value.as_frame())

    if not frames:
        return None

    merged = frames[0]
    for frame in frames[1:]:
        merged = merged.merge(frame, on=UNIT_COLUMN, how="outer", validate="one_to_one")
    return merged


def provenance_frame(results: Iterable[AdapterResult]) -> pd.DataFrame:
    """One row per resolved factor: value, source, tier and licence, as the brief asks.

    This is what the report renders and what a client auditing a number reads.
    """
    rows = [
        {
            "factor": value.factor,
            "column": value.column,
            "adapter": value.adapter,
            "tier": value.tier.value,
            "licence": value.licence.value,
            "coverage": round(value.coverage, 4),
            "source": " ".join(value.source.split()),
        }
        for result in results
        for value in result.resolved
    ]
    return pd.DataFrame(
        rows,
        columns=["factor", "column", "adapter", "tier", "licence", "coverage", "source"],
    )


def collect_notes(
    results: Iterable[AdapterResult],
    *,
    include_skipped: bool = True,
) -> list[str]:
    """Every adapter note, and optionally every skip reason, in one list.

    Deduplicated, in first-seen order. A note about the centreline being under-sampled
    belongs to both curvature columns and is true once; printing it twice teaches the
    reader to skim the warnings, which is the opposite of what they are for.

    ``include_skipped`` is False for callers that render the skipped factors on their
    own — a reason worth reading once is worth reading once.
    """
    notes: list[str] = []
    seen: set[str] = set()

    def add(note: str) -> None:
        if note not in seen:
            seen.add(note)
            notes.append(note)

    for result in results:
        for note in result.notes:
            add(note)
        for value in result.resolved:
            for note in value.notes:
                add(note)
        if include_skipped:
            for skip in result.skipped:
                add(f"{skip.factor}: not resolved by {skip.adapter} — {skip.reason}")

    return notes


__all__ = [
    "AdapterResult",
    "FactorValues",
    "SkippedFactor",
    "collect_notes",
    "provenance_frame",
    "require_slots",
    "resolve",
    "unit_frame",
]
