/**
 * The JSON contract, as TypeScript.
 *
 * These mirror `Assessment.as_dict()` and `CorridorPanel.as_dict()` on the Python
 * side. They are deliberately *narrow* — they describe what the page reads, not
 * everything the payload carries, so that adding a field to the engine never breaks
 * the page and removing one the page uses fails at the type level rather than as a
 * blank cell in front of a client.
 *
 * Fields typed as optional are the ones the payload legitimately omits. The most
 * important of those is Mode B's absent count: `expected` is not `number | null`, it
 * is simply not there, and the type says so because the whole point of step 4.2 was
 * that a null count is still a count-shaped hole.
 */

export interface UnitRisk {
  unit_id: string;
  rank: number;
  percentile: number;
  score: number;
  observed?: number;
  expected?: number;
  expected_low?: number;
  expected_high?: number;
  exposure?: number;
  rate?: number;
  components?: Record<string, number>;
}

export interface Blackspot {
  rank: number;
  unit_ids: string[];
  n_units: number;
  worst_unit: string;
  worst_rank: number;
  score: number;
  start_m?: number;
  end_m?: number;
  length_m?: number;
  observed?: number;
  expected?: number;
}

export interface Ranking {
  mode: string;
  basis: string;
  threshold_percentile: number;
  has_intervals: boolean;
  n_units: number;
  units: UnitRisk[];
  blackspots: Blackspot[];
  notes: string[];
}

export interface Check {
  number: number;
  name: string;
  status: string;
  failure_type: string;
  threshold: number | null;
  observed: number | null;
  message: string;
}

export interface Coefficient {
  factor: string;
  estimate: number;
  std_error: number;
  z_value: number;
  p_value: number;
  ci_low: number;
  ci_high: number;
}

export interface Fit {
  specification: string;
  family: string;
  converged: boolean;
  n_observations: number;
  n_parameters: number;
  alpha: number | null;
  pearson_dispersion: number | null;
  n_clusters: number | null;
  cluster_widening: Record<string, number>;
  panel_notes: string[];
  coefficients: Coefficient[];
}

export interface PosteriorSummary {
  name: string;
  mean: number;
  hdi_low: number;
  hdi_high: number;
}

export interface Posterior {
  specification: string;
  converged: boolean;
  method: string;
  hdi_probability: number;
  coefficients: PosteriorSummary[];
  sigma_u: PosteriorSummary | null;
  descent: string[];
  notes: string[];
}

export interface IndexTerm {
  factor: string;
  label: string;
  weight: number;
  weight_source: string;
  family: string;
  scope: string;
  mean_contribution: number;
  concerns: { code: string; message: string }[];
  agreement: { score: number | null; note: string } | null;
}

/**
 * A calibration result.
 *
 * The numeric fields are nullable because the engine will not invent one it could not
 * compute — a factor with no denominator, a deviation over folds that produced
 * nothing. `null` is what the payload carries and what the formatters render.
 */
export interface Calibration {
  scheme: string;
  n_folds: number;
  observed: number | null;
  predicted: number | null;
  factor: number | null;
  calibrated: boolean;
  mean_absolute_deviation: number | null;
}

export interface Cure {
  factor: string;
  share_outside: number;
  drifts: boolean;
  x: number[];
  cumulative: number[];
  bound: number[];
}

export interface Validation {
  available: boolean;
  passed: boolean;
  n_units: number;
  spatial: Calibration | null;
  random: Calibration | null;
  optimism: number | null;
  design_effect: number | null;
  cure: Cure[];
  refusal: string | null;
  notes: string[];
}

/** Rung 3's spline. Reference material — never a client number, by the brief. */
export interface Shape {
  factor: string;
  available: boolean;
  shape: string | null;
  turning_point: number | null;
  penalty_sensitive: boolean;
  curve: { x: number[]; y: number[]; lower: number[]; upper: number[] } | null;
}

export interface Assessment {
  mode: string;
  rung: string;
  banner: string;
  registry_version: string;
  context: {
    facility_type: string;
    region: string;
    severity: string;
    declared: boolean;
    crash_mix_is_default: boolean;
  };
  panel: {
    rows: number;
    units: number;
    periods: number;
    time_slots: number;
    total_crashes: number;
    zero_crash_rows: number;
    zero_crash_share: number;
    exposure_total: number;
  };
  checks: Check[];
  factors: {
    available: string[];
    missing: { name: string; missing_behaviour: string }[];
    constant: string[];
    dropped_for_collinearity: string[];
    in_model: string[];
  };
  fit: Fit | null;
  index: { specification: string; terms: IndexTerm[] } | null;
  ranking: Ranking | null;
  posterior: Posterior | null;
  spatial: { message: string; identified: boolean } | null;
  validation: Validation | null;
  reference: { shapes: Shape[] } | null;
  sign_guard: { contradictions: unknown[] } | null;
  receipts: {
    refusal: string | null;
    descent: string | null;
    index_refusal: string | null;
  };
  manifest: Record<string, unknown> & { panel_sha256?: string };
  log: { level: string; stage: string; event: string; message: string }[];
}

export interface ProvenanceRow {
  factor: string;
  column: string;
  adapter: string;
  tier: string;
  licence: string;
  coverage: number;
  confidence_high: number;
  confidence_low: number;
  contested_by: string;
  agreement: number | null;
  source: string;
}

export interface Obligation {
  licence: string;
  credit_required: boolean;
  share_alike_database: boolean;
  note: string;
  factors: string[];
  adapters: string[];
  credits: string[];
  recognised: boolean;
}

export interface Corridor {
  corridor: {
    name: string;
    length_m: number;
    length_km: number;
    epsg: number;
    self_intersecting: boolean;
    warnings: string[];
    geometry: [number, number][];
  };
  segmentation: {
    n_units: number;
    target_length_m: number;
    total_length_km: number;
    units: {
      unit_id: string;
      index: number;
      start_m: number;
      end_m: number;
      length_m: number;
      midpoint_m: number;
      geometry: [number, number][];
    }[];
  };
  snap: {
    n_supplied: number;
    n_snapped: number;
    n_dropped: number;
    snap_rate: number;
    dropped_reasons: Record<string, number>;
  } | null;
  provenance: ProvenanceRow[];
  contested: string[];
  attribution: {
    credit_required: boolean;
    share_alike_database: boolean;
    credit_lines: string[];
    database_warning: string | null;
    unrecognised: string[];
    obligations: Obligation[];
  };
  cache: { used: boolean; hits: number; misses: number; notes: string[] };
  warnings: string[];
}

/** What the page is handed: the engine's half, and the geography's half when there is one. */
export interface Run {
  assessment: Assessment;
  corridor: Corridor | null;
  generated_at?: string;
  engine_version?: string;
}
