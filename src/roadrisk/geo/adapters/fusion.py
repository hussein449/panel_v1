"""Step 2.7 — one value per factor per unit, and how much to trust it.

Step 5 of the pipeline brief, in three sentences: *resolve one value per factor per
unit, highest-priority adapter wins; where two sources cover the same factor, compute
agreement; emit a confidence tier per factor per unit.*

**Priority is the registry's, not the code's.** ``factor.adapters`` is an ordered chain —
``client_data -> Tier A/B -> drop`` — and the winner is simply the earliest declared
adapter that produced a value. Client-supplied data wins because it is declared first,
not because it is special-cased anywhere. Reordering the chain in YAML reorders the
outcome, which is the whole point of the registry.

**The loser is kept, not discarded.** A rejected source is what makes agreement
measurable, and a rejected source that *disagrees* is the most useful thing in the run.

**Agreement is asymmetric evidence, and the confidence tier treats it that way.** Two
sources agreeing is weak evidence: OSM tags, Overture places and a client inventory can
all descend from the same survey, so agreement may be an echo rather than a
corroboration. Two sources disagreeing is strong evidence: at least one of them is
definitely wrong about that unit. So disagreement pulls a unit's confidence down, and
agreement is reported separately rather than pushing it up.

**Only measured units are compared.** A value carried across a tagging gap is an
imputation; comparing it against another source measures the imputation, not the
sources. Carried units are excluded from the agreement set and reported as low
confidence in their own right.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
import pandas as pd

from roadrisk.core.contract import UNIT_COLUMN
from roadrisk.core.registry import Registry, Tier
from roadrisk.geo.adapters.base import AdapterResult, FactorValues
from roadrisk.geo.errors import GeoError

#: Relative difference above which two sources are taken to disagree about a unit.
#: A quarter is loose enough to survive rounding and a 30 m pixel landing differently,
#: tight enough that 80 km/h versus 50 km/h is a disagreement rather than a nuance.
DISAGREEMENT_TOLERANCE = 0.25

#: Floor on the denominator of that relative difference, as a share of the factor's own
#: spread across the corridor. Without it, 0.0 versus 0.1 accesses per km reads as total
#: disagreement because the denominator collapses toward zero.
SPREAD_FLOOR = 0.1

#: A unit whose value rests on less than half its own length is measured, but weakly.
#: This is the confidence boundary and is deliberately separate from any single
#: adapter's threshold for adding a warning note.
THIN_COVERAGE = 0.5

REASON_MEASURED = "measured"
REASON_INFERRED = "inferred"
REASON_THIN = "thin_coverage"
REASON_CARRIED = "carried"
REASON_CONTRADICTED = "contradicted"

REASON_LEGEND: dict[str, str] = {
    REASON_MEASURED: "measured for this unit by the winning source",
    REASON_INFERRED: "derived by us rather than stated by anyone (Tier B)",
    REASON_THIN: f"rests on under {THIN_COVERAGE:.0%} of the unit's length",
    REASON_CARRIED: "carried from a neighbouring unit, not measured here",
    REASON_CONTRADICTED: "a second source materially disagrees about this unit",
}


class Confidence(StrEnum):
    """How much a single factor value for a single unit is worth."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


_CONFIDENCE_FOR = {
    REASON_MEASURED: Confidence.HIGH,
    REASON_INFERRED: Confidence.MEDIUM,
    REASON_THIN: Confidence.MEDIUM,
    REASON_CARRIED: Confidence.LOW,
    REASON_CONTRADICTED: Confidence.LOW,
}

#: Worst first. The first reason that applies to a unit is the one reported, so a unit
#: that is both carried and contradicted is reported as carried — the imputation is the
#: thing to fix, and the disagreement is a consequence of it.
_REASON_ORDER = (
    REASON_CARRIED,
    REASON_CONTRADICTED,
    REASON_THIN,
    REASON_INFERRED,
    REASON_MEASURED,
)


