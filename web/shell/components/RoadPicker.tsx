"use client";

import dynamic from "next/dynamic";
import { useRef, useState, useTransition } from "react";

import type { Basemap } from "@/lib/api";
import type { Place } from "@/lib/geocode";
import { type Extent, describeLength } from "@/lib/measure";
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
 * **The map is the page, and the controls are a strip under it.**
 *
 * This was a 24rem sidebar of five numbered steps, and it did not work. Each step
 * carried several paragraphs explaining why it mattered — all of it true, most of it
 * worth saying once — and a narrow column is the worst possible place to put an essay.
 * The result was a page you scrolled past a map you could barely see, to reach a button
 * at the bottom of an argument. Squeezing a map to make room for prose about the map is
 * the wrong trade in both directions.
 *
 * So: the map gets the full width, the two controls that belong *to* the map live on it
 * — search, and what you picked — and everything the form needs is one row underneath.
 *
 * **The prose is not deleted, it is folded.** Every explanation that was shouting is
 * behind a disclosure next to the control it explains. That distinction matters here
 * more than on most screens, because some of this text is load-bearing: the extent
 * verdict caught a run that assessed 1.83 km of a 2.95 km road and produced four
 * segments, and nothing else on the page would have said so. So the verdict itself
 * stays visible, on the map, in colour; the paragraph explaining how it is estimated
 * folds away.
 *
 * **The reader is never asked for a bounding box.** It is the viewport, which they set
 * by framing the road they can see.
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
  const [extent, setExtent] = useState<Extent | null>(null);
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
    setExtent(null);
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
          const response = await fetch(`/api/places?q=${encodeURIComponent(text)}`);
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

  /** What the map is currently telling the reader, in one line. */
  const status = picked
    ? null
    : missed?.kind === "unlabelled" && !missed.zoomedEnough
      ? "That is a road, but the map carries no name for it at this zoom. Zoom in and click again."
      : missed?.kind === "unlabelled"
        ? "That road has neither a reference nor a name in OpenStreetMap, so there is nothing to fetch it by. Try a larger road."
        : missed?.kind === "nothing"
          ? "No road there — click directly on the line."
          : "Click a road on the map to begin.";

  return (
    <form className="picker" action={action}>
      {problem ? <p className="shell-problem">{problem}</p> : null}
      {mapProblem ? (
        <p className="shell-problem">
          The map failed: {mapProblem} You can still assess a road by typing its
          reference under <em>Advanced</em>.
        </p>
      ) : null}

      <div className="picker__stage">
        <RoadPickerCanvas
          basemap={basemap}
          centre={centre}
          picked={picked}
          onPick={onPick}
          onViewport={(viewport) => setBbox(viewport.bbox)}
          onExtent={setExtent}
          onFailure={setMapProblem}
        />

        {/* Search belongs to the map, so it sits on it. It was in the sidebar, two
            scroll positions away from the thing it moves. */}
        {searchEnabled ? (
          <div className="picker__search">
            <input
              type="search"
              value={query}
              placeholder="Search a town, region or address…"
              aria-label="Search for a place"
              onChange={(event) => runSearch(event.target.value)}
            />
            {searching ? <p className="picker__searching">Searching…</p> : null}
            {searchProblem ? (
              <p className="picker__search-problem">{searchProblem}</p>
            ) : null}
            {places.length > 0 ? (
              <ul className="picker__places">
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
          </div>
        ) : null}

        {/* What you picked, over the road you picked. The extent verdict is here rather
            than folded away because it is the one thing on this screen that has already
            caught a bad run before it happened. */}
        <div className={`picker__chip${picked ? " picker__chip--picked" : ""}`}>
          {picked ? (
            <>
              <div className="picker__chip-head">
                <strong>{picked.label}</strong>
                <button
                  type="button"
                  className="picker__clear"
                  onClick={() => {
                    setPicked(null);
                    setExtent(null);
                  }}
                >
                  Change
                </button>
              </div>
              <p className="picker__chip-note">
                OSM {picked.key === "ref" ? "reference" : "name"}{" "}
                <code>{picked.value}</code>
                {picked.highway ? ` · ${picked.highway}` : null}
              </p>
              {extent ? (
                <p className={`picker__extent picker__extent--${extent.verdict}`}>
                  ≈ {describeLength(extent.metres)} in view · {extent.segments} segment
                  {extent.segments === 1 ? "" : "s"}
                  {extent.verdict === "too-short" ? (
                    <span> — too short to assess well. Zoom out.</span>
                  ) : extent.verdict === "thin" ? (
                    <span> — workable but thin. Zoom out if there is more road.</span>
                  ) : (
                    <span> — enough to separate.</span>
                  )}
                </p>
              ) : null}
            </>
          ) : (
            <p className="picker__chip-note">{status}</p>
          )}
        </div>
      </div>

      {/* One row. Everything the run needs, and nothing that only explains it. */}
      <div className="picker__controls">
        <label className="control">
          <span className="control__label">Road type</span>
          <select name="facility_type" defaultValue="any">
            <option value="any">Not declared</option>
            <option value="rural_two_lane">Rural two-lane</option>
            <option value="rural_multilane">Rural multilane</option>
            <option value="urban_arterial">Urban arterial</option>
            <option value="motorway">Motorway</option>
          </select>
        </label>

        <label className="control">
          <span className="control__label">Region</span>
          <select name="region" defaultValue="global">
            <option value="global">Not declared</option>
            <option value="north_america">North America</option>
            <option value="europe">Europe</option>
            <option value="australasia">Australasia</option>
            <option value="asia">Asia</option>
            <option value="africa">Africa</option>
            <option value="middle_east">Middle East</option>
            <option value="latin_america">Latin America</option>
          </select>
        </label>

        <label className="control">
          <span className="control__label">Crashes counted</span>
          <select name="severity" defaultValue="all">
            <option value="all">All crashes</option>
            <option value="injury">Injury</option>
            <option value="fsi">Fatal and serious</option>
            <option value="fatal">Fatal only</option>
          </select>
        </label>

        <div className="control control--wide">
          <span className="control__label">Also measure</span>
          <div className="control__toggles">
            <label title="Gradient from the Copernicus 30 m elevation model and built-up share from ESA WorldCover. Gradient carries a cited weight. Adds about a minute.">
              <input type="checkbox" name="fetch_rasters" />
              <span>Hills &amp; land use</span>
            </label>
            <label title="Betweenness centrality over the surrounding network. Never called AADT and carries no volume units. The slowest option: several minutes.">
              <input type="checkbox" name="fetch_traffic" />
              <span>Traffic proxy</span>
            </label>
            <label title="Poles, sign supports and bollards from Mapillary's published detections. No cited weight yet, so it appears in provenance and not in the score.">
              <input type="checkbox" name="fetch_mapillary" />
              <span>Roadside objects</span>
            </label>
            <label title="Looks for street-level photographs along the corridor. A recent one is direct evidence the road was passable; finding none is weak evidence of anything.">
              <input type="checkbox" name="check_imagery" />
              <span>Driven check</span>
            </label>
          </div>
        </div>

        <label className="control control--wide">
          <span className="control__label">
            Crash table <span className="control__hint">CSV · optional</span>
          </span>
          <input
            type="file"
            name="crashes"
            accept=".csv,text/csv"
            onChange={(event) => setCrashFile(event.target.files?.[0]?.name ?? null)}
          />
          <span className="control__state">
            {crashFile ? (
              <code>{crashFile}</code>
            ) : (
              "Without one this is a ranking, not a model."
            )}
          </span>
        </label>

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

        <button type="submit" className="picker__go" disabled={!ready}>
          {ready ? `Assess ${picked.label}` : "Pick a road first"}
        </button>
      </div>

      {/* Everything that was shouting from the sidebar, kept and folded. A reader who
          wants to know why a field matters is one click away; a reader who does not is
          not scrolling past it to reach the button. */}
      <details className="picker__more">
        <summary>What these choices do</summary>
        <div className="picker__more-body">
          <p>
            <strong>The map view is the search area.</strong> The road is fetched from
            OpenStreetMap inside whatever the map is showing, so frame the stretch you
            want assessed — a wider view assesses more road and takes longer. The length
            readout on the map is estimated from the map&rsquo;s own geometry, which is
            simplified as you zoom out; read it as the difference between four segments
            and forty, not as a measurement.
          </p>
          <p>
            <strong>Road type decides how much published evidence is admissible.</strong>{" "}
            A weight is a number plus the context it is valid in, and one whose scope does
            not match this corridor is inadmissible rather than approximate. Left
            undeclared, only weights that state no scope at all can be used — on a real
            run that meant eleven factors measured and one scored. Declaring{" "}
            <strong>motorway</strong> admits fewer weights than the others, not more: it
            is there so a motorway need not be declared as a rural two-lane road, which
            would admit driveway-density evidence for a road that has no driveways.
          </p>
          <p>
            <strong>Region mismatches are reported, never refused.</strong> Most published
            weights are North American, and refusing them would leave nothing usable
            elsewhere. Match <strong>crashes counted</strong> to your file — a
            fatal-crash weight never scores an injury panel.
          </p>
          <p>
            <strong>OpenStreetMap is always fetched</strong> — one request, and it carries
            most of the road. The four toggles are the other sources, each its own fetch,
            each off until asked for, and each adds factors the assessment would otherwise
            report as absent. Any of them can be unavailable where this is deployed: the
            last two need a free Mapillary token, and hills and land use need the{" "}
            <code>raster</code> extra. When one is missing it is skipped with a note, the
            other factors are unaffected, and nothing about the run is silently different.
          </p>
          <p>
            <strong>The crash table decides how much the assessment can say.</strong> A
            CSV with <code>latitude</code>, <code>longitude</code> and{" "}
            <code>period</code>, one row per crash. With it the engine fits a model and
            reports expected counts with intervals. Without it it scores a ranking from
            published weights and says so on every screen — never a prediction, never a
            count. The engine picks the mode; nothing on this page overrules it.
          </p>
          <p className="shell-note">
            The road is cut into 500 m segments. A cold fetch takes under a minute; the
            next road in the same region is seconds.
          </p>
          {geocoderCredit ? (
            <p
              className="shell-credit"
              dangerouslySetInnerHTML={{ __html: geocoderCredit }}
            />
          ) : null}
        </div>
      </details>
    </form>
  );
}
