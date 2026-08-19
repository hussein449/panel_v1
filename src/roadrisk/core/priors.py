"""Step 3.3b — the registry's cited weights, turned into priors.

    select_weight  ->  scope dilution  ->  a width from agreement  ->  Normal(w, tau)

This is the idea the brief says unifies the whole architecture:

    A prior is what we believed before seeing data. **Mode B weights are priors.** Mode A
    is those priors updated by data.

Under it the two modes stop being separate products and become one continuum — Mode B is
the prior with no data to update it, A-minimal is the prior barely moved, A-full is the
data dominating. And a sign reversal stops being a silent bug and becomes a reportable
finding: *the data fought the prior and won*.

**Why this is cheap to do here and would not be anywhere else.**
:mod:`roadrisk.core.models.index` already keeps Mode B's weights on the Mode A
coefficient scale, and says so in as many words: standardising the index "would break
that correspondence and make the two modes incomparable". That decision was made long
before this module existed, and it is the only reason a published weight can be used as
a prior mean without any conversion at all.

**Soft priors, never constraints.** ``expected_sign`` must not truncate a coefficient to
its expected direction. Truncation would make ``P(beta has the wrong sign)`` identically
zero, which would delete the sign guard by construction — the engine would become
incapable of ever reporting the contradiction it exists to find. The prior carries the
direction as an *expectation*; the data is always allowed to overrule it, and how hard
it had to push is reported.

**The trap this step introduces, and the guard against it.** A thin panel today produces
wide intervals — visibly useless, which is honest. Add a confident prior and the same
panel produces a *narrow* interval that is purely the prior talking, and it looks like
evidence. That is a new way for this package to mislead, so
:class:`~roadrisk.core.models.bayes.PosteriorSummary` reports how much of each answer is
prior rather than data, and says plainly when the data added nothing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from roadrisk.core.context import RunContext
from roadrisk.core.registry.schema import CrashScope, Factor
from roadrisk.core.weights import Agreement, WeightSelection, assess_agreement, select_weight

#: Prior standard deviation for a cited weight that carries no concerns and that its
#: sources agree on.
#:
#: 0.35 is a statement, not a default: a 95% prior interval of roughly plus or minus
#: 0.69 around the published value, which on the log-rate scale means the literature
#: could be wrong by about a factor of two either way. That is the right amount of
#: deference to a number derived from somebody else's road network — enough that it
#: shapes a thin panel, nowhere near enough to survive a corridor that disagrees.
BASE_CITED_SD = 0.35

#: Full disagreement between sources doubles the width. Agreement leaves it alone.
#:
#: This uses the machinery the registry already has. Two families that agree on a factor
#: make a firmer prior than two that do not, and the engine already scores exactly that
#: when it picks the weight — so the confidence in a prior is derived rather than
#: declared, and a factor whose sources contradict each other cannot quietly produce a
#: prior as sharp as one they agree on.
DISAGREEMENT_WIDENING = 1.0

#: Each recorded concern multiplies the width by this.
#:
#: A concern is the weight selection saying "this number applies here less well than it
#: might" — a region it was not estimated in, an assumption the corridor breaks, a
#: standing caveat. `speed_limit` carries a permanent one, because the Elvik exponent
#: applies to operating speed and the column holds posted limit, and it is right that
#: this alone makes its prior looser without anybody remembering to do it.
CONCERN_WIDENING = 1.25

#: No prior is ever tighter than this, whatever the evidence behind it.
#:
#: A prior narrow enough that a corridor's own data cannot move it is not a prior, it is
#: an assumption wearing a posterior's clothes. This floor keeps every published weight
#: falsifiable by roughly 400 crashes' worth of evidence.
MIN_SD = 0.15

#: And never looser than the uninformative default, which is what an uncited factor
#: gets. Past this point the citation is adding nothing but a centre, and a weight this
#: heavily caveated should not be pretending to more.
DEFAULT_SD = 1.0

#: Prior on the intercept. Deliberately vague: nothing in the registry speaks to a
#: corridor's baseline rate, which depends on the country, the reporting regime and what
#: counts as a crash.
INTERCEPT_SD = 5.0


@dataclass(frozen=True)
class FactorPrior:
    """What we believed about one factor before seeing this corridor's crashes."""

    factor: str
    mean: float
    sd: float
    is_cited: bool
    source: str | None = None
    family: str | None = None
    scope: CrashScope = CrashScope.TOTAL
    #: The published number, before crash-scope dilution. Equal to ``mean`` for a
    #: total-scope weight.
    published_value: float | None = None
    #: The crash-type share a scoped weight was multiplied by. 1.0 for total scope.
    dilution: float = 1.0
    agreement: float | None = None
    concerns: tuple[str, ...] = ()
    rationale: str = ""

    @property
    def is_scoped(self) -> bool:
        return self.scope is not CrashScope.TOTAL

    def describe(self) -> str:
        if not self.is_cited:
            return (
                f"'{self.factor}' has no admissible cited weight for this run, so its "
                f"prior is uninformative — Normal(0, {self.sd:.2f}), centred on no "
                "effect. The data decides this one alone."
            )
        parts = [
            f"'{self.factor}' ~ Normal({self.mean:+.3f}, {self.sd:.2f}) from the "
            f"{self.family} weight {self.published_value:+.3f}."
        ]
        if self.is_scoped:
            parts.append(
                f"That weight covers {self.scope.value} crashes only, so it is diluted "
                f"by their {self.dilution:.1%} share of the crash mix before it can "
                "speak about total crashes."
            )
        if self.agreement is not None:
            parts.append(f"Sources agree at {self.agreement:.2f}.")
        if self.concerns:
            parts.append(
                f"{len(self.concerns)} concern(s) widened it: "
                + "; ".join(self.concerns)
            )
        return " ".join(parts)


