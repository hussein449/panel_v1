/**
 * What crosses the wire, as TypeScript.
 *
 * GENERATED FILE — do not edit by hand.
 *
 * Source of truth: `roadrisk.store.records`, `roadrisk.api.schemas` and
 *                  `roadrisk.api.errors` on the Python side.
 * Regenerate:      python tools/generate_types.py
 * Payload schema:  1.0
 *
 * The *envelope*, not the payload. `types.ts` in the report library describes what a run
 * is; this describes what the API says around one — the project it belongs to, the job
 * that produced it, the files it wrote, and what this deployment admits about itself.
 *
 * Generated for the same reason the payload is. A hand-written `Job` here is the step
 * 4.7 defect one layer out: `JobStatus` grows a sixth value, the shell has five, and a
 * job in the new state renders as nothing at all.
 *
 * Two names are not the Python ones, and both are deliberate:
 *
 * * **`StoredRun`** is `roadrisk.store.records.Run` — the row, not the payload. The
 *   payload is `Run` in the report library, and one file cannot hold two `Run`s.
 * * **`StoredRun.payload`** and **`Job.params`** are `dict[str, Any]` in Python, because
 *   the store deliberately knows nothing about what it is storing. They are typed here,
 *   because the shell does.
 *
 * **A response has every field; a request body does not.** A Python default is about
 * construction — a `Job` needs no id, because the store is about to give it one — and
 * FastAPI still serialises the field, default and all. So the shapes the API returns
 * carry no `?` at all, and the bodies it accepts carry one wherever a client may leave
 * a field out.
 */

import type { Run as ReportRun } from "roadrisk-report/report";

/** One way of obtaining a factor, with what it costs and what it obliges. */
export interface AdapterOut {
  name: string;
  tier: Tier;
  licence: Licence;
  credit_required: boolean;
  share_alike_database: boolean;
  obligation: string;
  notes: string | null;
}

/** What a stored file is. The bytes never enter the database. */
export type ArtefactKind = "report.html" | "report.pdf" | "run.json" | "ranking.csv";

/**
 * A file belonging to a run, as a client may see it.
 *
 * `uri` is not here. It is a path on the server's disk and a client has no use for
 * one; `href` is the URL that serves the bytes, and `sha256` is what they should hash
 * to when they arrive.
 */
export interface ArtefactOut {
  id: string;
  run_id: string;
  kind: ArtefactKind;
  size_bytes: number;
  sha256: string;
  created_at: string | null;
  href: string;
}

/**
 * A road, as the parameters needed to fetch and segment it again.
 *
 * Deliberately *not* the resolved geometry. Geometry belongs to a run, because the
 * OSM extract behind it changes: two runs of the same corridor a month apart are two
 * different centrelines and must not be conflated. What is stable is the request —
 * this reference, this bounding box, this unit length.
 */
export interface Corridor {
  id: string;
  tenant_id: string;
  project_id: string;
  name: string;
  ref: string | null;
  bbox: [number, number, number, number] | null;
  unit_length_m: number;
  created_at: string | null;
}

/** Created under the project in the path. `project_id` is never in the body. */
export interface CorridorCreate {
  name: string;
  /** Road reference as OSM knows it, e.g. 'B9'. Null for a client-supplied centreline. */
  ref?: string | null;
  bbox?: [number, number, number, number] | null;
  unit_length_m?: number;
}

/** See :class:`ProjectPatch`. `project_id` is not editable — see the store. */
export interface CorridorPatch {
  name?: string | null;
  ref?: string | null;
  bbox?: [number, number, number, number] | null;
  unit_length_m?: number | null;
}

/** The response body of every refusal this API makes. */
export interface ErrorBody {
  error: Refusal;
}

/**
 * What kind of refusal this is, as something a client can branch on.
 *
 * Codes rather than status alone, because 422 is doing two jobs — a malformed request
 * body and a panel that breaks the input contract are both 422 and are not the same
 * problem. A client retries the first after fixing its JSON and the second after
 * fixing its data.
 */
export type ErrorCode = "tenant_required" | "invalid_request" | "contract_violation" | "payload_rejected" | "not_found" | "in_use" | "artefact_unavailable" | "too_large" | "engine_refused" | "internal";

/**
 * How Mode A's numbers are arrived at. **Not** which mode or rung is used.
 *
 * The distinction matters, because ``assess`` deliberately exposes no way to force a
 * mode or a rung and a test asserts it never grows one. That rule is about *data
 * adequacy*: whether a panel can support seven terms or three is the engine's call,
 * never the caller's, because a caller who could overrule it would overrule it.
 *
 * This is a different question. The ladder still decides the mode, the rung and the
 * terms, identically either way; this only decides how the coefficients on those
 * terms are estimated. A test pins that: the same panel returns the same mode, rung
 * and factor list under both estimators.
 */
export type Estimator = "nb2" | "bayes";

