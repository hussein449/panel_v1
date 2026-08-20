import type { Assessment, Corridor, Ranking, Run } from "./types";
import {
  CalibrationBars,
  CorridorMap,
  CurePlot,
  RiskStrip,
  SplineCurve,
} from "./figures";
import { count, decimal, extent, percent, shorten, signed, significant } from "./format";

/** A titled block. Every section is one, so the print rules have one thing to target. */
export function Section({
  id,
  title,
  lead,
  children,
}: {
  id: string;
  title: string;
  lead?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="section" id={id}>
      <h2>{title}</h2>
      {lead ? <p className="lead">{lead}</p> : null}
      {children}
    </section>
  );
}

/**
 * The mode banner.
 *
 * The brief calls for this to be unmissable on every screen and every page of the
 * PDF. Mode B's version says "ranking only, not a crash prediction" because the one
 * failure this product cannot afford is a ranking being read as a forecast.
 */
export function ModeBanner({ assessment }: { assessment: Assessment }) {
  const modeA = assessment.mode === "A";
  return (
    <div className={`banner banner--${modeA ? "a" : "b"}`} role="status">
      <span className="banner__dot" aria-hidden="true" />
      <span className="banner__text">{assessment.banner}</span>
      <span className="banner__rung">{assessment.rung}</span>
    </div>
  );
}

/** Refusal and descent receipts. Shown whenever there is one, never collapsed away. */
export function Receipts({ assessment }: { assessment: Assessment }) {
  const { refusal, descent, index_refusal } = assessment.receipts;
  if (!refusal && !descent && !index_refusal) return null;

  return (
    <div className="receipts">
      {refusal ? (
        <div className="receipt receipt--refusal">
          <h3>Mode A was not available</h3>
          <p>{refusal}</p>
        </div>
      ) : null}
      {descent ? (
        <div className="receipt receipt--descent">
          <h3>The model stepped down</h3>
          <p>{descent}</p>
        </div>
      ) : null}
      {index_refusal ? (
        <div className="receipt receipt--refusal">
          <h3>The index could not be scored</h3>
          <p>{index_refusal}</p>
        </div>
      ) : null}
    </div>
  );
}

/** The four numbers a reader wants before anything else. */
export function Headline({ run }: { run: Run }) {
  const { assessment, corridor } = run;
  const worst = assessment.ranking?.units[0];

  const tiles: { label: string; value: string; note?: string }[] = [
    {
      label: "Corridor",
      value: corridor ? `${decimal(corridor.corridor.length_km, 2)} km` : "—",
      note: corridor?.corridor.name,
    },
    {
      label: "Segments",
      value: count(assessment.panel.units),
      note: corridor
        ? `${count(Math.round(corridor.segmentation.target_length_m))} m target`
        : undefined,
    },
    {
      label: "Crashes",
      value: count(assessment.panel.total_crashes),
      note: `${percent(assessment.panel.zero_crash_share)} of rows are zero-crash`,
    },
    {
      label: "Worst segment",
      value: worst ? worst.unit_id : "—",
      note: worst ? `rank 1 of ${count(assessment.ranking!.n_units)}` : undefined,
    },
  ];

  return (
    <div className="tiles">
      {tiles.map((tile) => (
        <div className="tile" key={tile.label}>
          <div className="tile__label">{tile.label}</div>
          <div className="tile__value">{tile.value}</div>
          {tile.note ? <div className="tile__note">{tile.note}</div> : null}
        </div>
      ))}
    </div>
  );
}

/**
 * The ranked table and the blackspot runs.
 *
 * The count columns appear only when the ranking says it has them. Mode B does not
 * omit them because they are empty — it omits them because it does not estimate a
 * count, and a column of dashes would invite the reader to think one was missing.
 */
