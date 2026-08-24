/**
 * The JSON contract, as TypeScript.
 *
 * GENERATED FILE — do not edit by hand.
 *
 * Source of truth: `src/roadrisk/contract/` on the Python side.
 * Regenerate:      python tools/generate_types.py
 * Payload schema:  1.0
 *
 * These types describe the payload completely, not partially. The Python models they
 * come from forbid undeclared fields, so a key the engine emits and the contract has
 * not declared fails a test rather than arriving here unannounced.
 *
 * A field typed `T | null` is one the payload carries as null; a field marked `?` is
 * one the payload omits entirely. The distinction matters most in Mode B, where the
 * count-shaped fields are *absent* rather than null — a null is a hole a renderer fills
 * with a dash, which reads as "not available" rather than "this mode does not produce
 * one".
 */

/** What one adapter resolved and what it refused. */
export interface AdapterRun {
  name: string;
  resolved: string[];
  skipped: AdapterSkip[];
  notes: string[];
}

/**
 * A factor an adapter was asked for and declined to produce, and why.
 *
 * A missing tag is not a zero. Reading an absent `lit` tag as *unlit* would
 * manufacture a lighting effect out of mapper attention, pointing exactly the way the
 * registry expects it to.
 */
export interface AdapterSkip {
  factor: string;
  adapter: string;
  reason: string;
}

/**
 * Whether the Laplace approximation could be believed on this fit.
 *
 * Two gates, neither negotiable: Pareto k-hat at most 0.7 and at least 400 effective
 * draws. k-hat says the *shape* was right and says nothing about whether enough draws
 * survived to place an interval endpoint, so both are needed.
 */
export interface ApproximationReport {
  k_hat: number | null;
  effective_draws: number | null;
  trustworthy: boolean;
  message: string;
}

/**
 * One complete assessment, as it travels.
 *
 * Mode B is the floor, so a contract-valid panel always produces one of these — even
 * when nothing could be fitted and nothing could be scored. `fit` and `index` both
 * absent with a refusal receipt is a real, reportable outcome, not an error.
 */
export interface Assessment {
  mode: string;
  rung: string;
  banner: string;
  registry_version: string;
  context: RunContext;
  panel: PanelSummary;
  checks: Check[];
  factors: FactorSummary;
  fit: Fit | null;
  predictions: Prediction[] | null;
  index: Index | null;
  ranking: Ranking | null;
  sign_guard: SignGuard | null;
  reference: Reference;
  posterior: Posterior | null;
  posterior_data_only: Posterior | null;
  evidence: Evidence | null;
  validation: Validation | null;
  spatial: Spatial | null;
  receipts: Receipts;
  manifest: Manifest;
  log: LogRecord[];
}

/**
 * What the client owes the people whose data this used.
 *
 * `unrecognised` is not empty-by-default optimism — a licence this collector does not
 * know how to classify is listed rather than assumed permissive.
 */
export interface Attribution {
  credit_required: boolean;
  share_alike_database: boolean;
  credit_lines: string[];
  database_warning: string | null;
  unrecognised: string[];
  obligations: Obligation[];
}

/**
 * A contiguous run of segments that all rank in the worst band.
 *
 * A run never spans a chainage gap — where the corridor breaks, the blackspot breaks.
 */
export interface Blackspot {
  rank: number;
  unit_ids: string[];
  n_units: number;
  worst_unit: string;
  worst_rank: number;
  score: number;
  start_m?: number | null;
  end_m?: number | null;
  length_m?: number | null;
  observed?: number | null;
  expected?: number | null;
}

/** One source, and how old the answer served for it was. */
export interface CacheAge {
  source: string;
  age_days: number;
  fetched_on: string;
}

/**
 * What the cache served, and how stale it was.
 *
 * A cache must never make a run look fresher than it is. Every hit is counted, the age
 * of the oldest thing used goes into the run's warnings, and past a fortnight the note
 * stops being a date and becomes an instruction to clear the cache.
 */
export interface CacheReport {
  used: boolean;
  hits: number;
  misses: number;
  oldest_days: number;
  notes: string[];
  ages: CacheAge[];
}

/**
 * Held-out calibration under one fold scheme.
 *
 * The numbers are nullable because the engine will not invent one it could not
 * compute — a fold that produced no denominator has none.
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

/**
 * One validation gate, and what it saw.
 *
 * `threshold` and `observed` are **prose, not numbers** — "max VIF < 5" against
 * "max 1.3 (lit)". They are written for a reader, and a check whose threshold is a
 * sentence has no numeric form to offer. The hand-written page types had both as
 * `number | null`, which no run has ever produced.
 */
