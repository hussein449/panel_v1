/**
 * Place search, so that finding a road does not begin with panning across an ocean.
 *
 * **This is the second external service this product calls, and that is a decision
 * rather than a convenience.** The basemap was the first and is documented as the only
 * one; a geocoder is the second, and it is here because the alternative was worse. A map
 * that opens on the whole world and asks a road engineer to pan to their corridor is a
 * map nobody uses twice — and the road *reference* they would happily have typed is the
 * one thing they usually do not know, because it is what this tool is for finding.
 *
 * **It is proxied through this app, never called from the browser.** Nominatim's usage
 * policy requires an identifying `User-Agent`, and a browser will not let a page set one
 * — `User-Agent` is a forbidden header name, so a client-side fetch would arrive
 * anonymous and in breach. Routing it through the server also means the viewer's IP
 * never reaches a third party for a search they typed on this page, which is the same
 * reason artefact downloads are proxied rather than linked.
 *
 * **The operator can point it anywhere, or switch it off.** `$ROADRISK_GEOCODER_URL`
 * takes any Nominatim-compatible endpoint — a self-hosted instance, a commercial one —
 * and `none` removes the search box entirely, exactly as `$ROADRISK_MAP_STYLE=none`
 * removes the basemap. A deployment that must make no external request keeps working;
 * it just pans.
 */

export const GEOCODER_ENV = "ROADRISK_GEOCODER_URL";

export const DEFAULT_GEOCODER = "https://nominatim.openstreetmap.org/search";

/**
 * Who is asking. Nominatim's policy requires this and is entitled to: it is a free
 * service paid for by donations, and anonymous traffic is what gets blocked. The same
 * string `geo/osm.py` sends to Overpass, for the same reason.
 */
export const USER_AGENT =
  "roadrisk-panel (road safety assessment; contact via repository)";

/**
 * What Nominatim's terms require said, said by us.
 *
 * Same reasoning as `DEFAULT_MAP_CREDIT`: the obligation is ours whether or not any
 * control happens to render. An endpoint somebody else configured gets no line from us,
 * because we do not know what it owes.
 */
export const DEFAULT_GEOCODER_CREDIT =
  '<a href="https://osm.org/copyright" target="_blank" rel="noreferrer">Search by Nominatim, © OpenStreetMap contributors</a>';

export interface Geocoder {
  url: string;
  /** Null for an endpoint this deployment configured: its credit is the operator's. */
  credit: string | null;
  ours: boolean;
}

export function geocoder(): Geocoder | null {
  const configured = process.env[GEOCODER_ENV]?.trim();

  if (configured === undefined || configured === "") {
    return { url: DEFAULT_GEOCODER, credit: DEFAULT_GEOCODER_CREDIT, ours: true };
  }
  if (["none", "off", "false"].includes(configured.toLowerCase())) return null;
  return { url: configured, credit: null, ours: false };
}

export interface Place {
  label: string;
  /** south, west, north, east — the order this whole codebase uses. */
  bbox: [number, number, number, number];
}

/** How many results are worth showing. More is a list nobody reads to the end of. */
const LIMIT = 5;

/**
 * Nominatim's usage policy caps unauthenticated use at one request a second and asks for
 * a timeout rather than an open connection. The debounce that keeps us under that lives
 * on the client, where the typing is; this is the backstop.
 */
const TIMEOUT_MS = 8_000;

/**
 * Look a place up. Returns an empty list rather than throwing on a bad answer.
 *
 * A search box that shows "no results" when the geocoder is down is wrong, so a genuine
 * failure does throw — the caller distinguishes them. What is *not* an error is a
 * well-formed answer with nothing in it.
 */
export async function search(query: string): Promise<Place[]> {
  const service = geocoder();
  if (service === null) return [];

  const trimmed = query.trim();
  if (trimmed.length < 2) return [];

  const url = new URL(service.url);
  url.searchParams.set("q", trimmed);
  url.searchParams.set("format", "jsonv2");
  url.searchParams.set("limit", String(LIMIT));

  const response = await fetch(url, {
    headers: {
      // Nominatim refuses anonymous traffic, and is entitled to: it is a free service
      // paid for by donations. This is the same string the Overpass client sends.
      "User-Agent": USER_AGENT,
      Accept: "application/json",
    },
    signal: AbortSignal.timeout(TIMEOUT_MS),
    // Places do not move. Caching keeps repeat searches off somebody else's service.
    next: { revalidate: 86_400 },
  });

  if (!response.ok) {
    throw new Error(
      `The place search service answered ${response.status}. ` +
        "The map still works — pan and zoom to the road instead.",
    );
  }

  const found: unknown = await response.json();
  if (!Array.isArray(found)) return [];

  return found.flatMap((entry) => {
    const box = asBoundingBox(entry);
    const label = typeof entry?.display_name === "string" ? entry.display_name : null;
    return box && label ? [{ label, bbox: box }] : [];
  });
}

/**
 * Nominatim's `boundingbox` is `[south, north, west, east]` as **strings**, which is
 * neither this codebase's order nor its type. Converting here means exactly one place
 * knows that, and a malformed entry is dropped rather than becoming a box that is
 * inside out — which the API would refuse anyway, but with a message about latitude
 * that would make no sense to somebody who had typed a town name.
 */
function asBoundingBox(entry: any): [number, number, number, number] | null {
  const raw = entry?.boundingbox;
  if (!Array.isArray(raw) || raw.length !== 4) return null;

  const [south, north, west, east] = raw.map(Number);
  const numbers = [south, north, west, east];
  if (numbers.some((value) => !Number.isFinite(value))) return null;
  if (south >= north || west >= east) return null;
  if (Math.abs(south) > 90 || Math.abs(north) > 90) return null;
  if (Math.abs(west) > 180 || Math.abs(east) > 180) return null;

  return [south, west, north, east];
}
