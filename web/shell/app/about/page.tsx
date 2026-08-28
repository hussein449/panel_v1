import Link from "next/link";

import { attempt, listRuns, tenantId } from "@/lib/api";
import { when } from "@/lib/format";

export const metadata = { title: "About" };

/**
 * What this is, what it will not do, and how to see one with no data at all.
 *
 * **This was the front page until the map arrived.** It answers three questions in
 * order, and it is the right writing about a tool whose whole value is what it refuses
 * to claim — but they are questions somebody asks *second*. The first is "assess this
 * road", and a page of prose is not where that starts. Nothing here was lost in the
 * move; it stopped being the thing standing between a reader and a corridor.
 */
export default async function About() {
  const runs = tenantId() ? await attempt(listRuns()) : null;
  const latest = runs?.ok ? runs.value.slice(0, 5) : [];

  return (
    <div className="shell-page">
      <h1>Corridor road-risk assessment</h1>
      <p>
        Two coordinates and a crash table in; a ranked corridor out, with every number
        traceable to the source it came from and a page in every report saying what that
        assessment cannot support. The engine decides how much can honestly be concluded
        from the data it was given, and there is no setting that overrules it.
      </p>

      <div className="shell-card">
        <h2>Two modes, and the engine picks</h2>
        <p>
          <strong>Mode A</strong> fits a crash-count model and reports coefficients with
          intervals. It needs crashes, and it needs road that had none — a model built
          only on crash locations cannot estimate a rate, it can only redescribe the
          crash table.
        </p>
        <p>
          <strong>Mode B</strong> is the floor: a weighted index from cited weights,
          ranked, with no counts and no prediction. It is a <em>ranking</em>, and every
          screen that shows one says so.
        </p>
        <p className="shell-note">
          Given the choice, people select Mode A on data that cannot support it and the
          tool prints confident numbers that are fabricated. So there is no such choice:
          the ladder descends on its own and names the check that made it descend.
        </p>
      </div>

      <div className="shell-card">
        <h2>See one without any data</h2>
        <p>
          A demonstration job assesses a synthetic 10 km corridor with an invented crash
          table. It needs no network, no API key and no crash extract, and finishes in
          seconds. <strong>The report it produces says on its own face that there is no
          real road in it</strong> — that travels in the payload, so it cannot be lost
          on the way to whoever you send it to.
        </p>
        <p>
          Start at <Link href="/projects">projects</Link>: a project holds corridors and
          jobs, and a job is one request to assess something.
        </p>
      </div>

      {latest.length > 0 ? (
        <div className="shell-card">
          <h2>Latest runs</h2>
          <table className="shell-table">
            <thead>
              <tr>
                <th>Run</th>
                <th>Mode</th>
                <th>Rung</th>
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
                  <td>{run.rung}</td>
                  <td>{when(run.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
