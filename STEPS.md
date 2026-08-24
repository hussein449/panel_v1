# Build Steps

The full build, broken into ordered steps. Each step has one deliverable and one way to
know it is done. Status is tracked here; what was actually built is logged in
[`IMPLEMENTED.md`](IMPLEMENTED.md).

**Status key** — `[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked

**Sequencing rule, from the brief:** make the model defensible on two corridors → make it
modular → then sell it. Stage 1 and Stage 3 are the credibility path. Stage 5 is not.

**Where the build is, 2026-08-24.** Stages 0, 1, 2, 3 and 4 are complete: two coordinates
in, a printed and sourced report out, with every number traceable and a limitations page
nothing can remove. **Stage 5 has started**, at 5.0 — the layering rule made a test,
written before the packages that could break it. The one thing no part of Stage 5
addresses is the critical path: this is still validated on two corridors with synthetic
crashes, and one real police extract is worth more than any of what follows.

---

## Stage 0 — Foundations

| | Step | Deliverable | Done when |
|---|---|---|---|
| `[x]` | **0.1** Repo skeleton | Package layout, `pyproject.toml`, gitignore, README | `pip install -e .` works |
| `[x]` | **0.2** Factor registry schema | Pydantic models for `Factor` / `Registry`, YAML loader | A malformed registry fails loudly with the field named |
| `[x]` | **0.3** Input contract + transforms | Required columns, typing, exposure derivation, `ln`/`ln1p`/`identity`/`zscore` | A panel missing a required column is rejected with the column named |

---

## Stage 1 — Engine core *(no geospatial, no web)*

This is the part that has to be right. It is pure Python over a dataframe.

| | Step | Deliverable | Done when |
|---|---|---|---|
| `[x]` | **1.1** Diagnostics | VIF, correlation matrix, variance-to-mean dispersion | VIF matches statsmodels on a known design |
| `[x]` | **1.2** Validation gates | The 9 checks from Part Seven-B, each returning HARD / SOFT / INFO | A crash-only panel (no zero rows) is refused |
| `[x]` | **1.3** Mode ladder | `A-full → A-reduced → A-minimal → B` descent, drops by registry priority | Every descent names the failed check and the dropped term |
| `[x]` | **1.4** Mode B index | Crash-type-decomposed weighted index from cited weights, ranked score, no counts | Refuses to score on an unsourced weight; a total-only registry scores identically to a flat sum |
| `[x]` | **1.5** Mode A rungs 0–1 | Poisson GLM (reference) + NB2 GLM (shipped), `ln(exposure)` offset | Coefficients, CIs and p-values on a synthetic panel |
| `[x]` | **1.6** Sign guard | Compare fitted signs to `expected_sign`, auto-run diagnostics on contradiction | A planted reversal is flagged, not reported quietly |
| `[x]` | **1.7** Run log + manifest | Append-only event log, reproducibility manifest with hashes | Two identical runs produce the same manifest hash |
| `[x]` | **1.8** Engine orchestrator | `validate → gate → select → fit/score → guard` in one entry point | One call returns a complete, serialisable assessment |
| `[x]` | **1.9** CLI | Mode banner, refusal receipt, descent receipt | `roadrisk assess` prints the receipts from the brief |

---

## Stage 2 — Geospatial pipeline

Turns two coordinates into the panel that Stage 1 consumes. Steps 1–6 of the pipeline brief.

**Re-ordered deliberately.** PostGIS was 2.1; it is now 2.9. A 100 km corridor fits in
memory comfortably, and persistence is a Stage 5 concern. Doing the geometry in memory
first got the pipeline to the engine in one pass instead of behind a migration.

Everything below runs with **no network and no API key**. That is not a limitation
being worked around — it is the shape of the product.

| | Step | Deliverable | Done when |
|---|---|---|---|
| `[x]` | **2.2a** Corridor + linear reference | `Corridor.from_latlon`, UTM projection, chainage, structural gates | A corridor that cannot be linearly referenced is rejected, not silently used |
| `[x]` | **2.2b** Resolve a corridor from OSM | Fetch by road `ref`, stitch, bridge gaps, detect divided roads, trim to start/end | Refuses a fragmented collection; never welds opposing carriageways |
| `[x]` | **2.3** Segmentation | Fixed-length units, chainage continuous and exhaustive, trailing runt merged | No gaps, no overlaps, unit lengths sum to the corridor |
| `[x]` | **2.4** Panel skeleton | `unit_id × period × time_slot`, `n_crashes` initialised to 0 | Zero rows exist by construction; skeleton passes the input contract |
| `[x]` | **2.5** Crash snapping | Project to centreline within tolerance, chainage → unit, period → cell | Every drop counted with a reason; `SnapReport` activates gate check 6 |
| `[x]` | **2.6** Tier A adapters | 12 factors behind one adapter contract, from three sources: centreline geometry, one OSM call, two COG rasters | Each returns value + source + tier + licence |
| `[x]` | **2.7** Fusion + agreement | Registry chain decides the winner; agreement scored where two sources overlap; client data enters as the first link | Confidence tier emitted per factor per unit |
| `[x]` | **2.8** Tier B adapters | Both named deliverables done and validated live: graph-centrality traffic proxy with a window-artefact gate, Mapillary detections. `mapillary_vision` and `dem_viewshed` are further Tier B factors, listed below rather than in this step | Never labelled `aadt` — asserted by test |
| `[~]` | **2.9** PostGIS + geographic cache | Cache **done** and validated live — a second corridor in the same region costs 1.2 s against 55.5 s. PostGIS persistence deliberately deferred, see below | Second corridor in the same country hits cache ✅ |

**Try it:**

```bash
roadrisk corridor --demo --facility-type rural_two_lane --region middle_east --severity injury
```

Add `--osm` for the road's own tags and its conflict-point densities, and `--rasters`
for gradient and roadside land use. Without either flag the pipeline never touches the
network.

**Validated on two real roads.** Cyprus B9 through the Troodos, 2026-08-10: 69 OSM
fragments → one 25.01 km centreline → 50 units → 1,200 panel rows → 99.8% snap rate →
Mode A. Dutch N201, 2026-08-17: 810 vertices → 33.50 km → 67 units → 1,608 rows → 84.3%
snap → Mode A, 11 of 13 factors resolved. Flat country after a mountain road, and the
pipeline needed no change for it. Details, and the defects each exposed, in
[`IMPLEMENTED.md`](IMPLEMENTED.md).

```bash
python tools/validate_corridor.py --list
```

### 2.9 — the cache, and why PostGIS is not in it yet

```bash
roadrisk corridor --ref B9 --bbox 34.80,32.80,35.05,33.05 --osm --traffic --cache .cache
```

Measured live on two real Cyprus roads into a fresh cache:

| | Time | |
|---|---|---|
| B9, cold cache | **55.5 s** | the first corridor pays |
| E601 — a *different* road, same region | **1.2 s** | cache hit |
| B9 again | **1.1 s** | cache hit |

**The rounding lives in the adapter, not the cache.** The strategic-network query is
built from a half-degree grid cell rather than from the corridor's own bounding box, so
two roads through the same county produce a byte-identical query and share an entry
without the cache having to be clever. An earlier version rewrote the bounding box
inside the query text as it passed through the cache; that worked, and it meant a cached
run fetched a different region from an uncached one — a cache that changes the answer is
not a cache.

**The half-degree grid is a measured choice, and it has a cost.** At a tenth of a degree
the second corridor missed entirely: B9 and E601 are a few kilometres apart and their
padded boxes still differed by more than one cell. Half a degree shares, and the price is
that the first corridor fetches a 1° × 1° region instead of a snug one — 55.5 s against
the 11.8 s a tight box took. That is the trade the brief asks for: *"a second corridor in
the same country is nearly free"* is a claim about the second corridor, not the first.

**A cache must never make a run look fresher than it is.** Every entry records when it
was fetched, every hit is counted, and the age of the oldest thing used goes into the
run's warnings. Past a fortnight the note stops being a date and starts being an
instruction to clear the cache. Expiry is per source, because OpenStreetMap changes daily
and Mapillary changes when somebody drives past with a camera.

**PostGIS is deliberately not built.** The other half of this step is persistence, and
the step's own note already says why it moved here from 2.1: *persistence is a Stage 5
concern*. Nothing in the pipeline needs a database today — a corridor fits in memory, the
CLI is single-user, and there is no multi-tenant story until 5.4. Building a schema and a
migration now would be guessing at what the web layer wants, and it would add a service
dependency to a package whose whole shape is "runs with no network and no API key".
It lands with 5.1, against real API requirements.

### 2.8 — the traffic proxy, and the gate that stops it lying

```bash
roadrisk corridor centreline.csv --crashes crashes.csv --osm --traffic
```

Betweenness centrality over the surrounding strategic network: the estimated share of
all shortest paths that use each unit. **Never AADT** — the column is `traffic_proxy`,
the notes say so in capitals, and the factor stays uncited because the HSM's AADT
exponent is estimated on measured volumes and does not transfer to a unitless score.

**The window is the trap.** Betweenness is computed over the graph you supply, so a
ribbon-shaped graph produces a parabola peaking in the middle of the ribbon — an
artefact of the query, indistinguishable at a glance from a town on the corridor. Two
defences: fetch a *region* rather than a ribbon (this is the one OSM fetch in the
package that uses a bounding box, deliberately), then test the finished proxy against a
symmetric parabola anyway and withhold it above 0.9.

Measured on Cyprus B9:

| Margin | Junctions | Artefact correlation | Peak unit (of 49) |
|---|---|---|---|
| 5 km | 114 | 0.38 | 1 |
| 10 km | 277 | 0.69 | 26 |
| 20 km | 592 | 0.41 | 19 |

Read honestly: **the along-corridor pattern is not stable under a change of window.**
An arbitrary analysis choice moves both the shape and where it peaks. That is the most
useful thing the adapter can say about its own output, and the reason `traffic_proxy`
stays uncited.

**Mapillary detections** are built and validated end to end on the Dutch N200: a median
of 93 rigid roadside objects per km, varying 0 to 142 between units, at `medium`
confidence throughout.

```bash
python tools/validate_mapillary.py amsterdam   # needs a token with the read scope
```

Getting there took five defects, each hiding the next — three in the plumbing (the
corridor box is too large for the endpoint, my error handling reported the wrong cause,
and a token without the `read` scope returns `200 {"data":[]}` indistinguishably from a
road with no imagery) and **two in the factor's own definition**: signage was 54% of the
count and is not a struck-object hazard, and the 50 m radius was measuring the
neighbourhood rather than the verge. Details in
[`IMPLEMENTED.md`](IMPLEMENTED.md).

Do not validate on B9 — it has no street-level imagery at all, so it exercises the
refusal and nothing else, and cannot tell a corridor with no poles from a bug that drops
every pole.

**Two Tier B factors from the brief are still unbuilt**, and neither belongs to this
step's deliverable:

- **`mapillary_vision`** — our own inference on sampled frames, feeding
  `roadside_hazard_score` and a `surface_paved` cross-check. This is the main cost trap
  in the pipeline at 50-150 USD of VLM calls per corridor, and it is also the one that
  needs the poles-to-RHR mapping study before its output means anything.
- **`dem_viewshed`** — `sight_distance_proxy` by marching the line of sight along the
  alignment against terrain. Cheap to attempt now that the elevation sampler from 2.6
  exists; crude by nature, since a DEM sees terrain but not vegetation, walls or parked
  vehicles.

`roadside_hazard_score` is **deliberately not derived** from those detections even
though the registry declares the adapter against it. Its units are the HSM roadside
hazard rating, 1 to 7, and mapping poles-per-km onto that scale needs a study — putting
a guess behind a cited weight is the worst thing this package could do.

### 2.7 — done

```bash
roadrisk corridor centreline.csv --crashes crashes.csv --osm --client inventory.csv
```

**Priority is the registry's, not the code's.** `factor.adapters` is an ordered chain,
and the winner is the earliest declared adapter that produced a value. Client data wins
because it is declared first — there is no branch anywhere that says so. Reordering the
YAML reorders the outcome.

**Client data is authoritative, not infallible.** Supplying an inventory does not
silently overwrite OSM: it wins, and where the two disagree the run names the units.

```
⚠  Sources disagree — speed_limit
   'client_speed_survey' won on registry priority; 'osm_maxspeed' disagrees.
   Compared on 16 unit(s) both measured, agreeing on 13 (81%).
   Units that differ: …-0006, …-0007, …-0008
   One of the two sources is wrong about them, and nothing here can say which.
