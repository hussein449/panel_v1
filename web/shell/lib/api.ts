/**
 * The one place this shell talks to the API.
 *
 * **Every call in here happens on the server.** No page in this app fetches from the
 * browser, and that is a decision rather than a habit: the tenant is carried in
 * `X-Tenant-Id`, which is not authentication — anybody may claim to be any tenant until
 * step 5.4a puts real identities and row-level policies underneath it. A header like
 * that belongs to a process the operator controls, not to a document they hand out. It
 * also means artefact downloads are proxied by this app rather than linked to directly:
 * a browser hitting the API with no tenant header gets a 401, and giving the browser the
 * header would be the thing this paragraph exists to avoid.
 *
 * **This module is also the seam 5.4a replaces.** One file sets one header; when the
 * tenant comes from a session instead of the environment, this is what changes.
 *
 * **What throws and what does not.** Everything here throws on a refusal or an
 * unreachable API — except {@link getHealth}, which never does. The banner is rendered
 * by the root layout, and a layout that throws takes the whole screen with it: the one
 * thing that must never disappear would be the one thing an outage removes.
 *
 * Pages then call through {@link attempt}, which turns a throw back into a value, and
 * render the message themselves. That is not ceremony: Next replaces an uncaught server
 * error with *"an error occurred in the Server Components render"* in a production
 * build, and a shell whose entire argument is that a refusal is a result cannot hand the
 * reader a digest hash. `error.tsx` is still there for the unforeseen — it is the last
 * resort, not the plan.
 */

import { cache } from "react";

import type {
  ArtefactOut,
  Corridor,
  ErrorBody,
  Health,
  Job,
  JobSubmission,
  Project,
  RegistryOut,
  RunSummary,
  StoredRun,
} from "./wire";

/** Where the API is, from this process. */
export const API_URL_ENV = "ROADRISK_API_URL";

/**
 * Whose rows this deployment shows.
 *
 * There is exactly one, because there is no login yet. A shell without it can still be
 * opened — the banner and this fact are the first things on the screen — and every page
 * that would touch a row says what to set instead of failing at the fetch.
 */
export const TENANT_ENV = "ROADRISK_TENANT_ID";

const DEFAULT_API_URL = "http://127.0.0.1:8000";

export function apiUrl(): string {
  return (process.env[API_URL_ENV] || DEFAULT_API_URL).replace(/\/+$/, "");
}

export function tenantId(): string | null {
  return process.env[TENANT_ENV]?.trim() || null;
}

/**
 * A MapLibre style URL to draw a basemap under the corridor, if the operator wants one.
 *
 * **Unset is the default, and the map is complete without it.** A tile source is a
 * network dependency and an attribution obligation, and this product's posture is that a
 * corridor can be assessed with no key and no connection — so a basemap is something you
 * switch on, not something you switch off. The map page states which of the two it is
 * showing, and the style's own credit appears in the corner when there is one.
 */
export const MAP_STYLE_ENV = "ROADRISK_MAP_STYLE";

export function mapStyleUrl(): string | null {
  return process.env[MAP_STYLE_ENV]?.trim() || null;
}

/** A refusal the API sent, in the one envelope it sends every refusal in. */
export class ApiRefusal extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly field: string | null = null,
  ) {
    super(message);
    this.name = "ApiRefusal";
  }
}

/** The API could not be reached at all, which is not the same as being refused by it. */
export class ApiUnreachable extends Error {
  constructor(
    readonly url: string,
    readonly reason: string,
  ) {
    super(`Cannot reach the road-risk API at ${url}: ${reason}`);
    this.name = "ApiUnreachable";
  }
}

/**
 * No tenant is configured, so there is nothing this shell is allowed to look at.
 *
 * Its own class because it is a setup problem rather than a failure, and the page that
 * catches it says which variable to set rather than showing an error.
 */
export class TenantNotConfigured extends Error {
  constructor() {
    super(
      `No tenant is configured. Set $${TENANT_ENV} to the id printed by ` +
        "`roadrisk store new-tenant`.",
    );
    this.name = "TenantNotConfigured";
  }
}

function requireTenant(): string {
  const tenant = tenantId();
  if (!tenant) throw new TenantNotConfigured();
  return tenant;
}

function describeCause(error: unknown): string {
  const cause = (error as { cause?: { code?: string; message?: string } })?.cause;
  return (
    cause?.code || cause?.message || (error as Error)?.message || "no reason given"
  );
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  /** Off for `GET /health` and `GET /registry`, which describe the service, not a row. */
  tenanted?: boolean;
}

/**
 * One request, and one shape for everything that can come back wrong.
 *
 * `no-store` on every call: a run listing that showed yesterday's jobs because a cache
 * was warm would be worse than a slow page. Nothing here is expensive enough to be
 * worth the class of bug caching introduces, and the expensive thing — a fit — is a job
 * that this app polls rather than a request it waits on.
 */
async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, tenanted = true } = options;
  const url = `${apiUrl()}${path}`;

  const headers: Record<string, string> = { Accept: "application/json" };
  if (tenanted) headers["X-Tenant-Id"] = requireTenant();
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
  } catch (error) {
    throw new ApiUnreachable(apiUrl(), describeCause(error));
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();

  if (!response.ok) {
    // Every refusal this API produces has the same envelope, including FastAPI's own
    // validation errors — that is the contract 5.1c enforced with exception handlers.
    // The fallback below is for a proxy or a gateway answering instead of the API,
    // which is the one thing that can put a different shape on this wire.
    try {
      const parsed = JSON.parse(text) as ErrorBody;
      throw new ApiRefusal(
        response.status,
        parsed.error.code,
        parsed.error.message,
        parsed.error.field,
      );
    } catch (error) {
      if (error instanceof ApiRefusal) throw error;
      throw new ApiRefusal(
        response.status,
        "unrecognised",
        `The API answered ${response.status} with a body this client does not ` +
          `recognise: ${text.slice(0, 200) || "(empty)"}`,
      );
    }
  }

  return JSON.parse(text) as T;
}