@dataclass(frozen=True)
class PriorSet:
    """Priors for one run, and everything needed to defend them."""

    priors: list[FactorPrior] = field(default_factory=list)
    intercept_sd: float = INTERCEPT_SD
    notes: tuple[str, ...] = ()

    @property
    def cited(self) -> list[FactorPrior]:
        return [p for p in self.priors if p.is_cited]

    @property
    def uncited(self) -> list[FactorPrior]:
        return [p for p in self.priors if not p.is_cited]

    @property
    def is_informative(self) -> bool:
        """True when at least one factor's prior comes from a citation."""
        return bool(self.cited)

    def prior(self, factor: str) -> FactorPrior | None:
        return next((p for p in self.priors if p.factor == factor), None)

    def means(self, names: list[str]) -> list[float]:
        return [(p.mean if (p := self.prior(n)) else 0.0) for n in names]

    def sds(self, names: list[str]) -> list[float]:
        return [(p.sd if (p := self.prior(n)) else DEFAULT_SD) for n in names]

    def summary(self) -> str:
        if not self.is_informative:
            return (
                "No factor in this specification has an admissible cited weight, so "
                "every prior is uninformative and the posterior is the data's answer "
                "alone."
            )
        return (
            f"{len(self.cited)} of {len(self.priors)} factors carry a prior from a cited "
            "weight; the rest are uninformative. Mode B's published weights and Mode A's "
            "estimates are the same quantity here — the prior and the posterior of one "
            "model."
        )


def build_priors(
    factors: list[Factor],
    context: RunContext,
    *,
    base_sd: float = BASE_CITED_SD,
    default_sd: float = DEFAULT_SD,
) -> PriorSet:
    """Turn the registry's weights into priors for the factors actually being fitted.

    Args:
        factors: The fitted specification, in the order the design matrix uses.
        context: Facility type, region, severity and crash mix. Decides which weight is
            admissible and how a scoped weight is diluted.
        base_sd: Width for a cited weight with agreement and no concerns.
        default_sd: Width for a factor with no admissible weight, centred on zero.

    Returns:
        A :class:`PriorSet`, one entry per factor, in the order given.
    """
    priors: list[FactorPrior] = []
    notes: list[str] = []

    for factor in factors:
        selection = select_weight(factor, context)
        if selection is None:
            priors.append(
                FactorPrior(
                    factor=factor.name,
                    mean=0.0,
                    sd=default_sd,
                    is_cited=False,
                    rationale=(
                        "no weight in the registry is admissible for this facility "
                        "type, region and severity"
                    ),
                )
            )
            continue
        priors.append(_from_selection(selection, factor, context, base_sd, default_sd))

    scoped = [p for p in priors if p.is_cited and p.is_scoped]
    if scoped:
        notes.append(
            f"{len(scoped)} prior(s) come from crash-type-specific weights and were "
            "diluted by that type's share of the crash mix, because Mode A fits total "
            "crashes. The dilution is first order — it is the linear term of the same "
            "combination Mode B does exactly — and it understates a large effect "
            "slightly."
        )
    if context.uses_default_crash_mix and scoped:
        notes.append(
            "That dilution used the default crash mix, an HSM figure for rural "
            "two-lane Washington State. A local crash-type split would change how "
            "strongly those priors speak."
        )
    return PriorSet(priors=priors, notes=tuple(notes))


