import {
  AttributionSection,
  ChecksSection,
  FactorsSection,
  Headline,
  ModeBanner,
  ModelSection,
  PanelSection,
  RankingSection,
  Receipts,
  ReferenceSection,
  ValidationSection,
} from "./sections";
import type { Run } from "./types";

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
export default function Report({ run }: { run: Run }) {
  const { assessment, corridor } = run;
  const ranking = assessment.ranking;

  return (
    <article className="report">
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
          dropped and where every number came from. A limitations page is added at step
          4.6 and cannot be switched off.
        </p>
      </footer>
    </article>
  );
}
