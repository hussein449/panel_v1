/**
 * Step 5.3a — the report, as a library.
 *
 * **One renderer.** This is what a client reads on screen, what prints to PDF under the
 * rules in step 4.5, and what the Next.js shell at 5.3b mounts as its report route. Not
 * a second template kept in visual sync with the web app by hand — a component, imported
 * twice.
 *
 * Everything above this line is an *entry point*: it decides where a run comes from and
 * where the tree is mounted, and it renders nothing of the report itself. That split is
 * the whole of this step. It is also why "the app renders the same component tree" is
 * true by construction rather than by comparison — there is one `Report`, both entries
 * import this file, and neither has anything else to render.
 *
 * **It takes a plain object and nothing else.** No fetching, no state, no engine types:
 * everything it draws came out of `Assessment.as_dict()` and `CorridorPanel.as_dict()`,
 * which is what lets a run stored months ago render identically today. `types.ts` is
 * generated from `roadrisk.contract` by `tools/generate_types.py` and is not edited by
 * hand.
 *
 * **The stylesheet is part of the library, not of a page.** A host that imported the
 * component and supplied its own CSS would be a second renderer with extra steps.
 */

export { default as Report } from "./Report";
export { Boundary } from "./Boundary";
export type { Assessment, Corridor, Limitation, Run } from "./types";

/**
 * The risk scale, for anything else that draws risk.
 *
 * Also its own entry point — `roadrisk-report/risk` — which is what the map at 5.3c
 * imports. That path carries no React, no payload types and no stylesheet, so something
 * that wants six colours does not pull a whole report in behind them.
 */
export { RISK_RAMP, riskColour } from "./risk";

import "./styles.css";