export interface Check {
  number: number;
  name: string;
  status: string;
  failure_type: string;
  threshold: string | null;
  observed: string | null;
  message: string;
}

/** One fitted term. Frequentist — this is the NB2 fit, p-value and all. */
export interface Coefficient {
  factor: string;
  estimate: number;
  std_error: number;
  z_value: number;
  p_value: number;
  ci_low: number;
  ci_high: number;
}

/** Something recorded against a published weight when it was derived. */
export interface Concern {
  code: string;
  message: string;
}

/**
 * One factor on one unit, with a one-word reason for its tier.
 *
 * `carried` is imputed from a neighbour · `contradicted` means a second source
 * materially disagrees here · `thin_coverage` rests on under half the unit ·
 * `inferred` was derived by us rather than stated by anyone · `measured` is measured.
 */
export interface ConfidenceRow {
  unit_id: string;
  factor: string;
  column: string;
  adapter: string;
  tier: string;
  value: number | null;
  confidence: string;
  reason: string;
}

/** Whether the chains mixed, when the ladder descended to MCMC. */
export interface ConvergenceReport {
  converged: boolean;
  max_r_hat: number | null;
  min_ess_bulk: number | null;
  acceptance: number | null;
  message: string;
}

/** The geography half of a run. */
export interface Corridor {
  corridor: CorridorGeometry;
  segmentation: Segmentation;
  panel: PanelShape;
  snap: SnapReport | null;
  adapters: AdapterRun[];
  provenance: ProvenanceRow[];
  confidence: ConfidenceRow[];
  contested: string[];
  disagreements: Disagreement[];
  attribution: Attribution;
  cache: CacheReport;
  fusion_notes: string[];
  warnings: string[];
}

/**
 * The stitched centreline, and what was wrong with it.
 *
 * `self_intersecting` is not cosmetic: a corridor that crosses itself cannot be
 * linearly referenced unambiguously, because one point on the ground has two
 * chainages.
 */
export interface CorridorGeometry {
  name: string;
  length_m: number;
  length_km: number;
  epsg: number;
  self_intersecting: boolean;
  warnings: string[];
  geometry: ([number, number])[];
}

/**
 * How total crashes divide by type, and where the split came from.
 *
 * The four shares partition total crashes and sum to one — the engine enforces that
 * on construction, so a payload that violates it never gets this far.
 */
export interface CrashMix {
  run_off_head_on: number;
  intersection: number;
  pedestrian: number;
  other: number;
  source: string;
}

/**
 * Cumulative residuals against one factor, with its band.
 *
 * Says *where* a factor is wrong, which no single number can. The band is widened by
 * the measured design effect — the textbook one assumes independent residuals, and on
 * this panel a badly fitted segment contributes a run of same-signed ones.
 */
export interface Cure {
  factor: string;
  share_outside: number;
  drifts: boolean;
  x: number[];
  cumulative: number[];
  bound: number[];
}

/**
 * Two sources that both measured a factor and did not match.
 *
 * Asymmetric evidence, and the confidence tier treats it that way: agreement is weak,
 * because open datasets copy from each other and agreement can be an echo.
 * Disagreement is strong evidence that one of the two is wrong, so it pulls the units
 * it names to low confidence, and nothing here can say which source is at fault.
 */
export interface Disagreement {
  factor: string;
  column: string;
  chosen: string;
  challenger: string;
  n_compared: number;
  n_agreeing: number;
  score: number | null;
  mean_absolute_difference: number | null;
  max_absolute_difference: number | null;
  correlation: number | null;
  disagreeing_units: string[];
  note: string;
}

/** Three answers per factor, and the one the engine designates. */
export interface Evidence {
  answer: string;
  reason: string;
  factors: EvidenceFactor[];
  notes: string[];
}

/**
 * Textbook, this corridor, and the two combined — for one factor.
 *
 * `prior_share` is the auditing device: the share of the mixed answer that came from
 * the literature rather than this road. 3% is your road talking; 78% is a textbook
 * with a corridor's name on it.
 */