```

**Agreement is asymmetric evidence, and the confidence tier treats it that way.** Two
sources matching is weak evidence — open datasets copy from each other, so agreement can
be an echo. Two sources differing is strong evidence that one of them is wrong. So
disagreement pulls a unit to low confidence; agreement is reported but never promotes
one.

**A confidence tier per factor per unit**, with a one-word reason:

| Tier | Reason | Meaning |
|---|---|---|
| `low` | `carried` | imputed from a neighbouring unit, not measured here |
| `low` | `contradicted` | a second source materially disagrees about this unit |
| `medium` | `thin_coverage` | rests on under half the unit's length |
| `medium` | `inferred` | derived by us rather than stated by anyone (Tier B) |
| `high` | `measured` | measured for this unit by the winning source |

Carried units are excluded from the agreement comparison — comparing an imputation
measures the imputation, not the sources.

### 2.6 — done

```bash
roadrisk corridor centreline.csv --crashes crashes.csv --osm --rasters
```

The adapter contract is the deliverable, not the twelve columns. A module names the
registry slot it fills — `osm_maxspeed`, `copernicus_dem_glo30` — and the tier and
licence travel from *that declaration* onto every value it produces. An adapter cannot
promote itself to Tier A or invent a licence, because it never gets to state either.

| Source | Cost | Factors |
|---|---|---|
| Centreline geometry | arithmetic | `curve_radius_min`, `curve_density` |
| OSM, one Overpass call | one request | `speed_limit`, `lanes`, `lit`, `surface_paved`, `sidewalk_present`, `median_present`, `junction_density`, `access_density`, `ramp_density`, `poi_density`, `building_density` |
| Copernicus DEM, ESA WorldCover | COG windows | `grade_pct`, `landuse_urban` |

The OSM query is bounded by the corridor rather than by its bounding box. The rasters
are read as windows over HTTPS range requests, never as whole tiles, and are the only
part that needs GDAL — hence a separate extra:

```bash
pip install "roadrisk-panel[raster]"
```

**Missing tags are not zeros.** A factor needs half the corridor tagged; an untagged unit
takes its neighbour's value only across a short gap, and says so. Reading an absent `lit`
tag as "unlit" would manufacture a lighting effect out of mapper attention, pointing
exactly the way the registry expects.

**Validated live on Cyprus B9, 2026-08-10.** 12 of 14 attempted factors resolved.
`lit` (32% tagged), `sidewalk_present` (16%) and `median_present` (0%) were refused and
reported. `grade_pct` reads a median 6.1% and a maximum 9.6% climbing into the Troodos.

`population_density` is the one Tier A factor in the brief with no adapter, and the
reason is delivery format rather than data — see the open decisions below.

### 2.2b — done

```bash
roadrisk corridor --ref B9 --bbox 34.80,32.80,35.05,33.05 --region europe --severity injury
```

Fetching **by road reference** rather than routing between two points is deliberate: a
router returns the *fastest* path and will leave the road you asked about without
telling you. `ref="B9"` cannot return anything that is not the B9.

Validated live against two real Cyprus roads:

| | B9 (Troodos, undivided) | A1 (motorway, divided) |
|---|---|---|
| Fragments | 69 | 49 |
| After merge | 3 | 4 |
| Gaps bridged | 2 | 0 |
| Longest share | **100%** | 26% |
| Divided | no | **yes** (49/49 one-way) |
| Result | 25.07 km | 8.11 km, 22.68 km excluded and reported |

The network layer is injectable, so all 34 tests run without touching it.

---

## Stage 3 — Model depth

**Complete.** Panel-clustered standard errors, the spline diagnostic, the Bayesian
random-intercept GLMM, the registry's weights as priors, the spatial field, and
out-of-sample validation.

| | Step | Deliverable | Done when |
|---|---|---|---|
| `[~]` | **3.1** NB GLMM | Panel-clustered standard errors **done** — up to 3.9x wider, two factors lose significance. The random-intercept GLMM itself is deferred to 3.3, see below | Standard errors widen versus plain NB2 ✅ |
| `[x]` | **3.2** GAM diagnostic | Spline on geometry, hunts the U-shape | Produces the diagnostic plot, never ships a number ✅ |
| `[x]` | **3.3** Bayesian hierarchical + spatial | Random-intercept GLMM **done** — credible intervals replace p-values, σ_u estimated at last. `expected_sign` encoded as a prior **done** — the registry's cited weights are the prior means, with the share of each answer they account for reported per factor. CAR/BYM **done** — a Leroux field over the corridor chain, fitted by joint Laplace, reporting rho with a credible interval and saying plainly when the corridor cannot tell | Credible intervals replace p-values in the report ✅ · `expected_sign` encoded as prior ✅ · CAR/BYM ✅ |
| `[x]` | **3.4** Out-of-sample validation | Spatial CV over contiguous stretches, CURE plots with a measured design effect, calibration on held-out units | Reported by default, including when bad ✅ |

### 3.3 — credible intervals, and the two halves still outstanding

```bash
roadrisk demo --units 40 --periods 12 --bayes
roadrisk assess panel.csv --bayes
```

**Delivered: the random-intercept GLMM, with credible intervals.** A p-value answers
"how surprising would this data be if the effect were exactly zero", which is nobody's
question. A credible interval answers "where is the effect, given this data". The result
type carries **no p-value at all** — not by convention, by construction, and a test
enumerates the forbidden fields.

It also estimates **σ_u**, the between-segment spread on the log rate. Rungs 1 and 2
could not measure that quantity at all: clustering corrects the *spread* of the
estimates, a random intercept models the thing causing it and changes the estimates too.

**An inference ladder, because the fast method has a measured limit.** Laplace with an
importance check first, MCMC only when that check fails, refusal when neither can be
believed — the same shape as the mode ladder and the rung ladder, receipts included.

| Specification | Dims | Outcome |
|---|---|---|
| 3 factors | 6 | Laplace, **~4 s** |
| A-reduced, 5 factors | 8 | Laplace, **~12 s** |
| A-full, 8 factors | 11 | Laplace refuses → MCMC, minutes |

Importance sampling loses efficiency exponentially with dimension; nine proposal
variants were tried on the eleven-dimensional case and none rescued it. Both validated
corridors — B9 and N201 — land on A-reduced, the side of that line answered in seconds.

**The honesty check is part of the fit, not a separate ritual.** The importance weights
police the approximation on every run: even weights mean it held, one weight carrying
everything means it did not. Two gates, Pareto k̂ ≤ 0.7 and ≥ 400 effective draws,
because k̂ says the *shape* was right and says nothing about whether enough draws
survived to place an interval endpoint. Neither threshold is negotiable to make a fit
pass.

`python tools/validate_posterior.py` runs both rungs on the same planted panel and puts
them side by side, the way `validate_coverage.py` proved rung 2's intervals honest.

**`--bayes` chooses how, never what.** `assess()` still exposes no way to force a mode or
a rung, and a test asserts the same panel returns the same mode, rung and factor list
under either estimator. NB2 stays on the result beside the posterior — it is the
comparison every reviewer expects to see cited.

### 3.4 — does it predict road it has not seen

```bash
roadrisk demo --units 80 --periods 18
roadrisk demo --units 80 --periods 18 --u-shape curve_density   # watch it fail
```

Runs on every Mode A assessment. **There is no flag that turns it on and none that turns
it off** — a model failing its own validation is a finding the report carries, not a
computation a caller may decline. A test asserts no such parameter ever appears.

**The folds are contiguous stretches, not random rows.** Adjacent segments share their
terrain, their design standard and the unobserved character rung 2 exists to model, so a
random fold leaves a segment's own neighbours in the training set and the model
half-remembers the answer. Both schemes are computed and printed side by side, so the
optimism of the easy one is visible rather than asserted.

| Scheme | Observed | Predicted | Ratio | MAD |
|---|---|---|---|---|
| contiguous stretches | 2,803 | 2,756 | 1.02 | 1.044 |
| random units | 2,803 | 2,722 | 1.03 | 1.042 |

**CURE plots say *where* a factor is wrong**, which no single number can. Cumulative
residuals against each factor, with a Brownian-bridge band; drifting outside it over a
stretch means the model is systematically over- or under-predicting for segments in that
band.

```
curve_density: outside its bounds over 22% of the range, worst around 0.25.
          cumulative residual, with ±2σ bounds
     +220 |        .....................
          |  ###********                .......
          | ...         * ****                 ...
          |.             *    ***                 .#
        0 |**--------------------*----------------*.
          |.                      **              .
          | ...                     ** ****    ...
          |    ....                   * ...**#####
     -220 |        .....................
