"""Synthetic corridors, for tests and demonstration.

Like :mod:`roadrisk.demo`, this fabricates data and therefore sits outside the
assessment path. It exists so the geometry pipeline can be exercised end to end without
a real centreline, and so curvature can be tested against a shape whose bends are known
by construction.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from roadrisk.geo.crs import Projector

#: Somewhere in the eastern Mediterranean — inside a single UTM zone, and in the
#: product's actual target region rather than a US test fixture.
DEFAULT_ORIGIN = (34.90, 33.20)


def synthetic_centreline(
    *,
    origin: tuple[float, float] = DEFAULT_ORIGIN,
    length_km: float = 10.0,
    bends: int = 6,
    amplitude_m: float = 250.0,
    spacing_m: float = 10.0,
) -> list[tuple[float, float]]:
    """A sinuous centreline with known, varying curvature.

    The path is a sine wave whose amplitude grows along its length, so the first bends
    are gentle and the last are tight. That gives curvature something real to find and
    makes an ordering the tests can assert.

    Returns:
        Ordered (latitude, longitude) vertices.
    """
    projector = Projector.for_point(*origin)
    easting, northing = projector.point_to_metric(*origin)

    total_m = length_km * 1000.0
    along = np.arange(0.0, total_m + spacing_m, spacing_m)

    # Amplitude ramps from 20% to 100% so bends tighten towards the far end.
    ramp = 0.2 + 0.8 * (along / total_m)
    offset = amplitude_m * ramp * np.sin(2.0 * np.pi * bends * along / total_m)

    return [
        projector.point_to_wgs84(easting + float(x), northing + float(y))
        for x, y in zip(along, offset, strict=True)
    ]


def synthetic_crashes(
    centreline: list[tuple[float, float]],
    periods: list[str],
    *,
    n_crashes: int = 400,
    seed: int = 5,
    off_corridor_fraction: float = 0.08,
    missing_coordinate_fraction: float = 0.03,
    unknown_period_fraction: float = 0.04,
) -> pd.DataFrame:
    """A crash table with the defects a real police extract has.

    Deliberately imperfect: some crashes are geocoded off the road, some have no
    coordinates, some carry a period the panel does not cover. Snapping has to find and
    report all three, and a fixture where everything snaps would prove nothing.
    """
    rng = np.random.default_rng(seed)
    projector = Projector.for_point(*centreline[0])

    metric = np.array([projector.point_to_metric(lat, lon) for lat, lon in centreline])
    n_vertices = len(metric)

    rows: list[dict[str, object]] = []
    for _ in range(n_crashes):
        index = int(rng.integers(0, n_vertices))
        x, y = metric[index]

        roll = rng.random()
        if roll < off_corridor_fraction:
            # Geocoded to a parallel street, or the wrong road entirely.
            x += rng.normal(0.0, 1.0) * 400.0
            y += rng.normal(0.0, 1.0) * 400.0
        else:
            # Ordinary GPS scatter about the centreline.
            x += rng.normal(0.0, 8.0)
            y += rng.normal(0.0, 8.0)

        latitude, longitude = projector.point_to_wgs84(x, y)

        if rng.random() < missing_coordinate_fraction:
            latitude, longitude = np.nan, np.nan

        outside_panel = rng.random() < unknown_period_fraction
        period = "1999-01" if outside_panel else str(rng.choice(periods))

        rows.append(
            {"latitude": latitude, "longitude": longitude, "period": period}
        )

    return pd.DataFrame(rows)


def monthly_periods(n: int, *, start_year: int = 2024) -> list[str]:
    """Unique ``YYYY-MM`` labels, carrying the year so they never repeat."""
    return [
        f"{start_year + month // 12}-{month % 12 + 1:02d}" for month in range(n)
    ]


__all__ = [
    "DEFAULT_ORIGIN",
    "monthly_periods",
    "synthetic_centreline",
    "synthetic_crashes",
]