@dataclass(frozen=True)
class SourceAgreement:
    """How far two adapters agree about one factor, unit by unit."""

    factor: str
    column: str
    chosen: str
    challenger: str
    n_compared: int
    n_agreeing: int
    score: float | None
    mean_absolute_difference: float
    max_absolute_difference: float
    correlation: float | None
    disagreeing_units: tuple[str, ...]
    note: str

    @property
    def disagrees(self) -> bool:
        return bool(self.disagreeing_units)


@dataclass(frozen=True)
class FusedFactor:
    """One factor after fusion: the value that won, what it beat, and how sure we are."""

    factor: str
    column: str
    chosen: FactorValues
    rejected: tuple[FactorValues, ...] = ()
    agreements: tuple[SourceAgreement, ...] = ()
    confidence: pd.Series = field(default_factory=pd.Series)
    reason: pd.Series = field(default_factory=pd.Series)

    @property
    def values(self) -> pd.Series:
        return self.chosen.values

    @property
    def contested(self) -> bool:
        return bool(self.rejected)

    def share(self, level: Confidence) -> float:
        if self.confidence.empty:
            return 0.0
        return float((self.confidence == level).mean())


@dataclass(frozen=True)
class FusionResult:
    """Every factor resolved to one source, with provenance and confidence."""

    factors: list[FusedFactor] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def columns(self) -> list[str]:
        return [fused.column for fused in self.factors]

    @property
    def contested(self) -> list[FusedFactor]:
        return [fused for fused in self.factors if fused.contested]

    @property
    def disagreements(self) -> list[SourceAgreement]:
        return [
            agreement
            for fused in self.factors
            for agreement in fused.agreements
            if agreement.disagrees
        ]

    def values_frame(self) -> pd.DataFrame | None:
        """Unit id and one column per factor, ready for ``attach_factor_values``."""
        if not self.factors:
            return None
        merged = self.factors[0].chosen.as_frame()
        for fused in self.factors[1:]:
            merged = merged.merge(
                fused.chosen.as_frame(), on=UNIT_COLUMN, how="outer", validate="one_to_one"
            )
        return merged

    def confidence_frame(self) -> pd.DataFrame:
        """Long form: one row per factor per unit. The brief's deliverable for 2.7."""
        rows = [
            {
                UNIT_COLUMN: unit_id,
                "factor": fused.factor,
                "column": fused.column,
                "adapter": fused.chosen.adapter,
                "tier": fused.chosen.tier.value,
                "confidence": fused.confidence.loc[unit_id].value,
                "reason": fused.reason.loc[unit_id],
                "value": float(fused.values.loc[unit_id]),
            }
            for fused in self.factors
            for unit_id in fused.values.index
        ]
        return pd.DataFrame(
            rows,
            columns=[
                UNIT_COLUMN,
                "factor",
                "column",
                "adapter",
                "tier",
                "confidence",
                "reason",
                "value",
            ],
        )


def fuse(results: Iterable[AdapterResult], registry: Registry) -> FusionResult:
    """Resolve every factor to one source and score the ones that were contested.

    Args:
        results: Everything the adapters produced. Two results may resolve the same
            factor; that is the case this function exists for.
        registry: Declares the adapter chain whose order decides the winner.

    Raises:
        GeoError: The same adapter resolved one factor twice, which is a bug in the
            adapter rather than a disagreement between sources.
    """
    grouped: dict[str, list[FactorValues]] = {}
    for result in results:
        for value in result.resolved:
            grouped.setdefault(value.factor, []).append(value)

    fused: list[FusedFactor] = []
    notes: list[str] = []

    for factor_name, candidates in grouped.items():
        ordered = _by_priority(factor_name, candidates, registry)
        chosen, *rejected = ordered

        agreements = tuple(
            _agree(chosen, other) for other in rejected if _comparable(chosen, other)
        )
        confidence, reason = _score_confidence(chosen, agreements)

        fused.append(
            FusedFactor(
                factor=factor_name,
                column=chosen.column,
                chosen=chosen,
                rejected=tuple(rejected),
                agreements=agreements,
                confidence=confidence,
                reason=reason,
            )
        )

        if rejected:
            notes.append(
                f"{factor_name}: {len(ordered)} sources resolved it. "
                f"'{chosen.adapter}' wins on registry priority over "
                + ", ".join(f"'{other.adapter}'" for other in rejected)
                + "."
            )
        for agreement in agreements:
            notes.append(agreement.note)

    # Most important factor first, by the registry's own drop_priority — the same
    # order `roadrisk registry` prints and the order the ladder retains terms in. A
    # provenance table is read top-down, so it should not be alphabetical by accident.
    priority = {factor.name: factor.drop_priority for factor in registry.factors}
    fused.sort(key=lambda item: priority[item.factor], reverse=True)
    return FusionResult(factors=fused, notes=notes)


