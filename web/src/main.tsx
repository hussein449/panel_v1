import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";

import Report from "./Report";
import type { Run } from "./types";
import "./styles.css";

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
    const assessment = byName["assessment.json"];
    if (!assessment) {
      setError("Select assessment.json — and corridor.json alongside it, if you have one.");
      return;
    }
    onLoad({
      assessment: assessment as Run["assessment"],
      corridor: (byName["corridor.json"] as Run["corridor"]) ?? null,
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
      <App />
    </StrictMode>,
  );
}
