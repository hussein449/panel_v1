"""The engine half of the payload — `Assessment.as_dict()`, as types.

Every model here mirrors one object the engine serialises. The mirroring is deliberate
duplication: `as_dict()` decides what travels, this decides what is *allowed* to travel,
and the conformance test in `tests/test_contract.py` fails when they disagree.

**Enum-valued fields are typed `str`, not as literal unions.** `mode`, `rung`, `family`,
`status` and their neighbours all carry an enum's `.value`, and a union type would be a
better description of today. It would also mean a run stored under one engine version
stops validating under the next one that adds a rung — which is exactly the property
5.1b needs not to have, because a stored run must re-render without a refit. The strings
are documented where they are narrow; they are not enforced.
"""

from __future__ import annotations

from typing import Any

from roadrisk.contract.base import Payload


class CrashMix(Payload):
    """How total crashes divide by type, and where the split came from.

    The four shares partition total crashes and sum to one — the engine enforces that
    on construction, so a payload that violates it never gets this far.
    """

    run_off_head_on: float
    intersection: float
    pedestrian: float
    other: float
    source: str


class RunContext(Payload):
    """What kind of corridor this is, which decides which published weights apply."""

    facility_type: str
    region: str
    severity: str
    declared: bool
    crash_mix: CrashMix
    crash_mix_is_default: bool
    #: True when the split was measured on a different kind of road than this one — a
    #: rural two-lane distribution standing in for a motorway, say.
    crash_mix_facility_mismatch: bool
    segment_length_km: float | None
    reference_aadt: float | None


class PanelSummary(Payload):
    """The panel as counted, after the input contract accepted it."""

    rows: int
    units: int
    periods: int
    time_slots: int
    total_crashes: int
    zero_crash_rows: int
    zero_crash_share: float
    exposure_total: float


class Check(Payload):
    """One validation gate, and what it saw.

    `threshold` and `observed` are **prose, not numbers** — "max VIF < 5" against
    "max 1.3 (lit)". They are written for a reader, and a check whose threshold is a
    sentence has no numeric form to offer. The hand-written page types had both as
    `number | null`, which no run has ever produced.
    """

    number: int
    name: str
    status: str
    failure_type: str
    threshold: str | None
    observed: str | None
    message: str


class MissingFactor(Payload):
    """A registry factor the panel did not carry, and what the registry does about it."""

    name: str
    missing_behaviour: str


class FactorSummary(Payload):
    """Which factors survived to the specification, and which fell out where."""

    available: list[str]
    missing: list[MissingFactor]
    constant: list[str]
    dropped_for_collinearity: list[str]
    #: Factors sent to the back of the keep order because they hold one value across
    #: most of this corridor. Demoted, not removed — they still fit if the rung has room.
    demoted_for_no_variation: list[str]
    in_model: list[str]


class Coefficient(Payload):
    """One fitted term. Frequentist — this is the NB2 fit, p-value and all."""

    factor: str
    estimate: float
    std_error: float
    z_value: float
    p_value: float
    ci_low: float
    ci_high: float


class Fit(Payload):
    """The Mode A fit.

    `cluster_widening` and `naive_std_errors` are keyed by factor name. They carry step
    3.1's whole point: how much too certain the independent-rows fit was, printed beside
    what is true, because a correction nobody can see the size of is a correction nobody
    believes.
    """

    specification: str
    family: str
    converged: bool
    n_observations: int
    n_parameters: int
    log_likelihood: float | None
    aic: float | None
    bic: float | None
    alpha: float | None
    pearson_dispersion: float | None
    n_clusters: int | None
    cluster_widening: dict[str, float]
    naive_std_errors: dict[str, float]
    panel_notes: list[str]
    intercept: Coefficient | None
    coefficients: list[Coefficient]


class Prediction(Payload):
    """One panel row: what happened, what the model expected, over what exposure.

    Per row, not per unit — the raw material the ranking is built from, and the one
    thing in this payload that cannot be reconstructed from anything else in it.
    """

    unit_id: str
    period: str
    time_slot: str
    observed: int
    expected: float
    exposure: float