export interface EvidenceFactor {
  factor: string;
  textbook: number | null;
  textbook_sd: number | null;
  textbook_source: string | null;
  data: EvidenceInterval | null;
  mix: EvidenceInterval | null;
  prior_share: number | null;
  prior_dominates: boolean;
  moved_by_others_se: number | null;
  indirectly_shifted: boolean;
  contradicts_textbook: boolean;
  label: string;
  verdict: string;
}

/** A mean with its interval, for one of the three answers. */
export interface EvidenceInterval {
  mean: number;
  low: number;
  high: number;
}

/** A correlated partner of a contradicting factor. */
export interface FactorCorrelation {
  partner: string;
  r: number;
}

/** Which factors survived to the specification, and which fell out where. */
export interface FactorSummary {
  available: string[];
  missing: MissingFactor[];
  constant: string[];
  dropped_for_collinearity: string[];
  in_model: string[];
}

/**
 * The Mode A fit.
 *
 * `cluster_widening` and `naive_std_errors` are keyed by factor name. They carry step
 * 3.1's whole point: how much too certain the independent-rows fit was, printed beside
 * what is true, because a correction nobody can see the size of is a correction nobody
 * believes.
 */
export interface Fit {
  specification: string;
  family: string;
  converged: boolean;
  n_observations: number;
  n_parameters: number;
  log_likelihood: number | null;
  aic: number | null;
  bic: number | null;
  alpha: number | null;
  pearson_dispersion: number | null;
  n_clusters: number | null;
  cluster_widening: Record<string, number>;
  naive_std_errors: Record<string, number>;
  panel_notes: string[];
  intercept: Coefficient | null;
  coefficients: Coefficient[];
}

/**
 * Mode B. Note what is absent: there is no count anywhere in this object.
 *
 * A weighted index of published effect sizes ranks segments against each other. It
 * cannot say how many crashes to expect, and the type gives it nowhere to say so.
 */
export interface Index {
  specification: string;
  n_units: number;
  n_observations: number;
  skipped_unsourced: string[];
  skipped_inadmissible: string[];
  crash_mix: CrashMix;
  bucket_mean_scores: Record<string, number>;
  terms: IndexTerm[];
  ranking: IndexRankingRow[];
}

/**
 * A unit's index score, decomposed by crash type.
 *
 * The per-bucket keys are fixed by the crash-type partition, not open-ended: a fifth
 * bucket would be a change to the engine's own enum and belongs here as a change too.
 */
export interface IndexRankingRow {
  unit_id: string;
  rank: number;
  percentile: number;
  score: number;
  score_run_off_head_on: number;
  score_intersection: number;
  score_pedestrian: number;
  score_other: number;
}

/** One weighted term in the Mode B index, with the citation behind it. */
export interface IndexTerm {
  factor: string;
  label: string;
  weight: number;
  weight_source: string;
  family: string;
  scope: string;
  mean_contribution: number;
  sd_contribution: number;
  concerns: Concern[];
  agreement: WeightAgreement | null;
}

/** How far the estimate moves when each unit is dropped in turn. */
export interface LeaveOneOut {
  n_units: number;
  n_refits: number;
  capped: boolean;
  estimate_min: number;
  estimate_max: number;
  n_sign_flips: number;
}

/**
 * One thing this assessment cannot tell you, and why.
 *
 * Assembled from what the run actually did — never written into the layout, so it
 * cannot go stale and cannot be quietly edited out. Removing it is a code change with
 * a failing test attached.
 */
export interface Limitation {
  code: string;
  severity: string;
  title: string;
  detail: string;
}

/** One event. Nothing is silent — every gate, descent and dropped term is here. */
export interface LogRecord {
  sequence: number;
  timestamp: string;
  level: string;
  stage: string;
  code: string;
  message: string;
  data: Record<string, unknown>;
}

/**
 * The reproducibility fingerprint. Two identical runs produce the same one.
 *
 * `settings` and `package_versions` are open maps by design — they record what the
 * run was given and what it ran against, and pinning either to a fixed set of keys
 * would mean a new option silently failing to be recorded.
 */
export interface Manifest {
  created_at: string;
  engine_version: string;
  fingerprint: string;
  panel_sha256: string;
  panel_shape: number[];
  registry_sha256: string;
  registry_version: string;
  python_version: string;
  platform: string;
  package_versions: Record<string, string>;
  settings: Record<string, unknown>;
}

/** A registry factor the panel did not carry, and what the registry does about it. */
export interface MissingFactor {
  name: string;
  missing_behaviour: string;
}

