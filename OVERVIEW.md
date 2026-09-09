# The Road Risk Panel — What Exists, and What It Is For

*A single-file account of the whole system: the problem, the flow, what is built,
what is not, and an explicit brief for drawing it as one figure.*

Status as of **2026-09-08**. Sources for every claim here: [`STEPS.md`](STEPS.md) (the
plan), [`IMPLEMENTED.md`](IMPLEMENTED.md) (the build log), [`TESTS.md`](TESTS.md) (every
real road it has been run against), [`README.md`](README.md) (the user-facing description).

**What changed since the last revision of this file (2026-08-27).** One thing, and it is
the thing every previous revision of this file was waiting for.

> ### 🟢 The critical path is closed
>
> Every earlier version of this document ended its status line by saying that **every
> corridor run to date used synthetic crashes**. Between 2026-08-28 and 2026-09-07,
> **seven real corridors** were assessed across Cyprus, England, Scotland and France —
> four of them against real police crash tables, UK STATS19 and French BAAC, both open.
>
> The A6 through Derbyshire produced **the first fitted model in the project's history**
> on 284 real collisions. The A82 through Glen Coe ran the same method on a comparable
> road and **reached the opposite answer**, which is the argument for Mode A stated as a
> measurement rather than as a design principle. The A3 through Paris was the first
> corridor with enough crashes to reach **A-full**, at 1,403, and finished with all ten
> checks passing, both cross-validation schemes calibrated, and no material limitation.
>
> **And the reason for putting real data ahead of everything else held.** These roads
> found **fourteen defects** in code that was already written, already tested, already
> reviewed and already shipping confident numbers. Most of them were invisible from a
> synthetic panel by construction — a synthetic panel has no tied values, no busy
> Overpass mirror, no motorway and no national crash extract that is mostly somewhere
> else. §8 has the list.

Everything else in Stage 5 also closed: 5.3d and 5.3e finished the website, and an
unplanned 5.3f rebuilt the front page around what running it on real roads revealed. The
report gained a **verdict**. What remains anywhere is a spend cap, per-tenant secrets,
identities, and deployment.

---

## Contents

