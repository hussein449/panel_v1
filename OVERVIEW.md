# The Road Risk Panel — What Exists, and What It Is For

*A single-file account of the whole system: the problem, the flow, what is built,
what is not, and an explicit brief for drawing it as one figure.*

Status as of **2026-08-19**. Sources for every claim here: [`STEPS.md`](STEPS.md) (the
plan), [`IMPLEMENTED.md`](IMPLEMENTED.md) (the build log), [`README.md`](README.md) (the
user-facing description).

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
number can be traced to a named source. The model is the easy part. The product is the
**path** from *a road, a crash table and open data* to *a defensible ranked assessment* —
in places that have no AADT, no road inventory and no survey budget.

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
| No inventory | The registry declares 22 factors; adapters fill what open data can support and **report by name** everything it cannot. |

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
| 1 | **Resolve the corridor** | Fetch by road `ref` from OSM (never by routing — a router returns the *fastest* path and silently leaves the road you asked about). Stitch fragments, bridge gaps, detect divided carriageways, project to UTM, build a linear reference: chainage 0 → N km. | **Built** |
| 2 | **Segment** | Cut into fixed-length units. Chainage continuous and exhaustive, no gaps, no overlaps, trailing runt merged. | **Built** |
| 3 | **Build the panel skeleton** | Cross `unit_id × period × time_slot`. `n_crashes` initialised to **0** everywhere. *This is where zero-crash rows are born — from geography, never from the crash table.* | **Built** |
| 4 | **Fan out the adapters** | One Overpass call along the corridor, two cloud-optimised raster windows, pure geometry, plus optional Tier B compute. Each adapter returns value + source + tier + licence. | **Built** (12 Tier A, 2 Tier B) |
| 5 | **Fuse and score agreement** | One value per factor per unit; the registry's ordered adapter chain decides the winner. Where two sources overlap, score agreement. Emit a **confidence tier per factor per unit**. | **Built** |
| 6 | **Snap the crashes** | Project each crash to the centreline within tolerance; chainage → `unit_id`, timestamp → `period` + `time_slot`. Every drop counted **with a reason**. | **Built** |
| 7 | **Validation gates** | Nine checks before anything is fitted: required columns, **zero-crash rows present**, exposure positive, crashes-per-parameter, temporal resolution, snap rate, VIF, variance-to-mean, convergence. Each returns HARD / SOFT / INFO. | **Built** |
| 8 | **Choose the mode — automatically** | Walk the ladder `A-full → A-reduced → A-minimal → B`, take the highest rung that passes every check. **The user has no override.** Every descent names the failed check and the dropped terms. | **Built** |
| 9 | **Fit or score** | Mode A: NB2 GLM with `ln(exposure)` offset, panel-clustered standard errors, optionally a Bayesian random-intercept GLMM. Mode B: crash-type-decomposed weighted index from cited weights — **ranked score only, never a count**. | **Built** |
| 10 | **Sign guard and diagnostics** | Every coefficient checked against its declared `expected_sign`. On contradiction, auto-run four confounding diagnostics plus a **spline** that hunts the U-shape none of the other four can see. | **Built** |
| 11 | **Validate out-of-sample** | Spatial cross-validation, CURE plots, calibration on held-out units — reported by default, including when bad. | **Not built** (Step 3.4) |
| 12 | **Rank and export** | Rank units, aggregate into blackspots, export an HTML/PDF report carrying method, mode, every factor with source/tier/licence/confidence, dropped terms, and a limitations page that cannot be disabled. | **Not built** (Stage 4) |

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
| **A** | Open, global, no key, pure script | Free | Us, automatically | **12 factors live** |
| **B** | Open, but needs vision models or graph compute | Compute time | Us, with real work | **2 of 4 live** |
| **C** | Free-tier APIs, licence-limited | Free → paid | Us, opt-in only | Slots declared, none wired |
| **D** | Cannot be derived, must be measured | Client's cost | Customer | **Client adapter live** |

**Tier B is the moat.** It is what replaces the survey vehicle.

### What resolves today

| Source | Cost per corridor | Factors |
|---|---|---|
| Centreline geometry | arithmetic | `curve_radius_min`, `curve_density` |
| OpenStreetMap — one Overpass call | one request | `speed_limit`, `lanes`, `lit`, `surface_paved`, `sidewalk_present`, `median_present`, `junction_density`, `access_density`, `ramp_density`, `poi_density`, `building_density` |
| Copernicus DEM GLO-30, ESA WorldCover | COG window reads over HTTPS | `grade_pct`, `landuse_urban` |
| OSM graph centrality, Mapillary detections *(Tier B)* | shortest paths, a free token | `traffic_proxy`, `roadside_object_density` |
| Whatever the client measured *(Tier D)* | client's | any factor — enters as the **first** link in every chain |

