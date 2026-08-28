"use client";

import dynamic from "next/dynamic";
import { useRef, useState, useTransition } from "react";

import type { Basemap } from "@/lib/api";
import type { Place } from "@/lib/geocode";
import type { PickedRoad, PickOutcome } from "./RoadPickerCanvas";

/**
 * MapLibre loads only in the browser, and only on this route.
 *
 * `ssr: false` is a requirement, not a saving: MapLibre touches `window` while it is
 * being imported. The saving comes with it — the library is about a megabyte and stays
 * out of every other route's bundle.
 */
const RoadPickerCanvas = dynamic(() => import("./RoadPickerCanvas"), {
  ssr: false,
  loading: () => (
    <div className="shell-map shell-map--waiting">
      <p>Loading the map…</p>
    </div>
  ),
});

/**
 * The front door: find a road, pick it, add crashes if you have them, assess.
 *
 * **What this screen is for.** Assessing one road used to be five screens — a project, a
 * corridor typed as a reference and four decimal bounding-box numbers, a job form of ten
 * fields, a poll, and then a hunt for the run. Every one of those is a real object and
 * they all still exist under *Advanced*; none of them is a question somebody arriving
 * with a road in mind can answer.
 *
 * **The reader is never asked for a bounding box.** It is the viewport, which they set by
 * framing the road they can see. That is stated on the page rather than left to be
 * discovered, because it is the input that decides how much road gets assessed.
 *
 * **The crash file is the one thing worth insisting on.** Without it the engine has no
 * counts to fit and the run can only be Mode B — a ranking, not a model. So the panel
 * says that where the file is chosen, not in a footnote afterwards.
 */
