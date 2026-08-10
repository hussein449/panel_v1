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

import pandas as pd

from roadrisk.core.gates import SnapReport
from roadrisk.core.registry import Registry, load_registry
from roadrisk.geo.adapters import (
    OSM_GEOMETRY_ADAPTER,
    AdapterResult,
    OsmExtract,
    PointSampler,
    collect_notes,
    compute_grade,
    compute_landcover,
    count_densities,
    curvature_adapter,
    fetch_extract,
    provenance_frame,
    read_tags,
    unit_frame,
)
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
        """One row per factor: value, source, tier and licence, as the brief asks."""
        return provenance_frame(self.adapters)

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
        latitude_column, longitude_column, period_column, time_slot_column: Column
            names in ``crashes``.

    Returns:
        A :class:`CorridorPanel`. Pass ``.panel`` and ``.snap`` to
        :func:`roadrisk.core.assess`.
    """
    active_registry = registry if registry is not None else load_registry()

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

    values = unit_frame(results)
    if values is not None:
        panel = attach_factor_values(panel, values)
    # Skip reasons are not repeated here: they are first-class on the result, as
    # `CorridorPanel.skipped`, and a reason worth reading is worth reading once.
    warnings.extend(collect_notes(results, include_skipped=False))

    return CorridorPanel(
        panel=panel,
        corridor=corridor,
        segmentation=segmentation,
        snap=outcome.report if outcome else None,
        snap_detail=outcome.detail if outcome else None,
        curvature=curvature,
        adapters=results,
        factor_columns=[column for result in results for column in result.columns],
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


__all__ = ["CorridorPanel", "build_corridor_panel"]
