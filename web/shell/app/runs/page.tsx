import Link from "next/link";

import Problem from "@/components/Problem";
import { attempt, listRuns } from "@/lib/api";
import { when } from "@/lib/format";

export const metadata = { title: "Runs" };

/**
 * Every finished assessment, newest first.
 *
 * Summaries, not payloads — a run is around 300 kB and fifty of them is a download
 * nobody asked for. Every column here was lifted out of the payload by the store when
 * the run was inserted, so a row cannot describe a different run than the one it links
 * to.
 *
 * **The mode is a column, not a detail.** A listing that showed only names and dates
 * would let a Mode B ranking sit beside a Mode A fit looking like the same kind of
 * answer, which is the confusion this whole product exists to prevent.
 */
export default async function RunsPage() {
  const runs = await attempt(listRuns());
  if (!runs.ok) return <Problem error={runs.error} what="runs" />;

  return (
    <div className="shell-page">
      <h1>Runs</h1>

      <div className="shell-card">
        {runs.value.length === 0 ? (
          <p className="shell-empty">
            No finished assessments. A demonstration job produces one in seconds.
          </p>
        ) : (
          <table className="shell-table">
            <thead>
              <tr>
                <th>Run</th>
                <th>Mode</th>
                <th>Rung</th>
                <th>Assessed</th>
                <th>Engine</th>
                <th>Fingerprint</th>
              </tr>
            </thead>
            <tbody>
              {runs.value.map((run) => (
                <tr key={run.id}>
                  <td>
                    <Link href={`/runs/${run.id}`} className="shell-mono">
                      {run.id.slice(0, 8)}
                    </Link>
                  </td>
                  <td>{run.mode}</td>
                  <td>{run.rung}</td>
                  <td>{when(run.created_at)}</td>
                  <td>v{run.engine_version}</td>
                  <td className="shell-mono">{run.fingerprint.slice(0, 12)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
