import Problem from "@/components/Problem";
import { attempt, getHealth, listArtefacts } from "@/lib/api";
import { when } from "@/lib/format";

export const metadata = { title: "Files" };

/**
 * The files this run wrote, if it wrote any.
 *
 * A second screen about a run, and the reason the mode banner is in the run segment's
 * layout rather than on the report page: this one shows no numbers at all and still has
 * to say what produced them, because a reader who downloads `ranking.csv` from here is
 * downloading a Mode B ranking or a Mode A fit and the difference is the whole point.
 *
 * **Downloads are proxied through this app.** The API needs `X-Tenant-Id` and a browser
 * has none — that header belongs to a server this operator controls, not to a document
 * they hand out. So the link points here, and this app fetches the bytes with the header
 * and passes them on.
 */
export default async function RunFilesPage({
  params,
}: {
  params: { runId: string };
}) {
  const [artefacts, deployment] = await Promise.all([
    attempt(listArtefacts(params.runId)),
    getHealth(),
  ]);
  if (!artefacts.ok) return <Problem error={artefacts.error} what="file list" />;

  const downloadable = deployment.reachable && deployment.health.artefacts_available;

  return (
    <div className="shell-page">
      <div className="shell-card">
        <h2>Files</h2>

        {artefacts.value.length === 0 ? (
          <>
            <p className="shell-empty">This run wrote none.</p>
            <p className="shell-note">
              Not a fault. A run assessed by this service is stored as a payload and
              nothing else — the report you are looking at is rendered from it on
              demand, which is what makes a run stored months ago still readable. Files
              arrive with runs imported from a machine that produced them:{" "}
              <code>roadrisk store import run/run.json --project …</code>.
            </p>
          </>
        ) : (
          <>
            <table className="shell-table">
              <thead>
                <tr>
                  <th>File</th>
                  <th>Size</th>
                  <th>SHA-256</th>
                  <th>Written</th>
                </tr>
              </thead>
              <tbody>
                {artefacts.value.map((artefact) => (
                  <tr key={artefact.id}>
                    <td>
                      {downloadable ? (
                        <a href={`/downloads/${params.runId}/${artefact.kind}`}>
                          {artefact.kind}
                        </a>
                      ) : (
                        artefact.kind
                      )}
                    </td>
                    <td>{artefact.size_bytes.toLocaleString("en-GB")} bytes</td>
                    <td className="shell-mono">{artefact.sha256.slice(0, 16)}</td>
                    <td>{when(artefact.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="shell-note">
              The hash is what the bytes should come to when they arrive. Everything is
              served as an attachment rather than shown in the page —{" "}
              <code>report.html</code> is a document to save, not a page to visit, and
              serving it inline would mean this origin executing a file it does not own
              the write path to.
            </p>
            {downloadable ? null : (
              <p className="shell-problem">
                Downloads are off: the API has no artefact root configured, so it refuses
                to open the paths in these rows. Set{" "}
                <code>$ROADRISK_ARTEFACT_ROOT</code> where the service runs.
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