/**
 * What one licence requires of whoever received this report.
 *
 * `share_alike_database` is the one that changes with delivery: crediting a source in
 * a report is one obligation, redistributing a derived database is another, and they
 * are kept apart because only the second one is contagious.
 */
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

/** The contradicting factor refitted with one partner, to see if the sign returns. */
export interface PairwiseFit {
  partner: string;
  correlation: number;
  estimate: number;
  agrees_with_expected: boolean;
  differs_from_full_fit: boolean;
}

/** The panel the geometry produced, before the engine saw it. */
export interface PanelShape {
  rows: number;
  units: number;
  total_crashes: number;
  zero_crash_rows: number;
  factor_columns: string[];
}

/** The panel as counted, after the input contract accepted it. */
export interface PanelSummary {
  rows: number;
  units: number;
  periods: number;
  time_slots: number;
  total_crashes: number;
  zero_crash_rows: number;
  zero_crash_share: number;
  exposure_total: number;
}

/**
 * The Bayesian fit.
 *
 * **`coefficients` is a mapping keyed by factor name, not a list.** Typing it as an
 * array is not a harmless slip — a lookup returns nothing, every row falls back to its
 * frequentist interval, and the heading keeps saying *credible*. That shipped once and
 * survived three steps; it is the reason this package exists.
 *
 * Present and unconverged is a real outcome. It means no rung of the inference ladder
 * could be believed, and it must not be read as *we have credible intervals*.
 */
export interface Posterior {
  specification: string;
  method: string;
  converged: boolean;
  n_observations: number;
  n_units: number;
  n_nodes: number | null;
  hdi_probability: number;
  coefficients: Record<string, PosteriorSummary | null>;
  intercept: PosteriorSummary | null;
  sigma_u: PosteriorSummary | null;
  alpha: PosteriorSummary | null;
  approximation: ApproximationReport | null;
  convergence: ConvergenceReport | null;
  descent: string[];
  failure_reason: string | null;
  notes: string[];
}

/** One parameter's posterior. No p-value — there is nowhere to put one. */
export interface PosteriorSummary {
  mean: number;
  sd: number;
  hdi_low: number;
  hdi_high: number;
  prob_positive: number;
  r_hat: number | null;
  ess_bulk: number | null;
}

/**
 * One panel row: what happened, what the model expected, over what exposure.
 *
 * Per row, not per unit — the raw material the ranking is built from, and the one
 * thing in this payload that cannot be reconstructed from anything else in it.
 */
export interface Prediction {
  unit_id: string;
  period: string;
  time_slot: string;
  observed: number;
  expected: number;
  exposure: number;
}

/**
 * One factor's winning source, and how far it reaches.
 *
 * Tier and licence travel from the **registry**, not from the module that produced the
 * value: an adapter cannot promote itself to Tier A or invent a licence, because it
 * never gets to state either.
 */
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

/**
 * One ranked table, whichever mode produced it.
 *
 * `has_intervals` is how a consumer tells the two apart without inspecting rows:
 * Mode A ranks by predicted rate and carries an interval, Mode B ranks by index score
 * and carries neither count nor interval.
 */
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

/** Why a mode was refused, why the ladder descended, why the index would not score. */
export interface Receipts {
  refusal: string | null;
  descent: string | null;
  index_refusal: string | null;
}

/** Reference material. Under its own key so a consumer knows before it has to ask. */
export interface Reference {
  shapes: Shape[];
}

/**
 * Whether the shape survived resampling the corridor by unit.
 *
 * A turn that a majority of resampled corridors do not reproduce is refused as an
 * explanation. `shapes` counts what each resample found.
 */
export interface ResampleReport {
  drawn: number;
  fitted: number;
  agreeing: number;
  share: number;
  shapes: Record<string, number>;
}

/** What kind of corridor this is, which decides which published weights apply. */
export interface RunContext {
  facility_type: string;
  region: string;
  severity: string;
  declared: boolean;
  crash_mix: CrashMix;
  crash_mix_is_default: boolean;
  segment_length_km: number | null;
  reference_aadt: number | null;
}

/** One segmentation unit, with its chainage extent and its own geometry. */
export interface SegmentUnit {
  unit_id: string;
  index: number;
  start_m: number;
  end_m: number;
  length_m: number;
  midpoint_m: number;
  geometry: ([number, number])[];
}

/**
 * The units the corridor was cut into.
 *
 * Chainage is continuous and exhaustive: no gaps, no overlaps, and the unit lengths
 * sum to the corridor.
 */
