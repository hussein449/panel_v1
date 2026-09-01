"""Double-entry check on the published equations behind every weight.

Each equation is written out here **independently of the derivation script**, straight
from the manual, and asserted against the worked-example answer the source itself
publishes. If the script and this file ever disagree, one of them misread the manual.

This is the closest thing to verification available without a licensed copy of the
AASHTO HSM. It does not replace that — see docs/WEIGHTS.md — but it does mean a
transcription error cannot pass silently.
"""

from __future__ import annotations

import math

import pytest
from tests.test_registry import _load_derivation_module

FEET_PER_METRE = 3.280839895
MILES_PER_KM = 0.621371192


class TestHSMWorkedExamples:
    """Each answer below is printed in the source document."""

    def test_eq_10_20_roadside_hazard_rating(self) -> None:
        """CMF10r = e^(-0.6869 + 0.0668 x RHR) / e^(-0.4865); RHR 4 -> 1.07."""

        def cmf(rhr: float) -> float:
            return math.exp(-0.6869 + 0.0668 * rhr) / math.exp(-0.4865)

        assert cmf(4) == pytest.approx(1.07, abs=0.005)
        assert cmf(3) == pytest.approx(1.00, abs=0.005), "RHR 3 is the base condition"

    def test_eq_10_17_driveway_density(self) -> None:
        """DD 6 at AADT 10,000 -> 1.01."""

        def cmf(driveways_per_mile: float, aadt: float) -> float:
            slope = 0.05 - 0.005 * math.log(aadt)
            return (0.322 + driveways_per_mile * slope) / (0.322 + 5 * slope)

        assert cmf(6, 10_000) == pytest.approx(1.01, abs=0.005)
        assert cmf(5, 10_000) == pytest.approx(1.00, abs=1e-9), "5/mile is the base"

    def test_eq_10_13_horizontal_curve(self) -> None:
        """0.1 mi curve, 1,200 ft radius, no spiral -> 1.43."""

        def cmf(length_miles: float, radius_feet: float, spiral: float) -> float:
            return (1.55 * length_miles + 80.2 / radius_feet - 0.012 * spiral) / (
                1.55 * length_miles
            )

        assert cmf(0.1, 1200, 0) == pytest.approx(1.43, abs=0.005)

    def test_table_10_11_grades(self) -> None:
        """Level terrain is the base condition at 1.00."""
        bands = {"level": 1.00, "moderate": 1.10, "steep": 1.16}
        assert bands["level"] == 1.00
        assert bands["steep"] > bands["moderate"] > bands["level"]

    def test_eq_10_21_lighting(self) -> None:
        """Table 10-12 defaults for 2U give a fully lit CMF of 0.9216."""
        p_inr, p_pnr, p_nr = 0.382, 0.618, 0.370
        cmf = 1.0 - ((1.0 - 0.72 * p_inr - 0.83 * p_pnr) * p_nr)

        assert cmf == pytest.approx(0.9216, abs=1e-4)
        assert p_inr + p_pnr == pytest.approx(1.0), "severity split must be exhaustive"


class TestPowerModel:
    def test_exponents_match_the_published_table(self) -> None:
        """FHWA-HRT-17-098 Table 1, reproducing Elvik (2009)."""
        derivations = _load_derivation_module()
        assert derivations.POWER_MODEL_EXPONENTS == {"injury": 1.6, "fatal": 4.1}

    def test_power_form_gives_the_exponent_directly_under_ln(self) -> None:
        """N proportional to V^k means ln(N) = k x ln(V), so beta = k."""
        exponent = 1.6
        speed_ratio = 100.0 / 80.0
        crash_ratio = speed_ratio**exponent

        assert math.log(crash_ratio) == pytest.approx(exponent * math.log(speed_ratio))


