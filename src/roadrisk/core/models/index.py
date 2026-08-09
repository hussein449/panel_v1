"""Mode B — weighted index from published weights.

Mode B produces a **ranked score and nothing else**. There is no predicted count, no
confidence interval and no p-value anywhere in this module, and that is structural:
the result type has no field to put one in. Mode B output can never be dressed in
Mode A's language because the type system will not allow it.

**On the scale of the weights.** The score is ``sum(w_j * x_j)`` over the *transformed*
columns, with no additional standardisation. That puts ``default_weight`` on exactly the
same scale as a Mode A coefficient, which is the point: a weight is a prior, and Mode A
is that prior updated by data. Standardising here would break the correspondence and
make the two modes incomparable.

**On what is being ranked.** The score is a rate-like quantity — risk per unit of
exposure. It deliberately does not multiply by exposure, so a long busy segment does not
outrank a short lethal one. Ranking total burden instead is a different question and
needs a different column.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from roadrisk.core.errors import WeightNotSourced
from roadrisk.core.registry import Factor

SPECIFICATION = "Weighted index (published weights)"


@dataclass(frozen=True)
class IndexTerm:
    """One weighted term and the citation that justifies it."""

    factor: str
    label: str
    weight: float
    weight_source: str
    mean_contribution: float
    sd_contribution: float


@dataclass(frozen=True)
class IndexResult:
    """A Mode B assessment. Ranking only."""

    specification: str
    terms: list[IndexTerm]
    row_scores: pd.Series
    unit_ranking: pd.DataFrame
    n_units: int
    n_observations: int
    skipped_unsourced: list[str] = field(default_factory=list)

    @property
    def factor_names(self) -> list[str]:
        return [t.factor for t in self.terms]


def score_index(
    design: pd.DataFrame,
    factors: list[Factor],
    unit_ids: pd.Series,
) -> IndexResult:
    """Score every panel row, then rank units by mean score.

    Args:
        design: Transformed design matrix, columns named by factor.
        factors: The factors present in ``design``. Every one must carry a sourced weight.
        unit_ids: The ``unit_id`` column, aligned to ``design``.

    Raises:
        WeightNotSourced: Any supplied factor lacks a weight or a citation for it.
    """
    unsourced = [f.name for f in factors if not f.is_sourced]
    if unsourced:
        raise WeightNotSourced(
            "Mode B cannot score — the following factor(s) have no cited weight: "
            + ", ".join(sorted(unsourced))
            + ". Set both `default_weight` and `weight_source` in the registry. A "
            "weight the client cannot trace to a named reference must not appear in "
            "an assessment."
        )

    usable = [f for f in factors if f.name in design.columns]
    if not usable:
        raise WeightNotSourced(
            "Mode B cannot score — none of the supplied factors are present in the "
            "design matrix. Mode B needs at least one factor column."
        )

    terms: list[IndexTerm] = []
    row_scores = pd.Series(0.0, index=design.index)

    for factor in usable:
        weight = float(factor.default_weight)  # type: ignore[arg-type]
        contribution = design[factor.name].astype(float) * weight
        row_scores = row_scores + contribution
        terms.append(
            IndexTerm(
                factor=factor.name,
                label=factor.label,
                weight=weight,
                weight_source=str(factor.weight_source),
                mean_contribution=float(contribution.mean()),
                sd_contribution=float(contribution.std(ddof=0)),
            )
        )

    ranking = _rank_units(row_scores, unit_ids)

    return IndexResult(
        specification=SPECIFICATION,
        terms=terms,
        row_scores=row_scores,
        unit_ranking=ranking,
        n_units=int(len(ranking)),
        n_observations=int(len(design)),
    )


def _rank_units(row_scores: pd.Series, unit_ids: pd.Series) -> pd.DataFrame:
    """Collapse row scores to one score per unit, ranked worst-first."""
    frame = pd.DataFrame({"unit_id": unit_ids.to_numpy(), "score": row_scores.to_numpy()})
    per_unit = frame.groupby("unit_id", sort=False)["score"].mean().reset_index()
    per_unit = per_unit.sort_values("score", ascending=False, kind="mergesort")
    per_unit["rank"] = range(1, len(per_unit) + 1)
    per_unit["percentile"] = per_unit["score"].rank(pct=True)
    return per_unit.reset_index(drop=True)


__all__ = ["SPECIFICATION", "IndexResult", "IndexTerm", "score_index"]
