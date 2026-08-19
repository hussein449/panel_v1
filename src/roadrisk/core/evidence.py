"""Three answers per factor, and which one this run designates.

    textbook        what the literature says, before seeing this road
    your data       what this road says, having been told nothing
    the mix         both, weighted by how sure each one is

Every factor gets all three, and the engine designates one as *the* answer. Showing
three numbers without designating one would be an abdication: a reader who has to choose
will choose the one that suits them, and the whole point of this package is that the
engine decides what the data can support rather than the person holding it.

**The share is the auditing device.** For each factor the report carries the proportion
of the answer that came from the prior rather than from this corridor — a percentage,
readable without any statistics. It falls straight out of the arithmetic: two opinions
pull on the answer with force proportional to their certainty, so the prior's share is
its precision over the total.

    share = (1 / prior_sd^2) / (1 / prior_sd^2 + 1 / data_sd^2)

A factor at 3% is this road talking. A factor at 78% is a textbook with a corridor's
name on it, and it is labelled as such.

**Why the comparison is between two fits of the same model.** "Your data" is not the NB2
fit — it is this same Bayesian model with uninformative priors. Comparing against NB2
would confound two changes at once, the estimator and the prior, and leave nobody able to
say which produced the difference. It costs a second fit and buys an answer that means
something.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from roadrisk.core.models.bayes import PosteriorFit, PosteriorSummary
from roadrisk.core.priors import FactorPrior, PriorSet

#: Prior share above which the answer is mostly literature. Past this the number is a
#: statement about published evidence, not about the road, and must not be quoted as a
#: measurement of it — nor, when prediction lands in stage 4, turned into a crash count.
#: Mode B refuses to produce a count from published weights alone; a prior-dominated
#: coefficient is the same thing arriving by a different route, and gets the same rule.
PRIOR_DOMINATES = 0.70

#: Below this the prior is doing so little that the simpler answer — the one with a
#: single parent — is the one worth designating.
DATA_DOMINATES = 0.25

#: Movement, in standard errors, above which an uncited factor is reported as having
#: been shifted by some *other* factor's prior. A quarter of a standard error is well
#: inside the noise for one estimate and well outside "untouched".
INDIRECT_SHIFT = 0.25


class Answer(StrEnum):
    """Which of the three columns this run designates as the assessment."""

    TEXTBOOK = "textbook"
    DATA = "your data"
    MIX = "the mix"


@dataclass(frozen=True)
class FactorEvidence:
    """One factor, seen three ways."""

    factor: str
    textbook: float | None = None
    textbook_sd: float | None = None
    textbook_source: str | None = None
    data_mean: float | None = None
    data_low: float | None = None
    data_high: float | None = None
    data_sd: float | None = None
    mix_mean: float | None = None
    mix_low: float | None = None
    mix_high: float | None = None
    mix_sd: float | None = None
    prior_share: float | None = None

    @property
    def is_cited(self) -> bool:
        return self.textbook is not None

    @property
    def prior_dominates(self) -> bool:
        return self.prior_share is not None and self.prior_share >= PRIOR_DOMINATES

    @property
    def data_is_silent(self) -> bool:
        """The corridor's own interval spans zero so widely it settles nothing."""
        return (
            self.data_low is not None
            and self.data_high is not None
            and self.data_low < 0.0 < self.data_high
        )

    @property
    def moved_by_others(self) -> float | None:
        """How far this factor moved between the two fits, in its own standard errors.

        It exists because a factor with no cited weight of its own is **not** insulated
        from the priors. Coefficients are correlated — junction density with access
        density, curvature with gradient — so tightening one of them drags its
        neighbours with it. On the first run of this comparison an uncited factor moved
        by two thirds of a standard error because `speed_limit` had been given a prior,
        while the report cheerfully described it as "this road's data alone".

        There is no way to report a mixed fit honestly without this number.
        """
        if self.data_mean is None or self.mix_mean is None or not self.data_sd:
            return None
        return abs(self.mix_mean - self.data_mean) / self.data_sd

    @property
    def indirectly_shifted(self) -> bool:
        """Uncited, yet moved by somebody else's prior."""
        moved = self.moved_by_others
        return not self.is_cited and moved is not None and moved >= INDIRECT_SHIFT

    @property
    def contradicts_textbook(self) -> bool:
        """This road disagrees with the literature, with evidence behind it.

        Judged on the **data-only** fit, never the mix. A prior centred on the textbook
        pulls the mix toward the textbook, so asking the mix whether it disagrees with
        the textbook is asking a question the prior has already influenced.
        """
        if not self.is_cited or self.data_low is None or self.data_high is None:
            return False
        textbook = self.textbook or 0.0
        outside = textbook < self.data_low or textbook > self.data_high
        opposed = (self.data_mean or 0.0) * textbook < 0.0
        return outside and opposed

    def label(self) -> str:
        """A few words for a table cell. :meth:`verdict` is the sentence for prose."""
        if not self.is_cited:
            moved = self.moved_by_others
            if self.indirectly_shifted:
                return f"shifted {moved:.1f} SE by another prior"
            return "data alone"
        if self.contradicts_textbook:
            return "CONTRADICTS"
        if self.prior_dominates:
            return "MOSTLY TEXTBOOK"
        if self.data_is_silent:
            return "prior steadies it"
        return "data leads"

    def verdict(self) -> str:
        if not self.is_cited:
            if self.indirectly_shifted:
                return (
                    f"no cited weight, but moved {self.moved_by_others:.1f} SE by a "
                    "correlated factor's prior"
                )
            return "no cited weight — this road's data alone"
        if self.contradicts_textbook:
            return "CONTRADICTS the literature"
        if self.prior_dominates:
            return "mostly the textbook — your data added little"
        if self.data_is_silent:
            return "your data is inconclusive; the prior steadies it"
        return "your data leads"


