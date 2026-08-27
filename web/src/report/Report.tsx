import {
  AttributionSection,
  ChecksSection,
  FactorsSection,
  Headline,
  LimitationsSection,
  ModeBanner,
  ModelSection,
  PanelSection,
  RankingSection,
  Receipts,
  ReferenceSection,
  ValidationSection,
} from "./sections";
import type { Run } from "./types";
import { SegmentFocusProvider } from "./focus";

/**
 * The report.
 *
 * One renderer. This component is what a client reads on screen, what prints to PDF
 * under the rules in step 4.5, and what Stage 5.3 imports as its report tab — not a
 * second template kept in visual sync with the web app by hand.
 *
 * It takes a plain object and nothing else. No fetching, no state, no engine types:
 * everything it renders came out of `Assessment.as_dict()` and
 * `CorridorPanel.as_dict()`, which is what lets a run stored months ago render
 * identically today.
 */
/**
 * Escape a string for use inside a CSS `content: "..."` value.
 *
 * The banner is user-adjacent text going into a stylesheet. A stray quote would end
 * the string and leave a broken `@page` rule — which fails quietly, as a PDF with no
 * running header rather than as an error.
 */
const cssString = (text: string): string =>
  text.replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, " ");

/**
 * The running header, written as a literal into a `@page` rule.
 *
 * The brief wants the mode banner on every page of the PDF, and a page banner has to
 * come from paged-media CSS — there is no element that repeats. Chrome supports
 * `@page` margin boxes and page counters but not `string-set`, and it does not need
 * to: one report is one mode, so the banner is the same on every page and can be
 * baked in at render time.
 */
function PageBanner({ banner }: { banner: string }) {
  return (
    <style>{`@media print { @page { @top-center {
      content: "${cssString(banner)}";
      font-family: "Segoe UI", system-ui, sans-serif;
      font-size: 8pt;
      font-weight: 600;
      color: #4a5158;
    } } }`}</style>
  );
}

export default function Report({ run }: { run: Run }) {
  const { assessment, corridor } = run;
  const ranking = assessment.ranking;

  return (
    // Step 5.3d. One piece of state, so that the strip, the map in plan and the ranked
    // table stop being three unrelated pictures of the same twenty segments. It changes
    // nothing about what is drawn — every mark keeps the `<title>` a reader with no
    // JavaScript relies on, and the readout it drives is `no-print`.
    <SegmentFocusProvider>
    <article className="report">
      <PageBanner banner={assessment.banner} />
      <div className="toolbar no-print">
        <button type="button" onClick={() => window.print()}>
          Print / Save as PDF
        </button>
      </div>
      <header className="report__header">
        <ModeBanner assessment={assessment} />
        <h1>
          {corridor ? corridor.corridor.name : "Corridor"} — road risk assessment
        </h1>
        <p className="report__subtitle">
          {assessment.context.declared
            ? `${assessment.context.facility_type} · ${assessment.context.region} · ${assessment.context.severity}`
            : "Corridor type, region and crash severity were not declared, so only unrestricted evidence was admitted."}
        </p>
      </header>

      <Headline run={run} />
      <Receipts assessment={assessment} />

      {ranking ? <RankingSection ranking={ranking} corridor={corridor} /> : null}
      <ModelSection assessment={assessment} />
      <ValidationSection assessment={assessment} />
      {corridor ? <FactorsSection corridor={corridor} /> : null}
      <PanelSection run={run} />
      <ChecksSection assessment={assessment} />
      {corridor ? <AttributionSection corridor={corridor} /> : null}
      <ReferenceSection assessment={assessment} />
      {/* No condition, no prop that empties it, and last so it is where a
          reader looks for it. Removing this line is a code change with a
          failing test attached. */}
      <LimitationsSection limitations={run.limitations ?? []} />

      <footer className="report__footer">
        <p>
          Run fingerprint{" "}
          <span className="mono">
            {String(assessment.manifest.panel_sha256 ?? "").slice(0, 16) || "unknown"}
          </span>
          {run.engine_version ? ` · engine v${run.engine_version}` : null}
          {run.generated_at ? ` · generated ${run.generated_at}` : null}
        </p>
        <p className="small muted">
          This report states which mode produced it, every check that ran, every term
          dropped, and where every number came from. What it cannot tell you is set out
          on its own page above, assembled from this run rather than written in advance,
          and there is no setting that removes it.
        </p>
      </footer>
    </article>
    </SegmentFocusProvider>
  );
}
