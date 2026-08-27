import Link from "next/link";

import AutoRefresh from "@/components/AutoRefresh";
import Problem from "@/components/Problem";
import { attempt, getJob, getJobRun } from "@/lib/api";
import { when } from "@/lib/format";
import type { JobOptions } from "@/lib/wire";

export const metadata = { title: "Job" };

/** The options a submission actually chose, without reprinting eleven defaults. */
function chosen(options: JobOptions): string[] {
  const said: string[] = [];
  if (options.facility_type && options.facility_type !== "any")
    said.push(options.facility_type);
  if (options.region && options.region !== "global") said.push(options.region);
  if (options.severity && options.severity !== "all") said.push(options.severity);
  if (options.estimator && options.estimator !== "nb2") said.push(options.estimator);
  if (options.use_registry_priors) said.push("registry priors");
  if (options.use_spatial) said.push("spatial field");
  if (options.shape_factors?.length)
    said.push(`splines on ${options.shape_factors.join(", ")}`);
  if (options.adapters?.length) said.push(`fetching ${options.adapters.join(", ")}`);
  return said;
}

export default async function JobPage({ params }: { params: { jobId: string } }) {
  const job = await attempt(getJob(params.jobId));
  if (!job.ok) return <Problem error={job.error} what="job" />;

  const { status, params: spec } = job.value;
  const inFlight = status === "queued" || status === "running";
  const run = status === "succeeded" ? await attempt(getJobRun(params.jobId)) : null;
  const options = chosen(spec.options);

  return (
    <div className="shell-page">
      {inFlight ? <AutoRefresh seconds={3} /> : null}

      <h1>
        Job <span className="shell-mono">{job.value.id.slice(0, 8)}</span>
      </h1>
      <p>
        <span className={`shell-status shell-status--${status}`}>{status}</span>
      </p>

      <div className="shell-card">
        <table className="shell-table">
          <tbody>
            <tr>
              <th>Assesses</th>
              <td>{spec.source}</td>
            </tr>
            <tr>
              <th>Options</th>
              <td>
                {options.length ? (
                  options.join(" · ")
                ) : (
                  <span className="shell-empty">
                    all defaults — the run `roadrisk corridor` would have done
                  </span>
                )}
              </td>
            </tr>
            <tr>
              <th>Submitted</th>
              <td>{when(job.value.created_at)}</td>
            </tr>
            <tr>
              <th>Started</th>
              <td>{when(job.value.started_at)}</td>
            </tr>
            <tr>
              <th>Finished</th>
              <td>{when(job.value.finished_at)}</td>
            </tr>
            <tr>
              <th>Attempts</th>
              <td>{job.value.attempts}</td>
            </tr>
            <tr>
              <th>Project</th>
              <td>
                <Link href={`/projects/${job.value.project_id}`} className="shell-mono">
                  {job.value.project_id.slice(0, 8)}
                </Link>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      {inFlight ? (
        <div className="shell-card">
          <h2>Working</h2>
          <p>
            This screen asks the server again every few seconds. It also refreshes on a{" "}
            <Link href={`/jobs/${params.jobId}`}>check again</Link> — the automatic part
            is the only thing in this app that needs JavaScript.
          </p>
          <p className="shell-note">
            A cold corridor is about a minute: the fetches happen once per region and are
            cached afterwards. A Bayesian fit is tens of minutes and there is nothing
            wrong when it is.
          </p>
        </div>
      ) : null}

      {job.value.error ? (
        <div className="shell-card">
          <h2>{status === "rejected" ? "The panel was refused" : "It failed"}</h2>
          <p className="shell-problem">{job.value.error}</p>
          <p className="shell-note">
            {status === "rejected"
              ? "Nothing malfunctioned. The panel broke the input contract, so there " +
                "was nothing to assess, and the receipt naming what was wrong is the " +
                "whole result. No run was produced and there is nothing to clean up."
              : "The machinery broke — a source refusing, a token missing, a process " +
                "stopping. This is a cause, not a traceback; the traceback is in the " +
                "service's log with a reference."}
          </p>
        </div>
      ) : null}

      {run ? (
        run.ok ? (
          <div className="shell-card">
            <h2>Finished</h2>
            <p>
              <Link className="shell-button" href={`/runs/${run.value.id}`}>
                Open the report
              </Link>
            </p>
            <p className="shell-note">
              {run.value.mode} · {run.value.rung}. A descent to Mode B is a job that{" "}
              <strong>succeeded</strong> — the mode, the checks that failed and the terms
              dropped are findings the run carries, and they are on the report.
            </p>
          </div>
        ) : (
          <Problem error={run.error} what="run" />
        )
      ) : null}
    </div>
  );
}