**22 factors are declared in the registry. 17 have adapters. On a real corridor 11–12
typically resolve** — the rest are refused on coverage and reported by name with the
coverage that failed.

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

### 5.2 The model stack — how the numbers are arrived at

| Rung | Model | State |
|---|---|---|
| 0 | Poisson GLM | **Built** — reference only, never in the client report |
| 1 | Negative Binomial (NB2) GLM | **Built** — the shipped default |
| 2 | Panel-clustered standard errors | **Built** — intervals up to **3.86× wider**; two factors lose significance |
| 3 | GAM spline on geometry | **Built** — a diagnostic that ships *no number*, by type |
| 4 | Bayesian hierarchical NB, random intercept per segment | **Built** — credible intervals, σ_u estimated |
| 4+ | Spatial CAR/BYM field | **Not built** — see §9 |

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
| **A contradicted sign is flagged, never quietly reported.** | Five diagnostics fire automatically; verdict states the term is not interpretable as causal |
| **An adapter cannot declare its own provenance.** | Tier and licence travel from the *registry*, not from the module |
| **A cache never makes a run look fresher than it is.** | Every hit reported with its fetch date; past a fortnight, an instruction to clear |
| **A derived quantity is refused when it is mostly a picture of the analysis window.** | The traffic proxy is tested against a symmetric parabola and withheld above 0.9 |
| **A number is never mapped onto a cited scale by assumption.** | Poles-per-km is *not* converted to the HSM 1–7 roadside hazard rating — that needs a study |
| **Client data outranks open data because the registry says so.** | Reordering the YAML reorders the outcome; no branch in the code prefers it |
| **Agreement is weaker evidence than disagreement.** | Open datasets copy from each other — agreement never *raises* confidence; disagreement lowers it and names the units |
| **A missing tag is not a zero.** | A factor needs half the corridor tagged to be emitted at all |
| **Nothing is silent.** | Every gate result, descent, dropped term and absent column enters the run log |
| **Every result is reproducible.** | The manifest fingerprints engine version, registry contents and input data |

---

## 7. Where we are, stage by stage

| Stage | State | Detail |
|---|---|---|
| **0 — Foundations** | ✅ **Done** | Package layout, registry schema, input contract, transforms |
| **1 — Engine core** | ✅ **Done** | Registry, contract, 9 gates, mode ladder, both modes, sign guard, run log, CLI. Mode B scores from context-aware weights sourced from AASHTO HSM, the Elvik Power Model and iRAP |
| **2 — Geospatial pipeline** | 🟡 **Nearly done** | Corridor from OSM, linear referencing, segmentation, panel skeleton, crash snapping, 12 Tier A + 2 Tier B factors behind one adapter contract, fusion with per-unit confidence, geographic cache. **Outstanding:** vision-model inference, DEM viewshed, PostGIS persistence |
| **3 — Model depth** | 🟡 **Mostly done** | Panel-clustered SEs, GAM spline diagnostic, Bayesian random-intercept GLMM with credible intervals. **Outstanding:** registry-weights-as-priors, spatial CAR/BYM, out-of-sample validation |
| **4 — Report and PDF** | ⬜ **Not started** | Jinja HTML template, WeasyPrint export, non-disableable limitations page |
| **5 — Web layer** | ⬜ **Not started** | FastAPI, Celery worker, Next.js + MapLibre, accounts and storage |
| **6 — Deploy** | ⬜ **Not started** | Containers, hosting |

**573 tests pass. `ruff check` clean.**

`core/` never imports the layers above it. That rule is why the geospatial dependencies
are an optional extra rather than a hard requirement, and why GDAL — needed by exactly two
of seventeen adapters — sits behind its own extra that the test suite never installs.

---

## 8. Evidence — what has actually been run

### Two real corridors, deliberately unalike

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

**The crash data for both roads is synthetic.** What these runs validate is the geometry
and adapter path, not any road. This is stated three times in the run output. See §9.

### Measured, not asserted