def _from_selection(
    selection: WeightSelection,
    factor: Factor,
    context: RunContext,
    base_sd: float,
    default_sd: float,
) -> FactorPrior:
    weight = selection.selected
    agreement = assess_agreement(selection)
    dilution = _dilution(weight.scope, context)
    concerns = tuple(c.message for c in selection.concerns)
    sd = _width(agreement, len(concerns), base_sd, default_sd)

    return FactorPrior(
        factor=factor.name,
        mean=weight.value * dilution,
        sd=sd,
        is_cited=True,
        source=weight.source,
        family=weight.family.value,
        scope=weight.scope,
        published_value=weight.value,
        dilution=dilution,
        agreement=agreement.score if agreement and agreement.comparable else None,
        concerns=concerns,
        rationale=_rationale(agreement, len(concerns), sd, base_sd),
    )


def _dilution(scope: CrashScope, context: RunContext) -> float:
    """How much of a crash-type-specific weight reaches the total-crash coefficient.

    Mode A fits total crashes. A weight covering run-off and head-on crashes only cannot
    move the total rate by its full value — it moves the part of it that those crashes
    make up. To first order that is the crash type's share, which is the linear term of
    the exact combination :mod:`roadrisk.core.models.index` performs.

    Index's own worked example: a weight contributing +0.8 to a bucket holding 64.3% of
    crashes contributes +0.55 to the combined score. The first-order figure here is
    0.8 x 0.643 = 0.51, close enough for a prior mean and conservative in the right
    direction — it makes the prior speak slightly *less* loudly than the exact
    combination would.
    """
    if scope is CrashScope.TOTAL:
        return 1.0
    return float(context.crash_mix.share(scope))


def _width(
    agreement: Agreement | None,
    n_concerns: int,
    base_sd: float,
    default_sd: float,
) -> float:
    """Derive the prior's confidence from what the registry already knows about it."""
    sd = base_sd
    if agreement is not None and agreement.comparable and agreement.score is not None:
        sd *= 1.0 + DISAGREEMENT_WIDENING * (1.0 - agreement.score)
    sd *= CONCERN_WIDENING**n_concerns
    return float(min(max(sd, MIN_SD), default_sd))


def _rationale(
    agreement: Agreement | None, n_concerns: int, sd: float, base_sd: float
) -> str:
    reasons = []
    if agreement is not None and agreement.comparable and agreement.score is not None:
        if agreement.score >= 0.9:
            reasons.append(f"sources agree ({agreement.score:.2f})")
        else:
            reasons.append(f"sources disagree ({agreement.score:.2f}), widening it")
    if n_concerns:
        reasons.append(f"{n_concerns} concern(s) widening it")
    if math.isclose(sd, MIN_SD):
        reasons.append("held at the floor, so the corridor can always overrule it")
    if math.isclose(sd, base_sd) and not reasons:
        reasons.append("nothing on record to weaken it")
    return "; ".join(reasons)


__all__ = [
    "BASE_CITED_SD",
    "CONCERN_WIDENING",
    "DEFAULT_SD",
    "DISAGREEMENT_WIDENING",
    "INTERCEPT_SD",
    "MIN_SD",
    "FactorPrior",
    "PriorSet",
    "build_priors",
]
