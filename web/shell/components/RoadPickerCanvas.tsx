"use client";

import { useEffect, useRef, useState } from "react";
import {
  Map as MapLibreMap,
  NavigationControl,
  ScaleControl,
  setWorkerUrl,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

import type { Basemap } from "@/lib/api";
import { type Extent, extentOf, totalLength } from "@/lib/measure";

/**
 * The map you pick a road on, and the second file in this app that knows MapLibre exists.
 *
 * **Why a click on the basemap can identify a road at all.** The basemap is not a picture
 * — it is vector tiles in the OpenMapTiles schema, and the features it draws roads from
 * carry their own OSM tags. So `queryRenderedFeatures` at the cursor returns the road,
 * with its `ref` and its `name`, and those are exactly the two selectors
 * `geo/osm.py` fetches by. Nothing is invented on the way: what is sent to the API is a
 * tag value that came out of OSM, which is where the fetch will go looking for it.
 *
 * **The bounding box is the viewport, deliberately.** A tile-clipped feature knows only
 * the part of the road inside the tile, so its own extent is not the road's. What the
 * reader can see is a claim they made on purpose by framing it, it is what
 * `fetch_corridor` wants, and it is the thing that decides how much road gets assessed.
 * The panel beside the map says so rather than leaving it to be discovered.
 *
 * **This file draws no corridor.** Nothing has been fetched yet — the road on screen is
 * the basemap's own line, highlighted. The assessed corridor is a different picture,
 * drawn by `RunMapCanvas` after a run exists, from geometry the pipeline resolved.
 */

/** Shared with `RunMapCanvas` by `scripts/copy-map-worker.mjs`, which a test asserts. */
const WORKER_URL = "/maplibre/maplibre-gl-worker.mjs";

/** A style with no sources. Valid, complete, and it asks the network for nothing. */
const NO_BASEMAP = {
  version: 8 as const,
  sources: {},
  layers: [
    {
      id: "background",
      type: "background" as const,
      paint: { "background-color": "#f4f6f8" },
    },
  ],
};

const HIGHLIGHT_SOURCE = "picked-road";
const HIGHLIGHT_CASING = "picked-road-casing";
const HIGHLIGHT_LINE = "picked-road-line";

/**
 * The OpenMapTiles layers that carry roads, and the split that matters.
 *
 * **`transportation` has the geometry. `transportation_name` has the tags.** Measured
 * against the shipped basemap rather than assumed: at zoom 9 a road feature carries
 * `access, bicycle, brunnel, class, foot, horse, ramp` and **no `ref` and no `name`** —
 * the identity is in a separate layer that the style only starts drawing around zoom 12
 * and that is only rich by 14. So a click has to consult both, and a road with no label
 * *near this zoom* is not a road without a name.
 *
 * Queried by *source layer* rather than by style layer id, because layer ids belong to
 * whoever authored the style and an operator may point `$ROADRISK_MAP_STYLE` anywhere.
 * A source layer name is part of the published schema and survives a restyle in a way
 * `road_motorway_casing` does not.
 */
const ROAD_GEOMETRY_LAYER = "transportation";
const ROAD_LABEL_LAYER = "transportation_name";
const ROAD_SOURCE_LAYERS = [ROAD_GEOMETRY_LAYER, ROAD_LABEL_LAYER];

/**
 * Below this, no road anywhere carries an identity in the tiles, so a click cannot
 * possibly resolve one and saying "this road has no name" would be false rather than
 * unhelpful. Measured: nothing at 9, the first refs at 12, useful coverage at 14.
 */
const LABELS_APPEAR_AT = 12;

/** How far from the click to look for a label. Wider than the road hit, because a label
 *  feature is placed along part of a road rather than under the cursor. */
const LABEL_SEARCH_PX = 40;

export interface PickedRoad {
  /** "ref" or "name" — which tag identified it, and which selector the API is sent. */
  key: "ref" | "name";
  value: string;
  /** What to show the reader. The name, when a road has both. */
  label: string;
  /** The road class OSM gave it, for the "is this really a corridor?" hint. */
  highway: string | null;
}

/**
 * What a click resolved to. Three outcomes, and keeping them apart is the whole point:
 * "nothing here", "a road nobody can name *yet*", and "a road nobody can name at all"
 * are different sentences, and only the last one is about the road.
 */
export type PickOutcome =
  | { kind: "road"; road: PickedRoad }
  | { kind: "unlabelled"; zoomedEnough: boolean }
  | { kind: "nothing" };

export interface Viewport {
  /** south, west, north, east — this codebase's order everywhere. */
  bbox: [number, number, number, number];
}

export default function RoadPickerCanvas({
  basemap,
  centre,
  picked,
  onPick,
  onViewport,
  onExtent,
  onFailure,
}: {
  basemap: Basemap | null;
  /** Where to fly to when a search result is chosen. Null leaves the view alone. */
  centre: [number, number, number, number] | null;
  picked: PickedRoad | null;
  onPick: (outcome: PickOutcome) => void;
  onViewport: (viewport: Viewport) => void;
  /** How much of the picked road is in frame. Null when nothing is picked. */
  onExtent: (extent: Extent | null) => void;
  onFailure: (reason: string) => void;
}) {
  const container = useRef<HTMLDivElement | null>(null);
  const map = useRef<MapLibreMap | null>(null);
  const [ready, setReady] = useState(false);
  const readyRef = useRef(false);

  // Handlers are replaced every render; the map is built once. Refs mean the listeners
  // registered at construction always call the current ones, without tearing the map
  // down — which would throw away the reader's pan and zoom on every click.
  const pick = useRef(onPick);
  pick.current = onPick;
  const viewport = useRef(onViewport);
  viewport.current = onViewport;
  const extent = useRef(onExtent);
  extent.current = onExtent;
  const fail = useRef(onFailure);
  fail.current = onFailure;

  // What is picked, readable from listeners registered once at construction. The
  // measurement has to be redone on every pan and zoom, and `moveend` fires long after
  // the render that set this. Named for the ref rather than `chosen`, which is a local
  // inside the click handler and would shadow it exactly where both are in scope.
  const pickedRef = useRef<PickedRoad | null>(picked);
  pickedRef.current = picked;

  useEffect(() => {
    if (!container.current || map.current) return;

    setWorkerUrl(WORKER_URL);

    const instance = new MapLibreMap({
      container: container.current,
      style: basemap?.url ?? NO_BASEMAP,
      // Cyprus, because it is where the two validated corridors are. A world view puts
      // every road at one pixel and makes the first interaction a long pan.
      center: [33.2, 34.9],
      // Zoomed enough that roads carry their identity — below `LABELS_APPEAR_AT` the
      // tiles have no `ref` for anything and every click would resolve to nothing.
      zoom: LABELS_APPEAR_AT + 1,
      attributionControl: {
        compact: true,
        customAttribution: basemap?.credit ?? [],
      },
    });
    map.current = instance;

    instance.addControl(new NavigationControl({ showCompass: false }), "top-right");
    instance.addControl(new ScaleControl({ unit: "metric" }), "bottom-left");

    // Same rule as the run map: a MapLibre failure that only reaches the console looks
    // exactly like a map of an empty place.
    instance.on("error", (event) => {
      fail.current(
        event.error?.message ?? "MapLibre reported an error with no message.",
      );
    });

    const deadline = window.setTimeout(() => {
      if (!readyRef.current) {
        fail.current(
          "MapLibre did not finish loading. Its worker is served from " +
            `${WORKER_URL} — if that is a 404, run the shell's build so the copy step runs.`,
        );
      }
    }, 10_000);

    const start = () => {
      if (instance.getSource(HIGHLIGHT_SOURCE)) return;
      instance.addSource(HIGHLIGHT_SOURCE, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      instance.addLayer({
        id: HIGHLIGHT_CASING,
        type: "line",
        source: HIGHLIGHT_SOURCE,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#16191d", "line-width": 9, "line-opacity": 0.5 },
      });
      instance.addLayer({
        id: HIGHLIGHT_LINE,
        type: "line",
        source: HIGHLIGHT_SOURCE,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#1c4e80", "line-width": 4 },
      });
      readyRef.current = true;
      setReady(true);
      viewport.current({ bbox: boundsOf(instance) });
    };
    instance.on("styledata", start);
    instance.on("load", start);

    instance.on("moveend", () => viewport.current({ bbox: boundsOf(instance) }));

    // **Measured on `idle`, not on `moveend`.** The box is the viewport, so zooming out
    // after picking is exactly how a reader lengthens their corridor and the figure has
    // to follow it. But `moveend` fires when the *camera* stops, which is before the
    // tiles that move revealed have arrived — measuring there reads whatever happened to
    // be rendered already and reports it as the answer: too low, in the one direction
    // that matters, and never corrected, because no further event is coming. `idle` is
    // the map saying it has finished drawing everything it is going to.
    instance.on("idle", () =>
      remeasure(instance, pickedRef.current, extent.current),
    );

    instance.on("click", (event) => {
      // A generous box rather than the exact pixel: a road is a few pixels wide and a
      // finger is not a mouse. The same reason `RunMapCanvas` carries a wide hit layer.
      const near = 6;
      const box = (radius: number) =>
        [
          [event.point.x - radius, event.point.y - radius],
          [event.point.x + radius, event.point.y + radius],
        ] as [[number, number], [number, number]];

      // No `layers` filter anywhere here: which style layers exist is the style
      // author's business. Filtering by source layer is what survives a basemap an
      // operator chose.
      const under = instance
        .queryRenderedFeatures(box(near))
        .filter((feature) =>
          ROAD_SOURCE_LAYERS.includes(String(feature.sourceLayer ?? "")),
        );

      if (under.length === 0) {
        pick.current({ kind: "nothing" });
        highlight(instance, []);
        extent.current(null);
        return;
      }

      // The identity is in the label layer, and a label sits *along* a road rather than
      // under the cursor — so it is looked for over a wider radius than the road itself.
      const labels = instance
        .queryRenderedFeatures(box(LABEL_SEARCH_PX))
        .filter(
          (feature) => String(feature.sourceLayer ?? "") === ROAD_LABEL_LAYER,
        );

      const chosen = labels.map(selectorOf).find((road) => road !== null) ?? null;

      if (chosen === null) {
        // **Not "this road has no name".** At low zoom the tiles carry no identity for
        // any road, so that sentence would be false; the reader is told which of the
        // two situations they are in.
        pick.current({
          kind: "unlabelled",
          zoomedEnough: instance.getZoom() >= LABELS_APPEAR_AT,
        });
        highlight(instance, under.slice(0, 1));
        extent.current(null);
        return;
      }

      pick.current({ kind: "road", road: chosen });
      // Every labelled piece of the same road on screen, so the highlight reads as a
      // corridor rather than as the one tile-clipped fragment that was clicked.
      highlight(
        instance,
        labels.filter((feature) => {
          const other = selectorOf(feature);
          return other?.key === chosen.key && other?.value === chosen.value;
        }),
      );
      remeasure(instance, chosen, extent.current);
    });

    // The cursor is the only affordance saying the map is clickable at all.
    instance.on("mousemove", (event) => {
      const near = 6;
      const hit = instance
        .queryRenderedFeatures([
          [event.point.x - near, event.point.y - near],
          [event.point.x + near, event.point.y + near],
        ])
        .some((feature) =>
          ROAD_SOURCE_LAYERS.includes(String(feature.sourceLayer ?? "")),
        );
      instance.getCanvas().style.cursor = hit ? "pointer" : "";
    });

    return () => {
      window.clearTimeout(deadline);
      instance.remove();
      map.current = null;
      readyRef.current = false;
    };
    // Built once. `basemap` cannot change without a reload, because it is read from the
    // server's environment; the rest is held in refs on purpose.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Fly to a chosen search result. Separate from construction so that searching again
  // moves the map rather than rebuilding it.
  useEffect(() => {
    if (!map.current || !ready || centre === null) return;
    const [south, west, north, east] = centre;
    map.current.fitBounds(
      [
        [west, south],
        [east, north],
      ],
      { padding: 40, duration: 800 },
    );
  }, [centre, ready]);

  // Clearing the selection from the panel has to clear the line on the map too.
  useEffect(() => {
    if (map.current && ready && picked === null) highlight(map.current, []);
  }, [picked, ready]);

  return (
    <div className="shell-map-frame">
      <div ref={container} className="shell-map" aria-label="Map for choosing a road" />
      {ready ? null : (
        <p className="shell-map__waiting">Loading the map…</p>
      )}
    </div>
  );
}

/** The viewport as south, west, north, east — the order everything else here uses. */
function boundsOf(instance: MapLibreMap): [number, number, number, number] {
  const bounds = instance.getBounds();
  return [
    bounds.getSouth(),
    bounds.getWest(),
    bounds.getNorth(),
    bounds.getEast(),
  ];
}

/**
 * Which tag identifies this road, if either.
 *
 * `ref` first, because that is the selector with a guarantee behind it: a reference is
 * effectively unique inside a sensible box, and a name is not. The label prefers the
 * name, because "Troodos Road" tells a reader more than "B9" — but what is *sent* is
 * always the reference when there is one.
 */
function selectorOf(feature: {
  properties?: Record<string, unknown> | null;
}): PickedRoad | null {
  const properties = feature.properties ?? {};
  const ref = text(properties.ref);
  const name = text(properties.name);
  const highway = text(properties.class) ?? text(properties.highway);

  if (ref) return { key: "ref", value: ref, label: name ?? ref, highway };
  if (name) return { key: "name", value: name, label: name, highway };
  return null;
}

function text(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  // OSM puts several references on one road as "A1;B9". Splitting would guess which one
  // the reader meant, so a multi-valued ref is treated as no ref and the name is used.
  if (!trimmed || trimmed.includes(";")) return null;
  return trimmed;
}

/**
 * How much of the picked road is in the frame, reported to the panel.
 *
 * **The query takes no geometry argument**, unlike the two in the click handler. Those
 * ask *what is under the cursor*; this asks *what is on screen*, because the box the API
 * will be sent is the viewport and the answer has to be about the same area. Passing a
 * box here would measure the road near where somebody happened to click, which is a
 * different question with a plausible-looking answer.
 *
 * Failure is silent by design: this is a hint beside a button, and a basemap whose schema
 * does not match the one assumed here should cost the reader that hint and nothing else.
 * The pick itself has already succeeded by the time this runs.
 */
function remeasure(
  instance: MapLibreMap,
  road: PickedRoad | null,
  report: (extent: Extent | null) => void,
): void {
  if (road === null) {
    report(null);
    return;
  }
  try {
    const mine = instance
      .queryRenderedFeatures()
      .filter(
        (feature) => String(feature.sourceLayer ?? "") === ROAD_LABEL_LAYER,
      )
      .filter((feature) => {
        const other = selectorOf(feature);
        return other?.key === road.key && other?.value === road.value;
      });
    const metres = totalLength(mine);
    report(metres > 0 ? extentOf(metres) : null);
  } catch {
    report(null);
  }
}

function highlight(
  instance: MapLibreMap,
  features: { geometry: unknown }[],
): void {
  const source = instance.getSource(HIGHLIGHT_SOURCE);
  if (!source || !("setData" in source)) return;
  (source as { setData: (data: unknown) => void }).setData({
    type: "FeatureCollection",
    features: features.map((feature) => ({
      type: "Feature",
      properties: {},
      geometry: feature.geometry,
    })),
  });
}
