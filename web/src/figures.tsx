/**
 * Step 4.4 — the figures.
 *
 * All SVG, drawn from arrays already in the payload. No plotting library, no image
 * requests, nothing fetched: a figure that needed a CDN would be a blank rectangle in
 * an emailed report, and the whole point of the page is that it survives being sent.
 *
 * **The colour scale is one hue, light to dark, and it was validated rather than
 * chosen.** Risk is a magnitude, so it gets a sequential ramp — never a rainbow, never
 * a categorical palette pressed into service as a value scale. The six steps below
 * pass the ordinal checks against a white surface: monotone lightness, visible gaps
 * between steps, a hue spread of 18°, and a pale end that still reads as a mark at
 * 2.11:1. Because the ramp varies by lightness it survives being printed in grey.
 *
 * **Every figure has a table beside it.** Colour is never the only way to read a
 * value here — the ranked table carries the same numbers, which is what makes the
 * strip and the map legible to a reader who cannot separate the steps.
 */

import type { Blackspot, Calibration, Corridor, Cure, Ranking, Shape, UnitRisk } from "./types";
import { count, decimal, percent, significant } from "./format";

/** Sequential, one hue, light→dark. Validated; do not reorder or interpolate. */
export const RISK_RAMP = [
  "#e9a468",
  "#dd8342",
  "#c96323",
  "#a84a13",
  "#84360c",
  "#5e2408",
] as const;

const INK = "#16191d";
const INK_SOFT = "#4a5158";
const RULE = "#dfe3e8";
const SURFACE = "#ffffff";

/** Percentile → ramp step. Worst segments get the darkest end. */
export const riskColour = (percentile: number): string =>
  RISK_RAMP[Math.min(RISK_RAMP.length - 1, Math.max(0, Math.floor(percentile * RISK_RAMP.length)))];

function Figure({
  caption,
  children,
}: {
  caption: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <figure className="figure">
      {children}
      <figcaption>{caption}</figcaption>
    </figure>
  );
}

/** The ramp's own key. A continuous scale without one is unreadable by construction. */
export function RiskLegend() {
  return (
    <div className="legend">
      <span className="legend__end">lower risk</span>
      <span className="legend__swatches">
        {RISK_RAMP.map((colour) => (
          <span key={colour} style={{ background: colour }} />
        ))}
      </span>
      <span className="legend__end">higher risk</span>
    </div>
  );
}

/** Nice round tick positions, at most `target` of them. */
function ticks(max: number, target = 6): number[] {
  const raw = max / target;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= raw) ?? magnitude * 10;
  const out: number[] = [];
  for (let value = 0; value <= max + 1e-9; value += step) out.push(value);
  return out;
}

/**
 * The corridor as a straight line, coloured by risk, with the blackspot runs beneath.
 *
 * This is the figure that answers the client's question without them reading a number:
 * where along this road is the problem, and is it one place or several.
 */
