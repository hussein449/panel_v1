"""Source adapters — one factor, one source, one licence, one tier.

Part Six of the pipeline brief: *modularity is not just factors, it is source
adapters*. A factor declares an ordered chain of ways it can be obtained —
``client_data → Tier A/B → drop`` — and every value that reaches the panel says which
link of that chain produced it.

What is implemented, all Tier A and all free:

======================  ==========================  ============================
Factor                  Registry adapter            Module
======================  ==========================  ============================
``curve_radius_min``    ``osm_geometry``            :mod:`.curvature`
``curve_density``       ``osm_geometry``            :mod:`.curvature`
``speed_limit``         ``osm_maxspeed``            :mod:`.osm_tags`
``lanes``               ``osm_lanes``               :mod:`.osm_tags`
``lit``                 ``osm_lit``                 :mod:`.osm_tags`
``surface_paved``       ``osm_surface``             :mod:`.osm_tags`
``sidewalk_present``    ``osm_sidewalk``            :mod:`.osm_tags`
``median_present``      ``osm_divided``             :mod:`.osm_tags`
``junction_density``    ``osm_graph_nodes``         :mod:`.osm_density`
``access_density``      ``osm_service_driveway``    :mod:`.osm_density`
``ramp_density``        ``osm_link_ways``           :mod:`.osm_density`
``poi_density``         ``osm_poi``                 :mod:`.osm_density`
======================  ==========================  ============================

Still to come in 2.6: ``grade_pct`` from the Copernicus DEM, and the raster-backed
context factors — land cover, population density, building density. They share a
different problem from everything here (reading a cloud-optimised GeoTIFF rather than
parsing a tag) and land together.

Choosing between two adapters that both resolve the same factor, and scoring their
agreement where they overlap, is step 2.7. Until it exists, :func:`.base.unit_frame`
refuses a collision rather than silently preferring one.
"""

from __future__ import annotations

from roadrisk.geo.adapters.base import (
    AdapterResult,
    FactorValues,
    SkippedFactor,
    collect_notes,
    provenance_frame,
    resolve,
    unit_frame,
)
from roadrisk.geo.adapters.curvature import (
    CLIENT_ALIGNMENT_ADAPTER,
    OSM_GEOMETRY_ADAPTER,
    curvature_adapter,
)
from roadrisk.geo.adapters.osm_density import count_densities, count_per_unit
from roadrisk.geo.adapters.osm_tags import CarrierMatch, match_carriers, read_tags
from roadrisk.geo.adapters.osmdata import (
    OsmExtract,
    OsmNode,
    OsmWay,
    build_extract_query,
    fetch_extract,
)

__all__ = [
    "CLIENT_ALIGNMENT_ADAPTER",
    "OSM_GEOMETRY_ADAPTER",
    "AdapterResult",
    "CarrierMatch",
    "FactorValues",
    "OsmExtract",
    "OsmNode",
    "OsmWay",
    "SkippedFactor",
    "build_extract_query",
    "collect_notes",
    "count_densities",
    "count_per_unit",
    "curvature_adapter",
    "fetch_extract",
    "match_carriers",
    "provenance_frame",
    "read_tags",
    "resolve",
    "unit_frame",
]
