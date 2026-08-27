/**
 * A run's geometry, as GeoJSON, and one unit's provenance.
 *
 * Kept apart from the map component on purpose: this is arithmetic over the payload and
 * has no opinion about how it is drawn. It is also the only place in the shell that
 * reaches into the shape of a run, which means the day 5.3d adds a hover layer there is
 * one function to change rather than two components to keep agreeing.
 *
 * **Everything here comes out of the payload.** No projection library, no geocoding, no
 * request: `segmentation.units[].geometry` is already `[lon, lat]` pairs, because the
 * engine put them there for the report's own SVG map. The map draws the same numbers in
 * a different projection.
 */

import { riskColour } from "roadrisk-report/risk";
import type { Run } from "roadrisk-report/report";

/** One segment, ready to draw and ready to click. */
export interface UnitFeature {
  type: "Feature";
  id: number;
  geometry: { type: "LineString"; coordinates: [number, number][] };
  properties: {
    unit_id: string;
    index: number;
    rank: number | null;
    percentile: number | null;
    score: number | null;
    observed: number | null;
    expected: number | null;
    expected_low: number | null;
    expected_high: number | null;
    start_m: number;
    end_m: number;
    colour: string;
  };
}

export interface UnitCollection {
  type: "FeatureCollection";
  features: UnitFeature[];
}

/** West, south, east, north — what a map fits itself to. */
export type Bounds = [number, number, number, number];

/**
 * The corridor as coloured segments.
 *
 * **A unit with no rank is grey, not pale orange.** Mode B ranks every unit and Mode A
 * ranks every unit it could fit, but a unit that is missing from the ranking has no risk
 * to show — and giving it the bottom of the scale would say *lowest risk* about a segment
 * nobody assessed. Absence of a rank is not a low rank.
 */
export const UNRANKED = "#c3c8ce";

export function unitFeatures(run: Run): UnitCollection {
  const units = run.corridor?.segmentation.units ?? [];
  const ranked = new Map(
    (run.assessment.ranking?.units ?? []).map((unit) => [unit.unit_id, unit]),
  );

  const features = units
    .filter((unit) => unit.geometry.length > 1)
    .map((unit, index): UnitFeature => {
      const risk = ranked.get(unit.unit_id);
      return {
        type: "Feature",
        id: index,
        geometry: { type: "LineString", coordinates: unit.geometry },
        properties: {
          unit_id: unit.unit_id,
          index: unit.index,
          rank: risk?.rank ?? null,
          percentile: risk?.percentile ?? null,
          score: risk?.score ?? null,
          observed: risk?.observed ?? null,
          expected: risk?.expected ?? null,
          expected_low: risk?.expected_low ?? null,
          expected_high: risk?.expected_high ?? null,
          start_m: unit.start_m,
          end_m: unit.end_m,
          colour: risk ? riskColour(risk.percentile) : UNRANKED,
        },
      };
    });

  return { type: "FeatureCollection", features };
}

export function bounds(collection: UnitCollection): Bounds | null {
  const points = collection.features.flatMap((feature) => feature.geometry.coordinates);
  if (points.length === 0) return null;

  const lons = points.map(([lon]) => lon);
  const lats = points.map(([, lat]) => lat);
  return [
    Math.min(...lons),
    Math.min(...lats),
    Math.max(...lons),
    Math.max(...lats),
  ];
}

/** What was measured on one unit, and who said so. */
export interface UnitFactor {
  factor: string;
  column: string;
  value: number | null;
  adapter: string;
  tier: string;
  confidence: string;
  reason: string;
  licence: string | null;
  source: string | null;
  coverage: number | null;
}

/**
 * Every factor value on one unit, joined to where it came from.
 *
 * This is the *deliverable* of step 5.3c — clicking a segment is meant to answer "why is
 * this one dark", and the honest answer is a list of measurements with the adapter, tier
 * and licence behind each. Two tables in the payload hold the halves: `confidence` is per
 * unit and per factor, `provenance` is per factor for the whole corridor. Joining them
 * here rather than in the component keeps the map about drawing.
 *
 * A factor with no matching provenance row keeps its value and shows no licence, rather
 * than being dropped. A value the reader can see and a source they cannot is a fact worth
 * showing; silently omitting the row would hide the value too.
 */
export function unitFactors(run: Run, unitId: string): UnitFactor[] {
  const corridor = run.corridor;
  if (!corridor) return [];

  const byFactor = new Map(corridor.provenance.map((row) => [row.factor, row]));

  return corridor.confidence
    .filter((row) => row.unit_id === unitId)
    .map((row) => {
      const provenance = byFactor.get(row.factor);
      return {
        factor: row.factor,
        column: row.column,
        value: row.value,
        adapter: row.adapter,
        tier: row.tier,
        confidence: row.confidence,
        reason: row.reason,
        licence: provenance?.licence ?? null,
        source: provenance?.source ?? null,
        coverage: provenance?.coverage ?? null,
      };
    })
    .sort((left, right) => left.factor.localeCompare(right.factor));
}