/**
 * The road type a weight was estimated on, or that a corridor is.
 *
 * ``ANY`` on a weight means the source does not restrict by facility. ``ANY`` on a
 * run means the corridor type was not declared, in which case only unrestricted
 * weights are admissible — the engine will not guess.
 */
export type FacilityType = "rural_two_lane" | "rural_multilane" | "urban_arterial" | "any";

/** A declared model term, exactly as `factors.yaml` declares it. */
export interface FactorOut {
  name: string;
  label: string;
  column: string;
  transform: Transform;
  expected_sign: Sign;
  drop_priority: number;
  sourced: boolean;
  weight_count: number;
  missing_behaviour: string;
  adapters: AdapterOut[];
  notes: string | null;
}

/** One thing wrong with the request, and where. */
export interface FieldError {
  /** Dotted path into the request, e.g. 'body.name'. */
  location: string;
  message: string;
}

/**
 * What this deployment is, said plainly rather than left to be discovered.
 *
 * `runner` is null until 5.1d and that is the honest answer: a job posted here today
 * is accepted, stored and queued, and nothing will pick it up. Reporting `"ok"` and
 * letting a client watch a job sit in `queued` forever would be a working service
 * that lies.
 */
export interface Health {
  status: "ok";
  engine_version: string;
  schema_version: string;
  registry_version: string;
  runner: string | null;
  auth: string | null;
  artefacts_available: boolean;
}

/**
 * One request to assess a corridor, and where it got to.
 *
 * `params` is the assessment's own options — estimator, priors, spatial, which
 * adapters to run. Stored as given so that a job can be re-run identically, and so
 * that the manifest's fingerprint has something to be checked against.
 */
export interface Job {
  id: string;
  tenant_id: string;
  project_id: string;
  corridor_id: string | null;
  status: JobStatus;
  params: JobSpec;
  attempts: number;
  error: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}

/**
 * The assessment's own options — exactly the CLI's, and nothing invented here.
 *
 * Everything absent has the same default the command line has, so a job submitted
 * with no options at all is the run `roadrisk corridor` would have done.
 *
 * What is deliberately **not** here: any way to force a mode, a rung or a term. The
 * engine decides those from data adequacy, `assess` exposes no argument for them, and
 * a test in `tests/test_engine.py` asserts it never grows one. A caller who could
 * overrule the ladder would overrule it.
 */
export interface JobOptions {
  facility_type?: FacilityType;
  region?: Region;
  severity?: Severity;
  estimator?: Estimator;
  use_registry_priors?: boolean;
  use_spatial?: boolean;
  /** Factors to put a rung 3 spline on. Validated against `factors.yaml` at submit — a name no factor has is a typo, and finding it in a run log a quarter of an hour later helps nobody. */
  shape_factors?: string[];
  adapters?: ("osm" | "rasters" | "traffic" | "mapillary")[];
  unit_length_m?: number | null;
  tolerance_m?: number;
  n_periods?: number;
}

/**
 * What is stored in `job.params`, and what 5.1d reads back to execute it.
 *
 * Written down as a model rather than left as a loose dictionary because a job has to
 * be re-runnable identically — that is what makes the manifest's fingerprint checkable
 * against anything. A dictionary nobody has described is a dictionary that grows a key
 * somebody forgot to read.
 */
export interface JobSpec {
  source: "corridor" | "panel" | "demo";
  options: JobOptions;
  panel: (Record<string, unknown>)[] | null;
}

/**
 * Where a job is, and nothing about what it concluded.
 *
 * The distinction this vocabulary exists to protect: **a job that descended to Mode B
 * succeeded.** Refusing Mode A, dropping a term, declining to score an unsourced
 * weight — those are findings the run carries, not failures of the job. `failed` is
 * reserved for the machinery breaking: Overpass returning 429, a missing token, a
 * worker dying. Collapsing the two would put the engine's honesty into an error log
 * where nobody reads it.
 */
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "rejected";

/**
 * One request to assess something. Exactly one of `corridor_id`, `panel` or `demo`.
 *
 * Three ways in. Two of them are the command line's: `roadrisk corridor` builds a
 * panel from geography, `roadrisk assess` judges one you already have, and neither is
 * the degraded case. The third is the demonstration, which exists so that this API can
 * be tried end to end without a road, a crash extract or a network.
 */
export interface JobSubmission {
  project_id: string;
  corridor_id?: string | null;
  /** Rows of a panel you already built, as objects. Validated against the input contract before the job exists, so a panel that could never be assessed never becomes a queued job. */
  panel?: (Record<string, unknown>)[] | null;
  /** Assess a synthetic 10 km corridor with an invented crash table. Needs no network and no data. **The resulting report says on its own face that there is no real road in it** — the flag travels into the payload and the limitations page reports it as material, so a demonstration cannot be mistaken for an assessment by whoever you send it to. */
  demo?: boolean;
  params?: JobOptions;
}

