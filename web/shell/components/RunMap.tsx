"use client";

import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import { RISK_RAMP } from "roadrisk-report/risk";
import type { Run } from "roadrisk-report/report";

import type { Basemap } from "@/lib/api";

import {
  boundaryFeatures,
  bounds,
  unitFactors,
  unitFeatures,
  UNRANKED,
} from "@/lib/corridor";

/**
 * MapLibre is loaded only when somebody opens this tab, and only in the browser.
 *
 * `ssr: false` is a requirement rather than a saving: MapLibre reaches for `window` as it
 * is imported, so rendering it on the server throws. The saving comes with it — the
 * library is a megabyte, and it stays out of every other route's bundle because this is
 * the only file that imports it.
 */
const RunMapCanvas = dynamic(() => import("./RunMapCanvas"), {
  ssr: false,
  loading: () => (
    <div className="shell-map shell-map--waiting">
      <p>Drawing the corridor…</p>
    </div>
  ),
});

const RANK_LIMIT = 25;

/** The limitation the engine writes when the corridor was invented rather than fetched. */
const SYNTHETIC = "synthetic_corridor";

function metres(value: number): string {
  return `${Math.round(value).toLocaleString("en-GB")} m`;
}

function shownValue(value: number | null): string {
  if (value === null) return "—";
  return Math.abs(value) >= 100 || Number.isInteger(value)
    ? value.toLocaleString("en-GB")
    : value.toPrecision(3);
}

/**
 * The map screen: the corridor, and what any segment on it is made of.
 *
 * **This is the screen's map, and it is deliberately not the document's.** The report
 * draws the same corridor as inline SVG in equirectangular projection so that no external
 * image request exists anywhere in a report — that is what lets one be emailed and opened
 * from a disk. This one is Web Mercator, it pans and zooms, and clicking a segment says
 * where each of its numbers came from. Consolidating them would mean putting a tile
 * request into the document, which is the one thing step 4.4 exists to prevent.
 *
 * **The ranked list beside the map is not a duplicate.** A canvas cannot be tabbed
 * through, so without it the whole feature would be unreachable to anybody not using a
 * mouse — and it is also the only part of this screen that says anything before MapLibre
 * has finished loading.
 */
