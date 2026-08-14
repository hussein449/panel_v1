"""Synthetic corridor panels, for tests and for demonstrating the engine.

This is not part of ``core`` — it fabricates data, and nothing that fabricates data
belongs in the assessment path. It exists so the engine can be exercised end to end
without a corridor, and so the sign guard can be tested against a *known* truth: if a
coefficient is planted positive and comes back negative, that is a bug in the engine
rather than a finding about a road.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Coefficients on the transformed scale. Every one agrees with the expected_sign
# declared in the shipped registry, so a clean run should raise no sign flags.
TRUE_EFFECTS: dict[str, float] = {
    "curve_density": 0.25,
    "junction_density": 0.30,
    "access_density": 0.20,
    "speed_limit": 0.90,
    "grade_pct": 0.15,
    "lanes": 0.35,
    "poi_density": 0.18,
    "lit": -0.25,
}

_TRANSFORMS: dict[str, str] = {
    "curve_density": "ln1p",
    "junction_density": "ln1p",
    "access_density": "ln1p",
    "speed_limit": "ln",
    "grade_pct": "ln1p",
    "lanes": "ln",
    "poi_density": "ln1p",
    "lit": "identity",
}


def synthetic_panel(
    *,
    n_units: int = 120,
    n_periods: int = 24,
    n_time_slots: int = 2,
    seed: int = 7,
    intercept: float = -5.5,
    alpha: float = 0.6,
    effects: dict[str, float] | None = None,
    segment_length_km: float = 0.5,
    unit_dispersion: float = 0.5,
    crash_rows_only: bool = False,
) -> pd.DataFrame:
    """Build a panel with known coefficients.

    Args:
        n_units: Number of corridor segments.
        n_periods: Number of periods (months).
        n_time_slots: Time slots within each period.
        seed: RNG seed. The same seed always produces the same panel.
        intercept: Log baseline rate per km-hour. Controls how sparse the counts are.
        alpha: NB2 dispersion. Variance is ``mu + alpha * mu^2``.
        effects: Override the true coefficients. Defaults to :data:`TRUE_EFFECTS`.
        segment_length_km: Length of every unit.
        unit_dispersion: Standard deviation of a per-unit random effect on the log
            rate, held constant across every period of that unit.

            Real segments carry unobserved persistent traits — a bad junction layout, a
            school, poor drainage — so repeated observations of one segment are
            correlated. This panel drew its overdispersion per *row* until rung 2 was
            built, which made every observation independent and let every model fitted
            to it look better than it would on a road. Set to zero to get that back.
        crash_rows_only: Drop the zero-crash rows, producing a panel that Mode A must
            refuse. Used to exercise check 1.

    Returns:
        A contract-valid panel, unless ``crash_rows_only`` is set.
    """
    rng = np.random.default_rng(seed)
    betas = dict(TRUE_EFFECTS if effects is None else effects)

    unit_ids = [f"U{index:04d}" for index in range(n_units)]
    unit_factors = _unit_factors(rng, n_units)

    periods = [
        f"{2024 + month // 12}-{month % 12 + 1:02d}" for month in range(n_periods)
    ]
    slots = [f"slot{index + 1}" for index in range(n_time_slots)]
    hours_per_cell = (365.25 * 24 / 12) / n_time_slots

    index = pd.MultiIndex.from_product(
        [unit_ids, periods, slots], names=["unit_id", "period", "time_slot"]
    )
    panel = pd.DataFrame(index=index).reset_index()

    for column, values in unit_factors.items():
        panel[column] = panel["unit_id"].map(dict(zip(unit_ids, values, strict=True)))

    panel["length_km"] = segment_length_km
    panel["duration_hours"] = hours_per_cell

    exposure = panel["length_km"] * panel["duration_hours"]
    linear = np.full(len(panel), float(intercept))
    for name, beta in betas.items():
        if name not in panel.columns:
            continue
        transformed = _transform(panel[name].to_numpy(dtype=float), _TRANSFORMS[name])
        linear = linear + beta * (transformed - transformed.mean())

    if unit_dispersion > 0:
        # Mapped by unit id rather than repeated positionally, so the effect stays with
        # its segment however the frame is later ordered.
        heterogeneity = dict(
            zip(unit_ids, rng.normal(0.0, unit_dispersion, n_units), strict=True)
        )
        linear = linear + panel["unit_id"].map(heterogeneity).to_numpy(dtype=float)

    mu = exposure.to_numpy(dtype=float) * np.exp(linear)
    panel["n_crashes"] = _negative_binomial(rng, mu, alpha)

    if crash_rows_only:
        panel = panel.loc[panel["n_crashes"] > 0].reset_index(drop=True)

    ordered = [
        "unit_id",
        "period",
        "time_slot",
        "n_crashes",
        "length_km",
        "duration_hours",
        *unit_factors.keys(),
    ]
    return panel[ordered]


def _unit_factors(rng: np.random.Generator, n_units: int) -> dict[str, np.ndarray]:
    """Unit-constant covariates, on their natural scales."""
    return {
        "curve_density": rng.gamma(shape=2.0, scale=1.2, size=n_units),
        "junction_density": rng.gamma(shape=1.5, scale=1.0, size=n_units),
        "access_density": rng.gamma(shape=2.5, scale=1.6, size=n_units),
        "speed_limit": rng.choice([50.0, 60.0, 80.0, 100.0, 120.0], size=n_units),
        "grade_pct": np.abs(rng.normal(loc=2.0, scale=1.5, size=n_units)),
        "lanes": rng.choice([1.0, 2.0, 3.0], size=n_units, p=[0.3, 0.5, 0.2]),
        "poi_density": rng.gamma(shape=2.0, scale=2.5, size=n_units),
        "lit": rng.uniform(0.0, 1.0, size=n_units),
    }


def _transform(values: np.ndarray, kind: str) -> np.ndarray:
    if kind == "ln":
        return np.log(values)
    if kind == "ln1p":
        return np.log1p(values)
    return values


def _negative_binomial(
    rng: np.random.Generator, mu: np.ndarray, alpha: float
) -> np.ndarray:
    """Draw NB2 counts with mean ``mu`` and variance ``mu + alpha * mu^2``."""
    if alpha <= 0:
        return rng.poisson(mu)
    size = 1.0 / alpha
    probability = size / (size + mu)
    return rng.negative_binomial(size, probability)


__all__ = ["TRUE_EFFECTS", "synthetic_panel"]
