/**
 * Entry point one: the single file you open by double-clicking.
 *
 * This is the `report.html` that `roadrisk corridor --report` writes — one document,
 * everything inlined, no server and no network. That is step 4.3's done-when and it is
 * not an arbitrary bar: a corridor can be assessed offline with no API key, and a report
 * that then needed a web server to be read would have put the network back into the one
 * product that does without it.
 *
 * **Everything specific to that is here, and nothing else is.** Where the run comes from
 * — injected into the document, or picked off disk — is this file's whole job. The report
 * itself is `../report`, which the app at 5.3b imports as well, so the two surfaces
 * cannot drift into drawing different things.
 */

import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";

import { Boundary, Report } from "../report";
import type { Run } from "../report";

/**
 * Read the run the Python side injected into the page.
 *
 * The build ships a `<script type="application/json">null</script>` placeholder and
 * `roadrisk.report.write_report` replaces the `null` with a real run. Parsing it here
 * — rather than fetching a sibling `.json` — is what lets the report open from a
 * `file://` URL: a browser will not `fetch()` a local file, but it will happily read
 * a script tag that is already in the document.
 */
function embeddedRun(): Run | null {
  const node = document.getElementById("roadrisk-run");
  if (!node?.textContent) return null;
  try {
    const parsed = JSON.parse(node.textContent);
    return parsed && parsed.assessment ? (parsed as Run) : null;
  } catch {
    return null;
  }
}

/**
 * The fallback when the bundle is opened on its own.
 *
 * `roadrisk corridor --out` writes `assessment.json` and `corridor.json` beside the
 * report, so someone holding a run directory but not a generated report can still read
 * it. `FileReader` works from `file://` where `fetch` does not.
 */
function Loader({ onLoad }: { onLoad: (run: Run) => void }) {
  const [error, setError] = useState<string | null>(null);

  const read = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const byName: Record<string, unknown> = {};
    for (const file of Array.from(files)) {
      try {
        byName[file.name] = JSON.parse(await file.text());
      } catch {
        setError(`${file.name} is not valid JSON.`);
        return;
      }
    }
    // `run.json` is the whole envelope and is preferred, because it is the only file
    // carrying the limitations. They are assembled when the run is built and live
    // nowhere else, so a report reassembled from the two halves alone is missing the
    // page step 4.6 says nothing may remove.
    const whole = byName["run.json"] as Run | undefined;
    if (whole?.assessment) {
      onLoad(whole);
      return;
    }

    const assessment = byName["assessment.json"];
    if (!assessment) {
      setError(
        "Select run.json — or assessment.json, with corridor.json beside it if you have one.",
      );
      return;
    }
    onLoad({
      assessment: assessment as Run["assessment"],
      corridor: (byName["corridor.json"] as Run["corridor"]) ?? null,
      // Absent by construction on this path: all three are properties of a *built*
      // run, not of either half. Empty rather than invented — the limitations section
      // prints its own warning when handed nothing, which is the honest outcome.
      limitations: [],
      generated_at: "",
      engine_version: "",
    });
  };

  return (
    <div className="loader">
      <h1>Road risk assessment</h1>
      <p>
        This page has no run in it. Choose the <code>assessment.json</code> and{" "}
        <code>corridor.json</code> written by <code>roadrisk corridor --out</code>.
      </p>
      <input
        type="file"
        accept="application/json,.json"
        multiple
        onChange={(event) => void read(event.target.files)}
      />
      {error ? <p className="caveat caveat--strong">{error}</p> : null}
      <p className="small muted">
        Nothing is uploaded. The files are read in this browser and never leave it.
      </p>
    </div>
  );
}

function App() {
  const [run, setRun] = useState<Run | null>(embeddedRun);
  return run ? <Report run={run} /> : <Loader onLoad={setRun} />;
}

const container = document.getElementById("root");
if (container) {
  createRoot(container).render(
    <StrictMode>
      <Boundary>
        <App />
      </Boundary>
    </StrictMode>,
  );
}
