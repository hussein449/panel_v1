"""Derive Mode B registry weights from published crash modification factors.

Run this to regenerate every sourced `default_weight` in the factor registry:

    python tools/derive_weights.py

Nothing here is a number I chose. Each weight is computed from a published equation
reproduced verbatim below, and the assumptions needed to get from that equation to a
registry weight are named as constants at the top of each function so they can be
argued with.

WHY A DERIVATION IS NEEDED AT ALL
---------------------------------
Published CMFs are *multipliers on a safety performance function that already contains
AADT*. The registry needs *log-scale coefficients on transformed columns*, because a
Mode B weight has to sit on the same scale as a Mode A coefficient — that is what makes
the two modes comparable, and what makes "Mode B is the prior, Mode A is the prior
updated by data" true rather than decorative.

The conversion is: a CMF of `c` corresponds to a log-scale contribution of `ln(c)`.
Where the CMF is already log-linear in the variable (roadside hazard rating), the
coefficient falls straight out. Where it is not, this script fits `ln(CMF)` against the
registry's declared transform by least squares over a stated range, and reports the
fit quality so a poor linearisation is visible rather than hidden.

THE TRANSFER PROBLEM — READ BEFORE TRUSTING ANY OF THIS
------------------------------------------------------
Every HSM CMF below was estimated on US rural two-lane two-way highways. The target
market for this tool is Lebanon, MENA, South Asia and much of Africa. Applying these
weights outside that facility type and that country is an extrapolation, and it is the
single largest source of error in Mode B. It is defensible only because Mode B is an
*ordinal ranking*, not a prediction — the ranking survives a common scaling error that
a predicted count would not.

This is exactly why the engine refuses to let Mode B emit a count.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

FEET_PER_METRE = 3.280839895
MILES_PER_KM = 0.621371192


@dataclass(frozen=True)
class Derivation:
    """One derived registry weight, with everything needed to audit it."""

    factor: str
    transform: str
    weight: float
    source: str
    assumptions: str
    r_squared: float | None = None

    def report(self) -> str:
        fit = "exact" if self.r_squared is None else f"R² = {self.r_squared:.4f}"
        return (
            f"{self.factor:<24} {self.transform:<10} {self.weight:+.4f}   ({fit})\n"
            f"    source      : {self.source}\n"
            f"    assumptions : {self.assumptions}\n"
        )


def _fit_log_linear(x: np.ndarray, log_cmf: np.ndarray) -> tuple[float, float]:
    """Least-squares slope of ln(CMF) on the transformed variable, plus R².

    An intercept is fitted and then discarded. Mode B is an ordinal ranking, so a
    constant shifts every unit equally and cannot change the order.
    """
    design = np.column_stack([np.ones_like(x), x])
    coefficients, *_ = np.linalg.lstsq(design, log_cmf, rcond=None)
    predicted = design @ coefficients
    residual_ss = float(((log_cmf - predicted) ** 2).sum())
    total_ss = float(((log_cmf - log_cmf.mean()) ** 2).sum())
    r_squared = 1.0 - residual_ss / total_ss if total_ss > 0 else 1.0
    return float(coefficients[1]), r_squared


# ---------------------------------------------------------------------------
# 1 · Roadside hazard rating — exact, no fitting required
# ---------------------------------------------------------------------------

def roadside_hazard() -> Derivation:
    """HSM Equation 10-20, roadside design.

        CMF10r = e^(-0.6869 + 0.0668 x RHR) / e^(-0.4865)

    Base condition RHR = 3, scale 1 (best) to 7 (worst). Since
    ln(CMF10r) = 0.0668 x (RHR - 3), the log-scale coefficient on RHR is exactly
    0.0668 and no linearisation is needed. This is the cleanest weight in the set.
    """
    coefficient = 0.0668

    # Verify against the HSM's own worked example: RHR = 4 gives CMF = 1.07.
    cmf_at_4 = math.exp(-0.6869 + coefficient * 4) / math.exp(-0.4865)
    assert abs(cmf_at_4 - 1.07) < 0.005, cmf_at_4

    return Derivation(
        factor="roadside_hazard_score",
        transform="identity",
        weight=coefficient,
        source=(
            "AASHTO HSM Eq. 10-20 (roadside design), rural two-lane two-way segments; "
            "RHR scale of Zegeer et al., CMF from Harwood et al."
        ),
        assumptions=(
            "Factor must be scored on the HSM roadside hazard rating scale 1-7, "
            "base 3. A vision model producing any other scale must be mapped onto "
            "RHR before this weight applies."
        ),
    )


# ---------------------------------------------------------------------------
# 2 · Lighting — exact
# ---------------------------------------------------------------------------

def lighting() -> Derivation:
    """HSM Equation 10-21 with Table 10-12 defaults for roadway type 2U.

        CMF11r = 1.0 - [(1.0 - 0.72 x p_inr - 0.83 x p_pnr) x p_nr]

    Table 10-12 (2U): p_inr = 0.382, p_pnr = 0.618, p_nr = 0.370.
    Underlying research is Elvik and Vaa.
    """
    p_injury_night = 0.382
    p_pdo_night = 0.618
    p_night = 0.370

    cmf = 1.0 - ((1.0 - 0.72 * p_injury_night - 0.83 * p_pdo_night) * p_night)

    return Derivation(
        factor="lit",
        transform="identity",
        weight=math.log(cmf),
        source=(
            "AASHTO HSM Eq. 10-21 with Table 10-12 defaults for roadway type 2U "
            "(p_inr=0.382, p_pnr=0.618, p_nr=0.370); underlying research Elvik and Vaa. "
            f"Fully lit segment CMF = {cmf:.4f}."
        ),
        assumptions=(
            "The column is the proportion of the segment that is lit, 0 to 1, so the "
            "weight scales linearly between unlit and fully lit. HSM Table 10-12 "
            "proportions are from Washington State HSIS data 2002-2006 and should be "
            "replaced with local night-crash proportions where they exist."
        ),
    )


# ---------------------------------------------------------------------------
# 3 · Speed limit — exact, from the Power Model
# ---------------------------------------------------------------------------

def speed_limit() -> Derivation:
    """Elvik (2009) Power Model, as reproduced by FHWA-HRT-17-098 Table 1.

        Injury accidents ∝ V^1.6      (rural roads and freeways)

    Taking logs gives ln(N) = 1.6 x ln(V), so with the registry's `ln` transform the
    coefficient is the exponent itself. Fatal accidents use 4.1 and all injured road
    users 2.2; 1.6 is the right one for a panel counting injury crashes.
    """
    exponent_injury_accidents = 1.6

    return Derivation(
        factor="speed_limit",
        transform="ln",
        weight=exponent_injury_accidents,
        source=(
            "Elvik (2009), Power Model, TOI Report 1034/2009, exponent 1.6 for all "
            "injury accidents on rural roads and freeways, as reproduced in "
            "FHWA-HRT-17-098 Chapter 2 Table 1. Power form N ∝ V^k gives beta = k "
            "directly under a ln transform."
        ),
        assumptions=(
            "UPPER BOUND, USE WITH CARE. The Power Model relates MEAN OPERATING SPEED "
            "to crashes. This column is POSTED speed limit. A change in posted limit "
            "moves operating speed by materially less than 1:1, so applying 1.6 to "
            "posted limit overstates the effect and inflates this term's weight "
            "relative to the others. Recalibrate against measured operating speed "
            "(Tier C) as soon as it is available. If the panel counts fatal crashes "
            "rather than injury crashes, the exponent is 4.1, not 1.6."
        ),
    )


# ---------------------------------------------------------------------------
# 4 · Grade — linearised from a three-band table
# ---------------------------------------------------------------------------

GRADE_BAND_MIDPOINTS = np.array([1.5, 4.5, 7.5])
GRADE_BAND_CMFS = np.array([1.00, 1.10, 1.16])


def grade() -> Derivation:
    """HSM Table 10-11, grades on rural two-lane two-way segments.

        level (grade <= 3%)          CMF = 1.00
        moderate (3% < grade <= 6%)  CMF = 1.10
        steep (grade > 6%)           CMF = 1.16

    A three-band step function is fitted onto the registry's ln1p transform. The
    top band is unbounded, so its midpoint is a choice, not a fact.
    """
    x = np.log1p(GRADE_BAND_MIDPOINTS)
    coefficient, r_squared = _fit_log_linear(x, np.log(GRADE_BAND_CMFS))

    return Derivation(
        factor="grade_pct",
        transform="ln1p",
        weight=coefficient,
        r_squared=r_squared,
        source=(
            "AASHTO HSM Table 10-11 (grades), rural two-lane two-way segments: "
            "1.00 / 1.10 / 1.16 for <=3%, 3-6%, >6%."
        ),
        assumptions=(
            "Bands represented by midpoints 1.5% / 4.5% / 7.5%. The steep band is "
            "unbounded above and 7.5% is a chosen representative value — a corridor "
            "with sustained grades well above 8% will be under-weighted. Column must "
            "be ABSOLUTE grade; the HSM table does not distinguish up from down."
        ),
    )


# ---------------------------------------------------------------------------
# 5 · Curve radius — linearised from the horizontal curve CMF
# ---------------------------------------------------------------------------

CURVE_SEGMENT_LENGTH_KM = 0.5
CURVE_RADII_M = np.array([50.0, 100.0, 200.0, 400.0, 800.0, 1600.0])


def curve_radius() -> Derivation:
    """HSM Equation 10-13, horizontal curves.

        CMF3r = (1.55 x Lc + 80.2/R - 0.012 x S) / (1.55 x Lc)

    Lc = curve length in miles, R = radius in feet, S = spiral indicator.
    """
    length_miles = CURVE_SEGMENT_LENGTH_KM * MILES_PER_KM
    spiral = 0.0  # No spiral transition — the conservative and commonest case.

    radii_feet = CURVE_RADII_M * FEET_PER_METRE
    cmf = (1.55 * length_miles + 80.2 / radii_feet - 0.012 * spiral) / (
        1.55 * length_miles
    )

    coefficient, r_squared = _fit_log_linear(np.log(CURVE_RADII_M), np.log(cmf))

    return Derivation(
        factor="curve_radius_min",
        transform="ln",
        weight=coefficient,
        r_squared=r_squared,
        source=(
            "AASHTO HSM Eq. 10-13 (horizontal curves), rural two-lane two-way "
            "segments; regression model of Zegeer et al."
        ),
        assumptions=(
            f"Segment length {CURVE_SEGMENT_LENGTH_KM} km assumed FULLY curved, no "
            "spiral transition. The CMF depends on curve length, so this weight is "
            "tied to the segmentation length — regenerate it if segmentation changes. "
            "Column must be radius in METRES. The adapter must cap radius on tangent "
            "sections; an uncapped infinity fails the ln transform by design."
        ),
    )


# ---------------------------------------------------------------------------
# 6 · Access density — linearised from the driveway density CMF
# ---------------------------------------------------------------------------

ACCESS_REFERENCE_AADT = 10_000.0
ACCESS_DENSITIES_PER_KM = np.array([3.11, 6.0, 10.0, 15.0, 20.0])


def access_density() -> Derivation:
    """HSM Equation 10-17, driveway density.

        CMF6r = [0.322 + DD x (0.05 - 0.005 x ln(AADT))]
              / [0.322 + 5  x (0.05 - 0.005 x ln(AADT))]

    DD = driveways per mile counting both sides. Base condition is 5 driveways per
    mile; below that the HSM sets CMF6r = 1.00.
    """
    per_mile = ACCESS_DENSITIES_PER_KM / MILES_PER_KM
    slope = 0.05 - 0.005 * math.log(ACCESS_REFERENCE_AADT)
    cmf = (0.322 + per_mile * slope) / (0.322 + 5 * slope)
    cmf = np.maximum(cmf, 1.0)  # HSM floor below 5 driveways/mile

    coefficient, r_squared = _fit_log_linear(
        np.log1p(ACCESS_DENSITIES_PER_KM), np.log(cmf)
    )

    return Derivation(
        factor="access_density",
        transform="ln1p",
        weight=coefficient,
        r_squared=r_squared,
        source=(
            "AASHTO HSM Eq. 10-17 (driveway density), rural two-lane two-way "
            "segments; derived from the work of Muskaug."
        ),
        assumptions=(
            f"THE CMF DEPENDS ON AADT, WHICH MODE B DOES NOT HAVE. Evaluated at a "
            f"reference AADT of {ACCESS_REFERENCE_AADT:,.0f} — the value used in the "
            "HSM's own worked example. The AADT term is weak (it enters as "
            "0.05 - 0.005 x ln(AADT)) but this is still an assumption, not a "
            "measurement. Column must be accesses per KM counting both sides."
        ),
    )


DERIVATIONS = (
    roadside_hazard,
    lighting,
    speed_limit,
    grade,
    curve_radius,
    access_density,
)


def main() -> None:
    print("Mode B registry weights, derived from published CMFs")
    print("=" * 72)
    print()
    results = [derive() for derive in DERIVATIONS]
    for result in results:
        print(result.report())

    print("=" * 72)
    print("YAML values for src/roadrisk/core/registry/factors.yaml:")
    print()
    for result in sorted(results, key=lambda r: r.factor):
        print(f"  {result.factor}: {result.weight:+.4f}")


if __name__ == "__main__":
    main()
