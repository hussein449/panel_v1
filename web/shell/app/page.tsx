import Link from "next/link";

import RoadPicker from "@/components/RoadPicker";
import { assessRoadAction } from "@/lib/actions";
import { attempt, basemap, listRuns, tenantId } from "@/lib/api";
import { geocoder } from "@/lib/geocode";
import { when } from "@/lib/format";

/**
 * The front door: a map, a road, a crash file, a button.
 *
 * **What this replaced, and why.** Assessing one road was five screens — create a
 * project, create a corridor by typing a road reference and four decimal bounding-box
 * numbers, fill a job form of ten fields, poll, then find the run. Every one of those
 * objects is real and all of them still exist under *Advanced*. None of them is a
 * question that somebody who has a road and wants it assessed can answer, and asking
 * them in that order was most of what made this feel like paperwork rather than a tool.
 *
 * **Three inputs, and only one of them is typed.** The road comes from clicking the
 * basemap, which is vector tiles carrying OSM's own tags — so a click yields the `ref`
 * or the `name` the fetch will go looking for, rather than something this page invented.
 * The search area is the map view. The crash table is a file, and it is optional in the
 * sense that the run happens without it and honest about what that costs.
 *
 * **Everything the reader is not asked is a default that is stated.** 500 m segments,
 * OSM adapters on, the engine choosing its own mode. The one thing no screen anywhere in
 * this product offers is a way to overrule that last one.
 */
export default async function Home({
  searchParams,
}: {
  searchParams: { error?: string };
}) {
  const runs = tenantId() ? await attempt(listRuns()) : null;
  const latest = runs?.ok ? runs.value.slice(0, 4) : [];
  const service = geocoder();

  return (
    <div className="shell-page shell-page--wide">
      <header className="shell-lede">
        <h1>Assess a road</h1>
        <p>
          Pick a corridor on the map, add a crash table if you have one, and get a
          ranked assessment with every number traceable to the source it came from.{" "}
          <Link href="/about">What this can and cannot tell you</Link>.
        </p>
      </header>

      <RoadPicker
        basemap={basemap()}
        searchEnabled={service !== null}
        geocoderCredit={service?.credit ?? null}
        action={assessRoadAction}
        problem={searchParams.error ?? null}
      />

      {latest.length > 0 ? (
        <div className="shell-card">
          <h2>Recent assessments</h2>
          <table className="shell-table">
            <thead>
              <tr>
                <th>Run</th>
                <th>Mode</th>
                <th>Assessed</th>
              </tr>
            </thead>
            <tbody>
              {latest.map((run) => (
                <tr key={run.id}>
                  <td>
                    <Link href={`/runs/${run.id}`} className="shell-mono">
                      {run.id.slice(0, 8)}
                    </Link>
                  </td>
                  <td>{run.mode}</td>
                  <td>{when(run.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="shell-note">
            <Link href="/runs">Every run</Link> ·{" "}
            <Link href="/projects">Projects and corridors</Link>
          </p>
        </div>
      ) : null}
    </div>
  );
}