def provenance_frame(fusion: FusionResult) -> pd.DataFrame:
    """One row per factor: value, source, tier, licence — and now confidence too."""
    rows = [
        {
            "factor": fused.factor,
            "column": fused.column,
            "adapter": fused.chosen.adapter,
            "tier": fused.chosen.tier.value,
            "licence": fused.chosen.licence.value,
            "coverage": round(fused.chosen.coverage, 4),
            "confidence_high": round(fused.share(Confidence.HIGH), 4),
            "confidence_low": round(fused.share(Confidence.LOW), 4),
            "contested_by": ", ".join(other.adapter for other in fused.rejected),
            "agreement": (
                round(fused.agreements[0].score, 4)
                if fused.agreements and fused.agreements[0].score is not None
                else None
            ),
            "source": " ".join(fused.chosen.source.split()),
        }
        for fused in fusion.factors
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "factor",
            "column",
            "adapter",
            "tier",
            "licence",
            "coverage",
            "confidence_high",
            "confidence_low",
            "contested_by",
            "agreement",
            "source",
        ],
    )


# ---- internals ---------------------------------------------------------------


def _by_priority(
    factor_name: str,
    candidates: Sequence[FactorValues],
    registry: Registry,
) -> list[FactorValues]:
    """Order candidates by where their adapter sits in the registry's chain."""
    try:
        factor = registry.by_name(factor_name)
    except KeyError as exc:  # pragma: no cover - resolve() already checked this
        raise GeoError(
            f"'{factor_name}' was resolved by an adapter but is not in registry "
            f"v{registry.version}"
        ) from exc

    order = {adapter.name: index for index, adapter in enumerate(factor.adapters)}

    seen: set[str] = set()
    for candidate in candidates:
        if candidate.adapter in seen:
            raise GeoError(
                f"adapter '{candidate.adapter}' resolved '{factor_name}' twice. Two "
                "results from one adapter is a bug in that adapter, not a disagreement "
                "between sources — fusion has no basis for choosing between them."
            )
        seen.add(candidate.adapter)

    return sorted(candidates, key=lambda value: order[value.adapter])


def _measured(value: FactorValues) -> pd.Series:
    """Per-unit coverage, defaulting to fully measured when an adapter states none.

    A density or a curvature has no notion of partial coverage — every unit is counted
    over its whole length — so those adapters leave it unset rather than filling in a
    column of ones.
    """
    if value.unit_coverage is None:
        return pd.Series(1.0, index=value.values.index, dtype=float)
    return value.unit_coverage.reindex(value.values.index).fillna(0.0)


def _comparable(chosen: FactorValues, other: FactorValues) -> bool:
    """Two sources can only be compared where they cover the same units."""
    return bool(len(chosen.values.index.intersection(other.values.index)))