```

That is the rung 3 spline's defect seen from the other side, and the verdict says so:
CURE finds *where*, the spline explains *what shape*.

**The CURE bounds needed the same correction the standard errors did, and that was
measured.** The textbook band assumes independent residuals. On this panel every factor
is a segment property repeated down every period, so a badly fitted segment contributes a
run of same-signed residuals and the cumulative sum wanders much further than an
independent-increment band allows. Uncorrected, on a panel whose effects are *planted
linear*:

| Per-unit heterogeneity | Share of curve outside |
|---|---|
| none | 0–6%, correctly nothing |
| 0.25 | 7–23% |
| 0.5 (realistic) | **16–60%, all of it spurious** |

Residuals are now summed within a segment before anything accumulates, and the remaining
inflation — measured as the variance of the standardised unit residuals, 6.4× on the
realistic panel — widens the band and is reported. The correction did not simply widen
until nothing fires: a planted U-shape still reads 22% outside and **still names only the
guilty factor**.

**Below 25 units it is declined, not estimated badly.** Five folds of five segments
measure noise. The run says so, and says what is missing rather than implying the fit is
worse than it is.

**What it cannot do.** It validates the specification against the corridor's own crash
data. It cannot say whether that crash data is any good, and on synthetic crashes it is
measuring the generator. Both are stated in the run rather than left to be worked out.

### 3.3b — registry weights as priors *(done)*

```bash
roadrisk demo --units 40 --periods 12 --priors --facility-type rural_two_lane --region europe
roadrisk assess panel.csv --priors
```

The brief's unifying idea, implemented:

> A prior is what we believed before seeing data. **Mode B weights are priors.** Mode A
> is those priors updated by data.

**Three answers per factor, and the engine names one.** Textbook, this corridor alone,
and the two combined — all printed, because showing one without the others hides where
the number came from, and showing three without designating one pushes the choice onto
the reader.

```
Factor            Textbook   Your data      The mix   %bk  Reading
speed_limit         +1.600      +0.348       +0.880   34%  prior steadies it
                            [-0.41,+1.12] [+0.21,+1.59]