export default function RoadPicker({
  basemap,
  searchEnabled,
  geocoderCredit,
  action,
  problem,
}: {
  basemap: Basemap | null;
  searchEnabled: boolean;
  geocoderCredit: string | null;
  action: (form: FormData) => void | Promise<void>;
  problem: string | null;
}) {
  const [picked, setPicked] = useState<PickedRoad | null>(null);
  const [missed, setMissed] = useState<PickOutcome | null>(null);
  const [bbox, setBbox] = useState<[number, number, number, number] | null>(null);
  const [centre, setCentre] = useState<[number, number, number, number] | null>(null);
  const [mapProblem, setMapProblem] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [places, setPlaces] = useState<Place[]>([]);
  const [searchProblem, setSearchProblem] = useState<string | null>(null);
  const [searching, startSearching] = useTransition();
  const debounce = useRef<number | null>(null);

  const [crashFile, setCrashFile] = useState<string | null>(null);

  function onPick(outcome: PickOutcome) {
    if (outcome.kind === "road") {
      setMissed(null);
      setPicked(outcome.road);
      return;
    }
    setPicked(null);
    setMissed(outcome);
  }

  function runSearch(text: string) {
    setQuery(text);
    if (debounce.current !== null) window.clearTimeout(debounce.current);
    if (text.trim().length < 2) {
      setPlaces([]);
      return;
    }
    // Nominatim's policy is one request a second. Typing is faster than that, so the
    // request is what waits rather than the typist.
    debounce.current = window.setTimeout(() => {
      startSearching(async () => {
        setSearchProblem(null);
        try {
          const response = await fetch(
            `/api/places?q=${encodeURIComponent(text)}`,
          );
          if (!response.ok) throw new Error(await response.text());
          setPlaces(await response.json());
        } catch (error) {
          setPlaces([]);
          setSearchProblem(
            error instanceof Error
              ? error.message
              : "The place search did not answer. Pan and zoom to the road instead.",
          );
        }
      });
    }, 600);
  }

  const ready = picked !== null && bbox !== null;

  return (
    <div className="shell-picker-layout">
      <RoadPickerCanvas
        basemap={basemap}
        centre={centre}
        picked={picked}
        onPick={onPick}
        onViewport={(viewport) => setBbox(viewport.bbox)}
        onFailure={setMapProblem}
      />

      <form className="shell-picker-panel shell-form" action={action}>
        {problem ? <p className="shell-problem">{problem}</p> : null}
        {mapProblem ? (
          <p className="shell-problem">
            The map failed: {mapProblem} You can still assess a road by typing its
            reference under <em>Advanced</em>.
          </p>
        ) : null}

        <section className="shell-step">
          <h2>
            <span className="shell-step__n">1</span> Find the road
          </h2>
          {searchEnabled ? (
            <>
              <label>
                <span className="shell-visually-hidden">Search for a place</span>
                <input
                  type="search"
                  value={query}
                  placeholder="A town, a region, an address…"
                  onChange={(event) => runSearch(event.target.value)}
                />
              </label>
              {searching ? <p className="shell-note">Searching…</p> : null}
              {searchProblem ? (
                <p className="shell-problem">{searchProblem}</p>
              ) : null}
              {places.length > 0 ? (
                <ul className="shell-places">
                  {places.map((place) => (
                    <li key={place.label}>
                      <button
                        type="button"
                        onClick={() => {
                          setCentre(place.bbox);
                          setPlaces([]);
                          setQuery(place.label);
                        }}
                      >
                        {place.label}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
            </>
          ) : (
            <p className="shell-note">
              Place search is switched off in this deployment. Pan and zoom the map to
              the road.
            </p>
          )}
        </section>

        <section className="shell-step">
          <h2>
            <span className="shell-step__n">2</span> Click the road
          </h2>

          {picked ? (
            <div className="shell-picked">
              <p className="shell-picked__name">{picked.label}</p>
              <p className="shell-note">
                Identified by its OSM{" "}
                {picked.key === "ref" ? "reference" : "name"}{" "}
                <code>{picked.value}</code>
                {picked.highway ? ` · ${picked.highway}` : null}
              </p>
              {picked.key === "name" ? (
                <p className="shell-note">
                  This road carries no reference, so it is fetched by name. A name is
                  not unique the way a reference is — if the area below holds two roads
                  of this name, the fetch is refused rather than welding them together.
                </p>
              ) : null}
              <button
                type="button"
                className="shell-button shell-button--quiet"
                onClick={() => setPicked(null)}
              >
                Choose a different road
              </button>
            </div>
          ) : missed?.kind === "unlabelled" && !missed.zoomedEnough ? (
            // The distinction that stops this screen saying something false. The tiles
            // carry no road identity at all below about zoom 12, so at this zoom
            // "that road has no name" would be a statement about the map, dressed up
            // as a statement about the road.
            <p className="shell-note">
              That is a road, but at this zoom the map carries no name or reference for
              it. <strong>Zoom in and click it again.</strong>
            </p>
          ) : missed?.kind === "unlabelled" ? (
            <p className="shell-problem">
              That road carries neither a reference nor a name in OpenStreetMap, so
              there is nothing to fetch it by. Try a larger road — or add the tag in
              OSM, and it will be selectable here.
            </p>
          ) : missed?.kind === "nothing" ? (
            <p className="shell-note">
              No road there. Click directly on the line of the road you want.
            </p>
          ) : (
            <p className="shell-note">
              Click a road on the map. Motorways, trunk and primary roads almost always
              carry a reference; smaller streets are matched by name.
            </p>
          )}

          <p className="shell-note">
            <strong>The map view is the search area.</strong> The road is fetched from
            OpenStreetMap inside whatever the map is showing, so frame the stretch you
            want assessed — a wider view assesses more road and takes longer.
          </p>
        </section>

        <section className="shell-step">
          <h2>
            <span className="shell-step__n">3</span> Crashes
            <span className="shell-step__optional">optional</span>
          </h2>
          <label>
            <span className="shell-hint">
              A CSV with <code>latitude</code>, <code>longitude</code> and{" "}
              <code>period</code>. One row per crash.
            </span>
            <input
              type="file"
              name="crashes"
              accept=".csv,text/csv"
              onChange={(event) =>
                setCrashFile(event.target.files?.[0]?.name ?? null)
              }
            />
          </label>
          {crashFile ? (
            <p className="shell-note">
              <code>{crashFile}</code>
            </p>
          ) : null}
          <p className="shell-note">
            <strong>This is what decides how much the assessment can say.</strong> With
            a crash table the engine can fit a model and report expected counts with
            intervals. Without one it scores a ranking from published weights and says
            so on every screen — never a prediction, and never a count.
          </p>
        </section>

        {/* The picked road and the viewport travel as hidden fields so the form is a
            plain POST. Everything above is a client component because a map is; the
            submission is not, and does not need to be. */}
        <input type="hidden" name="selector_key" value={picked?.key ?? ""} />
        <input type="hidden" name="selector_value" value={picked?.value ?? ""} />
        <input type="hidden" name="label" value={picked?.label ?? ""} />
        <input type="hidden" name="south" value={bbox?.[0] ?? ""} />
        <input type="hidden" name="west" value={bbox?.[1] ?? ""} />
        <input type="hidden" name="north" value={bbox?.[2] ?? ""} />
        <input type="hidden" name="east" value={bbox?.[3] ?? ""} />

        <button type="submit" className="shell-button" disabled={!ready}>
          {ready ? `Assess ${picked.label}` : "Pick a road first"}
        </button>

        <p className="shell-note">
          The road is fetched from OpenStreetMap and cut into 500 m segments. A cold
          fetch takes under a minute; the next road in the same region is seconds.
        </p>

        {geocoderCredit ? (
          <p
            className="shell-credit"
            dangerouslySetInnerHTML={{ __html: geocoderCredit }}
          />
        ) : null}
      </form>
    </div>
  );
}