export default function RunMap({
  run,
  basemap,
}: {
  run: Run;
  basemap: Basemap | null;
}) {
  const units = useMemo(() => unitFeatures(run), [run]);
  const boundaries = useMemo(() => boundaryFeatures(run), [run]);
  const extent = useMemo(() => bounds(units), [units]);
  const synthetic = run.limitations.some(
    (limitation) => limitation.code === SYNTHETIC,
  );
  const [selected, setSelected] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const chosen = units.features.find(
    (feature) => feature.properties.unit_id === selected,
  );
  const factors = useMemo(
    () => (selected ? unitFactors(run, selected) : []),
    [run, selected],
  );

  const ranked = useMemo(
    () =>
      [...units.features].sort(
        (left, right) =>
          (left.properties.rank ?? Number.MAX_SAFE_INTEGER) -
          (right.properties.rank ?? Number.MAX_SAFE_INTEGER),
      ),
    [units],
  );

  if (!extent) {
    return (
      <div className="shell-card">
        <h2>No geometry to draw</h2>
        <p>
          This run has no corridor. A job that assessed a panel you supplied directly has
          rows and no road — the ranking is on the report tab, and there is nothing to put
          on a map.
        </p>
      </div>
    );
  }

  const hasRanking = units.features.some(
    (feature) => feature.properties.rank !== null,
  );

  return (
    <>
      <div className="shell-card">
        <div className="shell-legend">
          <span>lower risk</span>
          <span className="shell-legend__swatches">
            {RISK_RAMP.map((colour) => (
              <span key={colour} style={{ background: colour }} />
            ))}
          </span>
          <span>higher risk</span>
          {units.features.some((feature) => feature.properties.rank === null) ? (
            <>
              <span
                className="shell-legend__chip"
                style={{ background: UNRANKED }}
              />
              not ranked
            </>
          ) : null}
          <span className="shell-legend__aside">
            <span className="shell-legend__tick" aria-hidden="true" />
            segment boundary
          </span>
        </div>

        {/*
          A basemap makes this necessary. A synthetic corridor drawn on an empty
          background is obviously a fixture; the same line over real streets, with real
          place names beside it, looks exactly like an assessment of a real road — which
          is the single failure this product exists to prevent. The run banner above says
          the corridor is invented; this says what that means *for the picture*.
        */}
        {synthetic && basemap ? (
          <p className="shell-problem">
            <strong>This line is not a road.</strong> The corridor is synthetic, so it is
            drawn at invented coordinates over a real basemap — whatever is underneath it
            has nothing to do with this assessment, and neither has anything named nearby.
          </p>
        ) : null}

        {failure ? (
          <p className="shell-problem">
            <strong>The map did not draw.</strong> {failure} The ranked list below is
            unaffected, and the report tab draws the same corridor without MapLibre.
          </p>
        ) : null}

        <RunMapCanvas
          units={units}
          boundaries={boundaries}
          extent={extent}
          basemap={basemap}
          selected={selected}
          onSelect={setSelected}
          onFailure={setFailure}
        />

        <p className="shell-note">
          Ticks across the road are the segment boundaries — the ranking is per segment
          and a blackspot is a run of them, so where one ends is part of the answer.{" "}
          {basemap ? (
            <>
              <strong>The basemap is fetched from a tile server</strong>, which is the one
              thing on this screen that talks to somebody else. The credit its licence
              requires is in the corner of the map and applies to what you do with a
              picture of this screen
              {basemap.ours
                ? " — OpenStreetMap's data under ODbL, served by OpenFreeMap"
                : ", and the terms of the style this deployment configured are yours to check"}
              . Set <code>$ROADRISK_MAP_STYLE=none</code> for a deployment that must make
              no external request at all.
            </>
          ) : (
            <>
              <strong>There is no basemap, and no request left this page to draw it.</strong>{" "}
              The line is the corridor as the run measured it, with nothing behind it.
            </>
          )}{" "}
          The report tab draws the same corridor as SVG, in a different projection, with no
          tiles and no JavaScript needed — that one is the document, and this one is the
          screen.
        </p>
      </div>

      <div className="shell-card">
        {chosen ? (
          <>
            <h2>
              {chosen.properties.unit_id}{" "}
              {chosen.properties.rank !== null ? (
                <span className="shell-note">
                  rank {chosen.properties.rank} of {units.features.length}
                </span>
              ) : (
                <span className="shell-note">not ranked</span>
              )}
            </h2>
            <table className="shell-table">
              <tbody>
                <tr>
                  <th>Chainage</th>
                  <td>
                    {metres(chosen.properties.start_m)} –{" "}
                    {metres(chosen.properties.end_m)}
                  </td>
                </tr>
                {chosen.properties.score !== null ? (
                  <tr>
                    <th>Score</th>
                    <td>{chosen.properties.score.toPrecision(3)}</td>
                  </tr>
                ) : null}
                {chosen.properties.observed !== null ? (
                  <tr>
                    <th>Observed</th>
                    <td>{chosen.properties.observed}</td>
                  </tr>
                ) : null}
                {chosen.properties.expected !== null ? (
                  <tr>
                    <th>Expected</th>
                    <td>
                      {chosen.properties.expected.toFixed(1)}
                      {chosen.properties.expected_low !== null &&
                      chosen.properties.expected_high !== null ? (
                        <>
                          {" "}
                          <span className="shell-note">
                            95% {chosen.properties.expected_low.toFixed(1)} –{" "}
                            {chosen.properties.expected_high.toFixed(1)}
                          </span>
                        </>
                      ) : null}
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>

            <h3>What was measured here, and who said so</h3>
            {factors.length === 0 ? (
              <p className="shell-empty">
                No factor resolved on this segment. That is a finding, not a gap in this
                page — the report&rsquo;s missing-factor table names what failed and why.
              </p>
            ) : (
              <table className="shell-table">
                <thead>
                  <tr>
                    <th>Factor</th>
                    <th>Value</th>
                    <th>Source</th>
                    <th>Tier</th>
                    <th>Licence</th>
                    <th>Confidence</th>
                  </tr>
                </thead>
                <tbody>
                  {factors.map((factor) => (
                    <tr key={factor.factor}>
                      <td>
                        {factor.factor}
                        <br />
                        <span className="shell-mono">{factor.column}</span>
                      </td>
                      <td>{shownValue(factor.value)}</td>
                      <td>
                        <span className="shell-mono">{factor.adapter}</span>
                        {factor.source ? (
                          <>
                            <br />
                            <span className="shell-note">{factor.source}</span>
                          </>
                        ) : null}
                      </td>
                      <td>{factor.tier}</td>
                      <td>{factor.licence ?? "—"}</td>
                      <td>
                        {factor.confidence}
                        <br />
                        <span className="shell-note">{factor.reason}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <p className="shell-note">
              <code>carried</code> means the value was imputed from a neighbouring unit
              rather than measured here; <code>contradicted</code> means a second source
              materially disagrees about this segment. Neither is hidden, and neither is
              averaged away.
            </p>
          </>
        ) : (
          <>
            <h2>Pick a segment</h2>
            <p>
              Click the corridor, or choose from the list. Each segment carries the
              measurements behind its colour — the value, the adapter that produced it,
              its tier, its licence, and whether it was measured here or carried from next
              door.
            </p>
            {hasRanking ? (
              <ul className="shell-picker">
                {ranked.slice(0, RANK_LIMIT).map((feature) => (
                  <li key={feature.properties.unit_id}>
                    <button
                      type="button"
                      onClick={() => setSelected(feature.properties.unit_id)}
                    >
                      <span
                        className="shell-legend__chip"
                        style={{ background: feature.properties.colour }}
                      />
                      <span className="shell-mono">{feature.properties.unit_id}</span>
                      <span className="shell-note">
                        rank {feature.properties.rank ?? "—"} ·{" "}
                        {metres(feature.properties.start_m)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="shell-empty">
                This run produced no ranking, so every segment is drawn unranked.
              </p>
            )}
          </>
        )}
      </div>
    </>
  );
}
