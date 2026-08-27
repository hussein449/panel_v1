/**
 * Step 4.4 — the figures.
 *
 * All SVG, drawn from arrays already in the payload. No plotting library, no image
 * requests, nothing fetched: a figure that needed a CDN would be a blank rectangle in
 * an emailed report, and the whole point of the page is that it survives being sent.
 *
 * **The colour scale lives in `risk.ts`**, not here. Step 5.3c draws the same corridor
 * on a MapLibre map — a different projection, a different technology, a different file —
 * and a second copy of those six hex codes would eventually mean the screen and the
 * document disagreeing about which segment is the dangerous one.
 *
 * **Every figure has a table beside it.** Colour is never the only way to read a
 * value here — the ranked table carries the same numbers, which is what makes the
 * strip and the map legible to a reader who cannot separate the steps.
 */

import type { Blackspot, Calibration, Corridor, Cure, Ranking, Shape, UnitRisk } from "./types";
import { count, decimal, percent, significant } from "./format";
import { RISK_RAMP, riskColour } from "./risk";
import { segmentHandlers, useSegmentFocus } from "./focus";

export { RISK_RAMP, riskColour };

const INK = "#16191d";
const INK_SOFT = "#4a5158";
const RULE = "#dfe3e8";
const SURFACE = "#ffffff";

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

/**
 * What the reader is pointing at, in words and numbers, under the figures.
 *
 * **Its height does not depend on what is in it.** Empty, it holds a prompt; full, it
 * holds a segment — and a document that reflows when you point at it is a document whose
 * printed page is not the one you were reading. It is `no-print` for the same reason the
 * print button is: a caption saying *point at a segment* has no business in a PDF.
 *
 * Everything in here is also in the table below the figures. That is deliberate — this is
 * an enhancement for whoever has a pointer, not the only route to a number.
 */
export function SegmentReadout({ ranking }: { ranking: Ranking }) {
  const { focused } = useSegmentFocus();
  const unit = focused ? ranking.units.find((u) => u.unit_id === focused) : undefined;

  return (
    <p className="readout no-print" role="status" aria-live="polite">
      {focused === null ? (
        <span className="readout__prompt">
          Point at a segment — on the strip, on the map or in the table — to read it here.
        </span>
      ) : unit === undefined ? (
        <>
          <span className="mono">{focused}</span>
          <span className="readout__prompt">
            {" "}
            is not in the ranking. Nothing was scored for it.
          </span>
        </>
      ) : (
        <>
          <span className="mono">{unit.unit_id}</span> · rank {unit.rank} of{" "}
          {count(ranking.n_units)} · score {significant(unit.score)}
          {unit.observed != null ? <> · {count(unit.observed)} observed</> : null}
          {unit.expected != null ? (
            <>
              {" "}
              · {decimal(unit.expected)} expected
              {unit.expected_low != null && unit.expected_high != null ? (
                <>
                  {" "}
                  <span className="muted">
                    (95% {decimal(unit.expected_low)} – {decimal(unit.expected_high)})
                  </span>
                </>
              ) : null}
            </>
          ) : null}
        </>
      )}
    </p>
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
  // Before the early return below: a hook called conditionally is a hook called in a
  // different order on the next render, which React counts rather than names.
  const { focused, focus } = useSegmentFocus();

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
              // Stroked rather than moved or resized. The 2px gap between fills is
              // exactly what the highlight fills, so nothing on the figure shifts.
              stroke={focused === unit.unit_id ? INK : "none"}
              strokeWidth={focused === unit.unit_id ? 2 : 0}
              {...segmentHandlers(unit.unit_id, focus)}
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
          spot.start_m == null || spot.end_m == null ? null : (
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
        {worst?.start_m != null && worst.end_m != null ? (
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
  const { focused, focus } = useSegmentFocus();

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
              // The focused segment goes dark rather than wider: a road that thickens
              // under the pointer redraws its own geometry, and this one is in plan.
              stroke={
                focused === unit.unit_id
                  ? INK
                  : risk
                    ? riskColour(risk.percentile)
                    : RULE
              }
              strokeWidth={6}
              strokeLinecap="round"
              strokeLinejoin="round"
              {...segmentHandlers(unit.unit_id, focus)}
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
