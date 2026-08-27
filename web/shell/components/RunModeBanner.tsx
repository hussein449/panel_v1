import { when } from "@/lib/format";
import type { StoredRun } from "@/lib/wire";

/** The limitation the engine writes when the corridor was invented rather than fetched. */
const SYNTHETIC = "synthetic_corridor";

/**
 * Which mode produced this run, on every screen about it.
 *
 * Rendered by `app/runs/[runId]/layout.tsx`, not by the pages under it, and that is the
 * point: 5.3c adds a map and 5.3d adds a detail layer, both as children of that layout,
 * and neither can arrive without this. The engine picks the mode and the user cannot,
 * so the one thing a screen must never do is show a ranking without saying which kind
 * of ranking it is.
 *
 * **The report carries its own copy of this**, and the duplication is deliberate. The
 * report is the artefact that leaves the building — emailed, printed, read a year later
 * with nothing around it — so its banner belongs to the document and prints on every
 * page. This one belongs to the screens that are *not* the document.
 *
 * The words come from the run: `assessment.banner` is written by the engine at the
 * moment it settled on a mode, and Mode B's version says *ranking only, not a crash
 * prediction* because the one failure this product cannot afford is a ranking read as a
 * forecast. Nothing here rewrites it.
 */
export default function RunModeBanner({ run }: { run: StoredRun }) {
  const { assessment, limitations, corridor } = run.payload;
  const demo = limitations.some((limitation) => limitation.code === SYNTHETIC);
  const tone = demo ? "demo" : assessment.mode === "A" ? "a" : "b";

  return (
    <aside
      className={`shell-runbanner shell-runbanner--${tone}`}
      aria-label="What produced this run"
    >
      <p className="shell-runbanner__head">
        <span>{assessment.banner}</span>
        <span>· {assessment.rung}</span>
        {demo ? <span>· demonstration</span> : null}
      </p>
      <p className="shell-runbanner__detail">
        {demo ? (
          <>
            <strong>There is no real road in this run.</strong> The corridor is
            synthetic and the crashes were invented, so every number below describes a
            fixture.{" "}
          </>
        ) : null}
        {corridor ? corridor.corridor.name : "Panel supplied directly"} · assessed{" "}
        {when(run.created_at)} · engine v{run.engine_version} · fingerprint{" "}
        <code>{run.fingerprint.slice(0, 12)}</code>
      </p>
    </aside>
  );
}
