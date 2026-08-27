import { describeProblem, fetchArtefact } from "@/lib/api";
import type { ArtefactKind } from "@/lib/wire";

/**
 * An artefact's bytes, fetched from the API and passed straight on.
 *
 * **Not a screen, which is why it is a route handler and has no layout.** There is
 * nothing here for a banner to sit above: the response is a file.
 *
 * It exists because the API needs `X-Tenant-Id` and a browser has none — and it must
 * not be given one, because that header is not authentication and belongs to a process
 * the operator controls rather than to a page they hand out. So the link in the files
 * list points here, this fetches with the header, and the bytes go through unchanged.
 *
 * **Unchanged is the point.** The hash the files list shows is what these bytes should
 * come to, so anything that rewrote them on the way past would break the one check a
 * reader can make. The body is streamed rather than read into memory for the same
 * reason a 15 MB PDF should not become a JavaScript string.
 */

/** Exactly what the store can hold. A path segment from a URL is never trusted. */
const KINDS: readonly ArtefactKind[] = [
  "report.html",
  "report.pdf",
  "run.json",
  "ranking.csv",
];

const PASS_THROUGH = [
  "content-type",
  "content-disposition",
  "content-length",
  "etag",
  "last-modified",
];

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  { params }: { params: { runId: string; kind: string } },
) {
  if (!KINDS.includes(params.kind as ArtefactKind)) {
    return new Response(`No artefact kind called ${params.kind}.`, {
      status: 404,
      headers: { "content-type": "text/plain; charset=utf-8" },
    });
  }

  let upstream: Response;
  try {
    upstream = await fetchArtefact(params.runId, params.kind);
  } catch (error) {
    return new Response(describeProblem(error), {
      status: 502,
      headers: { "content-type": "text/plain; charset=utf-8" },
    });
  }

  const headers = new Headers();
  for (const name of PASS_THROUGH) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }

  return new Response(upstream.body, { status: upstream.status, headers });
}