def _agree(chosen: FactorValues, other: FactorValues) -> SourceAgreement:
    """Compare two sources on the units where both actually measured something."""
    shared = chosen.values.index.intersection(other.values.index)
    both_measured = shared[
        (_measured(chosen).loc[shared] > 0.0) & (_measured(other).loc[shared] > 0.0)
    ]

    if not len(both_measured):
        return SourceAgreement(
            factor=chosen.factor,
            column=chosen.column,
            chosen=chosen.adapter,
            challenger=other.adapter,
            n_compared=0,
            n_agreeing=0,
            score=None,
            mean_absolute_difference=0.0,
            max_absolute_difference=0.0,
            correlation=None,
            disagreeing_units=(),
            note=(
                f"{chosen.factor}: '{chosen.adapter}' and '{other.adapter}' never both "
                "measured the same unit, so no agreement could be scored. This is not "
                "corroboration."
            ),
        )

    left = chosen.values.loc[both_measured].astype(float)
    right = other.values.loc[both_measured].astype(float)

    difference = (left - right).abs()
    combined = pd.concat([left, right])
    spread = float(combined.max() - combined.min())
    floor = SPREAD_FLOOR * spread
    denominator = np.maximum(np.maximum(left.abs(), right.abs()), max(floor, 1e-9))
    relative = difference / denominator

    disagreeing = both_measured[relative > DISAGREEMENT_TOLERANCE]
    n_agreeing = int(len(both_measured) - len(disagreeing))
    score = n_agreeing / len(both_measured)

    correlation: float | None = None
    if left.std() > 0 and right.std() > 0:
        correlation = float(left.corr(right))

    return SourceAgreement(
        factor=chosen.factor,
        column=chosen.column,
        chosen=chosen.adapter,
        challenger=other.adapter,
        n_compared=int(len(both_measured)),
        n_agreeing=n_agreeing,
        score=score,
        mean_absolute_difference=float(difference.mean()),
        max_absolute_difference=float(difference.max()),
        correlation=correlation,
        disagreeing_units=tuple(str(unit) for unit in disagreeing[:10]),
        note=_agreement_note(
            chosen, other, len(both_measured), n_agreeing, score, difference, correlation
        ),
    )


def _agreement_note(
    chosen: FactorValues,
    other: FactorValues,
    n_compared: int,
    n_agreeing: int,
    score: float,
    difference: pd.Series,
    correlation: float | None,
) -> str:
    head = (
        f"{chosen.factor}: '{chosen.adapter}' and '{other.adapter}' both measured "
        f"{n_compared} unit(s) and agree on {n_agreeing} ({score:.0%}), mean absolute "
        f"difference {difference.mean():.3g}"
    )
    if correlation is not None:
        head += f", correlation {correlation:+.2f}"

    if score == 1.0:
        return (
            head
            + ". Treat this as consistency, not corroboration — open sources copy from "
            "each other often enough that agreement can be an echo."
        )
    return (
        head
        + f". The {n_compared - n_agreeing} unit(s) that differ by more than "
        f"{DISAGREEMENT_TOLERANCE:.0%} are marked low confidence: one of the two "
        "sources is wrong about them and this cannot say which."
    )


def _score_confidence(
    chosen: FactorValues,
    agreements: Sequence[SourceAgreement],
) -> tuple[pd.Series, pd.Series]:
    """A confidence tier and a one-word reason for every unit."""
    index = chosen.values.index
    coverage = _measured(chosen)

    contradicted = {
        unit for agreement in agreements for unit in agreement.disagreeing_units
    }
    inferred = chosen.tier is Tier.B

    reasons: list[str] = []
    for unit_id in index:
        applies = {
            REASON_CARRIED: coverage.loc[unit_id] <= 0.0,
            REASON_CONTRADICTED: str(unit_id) in contradicted,
            REASON_THIN: coverage.loc[unit_id] < THIN_COVERAGE,
            REASON_INFERRED: inferred,
            REASON_MEASURED: True,
        }
        reasons.append(next(code for code in _REASON_ORDER if applies[code]))

    reason = pd.Series(reasons, index=index, dtype=object)
    confidence = reason.map(_CONFIDENCE_FOR)
    return confidence, reason


__all__ = [
    "DISAGREEMENT_TOLERANCE",
    "REASON_CARRIED",
    "REASON_CONTRADICTED",
    "REASON_INFERRED",
    "REASON_LEGEND",
    "REASON_MEASURED",
    "REASON_THIN",
    "SPREAD_FLOOR",
    "THIN_COVERAGE",
    "Confidence",
    "FusedFactor",
    "FusionResult",
    "SourceAgreement",
    "fuse",
    "provenance_frame",
]
