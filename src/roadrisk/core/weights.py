"""Choosing a weight for a run, and reporting where the sources disagree.

Two jobs, kept together because they are the same concern seen twice: given several
published weights for one factor, which one applies here, and what do the ones we did
not pick tell us about our confidence in the one we did?

**Selection never averages.** Where two sources disagree, one is chosen by declared
rules and the disagreement is reported. Averaging would hide exactly the signal worth
selling — *no competitor reports where their own inputs disagree*.

One note on the sign-conflict path in :func:`assess_agreement`. A registry cannot
actually reach it: every weight is validated against its factor's ``expected_sign`` at
load, so a published source contradicting the declared mechanism is refused before it
can be compared to anything. The check stays as defence in depth for programmatically
constructed selections, and because silently averaging a contradiction is the one
outcome this module exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from roadrisk.core.context import RunContext
from roadrisk.core.registry.schema import (
    FacilityType,
    Factor,
    Region,
    Severity,
    Weight,
    WeightFamily,
)

#: Tie-break order when context matching cannot separate two weights. iRAP first: it is
#: calibrated across 100+ countries and is cross-sectional by construction, which is
#: what Mode B does. HSM and Elvik are treatment-effect constructs being repurposed.
FAMILY_PREFERENCE: tuple[WeightFamily, ...] = (
    WeightFamily.IRAP,
    WeightFamily.HSM,
    WeightFamily.ELVIK,
)

#: An assumption is flagged when the run differs from it by more than this fraction.
ASSUMPTION_TOLERANCE = 0.25


@dataclass(frozen=True)
class Concern:
    """A reason to trust a selected weight less. Never a reason to hide it."""

    code: str
    message: str


@dataclass(frozen=True)
class WeightSelection:
    """The weight chosen for one factor, the ones rejected, and why."""

    factor: str
    selected: Weight
    alternatives: list[Weight] = field(default_factory=list)
    rejected: list[Weight] = field(default_factory=list)
    concerns: list[Concern] = field(default_factory=list)

    @property
    def has_concerns(self) -> bool:
        return bool(self.concerns)

    @property
    def reason(self) -> str:
        return (
            f"{self.selected.family.value} weight {self.selected.value:+.4f} "
            f"({self.selected.facility_type.value}/{self.selected.region.value}/"
            f"{self.selected.severity.value})"
        )


@dataclass(frozen=True)
class Agreement:
    """How well two or more independent sources agree on one factor."""

    factor: str
    score: float | None
    comparable: bool
    families: list[str]
    values: list[float]
    note: str

    @property
    def signs_conflict(self) -> bool:
        return self.score == 0.0 and self.comparable


def select_weight(factor: Factor, context: RunContext) -> WeightSelection | None:
    """Pick the weight that best matches this run, or None if none is admissible.

    Admissibility is strict on the two dimensions where using the wrong weight is a
    correctness error rather than a transfer error:

    * **Facility type** — a weight restricted to one facility is inadmissible on
      another. A weight declaring ``any`` is admissible everywhere.
    * **Severity** — a weight for fatal crashes must never score an injury panel. The
      Elvik exponent is 1.6 for injury and 4.1 for fatal; picking wrong is a
      factor-of-two error, not a nuance.

    **Region is deliberately not a filter.** Filtering on it would leave almost nothing
    admissible outside North America, which helps nobody. A regional mismatch is
    instead recorded as a concern and surfaced — that is the transfer problem stated
    out loud rather than either hidden or used as an excuse to refuse.
    """
    if not factor.weights:
        return None

    admissible = [w for w in factor.weights if _is_admissible(w, context)]
    rejected = [w for w in factor.weights if w not in admissible]
    if not admissible:
        return None

    ranked = sorted(admissible, key=lambda w: _rank(w, context))
    selected, *alternatives = ranked

    return WeightSelection(
        factor=factor.name,
        selected=selected,
        alternatives=alternatives,
        rejected=rejected,
        concerns=_concerns(selected, context),
    )


def assess_agreement(selection: WeightSelection) -> Agreement | None:
    """Compare the selected weight against the admissible alternatives.

    Returns None when there is only one weight — a single source cannot agree or
    disagree with anything, and reporting a score of 1.0 there would imply a
    corroboration that does not exist.
    """
    others = selection.alternatives
    if not others:
        return None

    selected = selection.selected
    values = [selected.value, *(w.value for w in others)]
    families = [selected.family.value, *(w.family.value for w in others)]

    scopes = {w.scope for w in (selected, *others)}
    if len(scopes) > 1:
        return Agreement(
            factor=selection.factor,
            score=None,
            comparable=False,
            families=families,
            values=values,
            note=(
                "Sources cover different crash types ("
                + ", ".join(sorted(s.value for s in scopes))
                + "), so their weights are not measuring the same quantity and an "
                "agreement score would be misleading. Reported separately instead."
            ),
        )

    signs = {1 if v > 0 else -1 for v in values if v != 0}
    if len(signs) > 1:
        return Agreement(
            factor=selection.factor,
            score=0.0,
            comparable=True,
            families=families,
            values=values,
            note=(
                "Published sources disagree on the DIRECTION of this factor. That is a "
                "finding, not a rounding difference — do not average them, and do not "
                "present this factor as settled."
            ),
        )

    magnitudes = [abs(v) for v in values]
    largest = max(magnitudes)
    score = min(magnitudes) / largest if largest > 0 else 1.0

    return Agreement(
        factor=selection.factor,
        score=score,
        comparable=True,
        families=families,
        values=values,
        note=(
            f"{len(values)} sources agree on direction; weakest/strongest magnitude "
            f"ratio {score:.2f}."
        ),
    )


# ---- internals ---------------------------------------------------------------


def _is_admissible(weight: Weight, context: RunContext) -> bool:
    facility_ok = (
        weight.facility_type is FacilityType.ANY
        or weight.facility_type is context.facility_type
    )
    severity_ok = (
        weight.severity is Severity.ALL or weight.severity is context.severity
    )
    return facility_ok and severity_ok


def _rank(weight: Weight, context: RunContext) -> tuple[int, int, int, int, str]:
    """Sort key, ascending. More specific context wins, then family preference."""
    facility_exact = weight.facility_type is context.facility_type
    region_exact = weight.region is context.region
    severity_exact = weight.severity is context.severity
    try:
        family_rank = FAMILY_PREFERENCE.index(weight.family)
    except ValueError:  # pragma: no cover - a family with no declared preference
        family_rank = len(FAMILY_PREFERENCE)
    return (
        0 if facility_exact else 1,
        0 if region_exact else 1,
        0 if severity_exact else 1,
        family_rank,
        weight.source,
    )


def _concerns(weight: Weight, context: RunContext) -> list[Concern]:
    concerns: list[Concern] = []

    if weight.caveat:
        concerns.append(Concern(code="weight_caveat", message=weight.caveat))

    if weight.region is not Region.GLOBAL and weight.region is not context.region:
        concerns.append(
            Concern(
                code="region_transfer",
                message=(
                    f"Weight was estimated in {weight.region.value} and this run is "
                    f"{context.region.value}. Vehicle fleet, enforcement, roadside "
                    "activity and crash reporting all differ. This is the largest "
                    "error source in Mode B and is tolerable only because the output "
                    "is an ordinal ranking, where a common scaling error leaves the "
                    "order intact."
                ),
            )
        )

    if (
        weight.facility_type is FacilityType.ANY
        and context.facility_type is not FacilityType.ANY
    ):
        concerns.append(
            Concern(
                code="facility_unrestricted",
                message=(
                    f"Weight is not restricted by facility type, and this run declares "
                    f"{context.facility_type.value}. No better-matched weight exists."
                ),
            )
        )

    if context.facility_type is FacilityType.ANY:
        concerns.append(
            Concern(
                code="facility_undeclared",
                message=(
                    "The corridor's facility type was not declared, so only "
                    "unrestricted weights were admissible. Declaring it may admit a "
                    "better-matched weight."
                ),
            )
        )

    concerns.extend(_assumption_concerns(weight, context))
    return concerns


def _assumption_concerns(weight: Weight, context: RunContext) -> list[Concern]:
    """Compare a weight's declared derivation conditions against the actual run."""
    actuals = context.actuals()
    concerns: list[Concern] = []

    for name, assumed in weight.assumes.items():
        actual = actuals.get(name)
        if actual is None or assumed == 0:
            continue
        deviation = abs(actual - assumed) / abs(assumed)
        if deviation <= ASSUMPTION_TOLERANCE:
            continue
        concerns.append(
            Concern(
                code=f"assumption_{name}",
                message=(
                    f"Weight was derived assuming {name} = {assumed:g}, but this run "
                    f"has {actual:g} ({deviation:.0%} different). Regenerate the "
                    "weight for this run's conditions with tools/derive_weights.py, or "
                    "treat this term as approximate."
                ),
            )
        )
    return concerns


__all__ = [
    "ASSUMPTION_TOLERANCE",
    "FAMILY_PREFERENCE",
    "Agreement",
    "Concern",
    "WeightSelection",
    "assess_agreement",
    "select_weight",
]