export interface Segmentation {
  n_units: number;
  target_length_m: number;
  total_length_km: number;
  units: SegmentUnit[];
}

/**
 * Rung 3's spline diagnostic.
 *
 * **It ships no number.** There is no coefficient here, no p-value, no predicted
 * count and no interval — by type, not by convention. The brief files rung 3 as
 * reference only, and a test enumerates the forbidden names.
 *
 * `penalty_shapes` pairs each smoothing penalty with the shape it found, because the
 * first version of this module chose one penalty by AIC and drew a bend on a panel
 * whose effect was planted linear. The headline is now the shape the grid agrees on
 * and every penalty's answer is reported either way.
 */
export interface Shape {
  factor: string;
  available: boolean;
  shape: string | null;
  turning_point: number | null;
  penalty: number | null;
  edf: number | null;
  penalty_shapes: ([number, string])[];
  penalty_sensitive: boolean;
  n_units: number;
  n_observations: number;
  curve: SplineCurve | null;
  resamples: ResampleReport | null;
  linear_estimate: number | null;
  expected_sign: string | null;
  explains_contradiction: boolean;
  verdict: string;
  refusal: string | null;
  notes: string[];
}

/** Every coefficient checked against its declared direction. */
export interface SignGuard {
  clean: boolean;
  n_contradictions: number;
  findings: SignGuardFinding[];
}

/** One factor's fitted sign against the sign the registry expected of it. */
export interface SignGuardFinding {
  factor: string;
  expected_sign: string;
  estimate: number;
  p_value: number;
  contradicts: boolean;
  significant: boolean;
  verdict: string;
  univariate_estimate: number | null;
  correlations: FactorCorrelation[];
  pairwise: PairwiseFit[];
  leave_one_out: LeaveOneOut | null;
  shape: Shape | null;
}

/**
 * Where the supplied crashes went.
 *
 * Every drop is counted with a reason. This is what activates gate check 6 — a
 * corridor most of whose crashes did not land on it is not a corridor this tool can
 * speak about.
 */
export interface SnapReport {
  n_supplied: number;
  n_snapped: number;
  n_dropped: number;
  snap_rate: number;
  dropped_reasons: Record<string, number>;
}

/**
 * The Leroux CAR field, and whether this corridor could identify it.
 *
 * `identified` false is an answer about the corridor, not a failure: below about
 * eighty units the spatial and independent parts explain the same variance and there
 * is not enough road to separate them.
 */
export interface Spatial {
  rho: number;
  rho_low: number;
  rho_high: number;
  identified: boolean;
  spatial: boolean;
  message: string;
}

/** The fitted spline and its band, as parallel arrays. */
export interface SplineCurve {
  x: number[];
  y: number[];
  lower: number[];
  upper: number[];
}

/**
 * One ranked segment.
 *
 * The count-shaped fields are **absent** in Mode B rather than null. That is 4.2's
 * deliberate choice: `"expected": null` is a count-shaped hole that a renderer fills
 * with a dash, which reads as *not available* when the truth is *this mode does not
 * produce one*.
 */
export interface UnitRisk {
  unit_id: string;
  rank: number;
  percentile: number;
  score: number;
  observed?: number | null;
  expected?: number | null;
  expected_low?: number | null;
  expected_high?: number | null;
  exposure?: number | null;
  rate?: number | null;
  components?: Record<string, number> | null;
}

/**
 * Out-of-sample validation. Runs on every Mode A assessment.
 *
 * There is no flag that turns it on and none that turns it off: a model failing its
 * own validation is a finding the report carries, not a computation a caller may
 * decline.
 */
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

/**
 * What two sources pricing the same factor said, side by side.
 *
 * Never averaged. The HSM prices grade at +0.12 and iRAP at +0.49; they are answering
 * slightly different questions and both numbers are reported.
 */
export interface WeightAgreement {
  score: number | null;
  comparable: boolean;
  families: string[];
  values: number[];
  signs_conflict: boolean;
  note: string;
}

/**
 * A complete run: the engine's half, the geography's half when there is one.
 *
 * `corridor` is absent for a panel assessed directly. That is not a degraded run — the
 * engine's whole shape is that it judges a panel, and where the panel came from is a
 * separate question.
 */
export interface Run {
  assessment: Assessment;
  corridor: Corridor | null;
  limitations: Limitation[];
  generated_at: string;
  engine_version: string;
  schema_version?: string | null;
}
