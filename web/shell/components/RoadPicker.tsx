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
        onExtent={setExtent}
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

              {/* The number the first real run of this page needed and did not have. It
                  assessed 1.83 km of a 2.95 km road, produced four segments, and the
                  collinearity check returned infinity — all decided by a zoom level,
                  before the button was pressed, with nothing on screen saying so. */}
              {extent ? (
                <div className={`shell-extent shell-extent--${extent.verdict}`}>
                  <p className="shell-extent__figure">
                    ≈ {describeLength(extent.metres)} in view ·{" "}
                    <strong>
                      about {extent.segments} segment
                      {extent.segments === 1 ? "" : "s"}
                    </strong>
                  </p>
                  {extent.verdict === "too-short" ? (
                    <p className="shell-extent__verdict">
                      <strong>Too short to assess well.</strong> Below about ten
                      segments there are more factors than observations: the
                      collinearity check returns infinity, most factors stop varying,
                      and the ranking spreads across a fraction of its own scale.{" "}
                      <strong>Zoom out</strong> to take in more of the road.
                    </p>
                  ) : extent.verdict === "thin" ? (
                    <p className="shell-extent__verdict">
                      Workable, but thin. Twenty segments or more is where the ranking
                      separates properly — zoom out if there is more of this road.
                    </p>
                  ) : (
                    <p className="shell-extent__verdict">
                      Enough road for the ranking to separate and the checks to mean
                      something.
                    </p>
                  )}
                  <p className="shell-note">
                    Estimated from the map’s own geometry, which is simplified as you
                    zoom out — the real fetch decides the length. Read it as the
                    difference between four segments and forty, not as a measurement.
                  </p>
                </div>
              ) : null}

              <button
                type="button"
                className="shell-button shell-button--quiet"
                onClick={() => {
                  setPicked(null);
                  setExtent(null);
                }}
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
            <span className="shell-step__n">3</span> What kind of road
            <span className="shell-step__optional">recommended</span>
          </h2>
          <p className="shell-note">
            <strong>This decides how much published evidence is admissible.</strong> A
            weight is a number plus the context it is valid in, and one whose scope does
            not match this corridor is inadmissible rather than approximate. Left
            undeclared, only weights that state no scope at all can be used — on a real
            run that meant <strong>eleven factors measured and one scored</strong>.
          </p>

          <label>
            Road type
            <select name="facility_type" defaultValue="any">
              <option value="any">Not declared — unrestricted weights only</option>
              <option value="rural_two_lane">Rural two-lane</option>
              <option value="rural_multilane">Rural multilane</option>
              <option value="urban_arterial">Urban arterial</option>
            </select>
          </label>

          <label>
            Region
            <span className="shell-hint">
              A mismatch is reported, never refused — most published weights are North
              American and refusing them would leave nothing usable elsewhere.
            </span>
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

          <label>
            Which crashes were counted
            <span className="shell-hint">
              Match this to your crash file. A fatal-crash weight never scores an
              injury panel.
            </span>
            <select name="severity" defaultValue="all">
              <option value="all">All crashes</option>
              <option value="injury">Injury</option>
              <option value="fsi">Fatal and serious injury</option>
              <option value="fatal">Fatal only</option>
            </select>
          </label>
        </section>

        <section className="shell-step">
          <h2>
            <span className="shell-step__n">4</span> Crashes
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