| Claim | Measurement |
|---|---|
| Clustered intervals are honest | 60 planted panels: naive 70% coverage → clustered **95%** |
| The correction is visible | `access_density` p < 0.0001 → **0.65**; interval **3.86×** wider |
| The cache pays for itself | B9 cold **55.5 s** → E601 same region **1.2 s** |
| The traffic proxy is unstable under its own window | 5/10/20 km margins move the peak unit from 1 → 26 → 19; **reported, and the reason the factor stays uncited** |
| The Bayesian rung is fast enough | A-reduced, 5 factors → **~12 s** in pure Python |
| The spline does not invent bends | A turn must survive resampling by unit — *"the same shape came back on 40 of 40 corridors"* |

### Defects the real data exposed, and what they cost

Recorded because they are the argument for validating on real roads at all:

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

---

## 9. What is not built, and the critical path

### 🔴 The critical path — one item

> **A real police crash extract.** Every corridor run so far uses synthetic crashes, which
> validate the geometry and the adapter path and **nothing about any road**. A single real
> extract is worth more than a third corridor.

### Ordered, after that

| # | Item | Why it is not built |
|---|---|---|
| 1 | **Out-of-sample validation** (Step 3.4) | Spatial CV, CURE plots, calibration. The last piece of the credibility path |
| 2 | **The report and its limitations page** (Stage 4) | Nothing structural blocks it; it is the deliverable clients actually receive |
| 3 | **Registry weights as priors** (3.3b) | The unifying idea: *Mode B weights **are** priors; Mode A is those priors updated by data.* `core/weights.py` already does the hard half. **The trap:** `expected_sign` must enter as a *soft* prior — truncating a coefficient to its expected sign would make the sign guard structurally incapable of ever firing again |
| 4 | **Spatial CAR/BYM** (3.3c) | **Blocked in a specific way.** The Bayesian rung is fast because it integrates the random intercepts out — independent 1-D integrals. A CAR field couples neighbours by construction, the integral stops factorising, and the trick evaporates. Three routes: Laplace on the joint latent field (a corridor is a *chain*, so the precision matrix is tridiagonal — cheap); a machine that can run PyMC; or drop it and say so |
| 5 | **`mapillary_vision`** | Our own inference on sampled frames. The main cost trap in the pipeline at 50–150 USD of VLM calls per corridor, **and** it needs the poles-to-RHR mapping study before its output means anything |
| 6 | **`dem_viewshed`** | `sight_distance_proxy` by marching the line of sight against terrain. Cheap to attempt; crude by nature — a DEM sees terrain but not vegetation, walls or parked vehicles |
| 7 | **`population_density`** | The one Tier A factor with no adapter, blocked on *delivery format* not data: WorldPop ignores HTTP `Range` headers and streams the whole file; GHSL ships deflated zip tiles that cannot be windowed |
| 8 | **PostGIS, web layer, deploy** | Deliberately deferred. A corridor fits in memory, the CLI is single-user, and there is no multi-tenant story yet. Building a schema now would be guessing at what the API wants |

### Environment constraints worth knowing

PyMC installs but **cannot sample** on the development machine: no C++ compiler, so
PyTensor falls back to pure Python, and Windows Smart App Control refuses the unsigned
native DLLs that Numba, `nutpie` and JAX would need. Turning that policy off was declined
— it cannot be re-enabled without reinstalling Windows. **The requirement was met in pure
Python instead.** WSL2 would sidestep it without weakening any security setting.

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

---

## 10. Illustration brief — the figure to draw

Everything below is written to be handed to an illustrator or an image model. Box labels
are given verbatim.

### 10.1 Figure 1 — the master flow

**Format:** landscape, left-to-right, five vertical bands, plus one full-width band along
the bottom. A0 or 16:9.

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
- `11. Out-of-sample validation` — **draw as not started**
- `12. Rank units → blackspots`
- `Report: HTML + PDF` — **draw as not started**
- `Limitations page` — **draw as not started**, tagged **`cannot be disabled by config`**

**Bottom band — THE HONESTY LAYER** *(full width, spanning every band above, with small
upward ticks into each)*

Label it: **`Run log · provenance · reproducibility manifest · refusal receipts`**
and beneath: **`Nothing is silent. Degrade loudly.`**

Place four badges along it:

- `Every gate result, descent and dropped term is logged`
- `Every value carries source · tier · licence · confidence to the PDF`
- `Two identical runs fingerprint identically`
- `A cache never makes a run look fresher than it is`

**Bottom-right corner — a status strip:**