export function RiskStrip({
  ranking,
  corridor,
}: {
  ranking: Ranking;
  corridor: Corridor;
}) {
  const units = corridor.segmentation.units;
  const byId = new Map(ranking.units.map((unit) => [unit.unit_id, unit]));
  const total = corridor.corridor.length_m;
  if (units.length === 0 || total <= 0) return null;

  const W = 1000;
  const PAD = 8;
  const inner = W - PAD * 2;
  const stripY = 10;
  const stripH = 30;
  const spotY = stripY + stripH + 7;
  const axisY = spotY + 20;
  const H = axisY + 18;

  const x = (metres: number) => PAD + (metres / total) * inner;
  const worst = ranking.blackspots[0];

  return (
    <Figure
      caption={
        <>
          The corridor from start to end, each segment shaded by its risk rank. Bars
          beneath mark the blackspot runs; the worst is labelled. Distances are chainage
          in metres from the start of the corridor.
        </>
      }
    >
      <RiskLegend />
      <svg viewBox={`0 0 ${W} ${H}`} className="chart chart--strip" role="img">
        <title>Risk along the corridor</title>

        {units.map((unit) => {
          const risk = byId.get(unit.unit_id);
          const left = x(unit.start_m);
          const right = x(unit.end_m);
          // A 2px surface gap between fills, never a stroke around them.
          const width = Math.max(1, right - left - 2);
          return (
            <rect
              key={unit.unit_id}
              x={left + 1}
              y={stripY}
              width={width}
              height={stripH}
              fill={risk ? riskColour(risk.percentile) : RULE}
              rx={1}
            >
              <title>
                {unit.unit_id} · {count(Math.round(unit.start_m))}–
                {count(Math.round(unit.end_m))} m
                {risk ? ` · rank ${risk.rank} of ${ranking.n_units}` : ""}
                {risk?.expected !== undefined
                  ? ` · ${decimal(risk.expected)} expected crashes`
                  : ""}
              </title>
            </rect>
          );
        })}

        {ranking.blackspots.map((spot) =>
          spot.start_m === undefined || spot.end_m === undefined ? null : (
            <rect
              key={spot.rank}
              x={x(spot.start_m)}
              y={spotY}
              width={Math.max(2, x(spot.end_m) - x(spot.start_m))}
              height={4}
              fill={INK}
            >
              <title>
                Blackspot {spot.rank} — {spot.n_units} segment(s),{" "}
                {count(Math.round(spot.length_m ?? 0))} m
              </title>
            </rect>
          ),
        )}

        {/* One direct label, on the one that matters. Not a number on every mark. */}
        {worst?.start_m !== undefined && worst.end_m !== undefined ? (
          <text
            x={Math.min(W - PAD, Math.max(PAD, (x(worst.start_m) + x(worst.end_m)) / 2))}
            y={spotY + 17}
            className="chart__label"
            textAnchor="middle"
            fill={INK}
          >
            worst: {worst.worst_unit}
          </text>
        ) : null}

        <line x1={PAD} y1={axisY} x2={W - PAD} y2={axisY} stroke={RULE} strokeWidth={1} />
        {ticks(total).map((metres) => (
          <g key={metres}>
            <line
              x1={x(metres)}
              y1={axisY}
              x2={x(metres)}
              y2={axisY + 4}
              stroke={RULE}
              strokeWidth={1}
            />
            <text
              x={x(metres)}
              y={axisY + 15}
              className="chart__tick"
              textAnchor="middle"
              fill={INK_SOFT}
            >
              {count(Math.round(metres))}
            </text>
          </g>
        ))}
      </svg>
    </Figure>
  );
}

/**
 * The road as it actually lies, each segment drawn in its risk colour.
 *
 * Equirectangular, scaled about the corridor's own mean latitude — over a corridor of
 * tens of kilometres the distortion is far below the width of the line, and it costs
 * no map tiles, no API key and no network.
 */
export function CorridorMap({
  ranking,
  corridor,
}: {
  ranking: Ranking;
  corridor: Corridor;
}) {
  const units = corridor.segmentation.units.filter((unit) => unit.geometry.length > 1);
  if (units.length === 0) return null;

  const byId = new Map(ranking.units.map((unit) => [unit.unit_id, unit]));
  const points = units.flatMap((unit) => unit.geometry);
  const lats = points.map(([, lat]) => lat);
  const lons = points.map(([lon]) => lon);
  const meanLat = (Math.min(...lats) + Math.max(...lats)) / 2;
  const kx = Math.cos((meanLat * Math.PI) / 180);

  const rawX = (lon: number) => lon * kx;
  const rawY = (lat: number) => -lat;
  const xs = lons.map(rawX);
  const ys = lats.map(rawY);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);

  const PAD = 14;
  const W = 1000;
  const spanX = maxX - minX || 1e-9;
  const spanY = maxY - minY || 1e-9;
  const scale = (W - PAD * 2) / spanX;
  const H = Math.min(520, Math.max(140, spanY * scale + PAD * 2));
  const fit = Math.min(scale, (H - PAD * 2) / spanY);
  const offsetX = PAD + ((W - PAD * 2) - spanX * fit) / 2;
  const offsetY = PAD + ((H - PAD * 2) - spanY * fit) / 2;

  const project = ([lon, lat]: [number, number]) =>
    `${(offsetX + (rawX(lon) - minX) * fit).toFixed(1)},${(
      offsetY +
      (rawY(lat) - minY) * fit
    ).toFixed(1)}`;

  return (
    <Figure
      caption={
        <>
          The corridor in plan, on the same scale as the strip above. Drawn from the
          centreline itself — there are no map tiles behind it, which is why it works
          with no network.
        </>
      }
    >
      <svg viewBox={`0 0 ${W} ${H}`} className="chart chart--map" role="img">
        <title>Risk along the corridor, in plan</title>
        {/* A continuous under-stroke so the road reads as one line, not as beads. */}
        <polyline
          points={units.flatMap((unit) => unit.geometry).map(project).join(" ")}
          fill="none"
          stroke={SURFACE}
          strokeWidth={9}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {units.map((unit) => {
          const risk = byId.get(unit.unit_id);
          return (
            <polyline
              key={unit.unit_id}
              points={unit.geometry.map(project).join(" ")}
              fill="none"
              stroke={risk ? riskColour(risk.percentile) : RULE}
              strokeWidth={6}
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <title>
                {unit.unit_id}
                {risk ? ` · rank ${risk.rank} of ${ranking.n_units}` : ""}
              </title>
            </polyline>
          );
        })}
      </svg>
    </Figure>
  );
}

