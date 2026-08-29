/**
 * How much road is actually in the frame, measured off the basemap's own geometry.
 *
 * **Why this exists.** The bounding box is the viewport, so the reader's zoom decides how
 * much road gets assessed — and nothing on the screen said so in a number. The first real
 * corridor run through this page assessed **1.83 km of a 2.95 km road** and produced four
 * segments, which is too few for the method to say anything: the collinearity check
 * returned infinity because four observations cannot support ten factors, and the ranking
 * came out spread across 1.8% of its own scale. All of that was decided before the button
 * was pressed, by a zoom level, silently.
 *
 * **It is an estimate and is labelled as one everywhere it is shown.** Three reasons it
 * cannot be exact, none of them fixable here:
 *
 * - Vector tiles simplify geometry, and more so as you zoom out — the direction that
 *   matters most here, so this reads slightly short on a wide view.
 * - A road is split at tile boundaries into several features. Summing them is right, but
 *   only the pieces currently rendered are counted.
 * - The tiles are one OSM extract and the fetch will make another, later. They will not
 *   always agree.
 *
 * The honest use is the order of magnitude: *four segments or forty*. That distinction is
 * the one that was silently wrong, and it survives every approximation above.
 */

/** Metres between two [lon, lat] pairs. Haversine — no projection, no dependency. */
export function metresBetween(a: number[], b: number[]): number {
  const R = 6_371_000;
  const toRad = Math.PI / 180;
  const lat1 = a[1] * toRad;
  const lat2 = b[1] * toRad;
  const dLat = lat2 - lat1;
  const dLon = (b[0] - a[0]) * toRad;
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** Summed length of one line of [lon, lat] positions. */
export function lineLength(coordinates: number[][]): number {
  let total = 0;
  for (let i = 1; i < coordinates.length; i += 1) {
    total += metresBetween(coordinates[i - 1], coordinates[i]);
  }
  return total;
}

/** The GeoJSON this needs, without pulling in a type package for two shapes. */
type LineGeometry =
  | { type: "LineString"; coordinates: number[][] }
  | { type: "MultiLineString"; coordinates: number[][][] };

function isLine(geometry: unknown): geometry is LineGeometry {
  const type = (geometry as { type?: unknown } | null)?.type;
  return type === "LineString" || type === "MultiLineString";
}

/**
 * Total length of a set of rendered features, in metres.
 *
 * **Deduplicated by geometry, which is not paranoia.** `queryRenderedFeatures` returns a
 * source feature once per style layer that draws it, and a basemap that labels roads in
 * two layers — a shield and a name — would otherwise double every motorway. Tile-split
 * pieces of one road are genuinely different geometries and are correctly counted twice.
 */
export function totalLength(features: { geometry?: unknown }[]): number {
  const seen = new Set<string>();
  let total = 0;

  for (const feature of features) {
    const geometry = feature.geometry;
    if (!isLine(geometry)) continue;

    const lines =
      geometry.type === "LineString"
        ? [geometry.coordinates]
        : geometry.coordinates;

    for (const line of lines) {
      if (line.length < 2) continue;
      // Rounded before it becomes a key: the same feature arriving through two layers
      // can differ in the last floating-point digit.
      const key = line
        .map((p) => `${p[0].toFixed(6)},${p[1].toFixed(6)}`)
        .join(";");
      if (seen.has(key)) continue;
      seen.add(key);
      total += lineLength(line);
    }
  }
  return total;
}

/** What the panel shows, and how strongly it should be saying it. */
export interface Extent {
  metres: number;
  segments: number;
  verdict: "too-short" | "thin" | "good";
}

/** The unit length this page always submits. See `assessAction`. */
export const UNIT_LENGTH_M = 500;

/**
 * Below this the method cannot do its job, and the number comes from a real run rather
 * than from taste: four segments produced `VIF = inf` on eight terms — not "collinear",
 * *undefined*, because there were more factors than observations — and a blackspot
 * defined as "the worst 20%" that selected exactly one segment.
 */
const TOO_FEW_SEGMENTS = 10;

/** Above this a corridor has enough units for the ranking to separate and the checks to mean something. */
const COMFORTABLE_SEGMENTS = 20;

export function extentOf(metres: number): Extent {
  const segments = Math.max(1, Math.round(metres / UNIT_LENGTH_M));
  return {
    metres,
    segments,
    verdict:
      segments < TOO_FEW_SEGMENTS
        ? "too-short"
        : segments < COMFORTABLE_SEGMENTS
          ? "thin"
          : "good",
  };
}

/** "9.4 km", "820 m" — one place after the point, because this is an estimate. */
export function describeLength(metres: number): string {
  return metres < 1000
    ? `${Math.round(metres / 10) * 10} m`
    : `${(metres / 1000).toFixed(1)} km`;
}
