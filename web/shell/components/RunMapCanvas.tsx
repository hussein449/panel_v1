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
import type { BoundaryCollection, Bounds, UnitCollection } from "@/lib/corridor";

/**
 * The corridor on a MapLibre map. This file is the only one that knows MapLibre exists.
 *
 * **There is a basemap, and it is the one place in this product that fetches from
 * somebody else.** A road drawn on nothing tells a reader the shape of a corridor and not
 * where it is, and *where it is* is most of what a map is opened for — so the network
 * dependency and the attribution obligation are paid deliberately and stated on the page.
 * They belong to the screen and stop there: the report's corridor is inline SVG, and a
 * test asserts the shipped `report.html` contains neither MapLibre nor a tile URL.
 * `$ROADRISK_MAP_STYLE=none` restores a map that asks the network for nothing — one
 * background layer, no sources — for a deployment that has to work that way.
 *
 * **This file draws no text of its own.** The basemap has its labels; adding a symbol
 * layer here would make MapLibre fetch glyph ranges for it, and with the basemap off that
 * would put a request back into a map that says it makes none. Labels belong to the panel
 * beside it.
 *
 * The corridor's colours are computed before they reach here — `unitFeatures` puts a
 * `colour` on every feature from the report library's own ramp, so the map cannot drift
 * from the document about which segment is the dangerous one. The boundary ticks come
 * the same way, from `boundaryFeatures`.
 */

/**
 * Where the worker is served from. `scripts/copy-map-worker.mjs` puts it there, and a
 * test asserts the two agree — the failure when they do not is a map that draws a canvas,
 * mounts its controls and never loads, which looks like a map with nothing on it rather
 * than like a fault. See that script for the whole story.
 */
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

const CASING = "corridor-casing";
const LINE = "corridor";
const SELECTED = "corridor-selected";
const HIT = "corridor-hit";
const SOURCE = "corridor-units";
const BOUNDARIES = "corridor-boundaries";
const BOUNDARY_LINE = "corridor-boundary-ticks";

/**
 * Widths by zoom, so the corridor reads at both ends of the scale.
 *
 * A fixed width is either a hairline over a whole region or a bandage over one junction.
 * Every line below is an interpolation of the same three stops, which is what keeps the
 * casing, the road and the selection halo in proportion to each other as the reader
 * zooms.
 *
 * The return type is written out rather than inferred: TypeScript widens
 * `["interpolate", …]` to `(string | number | string[])[]`, which is no longer a style
 * expression as far as MapLibre's types are concerned. Spelling the tuple keeps the
 * literals literal.
 */
type ByZoom = [
  "interpolate",
  ["linear"],
  ["zoom"],
  number,
  number,
  number,
  number,
  number,
  number,
];

const width = (at8: number, at12: number, at16: number): ByZoom => [
  "interpolate",
  ["linear"],
  ["zoom"],
  8,
  at8,
  12,
  at12,
  16,
  at16,
];

