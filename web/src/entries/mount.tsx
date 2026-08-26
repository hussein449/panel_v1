/**
 * Entry point two: the report mounted into a page somebody else owns.
 *
 * The Next.js shell at 5.3b renders `<Report run={run} />` directly, because it is React
 * and can. This exists for every host that is not — a server-rendered template, a plain
 * HTML page, an iframe, a dashboard that is not built in React — and it is the surface
 * the library build emits.
 *
 * **It is thin on purpose, and the thinness is the deliverable.** Where a run comes from
 * is the caller's problem: this one is handed a run, where `standalone.tsx` reads one out
 * of the document. Neither renders any part of the report, both import the same
 * `<Report>`, and that is what makes "the app renders the same component tree" true by
 * construction rather than something to be checked by eye afterwards.
 */

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";

import { Boundary, Report } from "../report";
import type { Run } from "../report";

export type { Assessment, Corridor, Limitation, Run } from "../report";
export { Report, Boundary } from "../report";

/**
 * Draw a run into an element, and hand back the handle to take it down again.
 *
 * Wrapped in the same `Boundary` the standalone bundle uses. A host that mounted the
 * bare component would get React's own behaviour on an uncaught error — the whole tree
 * unmounted, the host's page left with a hole in it and no explanation — which is
 * exactly the failure the boundary was written for, and there is no reason a host
 * should have to know to add it.
 *
 * @param container The element to draw into. Its contents are replaced.
 * @param run A run payload: `run.json`, or `GET /runs/{id}`'s `payload`.
 */
export function mountReport(container: Element, run: Run): Root {
  const root = createRoot(container);
  root.render(
    <StrictMode>
      <Boundary>
        <Report run={run} />
      </Boundary>
    </StrictMode>,
  );
  return root;
}
