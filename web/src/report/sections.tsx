import type { Assessment, Corridor, Limitation, Ranking, Run } from "./types";
import {
  CalibrationBars,
  CorridorMap,
  CurePlot,
  RiskStrip,
  SegmentReadout,
  SplineCurve,
} from "./figures";
import {
  ABSENT,
  count,
  decimal,
  extent,
  percent,
  shorten,
  signed,
  significant,
} from "./format";
import { segmentHandlers, useSegmentFocus } from "./focus";
import { buildVerdict, standingLabel } from "./verdict";

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

/**
 * Everything a reader needs before the first table, in one block.
 *
 * This replaces four separate cards — headline tiles, panel facts, the snapping table
 * and the check roll-up — that between them repeated the crash count three times and
 * spread the corridor's basic dimensions over two screens. A reader arriving at a
 * report wants to know how long the road is, how many crashes are on it, how many
 * landed, and whether anything failed; none of that needs a section of its own.
 */
export function SummarySection({ run }: { run: Run }) {
  const { assessment, corridor } = run;
  const snap = corridor?.snap;
  const failed = assessment.checks.filter((c) => c.status === "failed");

  const stats: { label: string; value: string; note?: string }[] = [
    {
      label: "Corridor",
      value: corridor ? `${decimal(corridor.corridor.length_km, 2)} km` : ABSENT,
      note: `${count(assessment.panel.units)} segments`,
    },
    {
      label: "Crashes placed",
      value: count(assessment.panel.total_crashes),
      note: snap
        ? `${percent(snap.snap_rate, 1)} of ${count(snap.n_supplied)} supplied`
        : `over ${count(assessment.panel.periods)} periods`,
    },
    {
      label: "Panel",
      value: `${count(assessment.panel.rows)} rows`,
      note: `${percent(assessment.panel.zero_crash_share)} zero-crash`,
    },
    {
      label: "Checks",
      value: `${assessment.checks.length - failed.length} / ${assessment.checks.length}`,
      note: failed.length === 0 ? "all passed" : `${failed.length} failed`,
    },
  ];

  return (
    <div className="summary">
      <dl className="summary__stats">
        {stats.map((stat) => (
          <div className="stat" key={stat.label}>
            <dt>{stat.label}</dt>
            <dd>{stat.value}</dd>
            {stat.note ? <p className="stat__note">{stat.note}</p> : null}
          </div>
        ))}
      </dl>
      {snap && Object.keys(snap.dropped_reasons).length > 0 ? (
        <p className="summary__drops">
          Not placed:{" "}
          {Object.entries(snap.dropped_reasons)
            .map(([reason, n]) => `${count(n)} ${reason.replace(/_/g, " ")}`)
            .join(" · ")}
          . Every drop is counted and has a reason.
        </p>
      ) : null}
    </div>
  );
}

/**
 * The closing judgement.
 *
 * **It grades the assessment, not the road**, for the reason set out in `verdict.ts`:
 * one corridor fitted from its own crashes is not on a scale with any other, so a
 * safety letter over it would be invented, and it would be the most quotable number
 * here. What it does state is what the run is worth, what it found, and where the
 * crashes actually are — the last of which needs no model to be true.
 */