/**
 * A CURE plot: the cumulative residual against a factor, inside its own bounds.
 *
 * The band is a reference envelope, not a second series — it is where the cumulative
 * residual should stay if the factor is specified correctly. A line that wanders
 * outside it is the plot earning its place.
 */
export function CurePlot({ cure }: { cure: Cure }) {
  if (cure.x.length < 2) return null;

  const W = 480;
  const H = 220;
  const PAD = { top: 12, right: 12, bottom: 30, left: 46 };
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;

  const maxY = Math.max(
    ...cure.cumulative.map(Math.abs),
    ...cure.bound.map(Math.abs),
    1e-9,
  );
  const minX = Math.min(...cure.x);
  const maxX = Math.max(...cure.x);
  const spanX = maxX - minX || 1e-9;

  const px = (value: number) => PAD.left + ((value - minX) / spanX) * plotW;
  const py = (value: number) => PAD.top + plotH / 2 - (value / maxY) * (plotH / 2);

  const upper = cure.x.map((value, i) => `${px(value)},${py(cure.bound[i])}`);
  const lower = cure.x.map((value, i) => `${px(value)},${py(-cure.bound[i])}`).reverse();

  return (
    <Figure
      caption={
        <>
          <strong>{cure.factor}</strong> —{" "}
          {cure.drifts
            ? "the cumulative residual leaves its band, which means this factor is not entered in the right shape."
            : "the cumulative residual stays inside its band, so nothing in this factor's shape is unaccounted for."}{" "}
          {percent(cure.share_outside, 1)} of the range sits outside.
        </>
      }
    >
      <svg viewBox={`0 0 ${W} ${H}`} className="chart chart--cure" role="img">
        <title>Cumulative residual against {cure.factor}</title>
        <polygon
          points={[...upper, ...lower].join(" ")}
          fill={RISK_RAMP[0]}
          fillOpacity={0.18}
        />
        <line
          x1={PAD.left}
          y1={py(0)}
          x2={W - PAD.right}
          y2={py(0)}
          stroke={RULE}
          strokeWidth={1}
        />
        <polyline
          points={cure.x.map((value, i) => `${px(value)},${py(cure.cumulative[i])}`).join(" ")}
          fill="none"
          stroke={cure.drifts ? RISK_RAMP[5] : INK}
          strokeWidth={2}
          strokeLinejoin="round"
        />
        <line
          x1={PAD.left}
          y1={PAD.top}
          x2={PAD.left}
          y2={H - PAD.bottom}
          stroke={RULE}
          strokeWidth={1}
        />
        <text x={PAD.left} y={H - 8} className="chart__tick" fill={INK_SOFT}>
          {significant(minX)}
        </text>
        <text
          x={W - PAD.right}
          y={H - 8}
          className="chart__tick"
          textAnchor="end"
          fill={INK_SOFT}
        >
          {significant(maxX)}
        </text>
        <text x={4} y={py(0) + 3} className="chart__tick" fill={INK_SOFT}>
          0
        </text>
      </svg>
    </Figure>
  );
}