curve_density            —      +0.487       +0.328    —   shifted 0.5 SE by another prior
```

**`%bk` is the auditing device.** The share of the mixed answer that came from the
literature rather than this road, from the precision each side pulls with. 3% is your
road talking; 78% is a textbook with a corridor's name on it, and it is labelled.

**Measured on the same panel at two sizes:**

| | 691 crashes | 5,782 crashes |
|---|---|---|
| Designated answer | **the mix** | **your data** |
| `speed_limit`, corridor alone | +0.375 [−0.41, +1.15] — spans zero | +0.896 [+0.52, +1.27] |
| `speed_limit`, mixed | +0.900 [+0.23, +1.60] — usable | +1.026 |
| Prior share | 34% | **11%** |

The planted truth is +0.90. The rich corridor found it alone; the thin one needed the
literature to get there. **More data automatically makes the textbook matter less** —
there is no rule doing that, it falls out of the arithmetic, and it is the check that
the priors are not quietly doing the work.

**Off by default.** `--bayes` alone still uses uninformative priors, so every number
already published stays reproducible. Part of a prior-informed answer is somebody else's
evidence, and that is a choice a user makes rather than one the engine makes for them.

**Four guards, each against a specific way this could mislead:**

- **`expected_sign` is never a constraint.** Truncating a coefficient to its expected
  direction would make `P(β has the wrong sign)` identically zero and delete the sign
  guard by construction. Every prior is a plain normal with support on both sides.
- **Contradiction is judged on the corridor-only fit.** Asking the mixed fit whether it
  disagrees with the textbook asks a question the prior has already influenced.
- **A prior-dominated coefficient may not become a crash count.** Mode B refuses to
  produce a count from published weights alone; the same number arriving through a
  prior gets the same rule.
- **Indirect shifts are reported.** A factor with no cited weight is *not* insulated:
  coefficients are correlated, so a prior on one drags its neighbours. The first run of
  this comparison moved an uncited factor by half a standard error while describing it
  as "this road's data alone". It now says which factors were moved, and by how much.

**One honest wart.** The prior *widths* — 0.35 for a clean cited weight, ×1.25 per
recorded concern, floored at 0.15 — are a judgement, not a citation. A package that
refuses uncited weights now carries uncited confidence levels. They are derived from
what the registry already records (source agreement and concern count) rather than typed
in per factor, and keeping the whole thing opt-in is what stops them reaching a default
number.

### 3.3c — spatial CAR/BYM *(done)*

```bash
roadrisk demo --units 80 --periods 12 --spatial
```

Rung 2 gives every segment an independent random intercept, which is wrong about a road:
a bad stretch is a *stretch*, and whatever makes segment 47 dangerous is usually working
on 48 as well. A Leroux CAR field says so.

**It was recorded here as blocked, and the record was half right.** The quadrature in
3.3a integrates each unit's effect out separately, which works *only* because units are
independent — a CAR field couples them and the integral stops factorising. That much was
correct. What was missed is that the *outer* half of that module never cared how the
marginal was obtained: swapping the inner quadrature for a **joint Laplace over the whole
latent field** left mode-finding, the importance check and every reporting surface
untouched. The block was in one function, not in the design.

**A corridor is a path graph, and that is what makes it cheap.** Neighbours are the units
either side, so the precision matrix is tridiagonal: Newton needs a banded solve and the
determinant a banded Cholesky, both O(units). One marginal evaluation on eighty units
costs about two milliseconds. None of the awkward areal cases — islands, disconnected
components, uneven neighbour counts — happen on a road.

**Leroux, because it nests what already exists:**

    Q = (1 / sigma_u²) [ (1 - rho) I + rho R ]

`rho = 0` is rung 2 exactly, `rho → 1` approaches the intrinsic CAR limit. So "is there
spatial structure here" becomes "is rho credibly above zero", answered by one posterior
rather than by comparing two models. A test asserts the nesting holds.

**Measured against planted truth:**

| Planted | Estimated | Verdict |
|---|---|---|
| ρ = 0.0 | 0.21 [0.01, 0.56] | *no spatial clustering worth modelling* |
| ρ = 0.9, 80 units | **0.89 [0.73, 0.98]** | *neighbouring segments are correlated* |
| ρ = 0.9, 40 units | 0.44 [0.05, 0.86] | *this corridor cannot tell* |

The last row is the caveat that was predicted, now measured rather than feared: below
about eighty units the spatial and independent parts of the field explain the same
variance and there is not enough road to separate them. **The report says so** instead of
presenting 0.44 as a finding. That is an answer about the corridor, not a failure.

**Two approximations are now stacked** — a Laplace over the latent field inside, and the
existing Laplace-with-importance-check over the hyperparameters outside. The importance
check polices only the outer one, which is stated in the module rather than glossed.

### 3.2 — the spline, and the bend it refuses to invent

```bash
roadrisk demo --u-shape curve_density
roadrisk assess panel.csv --shape curve_density
```

The sign guard's four existing diagnostics all hunt the brief's *first* suspect,
confounding — they ask which other term a wrong sign lives with. None can see the third:
a linear term forced through a U-shape has no correlated partner to blame. The spline is
the only diagnostic here that can say **this is why**, and the only one that can say
**this is not why** and hand the question back.

**The first version invented a bend.** Choosing the smoothing penalty by AIC, it drew an
inverted U on a panel whose curvature effect was planted *linear* — the worst failure
this module could have, because its answer is the one that stops people looking. Across
the penalty grid the truth was visible: one penalty of five found that bend, while a
genuine planted U held at three of five. So the headline is now the shape the grid
agrees on, and every penalty's answer is reported either way.

**The band is a cluster bootstrap, not the spline's own standard errors** — step 3.1
established that these rows are not independent, and drawing a naive band would undo
that correction in a new place. It yields a better headline than a band anyway: *the
same shape came back on 40 of 40 corridors resampled by unit*. A turn a majority of
resamples do not reproduce is refused as an explanation.

**It cannot ship a number.** `ShapeDiagnostic` has no coefficient, no p-value, no
predicted count and no interval — by type, not by convention. A test enumerates the
forbidden names and fails the moment one appears.

Deferred: the brief's *"convert the finding into an interpretable term"*. When the
spline finds a U the verdict names the fix and a human applies it. Automating it means
letting a diagnostic rewrite the specification it was checking, and the turning point is
not stable enough on 120 units to define a breakpoint — which the resampling is what
tells you.

### 3.1 — the panel correction, and what is deferred

```bash
roadrisk demo
```

**Why it matters more here than in most panels.** Every factor is *unit-constant* —
curvature, gradient, lane count, every density is a property of a segment, repeated
unchanged down every period. A 120-unit corridor over 24 months has 5,760 rows and
**120 independent observations of each covariate**. Rung 1 computes its intervals as
though it had 5,760.

Measured on a panel with realistic segment-level heterogeneity:

| | Naive p | Clustered p | Interval |
|---|---|---|---|
| `access_density` | < 0.0001 | **0.65** | 3.86× wider |
| `junction_density` | < 0.0001 | **0.05** | 2.90× wider |
| `curve_density` | < 0.0001 | 0.03 | 3.00× wider |

Two factors lose their significance. They were never significant — the first fit was
counting one segment forty-eight times. This is the brief's warning, reproduced:
*"this alone may change the geometry p-value."*

**The demo panel was fixed to make this visible.** It drew its overdispersion per *row*,
so every observation of a segment was independent — not what a panel is, and the
correction had nothing to find. Segments now carry persistent character by default;
`--unit-dispersion 0` restores the old behaviour.

**The coefficients do not move.** Only the covariance changes, so the report prints both
standard errors side by side with the ratio between them — a correction nobody can see
the size of is a correction nobody believes.

```
factor              β        SE naive   SE panel      ×
access_density   +0.0645       0.0370     0.1429   3.86
```

**The intervals are honest, and that is measured rather than asserted.** The synthetic
panel's coefficients are planted, so coverage is testable: across 60 panels, rung 1's
95% intervals contained the truth **70%** of the time and rung 2's contained it **95%**.
On data with genuinely independent rows rung 1 was already at 94% and the correction
does not inflate it. `python tools/validate_coverage.py`.

**Below 20 units the correction is declined, not silently applied.** The sandwich
estimator is consistent in the number of *clusters*; below a couple of dozen it is biased
downwards and would report intervals that are still too small while appearing to have
fixed the problem. The M51 corridor, with seven units, sits squarely in that zone — the
run says so, and estimates how wrong the uncorrected intervals are.

**What is deferred, and why.** This is not the random-intercept GLMM the step names. A
random intercept models the unobserved heterogeneity between segments and changes the
*estimates* as well as their spread; clustering corrects the spread only. The brief calls
rung 2 a *"cheap upgrade"*, and MCMC is not cheap — it would add PyMC, convergence
diagnostics and minutes per run. That dependency is already required by **3.3**, so the
GLMM belongs there, where it is paid for once and reported properly.

---

## Stage 4 — Report

**Complete.** The report model, the ranking, the page, the figures, the PDF, the limitations page and the CLI seam.

**Re-scoped deliberately.** The original 4.1 said *"same template serves the web page and
the PDF"* and assumed a Jinja template rendered in Python. With **5.3** in React, that is
two renderers in two languages, kept in visual sync by hand, forever. The report and the
UI would drift the first time either of them changed.

So there is one renderer, and it lives in the UI. The PDF is a print stylesheet over the
same route, not a second pipeline. WeasyPrint is gone — it cannot render the thing the
client will actually be looking at.

**The contract is JSON.** `Assessment.as_dict()` already calls itself *"the shape the API
and the report template consume"*; this stage finishes that promise and then holds the
line. Nothing renders from a live Python object, so a stored run can be re-rendered
without a refit, and the same payload feeds **5.1** and **5.3** unchanged.

| | Step | Deliverable | Done when |
|---|---|---|---|
| `[x]` | **4.1** Report model | `CorridorPanel.as_dict()`, the fitted values the serialised fit currently drops, and an attribution collector that separates report-attribution from database share-alike | A report renders from `assessment.json` + `corridor.json` alone, with no engine object in scope ✅ |
| `[x]` | **4.2** Rank and blackspots | One ranking surface for both modes — Mode A by predicted rate with its interval, Mode B by index score — and contiguous runs aggregated into blackspots with chainage extents | Both modes produce the same-shaped table; a blackspot never spans a chainage gap; Mode B rows carry no count and no interval ✅ |
| `[x]` | **4.3** Report page | React view over the JSON — method, mode banner, factors with source/tier/licence/confidence, ranked units, receipts. A standalone bundle that loads a run from disk | Opens a run written by `roadrisk corridor --out` with no server running ✅ |
| `[x]` | **4.4** Figures | Spline curves, CURE plots, calibration and a risk strip along chainage, as SVG over the curve data already in the JSON | No external image request anywhere in the page ✅ |
| `[x]` | **4.5** PDF export | `@media print` and `@page` over the same route — banner on every page, page counters, no orphaned tables | The exported PDF and the screen are the same document, and every number in it is traceable to a source ✅ |
| `[x]` | **4.6** Limitations page | Generated from the run, not written into the layout: dropped terms, failed checks, missing factors, Tier B caveats, the `speed_limit` and HSM caveats, Mode B's ranking-only status, corridor count, crash-mix defaults, cache age | Cannot be disabled by config — no flag removes it, and a test that tries every way to suppress it still finds it ✅ |
| `[x]` | **4.7** CLI seam | `roadrisk corridor --report`, and `--bayes` / `--priors` / `--spatial` wired through `corridor` | `roadrisk corridor --demo --bayes --report out/` goes from coordinates to a readable report in one command ✅ |

### 4.3 — one renderer, built early rather than twice

The page is written in React from the start and graduates into **5.3** as the report tab.
That pulls a JS toolchain into the repository at 4.3 instead of 5.3, which is paying
early, not paying extra — Stage 5 is on the roadmap either way. What it buys is that the
client's report and the client's screen can never disagree, because they are the same
component tree.

Until **5.1** exists the bundle is static and reads a run from disk, which is also how it
stays honest to the rest of this project: a corridor assessed offline, with no network
and no API key, still produces something a client can open.

### 4.5 — the PDF is a stylesheet, not a pipeline

Measured on the development machine, 2026-08-20, so that it is not re-litigated later:

- **Headless Chrome renders it.** `@page` margin boxes, `counter(page)` / `counter(pages)`
  and inline SVG all work — the mode banner repeated on all three pages of a test
  document. Chrome and Edge are both already installed.
- **`string-set` is not supported, and is not needed.** One report is one mode, so the
  banner is constant for the whole document and is written into the `@page` rule directly.
  Running headers only need `string-set` when they change per page; this one does not.
- **WeasyPrint could not load at all** — no GTK runtime present, and a partial
  `libgobject-2.0-0.dll` on `PATH` from an unrelated install is picked up first. Moot now:
  it cannot render a React page regardless.
- `--no-pdf-header-footer` is silently ignored. The flag is `--print-to-pdf-no-header`,
  and without it Chrome stamps a date and a URL on every page.

Client-side export is the browser's own print dialogue and needs no infrastructure at all.
Server-side generation — for a run that has to be stored or emailed — is headless Chrome
against the same route, producing the same document.

### 4.7 — the geometry path can finally reach every estimator

`corridor` called `assess()` with a context and nothing else — no estimator, no priors,
no spatial flag, no splines — so **the whole of Stage 3 was unreachable from the
geometry path.** A corridor assessed from coordinates could only ever produce p-values,
while the brief asks for credible intervals in the report and `assess` had offered them
since 3.3. Both commands now share one definition of each option.

Running that path through to a rendered page for the first time is what caught the
mislabelling recorded in [`IMPLEMENTED.md`](IMPLEMENTED.md): `posterior.coefficients` is
a mapping keyed by factor, the page treated it as a list, and every row silently fell
back to its frequentist interval under a *credible interval* heading. Nothing caught it
for three steps — the types agreed, the fallback was silent, and no test had ever
rendered a converged posterior.

### 4.6 — the limitations page is data

It is assembled from what the run actually did. Most of it is already on `as_dict()`:
`checks`, `factors.missing`, `factors.dropped_for_collinearity`, `receipts`, `validation`,
`context.crash_mix_is_default`. The two standing caveats from **Open decisions** — posted
speed standing in for operating speed, and the unpinned HSM edition — are registry-level
and come from [`docs/WEIGHTS.md`](docs/WEIGHTS.md).

Written as prose in the layout it becomes a thing that can be quietly edited out. Written
as data, removing it is a code change with a failing test attached.

---

## Stage 5 — Web layer

`core/` must never be imported *by* — only imported *from*.

**Stage 4 paid most of 5.1 and 5.3 forward.** The report model is already the transport
shape — `Assessment.as_dict()` plus `CorridorPanel.as_dict()`, JSON all the way down —
so the API's response body is a payload that exists, and the report page is a React
component that takes it as a prop. Neither should be written a second time.

**What this stage is for, plainly.** Today the product is a command you run on your own
machine, and a run is a folder you must not delete. Stage 5 makes it a website: runs are
stored, long fits happen in the background under a spend cap, a client picks a road on a
map instead of typing coordinates, and more than one client can do it without seeing each
other. **It buys reach, not credibility.** The numbers do not improve, and the sequencing
rule at the top of this file still holds — Stages 1 and 3 are the credibility path, and
this is not. It is worth building when the bottleneck is *nobody else can use this*, not
while the bottleneck is *two corridors and synthetic crashes*.

**Two things were re-ordered against the original four steps.**

*Tenancy moved out of 5.4 and into the first migration.* "Two tenants cannot see each
other's runs" is a property of **storage**, not of authentication — auth is who you are,
tenancy is which rows exist at all. Retro-fitting an owner key onto project, job and run
means rewriting every query and every test the stage has accumulated by then. The key
lands in 5.1b; 5.4 puts real identities behind it.

*The API is asynchronous from its first endpoint.* Measured in this repository already: a
cold corridor is 55.5 s (2.9), `--bayes` on the demo corridor runs for tens of minutes
(4.7), and MCMC is minutes when it is reached at all. No HTTP request survives that. If
`POST /jobs` only starts returning 202 once Celery exists, 5.2 changes the contract and
breaks every client written against 5.1. So the job resource is 5.1's, and 5.2 swaps what
executes it.

| | Step | Deliverable | Done when |
|---|---|---|---|
| `[x]` | **5.0** Boundary test | Import-graph assertion: `core` imports nothing from `geo`, `report`, `api`, `worker` | Adding such an import fails a test that names the offending module ✅ |
| `[ ]` | **5.1a** Contract frozen | Pydantic models mirroring `as_dict()`, a `schema_version`, and `web/src/types.ts` generated from them rather than hand-written | A stored run round-trips through the models; the hand-maintained types are gone |
| `[ ]` | **5.1b** Storage | Postgres schema — tenant, project, corridor, job, run — payload as JSONB, artefacts by reference, migrations | A run written by the CLI imports and re-renders from the database with no refit |
| `[ ]` | **5.1c** FastAPI | Project and corridor CRUD, `POST /jobs` → 202, `GET /jobs/{id}`, `GET /runs/{id}`, artefact download | OpenAPI generated, with factors, tiers and licences read from `factors.yaml` |
| `[ ]` | **5.1d** In-process executor | A runner interface with a synchronous implementation behind it | A demo corridor goes submit → report with no broker running |
| `[ ]` | **5.2a** Celery chord | Fan-out adapters, join, fit | An adapter failure fails its own branch — the factor is reported missing, the job is not failed |
| `[ ]` | **5.2b** Cost model + cap | Per-source request accounting, a price table, a per-project cap enforced *before* the call | A job that would breach stops at the boundary, names the source, and the partial run is still a run |
| `[ ]` | **5.2c** Secrets per tenant | Per-project keys, validated at entry, and an Overpass identity with a rate budget | A scope-less Mapillary token is refused when the key is entered, not rediscovered per run |
| `[ ]` | **5.3a** Report as a library | `web/src/` splits into `<Report run={run} />` and two thin entry points | The single-file bundle still opens from `file://`; the app renders the same component tree |
| `[ ]` | **5.3b** Next.js shell | Routes, layout, and the mode banner as a *layout* element | Mode banner unmissable on every screen — no route can omit it |
| `[ ]` | **5.3c** MapLibre map | Corridor geometry, units coloured by rank, factor provenance on click | Tiles never enter the report path; the document keeps its own SVG map |
| `[ ]` | **5.3d** Interactive layer | The hover and detail layer 4.4 deferred as screen-only | Native `<title>` still works with JavaScript off |
| `[ ]` | **5.4a** Auth + RLS | Supabase auth, row-level policies | The *database* refuses a cross-tenant read, proven by querying as tenant B |
| `[ ]` | **5.4b** Projects + history | Saved runs, re-open, re-render | Yesterday's run opens without a refit |
| `[ ]` | **5.4c** Corridor comparison | Two corridors side by side with mode, factor coverage and validation outcome | Every number shows the context it was valid in |