@dataclass(frozen=True)
class EvidenceReport:
    """The three-way comparison for a run, and the answer the engine designates."""

    factors: list[FactorEvidence] = field(default_factory=list)
    answer: Answer = Answer.DATA
    reason: str = ""
    notes: tuple[str, ...] = ()

    @property
    def contradictions(self) -> list[FactorEvidence]:
        return [f for f in self.factors if f.contradicts_textbook]

    @property
    def prior_dominated(self) -> list[FactorEvidence]:
        return [f for f in self.factors if f.prior_dominates]

    @property
    def cited(self) -> list[FactorEvidence]:
        return [f for f in self.factors if f.is_cited]

    @property
    def indirectly_shifted(self) -> list[FactorEvidence]:
        """Uncited factors that another factor's prior moved anyway."""
        return [f for f in self.factors if f.indirectly_shifted]

    def as_dict(self) -> dict[str, object]:
        return {
            "answer": self.answer.value,
            "reason": self.reason,
            "factors": [
                {
                    "factor": f.factor,
                    "textbook": f.textbook,
                    "textbook_sd": f.textbook_sd,
                    "textbook_source": f.textbook_source,
                    "data": (
                        None
                        if f.data_mean is None
                        else {"mean": f.data_mean, "low": f.data_low, "high": f.data_high}
                    ),
                    "mix": (
                        None
                        if f.mix_mean is None
                        else {"mean": f.mix_mean, "low": f.mix_low, "high": f.mix_high}
                    ),
                    "prior_share": f.prior_share,
                    "prior_dominates": f.prior_dominates,
                    "moved_by_others_se": f.moved_by_others,
                    "indirectly_shifted": f.indirectly_shifted,
                    "contradicts_textbook": f.contradicts_textbook,
                    "label": f.label(),
                    "verdict": f.verdict(),
                }
                for f in self.factors
            ],
            "notes": list(self.notes),
        }


def compare(
    *,
    priors: PriorSet,
    data_fit: PosteriorFit | None,
    mix_fit: PosteriorFit | None,
) -> EvidenceReport:
    """Put the textbook, the corridor and their combination side by side.

    Args:
        priors: What the registry believed before this corridor.
        data_fit: The posterior under uninformative priors — the corridor alone.
        mix_fit: The posterior under the registry's priors.

    Returns:
        An :class:`EvidenceReport`. When either fit is missing the comparison still
        reports what it has, because a run that could only produce one of them should
        say so rather than silently drop the column.
    """
    factors: list[FactorEvidence] = []
    for prior in priors.priors:
        data = data_fit.coefficient(prior.factor) if data_fit else None
        mix = mix_fit.coefficient(prior.factor) if mix_fit else None
        factors.append(_evidence(prior, data, mix))

    answer, reason = _designate(factors, priors, data_fit, mix_fit)
    return EvidenceReport(
        factors=factors, answer=answer, reason=reason, notes=priors.notes
    )