class Concern(Payload):
    """Something recorded against a published weight when it was derived."""

    code: str
    message: str


class WeightAgreement(Payload):
    """What two sources pricing the same factor said, side by side.

    Never averaged. The HSM prices grade at +0.12 and iRAP at +0.49; they are answering
    slightly different questions and both numbers are reported.
    """

    score: float | None
    comparable: bool
    families: list[str]
    values: list[float]
    signs_conflict: bool
    note: str


class IndexTerm(Payload):
    """One weighted term in the Mode B index, with the citation behind it."""

    factor: str
    label: str
    weight: float
    weight_source: str
    family: str
    scope: str
    mean_contribution: float
    sd_contribution: float
    concerns: list[Concern]
    agreement: WeightAgreement | None


class IndexRankingRow(Payload):
    """A unit's index score, decomposed by crash type.

    The per-bucket keys are fixed by the crash-type partition, not open-ended: a fifth
    bucket would be a change to the engine's own enum and belongs here as a change too.
    """

    unit_id: str
    rank: int
    percentile: float
    score: float
    score_run_off_head_on: float
    score_intersection: float
    score_pedestrian: float
    score_other: float


class Index(Payload):
    """Mode B. Note what is absent: there is no count anywhere in this object.

    A weighted index of published effect sizes ranks segments against each other. It
    cannot say how many crashes to expect, and the type gives it nowhere to say so.
    """

    specification: str
    n_units: int
    n_observations: int
    skipped_unsourced: list[str]
    skipped_inadmissible: list[str]
    crash_mix: CrashMix
    bucket_mean_scores: dict[str, float]
    terms: list[IndexTerm]
    ranking: list[IndexRankingRow]


class UnitRisk(Payload):
    """One ranked segment.

    The count-shaped fields are **absent** in Mode B rather than null. That is 4.2's
    deliberate choice: `"expected": null` is a count-shaped hole that a renderer fills
    with a dash, which reads as *not available* when the truth is *this mode does not
    produce one*.
    """

    unit_id: str
    rank: int
    percentile: float
    score: float
    observed: int | None = None
    expected: float | None = None
    expected_low: float | None = None
    expected_high: float | None = None
    exposure: float | None = None
    rate: float | None = None
    components: dict[str, float] | None = None


class Blackspot(Payload):
    """A contiguous run of segments that all rank in the worst band.

    A run never spans a chainage gap — where the corridor breaks, the blackspot breaks.
    """

    rank: int
    unit_ids: list[str]
    n_units: int
    worst_unit: str
    worst_rank: int
    score: float
    start_m: float | None = None
    end_m: float | None = None
    length_m: float | None = None
    observed: int | None = None
    expected: float | None = None


class Ranking(Payload):
    """One ranked table, whichever mode produced it.

    `has_intervals` is how a consumer tells the two apart without inspecting rows:
    Mode A ranks by predicted rate and carries an interval, Mode B ranks by index score
    and carries neither count nor interval.
    """

    mode: str
    basis: str
    threshold_percentile: float
    has_intervals: bool
    n_units: int
    units: list[UnitRisk]
    blackspots: list[Blackspot]
    notes: list[str]


class SplineCurve(Payload):
    """The fitted spline and its band, as parallel arrays."""

    x: list[float]
    y: list[float]
    lower: list[float]
    upper: list[float]


class ResampleReport(Payload):
    """Whether the shape survived resampling the corridor by unit.

    A turn that a majority of resampled corridors do not reproduce is refused as an
    explanation. `shapes` counts what each resample found.
    """

    drawn: int
    fitted: int
    agreeing: int
    share: float
    shapes: dict[str, int]


class Shape(Payload):
    """Rung 3's spline diagnostic.

    **It ships no number.** There is no coefficient here, no p-value, no predicted
    count and no interval — by type, not by convention. The brief files rung 3 as
    reference only, and a test enumerates the forbidden names.

    `penalty_shapes` pairs each smoothing penalty with the shape it found, because the
    first version of this module chose one penalty by AIC and drew a bend on a panel
    whose effect was planted linear. The headline is now the shape the grid agrees on
    and every penalty's answer is reported either way.
    """

    factor: str
    available: bool
    shape: str | None
    turning_point: float | None
    penalty: float | None
    edf: float | None
    penalty_shapes: list[tuple[float, str]]
    penalty_sensitive: bool
    n_units: int
    n_observations: int
    curve: SplineCurve | None
    resamples: ResampleReport | None
    linear_estimate: float | None
    expected_sign: str | None
    explains_contradiction: bool
    verdict: str
    refusal: str | None
    notes: list[str]