### 5.0 — the rule, before there is code able to break it *(done)*

```bash
pytest tests/test_layering.py
```

Four rules, checked by parsing the source with `ast` rather than by importing anything —
half this package is behind optional extras the test suite never installs, so a test that
imported modules could not see the layers it most needs to police.

| Rule | What it stops |
|---|---|
| Imports point downhill only | The layering rule itself, `core → demo → geo → report → api → worker → cli` |
| `core` imports nothing but `core` | The engine staying runnable on pandas and statsmodels alone |
| `report` imports nothing but `report` | 4.1's promise — a report renders from JSON, so a run stored months ago still renders |
| `roadrisk/__init__.py` stays a leaf | **The loophole**, below |

**The loophole is the reason this was worth a step.** `core` imports `roadrisk` for its
version string. The day the package root re-exports something from `roadrisk.geo`,
importing the engine imports shapely — while every direct import still points downhill and
every other check here still passes. The rule as written in the docstring for five stages
would not have caught it.

A fifth test plants a violation and reads the failure back, because a test that cannot fail
is decoration. All four were also verified against violations planted in the real source:
each names the file, the line and the rule.

### The refusal contract — a refusal is a result, not an HTTP error

The largest design risk in this stage. Three outcomes have to stay distinct, and a REST
instinct collapses all three onto 4xx and 5xx, which would swallow the entire honesty
layer into a generic error handler:

| Outcome | HTTP | Why |
|---|---|---|
| `ContractViolation` at submit | **422**, column named, no job created | The panel was rejected. This is the CLI's refusal receipt, over the wire |
| Descent to Mode B, dropped terms, a refused weight | **200, completed** | Mode B is the floor. The engine's refusals are *content*, and the run carries them |
| Overpass 429, absent token, no GDAL | job status `failed`, with a cause | Infrastructure failed. Never a 500 with a stack trace |

A test should assert that a Mode B descent is a 200 carrying its descent receipt.

### 5.1a — why the contract is frozen before the API is written

`web/src/types.ts` is hand-written and deliberately narrow, which was right when one
renderer read one file. With an API it becomes two hand-maintained descriptions of one
contract in two languages, and **4.7 already recorded what that costs**:
`posterior.coefficients` is a mapping and the page typed it as a list, so every row fell
back silently to its frequentist interval under a *credible interval* heading, and
survived three steps. Generating one description from the other is the fix that bug
argues for, which is why this precedes 5.1c rather than following it.

### 5.2 — two traps that are specific to this pipeline

**Nothing counts spend today.** There is no budget accounting anywhere in `src/`; the
only cost figure in the repository is the 50–150 USD per corridor recorded against the
unbuilt `mapillary_vision`. The done-when says *enforced in the runner*, so the cost model
is built here, not wired up — and a cap refusal enters the run log like every other
refusal in this project.