1. [In one paragraph](#1-in-one-paragraph)
2. [The problem this exists to solve](#2-the-problem-this-exists-to-solve)
3. [The whole flow, in twelve steps](#3-the-whole-flow-in-twelve-steps)
4. [Where the data comes from — the four tiers](#4-where-the-data-comes-from--the-four-tiers)
5. [The three ladders](#5-the-three-ladders)
6. [The honesty layer — rules enforced as code](#6-the-honesty-layer--rules-enforced-as-code)
7. [Where we are, stage by stage](#7-where-we-are-stage-by-stage)
8. [Evidence — what has actually been run](#8-evidence--what-has-actually-been-run)
9. [What is not built, and the critical path](#9-what-is-not-built-and-the-critical-path)
10. [Illustration brief — the figure to draw](#10-illustration-brief--the-figure-to-draw)

---

## 1. In one paragraph

Give the tool a road and a police crash table. It draws the corridor, cuts it into
segments, builds an empty panel from the **geography** rather than from the crashes,
fills that panel from free open data, checks whether the data can support a fitted
statistical model, chooses its own mode accordingly, fits or scores, checks its own
answers for contradictions, and returns a ranked list of dangerous segments where every
number can be traced to a named source. It writes that up as a report that ends on a
verdict about what the assessment is worth — never a grade for the road — and whose
limitations page is assembled from what the run actually did and which no setting removes,
keeps the
run so it re-renders years later without a refit, and serves the whole thing over HTTP and
on a website. The model is the easy part. The product is the **path** from *a road, a crash
table and open data* to *a defensible ranked assessment* — in places that have no AADT, no
road inventory and no survey budget.

---

## 2. The problem this exists to solve

**The established tools assume data that most of the world does not have.**
iRAP-style assessment requires a survey vehicle to drive the corridor and code it —
roughly 50–200 USD per kilometre. The AASHTO Highway Safety Manual's predictive method
requires AADT, a road inventory, and a calibration dataset. Both are excellent, and both
are unavailable on the roads where the death rate is highest.

**Three consequences follow, and they define the whole design.**

| The gap | What we do instead |
|---|---|
| No survey vehicle | Free maps, free satellite rasters, free street-level imagery. Tier A and Tier B replace the van. |
| No AADT | A graph-centrality **traffic proxy**, never called AADT, never dressed as a volume. |
| No inventory | The registry declares 23 factors; adapters fill what open data can support and **report by name** everything it cannot. |

**And one failure mode dominates the field.** A count model built only on the rows where
crashes happened cannot estimate a rate — it can only redescribe the crash table. It will
still produce confident-looking coefficients. Preventing that specific misuse, loudly and
without an override, is the single most load-bearing rule in the codebase.

---

## 3. The whole flow, in twelve steps

```
coords → route → segment → panel skeleton → adapter fan-out → fuse
       → snap crashes → validate → mode select → fit/score
       → sign guard → rank → report
```

| # | Step | What happens | State |
|---|---|---|---|
| 1 | **Resolve the corridor** | Fetch by road `ref` or name from OSM (never by routing — a router returns the *fastest* path and silently leaves the road you asked about). Match the reference by national spelling, stitch fragments, bridge the gaps at junctions, detect divided carriageways, **refuse a road that is not built**, project to UTM, build a linear reference: chainage 0 → N km. | **Built** |
| 2 | **Segment** | Cut into fixed-length units. Chainage continuous and exhaustive, no gaps, no overlaps, trailing runt merged. | **Built** |
| 3 | **Build the panel skeleton** | Cross `unit_id × period × time_slot`. `n_crashes` initialised to **0** everywhere. *This is where zero-crash rows are born — from geography, never from the crash table.* | **Built** |
| 4 | **Fan out the adapters** | One Overpass call along the corridor, two cloud-optimised raster windows, pure geometry, plus optional Tier B compute and a street-level imagery check. Each adapter returns value + source + tier + licence, and a *failure* returns a structured record that raises a material limitation rather than quietly changing the model. | **Built** (16 Tier A columns, 2 Tier B) |
| 5 | **Fuse and score agreement** | One value per factor per unit; the registry's ordered adapter chain decides the winner. Where two sources overlap, score agreement. Emit a **confidence tier per factor per unit**. | **Built** |
| 6 | **Snap the crashes** | Project each crash to the centreline within tolerance; chainage → `unit_id`, timestamp → `period` + `time_slot`. Every drop counted **with a reason** — and past 500 m a crash is not a near miss, it is somewhere else, so *missed the carriageway* and *was never on this road* are counted apart. | **Built** |
| 7 | **Validation gates** | Nine checks before anything is fitted: required columns, **zero-crash rows present**, exposure positive, crashes-per-parameter, temporal resolution, snap rate, VIF, variance-to-mean, convergence. Each returns HARD / SOFT / INFO. | **Built** |
| 8 | **Choose the mode — automatically** | Walk the ladder `A-full → A-reduced → A-minimal → B`, take the highest rung that passes every check. **The user has no override.** Every descent names the failed check and the dropped terms — and a term can leave for four distinct reasons, kept apart: nobody supplied it, the road does not have the feature, something better-evidenced measures the same thing, or it barely varies on this corridor. | **Built** |
| 9 | **Fit or score** | Mode A: NB2 GLM with `ln(exposure)` offset, panel-clustered standard errors, optionally a Bayesian random-intercept GLMM. Mode B: crash-type-decomposed weighted index from cited weights — **ranked score only, never a count**. | **Built** |
| 10 | **Sign guard and diagnostics** | Every coefficient checked against its declared `expected_sign`. On contradiction, auto-run five confounding diagnostics plus a **spline** that hunts the U-shape none of the others can see — then grade the finding: *suppressed by a named partner*, *too uncertain to have a sign*, or a real specification problem. | **Built** |
| 11 | **Validate out-of-sample** | Spatial cross-validation over contiguous stretches, CURE plots read against a measured design effect and treated as a *distribution* wherever a factor has tied values, calibration on held-out units — reported by default, including when bad. | **Built** |
| 12 | **Rank and export** | Rank units, aggregate into blackspots, render an HTML report carrying method, mode, every factor with source/tier/licence/confidence, dropped terms, a closing **verdict on what the assessment is worth**, and a limitations page that cannot be disabled. The PDF is that page printed, not a second document. | **Built** |

**And then, optionally, three more.** They add reach, not credibility, and the sequencing
rule in [`STEPS.md`](STEPS.md) says so plainly:

| # | Step | What happens | State |
|---|---|---|---|
| 13 | **Keep the run** | The whole payload into Postgres as `jsonb`, scoped to a tenant from the first migration, artefacts by reference. A stored run re-renders months later **without a refit**. | **Built** (5.1b) |
| 14 | **Serve it** | `POST /jobs` → `202`, a runner behind it, `GET /runs/{id}`. A refusal is a result: a broken panel is a `422` naming the column, a Mode B descent is a `200` carrying its receipts, and infrastructure failing is a job status with a cause. | **Built** (5.1c–d) |
| 15 | **A website over it** | **The front page is a map**: find a road, click it, attach a crash CSV, press the button. Under that: projects, corridors, jobs, runs, the registry — and the report itself as one of the screens, the same component the emailed file is built from. | **Built** (5.3a–f) |

**The two things that make it work, stated plainly:**

1. **The panel is built from geography, not from crashes.** Zero rows are structural, not
   optional. This is what makes a *rate* estimable rather than a *description*.
2. **Every value carries its source all the way to the report.** Nothing in the output is
   untraceable.

---

## 4. Where the data comes from — the four tiers

The whole product rests on one question per factor: **who pays to obtain it?**

| Tier | Meaning | Cost | Provided by | Built? |
|---|---|---|---|---|
| **A** | Open, global, no key, pure script | Free | Us, automatically | **16 factor columns live** |
| **B** | Open, but needs vision models or graph compute | Compute time | Us, with real work | **2 of 4 live** |
| **C** | Free-tier APIs, licence-limited | Free → paid | Us, opt-in only | Slots declared, none wired |
| **D** | Cannot be derived, must be measured | Client's cost | Customer | **Client adapter live** |

**Tier B is the moat.** It is what replaces the survey vehicle.

### What resolves today

| Source | Cost per corridor | Factors |
|---|---|---|
| Centreline geometry | arithmetic | `curve_radius_min`, `curve_density` |
| OpenStreetMap — one Overpass call | one request | `speed_limit`, `lanes`, `lane_width`, `lit`, `surface_paved`, `sidewalk_present`, `median_present`, `junction_density`, `access_density`, `ramp_density`, `poi_density`, `building_density` |
| Copernicus DEM GLO-30, ESA WorldCover | COG window reads over HTTPS | `grade_pct`, `landuse_urban` |
| OSM graph centrality, Mapillary detections *(Tier B)* | shortest paths, a free token | `traffic_proxy`, `roadside_object_density` |
| Whatever the client measured *(Tier D)* | client's | any factor — enters as the **first** link in every chain |

**23 factors are declared in the registry. 18 have adapters. On a real corridor 12–14
typically resolve** — the rest are refused on coverage and reported by name with the
coverage that failed. Measured on a short A6 stretch with every source enabled: **14
delivered against 8** when only OSM was asked for.

**And one source that fills no column at all.** The `imagery` check asks Mapillary whether
a vehicle has ever driven the corridor with a camera, and answers in a sentence rather than
a number. It exists because the construction gate reads a *tag*, and a tag is a label
somebody typed — it can be wrong in both directions. The evidence is deliberately
asymmetric: a photograph on the road is strong evidence it is open, no photograph is weak
evidence of anything, because Mapillary's coverage is absent across whole regions and this
product exists for the places with the worst data. A test asserts it never says the road
does not exist.

**Caching is by geography, not by corridor.** The strategic-network query is built from a
half-degree grid cell, so two different roads through the same county produce a
byte-identical query. Measured on two real Cyprus roads: **55.5 s cold, 1.2 s for the next
corridor in the same region.**

---

## 5. The three ladders

The same shape recurs at three levels: *try the best thing, test it honestly, descend when
it fails, and print a receipt.* This repetition is deliberate and it is the system's
signature.

### 5.1 The mode ladder — what the data can support

| Rung | Requires | Fits | Output |
|---|---|---|---|
| **A-full** | ≥ 700 crashes | up to 7 factors + offset | coefficients, intervals |
| **A-reduced** | ≥ 400 crashes | up to 5 factors | coefficients, intervals |
| **A-minimal** | ≥ 100 crashes | up to 3 factors | coefficients, wide intervals |
| **B** | cited weights only | none — scores | **ranked index, never a count** |

**The engine picks. The user cannot.** There is no "use Mode A anyway" flag and no
parameter that creates one. Mode B's result type has **no field** capable of holding a
predicted count — the constraint is structural, not conventional.

Terms are shed **by registry priority**, never by whichever happened to be significant.

**Three things move a factor before priority is applied, and none of them looks at the
outcome.** A factor the road cannot have is excluded outright (`not_applicable_on` — a
motorway has no at-grade junctions). Where two factors measure one construct, only the one
carrying a published weight is fitted. And a factor sitting on a single value across 80% or
more of the units goes to the *back* of the keep order — demoted, never dropped, because a
rung fits up to N terms. Promoting a factor because it correlates with crashes on this road
would be the garden of forking paths, and it is deliberately not done.

### 5.2 The model stack — how the numbers are arrived at

| Rung | Model | State |
|---|---|---|
| 0 | Poisson GLM | **Built** — reference only, never in the client report |
| 1 | Negative Binomial (NB2) GLM | **Built** — the shipped default |
| 2 | Panel-clustered standard errors | **Built** — intervals up to **3.86× wider**; two factors lose significance |
| 3 | GAM spline on geometry | **Built** — a diagnostic that ships *no number*, by type |
| 4 | Bayesian hierarchical NB, random intercept per segment | **Built** — credible intervals, σ_u estimated |
| 4+ | Registry weights as priors | **Built** — the cited weights *are* the prior means, and each factor reports the share of its answer the prior accounts for |
| 4+ | Spatial Leroux CAR field | **Built** — ρ with a credible interval, and a corridor that cannot tell is told so |

**Why rung 2 matters more here than in most panels.** Every factor is *unit-constant* —
curvature, gradient, lane count, every density is a property of a segment, repeated
unchanged down every period. A 120-unit corridor over 24 months has **5,760 rows and 120
independent observations** of each covariate. Rung 1 computes its intervals as though it
had 5,760. Measured against planted truth across 60 synthetic panels: rung 1's 95%
intervals contained the true value **70%** of the time; rung 2's contained it **95%**.

**Rung 4 replaces p-values with credible intervals.** A p-value answers "how surprising
would this data be if the effect were exactly zero", which is nobody's question. A
credible interval answers "where is the effect, given this data". The Bayesian result type
carries **no p-value field at all**, and a test enumerates the forbidden names.

### 5.3 The inference ladder — inside rung 4

Built in **pure Python**: no compiler, no MCMC toolchain. The segment effects are
integrated out by Gauss-Hermite quadrature — one independent 1-D integral per unit — which
reduces a 130-dimensional problem to about ten parameters. That remainder gets a Laplace
approximation, and the importance weights that correct it **are also the honesty meter**.

| Attempt | Check | Outcome |
|---|---|---|
| Laplace + importance sampling | Pareto k̂ ≤ 0.7 **and** ≥ 400 effective draws | 3 factors → ~4 s · A-reduced, 5 factors → ~12 s |
| MCMC | convergence diagnostics | A-full, 8 factors → Laplace refuses, MCMC takes minutes |
| Refuse | — | rather than report an interval it cannot vouch for |

Neither threshold is negotiable to make a fit pass. `--bayes` chooses **how** the numbers
are arrived at, **never** which mode or rung the engine picks — a test asserts the same
panel returns the same mode, rung and factor list either way.

### 5.4 What closed Stage 3 — priors and the spatial field

**The two modes stopped being two systems.** *Mode B's cited weights **are** priors; Mode A
is those priors updated by data.* `--priors` puts the registry's weight for a factor in as
the prior mean, and the run reports the **share of each answer the prior accounts for** —
34% on a 691-crash corridor, 11% on a 5,782-crash one. That number is the point: it says
when you are reading the literature and when you are reading the road, per factor, rather
than leaving it to be assumed.

`expected_sign` enters as a *soft* prior and never as a truncation. Truncating a
coefficient to its expected sign would make the sign guard structurally incapable of ever
firing again — the one diagnostic whose whole job is to notice when the road disagrees with
the literature.

**Neighbouring segments are not independent, and now that is testable.** `--spatial` fits a
Leroux CAR field over the corridor chain by joint Laplace — a corridor is a chain, so the
precision matrix is tridiagonal and the integral stays cheap. It reports ρ with a credible
interval, and on a corridor too short to tell it says exactly that instead of a number.

---

## 6. The honesty layer — rules enforced as code

These are product decisions implemented as code rather than documented as intentions.
They run *across* the whole flow, not at one point in it.

| Rule | Where it bites |
|---|---|
| **No zero-crash rows, no Mode A.** | Gate check 1 — the single most load-bearing rule |
| **The engine picks the mode; the user cannot.** | No override exists anywhere in the API |
| **Mode B cannot produce a count.** | The result type has no field for one |
| **An uncited weight is refused.** | Absent from the index, never silently weighted zero |
| **A weight is a number plus the context it is valid in.** | Facility type, region, severity, crash scope all declared |
| **Where two sources disagree, both are reported.** | Never averaged. HSM prices grade at +0.12; iRAP at +0.49 — different questions, both printed |
| **A crash-type weight only moves its own crash type.** | Mode B decomposes by crash type and recombines with a cited distribution |
| **The same segment measured twelve times is not twelve observations.** | Clustered SEs, printed beside the naive ones with the ratio |
| **Below 20 units the correction is declined, not silently applied.** | The run says how wrong the uncorrected intervals are instead |
| **A contradicted sign is flagged, never quietly reported.** | Six diagnostics fire automatically; verdict states the term is not interpretable as causal |
| **Suppression by a named partner is not a contradiction.** | Classified as suppression only if the factor points the declared way *alone* **and** removing one other term restores it — removal, not a pairwise refit, because a two-term fit drops five terms' confounding and a bystander passes |
| **A coefficient that cannot be told apart from zero has no sign to contradict with.** | Materiality follows significance; the same term at p = 0.95 raised a corridor's worst warning on one side of zero and nothing on the other |
| **A term about a feature the road does not have is not fitted.** | `not_applicable_on` with a *required* reason — an exclusion nobody argued for is indistinguishable from one added to flatter a corridor. An undeclared facility type excludes nothing |
| **Two views of one geometry are not fitted together.** | A `measures` construct fits one member, chosen by a standing rule — prefer the published weight — never by which term fits the road in front of us |
| **A rung's seats do not go to a factor that is flat on this road.** | Above 80% modal share a factor is demoted to the back of the keep order, never dropped, and never promoted on its correlation with the outcome |
| **A diagnostic reports the factor's shape, not the road's.** | CURE under ties is a distribution over 200 seeded orderings, with percentiles and a `tie_sensitive` flag |
| **A check reports the model that shipped, not the one considered.** | The ladder re-runs the collinearity gate on the subset it is about to fit; exactly one result reaches the report and it names its design |
| **A caveat is not printed on a run that never used the thing it qualifies.** | The crash-mix limitation is emitted only where an index exists, and names both road types where the measured facility disagrees |
| **A source outage changes the model, so it is reported like one.** | `source_unavailable` at **material** severity — the same standing as a synthetic corridor, because the claim is *this run is not repeatable* |
| **A client never hangs up on work the server was told it could still be doing.** | The Overpass client reads the timeout out of the query it carries and waits at least that long; a test walks every query the codebase ships |
| **A crash somewhere else is not a failure of the crash table.** | Past 500 m, `not_on_this_corridor` — counted and named, never scored against the snap rate |
| **The verdict grades the assessment, never the road.** | Two runs are not comparable quantities, so a letter grade over them would be invented — and it would be the most quotable number in the document |
| **`region` records where a weight was estimated, not who published it.** | A Norwegian handbook reporting an international meta-analysis is declared `global`; the registry still holds zero Europe-scoped weights, and says so |
| **An adapter cannot declare its own provenance.** | Tier and licence travel from the *registry*, not from the module |
| **A cache never makes a run look fresher than it is.** | Every hit reported with its fetch date; past a fortnight, an instruction to clear |
| **A derived quantity is refused when it is mostly a picture of the analysis window.** | The traffic proxy is tested against a symmetric parabola and withheld above 0.9 |
| **A number is never mapped onto a cited scale by assumption.** | Poles-per-km is *not* converted to the HSM 1–7 roadside hazard rating — that needs a study |
| **Client data outranks open data because the registry says so.** | Reordering the YAML reorders the outcome; no branch in the code prefers it |
| **Agreement is weaker evidence than disagreement.** | Open datasets copy from each other — agreement never *raises* confidence; disagreement lowers it and names the units |
| **A missing tag is not a zero.** | A factor needs half the corridor tagged to be emitted at all |
| **Nothing is silent.** | Every gate result, descent, dropped term and absent column enters the run log |
| **Every result is reproducible.** | The manifest fingerprints engine version, registry contents and input data |
| **A prior is never a truncation.** | `expected_sign` enters as a soft prior; truncating would make the sign guard incapable of firing |
| **Every run says how much of its answer came from the literature.** | Prior share, per factor — 34% on a thin corridor, 11% on a thick one |
| **A corridor that cannot tell is told so.** | The spatial ρ comes back wide, and the run says the corridor cannot resolve it |
| **The limitations page is data, not prose.** | Assembled from what the run did. No flag removes it, and a test tries every way to |
| **The PDF is the report printed, not a second document.** | One React component. There is no template kept in visual sync by hand |
| **A report renders from JSON alone.** | No engine object in scope, so a run stored months ago still renders |
| **A refusal is a result, not an HTTP error.** | 422 names the column and creates no job; a Mode B descent is a **200** carrying its receipts |
| **The mode is on every screen, because it is a layout element.** | A page is a child of its layout and cannot remove it — asserted, and fetched |
| **Every read is scoped to a tenant, with no default.** | The store interface makes the argument impossible to omit; the API makes the header required |

---

## 7. Where we are, stage by stage

| Stage | State | Detail |
|---|---|---|
| **0 — Foundations** | ✅ **Done** | Package layout, registry schema, input contract, transforms |
| **1 — Engine core** | ✅ **Done** | Registry, contract, 9 gates, mode ladder, both modes, sign guard, run log, CLI. Mode B scores from context-aware weights sourced from AASHTO HSM, the Elvik Power Model and iRAP |
| **2 — Geospatial pipeline** | ✅ **Done** | Corridor from OSM, linear referencing, segmentation, panel skeleton, crash snapping, 16 Tier A columns + 2 Tier B factors behind one adapter contract, fusion with per-unit confidence, geographic cache, and a run that knows where it is — the extent lifted from its centreline, so `GET /runs?bbox=` finds it. PostGIS itself is deliberately unbuilt: every spatial question the product asks is four comparisons, and a geometry column earns its extension when the hazard layers ask a real geometric one. **Then rebuilt in nine places by real roads** (2.10): a construction gate, national ref spellings, junction-gap bridging, the crash-distance split, `lane_width`, the imagery second opinion, and an Overpass client that waits as long as its own query asked for. **Two further Tier B factors remain unbuilt:** vision-model inference and the DEM viewshed |
| **3 — Model depth** | ✅ **Done** | Panel-clustered SEs, GAM spline diagnostic, Bayesian random-intercept GLMM with credible intervals, registry weights as priors with a reported prior share, a Leroux spatial field, and out-of-sample validation reported by default. **Hardened by one real motorway** (3.5): CURE under ties, the collinearity check on the design that shipped, a low-variation screen before the rung slices, sign findings graded three ways, and a transform that was the identity function on the range it was used over |
| **4 — Report and PDF** | ✅ **Done** | One React component rendered from `run.json` alone: mode banner, ranking, factors with source/tier/licence/confidence, receipts, SVG figures with no external request, a closing **verdict** on what the assessment is worth, and a limitations page assembled from the run that no flag removes. The PDF is that page printed |
| **5 — Web layer** | 🟡 **Mostly done** | Layering rule as a test (5.0), payload contract frozen and TypeScript generated from it (5.1a), Postgres storage tenant-scoped from the first migration (5.1b), FastAPI with the refusal contract enforced by exception handler (5.1c), an in-process runner (5.1d), adapters fanning out as independently-failable branches and jobs on a Celery queue that separate workers drain — the unit of distribution being a job rather than an adapter, because spreading one assessment's fetches across machines spreads them across caches (5.2a), the report as an importable library (5.3a), a Next.js shell whose banner no route can omit (5.3b), and a map of the corridor over OpenStreetMap where clicking a segment gives the provenance of every number on it (5.3c) — the one screen that fetches from a third party, and it can be switched off — and a hover layer that links the strip, the map and the ranked table without taking the native SVG tooltips away from a reader with no JavaScript (5.3d), a landing flow where a real road goes from a click on a map to a downloaded Mode A report with no reference typed and no bounding box (5.3e), and a front page rebuilt around what running that on real roads revealed — the extent verdict, the weight context, and every working source reachable at last (5.3f). **Steps 5.1, 5.2a and the whole of 5.3 are complete. Outstanding:** cost model and cap (5.2b), per-tenant secrets (5.2c), auth and row-level policies (5.4) |
| **6 — Deploy** | ⬜ **Not started** | Containers, hosting |

**1,108 tests pass, 42 skipped, in about four and a half minutes. `ruff check` clean.**
The 42 are the whole Postgres store, and they stop skipping the moment
`$ROADRISK_DATABASE_URL` points at a database — which CI does on every push, so the backend
a deployment actually uses is not the one that never gets exercised.

`core/` never imports the layers above it — and since 5.0 that is a test rather than a
docstring, checked by parsing the source with `ast` because half the package sits behind
optional extras the suite never installs. It is why the geospatial dependencies are an
optional extra rather than a hard requirement, why GDAL — needed by exactly two adapters —
sits behind its own, and why `pip install roadrisk-panel` still needs neither a database,
a web server nor a JavaScript toolchain.

---

## 8. Evidence — what has actually been run

### Seven real corridors, and what each one broke

**This is the section that changed.** Full accounts, with every measurement and every
mistaken diagnosis left in place beside what replaced it, are in [`TESTS.md`](TESTS.md).

| # | Corridor | Date | Mode | Crashes | What it produced |
|---|---|---|---|---|---|
| 1 | Ελαιώνων (U274), Cyprus | 2026-08-28 | B | none | First real road through the new front page |
| 2 | A10, Cyprus | 2026-08-29 | B | none | **The road is not built** — a construction gate, and `FacilityType.MOTORWAY` |
| 3 | F929, Cyprus | 2026-08-30 | B | none | Confirmed the length and context fixes |
| 4 | **A6 Derby–Buxton, England** | 2026-08-31 | **A** | **284 real** | **The first fitted model.** Curvature at p = 4.7e-07. Two fixes: the crash-distance split and junction-gap bridging |
| 5 | **A82 Lomond–Glen Coe, Scotland** | 2026-08-31 | **A** | **162 real** | **The same method, the opposite answer.** Curvature explains nothing here. Every check passed, 120 of 120 crashes placed |
| 6 | **A3 Paris, France** | 2026-09-04/05 | **A** | **1,403 real** | **The first A-full run.** Eight fixes, and the first clean sheet in the project |
| 7 | **A50 Marseille–Aubagne, France** | 2026-09-07 | **A** | **773 real** | A dead lead killed properly, and four more fixes |

**Fourteen defects, and the shape of them is the argument.** Every one was in code that was
written, tested, reviewed and shipping confident numbers:

| Found by | Defect |
|---|---|
| A6 | A snap check failing at 52.8% and calling a faithful panel unfaithful — because a national extract is mostly somewhere else by construction |
| A6 | Two thirds of the road discarded, because a British A-road restarts across an unreffed roundabout and the bridging distance was tuned on Cyprus |
| A3 | A gate that failed against a design that was never fitted — max VIF 1.8, reported as a failure at 5.4 |
| A3 | A node ceiling counting raw OSM vertices instead of contracted junctions: an 18× overcount, refusing the traffic proxy on exactly the dense urban networks it is most useful on |
| A3 | A rung's seat spent on a factor holding one value across 84% of the corridor |
| A3 | CURE reporting the road's shape rather than the factor's — three unrelated factors drifting at 40.5%, 37.8%, 40.5% off one shared block of ties |
| A3 | `ln1p` on a share of order 1e-3 being the identity function, so the term extrapolated linearly and one fold predicted 1,022 crashes against 311 |
| A3 | Suppression and a genuine specification problem filed under one material heading |
| A3 | A term about at-grade junctions fitted on a grade-separated motorway |
| A3 | The suppression test itself — shipped wrong, testing pairs instead of removals, corrected two commits later |
| A3 | A crash-mix caveat printed on a run that never used it, measured on the wrong kind of road |
| A50 | A source outage changing the specification while still reporting `succeeded` — the same factor at +0.469 and +0.392 on identical inputs |
| A50 | A client hanging up after 90 s on a query it had told the server to spend 180 s on |
| A50 | Two measurements of one geometry fitted together, neither identifiable |
| A3 + A50 | Every wrong sign material, however weak — a corridor's worst warning turning on which side of zero a coin landed |

**Three dead ends, recorded as carefully as the findings.** The presence-flag transform was
built to fix the CURE drift, made every metric worse and was reverted — and that failure is
what revealed the drift was never about the factors. A z-score was fitted to rule out "the
numbers are small" as the explanation for the traffic proxy, and changed nothing, which is
what proved the problem was the *shape*. And a lead on gradient was argued twice in
`TESTS.md` as promising — once as a pooled p = 0.019 described as nearly proven — before a
corridor that could actually test it returned p = 0.702 with a *smaller* standard error.
The three earlier runs had agreed because all three were missing the same block of factors.
**Three broken models agreeing is not corroboration.**

### And before them: two synthetic-crash corridors, deliberately unalike

| | **Cyprus B9** (Troodos) | **Dutch N201** (polder) |
|---|---|---|
| Date | 2026-08-10 | 2026-08-17 |
| Character | windy, mountainous | flat, polder into Amsterdam |
| Input | 69 OSM fragments | 810 vertices |
| Centreline | 25.01 km | 33.50 km |
| Units | 50 | 67 |
| Panel rows | 1,200 | 1,608 |
| Crash snap rate | 99.8% | 84.3% |
| Factors resolved | 12 of 14 attempted | 11 of 13 |
| Mode reached | A | A |

The second corridor was **chosen by measurement, not off a map**: `access_density` and
`ramp_density` had to *separate*, and on N201 they do, at VIF 1.00 / 1.00 — 18 units carry
an access and no ramp, 15 carry a ramp and no access. On B9 they cannot: one unit of fifty
has a ramp anywhere near it.

**The crash data for both roads is synthetic**, and it is stated three times in the run
output. What these two runs validate is the geometry and adapter path, not any road — which
is exactly why the seven above were worth the nine days they cost.

### Measured, not asserted

| Claim | Measurement |
|---|---|
| Clustered intervals are honest | 60 planted panels: naive 70% coverage → clustered **95%** |
| The correction is visible | `access_density` p < 0.0001 → **0.65**; interval **3.86×** wider |
| The cache pays for itself | B9 cold **55.5 s** → E601 same region **1.2 s** |
| The traffic proxy is unstable under its own window | 5/10/20 km margins move the peak unit from 1 → 26 → 19; **reported, and the reason the factor stays uncited** |
| The Bayesian rung is fast enough | A-reduced, 5 factors → **~12 s** in pure Python |
| The spline does not invent bends | A turn must survive resampling by unit — *"the same shape came back on 40 of 40 corridors"* |
| Out-of-sample calibration holds | Spatial CV over contiguous stretches: observed **2,803** vs predicted **2,756**, ratio **1.02** |
| A CURE plot needs its design effect measured | At realistic per-unit heterogeneity, **16–60%** of the curve falls outside naive bounds — *all of it spurious*. Read against the wrong band, every honest model looks broken |
| The prior share is a real number, not a gesture | Same factor, two corridors: **34%** of the answer from the literature on 691 crashes, **11%** on 5,782 |
| The spatial field admits ignorance | Planted ρ = 0.9: **0.89 [0.73, 0.98]** on 80 units; **0.44 [0.05, 0.86]** on 40 — reported as *this corridor cannot tell* |
| The screen and the emailed file are one document | The same run through both entry points: `article.report` **49,929 characters, identical hash** |
| The banner is on every screen, not most | 11 of 11 routes fetched and checked; **11 of 11 fail** when it is taken out of the layout |
| A website did not disturb the product | After the workspace move, `report.html` rebuilt **byte-identical** |
| The same method reaches different answers on different roads | A6: curvature at **p = 4.7e-07**. A82, same country, same crash source, comparable road: **curvature explains nothing**. A3 vs A50: `access_density` p = 8e-07 against 0.53; `speed_limit` 0.95 against 2e-23 |
| A tie-driven CURE excursion is not a finding | 2,000 permutations within ties: `junction_density` reported **0.432** against a median of **0.027**, and corridor order sat at the **100th percentile** of orderings |
| The transform was the problem, not the scale | A z-score control changed calibration 0.674 → **0.656**; changing `ln1p` to `ln` changed it to **1.143** |
| A source outage is a different model, not a slower one | Same road, same 773 crashes, minutes apart: five factors and four, `grade_pct` at **+0.469 and +0.392** — both runs reporting `succeeded` |
| The node ceiling was measuring the wrong quantity | Paris at the refused window: 674,358 raw vertices, **37,935 contracted junctions**, betweenness in **25 s** |
| A finding that survives its own machinery being rebuilt | `access_density` on the A3 across nine specifications: +0.44, +0.33, +0.30, +0.39, +0.40, +0.37, +0.36 — **never once changing sign** |

### Defects the earlier real *geometry* exposed, and what they cost

The fourteen above came from real crashes. These came before them, from real roads with
synthetic crashes, and they are why the geometry path is trusted at all:

- The default resample interval was set by guesswork.
- A test fixture was manufacturing the signal it tested for.
- Corridor contraction was contracting nothing.
- A 92%-tagged factor was being thrown away.
- The first spline **invented a bend** on a panel whose effect was planted linear — the
  worst failure that module could have, because its answer is the one that stops people
  looking. Fixed by reporting only the shape the whole penalty grid agrees on.
- Mapillary took five defects to get working, and **two of them were in the factor's own
  definition**: signage was 54% of the count and is not a struck-object hazard, and a 50 m
  radius was measuring the neighbourhood rather than the verge.

**And two the later stages exposed, both about descriptions drifting apart:**

- `posterior.coefficients` is a mapping, and the hand-written TypeScript had it typed as a
  list. Every coefficient fell back silently to its frequentist interval under a *credible
  interval* heading, and it survived three steps. That defect is the entire argument for
  5.1a: there is now **one** description of the payload, in Python, and the TypeScript is
  projected from it — as is the API envelope the website reads, for the same reason.
- `.gitignore` has carried `runs/` since Stage 0 for output directories. It matches a
  folder of that name at any depth, and it was quietly swallowing `web/shell/app/runs/` —
  the layout carrying the mode banner. Everything built, every test passed, and the files
  would not have been in the commit. Caught by reading `git status`, which is not a
  mechanism, so there is now a test that asks git what it is hiding.

---

## 9. What is not built, and the critical path

### ✅ The item that was the critical path — done

> ~~**A real police crash extract.**~~ **Spent, 2026-08-31 to 2026-09-07.** Seven real
> corridors, four on real police extracts (UK STATS19, French BAAC), fourteen defects
> found, the first fitted model and the first A-full run. §8 has the list. The prediction
> that justified putting this first — that real roads would find what tests could not —
> held, and it is the reason the two items below are now the top of the list rather than
> the third and fourth entries on it.

### 🔴 The critical path now — two items

> **1. A region outside Europe.** All seven corridors are Cypriot, British or French, and
> the call topic asks for at least three regions with region-level comparison. The
> constraint is free crash data with coordinates, not geography.
>
> **2. Hazard layers — flood, fire, storm, snow.** Unstaged, and now the highest-value
> unbuilt work in this repository: the adapter contract and raster windowing already fit
> them exactly, and JRC river flood maps, EFFIS and ERA5 are all free.

### Ordered, after those

| # | Item | Why it is not built |
|---|---|---|
| 1 | **The information-gap experiment** | Rank displacement, predictive degradation and literature share per data condition. The machinery has existed since 3.3b; the experiment was never meaningful on synthetic crashes and now is, on four corridors' worth of real ones |
| 2 | **Primary *and* secondary roads in the same region** | Six of the seven real corridors are primary or motorway. The pipeline has no known problem with secondary roads; nobody has run one with crashes on it |
| 3 | **The branch-level chord** (deliberately unbuilt) | Jobs are on a queue and workers drain it, which is what 5.2a needed. Distributing one assessment's *adapters* is a different thing, and it would spread its fetches across per-machine caches — slower than the threads it replaced. **Waits on 6.2's object storage**, which is the only thing that makes it worth having |
| 4 | **Cost model and spend cap** (5.2b) | Nothing counts spend anywhere. The only cost figure in the repository is the 50–150 USD per corridor recorded against the unbuilt `mapillary_vision`. A cap has to refuse *before* the call, and its refusal is a receipt like any other |
| 5 | **Auth and row-level policies** (5.4a) | `X-Tenant-Id` scopes every read and proves nothing. The storage seam was built for this from the first migration; what is missing is identity and a database that refuses a cross-tenant read on its own |
| 6 | **`mapillary_vision`** | Our own inference on sampled frames. The main cost trap in the pipeline at 50–150 USD of VLM calls per corridor, **and** it needs the poles-to-RHR mapping study before its output means anything |
| 7 | **`dem_viewshed`** | `sight_distance_proxy` by marching the line of sight against terrain. Cheap to attempt; crude by nature — a DEM sees terrain but not vegetation, walls or parked vehicles |
| 8 | **`population_density`** | The one Tier A factor with no working adapter, blocked on *delivery format* not data: WorldPop ignores HTTP `Range` headers and streams the whole file; GHSL ships deflated zip tiles that cannot be windowed |
| 9 | **PostGIS geometry** | Settled rather than pending: a run's extent is four indexed numbers and every spatial question the product asks — *which runs overlap this view* — is four comparisons. A geometry column answers predicates nothing here asks, at the price of an extension between an operator and a working install. **What would change it:** the hazard layers, where *which runs intersect this flood outline* is a real geometric predicate |
| 10 | **Containers and hosting** | Stage 6, and not started |

### Environment constraints worth knowing

PyMC installs but **cannot sample** on the original development machine: no C++ compiler,
so PyTensor falls back to pure Python, and Windows Smart App Control refuses the unsigned
native DLLs that Numba, `nutpie` and JAX would need. Turning that policy off was declined —
it cannot be re-enabled without reinstalling Windows. **The requirement was met in pure
Python instead**, which is why the Bayesian rung integrates the segment effects out by
quadrature rather than sampling them, and why the spatial field is a joint Laplace over a
tridiagonal precision matrix.

**Development moved to WSL2 / Ubuntu on 2026-08-24**, because the same policy blocks every
compiled Python wheel the project depends on — numpy, pandas, statsmodels, pydantic-core.
Nothing about the package changed; the interpreter simply has to live somewhere it is
allowed to run. The JavaScript toolchain moved with it, and rebuilding the report bundle in
WSL produced a file byte-identical to the one built on Windows.

### Open decisions that need a human, not a code change

1. **A licensed AASHTO HSM.** Equations were read from the NCHRP draft of the 2nd edition
   and are double-checked against published worked examples by a test, but HSM2 (2024)
   changed Parts C and D. One afternoon with the book closes it.
2. **Measure operating speed on one corridor.** `speed_limit` carries a permanent caveat
   because the Elvik exponent applies to *operating* speed, not posted limit. One Tier C
   speed pull removes the largest known weakness in the index.
3. **Supply a local crash-type distribution.** The default shares come from HSM Table 10-4
   — Washington State, rural two-lane, 2002–2006. Most national crash databases can
   produce a local split directly. One of the cheapest accuracy improvements available.
4. **Resolve `lanes`.** It is a volume proxy expecting `+` for total crashes, while iRAP
   prices lane count at `−` for head-on-overtaking crashes only. Two mechanisms in one
   column. The fix is separating the exposure role from the risk role, not picking a sign.
5. **European evidence, if anybody can reach it.** The registry holds **zero weights
   estimated in Europe**, so every European corridor — which is all seven of them —
   reaches for North American or global evidence, and every report says so at length. A
   sweep on 2026-09-01 found the evidence exists in quantity and is almost entirely
   unreachable: PRACT catalogued 889 CMFs and 273 accident prediction models on European
   infrastructure and **its repository is 404 on both http and https**. The harvest was
   one weight, from the Norwegian handbook, and it is declared `global` rather than
   `europe` because its own page says the figure pools 47 international studies. Full
   survey in [`docs/EUROPEAN_EVIDENCE.md`](docs/EUROPEAN_EVIDENCE.md). **The honest route
   out remains Mode A**, which does not need a weight at all.

---

## 10. Illustration brief — the figure to draw

Everything below is written to be handed to an illustrator or an image model. Box labels
are given verbatim.

### 10.1 Figure 1 — the master flow

**Format:** landscape, left-to-right, five vertical bands, plus one full-width band along
the bottom. A0 or 16:9. A sixth, narrower band is described at the end — it is what the
system became after the analysis was finished, and it is deliberately drawn smaller.

**Colour key** — use it consistently and put the legend top-right:

| Colour | Meaning |
|---|---|
| **Solid fill, dark outline** | Built and validated |
| **Solid fill, dashed outline** | Partly built |
| **No fill, grey dashed outline** | Not started |
| **Red outline** | A refusal path — where the system stops rather than guesses |

**Band 1 — INPUTS** *(narrow, far left)*

- `Road reference + bounding box` — or a centreline CSV
- `Police crash table (lat, lon, timestamp)` ← mark this **"the one required input"**
- `Client inventory (optional)` ← mark **"Tier D — wins every factor it covers"**
- `Run context: facility type · region · severity`

**Band 2 — BUILD THE PANEL FROM GEOGRAPHY**

- `1. Resolve corridor` — sub-label: *fetch by road ref, stitch fragments, bridge gaps,
  detect divided carriageways*
- `2. Linear reference` — sub-label: *project to UTM, chainage 0 → N km*
- `3. Segment` — sub-label: *fixed-length units, no gaps, no overlaps*
- `4. Panel skeleton` — sub-label: **`unit_id × period × time_slot`, n_crashes = 0**

> ⭐ **Call-out box on step 4, prominent:**
> *"Zero-crash rows are born here — from the road, never from the crash table.
> This is what makes a rate estimable rather than a description."*

**Band 3 — FILL THE PANEL**

Draw as a **fan-out then a fan-in**.

Fan-out — four parallel adapter lanes, each labelled with its tier badge:

| Lane | Badge | Label |
|---|---|---|
| Geometry | **A** | `curvature — pure arithmetic` |
| OpenStreetMap | **A** | `one Overpass call → 11 factors` |
| Rasters | **A** | `Copernicus DEM + ESA WorldCover — COG windows` |
| Compute | **B** | `graph centrality · Mapillary detections` |
| Client | **D** | `whatever the client measured` |

Each lane carries a small tag: **`value + source + tier + licence`**.

Fan-in — one box:

- `5. Fuse` — sub-label: *registry chain decides the winner; agreement scored; **confidence
  tier per factor per unit***

Then, joining from below:

- `6. Snap crashes to units` — sub-label: *every drop counted, with a reason*

> **Call-out on the fan-in:**
> *"An adapter cannot declare its own provenance — tier and licence travel from the
> registry. Client data wins because the registry says so, not because the code does."*

Add a small **cache** icon feeding the OSM and raster lanes, labelled
**`55.5 s cold → 1.2 s for the next corridor in the same region`**.

**Band 4 — DECIDE, THEN FIT**

This is the heart of the figure. Give it the most space.

- `7. Nine validation gates` — list them small: *columns · **zero-crash rows** · exposure ·
  crashes-per-parameter · temporal resolution · snap rate · VIF · variance-to-mean ·
  convergence.* Each returns HARD / SOFT / INFO.

Then draw the **mode ladder as an actual descending staircase**, top-left to
bottom-right, with a red side-arrow off each step labelled with the failed check:

```
A-full      ≥700 crashes · 7 factors  ─┐
   A-reduced   ≥400 crashes · 5 factors  ─┐
      A-minimal   ≥100 crashes · 3 factors  ─┐
         MODE B      cited weights · ranked score, NO COUNT
```

> ⭐ **Call-out beside the staircase, the largest in the figure:**
> *"The engine picks the mode. The user cannot. There is no 'use Mode A anyway' flag,
> and Mode B's result type has no field to put a count in."*

Then two outcome boxes side by side:

- **MODE A — FITTED** → `NB2 GLM + ln(exposure) offset` → `panel-clustered SE` →
  optional `Bayesian GLMM — credible intervals, σ_u`
  *Annotate the clustering arrow:* **`intervals up to 3.86× wider — two factors lose
  significance`**
- **MODE B — SCORED** → `crash-type-decomposed weighted index from cited weights`
  *Annotate:* **`ranked score only — never a predicted count`**

Small linking arrow between them, dashed, labelled:
**`the target: Mode B weights are priors, Mode A is those priors updated by data (not
built)`**

**Band 5 — EXPLAIN, THEN DELIVER**

- `10. Sign guard` — sub-label: *every β against its declared `expected_sign`*
- On contradiction, a branch into five diagnostics: `factor alone` · `with each correlated
  partner` · `correlation matrix` · `leave-one-unit-out` · `GAM spline — hunts the U-shape`
  *Tag the spline:* **`ships no number, by type`**
- `11. Out-of-sample validation` — sub-label: *spatial CV over contiguous stretches · CURE
  against a **measured** design effect · calibration on held-out units*
- `12. Rank units → blackspots`
- `Report: one component` — tag it **`the screen and the PDF are the same document`**
- `Limitations page` — tagged **`assembled from the run · no flag removes it`**

**Band 6 — KEEP IT, SERVE IT, SHOW IT** *(optional; draw narrower than the others)*

Everything here **adds reach, not credibility**, and the figure should not let it look
like part of the analysis. A thin separating rule and a smaller type size say it best.

- `Store the run` — sub-label: *the whole payload as `jsonb`, tenant-scoped from the first
  migration.* Tag: **`re-renders months later without a refit`**
- `Serve it` — sub-label: *`POST /jobs` → 202 · a runner behind it.* Tag in **red outline**:
  **`a refusal is a result — 422 names the column, a Mode B descent is a 200`**
- `The website` — sub-label: *projects · corridors · jobs · runs · the report itself.*
  Tag: **`the same component the emailed file is built from`**
- `The map` — sub-label: *the corridor in Web Mercator over OpenStreetMap, each segment in
  its risk colour, ticks where segments divide, a click giving every number's source.*
  Tag: **`the one thing in the product that fetches from somebody else — screen only, and
  it can be switched off`**
- Draw a small banner strip pinned across the top of the website box, labelled
  **`the mode banner is a layout element — no route can omit it`**

> **Call-out between `The map` and the report in band 5, drawn as a barrier rather than
> an arrow:** *"The screen's map is not the document's. The report draws its corridor as
> inline SVG so that no external image request exists anywhere in it — that is what lets
> a report be emailed. The two are deliberately not consolidated."*

**Bottom band — THE HONESTY LAYER** *(full width, spanning every band above, with small
upward ticks into each)*

Label it: **`Run log · provenance · reproducibility manifest · refusal receipts`**
and beneath: **`Nothing is silent. Degrade loudly.`**

Place five badges along it:

- `Every gate result, descent and dropped term is logged`
- `Every value carries source · tier · licence · confidence to the PDF`
- `Two identical runs fingerprint identically`
- `A cache never makes a run look fresher than it is`
- `Every run says how much of its answer came from the literature`

**Bottom-right corner — a status strip:**

`Stage 0 ✅ · Stage 1 ✅ · Stage 2 ✅ · Stage 3 ✅ · Stage 4 ✅ · Stage 5 🟡 · Stage 6 ⬜
— 1,108 tests passing`

**One thing the figure may now say, and one it still must not flatter.** Where crashes
enter the drawing, the old brief called for a red-outlined tag reading *synthetic on every
corridor run to date*. **That tag comes off** — four corridors have run on real police
extracts. What replaces it is not a boast: tag the crash input
**`7 real corridors · 4 with police data · all of them European`**, because the region
limit is now the honest caveat, and it is the one a diagram would hide next.

### 10.2 Figure 2 — the recurring shape *(optional inset)*

One small diagram, reused three times, showing that the same pattern governs three
different decisions. Draw once and label the three instances:

```
      try the best thing
              ↓
      test it honestly  ──✗──→  descend  ──→  print a receipt
              ↓ ✓
           report it                         (refuse if nothing passes)
```

| Instance | Best thing | The honest test | Floor |
|---|---|---|---|
| **Mode ladder** | A-full | nine gates | Mode B |
| **Model stack** | Bayesian GLMM | convergence | NB2 |
| **Inference ladder** | Laplace | Pareto k̂ ≤ 0.7, ≥400 draws | refuse |

### 10.3 Mermaid source

Renders directly in GitHub, Obsidian, or any Mermaid live editor — useful as a first pass
before the illustration.

```mermaid
flowchart LR
  subgraph IN["① INPUTS"]
    A1["Road ref + bbox<br/><i>or centreline CSV</i>"]
    A2["Police crash table<br/><b>the one required input</b><br/><i>synthetic on every run to date</i>"]
    A3["Client inventory<br/><i>Tier D, optional</i>"]
  end

  subgraph GEO["② BUILD THE PANEL FROM GEOGRAPHY"]
    B1["Resolve corridor<br/><i>by road ref, never by routing</i>"]
    B2["Linear reference<br/><i>UTM, chainage 0 to N km</i>"]
    B3["Segment<br/><i>fixed length, no gaps</i>"]
    B4["PANEL SKELETON<br/><b>unit x period x slot, crashes = 0</b>"]
    B1 --> B2 --> B3 --> B4
  end

  subgraph FILL["③ FILL THE PANEL"]
    C1["Geometry · Tier A"]
    C2["OpenStreetMap · Tier A<br/><i>one call, 11 factors</i>"]
    C3["DEM + WorldCover · Tier A"]
    C4["Graph + Mapillary · Tier B"]
    C5["Client data · Tier D"]
    C6["FUSE<br/><i>registry chain wins;<br/>confidence tier per unit</i>"]
    C7["Snap crashes<br/><i>every drop given a reason</i>"]
    C1 --> C6
    C2 --> C6
    C3 --> C6
    C4 --> C6
    C5 --> C6
    C6 --> C7
  end

  subgraph DECIDE["④ DECIDE, THEN FIT"]
    D1{"NINE GATES<br/><b>zero-crash rows?</b><br/>VIF · dispersion · snap rate"}
    D2["A-full · 700 crashes · 7 factors"]
    D3["A-reduced · 400 · 5"]
    D4["A-minimal · 100 · 3"]
    D5["MODE B<br/><b>ranked score, no count</b>"]
    D6["NB2 GLM + ln exposure offset"]
    D7["Panel-clustered SE<br/><i>up to 3.86x wider</i>"]
    D8["Bayesian GLMM<br/><i>credible intervals, sigma_u</i>"]
    D9["Registry weights as priors<br/><i>prior share reported per factor</i>"]
    D10["Leroux spatial field<br/><i>rho, or 'this corridor cannot tell'</i>"]
    D1 --> D2
    D2 -->|"fails"| D3
    D3 -->|"fails"| D4
    D4 -->|"fails"| D5
    D2 --> D6
    D3 --> D6
    D4 --> D6
    D6 --> D7 --> D8
    D8 -.-> D9
    D8 -.-> D10
  end

  subgraph OUT["⑤ EXPLAIN, THEN DELIVER"]
    E1["SIGN GUARD<br/><i>every beta vs expected_sign</i>"]
    E2["5 diagnostics<br/><i>incl. GAM spline — ships no number</i>"]
    E3["Out-of-sample validation<br/><i>spatial CV · CURE · calibration</i>"]
    E4["Rank units into blackspots"]
    E5["REPORT<br/><i>one component: the screen and the PDF</i>"]
    E6["Limitations page<br/><b>no flag removes it</b>"]
    E1 -->|"contradiction"| E2
    E1 --> E3 --> E4 --> E5 --> E6
  end

  subgraph WEB["⑥ KEEP IT, SERVE IT, SHOW IT — reach, not credibility"]
    F1["Store the run<br/><i>jsonb, tenant-scoped</i>"]
    F2["HTTP API<br/><b>a refusal is a result</b>"]
    F3["The website<br/><i>the same Report component</i>"]
    F4["The map<br/><i>corridor over OSM, segment boundaries,<br/>provenance on click</i>"]
    F1 --> F2 --> F3 --> F4
  end

  A1 --> B1
  A2 --> C7
  A3 --> C5
  B4 --> C6
  C7 --> D1
  D5 --> E4
  D8 --> E1
  E6 --> F1

  LOG["<b>THE HONESTY LAYER</b> — run log · provenance · manifest · refusal receipts<br/><i>Nothing is silent. Degrade loudly.</i>"]
  GEO -.-> LOG
  FILL -.-> LOG
  DECIDE -.-> LOG
  OUT -.-> LOG
  WEB -.-> LOG
```

### 10.4 If only one sentence fits under the figure

> **The panel is built from the road, not from the crashes; the engine — not the user —
> decides what the data can support; and every number carries its source all the way to
> the PDF.**

---

## Appendix — the layout on disk

```
src/roadrisk/
├── contract/                one description of the payload — the bottom of the layer order
├── core/                    plain library — no web, no network, no database
│   ├── registry/            23 declarative factors (schema, loader, factors.yaml)
│   ├── contract.py          the six required columns; exposure derivation
│   ├── context.py           what kind of corridor, and what crashes were counted
│   ├── crashmix.py          how total crashes split by type; the cited default
│   ├── weights.py           weight selection and source-agreement scoring
│   ├── transforms.py        ln / ln1p / identity / zscore, each guarded
│   ├── diagnostics.py       VIF, correlation, dispersion
│   ├── gates.py             the nine validation checks
│   ├── ladder.py            A-full → A-reduced → A-minimal → B; and what loses a seat
│   ├── gam.py               the rung 3 spline
│   ├── models/              Poisson (reference), NB2 (shipped), Bayes, spatial, Mode B index
│   ├── signguard.py         expected_sign: contradiction, suppression, or a coin flip
│   ├── validation.py        spatial CV, CURE under ties, calibration — reported even when bad
│   ├── runlog.py            append-only event log, reproducibility manifest
│   └── engine.py            the one entry point
├── geo/                     geography → panel. Optional extra; core never imports it
│   ├── crs.py               UTM projection — all geometry is metric, never degrees
│   ├── corridor.py          linear referencing and the structural gates
│   ├── segmentation.py      fixed-length units, continuity asserted not assumed
│   ├── panel.py             the skeleton — zero rows exist because road exists
│   ├── snapping.py          crashes onto the corridor; a near miss and an elsewhere kept apart
│   ├── geometry.py          curvature, computed from the centreline alone
│   ├── osm.py               fetch by ref or name; stitch, bridge, gate, refuse a building site
│   ├── adapters/            one factor, one source, one tier, one licence — plus imagery.py,
│   │                        which fills no column and answers in a sentence
│   ├── branches.py          adapters as independently-failable units, and the fan-out
│   ├── cache.py             remember fetches by geography, and report their age
│   └── pipeline.py          the orchestrator
├── report/                  the seam between a finished run and the page that shows it
│   ├── limitations.py       what this run cannot support, read off the run itself
│   ├── pdf.py               print the written report; the browser is a dependency of nothing
│   └── static/index.html    the built report — committed, so installing needs no Node
├── store/                   where runs live once the process that made them has gone
│   ├── base.py              the interface — every read takes a tenant, with no default
│   ├── memory.py            needs no server, and is not a toy — the suite runs on it
│   ├── postgres.py          plain SQL over psycopg3, no ORM
│   └── migrations/          numbered SQL, each recorded with the hash that produced it
├── api/                     the product over HTTP. Optional extra; nothing below imports it
│   ├── errors.py            the refusal contract — one envelope, three distinct outcomes
│   ├── runner.py            the work, the interface, and the seam Celery replaces
│   └── routes/              meta, registry, projects, corridors, jobs, runs
├── demo.py                  synthetic panels for tests and demonstration
├── storecli.py              `roadrisk store` — kept apart so `assess` never needs psycopg
└── cli.py                   mode banner, refusal receipt, descent receipt

web/                         one report, imported three times. Nothing else renders it
├── src/report/              the library — Report, sections, figures, verdict, styles, types
├── src/entries/             the file:// bundle, and mountReport() for a host page
└── shell/                   the website — a map for a front page, routes, two layouts,
                             the banners in them, and the Nominatim proxy
```

**The layering rule:** `core/` never imports the layers above it — `core → demo → geo →
report → api → worker → cli`, downhill only. Since 5.0 that is a test rather than a
docstring, and it has a fourth check for the loophole: `core` imports the package root for
its version string, so the day the root re-exports something from `geo`, importing the
engine imports shapely while every direct import still points downhill. It is why the
geospatial dependencies are an optional extra rather than a hard requirement, and why GDAL
— the heaviest thing this package can depend on, needed by exactly two adapters — sits
behind its own extra that the test suite never installs.

### Commands that demonstrate each claim

```bash
roadrisk demo                                   # end to end on a synthetic corridor
roadrisk demo --crash-rows-only                 # watch Mode A be refused
roadrisk demo --u-shape curve_density           # watch the sign guard and the spline
roadrisk demo --units 40 --periods 12 --bayes   # credible intervals instead of p-values
roadrisk corridor --demo --bayes --report out/  # coordinates to a readable report, one command
roadrisk registry                               # the 23 factors and their weight status
roadrisk serve --tenant                         # the API, and a tenant to use it with

python tools/validate_corridor.py               # the two real corridors
python tools/validate_coverage.py               # proves the clustered intervals honest
python tools/validate_posterior.py              # puts the two rungs side by side
python tools/generate_types.py --check          # the TypeScript still matches the Python
python tools/check_shell.py --tenant …          # every screen still carries the banner
```

```bash
cd web && npm ci && npm run build               # rebuild the committed report bundle
cd web/shell && npm run dev                     # the website, over a running API
```