/** What the banner is drawn from, including the case where there is nothing to draw. */
export type Deployment =
  | { reachable: true; url: string; tenant: string | null; health: Health }
  | { reachable: false; url: string; tenant: string | null; reason: string };

/**
 * What this deployment is, or why that could not be established.
 *
 * The only function here that does not throw. See the module docstring: the banner is a
 * layout element, and an unreachable API must change what it says rather than remove it.
 */
export const getHealth = cache(async (): Promise<Deployment> => {
  const url = apiUrl();
  const tenant = tenantId();
  try {
    const health = await request<Health>("/health", { tenanted: false });
    return { reachable: true, url, tenant, health };
  } catch (error) {
    const reason =
      error instanceof ApiUnreachable
        ? error.reason
        : error instanceof ApiRefusal
          ? `${error.status} ${error.message}`
          : String(error);
    return { reachable: false, url, tenant, reason };
  }
});

export const getRegistry = cache(
  async (): Promise<RegistryOut> => request("/registry", { tenanted: false }),
);

export const listProjects = cache(
  async (): Promise<Project[]> => request("/projects"),
);

export const getProject = cache(
  async (id: string): Promise<Project> => request(`/projects/${id}`),
);

export async function createProject(
  name: string,
  spendCap: number | null,
): Promise<Project> {
  return request("/projects", {
    method: "POST",
    body: { name, spend_cap: spendCap },
  });
}

export const listCorridors = cache(
  async (projectId: string): Promise<Corridor[]> =>
    request(`/projects/${projectId}/corridors`),
);

export async function createCorridor(
  projectId: string,
  body: {
    name: string;
    ref: string | null;
    bbox: [number, number, number, number] | null;
    unit_length_m: number;
  },
): Promise<Corridor> {
  return request(`/projects/${projectId}/corridors`, { method: "POST", body });
}

export const listJobs = cache(
  async (projectId: string): Promise<Job[]> => request(`/projects/${projectId}/jobs`),
);

export const getJob = cache(async (id: string): Promise<Job> => request(`/jobs/${id}`));

/**
 * The run a job produced.
 *
 * Fetched only once a job has succeeded, and only to link to it: the API has no
 * "which run came out of this job" endpoint that stops short of the payload, so this
 * pulls the whole 300 kB to read an id off it. Worth naming rather than hiding — it is
 * one fetch on a screen somebody opens twice, and the alternative is a run listing
 * scanned for a job id, which is wrong the moment a project has more runs than a page.
 */
export const getJobRun = cache(
  async (jobId: string): Promise<StoredRun> => request(`/jobs/${jobId}/run`),
);

export async function submitJob(body: JobSubmission): Promise<Job> {
  return request("/jobs", { method: "POST", body });
}

export const listRuns = cache(
  async (projectId?: string): Promise<RunSummary[]> =>
    request(`/runs${projectId ? `?project_id=${projectId}` : ""}`),
);

/**
 * One run, payload and all.
 *
 * Memoised for the render, because the run route's layout and its pages all need it:
 * the layout to state the mode, the report page to draw it. Three fetches of 300 kB to
 * draw one screen would be a self-inflicted wound.
 */
export const getRun = cache(
  async (id: string): Promise<StoredRun> => request(`/runs/${id}`),
);

export const listArtefacts = cache(
  async (runId: string): Promise<ArtefactOut[]> => request(`/runs/${runId}/artefacts`),
);

/**
 * Fetch an artefact's bytes, for the route handler that proxies them to the browser.
 *
 * Not `request`: the body is a file rather than JSON, and a 15 MB PDF should not be
 * turned into a string on the way past.
 */
export async function fetchArtefact(runId: string, kind: string): Promise<Response> {
  try {
    return await fetch(`${apiUrl()}/runs/${runId}/artefacts/${kind}`, {
      headers: { "X-Tenant-Id": requireTenant() },
      cache: "no-store",
    });
  } catch (error) {
    throw new ApiUnreachable(apiUrl(), describeCause(error));
  }
}

/** A call that came back, or the reason it did not. See the module docstring. */
export type Attempt<T> = { ok: true; value: T } | { ok: false; error: unknown };

export async function attempt<T>(work: Promise<T>): Promise<Attempt<T>> {
  try {
    return { ok: true, value: await work };
  } catch (error) {
    return { ok: false, error };
  }
}

/** How a person is told what went wrong, whatever went wrong. */
export function describeProblem(error: unknown): string {
  if (error instanceof ApiRefusal) {
    // The field, unless the message already opens with it. FastAPI's own validation
    // errors are reshaped into this envelope with the location in both places, and
    // "body.name: String should have at least 1 character (body.name)" reads like a
    // program talking to itself.
    return error.field && !error.message.includes(error.field)
      ? `${error.message} (${error.field})`
      : error.message;
  }
  if (error instanceof ApiUnreachable || error instanceof TenantNotConfigured) {
    return error.message;
  }
  return error instanceof Error ? error.message : String(error);
}
