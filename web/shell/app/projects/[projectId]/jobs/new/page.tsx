import Problem from "@/components/Problem";
import { submitJobAction } from "@/lib/actions";
import { attempt, getProject, listCorridors } from "@/lib/api";

export const metadata = { title: "Assess something" };

const FACILITY_TYPES = [
  ["any", "any — unrestricted evidence only"],
  ["rural_two_lane", "rural two-lane"],
  ["rural_multilane", "rural multilane"],
  ["urban_arterial", "urban arterial"],
];

const REGIONS = [
  ["global", "global"],
  ["europe", "Europe"],
  ["north_america", "North America"],
  ["australasia", "Australasia"],
  ["asia", "Asia"],
  ["africa", "Africa"],
  ["middle_east", "Middle East"],
  ["latin_america", "Latin America"],
];

const SEVERITIES = [
  ["all", "all crashes"],
  ["injury", "injury"],
  ["fsi", "fatal and serious"],
  ["fatal", "fatal"],
];

const ADAPTERS = [
  ["osm", "OpenStreetMap — speed, lanes, lighting, junctions, accesses, buildings"],
  ["rasters", "DEM and land cover — grade and roadside built-up share (needs GDAL)"],
  ["traffic", "strategic network graph — the traffic proxy"],
  ["mapillary", "roadside fixed objects (needs a token)"],
];

/**
 * One request to assess something.
 *
 * **There is no way to pick a mode, a rung or a term here, and there will not be.** The
 * engine decides those from data adequacy, the command line exposes no argument for
 * them, the API's `JobOptions` declares none, and a test in `tests/test_engine.py`
 * asserts it never grows one. A form that could overrule the ladder would overrule it.
 */
export default async function NewJobPage({
  params,
  searchParams,
}: {
  params: { projectId: string };
  searchParams: { error?: string };
}) {
  const project = await attempt(getProject(params.projectId));
  if (!project.ok) return <Problem error={project.error} what="project" />;

  const corridors = await attempt(listCorridors(params.projectId));
  const available = corridors.ok ? corridors.value : [];

  return (
    <div className="shell-page">
      <h1>Assess something</h1>
      <p className="shell-note">in {project.value.name}</p>

      {searchParams.error ? (
        <p className="shell-problem">{searchParams.error}</p>
      ) : null}

      <div className="shell-card">
        <form className="shell-form" action={submitJobAction}>
          <input type="hidden" name="project_id" value={params.projectId} />

          <fieldset>
            <legend>What to assess</legend>
            <label className="shell-check">
              <input type="radio" name="source" value="demo" defaultChecked />
              <span>
                <strong>A demonstration.</strong> A synthetic 10 km corridor with an
                invented crash table. No network, no data, seconds to finish — and the
                report says on its own face that there is no real road in it.
              </span>
            </label>
            <label className="shell-check">
              <input
                type="radio"
                name="source"
                value="corridor"
                disabled={available.length === 0}
              />
              <span>
                <strong>A corridor.</strong>{" "}
                {available.length === 0
                  ? "This project has none yet."
                  : "Fetched and segmented from the reference or box it was created with."}
              </span>
            </label>
            {available.length > 0 ? (
              <label>
                Corridor
                <select name="corridor_id" defaultValue={available[0].id}>
                  {available.map((corridor) => (
                    <option key={corridor.id} value={corridor.id}>
                      {corridor.name}
                      {corridor.ref ? ` (${corridor.ref})` : ""}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
          </fieldset>

          <fieldset>
            <legend>Context</legend>
            <p className="shell-hint">
              What the corridor <em>is</em>. Declaring it lets the engine reach for
              evidence derived on that kind of road, in that region, for that severity;
              leaving it undeclared admits unrestricted evidence only. The report states
              which it reached for either way.
            </p>
            <label>
              Facility type
              <select name="facility_type" defaultValue="any">
                {FACILITY_TYPES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Region
              <select name="region" defaultValue="global">
                {REGIONS.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Severity
              <select name="severity" defaultValue="all">
                {SEVERITIES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </fieldset>

          <fieldset>
            <legend>Estimation</legend>
            <label>
              Estimator
              <select name="estimator" defaultValue="nb2">
                <option value="nb2">NB2 — negative binomial, seconds</option>
                <option value="bayes">
                  Bayesian — posterior intervals, tens of minutes
                </option>
              </select>
            </label>
            <label className="shell-check">
              <input type="checkbox" name="use_registry_priors" />
              <span>Use the registry&rsquo;s cited weights as priors</span>
            </label>
            <label className="shell-check">
              <input type="checkbox" name="use_spatial" />
              <span>Fit a spatial field over the units</span>
            </label>
          </fieldset>

          <fieldset>
            <legend>Sources to fetch</legend>
            <p className="shell-hint">
              These apply to a corridor job, and are <strong>not sent</strong> for a
              demonstration: its centreline is invented, so a query along it would be
              asking real sources about a road that does not exist, and the API refuses
              that combination at submit rather than filling a provenance table with
              answers about somewhere else. An adapter that fails costs its own factor,
              not the corridor.
            </p>
            {ADAPTERS.map(([value, label]) => (
              <label key={value} className="shell-check">
                <input type="checkbox" name="adapters" value={value} />
                <span>{label}</span>
              </label>
            ))}
          </fieldset>

          <button type="submit" className="shell-button">
            Submit
          </button>
          <p className="shell-hint">
            Submitting returns immediately. Assessment happens behind the request — a
            cold corridor is around a minute, and a Bayesian fit is tens of them — so the
            next screen is the job, not the answer.
          </p>
        </form>
      </div>
    </div>
  );
}