/** Observed against predicted on held-out road. One measure, so one colour. */
export function CalibrationBars({
  calibrations,
}: {
  calibrations: { label: string; calibration: Calibration }[];
}) {
  // A fold that produced no crashes to compare is not a zero — it is an absence,
  // and a bar chart of zeros reads as "the model predicted nothing" rather than
  // "there was nothing to check it against".
  const usable = calibrations.filter(
    ({ calibration }) =>
      typeof calibration.factor === "number" &&
      Number.isFinite(calibration.factor) &&
      ((calibration.observed ?? 0) > 0 || (calibration.predicted ?? 0) > 0),
  );
  if (usable.length === 0) {
    return (
      <p className="caveat">
        The held-out folds contained no crashes to compare against, so the level could
        not be checked. That is a property of how thinly the crashes are spread over
        this corridor, not a result.
      </p>
    );
  }

  const max = Math.max(
    ...usable.flatMap(({ calibration }) =>
      [calibration.observed, calibration.predicted].filter(
        (value): value is number => typeof value === "number" && Number.isFinite(value),
      ),
    ),
    1e-9,
  );

  return (
    <Figure
      caption={
        <>
          Crashes actually seen on held-out stretches of road against the number the
          model expected there. A factor near 1.00 means the level is right; the spatial
          split is the honest one, because a random split lets the model learn from road
          either side of the segment it is predicting.
        </>
      }
    >
      <div className="calibration">
        {usable.map(({ label, calibration }) => (
          <div className="calibration__row" key={label}>
            <div className="calibration__head">
              <span>{label}</span>
              <span className={calibration.calibrated ? "tag tag--clear" : "tag tag--skipped"}>
                factor {decimal(calibration.factor, 2)}
              </span>
            </div>
            {(
              [
                ["observed", calibration.observed],
                ["expected", calibration.predicted],
              ] as const
            ).map(([name, value]) => (
              <div className="calibration__bar" key={name}>
                <span className="calibration__name">{name}</span>
                <span className="calibration__track">
                  <span
                    className="calibration__fill"
                    style={{
                      width: `${((value ?? 0) / max) * 100}%`,
                      background: RISK_RAMP[2],
                    }}
                  />
                </span>
                <span className="calibration__value">{decimal(value, 1)}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </Figure>
  );
}

/**
 * The spline diagnostic.
 *
 * Filed under reference, never beside a client number, because the brief files rung 3
 * that way: it says what *shape* a factor has, and it does not produce an effect size
 * anyone should quote.
 */
export function SplineCurve({ shape }: { shape: Shape }) {
  if (!shape.curve || shape.curve.x.length < 2) return null;
  const { x, y, lower, upper } = shape.curve;

  const W = 480;
  const H = 200;
  const PAD = { top: 12, right: 12, bottom: 28, left: 40 };
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;

  const minX = Math.min(...x);
  const maxX = Math.max(...x);
  const minY = Math.min(...lower);
  const maxY = Math.max(...upper);
  const spanX = maxX - minX || 1e-9;
  const spanY = maxY - minY || 1e-9;

  const px = (value: number) => PAD.left + ((value - minX) / spanX) * plotW;
  const py = (value: number) => PAD.top + plotH - ((value - minY) / spanY) * plotH;

  const band = [
    ...x.map((value, i) => `${px(value)},${py(upper[i])}`),
    ...x.map((value, i) => `${px(value)},${py(lower[i])}`).reverse(),
  ];

  return (
    <Figure
      caption={
        <>
          <strong>{shape.factor}</strong> — the fitted shape is{" "}
          <strong>{shape.shape ?? "not identified"}</strong>
          {shape.turning_point !== null
            ? `, turning at ${significant(shape.turning_point)}`
            : ""}
          . Reference only: this says what shape the relationship has, not how large it
          is, and no number from it belongs in a decision.
        </>
      }
    >
      <svg viewBox={`0 0 ${W} ${H}`} className="chart chart--spline" role="img">
        <title>Fitted spline for {shape.factor}</title>
        <polygon points={band.join(" ")} fill={INK} fillOpacity={0.08} />
        <polyline
          points={x.map((value, i) => `${px(value)},${py(y[i])}`).join(" ")}
          fill="none"
          stroke={INK}
          strokeWidth={2}
          strokeLinejoin="round"
        />
        <line
          x1={PAD.left}
          y1={H - PAD.bottom}
          x2={W - PAD.right}
          y2={H - PAD.bottom}
          stroke={RULE}
          strokeWidth={1}
        />
        <text x={PAD.left} y={H - 8} className="chart__tick" fill={INK_SOFT}>
          {significant(minX)}
        </text>
        <text
          x={W - PAD.right}
          y={H - 8}
          className="chart__tick"
          textAnchor="end"
          fill={INK_SOFT}
        >
          {significant(maxX)}
        </text>
      </svg>
    </Figure>
  );
}

export type { Blackspot, UnitRisk };