`Stage 0 ✅ · Stage 1 ✅ · Stage 2 🟡 · Stage 3 🟡 · Stage 4 ⬜ · Stage 5 ⬜ · Stage 6 ⬜
— 573 tests passing`

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
    A2["Police crash table<br/><b>the one required input</b>"]
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
    D1 --> D2
    D2 -->|"fails"| D3
    D3 -->|"fails"| D4
    D4 -->|"fails"| D5
    D2 --> D6
    D3 --> D6
    D4 --> D6
    D6 --> D7 --> D8
  end

  subgraph OUT["⑤ EXPLAIN, THEN DELIVER"]
    E1["SIGN GUARD<br/><i>every beta vs expected_sign</i>"]
    E2["5 diagnostics<br/><i>incl. GAM spline — ships no number</i>"]
    E3["Out-of-sample validation<br/><b>NOT BUILT</b>"]
    E4["Rank units into blackspots"]
    E5["Report + limitations page<br/><b>NOT BUILT</b>"]
    E1 -->|"contradiction"| E2
    E1 --> E3 --> E4 --> E5
  end

  A1 --> B1
  A2 --> C7
  A3 --> C5
  B4 --> C6
  C7 --> D1
  D5 --> E4
  D8 --> E1

  LOG["<b>THE HONESTY LAYER</b> — run log · provenance · manifest · refusal receipts<br/><i>Nothing is silent. Degrade loudly.</i>"]
  GEO -.-> LOG
  FILL -.-> LOG
  DECIDE -.-> LOG
  OUT -.-> LOG
```

### 10.4 If only one sentence fits under the figure

> **The panel is built from the road, not from the crashes; the engine — not the user —
> decides what the data can support; and every number carries its source all the way to
> the PDF.**

---

## Appendix — the layout on disk

```
src/roadrisk/
├── core/                    plain library — no web, no network, no database
│   ├── registry/            22 declarative factors (schema, loader, factors.yaml)
│   ├── contract.py          the six required columns; exposure derivation
│   ├── context.py           what kind of corridor, and what crashes were counted
│   ├── crashmix.py          how total crashes split by type; the cited default
│   ├── weights.py           weight selection and source-agreement scoring
│   ├── transforms.py        ln / ln1p / identity / zscore, each guarded
│   ├── diagnostics.py       VIF, correlation, dispersion
│   ├── gates.py             the nine validation checks
│   ├── ladder.py            A-full → A-reduced → A-minimal → B
│   ├── gam.py               the rung 3 spline
│   ├── models/              Poisson (reference), NB2 (shipped), Bayes, Mode B index
│   ├── signguard.py         expected_sign enforcement and follow-up diagnostics
│   ├── runlog.py            append-only event log, reproducibility manifest
│   └── engine.py            the one entry point
├── geo/                     geography → panel. Optional extra; core never imports it
│   ├── crs.py               UTM projection — all geometry is metric, never degrees
│   ├── corridor.py          linear referencing and the structural gates
│   ├── segmentation.py      fixed-length units, continuity asserted not assumed
│   ├── panel.py             the skeleton — zero rows exist because road exists
│   ├── snapping.py          crashes onto the corridor, every drop given a reason
│   ├── geometry.py          curvature, computed from the centreline alone
│   ├── osm.py               fetch a corridor by road ref; stitch, bridge, gate
│   ├── adapters/            one factor, one source, one tier, one licence
│   ├── cache.py             remember fetches by geography, and report their age
│   └── pipeline.py          the orchestrator
├── demo.py                  synthetic panels for tests and demonstration
└── cli.py                   mode banner, refusal receipt, descent receipt
```

**The layering rule:** `core/` never imports the layers above it. That is why the
geospatial dependencies are an optional extra rather than a hard requirement, and why GDAL
— the heaviest thing this package can depend on, needed by exactly two adapters — sits
behind its own extra that the test suite never installs.

### Commands that demonstrate each claim

```bash
roadrisk demo                                   # end to end on a synthetic corridor
roadrisk demo --crash-rows-only                 # watch Mode A be refused
roadrisk demo --u-shape curve_density           # watch the sign guard and the spline
roadrisk demo --units 40 --periods 12 --bayes   # credible intervals instead of p-values
roadrisk registry                               # the 22 factors and their weight status
python tools/validate_corridor.py               # the two real corridors
python tools/validate_coverage.py               # proves the clustered intervals honest
python tools/validate_posterior.py              # puts the two rungs side by side
```
