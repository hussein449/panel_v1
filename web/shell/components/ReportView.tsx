"use client";

import { Boundary, Report } from "roadrisk-report/report";
import type { Run } from "roadrisk-report/report";

/**
 * The report, in the app.
 *
 * **This renders no part of the report.** It is this app's version of the entry points
 * in `web/src/entries/`, and it exists for the same reason they do: `<Report>` is one
 * component, imported by everything that shows a report, so the single file that gets
 * emailed and the page served here cannot drift into drawing different things. A
 * heading added here instead of in the library would be the first millimetre of that
 * drift, and `tests/test_shell.py` fails on it.
 *
 * `"use client"` because the report has a print button and `Boundary` is an error
 * boundary — both need the browser. The cost is honest and worth naming: the run's
 * payload is serialised into the page so the client can hydrate it, which is a few
 * hundred kilobytes. 5.3d is where that stops being the whole document.
 *
 * `Boundary` comes from the library rather than being written again here. It is what
 * turns a rendering failure into a message instead of a blank white page, and a host
 * should not have to know to add it.
 */
export default function ReportView({ run }: { run: Run }) {
  return (
    <Boundary>
      <Report run={run} />
    </Boundary>
  );
}