class Reference(Payload):
    """Reference material. Under its own key so a consumer knows before it has to ask."""

    shapes: list[Shape]


class FactorCorrelation(Payload):
    """A correlated partner of a contradicting factor."""

    partner: str
    r: float


class PairwiseFit(Payload):
    """The contradicting factor refitted with one partner, to see if the sign returns."""

    partner: str
    correlation: float
    estimate: float
    agrees_with_expected: bool
    differs_from_full_fit: bool


class LeaveOneOut(Payload):
    """How far the estimate moves when each unit is dropped in turn."""

    n_units: int
    n_refits: int
    capped: bool
    estimate_min: float
    estimate_max: float
    n_sign_flips: int


class SignGuardFinding(Payload):
    """One factor's fitted sign against the sign the registry expected of it."""

    factor: str
    expected_sign: str
    estimate: float
    p_value: float
    contradicts: bool
    #: The one correlated factor that puts the sign back, when a single one does. A
    #: named suppressor is a mechanism; a contradiction without one is still open.
    suppressed_by: str | None
    suppressed: bool
    significant: bool
    verdict: str
    univariate_estimate: float | None
    correlations: list[FactorCorrelation]
    pairwise: list[PairwiseFit]
    leave_one_out: LeaveOneOut | None
    shape: Shape | None


class SignGuard(Payload):
    """Every coefficient checked against its declared direction."""

    clean: bool
    n_contradictions: int
    findings: list[SignGuardFinding]


class PosteriorSummary(Payload):
    """One parameter's posterior. No p-value — there is nowhere to put one."""

    mean: float
    sd: float
    hdi_low: float
    hdi_high: float
    prob_positive: float
    r_hat: float | None
    ess_bulk: float | None


class ApproximationReport(Payload):
    """Whether the Laplace approximation could be believed on this fit.

    Two gates, neither negotiable: Pareto k-hat at most 0.7 and at least 400 effective
    draws. k-hat says the *shape* was right and says nothing about whether enough draws
    survived to place an interval endpoint, so both are needed.
    """

    k_hat: float | None
    effective_draws: float | None
    trustworthy: bool
    message: str


class ConvergenceReport(Payload):
    """Whether the chains mixed, when the ladder descended to MCMC."""

    converged: bool
    max_r_hat: float | None
    min_ess_bulk: float | None
    acceptance: float | None
    message: str


class Posterior(Payload):
    """The Bayesian fit.

    **`coefficients` is a mapping keyed by factor name, not a list.** Typing it as an
    array is not a harmless slip — a lookup returns nothing, every row falls back to its
    frequentist interval, and the heading keeps saying *credible*. That shipped once and
    survived three steps; it is the reason this package exists.

    Present and unconverged is a real outcome. It means no rung of the inference ladder
    could be believed, and it must not be read as *we have credible intervals*.
    """

    specification: str
    method: str
    converged: bool
    n_observations: int
    n_units: int
    n_nodes: int | None
    hdi_probability: float
    coefficients: dict[str, PosteriorSummary | None]
    intercept: PosteriorSummary | None
    sigma_u: PosteriorSummary | None
    alpha: PosteriorSummary | None
    approximation: ApproximationReport | None
    convergence: ConvergenceReport | None
    descent: list[str]
    failure_reason: str | None
    notes: list[str]


class EvidenceInterval(Payload):
    """A mean with its interval, for one of the three answers."""

    mean: float
    low: float
    high: float


