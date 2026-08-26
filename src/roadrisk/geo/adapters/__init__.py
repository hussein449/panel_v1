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
``building_density``    ``osm_buildings``           :mod:`.osm_density`
``grade_pct``           ``copernicus_dem_glo30``    :mod:`.grade`
``landuse_urban``       ``esa_worldcover``          :mod:`.landcover`
======================  ==========================  ============================

And two Tier B factors — open data, but real compute rather than a lookup:

==========================  =========================  ==========================
``traffic_proxy``           ``osm_graph_centrality``   :mod:`.graph`
``roadside_object_density`` ``mapillary_detections``   :mod:`.mapillary`
==========================  =========================  ==========================

Four sources, four costs. Curvature is arithmetic on the centreline. The nine Tier A OSM
factors are one Overpass call. The two raster factors are COG window reads over HTTPS,
and are the only ones that need GDAL — hence the separate ``raster`` extra. The traffic
proxy is a second, much wider Overpass fetch plus a few seconds of shortest-path work,
and Mapillary needs a free access token.

``population_density`` is the one Tier A factor in the brief with no adapter here, and
the reason is delivery format rather than data: WorldPop's global mosaic ignores HTTP
Range and GHSL ships deflated zip tiles, so either costs a whole-file download per
corridor. The registry records that under the factor, and it belongs behind the
content-addressed cache in step 2.9.

Client data enters through :mod:`.client` — the same code path, the same contract, and
first place in every chain because the registry declares it first. :mod:`.fusion` then
resolves each factor to one source, scores agreement where two of them overlap, and
emits a confidence tier per factor per unit.
"""

from __future__ import annotations

from roadrisk.geo.adapters.base import (
    AdapterNotDeclared,
    AdapterResult,
    FactorValues,
    SkippedFactor,
    collect_notes,
    resolve,
)
from roadrisk.geo.adapters.client import client_slot, read_client_values
from roadrisk.geo.adapters.curvature import (
    CLIENT_ALIGNMENT_ADAPTER,
    OSM_GEOMETRY_ADAPTER,
    curvature_adapter,
)
from roadrisk.geo.adapters.fusion import (
    Confidence,
    FusedFactor,
    FusionResult,
    SourceAgreement,
    fuse,
    provenance_frame,
)
from roadrisk.geo.adapters.grade import compute_grade
from roadrisk.geo.adapters.graph import (
    RoadGraph,
    compute_traffic_proxy,
    edge_betweenness,
    fetch_network,
)
from roadrisk.geo.adapters.landcover import compute_landcover
from roadrisk.geo.adapters.mapillary import (
    HttpMapillaryClient,
    MapillaryClient,
    MapillaryFeatures,
    compute_object_density,
    fetch_features,
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
from roadrisk.geo.adapters.rasters import (
    COPERNICUS_DEM,
    ESA_WORLDCOVER,
    CogSampler,
    PointSampler,
    RasterProduct,
    elevation_sampler,
    landcover_sampler,
)
from roadrisk.geo.adapters.sampling import Stations, stations_along, to_latlon

__all__ = [
    "CLIENT_ALIGNMENT_ADAPTER",
    "COPERNICUS_DEM",
    "ESA_WORLDCOVER",
    "OSM_GEOMETRY_ADAPTER",
    "AdapterNotDeclared",
    "AdapterResult",
    "CarrierMatch",
    "CogSampler",
    "Confidence",
    "FactorValues",
    "FusedFactor",
    "FusionResult",
    "HttpMapillaryClient",
    "MapillaryClient",
    "MapillaryFeatures",
    "OsmExtract",
    "OsmNode",
    "OsmWay",
    "PointSampler",
    "RasterProduct",
    "RoadGraph",
    "SkippedFactor",
    "SourceAgreement",
    "Stations",
    "build_extract_query",
    "client_slot",
    "collect_notes",
    "compute_grade",
    "compute_landcover",
    "compute_object_density",
    "compute_traffic_proxy",
    "count_densities",
    "count_per_unit",
    "curvature_adapter",
    "edge_betweenness",
    "elevation_sampler",
    "fetch_extract",
    "fetch_features",
    "fetch_network",
    "fuse",
    "landcover_sampler",
    "match_carriers",
    "provenance_frame",
    "read_client_values",
    "read_tags",
    "resolve",
    "stations_along",
    "to_latlon",
]