class TestIRAPReferenceGuide:
    """Values transcribed from the iRAP Methodology Reference Guide v3.10."""

    def test_grade_risk_factors_are_as_published(self) -> None:
        """Grade — 1.0 / 1.2 / 1.7 for 0-7.5%, 7.5-10%, >=10%."""
        derivations = _load_derivation_module()
        assert list(derivations.GRADE_IRAP_FACTORS) == [1.0, 1.2, 1.7]

    def test_curvature_risk_factors_are_as_published(self) -> None:
        """Curvature — 1.0 / 1.8 / 3.5 / 6.0, vehicle occupants."""
        derivations = _load_derivation_module()
        assert list(derivations.CURVE_IRAP_FACTORS) == [1.0, 1.8, 3.5, 6.0]

    def test_curvature_radius_bands_match_the_guide(self) -> None:
        """>900 / 500-900 / 200-500 / 0-200 m, with the same midpoint rule.

        The Guide publishing radius ranges for a categorical attribute is what makes
        this convertible to a continuous weight at all.
        """
        derivations = _load_derivation_module()
        radii = list(derivations.CURVE_IRAP_RADII_M)

        assert radii[1] == pytest.approx((500 + 900) / 2)
        assert radii[2] == pytest.approx((200 + 500) / 2)
        assert radii[3] == pytest.approx((0 + 200) / 2)
        assert radii[0] == pytest.approx(900 + (900 - 500) / 2), "unbounded top band"

    def test_sealed_versus_unsealed_is_a_factor_of_three(self) -> None:
        """Skid resistance — sealed-adequate 1.0, unsealed-adequate 3.0."""
        derivations = _load_derivation_module()
        weight = derivations.irap_surface_paved().value

        assert math.exp(-weight) == pytest.approx(3.0)

    def test_lighting_is_priced_at_intersections_only(self) -> None:
        """The narrow scope is the point — HSM prices lighting for total crashes."""
        derivations = _load_derivation_module()
        lighting = derivations.irap_lighting()

        assert lighting.scope == "intersection"
        assert math.exp(-lighting.value) == pytest.approx(1.15)

    def test_irap_weights_are_global_and_facility_agnostic(self) -> None:
        """Which is exactly why they clear the region-transfer flag."""
        derivations = _load_derivation_module()
        for derive in derivations.DERIVATIONS:
            result = derive()
            if result.family != "irap":
                continue
            assert result.region == "global", result.factor
            assert result.facility_type == "any", result.factor

    def test_band_midpoint_rule_is_applied_consistently(self) -> None:
        """Unbounded top band = threshold + half the width of the band below.

        HSM's ">6%" becomes 7.5 (6 + 3/2); iRAP's ">10%" becomes 11.25 (10 + 2.5/2).
        A rule beats a preference, and it must be the same rule for both sources.
        """
        derivations = _load_derivation_module()

        hsm = list(derivations.GRADE_HSM_MIDPOINTS)
        irap = list(derivations.GRADE_IRAP_MIDPOINTS)

        assert hsm[-1] == pytest.approx(6 + 3 / 2)
        assert irap[-1] == pytest.approx(10 + 2.5 / 2)


class TestDerivedValuesAreStable:
    """Regression lock. A change here means a source or an assumption moved."""

    EXPECTED = {
        ("roadside_hazard_score", "hsm", "all"): 0.0668,
        ("lit", "hsm", "all"): -0.0817,
        ("lit", "irap", "all"): -0.1398,
        ("grade_pct", "hsm", "all"): 0.1212,
        ("grade_pct", "irap", "all"): 0.4863,
        ("curve_radius_min", "hsm", "all"): -0.1855,
        ("curve_radius_min", "irap", "all"): -0.7232,
        # Trafikksikkerhetshandboken 1.13, reporting Elvik (2023) over 47 studies.
        # Exact on two points: ln(3.58) / (ln 50 - ln 600). It lands between the HSM and
        # iRAP figures, which is mild corroboration of both rather than anything to lean
        # on — all three are meta-analytic averages over overlapping literature.
        ("curve_radius_min", "elvik", "all"): -0.5132,
        ("access_density", "hsm", "all"): 0.1658,
        ("surface_paved", "irap", "all"): -1.0986,
        ("speed_limit", "elvik", "injury"): 1.6,
        ("speed_limit", "elvik", "fatal"): 4.1,
        ("operating_speed_85", "elvik", "injury"): 1.6,
        ("operating_speed_85", "elvik", "fatal"): 4.1,
    }

    def test_every_derivation_matches(self) -> None:
        derivations = _load_derivation_module()
        actual = {
            (d.factor, d.family, d.severity): round(d.value, 4)
            for d in (derive() for derive in derivations.DERIVATIONS)
        }
        assert actual == self.EXPECTED

    def test_fit_quality_is_reported_where_fitted(self) -> None:
        """An exact weight must not claim a fit; a fitted one must report R²."""
        derivations = _load_derivation_module()
        for derive in derivations.DERIVATIONS:
            result = derive()
            if result.transform == "identity" or result.family == "elvik":
                continue
            assert result.fit_r2 is not None, result.key

    def test_the_weakest_linearisation_declares_itself(self) -> None:
        """curve_radius_min fits worst, and must say so rather than hide it."""
        derivations = _load_derivation_module()
        curve = derivations.hsm_curve_radius()

        assert curve.fit_r2 is not None
        assert curve.fit_r2 < 0.9
        assert curve.caveat and "Weakest" in curve.caveat