/**
 * Licence attached to a value, carried through to the report.
 *
 * ODbL and CC-BY-SA both impose share-alike on a redistributed derived *database*.
 * The report is fine with attribution; the dataset is not. Hence this travels with
 * every value rather than being assumed per project.
 *
 * ``CC-BY-4.0`` is attribution without share-alike — a materially lighter obligation
 * than the two above and a materially heavier one than public domain. It is separate
 * because collapsing it into either would misstate what the client must do.
 */
export type Licence = "ODbL" | "CC-BY-SA" | "CC-BY-4.0" | "public-domain" | "proprietary" | "client";

export interface LicenceOut {
  code: Licence;
  credit_required: boolean;
  share_alike_database: boolean;
  obligation: string;
}

/** A body of work — usually one road authority's network, or one study. */
export interface Project {
  id: string;
  tenant_id: string;
  name: string;
  spend_cap: number | null;
  created_at: string | null;
}

/** A body of work — usually one road authority's network, or one study. */
export interface ProjectCreate {
  name: string;
  spend_cap?: number | null;
}

/**
 * Only the fields actually sent are applied.
 *
 * Which is why `spend_cap` being null has to mean *clear it* and an absent
 * `spend_cap` has to mean *leave it*. Pydantic distinguishes those through
 * ``exclude_unset``; a bag of optional arguments on the store would not, which is why
 * :meth:`roadrisk.store.Store.update_project` takes a whole record instead.
 */
export interface ProjectPatch {
  name?: string | null;
  spend_cap?: number | null;
}

/** Why the request was refused, in the terms the caller can act on. */
export interface Refusal {
  code: ErrorCode;
  /** Written for a person. Names the column, the id or the setting. */
  message: string;
  /** The single thing at fault, when there is one. */
  field: string | null;
  /** Every fault found, when a request had more than one. */
  errors: FieldError[];
}

/**
 * Where a weight was estimated, or where a corridor is.
 *
 * Region granularity, not country, because published weights are estimated on
 * regional or national datasets and never on "Cyprus" specifically. A Cyprus
 * corridor declares ``europe`` and gets European evidence where it exists, global
 * evidence otherwise, and North American evidence only as a last resort — with the
 * reach reported.
 *
 * Stage 2 will resolve this from the corridor's admin boundary automatically; the
 * GADM and OSM-relation adapters are already declared for that.
 */
export type Region = "north_america" | "europe" | "australasia" | "asia" | "africa" | "middle_east" | "latin_america" | "global";

/**
 * The whole registry as served, including what it hashed to.
 *
 * `sha256` is the file's, computed by the loader. A client comparing it against the
 * one inside a run's manifest can tell whether that run was assessed under the
 * registry this API is now serving — which is the only honest way to answer "is this
 * still current".
 */
export interface RegistryOut {
  version: string;
  sha256: string | null;
  source: string;
  factor_count: number;
  sourced_count: number;
  tiers: TierOut[];
  licences: LicenceOut[];
  factors: FactorOut[];
}

/**
 * A run without its payload. What a listing is made of.
 *
 * Every field is one the store lifted out of the payload on insert, so a summary
 * cannot describe a different run than the one it points at.
 */
export interface RunSummary {
  id: string;
  tenant_id: string;
  project_id: string;
  job_id: string | null;
  corridor_id: string | null;
  schema_version: string | null;
  engine_version: string;
  fingerprint: string;
  mode: string;
  rung: string;
  created_at: string | null;
}

/**
 * Which crashes a weight predicts.
 *
 * This is not decoration. The Elvik Power Model exponent is 1.6 for injury crashes
 * and 4.1 for fatal ones — applying the wrong one is a factor-of-two error, and
 * before this existed the registry silently assumed injury.
 */
export type Severity = "all" | "injury" | "fsi" | "fatal";

/** The direction a factor is expected to push risk. The guard rail. */
export type Sign = "+" | "-";

/**
 * A finished assessment: the whole payload, plus the few things worth indexing.
 *
 * The payload is stored entire and is the only source of truth. Every other column
 * here is a copy of something inside it, lifted out so a list of runs can be drawn
 * without opening any of them — and each one is written from the payload on insert,
 * never supplied separately, so they cannot disagree with it.
 */
export interface StoredRun {
  id: string;
  tenant_id: string;
  project_id: string;
  job_id: string | null;
  corridor_id: string | null;
  schema_version: string | null;
  engine_version: string;
  fingerprint: string;
  mode: string;
  rung: string;
  payload: ReportRun;
  created_at: string | null;
}

/**
 * Who pays to obtain the value.
 *
 * A — open, global, scriptable, free.
 * B — open, but needs vision models or graph compute.
 * C — free-tier APIs, licence-limited, opt-in per project.
 * D — cannot be derived; the client must measure and supply it.
 */
export type Tier = "A" | "B" | "C" | "D";

export interface TierOut {
  code: Tier;
  meaning: string;
}

/** How a raw column is mapped before it enters the model. */
export type Transform = "identity" | "ln" | "ln1p" | "zscore";
