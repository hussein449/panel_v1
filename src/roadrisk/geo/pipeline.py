"""The geometry path, end to end.

    centreline → corridor → segment → skeleton → snap crashes → fan out adapters → panel

The output is a contract-valid panel that :func:`roadrisk.core.assess` consumes
directly, together with the snap report that activates gate check 6 and the provenance
of every factor value the adapters produced. This is the seam between Stage 2 and
Stage 1: geography produces the panel, the engine judges it, and neither knows how the
other works.

**Adapters are opt-in per source, not per factor.** Curvature costs nothing and runs by
default. Anything needing OpenStreetMap runs only when a caller supplies a client, so
the whole pipeline — and the whole test suite — still runs with no network.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from roadrisk.core.gates import SnapReport
from roadrisk.core.registry import Registry, load_registry
from roadrisk.geo.adapters import (
    OSM_GEOMETRY_ADAPTER,
    AdapterResult,
    FusionResult,
    MapillaryClient,
    OsmExtract,
    PointSampler,
    RoadGraph,
    collect_notes,
    compute_grade,
    compute_landcover,
    compute_object_density,
    compute_traffic_proxy,
    count_densities,
    curvature_adapter,
    fetch_extract,
    fetch_features,
    fetch_network,
    fuse,
    provenance_frame,
    read_client_values,
    read_tags,
)
from roadrisk.geo.attribution import AttributionReport, collect_attributions
from roadrisk.geo.cache import Cache, CacheReport, NullCache
from roadrisk.geo.cache import collect_notes as collect_cache_notes
from roadrisk.geo.cached import cached_mapillary, cached_overpass
from roadrisk.geo.corridor import Corridor
from roadrisk.geo.errors import CorridorError
from roadrisk.geo.geometry import CurvatureResult, compute_curvature
from roadrisk.geo.osm import OverpassClient
from roadrisk.geo.panel import attach_factor_values, build_skeleton
from roadrisk.geo.segmentation import (
    DEFAULT_TARGET_LENGTH_M,
    Segmentation,
    segment,
)
from roadrisk.geo.snapping import (
    DEFAULT_TOLERANCE_M,
    SnapOutcome,
    apply_counts,
    snap_crashes,
)


@dataclass(frozen=True)
class CorridorPanel:
    """A panel built from geography, and everything needed to defend it."""

    panel: pd.DataFrame
    corridor: Corridor
    segmentation: Segmentation
    snap: SnapReport | None = None
    snap_detail: pd.DataFrame | None = None
    curvature: CurvatureResult | None = None
    adapters: list[AdapterResult] = field(default_factory=list)
    fusion: FusionResult = field(default_factory=FusionResult)
    cache: CacheReport = field(default_factory=CacheReport)
    factor_columns: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def n_units(self) -> int:
        return len(self.segmentation)

    @property
    def n_rows(self) -> int:
        return int(len(self.panel))

    @property
    def total_crashes(self) -> int:
        return int(self.panel["n_crashes"].sum())

    @property
    def zero_crash_rows(self) -> int:
        return int((self.panel["n_crashes"] == 0).sum())

    @property
    def provenance(self) -> pd.DataFrame:
        """One row per factor: value, source, tier, licence, confidence, agreement."""
        return provenance_frame(self.fusion)

    @property
    def confidence(self) -> pd.DataFrame:
        """One row per factor per unit — the deliverable of step 2.7."""
        return self.fusion.confidence_frame()

    @property
    def contested(self) -> list[str]:
        """Factors more than one source resolved, so fusion had to choose."""
        return [fused.column for fused in self.fusion.contested]

    @property
    def skipped(self) -> list[tuple[str, str, str]]:
        """Factors an adapter could have filled and did not — factor, adapter, reason."""
        return [
            (skip.factor, skip.adapter, skip.reason)
            for result in self.adapters
            for skip in result.skipped
        ]

    def summary(self) -> str:
        return (
            f"{self.corridor.name}: {self.corridor.length_km:.2f} km in "
            f"{self.n_units:,} units, {self.n_rows:,} panel rows, "
            f"{self.total_crashes:,} crashes, "
            f"{self.zero_crash_rows:,} zero-crash rows"
        )

    @property
    def attribution(self) -> AttributionReport:
        """Who must be credited, and what redistributing the panel would cost."""
        return collect_attributions(self.fusion)

    def as_dict(self) -> dict[str, Any]:
        """Serialisable form. The geography half of what the report consumes.

        The counterpart to :meth:`roadrisk.core.Assessment.as_dict`. Together the two
        carry everything a report needs, which is the point: a report rendered from
        these two payloads never holds a Python object, so a run stored today can be
        re-rendered tomorrow without refitting anything.

        Geometry is included in WGS84 — ``(longitude, latitude)`` pairs, GeoJSON's
        order — because the corridor map is part of the report rather than a separate
        product, and a consumer that has to reproject is a consumer that will get it
        wrong.
        """
        return {
            "corridor": {
                "name": self.corridor.name,
                "length_m": round(self.corridor.length_m, 3),
                "length_km": round(self.corridor.length_km, 4),
                "epsg": self.corridor.epsg,
                "self_intersecting": self.corridor.self_intersecting,
                "warnings": list(self.corridor.warnings),
                "geometry": _linestring(self.corridor.wgs84),
            },
            "segmentation": {
                "n_units": self.n_units,
                "target_length_m": self.segmentation.target_length_m,
                "total_length_km": round(self.segmentation.total_length_km, 4),
                "units": [
                    {
                        "unit_id": unit.unit_id,
                        "index": unit.index,
                        "start_m": round(unit.start_m, 3),
                        "end_m": round(unit.end_m, 3),
                        "length_m": round(unit.length_m, 3),
                        "midpoint_m": round(unit.midpoint_m, 3),
                        "geometry": _linestring(
                            self.corridor.projector.to_wgs84(unit.geometry)
                        ),
                    }
                    for unit in self.segmentation.units
                ],
            },
            "panel": {
                "rows": self.n_rows,
                "units": self.n_units,
                "total_crashes": self.total_crashes,
                "zero_crash_rows": self.zero_crash_rows,
                "factor_columns": list(self.factor_columns),
            },
            "snap": (
                {
                    "n_supplied": self.snap.n_supplied,
                    "n_snapped": self.snap.n_snapped,
                    "n_dropped": self.snap.n_dropped,
                    "snap_rate": round(self.snap.snap_rate, 4),
                    "dropped_reasons": dict(self.snap.dropped_reasons),
                }
                if self.snap is not None
                else None
            ),
            "adapters": [
                {
                    "name": result.name,
                    "resolved": [values.factor for values in result.resolved],
                    "skipped": [
                        {
                            "factor": skip.factor,
                            "adapter": skip.adapter,
                            "reason": skip.reason,
                        }
                        for skip in result.skipped
                    ],
                    "notes": list(result.notes),
                }
                for result in self.adapters
            ],
            "provenance": self.provenance.to_dict("records"),
            "confidence": self.confidence.to_dict("records"),
            "contested": list(self.contested),
            "disagreements": [
                {
                    "factor": agreement.factor,
                    "column": agreement.column,
                    "chosen": agreement.chosen,
                    "challenger": agreement.challenger,
                    "n_compared": agreement.n_compared,
                    "n_agreeing": agreement.n_agreeing,
                    "score": agreement.score,
                    "mean_absolute_difference": agreement.mean_absolute_difference,
                    "max_absolute_difference": agreement.max_absolute_difference,
                    "correlation": agreement.correlation,
                    "disagreeing_units": list(agreement.disagreeing_units),
                    "note": agreement.note,
                }
                for agreement in self.fusion.disagreements
            ],
            "attribution": self.attribution.as_dict(),
            "cache": {
                "hits": self.cache.hits,
                "misses": self.cache.misses,
                "used": self.cache.used,
                "oldest_days": round(self.cache.oldest_days, 2),
                "notes": self.cache.notes(),
                "ages": [
                    {"source": source, "age_days": round(age, 2), "fetched_on": on}
                    for source, age, on in self.cache.ages
                ],
            },
            "fusion_notes": list(self.fusion.notes),
            "warnings": list(self.warnings),
        }


def _linestring(geometry: Any) -> list[list[float]]:
    """A shapely line as GeoJSON-ordered coordinate pairs.

    Six decimal places is about 0.1 m at the equator — finer than any centreline this
    tool consumes, and it keeps a 200-unit corridor's geometry from dominating the
    payload it travels in.
    """
    return [[round(x, 6), round(y, 6)] for x, y in geometry.coords]


def build_corridor_panel(
    points: Sequence[tuple[float, float]],
    *,
    periods: Sequence[str],
    name: str = "corridor",
    crashes: pd.DataFrame | None = None,
    time_slots: Mapping[str, float] | None = None,
    target_length_m: float = DEFAULT_TARGET_LENGTH_M,
    tolerance_m: float = DEFAULT_TOLERANCE_M,
    with_curvature: bool = True,
    registry: Registry | None = None,
    centreline_adapter: str = OSM_GEOMETRY_ADAPTER,
    osm: OsmExtract | None = None,
    osm_client: OverpassClient | None = None,
    ref: str | None = None,
    elevation: PointSampler | None = None,
    landcover: PointSampler | None = None,
    client_values: pd.DataFrame | None = None,
    client_source: str | None = None,
    network: RoadGraph | None = None,
    network_client: OverpassClient | None = None,
    mapillary_client: MapillaryClient | None = None,
    cache: Cache | None = None,
    latitude_column: str = "latitude",
    longitude_column: str = "longitude",
    period_column: str = "period",
    time_slot_column: str | None = None,
) -> CorridorPanel:
    """Turn a centreline and a crash table into a panel the engine can assess.

    Args:
        points: Ordered centreline vertices as (latitude, longitude).
        periods: Period labels, e.g. ``["2024-01", ...]``. Must be unique.
        name: Corridor identifier, used to prefix unit ids.
        crashes: Crash table. When None the panel is all zeros — useful for Mode B,
            which needs no crash data at all.
        time_slots: Slot name to hours per period. Defaults to one whole-month slot.
        target_length_m: Nominal unit length.
        tolerance_m: Snapping tolerance from the centreline.
        with_curvature: Compute the geometry-derived factors. No network required.
        registry: Factor registry. Supplies the tier and licence attached to every
            adapter value. Defaults to the one shipped with the package.
        centreline_adapter: Registry slot the centreline fills. ``osm_geometry`` for an
            OSM export, ``client_alignment`` for an alignment the client supplied — the
            curvature arithmetic is identical, the provenance is not.
        osm: A pre-fetched OSM extract, when the caller already has one.
        osm_client: Overpass client. Supplying either this or ``osm`` runs the OSM
            Tier A adapters; supplying neither leaves the pipeline entirely offline.
        ref: Road reference, used to prefer the right way where several run close
            together.
        elevation: Elevation sampler for ``grade_pct``. Supply
            :func:`~roadrisk.geo.adapters.rasters.elevation_sampler` for Copernicus DEM
            GLO-30 over the network, or any callable for a surface of your own.
        landcover: Land-cover sampler for ``landuse_urban``. Supply
            :func:`~roadrisk.geo.adapters.rasters.landcover_sampler` for ESA WorldCover.
        client_values: Anything the client already measured, one row per unit keyed by
            ``unit_id``. It wins every factor it covers, because the registry declares
            the client slot first — and where an open source covered the same factor,
            the two are compared and the units they differ on are named.
        client_source: Provenance text for that table, e.g. "2024 asset inventory".
        network: A pre-fetched strategic road network for the traffic proxy.
        network_client: Overpass client for that fetch. Deliberately separate from
            ``osm_client``: the ribbon fetch and the wide regional fetch are different
            queries with very different costs, and a caller may want one without the
            other.
        mapillary_client: Client for the Mapillary map-features API. Supplying it runs
            the roadside-object adapter; the default implementation needs a free access
            token in ``$MAPILLARY_ACCESS_TOKEN``.
        cache: Where to remember remote answers between runs. Every network client is
            wrapped in it, the strategic-network request is rounded to a grid so a second
            corridor in the same region reuses the first one's fetch, and every hit is
            reported with the age of what it served.
        latitude_column, longitude_column, period_column, time_slot_column: Column
            names in ``crashes``.

    Returns:
        A :class:`CorridorPanel`. Pass ``.panel`` and ``.snap`` to
        :func:`roadrisk.core.assess`.
    """
    active_registry = registry if registry is not None else load_registry()
    store = cache if cache is not None else NullCache()
    cache_report = CacheReport()

    if osm_client is not None:
        osm_client = cached_overpass(osm_client, store, report=cache_report, label="ribbon")
    if network_client is not None:
        # Plain query-text caching is enough here: the network query is built from a
        # grid cell, so two corridors in the same county already ask the same question.
        network_client = cached_overpass(
            network_client, store, report=cache_report, label="network"
        )
    if mapillary_client is not None:
        mapillary_client = cached_mapillary(mapillary_client, store, report=cache_report)

    corridor = Corridor.from_latlon(points, name=name)
    segmentation = segment(corridor, target_length_m=target_length_m)
    warnings = list(corridor.warnings)

    slots = dict(time_slots) if time_slots else None
    panel = build_skeleton(segmentation, periods=periods, time_slots=slots)
    slot_names = sorted(panel["time_slot"].unique().tolist())

    outcome: SnapOutcome | None = None
    if crashes is not None and len(crashes):
        outcome = snap_crashes(
            segmentation,
            crashes,
            periods=list(periods),
            time_slots=slot_names,
            latitude_column=latitude_column,
            longitude_column=longitude_column,
            period_column=period_column,
            time_slot_column=time_slot_column,
            tolerance_m=tolerance_m,
        )
        panel = apply_counts(panel, outcome.counts)
        warnings.extend(outcome.warnings)

    results: list[AdapterResult] = []

    curvature: CurvatureResult | None = None
    if with_curvature:
        curvature = compute_curvature(segmentation)
        results.append(
            curvature_adapter(
                curvature,
                segmentation,
                registry=active_registry,
                adapter=centreline_adapter,
            )
        )

    extract = osm
    if extract is None and osm_client is not None:
        extract, fetch_warnings = _fetch_extract(corridor, osm_client, ref)
        warnings.extend(fetch_warnings)

    if extract is not None:
        warnings.extend(extract.warnings)
        results.append(
            read_tags(
                extract, segmentation, registry=active_registry, ref=ref or extract.ref
            )
        )
        results.append(count_densities(extract, segmentation, registry=active_registry))

    if elevation is not None:
        results.append(
            compute_grade(segmentation, elevation, registry=active_registry)
        )
    if landcover is not None:
        results.append(
            compute_landcover(segmentation, landcover, registry=active_registry)
        )

    graph = network
    if graph is None and network_client is not None:
        graph, network_warnings = _fetch_network(corridor, network_client)
        warnings.extend(network_warnings)
    if graph is not None:
        results.append(
            compute_traffic_proxy(segmentation, graph, registry=active_registry)
        )

    if mapillary_client is not None:
        features, mapillary_warnings = _fetch_features(corridor, mapillary_client)
        warnings.extend(mapillary_warnings)
        if features is not None:
            results.append(
                compute_object_density(
                    segmentation, features, registry=active_registry
                )
            )

    if client_values is not None:
        results.append(
            read_client_values(
                client_values,
                segmentation,
                registry=active_registry,
                source=client_source,
            )
        )

    fusion = fuse(results, active_registry)
    values = fusion.values_frame()
    if values is not None:
        panel = attach_factor_values(panel, values)

    # Skip reasons are not repeated here: they are first-class on the result, as
    # `CorridorPanel.skipped`, and a reason worth reading is worth reading once.
    warnings.extend(collect_notes(results, include_skipped=False))
    warnings.extend(fusion.notes)
    # Last, and never omitted when the cache was used: a reader has to be able to see
    # that the result rests on stored data, and how old that data was.
    warnings.extend(collect_cache_notes([cache_report]))

    return CorridorPanel(
        panel=panel,
        corridor=corridor,
        segmentation=segmentation,
        snap=outcome.report if outcome else None,
        snap_detail=outcome.detail if outcome else None,
        curvature=curvature,
        adapters=results,
        fusion=fusion,
        cache=cache_report,
        factor_columns=fusion.columns,
        warnings=warnings,
    )


def _fetch_extract(
    corridor: Corridor,
    client: OverpassClient,
    ref: str | None,
) -> tuple[OsmExtract | None, list[str]]:
    """Fetch the OSM extract, degrading loudly rather than losing the whole run.

    Overpass mirrors return 504 under load often enough that a corridor's crash data,
    segmentation and curvature should not be thrown away because a volunteer-run server
    was busy. The failure is reported at the top of the run, not swallowed.
    """
    try:
        return fetch_extract(corridor, client=client, ref=ref), []
    except CorridorError as exc:
        return None, [
            "The OSM attribute fetch failed, so every OSM-derived factor is absent from "
            f"this panel: {exc} Curvature and the crash counts are unaffected. Re-run "
            "to pick the factors up."
        ]


def _fetch_network(
    corridor: Corridor,
    client: OverpassClient,
) -> tuple[RoadGraph | None, list[str]]:
    """Fetch the regional network, degrading loudly rather than losing the run.

    This is by far the largest query the pipeline makes — a whole region rather than a
    ribbon — so it is the one most likely to meet a busy mirror.
    """
    try:
        return fetch_network(corridor, client=client), []
    except CorridorError as exc:
        return None, [
            f"The strategic network fetch failed, so traffic_proxy is absent: {exc} "
            "Every other factor is unaffected."
        ]


def _fetch_features(
    corridor: Corridor,
    client: MapillaryClient,
) -> tuple[Any | None, list[str]]:
    """Fetch Mapillary detections, degrading loudly."""
    try:
        return fetch_features(corridor, client=client), []
    except CorridorError as exc:
        return None, [
            f"The Mapillary fetch failed, so roadside_object_density is absent: {exc} "
            "Every other factor is unaffected."
        ]


__all__ = ["CorridorPanel", "build_corridor_panel"]
