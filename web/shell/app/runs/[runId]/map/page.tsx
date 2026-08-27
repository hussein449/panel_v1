import Problem from "@/components/Problem";
import RunMap from "@/components/RunMap";
import { attempt, getRun, mapStyleUrl } from "@/lib/api";

export const metadata = { title: "Map" };

/**
 * Step 5.3c — the corridor on a map, and what any segment on it is made of.
 *
 * **A third screen about one run, and it needed nothing from step 5.3b to be honest.**
 * The mode banner above it is the run segment's layout, so this page states which mode
 * produced the colours it is drawing without containing a line about it. That was the
 * argument for putting the banner in a layout, made concrete by the first route added
 * afterwards.
 *
 * The page itself is a server component that fetches the run and hands it over. MapLibre
 * is loaded in the browser and nowhere else — see `RunMap`.
 */
export default async function RunMapPage({
  params,
}: {
  params: { runId: string };
}) {
  const run = await attempt(getRun(params.runId));
  if (!run.ok) return <Problem error={run.error} what="run" />;

  return (
    <div className="shell-page">
      <RunMap run={run.value.payload} styleUrl={mapStyleUrl()} />
    </div>
  );
}