def _evidence(
    prior: FactorPrior,
    data: PosteriorSummary | None,
    mix: PosteriorSummary | None,
) -> FactorEvidence:
    return FactorEvidence(
        factor=prior.factor,
        textbook=prior.mean if prior.is_cited else None,
        textbook_sd=prior.sd if prior.is_cited else None,
        textbook_source=prior.source,
        data_mean=data.mean if data else None,
        data_low=data.hdi_low if data else None,
        data_high=data.hdi_high if data else None,
        data_sd=data.sd if data else None,
        mix_mean=mix.mean if mix else None,
        mix_low=mix.hdi_low if mix else None,
        mix_high=mix.hdi_high if mix else None,
        mix_sd=mix.sd if mix else None,
        prior_share=_share(prior, data),
    )


def _share(prior: FactorPrior, data: PosteriorSummary | None) -> float | None:
    """How much of the mixed answer came from the prior rather than the corridor.

    Precision — one over variance — is how hard each side pulls, so the prior's share of
    the total pull is the share of the answer it is responsible for. Computed from the
    *measured* width of the data-only posterior rather than from the mixed one, so it
    reports what the corridor actually managed to say on its own.
    """
    if not prior.is_cited or data is None or data.sd <= 0 or prior.sd <= 0:
        return None
    prior_precision = 1.0 / prior.sd**2
    data_precision = 1.0 / data.sd**2
    total = prior_precision + data_precision
    return float(prior_precision / total) if total > 0 else None


def _designate(
    factors: list[FactorEvidence],
    priors: PriorSet,
    data_fit: PosteriorFit | None,
    mix_fit: PosteriorFit | None,
) -> tuple[Answer, str]:
    """Pick the answer, and say why in a sentence a reader can check."""
    if mix_fit is None or not mix_fit.converged:
        return Answer.DATA, (
            "The mixed fit is unavailable, so the corridor's own data is the answer."
        )
    if data_fit is None or not data_fit.converged:
        return Answer.MIX, (
            "The corridor-only fit is unavailable, so the mixed fit is the answer. "
            "Read its prior shares carefully — there is nothing here to compare against."
        )
    if not priors.is_informative:
        return Answer.DATA, (
            "No factor in this specification has an admissible cited weight, so there "
            "is no prior to mix in and the corridor's own data is the whole answer."
        )

    shares = [f.prior_share for f in factors if f.prior_share is not None]
    if not shares:
        return Answer.DATA, "Nothing to mix: no factor carries both a prior and a fit."

    worst = max(shares)
    typical = sorted(shares)[len(shares) // 2]

    if worst < DATA_DOMINATES:
        return Answer.DATA, (
            f"This corridor's data outweighs the literature on every factor — the "
            f"largest prior share is {worst:.0%}. The mixed fit is reported alongside "
            "and barely differs, which is the check that the priors are not doing the "
            "work. The answer with one source is the one worth designating."
        )

    dominated = [f.factor for f in factors if f.prior_dominates]
    if dominated:
        return Answer.MIX, (
            f"The mixed fit is the answer: this corridor's data is too thin to stand "
            f"alone on every factor (typical prior share {typical:.0%}). "
            f"{len(dominated)} factor(s) are mostly literature — "
            f"{', '.join(dominated)} — and must be read as statements about published "
            "evidence rather than about this road. No crash count may be derived from "
            "them."
        )
    return Answer.MIX, (
        f"The mixed fit is the answer: the corridor's own intervals are too wide to act "
        f"on and the cited weights steady them (typical prior share {typical:.0%}). No "
        "factor is prior-dominated, so every number here still has this road in it."
    )


__all__ = [
    "DATA_DOMINATES",
    "INDIRECT_SHIFT",
    "PRIOR_DOMINATES",
    "Answer",
    "EvidenceReport",
    "FactorEvidence",
    "compare",
]
