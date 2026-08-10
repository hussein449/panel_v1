"""Derive Mode B registry weights from published crash modification factors.

Run this to regenerate every weight in the factor registry:

    python tools/derive_weights.py            # human-readable report
    python tools/derive_weights.py --yaml     # registry-ready YAML fragments

Nothing here is a number anyone chose. Each weight is computed from a published
equation reproduced verbatim below, and every assumption needed to get from that
equation to a registry weight is a named constant that can be argued with.

WHY A DERIVATION IS NEEDED AT ALL
---------------------------------
Published CMFs and risk factors are *multipliers*. The registry needs *log-scale
coefficients on transformed columns*, because a Mode B weight has to sit on the same
scale as a Mode A coefficient — that is what makes the two modes comparable, and what
makes "Mode B is the prior, Mode A is the prior updated by data" true rather than
decorative.

A multiplier of `c` corresponds to a log-scale contribution of `ln(c)`. Where the
relationship is already log-linear the coefficient falls straight out. Otherwise
`ln(multiplier)` is fitted against the declared transform by least squares over a
stated range, and R² is reported so a poor linearisation is visible.

WHY EVERY WEIGHT CARRIES A CONTEXT
----------------------------------
An HSM weight is a US rural two-lane number. An Elvik speed exponent is severity
specific. An iRAP risk factor covers particular crash types. Applying any of them
outside that context is either a transfer approximation or an outright error, and the
registry now records which. The engine picks the best-matched weight, reports what it
had to reach for, and scores agreement where two sources genuinely overlap.

BAND MIDPOINT RULE
------------------
Several sources state multipliers per band, with the top band unbounded. Every
midpoint here follows one rule: interior bands use their true midpoint; the unbounded
top band uses `threshold + half the width of the band below it`. HSM's ">6%" becomes
7.5, iRAP's ">10%" becomes 11.25. A rule beats a preference.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field

import numpy as np

FEET_PER_METRE = 3.280839895
MILES_PER_KM = 0.621371192


@dataclass(frozen=True)
class Derivation:
    """One derived registry weight, with everything needed to audit it."""

    factor: str
    transform: str
    value: float
    source: str
    family: str
    assumptions: str
    facility_type: str = "any"
    region: str = "global"
    severity: str = "all"
    scope: str = "total"
    fit_r2: float | None = None
    assumes: dict[str, float] = field(default_factory=dict)
    caveat: str | None = None

    @property
    def key(self) -> str:
        return f"{self.factor}::{self.family}::{self.severity}"

    def report(self) -> str:
        fit = "exact" if self.fit_r2 is None else f"R² = {self.fit_r2:.4f}"
        head = (
            f"{self.factor:<22} {self.family:<6} {self.transform:<9} "
            f"{self.value:+.4f}   ({fit})"
        )
        lines = [
            head,
            f"    context     : {self.facility_type} / {self.region} / "
            f"{self.severity} / {self.scope}",
            f"    source      : {self.source}",
            f"    assumptions : {self.assumptions}",
        ]
        if self.assumes:
            lines.append(f"    assumes     : {self.assumes}")
        if self.caveat:
            lines.append(f"    CAVEAT      : {self.caveat}")
        return "\n".join(lines) + "\n"

    def as_yaml(self) -> str:
        lines = [
            f"      - value: {self.value:.4f}",
            f"        family: {self.family}",
            f"        facility_type: {self.facility_type}",
            f"        region: {self.region}",
            f"        severity: {self.severity}",
            f"        scope: {self.scope}",
        ]
        if self.fit_r2 is not None:
            lines.append(f"        fit_r2: {self.fit_r2:.4f}")
        if self.assumes:
            inner = ", ".join(f"{k}: {v:g}" for k, v in self.assumes.items())
            lines.append(f"        assumes: {{ {inner} }}")
        lines.append(f"        source: >\n          {self.source}")
        if self.caveat:
            lines.append(f"        caveat: >\n          {self.caveat}")
        return "\n".join(lines)


def _fit_log_linear(x: np.ndarray, log_multiplier: np.ndarray) -> tuple[float, float]:
    """Least-squares slope of ln(multiplier) on the transformed variable, plus R².

    An intercept is fitted and then discarded. Mode B is an ordinal ranking, so a
    constant shifts every unit equally and cannot change the order.
    """
    design = np.column_stack([np.ones_like(x), x])
    coefficients, *_ = np.linalg.lstsq(design, log_multiplier, rcond=None)
    predicted = design @ coefficients
    residual_ss = float(((log_multiplier - predicted) ** 2).sum())
    total_ss = float(((log_multiplier - log_multiplier.mean()) ** 2).sum())
    r_squared = 1.0 - residual_ss / total_ss if total_ss > 0 else 1.0
    return float(coefficients[1]), r_squared


# =============================================================================
# AASHTO HSM — rural two-lane two-way segments, North America
# =============================================================================

HSM_SOURCE_NOTE = (
    "Verified verbatim against the NCHRP draft text for the HSM 2nd edition, and "
    "checked against that document's own worked example"
)


def hsm_roadside_hazard() -> Derivation:
    """HSM Equation 10-20, roadside design.

        CMF10r = e^(-0.6869 + 0.0668 x RHR) / e^(-0.4865)

    Base RHR = 3 on a 1 (best) to 7 (worst) scale. Since
    ln(CMF) = 0.0668 x (RHR - 3), the coefficient is exact.
    """
    coefficient = 0.0668
    cmf_at_4 = math.exp(-0.6869 + coefficient * 4) / math.exp(-0.4865)
    assert abs(cmf_at_4 - 1.07) < 0.005, cmf_at_4

    return Derivation(
        factor="roadside_hazard_score",
        transform="identity",
        value=coefficient,
        family="hsm",
        facility_type="rural_two_lane",
        region="north_america",
        source=(
            f"AASHTO HSM Eq. 10-20 (roadside design), rural two-lane two-way segments; "
            f"RHR scale of Zegeer et al., CMF from Harwood et al. Already log-linear, "
            f"so the weight is exact. {HSM_SOURCE_NOTE} (RHR 4 -> 1.07)."
        ),
        assumptions=(
            "Column must be scored on the HSM roadside hazard rating scale 1-7, base 3."
        ),
    )


def hsm_lighting() -> Derivation:
    """HSM Equation 10-21 with Table 10-12 defaults for roadway type 2U.

        CMF11r = 1.0 - [(1.0 - 0.72 x p_inr - 0.83 x p_pnr) x p_nr]
    """
    p_injury_night, p_pdo_night, p_night = 0.382, 0.618, 0.370
    cmf = 1.0 - ((1.0 - 0.72 * p_injury_night - 0.83 * p_pdo_night) * p_night)

    return Derivation(
        factor="lit",
        transform="identity",
        value=math.log(cmf),
        family="hsm",
        facility_type="rural_two_lane",
        region="north_america",
        source=(
            f"AASHTO HSM Eq. 10-21 with Table 10-12 defaults for roadway type 2U "
            f"(p_inr=0.382, p_pnr=0.618, p_nr=0.370); underlying research Elvik and "
            f"Vaa. Fully lit segment CMF = {cmf:.4f}, weight = ln(CMF), exact. "
            f"{HSM_SOURCE_NOTE}."
        ),
        assumptions=(
            "Column is the proportion of segment lit, 0 to 1. Table 10-12 night-crash "
            "proportions are Washington State HSIS data 2002-2006 and should be "
            "replaced with local values where they exist."
        ),
    )


GRADE_HSM_MIDPOINTS = np.array([1.5, 4.5, 7.5])
GRADE_HSM_CMFS = np.array([1.00, 1.10, 1.16])


def hsm_grade() -> Derivation:
    """HSM Table 10-11: 1.00 / 1.10 / 1.16 for <=3%, 3-6%, >6%."""
    coefficient, r_squared = _fit_log_linear(
        np.log1p(GRADE_HSM_MIDPOINTS), np.log(GRADE_HSM_CMFS)
    )
    return Derivation(
        factor="grade_pct",
        transform="ln1p",
        value=coefficient,
        family="hsm",
        facility_type="rural_two_lane",
        region="north_america",
        fit_r2=r_squared,
        source=(
            f"AASHTO HSM Table 10-11 (grades), rural two-lane two-way segments: "
            f"1.00 / 1.10 / 1.16 for <=3%, 3-6%, >6%. Log-linearised against ln1p at "
            f"band midpoints 1.5 / 4.5 / 7.5 percent. {HSM_SOURCE_NOTE}."
        ),
        assumptions=(
            "Column must be ABSOLUTE grade in percent; the HSM table does not "
            "distinguish upgrade from downgrade. R2 is computed on three points and is "
            "not evidence of anything — the source table is."
        ),
    )


CURVE_SEGMENT_LENGTH_KM = 0.5
CURVE_RADII_M = np.array([50.0, 100.0, 200.0, 400.0, 800.0, 1600.0])


def hsm_curve_radius() -> Derivation:
    """HSM Equation 10-13, horizontal curves.

        CMF3r = (1.55 x Lc + 80.2/R - 0.012 x S) / (1.55 x Lc)
    """
    length_miles = CURVE_SEGMENT_LENGTH_KM * MILES_PER_KM
    radii_feet = CURVE_RADII_M * FEET_PER_METRE
    cmf = (1.55 * length_miles + 80.2 / radii_feet) / (1.55 * length_miles)
    coefficient, r_squared = _fit_log_linear(np.log(CURVE_RADII_M), np.log(cmf))

    return Derivation(
        factor="curve_radius_min",
        transform="ln",
        value=coefficient,
        family="hsm",
        facility_type="rural_two_lane",
        region="north_america",
        fit_r2=r_squared,
        assumes={"segment_length_km": CURVE_SEGMENT_LENGTH_KM},
        source=(
            f"AASHTO HSM Eq. 10-13 (horizontal curves), rural two-lane two-way "
            f"segments; regression model of Zegeer et al. Log-linearised against ln "
            f"over radii 50-1600 m. {HSM_SOURCE_NOTE} "
            f"(0.1 mi / 1200 ft -> 1.43)."
        ),
        assumptions=(
            f"Segment length {CURVE_SEGMENT_LENGTH_KM} km assumed FULLY curved, no "
            "spiral transition. Column must be radius in METRES. The adapter must cap "
            "radius on tangent sections."
        ),
        caveat=(
            "Weakest linearisation in the registry. A 1 + c/R relationship is only "
            "roughly log-linear, so this weight under-weights very tight curves."
        ),
    )


ACCESS_REFERENCE_AADT = 10_000.0
ACCESS_DENSITIES_PER_KM = np.array([3.11, 6.0, 10.0, 15.0, 20.0])


def hsm_access_density() -> Derivation:
    """HSM Equation 10-17, driveway density.

        CMF6r = [0.322 + DD x k] / [0.322 + 5 x k],  k = 0.05 - 0.005 x ln(AADT)
    """
    per_mile = ACCESS_DENSITIES_PER_KM / MILES_PER_KM
    slope = 0.05 - 0.005 * math.log(ACCESS_REFERENCE_AADT)
    cmf = np.maximum((0.322 + per_mile * slope) / (0.322 + 5 * slope), 1.0)
    coefficient, r_squared = _fit_log_linear(
        np.log1p(ACCESS_DENSITIES_PER_KM), np.log(cmf)
    )

    return Derivation(
        factor="access_density",
        transform="ln1p",
        value=coefficient,
        family="hsm",
        facility_type="rural_two_lane",
        region="north_america",
        fit_r2=r_squared,
        assumes={"reference_aadt": ACCESS_REFERENCE_AADT},
        source=(
            f"AASHTO HSM Eq. 10-17 (driveway density), rural two-lane two-way "
            f"segments; derived from Muskaug. Log-linearised against ln1p over 3-20 "
            f"accesses/km at a reference AADT of {ACCESS_REFERENCE_AADT:,.0f}, the "
            f"value in the HSM's own worked example. {HSM_SOURCE_NOTE} "
            f"(DD 6 @ AADT 10,000 -> 1.01)."
        ),
        assumptions=(
            "Column must be accesses per KM counting both sides; the mile conversion "
            "is inside the weight. Base condition is 5 driveways/mile, below which the "
            "HSM sets CMF = 1.00."
        ),
        caveat=(
            "The source CMF depends on AADT, which Mode B does not have. The reference "
            "AADT is an assumption, not a measurement, though the AADT term is weak — "
            "it enters only as 0.05 - 0.005 x ln(AADT)."
        ),
    )


# =============================================================================
# iRAP — global, cross-sectional by construction
# =============================================================================

GRADE_IRAP_MIDPOINTS = np.array([3.75, 8.75, 11.25])
GRADE_IRAP_FACTORS = np.array([1.0, 1.2, 1.7])


def irap_grade() -> Derivation:
    """iRAP Road Attribute Risk Factors: Grade.

        <7.5%    risk factor 1.0
        7.5-10%  risk factor 1.2
        >10%     risk factor 1.7

    Selection of these factors was based on limited data from US and Australian
    studies, and they apply to run-off, head-on and loss-of-control crashes for
    vehicle occupants, motorcyclists, pedestrians and bicyclists.
    """
    coefficient, r_squared = _fit_log_linear(
        np.log1p(GRADE_IRAP_MIDPOINTS), np.log(GRADE_IRAP_FACTORS)
    )
    return Derivation(
        factor="grade_pct",
        transform="ln1p",
        value=coefficient,
        family="irap",
        facility_type="any",
        region="global",
        scope="run_off_head_on",
        fit_r2=r_squared,
        source=(
            "iRAP Road Attribute Risk Factors: Grade — risk factors 1.0 / 1.2 / 1.7 "
            "for <7.5%, 7.5-10%, >10%. Log-linearised against ln1p at band midpoints "
            "3.75 / 8.75 / 11.25 percent."
        ),
        assumptions=(
            "Column must be ABSOLUTE grade in percent. iRAP states these factors apply "
            "to run-off, head-on and loss-of-control crashes, not to total crashes — "
            "the declared scope reflects that, and the engine will not compute a "
            "like-for-like agreement score against a total-crash weight."
        ),
        caveat=(
            "iRAP notes the factors were selected from limited data relating crash "
            "rates to grade. Bands are much wider than the HSM's and the resulting "
            "weight is several times larger; the two are not measuring the same thing."
        ),
    )


# =============================================================================
# Elvik Power Model — speed, severity-specific
# =============================================================================

POWER_MODEL_EXPONENTS = {"injury": 1.6, "fatal": 4.1}

_POWER_SOURCE = (
    "Elvik (2009), Power Model, TOI Report 1034/2009 — exponent {exponent} for "
    "{label} on rural roads and freeways, as reproduced in FHWA-HRT-17-098 Chapter 2, "
    "Table 1. The Power form N proportional to V^k gives beta = k directly under a ln "
    "transform, so the weight is exact rather than fitted."
)

_POSTED_CAVEAT = (
    "UPPER BOUND. The Power Model relates MEAN OPERATING SPEED to crashes; this column "
    "is POSTED limit. Posted moves operating speed by materially less than 1:1, so this "
    "overstates the term and inflates it relative to the others. Deflating it would "
    "require a transfer coefficient nobody has published for cross-sectional ranking, "
    "so the weight is left intact and the limitation is declared instead. Use "
    "operating_speed_85 wherever measured speed exists."
)


def _power_model(factor: str, severity: str, caveat: str | None) -> Derivation:
    label = "all injury accidents" if severity == "injury" else "fatal accidents"
    exponent = POWER_MODEL_EXPONENTS[severity]
    return Derivation(
        factor=factor,
        transform="ln",
        value=exponent,
        family="elvik",
        facility_type="any",
        region="global",
        severity=severity,
        source=_POWER_SOURCE.format(exponent=exponent, label=label),
        assumptions=(
            "Severity-specific by construction. The engine will not apply the fatal "
            "exponent to an injury panel or the reverse — that is a factor-of-two "
            "error, not a nuance."
        ),
        caveat=caveat,
    )


def speed_limit_injury() -> Derivation:
    return _power_model("speed_limit", "injury", _POSTED_CAVEAT)


def speed_limit_fatal() -> Derivation:
    return _power_model("speed_limit", "fatal", _POSTED_CAVEAT)


def operating_speed_injury() -> Derivation:
    return _power_model("operating_speed_85", "injury", None)


def operating_speed_fatal() -> Derivation:
    return _power_model("operating_speed_85", "fatal", None)


DERIVATIONS = (
    hsm_roadside_hazard,
    hsm_lighting,
    hsm_grade,
    hsm_curve_radius,
    hsm_access_density,
    irap_grade,
    speed_limit_injury,
    speed_limit_fatal,
    operating_speed_injury,
    operating_speed_fatal,
)


def main() -> None:
    results = [derive() for derive in DERIVATIONS]

    if "--yaml" in sys.argv:
        by_factor: dict[str, list[Derivation]] = {}
        for result in results:
            by_factor.setdefault(result.factor, []).append(result)
        for factor, derivations in sorted(by_factor.items()):
            print(f"# {factor}")
            print("    weights:")
            for derivation in derivations:
                print(derivation.as_yaml())
            print()
        return

    print("Mode B registry weights, derived from published sources")
    print("=" * 78)
    print()
    for result in results:
        print(result.report())

    print("=" * 78)
    print(f"{len(results)} weights across {len({r.factor for r in results})} factors.")


if __name__ == "__main__":
    main()