class EvidenceFactor(Payload):
    """Textbook, this corridor, and the two combined — for one factor.

    `prior_share` is the auditing device: the share of the mixed answer that came from
    the literature rather than this road. 3% is your road talking; 78% is a textbook
    with a corridor's name on it.
    """

    factor: str
    textbook: float | None
    textbook_sd: float | None
    textbook_source: str | None
    data: EvidenceInterval | None
    mix: EvidenceInterval | None
    prior_share: float | None
    prior_dominates: bool
    moved_by_others_se: float | None
    indirectly_shifted: bool
    contradicts_textbook: bool
    label: str
    verdict: str


class Evidence(Payload):
    """Three answers per factor, and the one the engine designates."""

    answer: str
    reason: str
    factors: list[EvidenceFactor]
    notes: list[str]


class Calibration(Payload):
    """Held-out calibration under one fold scheme.

    The numbers are nullable because the engine will not invent one it could not
    compute — a fold that produced no denominator has none.
    """

    scheme: str
    n_folds: int
    observed: float | None
    predicted: float | None
    factor: float | None
    calibrated: bool
    mean_absolute_deviation: float | None


class Cure(Payload):
    """Cumulative residuals against one factor, with its band.

    Says *where* a factor is wrong, which no single number can. The band is widened by
    the measured design effect — the textbook one assumes independent residuals, and on
    this panel a badly fitted segment contributes a run of same-signed ones.
    """

    factor: str
    #: Median over the orderings this factor's tied values permit — see
    #: :func:`roadrisk.core.validation._cure_for` for why a tied factor has more than one.
    share_outside: float
    #: 5th and 95th percentile of that sample; equal to ``share_outside`` when untied.
    share_outside_low: float
    share_outside_high: float
    drifts: bool
    x: list[float]
    cumulative: list[float]
    bound: list[float]


class Validation(Payload):
    """Out-of-sample validation. Runs on every Mode A assessment.

    There is no flag that turns it on and none that turns it off: a model failing its
    own validation is a finding the report carries, not a computation a caller may
    decline.
    """

    available: bool
    passed: bool
    n_units: int
    spatial: Calibration | None
    random: Calibration | None
    optimism: float | None
    design_effect: float | None
    cure: list[Cure]
    refusal: str | None
    notes: list[str]


class Spatial(Payload):
    """The Leroux CAR field, and whether this corridor could identify it.

    `identified` false is an answer about the corridor, not a failure: below about
    eighty units the spatial and independent parts explain the same variance and there
    is not enough road to separate them.
    """

    rho: float
    rho_low: float
    rho_high: float
    identified: bool
    spatial: bool
    message: str


class Receipts(Payload):
    """Why a mode was refused, why the ladder descended, why the index would not score."""

    refusal: str | None
    descent: str | None
    index_refusal: str | None


class Manifest(Payload):
    """The reproducibility fingerprint. Two identical runs produce the same one.

    `settings` and `package_versions` are open maps by design — they record what the
    run was given and what it ran against, and pinning either to a fixed set of keys
    would mean a new option silently failing to be recorded.
    """

    created_at: str
    engine_version: str
    fingerprint: str
    panel_sha256: str
    panel_shape: list[int]
    registry_sha256: str
    registry_version: str
    python_version: str
    platform: str
    package_versions: dict[str, str]
    settings: dict[str, Any]


class LogRecord(Payload):
    """One event. Nothing is silent — every gate, descent and dropped term is here."""

    sequence: int
    timestamp: str
    level: str
    stage: str
    code: str
    message: str
    data: dict[str, Any]


class Assessment(Payload):
    """One complete assessment, as it travels.

    Mode B is the floor, so a contract-valid panel always produces one of these — even
    when nothing could be fitted and nothing could be scored. `fit` and `index` both
    absent with a refusal receipt is a real, reportable outcome, not an error.
    """

    mode: str
    rung: str
    banner: str
    registry_version: str
    context: RunContext
    panel: PanelSummary
    checks: list[Check]
    factors: FactorSummary
    fit: Fit | None
    predictions: list[Prediction] | None
    index: Index | None
    ranking: Ranking | None
    sign_guard: SignGuard | None
    reference: Reference
    posterior: Posterior | None
    posterior_data_only: Posterior | None
    evidence: Evidence | None
    validation: Validation | None
    spatial: Spatial | None
    receipts: Receipts
    manifest: Manifest
    log: list[LogRecord]