export default function RunMapCanvas({
  units,
  boundaries,
  extent,
  basemap,
  selected,
  onSelect,
  onFailure,
}: {
  units: UnitCollection;
  boundaries: BoundaryCollection;
  extent: Bounds;
  basemap: Basemap | null;
  selected: string | null;
  onSelect: (unitId: string | null) => void;
  onFailure: (reason: string) => void;
}) {
  const container = useRef<HTMLDivElement | null>(null);
  const map = useRef<MapLibreMap | null>(null);
  const chosen = useRef<number | null>(null);

  // Whether the corridor is actually on the map yet. Shown rather than assumed: a
  // MapLibre map that never finishes loading looks exactly like a map of an empty place,
  // and that is how a broken worker went unnoticed here for an afternoon. The ref is what
  // the deadline below reads — state would be the value captured when it was set.
  const [drawn, setDrawn] = useState(false);
  const drawnRef = useRef(false);

  // The click handler is replaced on every render; the map is not. Holding it in a ref
  // means the listener registered once always calls the current one, without tearing the
  // map down and rebuilding it — which would lose the reader's pan and zoom on every
  // selection.
  const select = useRef(onSelect);
  select.current = onSelect;
  const fail = useRef(onFailure);
  fail.current = onFailure;

  useEffect(() => {
    if (!container.current || map.current) return;

    // Before the map exists, because it is read as the first worker is spawned.
    setWorkerUrl(WORKER_URL);

    const instance = new MapLibreMap({
      container: container.current,
      style: basemap?.url ?? NO_BASEMAP,
      bounds: [extent[0], extent[1], extent[2], extent[3]],
      fitBoundsOptions: { padding: 48 },
      attributionControl: {
        compact: true,
        // Stated, not discovered. MapLibre does read credit out of a source's TileJSON,
        // and the default basemap's carries it — but only once that source has loaded and
        // the control has repainted, and it was seen showing nothing at all in a tab that
        // had not rendered. An attribution that depends on the rendering lifecycle is not
        // an attribution. MapLibre de-duplicates what it then finds for itself.
        customAttribution: [
          "Corridor geometry: this run",
          ...(basemap?.credit ?? []),
        ],
      },
    });
    map.current = instance;

    instance.addControl(new NavigationControl({ showCompass: false }), "top-right");
    instance.addControl(new ScaleControl({ unit: "metric" }), "bottom-left");

    // **A map that cannot draw has to say so.** MapLibre reports its failures on this
    // event and then carries on looking like a map: a canvas, controls, and nothing on
    // it. That is indistinguishable from a corridor with no geometry, and it is how a
    // broken worker survived a whole afternoon here. Anything that goes wrong now
    // reaches the screen instead of the console.
    instance.on("error", (event) => {
      fail.current(event.error?.message ?? "MapLibre reported an error with no message.");
    });

    // A map that never finishes loading is the failure this whole page has to be able to
    // report. MapLibre has no event for *not* happening, so it is a deadline: if the
    // corridor is not on the map by now, say so rather than leaving a grey rectangle.
    const deadline = window.setTimeout(() => {
      if (!drawnRef.current) {
        fail.current(
          "MapLibre did not finish loading. Its worker is served from " +
            `${WORKER_URL} — if that is a 404, run the shell's build so the copy step runs.`,
        );
      }
    }, 10_000);

    // **Whichever of the two comes first.** What this needs is a style ready to take a
    // source; `styledata` says exactly that, and `load` says it plus *and the map has
    // painted a frame*. Listening for both and guarding on the source already existing
    // makes it once-only whichever way round they arrive, and means a browser that never
    // paints — a background tab, where `requestAnimationFrame` does not run — is one
    // fewer thing that can leave this screen grey with no explanation.
    const start = () => {
      if (instance.getSource(SOURCE)) return;
      try {
        addCorridor(instance);
      } catch (error) {
        // Not left to an uncaught exception inside a MapLibre event handler, which
        // reaches the console and nowhere a reader will look.
        fail.current(
          error instanceof Error ? error.message : "The corridor could not be drawn.",
        );
      }
    };
    instance.on("styledata", start);
    instance.on("load", start);

    function addCorridor(instance: MapLibreMap) {
      instance.addSource(SOURCE, { type: "geojson", data: units });
      instance.addSource(BOUNDARIES, { type: "geojson", data: boundaries });

      // Under the road: a dark casing, because the basemap is pale and a pale segment at
      // the light end of the risk ramp would otherwise dissolve into it.
      instance.addLayer({
        id: CASING,
        type: "line",
        source: SOURCE,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": "#1f2328",
          "line-width": width(7, 10, 15),
          "line-opacity": 0.55,
        },
      });

      // A halo under the selected segment only. Feature state rather than a filter, so
      // choosing one repaints a line instead of rebuilding a source.
      instance.addLayer({
        id: SELECTED,
        type: "line",
        source: SOURCE,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": "#16191d",
          "line-width": width(11, 15, 21),
          "line-opacity": [
            "case",
            ["boolean", ["feature-state", "selected"], false],
            1,
            0,
          ],
        },
      });

      instance.addLayer({
        id: LINE,
        type: "line",
        source: SOURCE,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": ["get", "colour"], "line-width": width(3, 6, 11) },
      });

      // The segmentation, drawn across the road. The ranking is per segment and a
      // blackspot is a run of them, so where one unit ends and the next begins is part of
      // the answer rather than an implementation detail — and colour alone cannot show it,
      // since two neighbours of the same rank are the same shade.
      instance.addLayer({
        id: BOUNDARY_LINE,
        type: "line",
        source: BOUNDARIES,
        layout: { "line-cap": "butt" },
        paint: {
          "line-color": "#16191d",
          "line-width": width(1, 1.6, 2.6),
          // Invisible where the whole corridor is a few pixels long; there is nothing to
          // divide at that scale and twenty ticks would read as a smudge on the road.
          "line-opacity": [
            "interpolate",
            ["linear"],
            ["zoom"],
            9,
            0,
            11,
            0.85,
          ],
        },
      });

      // Invisible and twenty pixels wide, purely so that a segment can be hit on a phone.
      // A five-pixel line is a target nobody can reliably touch, and a map whose whole
      // point is clicking a segment cannot make that the reader's problem.
      instance.addLayer({
        id: HIT,
        type: "line",
        source: SOURCE,
        paint: { "line-color": "#000000", "line-width": 20, "line-opacity": 0 },
      });

      instance.on("click", HIT, (event) => {
        const feature = event.features?.[0];
        if (feature) select.current(String(feature.properties?.unit_id ?? ""));
      });

      // A click on the background clears the selection. Without it the only way out of a
      // selected segment is to pick another one, which is a trap rather than an affordance.
      instance.on("click", (event) => {
        const hits = instance.queryRenderedFeatures(event.point, { layers: [HIT] });
        if (hits.length === 0) select.current(null);
      });

      instance.on("mouseenter", HIT, () => {
        instance.getCanvas().style.cursor = "pointer";
      });
      instance.on("mouseleave", HIT, () => {
        instance.getCanvas().style.cursor = "";
      });

      drawnRef.current = true;
      setDrawn(true);
    }

    return () => {
      window.clearTimeout(deadline);
      instance.remove();
      map.current = null;
    };
  }, [units, boundaries, extent, basemap]);

  // Selection is feature state rather than a filter, so choosing a segment repaints one
  // line instead of rebuilding the source.
  useEffect(() => {
    const instance = map.current;
    if (!instance) return;

    const apply = () => {
      if (!instance.getSource(SOURCE)) {
        // The corridor is not on the map yet; the source arrives with `selected` already
        // set only when a reader lands here from a link. Re-run when it does.
        instance.once("styledata", apply);
        return;
      }
      if (chosen.current !== null) {
        instance.setFeatureState(
          { source: SOURCE, id: chosen.current },
          { selected: false },
        );
        chosen.current = null;
      }
      const feature = units.features.find(
        (candidate) => candidate.properties.unit_id === selected,
      );
      if (feature) {
        instance.setFeatureState({ source: SOURCE, id: feature.id }, { selected: true });
        chosen.current = feature.id;
      }
    };

    apply();
  }, [selected, units]);

  return (
    <div className="shell-map-frame">
      <div className="shell-map" ref={container} />
      {drawn ? null : (
        <p className="shell-map__waiting" role="status">
          Putting the corridor on the map…
        </p>
      )}
    </div>
  );
}
