import Problem from "@/components/Problem";
import ReportView from "@/components/ReportView";
import { attempt, getRun } from "@/lib/api";

export const metadata = { title: "Report" };

/**
 * The report, served as an application rather than as a file.
 *
 * This page renders one component and no part of a report. `<Report>` is the same
 * component the single-file bundle in the Python package is built from — the thing that
 * gets emailed, and the thing that prints to PDF under step 4.5's rules — so what is on
 * this screen and what arrives in somebody's inbox cannot drift apart. There is no
 * second template kept in visual sync by hand, which is exactly what step 4.3 refused
 * and what an app tab would have quietly reintroduced.
 *
 * Printing this page produces the report and nothing else: the shell's chrome is hidden
 * in `@media print`, and the report's own paged-media rules take over — including its
 * mode banner in the running header of every page.
 */
export default async function RunReportPage({
  params,
}: {
  params: { runId: string };
}) {
  const run = await attempt(getRun(params.runId));
  if (!run.ok) return <Problem error={run.error} what="run" />;

  return <ReportView run={run.value.payload} />;
}
