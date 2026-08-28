import { search } from "@/lib/geocode";

/**
 * Place search, proxied.
 *
 * **Not a screen, so a route handler with no layout** — the response is a list, the same
 * reasoning as the artefact download beside it.
 *
 * **The browser never calls the geocoder directly, and cannot.** Nominatim's usage policy
 * requires an identifying `User-Agent`, and `User-Agent` is a forbidden header name in
 * `fetch` — a page cannot set it, so a client-side call would arrive anonymous and in
 * breach of the terms this deployment agreed to by using the service. Proxying also
 * keeps the viewer's IP address off a third party for a search they typed here, which is
 * the same reason artefact downloads go through this app rather than being linked.
 */

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const query = new URL(request.url).searchParams.get("q") ?? "";

  try {
    return Response.json(await search(query));
  } catch (error) {
    // The message is written for the person typing, not for a log: the map still works
    // without search, and saying so is more useful than a status code.
    return new Response(
      error instanceof Error
        ? error.message
        : "The place search did not answer. Pan and zoom to the road instead.",
      { status: 502 },
    );
  }
}
