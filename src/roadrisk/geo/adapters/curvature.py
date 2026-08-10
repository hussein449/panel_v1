"""Tier A adapter — horizontal alignment, from the centreline alone.

The computation lives in :mod:`roadrisk.geo.geometry`, which predates the adapter
contract; this module is the thin layer that gives its two columns a source, a tier and
a licence so they travel through the pipeline like every other factor.

**Which registry slot this fills depends on where the centreline came from**, not on
what the code does. The same circumradius arithmetic is Tier A ODbL when the line is an
OSM export and Tier D client-licensed when the client supplied their own alignment. The
caller knows which; this module will not guess, it only defaults to the one the CLI
tells people to use.
"""

from __future__ import annotations

from roadrisk.core.registry import Registry
from roadrisk.geo.adapters.base import AdapterResult, resolve
from roadrisk.geo.geometry import (
    CURVE_DENSITY_COLUMN,
    CURVE_RADIUS_COLUMN,
    CurvatureResult,
)
from roadrisk.geo.segmentation import Segmentation

#: Registry slot for a centreline traced by OSM mappers. The default because
#: ``roadrisk centreline-help`` tells users to export the road from OSM.
OSM_GEOMETRY_ADAPTER = "osm_geometry"

#: Registry slot for a centreline the client supplied — a design alignment, a survey,
#: or a GIS layer of their own. Same arithmetic, different tier and licence.
CLIENT_ALIGNMENT_ADAPTER = "client_alignment"

_FACTORS = {
    "curve_radius_min": CURVE_RADIUS_COLUMN,
    "curve_density": CURVE_DENSITY_COLUMN,
}


def curvature_adapter(
    curvature: CurvatureResult,
    segmentation: Segmentation,
    *,
    registry: Registry,
    adapter: str = OSM_GEOMETRY_ADAPTER,
) -> AdapterResult:
    """Wrap a computed :class:`CurvatureResult` in the adapter contract.

    Args:
        curvature: Output of :func:`roadrisk.geo.geometry.compute_curvature`.
        segmentation: The units it was computed over, used to check nothing is missing.
        registry: Supplies the tier and licence for ``adapter``.
        adapter: Registry adapter slot this centreline fills.

    Returns:
        An :class:`AdapterResult` carrying ``curve_radius_min`` and ``curve_density``.
    """
    values = curvature.values.set_index("unit_id")
    expected = set(segmentation.unit_ids)
    if set(values.index) != expected:
        missing = sorted(expected - set(values.index))[:5]
        raise ValueError(
            f"curvature covers {len(values)} of {len(expected)} units; first missing: "
            f"{missing}"
        )

    source = (
        f"Circumradius of the centreline resampled to "
        f"{curvature.resample_interval_m:.0f} m spacing "
        f"({curvature.n_samples:,} samples); a curve is a run of samples below "
        f"{curvature.curve_threshold_m:.0f} m radius, the iRAP straight/moderate "
        f"boundary. Straights capped at {curvature.max_radius_m:.0f} m. "
        "Pure computation — no external data."
    )

    # The under-sampling warning belongs to both columns: it is a property of the line,
    # not of either measurement, and a reader looking at one number must see it.
    notes = tuple(curvature.notes)

    return AdapterResult(
        name="curvature",
        resolved=[
            resolve(
                registry,
                factor,
                adapter,
                source=source,
                values=values[column].astype(float),
                coverage=1.0,
                notes=notes,
            )
            for factor, column in _FACTORS.items()
        ],
    )


__all__ = [
    "CLIENT_ALIGNMENT_ADAPTER",
    "OSM_GEOMETRY_ADAPTER",
    "curvature_adapter",
]