**The chord is where the cache stops being a cache.** 2.9's store is content-addressed on
disk for a single user. Parallel adapter branches racing on the same half-degree grid cell
need a lock or a shared store, or the first corridor pays its 55.5 s several times over.

### 5.3 — the map on the screen is not the map in the document

4.4 drew the corridor as inline SVG in equirectangular projection so that **no external
image request exists anywhere in the report** — that is its done-when, and it is what lets
a report be emailed. MapLibre needs a tile source, which is both a network dependency and
a new attribution obligation. So MapLibre is the screen and the SVG stays the document;
they are not consolidated.

---

## Stage 6 — Deploy

| | Step | Deliverable | Done when |
|---|---|---|---|
| `[ ]` | **6.1** Containers | Dockerfiles for api / worker, compose for local | `docker compose up` runs a corridor |
| `[ ]` | **6.2** Hosting | Vercel + Fly/Render + Supabase + Cloudflare R2 | Public URL resolves over TLS on a custom domain |

---

## Open decisions

Things that need a human call, not a code change.

1. ~~**Mode B default weights are unsourced.**~~ **RESOLVED as far as it can be
   without spend, 2026-08-10.** Seven of twenty-two factors carry ten weights derived
   from the AASHTO HSM, the Elvik Power Model and iRAP, each computed by
   `tools/derive_weights.py` and documented in [`docs/WEIGHTS.md`](docs/WEIGHTS.md).
   Weights are context-aware — the engine picks by facility type, region and crash
   severity, reports what it reached for, and scores agreement between sources.
   **Two things still need a human:**
   - **A licensed AASHTO HSM.** Equations were read from the NCHRP draft text of the
     2nd edition and are double-checked against their published worked examples by
     `tests/test_published_equations.py`, but HSM2 (2024) changed Parts C and D and
     nothing here is edition-pinned to a verifiable artefact. One afternoon with the
     book closes it.
   - ~~**The iRAP Methodology Reference Guide v3.10.**~~ **DONE.** Sourced grade,
     curvature, skid resistance and street lighting. Global weights went 4 → 8, and a
     European or MENA corridor now reaches for American evidence on one factor instead
     of three. `median_type` is the best remaining candidate but needs the Star Rating
     Score traversability normalisation understood first — its values are 0-100
     traversability scores, not CMFs. See `docs/WEIGHTS.md` for the four attributes
     examined and deliberately not used.
2. **Measure operating speed on one corridor.** `speed_limit` carries a permanent
   caveat because the Power Model exponent applies to operating speed, not posted
   limit; `operating_speed_85` exists and is uncaveated but has no data. A single
   Tier C speed pull removes the largest known weakness in the index.
3. **Supply a local crash-type distribution.** Mode B now decomposes the score by crash
   type, and the default shares come from HSM Table 10-4 — Washington State, rural
   two-lane, 2002–2006. Most national crash databases can produce a local split
   directly, and it is one of the cheapest accuracy improvements available. Pass it as
   `RunContext(crash_mix=...)`; `uniform_mix()` is available for corridors where no
   defensible split exists.
