"""Reading a few thousand pixels out of a global raster without downloading it.

Copernicus DEM GLO-30 is about 1.5 TB. ESA WorldCover is larger. A corridor needs a few
thousand values from each, and the only reason that is affordable is the cloud-optimised
GeoTIFF: an internally tiled, overview-carrying layout that a client can read *windows*
of over HTTP range requests. GDAL's ``/vsicurl/`` driver does the range requests; this
module decides which windows to ask for.

**Windows, batched along the corridor — never one request per point.** Sampling point by
point costs one HTTP round trip each, which for 500 stations is minutes. Reading one
window for the whole corridor costs a single request but can be hundreds of megabytes
for a long diagonal road. So points are grouped into runs of consecutive stations and a
window is read per run: memory stays bounded whatever shape the corridor is, and a 25 km
road costs a handful of requests.

**rasterio is an optional extra.** ``core`` needs pandas; ``geo`` adds shapely; only this
module needs GDAL, and it says so by name rather than dying with a bare ImportError::

    pip install "roadrisk-panel[raster]"

**Everything above the sampler is testable without any of it.** :class:`PointSampler` is
a protocol, so the grade and land-cover adapters take a callable and the tests hand them
an analytic surface.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

from roadrisk.geo.errors import GeoError

#: Consecutive stations read in one window. Bounds the window extent — and therefore
#: memory — regardless of corridor length or bearing, while keeping the request count
#: proportional to length rather than to station count.
DEFAULT_BATCH = 48

#: Refuse rather than read a window this large. A window only gets here if a batch of
#: consecutive stations spans an implausible distance, which means the caller passed
#: points that are not a corridor.
MAX_WINDOW_PIXELS = 16_000_000

#: GDAL settings that make /vsicurl/ behave. Without the first two, GDAL lists the
#: bucket prefix and probes for sidecar files on every open — several wasted round trips
#: per tile against a server that will 404 all of them.
GDAL_OPTIONS: dict[str, str] = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
    "GDAL_HTTP_MULTIPLEX": "YES",
    "GDAL_HTTP_VERSION": "2",
    "VSI_CACHE": "TRUE",
    "VSI_CACHE_SIZE": str(64 * 1024 * 1024),
}

COPERNICUS_DEM_ROOT = "https://copernicus-dem-30m.s3.amazonaws.com"
WORLDCOVER_ROOT = "https://esa-worldcover.s3.eu-central-1.amazonaws.com"

#: ESA WorldCover class for built-up land. The one class this package reads by number.
WORLDCOVER_BUILT_UP = 50


class PointSampler(Protocol):
    """Anything that can return a value per (latitude, longitude) point.

    ``NaN`` means *no value here* — outside coverage, over nodata, or a tile that does
    not exist. It never means zero, and every caller in this package treats it as
    absence of evidence rather than as a measurement.
    """

    def __call__(self, points: Sequence[tuple[float, float]]) -> np.ndarray: ...


def copernicus_dem_url(latitude: float, longitude: float) -> str:
    """URL of the one-degree GLO-30 tile containing this point.

    Tiles are named for their south-west integer degree corner, so the arithmetic is
    ``floor``, and it must be ``floor`` rather than ``int`` — truncating toward zero
    puts every point between 0 and -1 degrees in the wrong tile.
    """
    lat_index = math.floor(latitude)
    lon_index = math.floor(longitude)
    name = (
        f"Copernicus_DSM_COG_10_"
        f"{'N' if lat_index >= 0 else 'S'}{abs(lat_index):02d}_00_"
        f"{'E' if lon_index >= 0 else 'W'}{abs(lon_index):03d}_00_DEM"
    )
    return f"{COPERNICUS_DEM_ROOT}/{name}/{name}.tif"


def worldcover_url(latitude: float, longitude: float) -> str:
    """URL of the three-degree WorldCover tile containing this point."""
    lat_index = math.floor(latitude / 3.0) * 3
    lon_index = math.floor(longitude / 3.0) * 3
    tile = (
        f"{'N' if lat_index >= 0 else 'S'}{abs(lat_index):02d}"
        f"{'E' if lon_index >= 0 else 'W'}{abs(lon_index):03d}"
    )
    return (
        f"{WORLDCOVER_ROOT}/v200/2021/map/"
        f"ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
    )


@dataclass(frozen=True)
class RasterProduct:
    """A global raster addressed as a grid of independently readable tiles."""

    name: str
    url_for: Callable[[float, float], str]
    attribution: str
    resolution_m: float
    #: Values that mean "no data" beyond whatever the file declares. WorldCover uses 0
    #: and says so; some products say nothing and rely on convention.
    extra_nodata: tuple[float, ...] = ()


COPERNICUS_DEM = RasterProduct(
    name="Copernicus DEM GLO-30",
    url_for=copernicus_dem_url,
    attribution=(
        "Copernicus DEM GLO-30, produced using Copernicus WorldDEM-30 "
        "(c) DLR e.V. 2010-2014 and (c) Airbus Defence and Space GmbH 2014-2018, "
        "provided under COPERNICUS by the European Union and ESA. Attribution required."
    ),
    resolution_m=30.0,
)

ESA_WORLDCOVER = RasterProduct(
    name="ESA WorldCover 10 m v200 (2021)",
    url_for=worldcover_url,
    attribution=(
        "ESA WorldCover 10 m 2021 v200, (c) ESA WorldCover project 2021 / "
        "Contains modified Copernicus Sentinel data (2021) processed by ESA "
        "WorldCover consortium. CC BY 4.0 — attribution required."
    ),
    resolution_m=10.0,
    extra_nodata=(0.0,),
)


@dataclass
class CogSampler:
    """Samples a tiled global raster over HTTP, one window per batch of points.

    Not frozen: it keeps a small per-instance cache of tiles known to be missing, so a
    corridor that runs off the edge of coverage does not re-request the same absent tile
    for every batch.
    """

    product: RasterProduct
    batch: int = DEFAULT_BATCH
    max_window_pixels: int = MAX_WINDOW_PIXELS
    _absent: set[str] = field(default_factory=set, repr=False)

    def __call__(self, points: Sequence[tuple[float, float]]) -> np.ndarray:
        rasterio = _require_rasterio(self.product.name)

        values = np.full(len(points), np.nan, dtype=float)
        if not len(points):
            return values

        with rasterio.Env(**GDAL_OPTIONS):
            for url, positions in self._by_tile(points):
                if url in self._absent:
                    continue
                try:
                    with rasterio.open(url) as source:
                        for run in _runs(positions, self.batch):
                            self._read_window(source, points, run, values)
                except rasterio.errors.RasterioIOError:
                    # A missing tile is ordinary: the grid covers the globe, coverage
                    # does not. Ocean, and the poles for WorldCover, simply have no file.
                    self._absent.add(url)

        return values

    def _by_tile(
        self, points: Sequence[tuple[float, float]]
    ) -> Iterator[tuple[str, list[int]]]:
        grouped: dict[str, list[int]] = {}
        for index, (latitude, longitude) in enumerate(points):
            if not (np.isfinite(latitude) and np.isfinite(longitude)):
                continue
            grouped.setdefault(self.product.url_for(latitude, longitude), []).append(
                index
            )
        yield from grouped.items()

    def _read_window(
        self,
        source: Any,
        points: Sequence[tuple[float, float]],
        run: list[int],
        values: np.ndarray,
    ) -> None:
        from rasterio.windows import Window, from_bounds

        latitudes = [points[i][0] for i in run]
        longitudes = [points[i][1] for i in run]

        # A one-pixel margin: from_bounds floors and ceils, and a point sitting exactly
        # on the window edge would otherwise index one past the array.
        pad = source.res[0] * 2.0
        window = from_bounds(
            min(longitudes) - pad,
            min(latitudes) - pad,
            max(longitudes) + pad,
            max(latitudes) + pad,
            transform=source.transform,
        ).round_offsets().round_lengths()

        window = _clip(window, source.width, source.height, Window)
        if window.width <= 0 or window.height <= 0:
            return
        if window.width * window.height > self.max_window_pixels:
            raise GeoError(
                f"{self.product.name}: a batch of {len(run)} points spans a "
                f"{window.width:,.0f} x {window.height:,.0f} pixel window, over the "
                f"{self.max_window_pixels:,} limit. These points are too far apart to "
                "be consecutive stations on one corridor."
            )

        block = source.read(1, window=window, masked=True)
        transform = source.window_transform(window)
        inverse = ~transform

        for position, index in enumerate(run):
            column, row = inverse * (longitudes[position], latitudes[position])
            row, column = int(row), int(column)
            if not (0 <= row < block.shape[0] and 0 <= column < block.shape[1]):
                continue
            if block.mask is not np.ma.nomask and block.mask[row, column]:
                continue
            value = float(block.data[row, column])
            if value in self.product.extra_nodata:
                continue
            values[index] = value


def _clip(window: Any, width: int, height: int, window_cls: Any) -> Any:
    """Trim a window to the raster, so a corridor at a tile edge still reads."""
    col_off = max(int(window.col_off), 0)
    row_off = max(int(window.row_off), 0)
    return window_cls(
        col_off=col_off,
        row_off=row_off,
        width=min(int(window.width) + int(window.col_off) - col_off, width - col_off),
        height=min(int(window.height) + int(window.row_off) - row_off, height - row_off),
    )


def _runs(positions: list[int], size: int) -> Iterator[list[int]]:
    for start in range(0, len(positions), size):
        yield positions[start : start + size]


def _require_rasterio(product: str) -> Any:
    try:
        import rasterio
        import rasterio.errors  # noqa: F401  - referenced as rasterio.errors below
    except ModuleNotFoundError as exc:  # pragma: no cover - import-time guard
        raise GeoError(
            f"reading {product} needs GDAL, which is deliberately not a dependency of "
            "the geometry pipeline — the OSM adapters and the whole engine run without "
            'it. Install it with:  pip install "roadrisk-panel[raster]"'
        ) from exc
    return rasterio


def elevation_sampler(**kwargs: Any) -> CogSampler:
    """The default Copernicus DEM GLO-30 sampler."""
    return CogSampler(product=COPERNICUS_DEM, **kwargs)


def landcover_sampler(**kwargs: Any) -> CogSampler:
    """The default ESA WorldCover sampler."""
    return CogSampler(product=ESA_WORLDCOVER, **kwargs)


__all__ = [
    "COPERNICUS_DEM",
    "DEFAULT_BATCH",
    "ESA_WORLDCOVER",
    "GDAL_OPTIONS",
    "MAX_WINDOW_PIXELS",
    "WORLDCOVER_BUILT_UP",
    "CogSampler",
    "PointSampler",
    "RasterProduct",
    "copernicus_dem_url",
    "elevation_sampler",
    "landcover_sampler",
    "worldcover_url",
]
