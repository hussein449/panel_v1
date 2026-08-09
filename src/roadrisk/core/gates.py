"""The nine validation checks that decide whether Mode A is admissible.

HARD failure → Mode B immediately, or job rejection. No retry.
SOFT failure → the ladder attempts a reduced specification before falling back.
INFO         → sets the count family, not the mode.

Every check writes its result into the run log and into the report. None of them is
silent, and none of them can be overridden by the user. There is no "use Mode A anyway"
button, because a user given that button will press it on data that cannot support it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from roadrisk.core.contract import ContractReport
from roadrisk.core.diagnostics import DispersionReport, VIFReport

MIN_CRASHES_PER_PARAMETER = 10
MAX_VIF = 5.0
MIN_SNAP_RATE = 0.80


class FailureType(StrEnum):
    HARD = "HARD"
    SOFT = "SOFT"
    INFO = "INFO"


class CheckStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class CheckResult:
    """The outcome of one gate, in a form the report can print verbatim."""

    number: int
    name: str
    status: CheckStatus
    failure_type: FailureType
    message: str
    threshold: str | None = None
    observed: str | None = None

    @property
    def failed(self) -> bool:
        return self.status is CheckStatus.FAILED

    @property
    def blocks_mode_a(self) -> bool:
        return self.failed and self.failure_type is FailureType.HARD

    @property
    def forces_descent(self) -> bool:
        return self.failed and self.failure_type is FailureType.SOFT


@dataclass(frozen=True)
class SnapReport:
    """How the client's crash table landed on the corridor.

    Supplied by the geospatial pipeline (Step 6). Absent when a panel is handed to the
    engine directly, in which case check 6 is recorded as skipped — never as passed.
    """

    n_supplied: int
    n_snapped: int
    dropped_reasons: dict[str, int] = field(default_factory=dict)

    @property
    def snap_rate(self) -> float:
        return self.n_snapped / self.n_supplied if self.n_supplied else 0.0

    @property
    def n_dropped(self) -> int:
        return self.n_supplied - self.n_snapped


@dataclass(frozen=True)
class GateReport:
    """All gate outcomes for one run."""

    checks: list[CheckResult]

    @property
    def hard_failures(self) -> list[CheckResult]:
        return [c for c in self.checks if c.blocks_mode_a]

    @property
    def soft_failures(self) -> list[CheckResult]:
        return [c for c in self.checks if c.forces_descent]

    @property
    def mode_a_admissible(self) -> bool:
        return not self.hard_failures

    def by_number(self, number: int) -> CheckResult | None:
        return next((c for c in self.checks if c.number == number), None)


# ---- individual checks -------------------------------------------------------


def check_zero_crash_rows(contract: ContractReport) -> CheckResult:
    """Check 1 — the one that matters.

    A count model built only on crash locations cannot estimate a rate. It can only
    describe crashes that already happened. This single check prevents the most common
    and most damaging misuse of the method.
    """
    present = contract.zero_crash_rows > 0
    return CheckResult(
        number=1,
        name="Zero-crash rows present",
        status=CheckStatus.PASSED if present else CheckStatus.FAILED,
        failure_type=FailureType.HARD,
        threshold="at least one row with n_crashes = 0",
        observed=f"{contract.zero_crash_rows:,} of {contract.n_rows:,} rows",
        message=(
            f"{contract.zero_crash_rows:,} zero-crash rows "
            f"({contract.zero_crash_share:.1%} of the panel)."
            if present
            else (
                "The panel contains only rows where crashes occurred. A count model "
                "needs the whole road, not just the places where crashes happened — "
                "without zero rows it cannot estimate a rate, only redescribe the "
                "crash table. Supply the full corridor extent."
            )
        ),
    )


def check_required_columns() -> CheckResult:
    """Check 2 — enforced by the input contract before this point."""
    return CheckResult(
        number=2,
        name="Required columns present and typed",
        status=CheckStatus.PASSED,
        failure_type=FailureType.HARD,
        threshold="unit_id, period, time_slot, n_crashes, length_km, duration_hours",
        observed="all present and correctly typed",
        message="Input contract satisfied; the job would have been rejected otherwise.",
    )


def check_exposure_positive(contract: ContractReport) -> CheckResult:
    """Check 3 — enforced by the input contract before this point."""
    return CheckResult(
        number=3,
        name="Exposure strictly positive",
        status=CheckStatus.PASSED,
        failure_type=FailureType.HARD,
        threshold="length_km x duration_hours > 0 on every row, no nulls",
        observed=f"total exposure {contract.exposure_total:,.1f} km-hours",
        message="Exposure is positive and complete; ln(exposure) is usable as an offset.",
    )


def check_crashes_per_parameter(total_crashes: int, n_parameters: int) -> CheckResult:
    """Check 4 — is there enough signal for the number of terms being estimated?"""
    per_parameter = total_crashes / n_parameters if n_parameters else float("inf")
    passed = per_parameter >= MIN_CRASHES_PER_PARAMETER
    return CheckResult(
        number=4,
        name="Crash count versus estimated parameters",
        status=CheckStatus.PASSED if passed else CheckStatus.FAILED,
        failure_type=FailureType.SOFT,
        threshold=f"{MIN_CRASHES_PER_PARAMETER} crashes per estimated parameter",
        observed=f"{per_parameter:.1f} ({total_crashes:,} crashes / {n_parameters} terms)",
        message=(
            f"{total_crashes:,} crashes support {n_parameters} estimated terms "
            f"at {per_parameter:.1f} per term."
            if passed
            else (
                f"{total_crashes:,} crashes cannot support {n_parameters} estimated "
                f"terms — {per_parameter:.1f} per term is below the minimum of "
                f"{MIN_CRASHES_PER_PARAMETER}. The specification must be reduced."
            )
        ),
    )


def check_temporal_resolution(contract: ContractReport) -> CheckResult:
    """Check 5 — do the crashes carry usable dates?"""
    passed = contract.n_periods > 1
    return CheckResult(
        number=5,
        name="Temporal resolution",
        status=CheckStatus.PASSED if passed else CheckStatus.FAILED,
        failure_type=FailureType.SOFT,
        threshold="more than one period in the panel",
        observed=f"{contract.n_periods} period(s), {contract.n_time_slots} time slot(s)",
        message=(
            f"Panel resolves {contract.n_periods} periods across "
            f"{contract.n_time_slots} time slot(s)."
            if passed
            else (
                "The panel collapses to a single period, so no temporal variation is "
                "available. Time-varying factors are constant and will be dropped."
            )
        ),
    )


def check_snap_rate(snap: SnapReport | None) -> CheckResult:
    """Check 6 — did the crash table actually land on this corridor?

    Skipped, never assumed, when the panel was supplied directly rather than built by
    the geospatial pipeline. Degrade loudly.
    """
    if snap is None:
        return CheckResult(
            number=6,
            name="Crash snap rate",
            status=CheckStatus.SKIPPED,
            failure_type=FailureType.SOFT,
            threshold=f"{MIN_SNAP_RATE:.0%} of crashes land on the corridor",
            observed="not measured",
            message=(
                "The panel was supplied pre-built, so snapping was not performed by "
                "this engine. Snap quality is unknown and is not assumed to be good."
            ),
        )

    passed = snap.snap_rate >= MIN_SNAP_RATE
    reasons = (
        "; ".join(f"{k}: {v:,}" for k, v in sorted(snap.dropped_reasons.items()))
        or "no reasons recorded"
    )
    return CheckResult(
        number=6,
        name="Crash snap rate",
        status=CheckStatus.PASSED if passed else CheckStatus.FAILED,
        failure_type=FailureType.SOFT,
        threshold=f"{MIN_SNAP_RATE:.0%} of crashes land on the corridor",
        observed=f"{snap.snap_rate:.1%} ({snap.n_snapped:,} of {snap.n_supplied:,})",
        message=(
            f"{snap.n_snapped:,} of {snap.n_supplied:,} crashes snapped "
            f"({snap.snap_rate:.1%}). Dropped — {reasons}."
            if passed
            else (
                f"Only {snap.snap_rate:.1%} of crashes snapped to the corridor "
                f"({snap.n_dropped:,} dropped). Below {MIN_SNAP_RATE:.0%} the panel is "
                f"not a faithful record of what happened on this road. Dropped — {reasons}."
            )
        ),
    )


def check_vif(vif: VIFReport) -> CheckResult:
    """Check 7 — collinearity across the active factors.

    This is the check that would have caught the geometry/roadside confounding on M51
    before it reached a result.
    """
    offenders = vif.above(MAX_VIF)
    passed = not offenders
    detail = ", ".join(f"{name} = {vif.values[name]:.1f}" for name in offenders[:5])
    return CheckResult(
        number=7,
        name="Collinearity (VIF)",
        status=CheckStatus.PASSED if passed else CheckStatus.FAILED,
        failure_type=FailureType.SOFT,
        threshold=f"max VIF < {MAX_VIF:.0f}",
        observed=f"max {vif.max_vif:.1f}" + (f" ({vif.worst})" if vif.worst else ""),
        message=(
            f"No collinearity above threshold; highest VIF is {vif.max_vif:.1f}."
            if passed
            else (
                f"{len(offenders)} term(s) exceed VIF {MAX_VIF:.0f} — {detail}. "
                "Coefficients on collinear terms are not separately interpretable; "
                "the worst offender is dropped before refitting."
            )
        ),
    )


def check_dispersion(dispersion: DispersionReport) -> CheckResult:
    """Check 8 — sets the family, not the mode."""
    return CheckResult(
        number=8,
        name="Variance-to-mean (count family)",
        status=CheckStatus.PASSED,
        failure_type=FailureType.INFO,
        threshold="ratio > 1.2 indicates negative binomial",
        observed=f"variance/mean = {dispersion.ratio:.2f}",
        message=(
            f"Mean {dispersion.mean:.3f}, variance {dispersion.variance:.3f}, "
            f"ratio {dispersion.ratio:.2f} — fitting as "
            f"{dispersion.family.value.replace('_', ' ')}."
        ),
    )


def check_convergence(converged: bool, specification: str) -> CheckResult:
    """Check 9 — evaluated at fit time by the ladder, not before it."""
    return CheckResult(
        number=9,
        name="Model convergence",
        status=CheckStatus.PASSED if converged else CheckStatus.FAILED,
        failure_type=FailureType.SOFT,
        threshold="optimiser reports convergence",
        observed="converged" if converged else "did not converge",
        message=(
            f"{specification} converged."
            if converged
            else (
                f"{specification} did not converge. Its estimates are not usable and "
                "the ladder steps down."
            )
        ),
    )


def run_pre_fit_gates(
    *,
    contract: ContractReport,
    vif: VIFReport,
    dispersion: DispersionReport,
    n_parameters: int,
    snap: SnapReport | None = None,
) -> GateReport:
    """Run checks 1-8. Check 9 is a fit-time check and is appended by the ladder."""
    return GateReport(
        checks=[
            check_zero_crash_rows(contract),
            check_required_columns(),
            check_exposure_positive(contract),
            check_crashes_per_parameter(contract.total_crashes, n_parameters),
            check_temporal_resolution(contract),
            check_snap_rate(snap),
            check_vif(vif),
            check_dispersion(dispersion),
        ]
    )


__all__ = [
    "MAX_VIF",
    "MIN_CRASHES_PER_PARAMETER",
    "MIN_SNAP_RATE",
    "CheckResult",
    "CheckStatus",
    "FailureType",
    "GateReport",
    "SnapReport",
    "check_convergence",
    "check_crashes_per_parameter",
    "check_dispersion",
    "check_exposure_positive",
    "check_required_columns",
    "check_snap_rate",
    "check_temporal_resolution",
    "check_vif",
    "check_zero_crash_rows",
    "run_pre_fit_gates",
]