4. **Resolve `lanes`.** It is currently a volume proxy expecting `+` for total crashes,
   while iRAP prices lane count at `−` for head-on-overtaking crashes only. Two
   mechanisms in one column — the composite-masking trap the brief warns about. The
   real fix is separating the exposure role from the risk role, not picking a sign.
3. **`population_density` needs a range-readable source, or the 2.9 cache.** It is the
   one Tier A factor in the brief with no adapter, and the obstacle is delivery format
   rather than data. Every other raster here is a cloud-optimised GeoTIFF, so a corridor
   costs a few window reads; neither population source is. Measured 2026-08-10:
   WorldPop's global mosaic answers a `Range` request with **200, not 206** — it ignores
   the header and streams the whole file — and GHSL ships deflated zip tiles whose
   members cannot be windowed. Either way one corridor costs a whole-file download,
   which contradicts the registry's own instruction on the DEM adapter. Three ways out,
   in order of appeal: find a COG mirror (Meta's HRSL on `dataforgood-fb-data` is a
   candidate and would need a new adapter declared); wait for the content-addressed
   cache in 2.9 and pay the download once per region; or drop the factor and let
   `landuse_urban` and `building_density` carry urban context between them.
4. ~~**Second corridor.**~~ **DONE, and it moved the problem, 2026-08-17.** Five real
   roads were measured against this decision's own criterion; **Dutch N201** wins with
   18 units carrying accesses and no ramp, 15 carrying a ramp and no access, and VIF
   1.00/1.00 between them. B9 could never have settled it — zero units of fifty carry a
   ramp and no access. Re-runnable as `python tools/validate_corridor.py`.

   **What it exposed.** `ramp_density` is *eighth* by `drop_priority` and A-full keeps
   seven, so on a corridor where the higher-priority factors all resolve it is shed
   before fitting at every rung. Separation in the data is necessary and not sufficient.
   Three things have to hold together: a corridor that separates them (N201 does),
   enough crashes to buy the terms, and a specification that carries `ramp_density` at
   all — which today means fitting it deliberately.

   **The critical path is now crash data, not geography.** Every corridor run so far
   uses synthetic crashes, which validate the geometry and adapter path and nothing
   about a road. A single real police extract is worth more than a third corridor.
4. **Rung 4 engine.** PyMC/NumPyro keeps one language; R + INLA is materially faster for
   CAR/BYM at panel scale. Defer until MCMC actually hurts.

---

## Project Requirements

Reference only. This section records what the call topic *Road Safety and Resilience of
Rural Areas* asks a funded project to deliver. It states the requirements as written; it
does not assign them to stages.

### Context the call sets

More than 50% of all EU road fatalities occur in rural areas, and crashes and
crash-related fatalities on rural roads differ from those on urban roads and motorways.

The **RISM Directive** introduced the concept of **network-wide road safety assessment
(NWRSA)** and of proactive assessment through the **in-built safety** of roads.
Network-level assessment gives an overview of road safety performance instead of
focusing on isolated parts of it; in-built safety assessment identifies parts of the road
that crash-based analyses (crash clusters, hotspot analysis) omit — sections that do not
concentrate the majority of crashes yet are crash-prone and/or uncomfortable to navigate.

A methodology has been developed under the Directive to assess the network-wide safety of
**motorways and primary rural roads** on their combined crash-based and in-built safety
assessments. **Secondary and lower-class roads are not covered**, and there is not
adequate information on road user behaviour.

The call additionally notes that in an ageing society, cognitive and physical impairments
pose an increasing threat to safe mobility, and that in rural areas people with any kind
of impairment or disability often lack alternatives to driving — so addressing this
concerns quality of life and social exclusion as well as road safety.

Local and regional authorities also manage risks from extreme weather phenomena and
natural disasters such as floods, fires, storms or heavy snowfall, which affect both
safety and operations, and need a more holistic resilience monitoring and response.

### Expected outcomes

Project results are expected to contribute to **all** of the following:

1. Implementation of the **NWRSA methodology for secondary rural roads**.
2. **Innovative and effective enforcement strategies, incentive mechanisms and measures
   raising risk awareness** for fostering safer behaviour.
3. **Prevention strategies** for reducing road fatalities and serious road traffic
   injuries on rural roads, along with the respective **implementation guidelines and
   policy measures tailored to the responsible stakeholders** (regional authorities,
   police, healthcare professionals, national governments, etc.).
4. A **GIS-based application** to assist local and regional authorities in identifying and
   mapping the impact of extreme weather phenomena and other natural disasters (floods,
   fires, storms, heavy snowfall, etc.) on the safety and resilience of the road network
   in their jurisdiction.

### Required actions

Research should undertake **all** of the following, in **at least three regions**,
covering **both primary and secondary rural roads of adequate length** to allow
region-level comparisons:

1. **Demonstrate the practical applicability of the NWRSA methodology and expand its use
   to all rural roads** for an easy, low-cost, flexible and transparent, yet sufficiently
   accurate assessment of road infrastructure safety. **Identify information gaps and
   propose methods to leverage available data** to supplement the understanding of crash
   causation and outcomes.

2. **Develop prevention strategies and measures** to reduce fatalities and serious
   injuries in rural areas, with a focus on high-risk locations and situations and on
   improving road user behaviour. This includes:
   - reliable and easy-to-use methods providing **quantified indications of the actual
     crash risk** associated with, and the **prevalence of**, risky behaviours;
   - **enforcement measures with evidence-based effectiveness** addressing the problems
     and motivations underlying risky behaviour, combining traditional methods with
     innovative enforcement approaches and new technologies;
   - the issue of **multi-offenders** — a small group of repeat offenders accounts for a
     large share of crashes (e.g. 5% of the population vs 27% of crashes, SWOV 2017);
   - **intoxication by drugs** — recent studies show the share of crash-involved drivers
     intoxicated by drugs equals or surpasses those intoxicated by alcohol (Gjerde &
     Forst 2023);
   - **awareness raising and nudging measures**, and **novel incentive mechanisms** to
     promote safe driving, forming building blocks of integrated strategies tailored to
     local needs and rural specificities;
   - a **gender and disability sensitive and intersectional approach**, intersecting with
     other social factors, could be considered;
   - **countermeasures for health-related risk factors**, guaranteeing at the same time
     the mobility of older people and persons with health impairments in rural areas.

3. **Develop tools to make knowledge about climate-related risks easily accessible to
   local authorities**, enabling them to take appropriate actions to maintain road safety
   and the resilience of the rural road network and of the infrastructure for road users
   even in extreme conditions.

### Region selection

- Regions must ensure **diversity in terms of road network design, geography and climate
  conditions, and road safety culture**.
- **At least two** of those regions should be in **countries with a higher percentage of
  fatalities on rural roads than the EU average**.
- **Involvement of road authorities is strongly recommended.**

### Maturity

Activities are expected to achieve **TRL 6–7** by the end of the project.