export function RankingSection({
  ranking,
  corridor,
}: {
  ranking: Ranking;
  corridor: Corridor | null;
}) {
  const withCounts = ranking.has_intervals;
  const top = ranking.units.slice(0, 20);

  return (
    <Section
      id="ranking"
      title="Where to look first"
      lead={`Ranked on ${ranking.basis}.`}
    >
      {corridor ? (
        <>
          <RiskStrip ranking={ranking} corridor={corridor} />
          <CorridorMap ranking={ranking} corridor={corridor} />
        </>
      ) : null}

      {ranking.blackspots.length > 0 ? (
        <>
          <h3>
            Blackspots — runs of segments in the worst{" "}
            {percent(1 - ranking.threshold_percentile)}
          </h3>
          <table className="table table--blackspots">
            <thead>
              <tr>
                <th>#</th>
                <th>Segments</th>
                <th>Extent</th>
                <th>Length</th>
                <th>Worst segment</th>
                {withCounts ? <th className="num">Observed</th> : null}
                {withCounts ? <th className="num">Expected</th> : null}
              </tr>
            </thead>
            <tbody>
              {ranking.blackspots.map((spot) => (
                <tr key={spot.rank}>
                  <td>{spot.rank}</td>
                  <td>{spot.n_units}</td>
                  <td>{extent(spot.start_m, spot.end_m) ?? "chainage unknown"}</td>
                  <td>
                    {spot.length_m !== undefined
                      ? `${count(Math.round(spot.length_m))} m`
                      : "—"}
                  </td>
                  <td className="mono">{spot.worst_unit}</td>
                  {withCounts ? (
                    <td className="num">{count(spot.observed ?? 0)}</td>
                  ) : null}
                  {withCounts ? (
                    <td className="num">{decimal(spot.expected ?? 0)}</td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ) : (
        <p className="muted">No segment cleared the blackspot threshold.</p>
      )}

      <h3>
        Worst {top.length} of {count(ranking.n_units)} segments
      </h3>
      <table className="table table--ranking">
        <thead>
          <tr>
            <th className="num">#</th>
            <th>Segment</th>
            <th className="num">Score</th>
            {withCounts ? <th className="num">Observed</th> : null}
            {withCounts ? <th className="num">Expected</th> : null}
            {withCounts ? <th className="num">95% interval</th> : null}
          </tr>
        </thead>
        <tbody>
          {top.map((unit) => (
            <tr key={unit.unit_id}>
              <td className="num">{unit.rank}</td>
              <td className="mono">{unit.unit_id}</td>
              <td className="num">{significant(unit.score)}</td>
              {withCounts ? (
                <td className="num">{count(unit.observed ?? 0)}</td>
              ) : null}
              {withCounts ? (
                <td className="num">{decimal(unit.expected ?? 0)}</td>
              ) : null}
              {withCounts ? (
                <td className="num nowrap">
                  {decimal(unit.expected_low ?? 0)} – {decimal(unit.expected_high ?? 0)}
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>

      {withCounts ? (
        <p className="footnote">
          The interval is a 95% confidence interval on the <em>expected</em> count —
          where the model's estimate of the average sits. It is not a prediction
          interval for next year's actual count, which would be wider.
        </p>
      ) : null}
      {ranking.notes.map((note) => (
        <p className="caveat" key={note}>
          {note}
        </p>
      ))}
    </Section>
  );
}

/** Mode A's coefficients, or Mode B's weighted terms. Never both, never mixed. */
export function ModelSection({ assessment }: { assessment: Assessment }) {
  const posterior = assessment.posterior;

  if (assessment.fit) {
    return (
      <Section
        id="model"
        title="What the model found"
        lead={assessment.fit.specification}
      >
        <table className="table">
          <thead>
            <tr>
              <th>Factor</th>
              <th className="num">Effect</th>
              <th className="num">
                {posterior ? "95% credible interval" : "95% confidence interval"}
              </th>
              <th>Reading</th>
            </tr>
          </thead>
          <tbody>
            {assessment.fit.coefficients.map((coefficient) => {
              const credible = posterior?.coefficients.find(
                (item) => item.name === coefficient.factor,
              );
              const low = credible ? credible.hdi_low : coefficient.ci_low;
              const high = credible ? credible.hdi_high : coefficient.ci_high;
              const excludesZero = low > 0 || high < 0;
              return (
                <tr key={coefficient.factor}>
                  <td className="mono">{coefficient.factor}</td>
                  <td className="num">
                    {signed(credible ? credible.mean : coefficient.estimate)}
                  </td>
                  <td className="num nowrap">
                    {signed(low)} to {signed(high)}
                  </td>
                  <td>
                    {excludesZero ? (
                      <span className="tag tag--clear">interval excludes zero</span>
                    ) : (
                      <span className="tag tag--muted">interval includes zero</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {assessment.fit.n_clusters ? (
          <p className="footnote">
            Standard errors are clustered by segment over{" "}
            {count(assessment.fit.n_clusters)} clusters. Each factor is a property of a
            segment repeated down every period, so treating rows as independent would
            count one segment many times over.
          </p>
        ) : null}
        {posterior?.sigma_u ? (
          <p className="footnote">
            Between-segment spread on the log rate, σ<sub>u</sub> ={" "}
            {decimal(posterior.sigma_u.mean, 3)} ({decimal(posterior.sigma_u.hdi_low, 3)}{" "}
            to {decimal(posterior.sigma_u.hdi_high, 3)}) — how much persistent character
            segments carry beyond the factors above.
          </p>
        ) : null}
        {assessment.spatial ? (
          <p className="footnote">{assessment.spatial.message}</p>
        ) : null}
      </Section>
    );
  }

  if (assessment.index) {
    return (
      <Section
        id="model"
        title="How the score was built"
        lead="Every weight below comes from published evidence, and is cited. No weight was invented, and an uncited weight would have stopped the run."
      >
        <table className="table">
          <thead>
            <tr>
              <th>Factor</th>
              <th className="num">Weight</th>
              <th>Evidence</th>
              <th>Crash type</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {assessment.index.terms.map((term) => (
              <tr key={`${term.factor}-${term.scope}`}>
                <td className="mono">{term.factor}</td>
                <td className="num">{signed(term.weight)}</td>
                <td>{term.family}</td>
                <td>{term.scope}</td>
                <td className="cite" title={term.weight_source}>
                  {shorten(term.weight_source)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {assessment.index.terms.flatMap((term) =>
          term.concerns.map((concern) => (
            <p className="caveat" key={`${term.factor}-${concern.code}`}>
              <strong>{term.factor}:</strong> {concern.message}
            </p>
          )),
        )}
      </Section>
    );
  }

  return null;
}

/**
 * Every factor with its source, tier, licence and confidence.
 *
 * The promise the whole product rests on: nothing in this report is untraceable.
 */
export function FactorsSection({ corridor }: { corridor: Corridor }) {
  if (corridor.provenance.length === 0) return null;

  return (
    <Section
      id="factors"
      title="Where every number came from"
      lead="One row per factor. Tier A is measured from the corridor or from open data; Tier B is inferred. Confidence is the share of segments where the value was measured rather than carried."
    >
      <table className="table table--provenance">
        <thead>
          <tr>
            <th>Factor</th>
            <th>Source</th>
            <th>Tier</th>
            <th>Licence</th>
            <th className="num">Coverage</th>
            <th className="num">High confidence</th>
            <th>Contested by</th>
          </tr>
        </thead>
        <tbody>
          {corridor.provenance.map((row) => (
            <tr key={row.column}>
              <td className="mono">{row.factor}</td>
              <td className="cite" title={row.source}>
                {shorten(row.source, 70)}
              </td>
              <td>
                <span className={`tag tag--tier-${row.tier.toLowerCase()}`}>
                  {row.tier}
                </span>
              </td>
              <td className="nowrap">{row.licence}</td>
              <td className="num">{percent(row.coverage)}</td>
              <td className="num">{percent(row.confidence_high)}</td>
              <td>{row.contested_by || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {corridor.contested.length > 0 ? (
        <p className="footnote">
          {corridor.contested.length} factor(s) were resolved by more than one source, so
          fusion had to choose. Where sources disagreed, the disagreement is scored rather
          than hidden.
        </p>
      ) : null}
    </Section>
  );
}

/** The gate checks, in the order they ran. */
export function ChecksSection({ assessment }: { assessment: Assessment }) {
  return (
    <Section
      id="checks"
      title="What was checked before anything was fitted"
      lead="Nine checks decide whether a model may run at all. A hard failure refuses Mode A outright; a soft failure steps the model down a rung."
    >
      <table className="table table--checks">
        <thead>
          <tr>
            <th className="num">#</th>
            <th>Check</th>
            <th>Result</th>
            <th>What it means</th>
          </tr>
        </thead>
        <tbody>
          {assessment.checks.map((check) => (
            <tr key={`${check.number}-${check.name}`}>
              <td className="num">{check.number}</td>
              <td>{check.name}</td>
              <td>
                <span className={`tag tag--${check.status.toLowerCase()}`}>
                  {check.status}
                </span>
              </td>
              <td className="small">{check.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Section>
  );
}

/** The panel, and what the crash snapping did to build it. */
export function PanelSection({ run }: { run: Run }) {
  const { assessment, corridor } = run;
  const snap = corridor?.snap;

  return (
    <Section
      id="panel"
      title="The data this rests on"
      lead="The panel is built from geography, not from crashes: every segment appears in every period whether or not anything happened there. Zero rows are structural, which is what makes a count model legitimate."
    >
      <dl className="facts">
        <div>
          <dt>Panel rows</dt>
          <dd>{count(assessment.panel.rows)}</dd>
        </div>
        <div>
          <dt>Segments × periods</dt>
          <dd>
            {count(assessment.panel.units)} × {count(assessment.panel.periods)}
          </dd>
        </div>
        <div>
          <dt>Zero-crash rows</dt>
          <dd>
            {count(assessment.panel.zero_crash_rows)} (
            {percent(assessment.panel.zero_crash_share)})
          </dd>
        </div>
        <div>
          <dt>Factor registry</dt>
          <dd>v{assessment.registry_version}</dd>
        </div>
      </dl>

      {snap ? (
        <>
          <h3>Crash snapping</h3>
          <p>
            {count(snap.n_snapped)} of {count(snap.n_supplied)} supplied crashes landed on
            the corridor ({percent(snap.snap_rate, 1)}). Every drop is counted and has a
            reason.
          </p>
          <table className="table table--narrow">
            <thead>
              <tr>
                <th>Reason a crash was dropped</th>
                <th className="num">Crashes</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(snap.dropped_reasons).map(([reason, n]) => (
                <tr key={reason}>
                  <td>{reason.replace(/_/g, " ")}</td>
                  <td className="num">{count(n)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ) : null}
    </Section>
  );
}

/**
 * Out-of-sample validation, reported by default and including when it fails.
 *
 * There is no flag that turns this on and none that turns it off. A model that cannot
 * predict road it has not seen is a finding the report carries, not a computation the
 * caller may decline.
 */
export function ValidationSection({ assessment }: { assessment: Assessment }) {
  const validation = assessment.validation;
  if (!validation) return null;

  if (!validation.available) {
    return (
      <Section id="validation" title="Does it predict road it has not seen?">
        <p className="caveat">
          {validation.refusal ??
            "This corridor is too small to hold out a piece of and still fit the rest."}
        </p>
      </Section>
    );
  }

  const calibrations = [
    validation.spatial ? { label: "held-out stretches", calibration: validation.spatial } : null,
    validation.random ? { label: "random split", calibration: validation.random } : null,
  ].filter((item): item is { label: string; calibration: NonNullable<typeof item>["calibration"] } =>
    item !== null,
  );

  return (
    <Section
      id="validation"
      title="Does it predict road it has not seen?"
      lead="The model is refitted with stretches of the corridor held back, then asked to predict them. Reported whatever the answer is."
    >
      <p>
        {validation.passed
          ? "The model predicts held-out road at close to the right level."
          : "The model does not predict held-out road well. Treat the ranking as indicative and the counts as weak."}
      </p>

      <CalibrationBars calibrations={calibrations} />

      {validation.optimism !== null ? (
        <p className="footnote">
          A random split flatters the model by {percent(Math.abs(validation.optimism), 1)}{" "}
          relative to holding out contiguous road — which is why the spatial split is
          the one to read.
        </p>
      ) : null}

      {validation.cure.length > 0 ? (
        <>
          <h3>Cumulative residuals</h3>
          <div className="figures">
            {validation.cure.map((cure) => (
              <CurePlot cure={cure} key={cure.factor} />
            ))}
          </div>
        </>
      ) : null}

      {validation.notes.map((note) => (
        <p className="caveat" key={note}>
          {note}
        </p>
      ))}
    </Section>
  );
}

/**
 * Reference material, kept apart from everything above it.
 *
 * The brief files the spline as reference only — never in the client report. It is
 * here because hiding a diagnostic is worse than labelling one, and the label is the
 * point: nothing in this section is a number to act on.
 */
export function ReferenceSection({ assessment }: { assessment: Assessment }) {
  const shapes = (assessment.reference?.shapes ?? []).filter((shape) => shape.curve);
  if (shapes.length === 0) return null;

  return (
    <Section
      id="reference"
      title="Reference — diagnostics, not findings"
      lead="These say what shape a relationship has. They do not produce an effect size, and nothing here should be quoted as one."
    >
      <div className="figures">
        {shapes.map((shape) => (
          <SplineCurve shape={shape} key={shape.factor} />
        ))}
      </div>
    </Section>
  );
}

/** Credits, and the sentence a client redistributing the panel needs to have read. */
export function AttributionSection({ corridor }: { corridor: Corridor }) {
  const attribution = corridor.attribution;
  if (attribution.obligations.length === 0) return null;

  return (
    <Section id="attribution" title="Credits and licensing">
      {attribution.credit_lines.length > 0 ? (
        <>
          <h3>Credit these sources</h3>
          <ul className="credits">
            {attribution.credit_lines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </>
      ) : null}

      {attribution.database_warning ? (
        <p className="caveat caveat--strong">{attribution.database_warning}</p>
      ) : null}

      {attribution.unrecognised.length > 0 ? (
        <p className="caveat caveat--strong">
          Unrecognised licence(s): {attribution.unrecognised.join(", ")}. Check their
          terms before this report is shared.
        </p>
      ) : null}

      <table className="table table--narrow">
        <thead>
          <tr>
            <th>Licence</th>
            <th>Applies to</th>
            <th>What it requires</th>
          </tr>
        </thead>
        <tbody>
          {attribution.obligations.map((obligation) => (
            <tr key={obligation.licence}>
              <td className="nowrap">{obligation.licence}</td>
              <td className="small">{obligation.factors.join(", ")}</td>
              <td className="small">{obligation.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Section>
  );
}
