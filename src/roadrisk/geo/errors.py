"""Errors raised while turning geography into a panel.

All descend from :class:`roadrisk.core.errors.RoadRiskError`, so a caller can catch
one exception type across both layers. The dependency runs one way only — geo imports
core, never the reverse.
"""

from __future__ import annotations

from roadrisk.core.errors import RoadRiskError


class GeoError(RoadRiskError):
    """Base class for every geospatial failure."""


class CorridorError(GeoError):
    """The corridor geometry is unusable.

    Raised before any work is done on it. A corridor that cannot be linearly
    referenced cannot be segmented, and a panel built on a bad centreline is worse
    than no panel — every downstream number would be wrong but plausible.
    """


class SegmentationError(GeoError):
    """The corridor cannot be cut into the units requested."""


class SnapError(GeoError):
    """The crash table cannot be snapped as supplied."""


__all__ = ["CorridorError", "GeoError", "SegmentationError", "SnapError"]
