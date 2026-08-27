import Link from "next/link";

import Problem from "@/components/Problem";
import { attempt, getProject, listCorridors, listJobs, listRuns } from "@/lib/api";
import { bbox, metres, when } from "@/lib/format";
import type { Job } from "@/lib/wire";

export const metadata = { title: "Project" };

/** What a job was asked to assess, read back off the spec the submission stored. */
function source(job: Job): string {
  return job.params.source;
}

export default async function ProjectPage({
  params,
  searchParams,
}: {
  params: { projectId: string };
  searchParams: { error?: string };
}) {
  const project = await attempt(getProject(params.projectId));
  if (!project.ok) return <Problem error={project.error} what="project" />;

  const [corridors, jobs, runs] = await Promise.all([
    attempt(listCorridors(params.projectId)),
    attempt(listJobs(params.projectId)),
    attempt(listRuns(params.projectId)),
  ]);

  return (
    <div className="shell-page">
      <h1>{project.value.name}</h1>
      <p className="shell-mono">{project.value.id}</p>

      {searchParams.error ? (
        <p className="shell-problem">{searchParams.error}</p>
      ) : null}

      <p>
        <Link className="shell-button" href={`/projects/${params.projectId}/jobs/new`}>
          Assess something
        </Link>
      </p>

      <div className="shell-card">
        <h2>Corridors</h2>
        <p className="shell-note">
          A corridor is the <em>request</em> that fetches and segments a road, not the
          geometry it resolved to. Geometry belongs to a run: the extract behind a road
          changes, and two runs of the same corridor a month apart are two different
          centrelines that must not be conflated.
        </p>
        {!corridors.ok ? (
          <Problem error={corridors.error} what="corridors" />
        ) : corridors.value.length === 0 ? (
          <p className="shell-empty">
            None. A demonstration job needs no corridor at all.
          </p>
        ) : (
          <table className="shell-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Reference</th>
                <th>Box (S, W, N, E)</th>
                <th>Unit</th>
              </tr>
            </thead>
            <tbody>
              {corridors.value.map((corridor) => (
                <tr key={corridor.id}>
                  <td>{corridor.name}</td>
                  <td className="shell-mono">{corridor.ref ?? "—"}</td>
                  <td className="shell-mono">{bbox(corridor.bbox)}</td>
                  <td>{metres(corridor.unit_length_m)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p>
          <Link href={`/projects/${params.projectId}/corridors/new`}>New corridor</Link>
        </p>
      </div>

      <div className="shell-card">
        <h2>Jobs</h2>
        <p className="shell-note">
          <strong>A job that descended to Mode B succeeded.</strong> Refusing Mode A,
          dropping a term, declining to score an unsourced weight — those are findings
          the run carries, not failures of the job. <code>failed</code> is the machinery
          breaking, and <code>rejected</code> is a panel that broke the input contract,
          which is a receipt rather than an error.
        </p>
        {!jobs.ok ? (
          <Problem error={jobs.error} what="jobs" />
        ) : jobs.value.length === 0 ? (
          <p className="shell-empty">Nothing submitted yet.</p>
        ) : (
          <table className="shell-table">
            <thead>
              <tr>
                <th>Job</th>
                <th>Status</th>
                <th>Assesses</th>
                <th>Submitted</th>
              </tr>
            </thead>
            <tbody>
              {jobs.value.map((job) => (
                <tr key={job.id}>
                  <td>
                    <Link href={`/jobs/${job.id}`} className="shell-mono">
                      {job.id.slice(0, 8)}
                    </Link>
                  </td>
                  <td>
                    <span className={`shell-status shell-status--${job.status}`}>
                      {job.status}
                    </span>
                  </td>
                  <td>{source(job)}</td>
                  <td>{when(job.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="shell-card">
        <h2>Runs</h2>
        {!runs.ok ? (
          <Problem error={runs.error} what="runs" />
        ) : runs.value.length === 0 ? (
          <p className="shell-empty">No finished assessments yet.</p>
        ) : (
          <table className="shell-table">
            <thead>
              <tr>
                <th>Run</th>
                <th>Mode</th>
                <th>Rung</th>
                <th>Assessed</th>
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