export function VerdictSection({ run }: { run: Run }) {
  const verdict = buildVerdict(run);
  const { where, finding } = verdict;

  return (
    <Section
      id="verdict"
      title="In summary"
      lead="What this assessment is worth, what it found, and where to send somebody. Every number below is read off the sections above rather than recomputed."
    >
      <div className={`verdict verdict--${verdict.standing}`}>
        <div className="verdict__grade">
          <span className="verdict__standing">{standingLabel(verdict.standing)}</span>
          <span className="verdict__scope">assessment standing</span>
        </div>
        <div className="verdict__body">
          <p className="verdict__headline">{verdict.headline}</p>
          <ul className="verdict__because">
            {verdict.because.map((clause) => (
              <li key={clause}>{clause}</li>
            ))}
          </ul>
        </div>
      </div>

      <div className="verdict__panes">
        <div className="pane">
          <h3>What it found</h3>
          {finding ? (
            <p>
              More <span className="mono">{finding.factor}</span> goes with{" "}
              {finding.estimate > 0 ? "more" : "fewer"} crashes on this corridor —{" "}
              {signed(finding.estimate)} at p = {significant(finding.p_value, 2)}, the
              most confident term in the model. It is an association measured on this
              road, not a prediction of what changing it would do.
            </p>
          ) : (
            <p>
              No factor both cleared significance and agreed with the direction the
              literature expects. That is a finding rather than a gap: the terms the
              model could carry do not separate the segments where crashes happened from
              the ones where they did not.
            </p>
          )}
        </div>

        <div className="pane">
          <h3>Where to look</h3>
          {where ? (
            <p>
              <span className="mono">{where.label}</span>
              {where.shareOfCrashes !== null && where.shareOfLength !== null ? (
                <>
                  {" "}
                  carries {percent(where.shareOfCrashes)} of the corridor's crashes on{" "}
                  {percent(where.shareOfLength)} of its length.
                </>
              ) : (
                " is the worst-ranked stretch."
              )}{" "}
              A site inspection decides what to do about it; this report decides where to
              send one.
            </p>
          ) : (
            <p>
              No blackspot stood out from the rest of the corridor, so there is no single
              place to send an inspection ahead of any other.
            </p>
          )}
        </div>
      </div>

      {verdict.next ? (
        <p className="verdict__next">
          <strong>What would strengthen this:</strong> {verdict.next}
        </p>
      ) : null}
    </Section>
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
  const { focused, focus } = useSegmentFocus();

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
          <SegmentReadout ranking={ranking} />
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
                <tr
                  key={spot.rank}
                  // A blackspot is a run of segments; pointing at the row lights the
                  // worst of them, which is the one the row is named after.
                  className={focused === spot.worst_unit ? "is-focused" : undefined}
                  {...segmentHandlers(spot.worst_unit, focus)}
                >
                  <td>{spot.rank}</td>
                  <td>{spot.n_units}</td>
                  <td>{extent(spot.start_m, spot.end_m) ?? "chainage unknown"}</td>
                  <td>
                    {spot.length_m != null
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
            <tr
              key={unit.unit_id}
              className={focused === unit.unit_id ? "is-focused" : undefined}
              {...segmentHandlers(unit.unit_id, focus)}
            >
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
  // A posterior that exists is not a posterior that can be believed. When the
  // inference ladder ran out of rungs — Laplace refused, then MCMC failed to mix —
  // `posterior` is present, unconverged and carries no coefficients. Reading its mere
  // presence as "we have credible intervals" would put the frequentist numbers under a
  // Bayesian heading, which is the one mislabelling this section must never make.
  const attempted = assessment.posterior;
  const posterior =
    attempted &&
    attempted.converged &&
    Object.keys(attempted.coefficients ?? {}).length > 0
      ? attempted
      : null;
  const refused = attempted && !posterior ? attempted : null;

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
              const credible = posterior?.coefficients[coefficient.factor];
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
        {refused ? (
          <p className="caveat">
            A Bayesian fit was attempted and <strong>could not be believed</strong>, so
            nothing from it is reported and the intervals above are the frequentist
            ones. {refused.descent[refused.descent.length - 1] ?? ""}
          </p>
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
/**
 * The gate checks.
 *
 * **Compact by default, because a passing check is not news.** Ten rows of prose
 * explaining that everything was fine trains a reader to skip the block entirely, and
 * then a failure in it goes past unread. So the passes collapse to a row of named
 * ticks and only the failures and skips keep their sentence — which is where the
 * reader's attention is worth spending.
 */
export function ChecksSection({ assessment }: { assessment: Assessment }) {
  const notable = assessment.checks.filter((c) => c.status !== "passed");
  const passed = assessment.checks.filter((c) => c.status === "passed");

  return (
    <Section
      id="checks"
      title="What was checked before anything was fitted"
      lead="Nine gates decide whether a model may run at all. A hard failure refuses Mode A outright; a soft failure steps it down a rung."
    >
      <ul className="checkstrip">
        {assessment.checks.map((check, index) => (
          <li
            className={`checkstrip__item checkstrip__item--${check.status.toLowerCase()}`}
            key={`${check.number}-${index}`}
            title={`${check.number}. ${check.name} — ${check.message}`}
          >
            <span className="checkstrip__mark" aria-hidden="true" />
            <span className="checkstrip__name">{check.name}</span>
          </li>
        ))}
      </ul>

      {notable.length > 0 ? (
        <dl className="checkdetail">
          {notable.map((check, index) => (
            <div key={`${check.number}-${index}`}>
              <dt>
                <span className={`tag tag--${check.status.toLowerCase()}`}>
                  {check.status}
                </span>{" "}
                {check.number}. {check.name}
              </dt>
              <dd>{check.message}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="footnote">
          All {count(passed.length)} checks passed. Each one's detail is on its tick.
        </p>
      )}
    </Section>
  );
}

/**
 * Where every number came from, and what is owed for using it.
 *
 * Provenance and licensing were two sections asking a reader to hold the same list of
 * factors in mind twice. They are one table and a credits line here: the licence a
 * factor arrived under belongs in the row that names the factor, not in a second table
 * further down keyed by licence.
 */
export function SourcesSection({ corridor }: { corridor: Corridor }) {
  const attribution = corridor.attribution;
  if (corridor.provenance.length === 0 && attribution.obligations.length === 0) {
    return null;
  }

  return (
    <Section
      id="sources"
      title="Where every number came from"
      lead="One row per factor. Tier A is measured from the corridor or from open data; Tier B is inferred. Confidence is the share of segments where the value was measured rather than carried from a neighbour."
    >
      {corridor.provenance.length > 0 ? (
        <table className="table table--provenance">
          <thead>
            <tr>
              <th>Factor</th>
              <th>Source</th>
              <th>Tier</th>
              <th>Licence</th>
              <th className="num">Coverage</th>
              <th className="num">Measured</th>
            </tr>
          </thead>
          <tbody>
            {corridor.provenance.map((row) => (
              <tr key={row.column}>
                <td className="mono">{row.factor}</td>
                <td className="cite" title={row.source}>
                  {shorten(row.source, 64)}
                </td>
                <td>
                  <span className={`tag tag--tier-${row.tier.toLowerCase()}`}>
                    {row.tier}
                  </span>
                </td>
                <td className="nowrap small">{row.licence}</td>
                <td className="num">{percent(row.coverage)}</td>
                <td className="num">{percent(row.confidence_high)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      {corridor.contested.length > 0 ? (
        <p className="footnote">
          {count(corridor.contested.length)} factor(s) were resolved by more than one
          source, so fusion had to choose. Where sources disagreed, the disagreement is
          scored rather than hidden.
        </p>
      ) : null}

      {attribution.credit_lines.length > 0 ? (
        <p className="credits-line">
          <strong>Credit required:</strong> {attribution.credit_lines.join(" · ")}
        </p>
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

/**
 * The limitations page.
 *
 * Rendered for every report with no prop, no flag and no conditional wrapping it. The
 * list is assembled on the Python side from what the run did, so this component cannot
 * be given an empty one by a caller who would rather not show it — and a run with
 * nothing wrong with it still carries the standing caveats, because a report whose
 * limitations page said nothing would be making a claim it cannot support.
 *
 * It is last on the page and starts a new sheet in print, which is the one place a
 * reader looks for it.
 */
export function LimitationsSection({ limitations }: { limitations: Limitation[] }) {
  const bands: { severity: string; heading: string; lead: string }[] = [
    {
      severity: "material",
      heading: "Read these before the numbers",
      lead: "Each of these changes what this assessment can be used to conclude.",
    },
    {
      severity: "caveat",
      heading: "These qualify the numbers",
      lead: "None of these invalidates a result. All of them narrow what it means.",
    },
    {
      severity: "context",
      heading: "Worth knowing",
      lead: "True of this method rather than of anything that went wrong here.",
    },
  ];

  return (
    <Section
      id="limitations"
      title="What this assessment cannot tell you"
      lead="Assembled from what this run actually did, not written in advance. It is part of the report and there is no setting that removes it."
    >
      {bands.map(({ severity, heading, lead }) => {
        const items = limitations.filter((item) => item.severity === severity);
        if (items.length === 0) return null;
        return (
          <div className="limitations" key={severity}>
            <h3>{heading}</h3>
            <p className="lead">{lead}</p>
            <dl className={`limits limits--${severity}`}>
              {items.map((item, index) => (
                <div className="limit" key={`${item.code}-${index}`}>
                  <dt>{item.title}</dt>
                  <dd>{item.detail}</dd>
                </div>
              ))}
            </dl>
          </div>
        );
      })}
      {limitations.length === 0 ? (
        <p className="caveat caveat--strong">
          No limitations were recorded for this run. That is itself a defect — every
          assessment has limits — so treat this report as incomplete and report it.
        </p>
      ) : null}
    </Section>
  );
}
