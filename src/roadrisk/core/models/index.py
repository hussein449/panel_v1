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

**On crash types — the decomposition.** Published weights are crash-type specific. iRAP
prices grade for run-off and head-on crashes; it prices street lighting for intersection
crashes. Summing those into one number treats a run-off-only weight as though it moved
every crash on the road.

So the score is built per crash type and then combined:

.. code-block:: text

    log_score[type] = sum of  w_j * x_j   for weights scoped `type` or `total`
    combined        = sum of  share[type] * exp(log_score[type])
    row score       = ln(combined)

A weight scoped to one type moves only that type, and its share dilutes it correctly.
A ``total``-scope weight enters every type and survives at full strength — so a registry
of only total-scope weights produces *exactly* the score it did before the
decomposition existed. This is a strict correction, not a re-scaling, and the final
``ln`` keeps the result on the Mode A coefficient scale.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from roadrisk.core.context import RunContext
from roadrisk.core.crashmix import BUCKETS, CrashMix
from roadrisk.core.errors import WeightNotSourced
from roadrisk.core.registry import CrashScope, Factor
from roadrisk.core.weights import (
    Agreement,
    Concern,
    WeightSelection,
    assess_agreement,
    select_weight,
)

SPECIFICATION = "Weighted index (published weights, crash-type decomposed)"


@dataclass(frozen=True)
class IndexTerm:
    """One weighted term, the citation behind it, and how sure we are of it."""

    factor: str
    label: str
    weight: float
    weight_source: str
    family: str
    scope: CrashScope
    mean_contribution: float
    sd_contribution: float
    agreement: Agreement | None = None
    concerns: list[Concern] = field(default_factory=list)

    @property
    def has_concerns(self) -> bool:
        return bool(self.concerns)

    @property
    def applies_to_all_crash_types(self) -> bool:
        return self.scope is CrashScope.TOTAL


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
    crash_mix: CrashMix
    bucket_mean_scores: dict[CrashScope, float] = field(default_factory=dict)
    skipped_unsourced: list[str] = field(default_factory=list)
    skipped_inadmissible: list[str] = field(default_factory=list)

    @property
    def factor_names(self) -> list[str]:
        return [t.factor for t in self.terms]

    def terms_for(self, bucket: CrashScope) -> list[IndexTerm]:
        """Terms entering one crash-type bucket, including the total-scope ones."""
        return [
            t for t in self.terms if t.scope is bucket or t.scope is CrashScope.TOTAL
        ]

    @property
    def scoped_terms(self) -> list[IndexTerm]:
        """Terms that move only one crash type. These are what the split exists for."""
        return [t for t in self.terms if not t.applies_to_all_crash_types]

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
    contributions: dict[str, pd.Series] = {}

    for factor, selection in selections:
        weight = selection.selected
        contribution = design[factor.name].astype(float) * weight.value
        contributions[factor.name] = contribution
        terms.append(
            IndexTerm(
                factor=factor.name,
                label=factor.label,
                weight=weight.value,
                weight_source=weight.source,
                family=weight.family.value,
                scope=weight.scope,
                mean_contribution=float(contribution.mean()),
                sd_contribution=float(contribution.std(ddof=0)),
                agreement=assess_agreement(selection),
                concerns=list(selection.concerns),
            )
        )

    bucket_scores = _bucket_log_scores(terms, contributions, design.index)
    row_scores = _combine(bucket_scores, active_context.crash_mix)

    return IndexResult(
        specification=SPECIFICATION,
        terms=terms,
        row_scores=row_scores,
        unit_ranking=_rank_units(row_scores, bucket_scores, unit_ids),
        n_units=int(unit_ids.nunique()),
        n_observations=int(len(design)),
        context=active_context,
        crash_mix=active_context.crash_mix,
        bucket_mean_scores={
            bucket: float(series.mean()) for bucket, series in bucket_scores.items()
        },
        skipped_unsourced=unsourced,
        skipped_inadmissible=sorted(inadmissible),
    )


def _bucket_log_scores(
    terms: list[IndexTerm],
    contributions: dict[str, pd.Series],
    index: pd.Index,
) -> dict[CrashScope, pd.Series]:
    """Sum each term's contribution into every crash type it applies to.

    A ``total``-scope term enters all four buckets, which is what keeps a
    total-only registry scoring exactly as it did before the decomposition.
    """
    scores = {bucket: pd.Series(0.0, index=index) for bucket in BUCKETS}
    for term in terms:
        contribution = contributions[term.factor]
        targets = BUCKETS if term.applies_to_all_crash_types else (term.scope,)
        for bucket in targets:
            if bucket in scores:
                scores[bucket] = scores[bucket] + contribution
    return scores


def _combine(
    bucket_scores: dict[CrashScope, pd.Series],
    crash_mix: CrashMix,
) -> pd.Series:
    """Weight each crash type's score by its share, then return to the log scale.

    The final ``ln`` matters: it keeps the combined score on the same scale as a
    Mode A coefficient, so the prior/posterior correspondence survives the split.
    """
    combined = None
    for bucket, series in bucket_scores.items():
        weighted = crash_mix.share(bucket) * np.exp(series)
        combined = weighted if combined is None else combined + weighted

    assert combined is not None  # noqa: S101 - BUCKETS is never empty
    return np.log(combined)


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


def _rank_units(
    row_scores: pd.Series,
    bucket_scores: dict[CrashScope, pd.Series],
    unit_ids: pd.Series,
) -> pd.DataFrame:
    """Collapse row scores to one score per unit, ranked worst-first.

    Per-crash-type columns ride along, so a unit that ranks badly can be read for
    *why* — a run-off problem and an intersection problem call for different
    countermeasures, and a single combined number hides which one it is.
    """
    columns: dict[str, object] = {
        "unit_id": unit_ids.to_numpy(),
        "score": row_scores.to_numpy(),
    }
    for bucket, series in bucket_scores.items():
        columns[f"score_{bucket.value}"] = series.to_numpy()

    frame = pd.DataFrame(columns)
    per_unit = frame.groupby("unit_id", sort=False).mean().reset_index()
    per_unit = per_unit.sort_values("score", ascending=False, kind="mergesort")
    per_unit["rank"] = range(1, len(per_unit) + 1)
    per_unit["percentile"] = per_unit["score"].rank(pct=True)
    return per_unit.reset_index(drop=True)


__all__ = ["SPECIFICATION", "IndexResult", "IndexTerm", "score_index"]
