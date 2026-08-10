"""Geospatial pipeline — turns geography into the panel the engine assesses.

    centreline → corridor → segment → skeleton → snap crashes → factor values → panel

**Layering.** ``geo`` imports ``core``; ``core`` never imports ``geo``. That is why the
geospatial dependencies are an optional extra: the method stays testable, and the
engine stays runnable, without any of this installed.

Install with::

    pip install "roadrisk-panel[geo]"
"""

from __future__ import annotations

try:
    import pyproj as _pyproj  # noqa: F401
    import shapely as _shapely  # noqa: F401
except ModuleNotFoundError as exc:  # pragma: no cover - import-time guard
    raise ModuleNotFoundError(
        "roadrisk.geo needs the geospatial extra, which is deliberately not a core "
        'dependency. Install it with:  pip install "roadrisk-panel[geo]"'
    ) from exc

from roadrisk.geo.corridor import Corridor
from roadrisk.geo.crs import Projector, utm_epsg_for
from roadrisk.geo.errors import (
    CorridorError,
    GeoError,
    SegmentationError,
    SnapError,
)
from roadrisk.geo.geometry import CurvatureResult, compute_curvature
from roadrisk.geo.panel import attach_factor_values, build_skeleton
from roadrisk.geo.pipeline import CorridorPanel, build_corridor_panel
from roadrisk.geo.segmentation import Segmentation, Unit, segment
from roadrisk.geo.snapping import SnapOutcome, apply_counts, snap_crashes

__all__ = [
    "Corridor",
    "CorridorError",
    "CorridorPanel",
    "CurvatureResult",
    "GeoError",
    "Projector",
    "Segmentation",
    "SegmentationError",
    "SnapError",
    "SnapOutcome",
    "Unit",
    "apply_counts",
    "attach_factor_values",
    "build_corridor_panel",
    "build_skeleton",
    "compute_curvature",
    "segment",
    "snap_crashes",
    "utm_epsg_for",
]
