"""Mode B — weighted index from published weights.

Mode B produces a **ranked score and nothing else**. There is no predicted count, no
confidence interval and no p-value anywhere in this module, and that is structural:
the result type has no field to put one in. Mode B output can never be dressed in
Mode A's language because the type system will not allow it.

**On the scale of the weights.** The score is ``sum(w_j * x_j)`` over the *transformed*
columns, with no additional standardisation. That puts a published weight on exactly the
same scale as a Mode A coefficient, which is the point: a weight is a prior, and Mode A
is that prior updated by data. Standardising here would break the correspondence and
make the two modes incomparable.

**On what is being ranked.** The score is a rate-like quantity — risk per unit of
exposure. It deliberately does not multiply by exposure, so a long busy segment does not
outrank a short lethal one. Ranking total burden instead is a different question and
needs a different column.

**On partial coverage.** A factor with no cited weight does not participate, and it does
not silently become a weight of zero either. It is dropped and named in
``skipped_unsourced``, which the report prints — degrade loudly, never silently skip.
Mode B refuses outright only when *no* available factor yields an admissible weight.

**On which weight.** A factor may carry several published weights from different
sources, each valid in a different context. Selection is by declared rule
(:mod:`roadrisk.core.weights`), never by averaging, and every term carries the reason it
was chosen, the concerns attached to it, and how far the sources it beat disagreed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from roadrisk.core.context import RunContext
from roadrisk.core.errors import WeightNotSourced
from roadrisk.core.registry import Factor
from roadrisk.core.weights import (
    Agreement,
    Concern,
    WeightSelection,
    assess_agreement,
    select_weight,
)

SPECIFICATION = "Weighted index (published weights)"


@dataclass(frozen=True)
class IndexTerm:
    """One weighted term, the citation behind it, and how sure we are of it."""

    factor: str
    label: str
    weight: float
    weight_source: str
    family: str
    mean_contribution: float
    sd_contribution: float
    agreement: Agreement | None = None
    concerns: list[Concern] = field(default_factory=list)

    @property
    def has_concerns(self) -> bool:
        return bool(self.concerns)


@dataclass(frozen=True)
class IndexResult:
    """A Mode B assessment. Ranking only."""

    specification: str
    terms: list[IndexTerm]
    row_scores: pd.Series
    unit_ranking: pd.DataFrame
    n_units: int
    n_observations: int
    context: RunContext
    skipped_unsourced: list[str] = field(default_factory=list)
    skipped_inadmissible: list[str] = field(default_factory=list)

    @property
    def factor_names(self) -> list[str]:
        return [t.factor for t in self.terms]

    @property
    def disagreements(self) -> list[IndexTerm]:
        """Terms where independent sources point opposite ways."""
        return [
            t for t in self.terms if t.agreement and t.agreement.signs_conflict
        ]

    @property
    def concerns(self) -> list[IndexTerm]:
        return [t for t in self.terms if t.has_concerns]


def score_index(
    design: pd.DataFrame,
    factors: list[Factor],
    unit_ids: pd.Series,
    context: RunContext | None = None,
) -> IndexResult:
    """Score every panel row, then rank units by mean score.

    Args:
        design: Transformed design matrix, columns named by factor.
        factors: The factors available in this panel.
        unit_ids: The ``unit_id`` column, aligned to ``design``.
        context: Corridor and crash-data context, used to pick between published
            weights. Defaults to an undeclared context, which admits only
            unrestricted weights.

    Raises:
        WeightNotSourced: No available factor yields an admissible weight, so there is
            nothing legitimate to rank with.
    """
    active_context = context if context is not None else RunContext()

    unsourced = sorted(f.name for f in factors if not f.is_sourced)
    inadmissible: list[str] = []
    selections: list[tuple[Factor, WeightSelection]] = []

    for factor in factors:
        if not factor.is_sourced or factor.name not in design.columns:
            continue
        selection = select_weight(factor, active_context)
        if selection is None:
            inadmissible.append(factor.name)
            continue
        selections.append((factor, selection))

    if not selections:
        raise WeightNotSourced(_refusal_message(unsourced, inadmissible, active_context))

    terms: list[IndexTerm] = []
    row_scores = pd.Series(0.0, index=design.index)

    for factor, selection in selections:
        weight = selection.selected
        contribution = design[factor.name].astype(float) * weight.value
        row_scores = row_scores + contribution
        terms.append(
            IndexTerm(
                factor=factor.name,
                label=factor.label,
                weight=weight.value,
                weight_source=weight.source,
                family=weight.family.value,
                mean_contribution=float(contribution.mean()),
                sd_contribution=float(contribution.std(ddof=0)),
                agreement=assess_agreement(selection),
                concerns=list(selection.concerns),
            )
        )

    return IndexResult(
        specification=SPECIFICATION,
        terms=terms,
        row_scores=row_scores,
        unit_ranking=_rank_units(row_scores, unit_ids),
        n_units=int(unit_ids.nunique()),
        n_observations=int(len(design)),
        context=active_context,
        skipped_unsourced=unsourced,
        skipped_inadmissible=sorted(inadmissible),
    )


def _refusal_message(
    unsourced: list[str],
    inadmissible: list[str],
    context: RunContext,
) -> str:
    parts = [
        "Mode B cannot score — no available factor yields a usable weight for this "
        f"run ({context.describe()})."
    ]
    if unsourced:
        parts.append("No cited weight at all: " + ", ".join(unsourced) + ".")
    if inadmissible:
        parts.append(
            "Cited, but no weight admissible in this context: "
            + ", ".join(inadmissible)
            + ". A weight restricted to another facility type, or to a different crash "
            "severity, is not transferable and the engine will not stretch it."
        )
    parts.append(
        "A weight the client cannot trace to a named reference, valid for the road "
        "being assessed, must not appear in an assessment."
    )
    return " ".join(parts)


def _rank_units(row_scores: pd.Series, unit_ids: pd.Series) -> pd.DataFrame:
    """Collapse row scores to one score per unit, ranked worst-first."""
    frame = pd.DataFrame({"unit_id": unit_ids.to_numpy(), "score": row_scores.to_numpy()})
    per_unit = frame.groupby("unit_id", sort=False)["score"].mean().reset_index()
    per_unit = per_unit.sort_values("score", ascending=False, kind="mergesort")
    per_unit["rank"] = range(1, len(per_unit) + 1)
    per_unit["percentile"] = per_unit["score"].rank(pct=True)
    return per_unit.reset_index(drop=True)


__all__ = ["SPECIFICATION", "IndexResult", "IndexTerm", "score_index"]
