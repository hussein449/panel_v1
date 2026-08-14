"""The engine — one entry point for a complete assessment.

    validate → diagnose → gate → select mode → fit or score → sign guard → report

Everything the report needs comes back in a single :class:`Assessment`. Nothing is
computed later and nothing is left implicit: the mode, the rung, every gate outcome,
every dropped term, the provenance of every factor and the manifest that reproduces the
run all travel together.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from roadrisk.core.context import RunContext
from roadrisk.core.contract import (
    CRASH_COLUMN,
    LOG_EXPOSURE_COLUMN,
    UNIT_COLUMN,
    ContractReport,
    prepare_panel,
)
from roadrisk.core.diagnostics import (
    DispersionReport,
    VIFReport,
    compute_dispersion,
    compute_vif,
    zero_variance_columns,
)
from roadrisk.core.errors import WeightNotSourced
from roadrisk.core.gates import GateReport, SnapReport, run_pre_fit_gates
from roadrisk.core.ladder import LadderResult, Mode, Rung, walk_ladder
from roadrisk.core.models import FitResult, IndexResult, score_index
from roadrisk.core.registry import Factor, Registry, load_registry
from roadrisk.core.runlog import RunLog, RunManifest, build_manifest
from roadrisk.core.signguard import (
    DEFAULT_CORRELATION_THRESHOLD,
    DEFAULT_MAX_LEAVE_ONE_OUT,
    SignGuardReport,
    run_sign_guard,
)
from roadrisk.core.transforms import build_design

STAGE = "engine"

MODE_A_BANNER = "MODE A — FITTED FROM YOUR DATA · {factors} factors · {crashes:,} crashes"
MODE_B_BANNER = "MODE B — PUBLISHED WEIGHTS · RANKING ONLY · not a crash prediction"


@dataclass(frozen=True)
class Assessment:
    """A complete, self-describing assessment of one panel."""

    mode: Mode
    rung: Rung
    banner: str
    registry_version: str
    context: RunContext
    contract: ContractReport
    gates: GateReport
    ladder: LadderResult
    dispersion: DispersionReport
    vif: VIFReport
    available_factors: list[Factor]
    missing_factors: list[Factor]
    constant_factors: list[str]
    manifest: RunManifest
    log: RunLog
    fit: FitResult | None = None
    index: IndexResult | None = None
    sign_guard: SignGuardReport | None = None
    refusal_receipt: str | None = None
    descent_receipt: str | None = None
    index_refusal: str | None = None

    @property
    def is_mode_a(self) -> bool:
        return self.mode is Mode.A

    @property
    def factor_names(self) -> list[str]:
        if self.fit is not None:
            return self.fit.factor_names
        if self.index is not None:
            return self.index.factor_names
        return []

    @property
    def has_result(self) -> bool:
        """False when Mode A was refused and Mode B could not score either."""
        return self.fit is not None or self.index is not None

    def as_dict(self) -> dict[str, Any]:
        """Serialisable summary. The shape the API and the report template consume."""
        return {
            "mode": self.mode.value,
            "rung": self.rung.value,
            "banner": self.banner,
            "registry_version": self.registry_version,
            "context": {
                "facility_type": self.context.facility_type.value,
                "region": self.context.region.value,
                "severity": self.context.severity.value,
                "declared": self.context.is_declared,
                "crash_mix": self.context.crash_mix.as_dict(),
                "crash_mix_is_default": self.context.uses_default_crash_mix,
                "segment_length_km": self.context.segment_length_km,
                "reference_aadt": self.context.reference_aadt,
            },
            "panel": {
                "rows": self.contract.n_rows,
                "units": self.contract.n_units,
                "periods": self.contract.n_periods,
                "time_slots": self.contract.n_time_slots,
                "total_crashes": self.contract.total_crashes,
                "zero_crash_rows": self.contract.zero_crash_rows,
                "zero_crash_share": round(self.contract.zero_crash_share, 4),
                "exposure_total": round(self.contract.exposure_total, 3),
            },
            "checks": [
                {
                    "number": c.number,
                    "name": c.name,
                    "status": c.status.value,
                    "failure_type": c.failure_type.value,
                    "threshold": c.threshold,
                    "observed": c.observed,
                    "message": c.message,
                }
                for c in [*self.gates.checks, *self.ladder.fit_checks]
            ],
            "factors": {
                "available": [f.name for f in self.available_factors],
                "missing": [
                    {"name": f.name, "missing_behaviour": f.missing_behaviour}
                    for f in self.missing_factors
                ],
                "constant": self.constant_factors,
                "dropped_for_collinearity": self.ladder.dropped_for_collinearity,
                "in_model": self.factor_names,
            },
            "fit": _fit_as_dict(self.fit),
            "index": _index_as_dict(self.index),
            "sign_guard": _sign_guard_as_dict(self.sign_guard),
            "receipts": {
                "refusal": self.refusal_receipt,
                "descent": self.descent_receipt,
                "index_refusal": self.index_refusal,
            },
            "manifest": self.manifest.as_dict(),
            "log": self.log.as_records(),
        }


def assess(
    panel: pd.DataFrame,
    *,
    registry: Registry | None = None,
    context: RunContext | None = None,
    snap: SnapReport | None = None,
    correlation_threshold: float = DEFAULT_CORRELATION_THRESHOLD,
    max_leave_one_out: int = DEFAULT_MAX_LEAVE_ONE_OUT,
) -> Assessment:
    """Assess one panel end to end.

    Args:
        panel: The panel. Must satisfy the input contract.
        registry: Factor registry. Defaults to the one shipped with the package.
        context: What kind of corridor this is and what crashes were counted, used to
            pick between published weights in Mode B. Undeclared by default, which
            admits only unrestricted weights — the engine does not guess.
        snap: Crash-snapping report from the geospatial pipeline, when there was one.
        correlation_threshold: Minimum |r| for a factor to count as a correlated partner
            in the sign guard's follow-up diagnostics.
        max_leave_one_out: Cap on leave-one-unit-out refits per contradicting factor.

    Raises:
        ContractViolation: The panel breaks the input contract. The job is rejected.
        TransformError: A declared transform cannot be applied to the data supplied.

    Returns:
        An :class:`Assessment`. Mode B is the floor, so a contract-valid panel always
        produces a result object even when nothing could be fitted or scored.
    """
    log = RunLog()
    active_registry = registry if registry is not None else load_registry()

    prepared, contract = prepare_panel(panel)
    log.info(
        STAGE,
        "panel_accepted",
        (
            f"Panel accepted — {contract.n_rows:,} rows, {contract.n_units:,} units, "
            f"{contract.n_periods} period(s), {contract.total_crashes:,} crashes, "
            f"{contract.zero_crash_rows:,} zero-crash rows."
        ),
        rows=contract.n_rows,
        units=contract.n_units,
        total_crashes=contract.total_crashes,
    )

    active_context = (context if context is not None else RunContext()).measured_from(
        prepared
    )
    log.info(
        STAGE,
        "context",
        (
            f"Run context — {active_context.describe()}"
            + (
                ""
                if active_context.is_declared
                else ". Nothing was declared, so only unrestricted weights are "
                "admissible in Mode B. Declaring the corridor type, region and crash "
                "severity may admit better-matched weights."
            )
        ),
        facility_type=active_context.facility_type.value,
        region=active_context.region.value,
        severity=active_context.severity.value,
        declared=active_context.is_declared,
    )

    manifest = build_manifest(
        prepared,
        registry_version=active_registry.version,
        registry_sha256=active_registry.sha256,
        settings={
            "correlation_threshold": correlation_threshold,
            "max_leave_one_out": max_leave_one_out,
            "snap_supplied": snap is not None,
            "facility_type": active_context.facility_type.value,
            "region": active_context.region.value,
            "severity": active_context.severity.value,
            "crash_mix": active_context.crash_mix.as_dict(),
        },
    )

    available, missing, constant, design = _resolve_factors(
        prepared, active_registry, log
    )

    counts = prepared[CRASH_COLUMN]
    log_exposure = prepared[LOG_EXPOSURE_COLUMN]
    unit_ids = prepared[UNIT_COLUMN]

    vif = compute_vif(design)
    dispersion = compute_dispersion(counts)
    log.info(
        STAGE,
        "dispersion",
        (
            f"Variance-to-mean {dispersion.ratio:.2f} — count family set to "
            f"{dispersion.family.value.replace('_', ' ')}."
        ),
        ratio=round(dispersion.ratio, 4),
        family=dispersion.family.value,
    )

    gates = run_pre_fit_gates(
        contract=contract,
        vif=vif,
        dispersion=dispersion,
        n_parameters=len(available) + 2,
        snap=snap,
    )
    for check in gates.checks:
        log.info(
            "gates",
            f"check_{check.number}",
            f"[{check.status.value}] {check.name} — {check.message}",
            number=check.number,
            status=check.status.value,
            failure_type=check.failure_type.value,
        )

    common = {
        "registry_version": active_registry.version,
        "context": active_context,
        "contract": contract,
        "gates": gates,
        "dispersion": dispersion,
        "vif": vif,
        "available_factors": available,
        "missing_factors": missing,
        "constant_factors": constant,
        "manifest": manifest,
        "log": log,
    }

    hard_failures = gates.hard_failures
    if hard_failures:
        receipt = _refusal_receipt(hard_failures)
        log.refusal(STAGE, "mode_a_refused", receipt)
        ladder = LadderResult(
            mode=Mode.B, rung=Rung.B, factors=[], refusal=receipt
        )
        return _mode_b_assessment(
            ladder=ladder,
            design=design,
            available=available,
            unit_ids=unit_ids,
            log=log,
            refusal_receipt=receipt,
            common=common,
        )

    ladder = walk_ladder(
        counts=counts,
        design=design,
        log_exposure=log_exposure,
        factors=available,
        contract=contract,
        dispersion=dispersion,
        unit_ids=unit_ids,
        log=log,
    )
    descent_receipt = _descent_receipt(ladder, available)

    if ladder.mode is Mode.B:
        return _mode_b_assessment(
            ladder=ladder,
            design=design,
            available=available,
            unit_ids=unit_ids,
            log=log,
            refusal_receipt=ladder.refusal,
            descent_receipt=descent_receipt,
            common=common,
        )

    assert ladder.fit is not None  # noqa: S101 - guaranteed by walk_ladder on Mode A
    sign_guard = run_sign_guard(
        fit=ladder.fit,
        counts=counts,
        design=design[[f.name for f in ladder.factors]],
        log_exposure=log_exposure,
        unit_ids=unit_ids,
        factors=ladder.factors,
        log=log,
        correlation_threshold=correlation_threshold,
        max_leave_one_out=max_leave_one_out,
    )

    return Assessment(
        mode=Mode.A,
        rung=ladder.rung,
        banner=MODE_A_BANNER.format(
            factors=len(ladder.factors), crashes=contract.total_crashes
        ),
        ladder=ladder,
        fit=ladder.fit,
        sign_guard=sign_guard,
        descent_receipt=descent_receipt,
        **common,  # type: ignore[arg-type]
    )


# ---- internals ---------------------------------------------------------------


def _resolve_factors(
    prepared: pd.DataFrame,
    registry: Registry,
    log: RunLog,
) -> tuple[list[Factor], list[Factor], list[str], pd.DataFrame]:
    """Work out which registry factors this panel can actually support."""
    available = registry.available(prepared.columns)
    missing = registry.missing(prepared.columns)

    for factor in missing:
        log.warning(
            "factors",
            "column_absent",
            (
                f"'{factor.name}' has no column '{factor.column}' in this panel — "
                f"one term dropped. {factor.missing_behaviour.strip()}"
            ),
            factor=factor.name,
            column=factor.column,
        )

    design = build_design(prepared, available)
    constant = zero_variance_columns(design)
    if constant:
        for name in constant:
            log.warning(
                "factors",
                "constant_column",
                (
                    f"'{name}' is constant across the panel and carries no information. "
                    "Dropped before fitting — it would make the design singular."
                ),
                factor=name,
            )
        available = [f for f in available if f.name not in constant]
        design = design.drop(columns=constant)

    log.info(
        "factors",
        "resolved",
        (
            f"{len(available)} of {len(registry.factors)} registry factors are usable "
            f"on this panel."
        ),
        available=[f.name for f in available],
    )
    return available, missing, constant, design


def _mode_b_assessment(
    *,
    ladder: LadderResult,
    design: pd.DataFrame,
    available: list[Factor],
    unit_ids: pd.Series,
    log: RunLog,
    common: dict[str, Any],
    refusal_receipt: str | None = None,
    descent_receipt: str | None = None,
) -> Assessment:
    """Score Mode B, or explain precisely why it could not be scored."""
    index: IndexResult | None = None
    index_refusal: str | None = None
    context: RunContext = common["context"]

    try:
        index = score_index(design, available, unit_ids, context)
        log.info(
            "mode_b",
            "index_scored",
            (
                f"Mode B index scored {index.n_units:,} units from "
                f"{len(index.terms)} cited weight(s)."
            ),
            factors=index.factor_names,
        )
        log.info(
            "mode_b",
            "crash_mix",
            (
                f"Score decomposed by crash type — {index.crash_mix.describe()}. "
                + (
                    "Using the default distribution; it is an HSM figure and carries "
                    "the same regional transfer problem as any other. Supplying a "
                    "local distribution is a cheap improvement."
                    if index.context.uses_default_crash_mix
                    else "Distribution supplied by the caller."
                )
            ),
            shares=index.crash_mix.as_dict(),
            bucket_mean_scores={
                b.value: round(v, 6) for b, v in index.bucket_mean_scores.items()
            },
        )
        _log_index_provenance(index, log)
    except WeightNotSourced as exc:
        index_refusal = str(exc)
        log.refusal("mode_b", "unsourced_weights", index_refusal)

    return Assessment(
        mode=Mode.B,
        rung=Rung.B,
        banner=MODE_B_BANNER,
        ladder=ladder,
        index=index,
        refusal_receipt=refusal_receipt,
        descent_receipt=descent_receipt,
        index_refusal=index_refusal,
        **common,  # type: ignore[arg-type]
    )


def _log_index_provenance(index: IndexResult, log: RunLog) -> None:
    """Record which weight was used for each term, and every reason to doubt it."""
    for term in index.terms:
        log.info(
            "mode_b",
            "weight_selected",
            f"'{term.factor}' scored with the {term.family} weight {term.weight:+.4f}.",
            factor=term.factor,
            family=term.family,
            weight=term.weight,
        )
        for concern in term.concerns:
            log.warning(
                "mode_b",
                concern.code,
                f"'{term.factor}': {concern.message}",
                factor=term.factor,
            )
        agreement = term.agreement
        if agreement is None:
            continue
        if agreement.signs_conflict:
            log.flag(
                "mode_b",
                "source_sign_conflict",
                f"'{term.factor}': {agreement.note} Values: "
                + ", ".join(
                    f"{family}={value:+.4f}"
                    for family, value in zip(
                        agreement.families, agreement.values, strict=True
                    )
                ),
                factor=term.factor,
                families=agreement.families,
                values=agreement.values,
            )
        else:
            log.info(
                "mode_b",
                "source_agreement",
                f"'{term.factor}': {agreement.note}",
                factor=term.factor,
                score=agreement.score,
                comparable=agreement.comparable,
            )

    if index.skipped_unsourced:
        log.warning(
            "mode_b",
            "unsourced_skipped",
            (
                f"{len(index.skipped_unsourced)} factor(s) were available in the panel "
                "but carry no cited weight, so they did not enter the index: "
                + ", ".join(index.skipped_unsourced)
                + "."
            ),
            factors=index.skipped_unsourced,
        )

    if index.skipped_inadmissible:
        log.warning(
            "mode_b",
            "inadmissible_skipped",
            (
                f"{len(index.skipped_inadmissible)} factor(s) carry a cited weight, but "
                "none valid for this run's facility type or crash severity, so they did "
                "not enter the index: "
                + ", ".join(index.skipped_inadmissible)
                + ". Stretching a weight across facility or severity is a correctness "
                "error, not a transfer approximation."
            ),
            factors=index.skipped_inadmissible,
        )


def _refusal_receipt(hard_failures: list[Any]) -> str:
    """Plain-English explanation of why Mode A was refused.

    This is also a sales tool — it tells the client exactly what data to supply to get
    a better answer.
    """
    reasons = " ".join(f.message for f in hard_failures)
    return f"Mode A was not available. {reasons}"


def _descent_receipt(ladder: LadderResult, available: list[Factor]) -> str | None:
    if not ladder.descent:
        return None

    parts = [event.receipt for event in ladder.descent]
    if ladder.mode is Mode.A:
        parts.append(
            f"Stepped to {ladder.rung.value} ({len(ladder.factors)} factors)."
        )
        dropped = [f.name for f in available if f.name not in ladder.factor_names]
        if dropped:
            parts.append(
                f"Dropped: {', '.join(dropped)} — by registry priority."
            )
    else:
        parts.append("No Mode A rung passed its gates. The result is Mode B — ranking only.")
    return " ".join(parts)


def _fit_as_dict(fit: FitResult | None) -> dict[str, Any] | None:
    if fit is None:
        return None
    return {
        "specification": fit.specification,
        "family": fit.family.value,
        "converged": fit.converged,
        "n_observations": fit.n_observations,
        "n_parameters": fit.n_parameters,
        "log_likelihood": fit.log_likelihood,
        "aic": fit.aic,
        "bic": fit.bic,
        "alpha": fit.alpha,
        "pearson_dispersion": fit.pearson_dispersion,
        "n_clusters": fit.n_clusters,
        "cluster_widening": fit.cluster_widening,
        "naive_std_errors": fit.naive_std_errors,
        "panel_notes": list(fit.notes),
        "intercept": _coefficient_as_dict(fit.intercept),
        "coefficients": [_coefficient_as_dict(c) for c in fit.coefficients],
    }


def _coefficient_as_dict(coefficient: Any) -> dict[str, Any] | None:
    if coefficient is None:
        return None
    return {
        "factor": coefficient.factor,
        "estimate": coefficient.estimate,
        "std_error": coefficient.std_error,
        "z_value": coefficient.z_value,
        "p_value": coefficient.p_value,
        "ci_low": coefficient.ci_low,
        "ci_high": coefficient.ci_high,
    }


def _index_as_dict(index: IndexResult | None) -> dict[str, Any] | None:
    if index is None:
        return None
    return {
        "specification": index.specification,
        "n_units": index.n_units,
        "n_observations": index.n_observations,
        "skipped_unsourced": index.skipped_unsourced,
        "skipped_inadmissible": index.skipped_inadmissible,
        "crash_mix": index.crash_mix.as_dict(),
        "bucket_mean_scores": {
            bucket.value: value for bucket, value in index.bucket_mean_scores.items()
        },
        "terms": [
            {
                "factor": t.factor,
                "label": t.label,
                "weight": t.weight,
                "weight_source": t.weight_source,
                "family": t.family,
                "scope": t.scope.value,
                "mean_contribution": t.mean_contribution,
                "sd_contribution": t.sd_contribution,
                "concerns": [
                    {"code": c.code, "message": c.message} for c in t.concerns
                ],
                "agreement": (
                    {
                        "score": t.agreement.score,
                        "comparable": t.agreement.comparable,
                        "families": t.agreement.families,
                        "values": t.agreement.values,
                        "signs_conflict": t.agreement.signs_conflict,
                        "note": t.agreement.note,
                    }
                    if t.agreement
                    else None
                ),
            }
            for t in index.terms
        ],
        "ranking": index.unit_ranking.to_dict("records"),
    }


def _sign_guard_as_dict(report: SignGuardReport | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        "clean": report.clean,
        "n_contradictions": len(report.contradictions),
        "findings": [
            {
                "factor": f.factor,
                "expected_sign": f.expected_sign.value,
                "estimate": f.estimate,
                "p_value": f.p_value,
                "contradicts": f.contradicts,
                "significant": f.significant,
                "verdict": f.verdict,
                "univariate_estimate": f.univariate_estimate,
                "correlations": [
                    {"partner": name, "r": value} for name, value in f.correlations
                ],
                "pairwise": [
                    {
                        "partner": p.partner,
                        "correlation": p.correlation,
                        "estimate": p.estimate,
                        "agrees_with_expected": p.agrees_with_expected,
                        "differs_from_full_fit": p.differs_from_full_fit,
                    }
                    for p in f.pairwise
                ],
                "leave_one_out": (
                    {
                        "n_units": f.leave_one_out.n_units,
                        "n_refits": f.leave_one_out.n_refits,
                        "capped": f.leave_one_out.capped,
                        "estimate_min": f.leave_one_out.estimate_min,
                        "estimate_max": f.leave_one_out.estimate_max,
                        "n_sign_flips": f.leave_one_out.n_sign_flips,
                    }
                    if f.leave_one_out
                    else None
                ),
            }
            for f in report.findings
        ],
    }


__all__ = ["Assessment", "assess"]
