# Build Steps

The full build, broken into ordered steps. Each step has one deliverable and one way to
know it is done. Status is tracked here; what was actually built is logged in
[`IMPLEMENTED.md`](IMPLEMENTED.md).

**Status key** — `[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked

**Sequencing rule, from the brief:** make the model defensible on two corridors → make it
modular → then sell it. Stage 1 and Stage 3 are the credibility path. Stage 5 is not.

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

| | Step | Deliverable | Done when |
|---|---|---|---|
| `[~]` | **3.1** NB GLMM | Panel-clustered standard errors **done** — up to 3.9x wider, two factors lose significance. The random-intercept GLMM itself is deferred to 3.3, see below | Standard errors widen versus plain NB2 ✅ |
| `[x]` | **3.2** GAM diagnostic | Spline on geometry, hunts the U-shape | Produces the diagnostic plot, never ships a number ✅ |
| `[ ]` | **3.3** Bayesian hierarchical + spatial | CAR/BYM, `expected_sign` encoded as prior | Credible intervals replace p-values in the report |
| `[ ]` | **3.4** Out-of-sample validation | Spatial CV, CURE plots, calibration on held-out units | Reported by default, including when bad |

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

| | Step | Deliverable | Done when |
|---|---|---|---|
| `[ ]` | **4.1** Report template | Jinja HTML — method, mode, factors with source/tier/licence/confidence | Same template serves the web page and the PDF |
| `[ ]` | **4.2** PDF export | WeasyPrint, branded | Every number traceable to a source in the document |
| `[ ]` | **4.3** Limitations page | Data sources, dropped terms, unvalidated assumptions, what it does not cover | Cannot be disabled by config |

---

## Stage 5 — Web layer

`core/` must never be imported *by* — only imported *from*.

| | Step | Deliverable | Done when |
|---|---|---|---|
| `[ ]` | **5.1** FastAPI | Project CRUD, job submit, result read | OpenAPI schema generated from the registry |
| `[ ]` | **5.2** Celery worker | Pipeline as a chord: fan-out adapters, join, fit | Per-project spend cap enforced in the runner |
| `[ ]` | **5.3** Next.js + MapLibre | Corridor map, ranked units, factor provenance, mode banner | Mode banner unmissable on every screen |
| `[ ]` | **5.4** Accounts + storage | Supabase auth, saved projects, corridor comparison | Two tenants cannot see each other's runs |

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
