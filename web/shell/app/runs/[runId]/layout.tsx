import Link from "next/link";

import Problem from "@/components/Problem";
import RunModeBanner from "@/components/RunModeBanner";
import { attempt, getRun } from "@/lib/api";

/**
 * Everything about one run sits inside this.
 *
 * **The mode banner is here, not on the report page.** A run has more than one screen
 * already — the report and the files it wrote — and 5.3c adds a map, 5.3d a detail
 * layer. Each of those is a child of this layout, so each of them states which mode
 * produced the numbers it is showing, without anybody having to remember. That is the
 * same argument as the deployment banner in the root layout, one level down: a fact
 * that must be on every screen belongs to the thing every screen is inside.
 *
 * **A run that cannot be loaded renders nothing but the reason.** The children are not
 * rendered at all in that case, which is deliberate — a tab strip over an empty page
 * would invite a reader to try the next tab, and every one of them would fail the same
 * way.
 *
 * One fetch, not four: `getRun` is memoised for the render, so this layout and the page
 * inside it share the payload rather than pulling 300 kB each.
 */
export default async function RunLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: { runId: string };
}) {
  const run = await attempt(getRun(params.runId));

  if (!run.ok) {
    return (
      <div className="shell-page">
        <Problem error={run.error} what="run" />
      </div>
    );
  }

  return (
    <>
      <RunModeBanner run={run.value} />
      <nav className="shell-tabs shell-chrome" aria-label="This run">
        <Link href={`/runs/${params.runId}`}>Report</Link>
        <Link href={`/runs/${params.runId}/files`}>Files</Link>
      </nav>
      {children}
    </>
  );
}
