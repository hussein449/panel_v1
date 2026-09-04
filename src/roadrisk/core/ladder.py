"""Mode selection — the ladder.

**The engine picks the mode. The user cannot.** There is no "use Mode A anyway" button
and this module exposes no parameter that would create one. Users will always prefer
Mode A because it produces real numbers and reads as more authoritative; given the
choice they will select it on data that cannot support it, and the tool will print
confident numbers that are fabricated. That is the single most damaging thing this
product could do.

The engine walks **down** the rungs and takes the highest one that passes every gate.

Descent rules, all enforced here:

* Terms are dropped in the registry's declared priority order, never at random.
* The highest-VIF term is dropped first when collinearity is the trigger.
* The exposure offset is never dropped — it is structural, not a term.
* Every descent records which rung was attempted, which check failed, and what was shed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

import pandas as pd

from roadrisk.core.contract import ContractReport
from roadrisk.core.diagnostics import DispersionReport, Family, compute_vif
from roadrisk.core.gates import (
    MAX_VIF,
    CheckResult,
    check_convergence,
    check_crashes_per_parameter,
    check_vif,
)
from roadrisk.core.models import FitResult, fit_poisson
from roadrisk.core.models.glm import fit_negative_binomial_panel
from roadrisk.core.registry import Factor, Registry
from roadrisk.core.runlog import RunLog

STAGE = "mode_selection"


class Mode(StrEnum):
    A = "A"
    B = "B"


class Rung(StrEnum):
    A_FULL = "A-full"
    A_REDUCED = "A-reduced"
    A_MINIMAL = "A-minimal"
    B = "B"


@dataclass(frozen=True)
class RungSpec:
    """Data support required to attempt one rung."""

    rung: Rung
    min_crashes: int
    max_factors: int
    summary: str


MODE_A_RUNGS: tuple[RungSpec, ...] = (
    RungSpec(Rung.A_FULL, 700, 7, "Fitted, up to 7 factors plus the exposure offset"),
    RungSpec(Rung.A_REDUCED, 400, 5, "Fitted, up to 5 factors"),
    RungSpec(Rung.A_MINIMAL, 100, 3, "Fitted, up to 3 factors, wide intervals"),
)


@dataclass(frozen=True)
class DescentEvent:
    """One abandoned rung, and why."""

    attempted: Rung
    failed_check: str
    detail: str
    dropped: list[str] = field(default_factory=list)

    @property
    def receipt(self) -> str:
        text = f"Attempted {self.attempted.value}. Failed {self.failed_check}: {self.detail}"
        if self.dropped:
            text += f" Dropped: {', '.join(self.dropped)} — by registry priority."
        return text


@dataclass(frozen=True)
class LadderResult:
    """Where the ladder stopped, and everything shed on the way down."""

    mode: Mode
    rung: Rung
    factors: list[Factor]
    fit: FitResult | None = None
    reference_poisson: FitResult | None = None
    fit_checks: list[CheckResult] = field(default_factory=list)
    descent: list[DescentEvent] = field(default_factory=list)
    dropped_for_collinearity: list[str] = field(default_factory=list)
    refusal: str | None = None

    @property
    def factor_names(self) -> list[str]:
        return [f.name for f in self.factors]

    @property
    def stepped_down(self) -> bool:
        return bool(self.descent)


def walk_ladder(
    *,
    counts: pd.Series,
    design: pd.DataFrame,
    log_exposure: pd.Series,
    factors: list[Factor],
    contract: ContractReport,
    dispersion: DispersionReport,
    unit_ids: pd.Series,
    log: RunLog,
) -> LadderResult:
    """Walk down the rungs and stop at the first that passes every gate.

    Args:
        counts: ``n_crashes``.
        design: Transformed design matrix for every available factor.
        log_exposure: ``ln(length_km * duration_hours)``, used as the offset.
        factors: Factors present in ``design``.
        contract: Summary of the accepted panel.
        dispersion: Pre-fit variance-to-mean report; refined by the Poisson reference fit.
        unit_ids: Unit id per row. The clusters rung 2 corrects the standard errors over.
        log: Run log, appended in place.

    Returns:
        A :class:`LadderResult`. Mode B is the floor — this never raises.
    """
    descent: list[DescentEvent] = []
    fit_checks: list[CheckResult] = []

    if not factors:
        return _fall_to_mode_b(
            descent,
            fit_checks,
            log,
            reason=(
                "No registry factor has a usable column in this panel, so there is "
                "nothing to fit."
            ),
        )

    for spec in MODE_A_RUNGS:
        if contract.total_crashes < spec.min_crashes:
            event = DescentEvent(
                attempted=spec.rung,
                failed_check="crash count",
                detail=(
                    f"{contract.total_crashes:,} crashes available, "
                    f"{spec.min_crashes:,} required."
                ),
            )
            descent.append(event)
            log.descent(
                STAGE,
                "insufficient_crashes",
                event.receipt,
                rung=spec.rung.value,
                available=contract.total_crashes,
                required=spec.min_crashes,
            )
            continue

        selected = Registry.in_keep_order(factors)[: spec.max_factors]
        selected, shed_for_vif = _resolve_collinearity(design, selected, log, spec.rung)

        n_parameters = len(selected) + 1 + (
            1 if dispersion.family is Family.NEGATIVE_BINOMIAL else 0
        )
        parameter_check = check_crashes_per_parameter(
            contract.total_crashes, n_parameters
        )
        fit_checks.append(parameter_check)
        if parameter_check.failed:
            event = DescentEvent(
                attempted=spec.rung,
                failed_check="crashes per parameter",
                detail=parameter_check.observed or "",
                dropped=shed_for_vif,
            )
            descent.append(event)
            log.descent(
                STAGE, "insufficient_signal", event.receipt, rung=spec.rung.value
            )
            continue

        subset = design[[f.name for f in selected]]
        # Check 7 again, on the design that is about to be fitted. The pre-fit gate saw
        # every available factor; this rung fits at most `spec.max_factors` of them, so
        # the two can disagree — and it is this one that describes the result.
        fit_checks.append(check_vif(compute_vif(subset), fitted=True))
        poisson = fit_poisson(counts, subset, log_exposure)
        shipped, note = _fit_shipped(
            counts, subset, log_exposure, poisson, dispersion, unit_ids
        )

        convergence = check_convergence(
            shipped is not None and shipped.converged,
            f"{spec.rung.value} ({len(selected)} factors)",
        )
        fit_checks.append(convergence)

        if shipped is None or not shipped.converged:
            reason = (
                shipped.failure_reason
                if shipped is not None
                else "no count model converged"
            )
            event = DescentEvent(
                attempted=spec.rung,
                failed_check="convergence",
                detail=str(reason),
                dropped=shed_for_vif,
            )
            descent.append(event)
            log.descent(
                STAGE, "no_convergence", event.receipt, rung=spec.rung.value
            )
            continue

        if note:
            log.warning(STAGE, "family_fallback", note, rung=spec.rung.value)

        for panel_note in shipped.notes:
            log.warning(STAGE, "panel_standard_errors", panel_note, rung=spec.rung.value)

        log.info(
            STAGE,
            "rung_selected",
            (
                f"Mode A at {spec.rung.value} — {shipped.specification}, "
                f"{len(selected)} factor(s), {contract.total_crashes:,} crashes."
            ),
            rung=spec.rung.value,
            specification=shipped.specification,
            factors=[f.name for f in selected],
        )

        return LadderResult(
            mode=Mode.A,
            rung=spec.rung,
            factors=selected,
            fit=shipped,
            reference_poisson=poisson,
            fit_checks=fit_checks,
            descent=descent,
            dropped_for_collinearity=shed_for_vif,
        )

    return _fall_to_mode_b(
        descent,
        fit_checks,
        log,
        reason=(
            "No Mode A rung passed its gates. A-minimal is the floor; below it the "
            "result is Mode B."
        ),
    )


def _resolve_collinearity(
    design: pd.DataFrame,
    selected: list[Factor],
    log: RunLog,
    rung: Rung,
) -> tuple[list[Factor], list[str]]:
    """Drop the highest-VIF term until collinearity is below threshold."""
    shed: list[str] = []
    while len(selected) > 1:
        vif = compute_vif(design[[f.name for f in selected]])
        if vif.max_vif <= MAX_VIF:
            break
        worst = vif.worst
        if worst is None:
            break
        shed.append(worst)
        selected = [f for f in selected if f.name != worst]
        log.warning(
            STAGE,
            "collinearity_drop",
            (
                f"Dropped '{worst}' at {rung.value} — VIF {vif.values[worst]:.1f} "
                f"exceeds {MAX_VIF:.0f}. Coefficients on collinear terms are not "
                "separately interpretable."
            ),
            rung=rung.value,
            factor=worst,
            vif=round(float(vif.values[worst]), 3),
        )
    return selected, shed


def _fit_shipped(
    counts: pd.Series,
    design: pd.DataFrame,
    log_exposure: pd.Series,
    poisson: FitResult,
    dispersion: DispersionReport,
    unit_ids: pd.Series,
) -> tuple[FitResult | None, str | None]:
    """Fit the model that may reach a client.

    Rung 2 — NB2 with standard errors clustered by unit — is the shipped baseline, and
    the coefficients are identical to rung 1's. Clustering is declined, loudly, on a
    corridor with too few units for the estimator to be trustworthy; the fit that comes
    back is then rung 1's, carrying a note saying how much too certain it is.

    Poisson is a reference fit and is normally never reported. The one exception is an
    NB2 that fails to converge on data showing no overdispersion, where NB2 is trying to
    estimate a dispersion parameter that is genuinely near zero. That substitution is
    logged, never silent.
    """
    negative_binomial = fit_negative_binomial_panel(
        counts, design, log_exposure, unit_ids
    )
    if negative_binomial.converged:
        return negative_binomial, None

    not_overdispersed = (
        poisson.converged
        and poisson.pearson_dispersion is not None
        and poisson.pearson_dispersion <= 1.2
    )
    if not_overdispersed:
        return poisson, (
            "NB2 did not converge, but the Poisson reference fit shows no "
            f"overdispersion (Pearson dispersion {poisson.pearson_dispersion:.2f}). "
            "Reporting the Poisson fit instead. The dispersion parameter NB2 was "
            "trying to estimate is near zero, which is why it failed."
        )

    return negative_binomial, None


def _fall_to_mode_b(
    descent: list[DescentEvent],
    fit_checks: list[CheckResult],
    log: RunLog,
    *,
    reason: str,
) -> LadderResult:
    log.refusal(STAGE, "mode_b_floor", reason)
    return LadderResult(
        mode=Mode.B,
        rung=Rung.B,
        factors=[],
        fit_checks=fit_checks,
        descent=descent,
        refusal=reason,
    )


__all__ = [
    "MODE_A_RUNGS",
    "DescentEvent",
    "LadderResult",
    "Mode",
    "Rung",
    "RungSpec",
    "walk_ladder",
]
