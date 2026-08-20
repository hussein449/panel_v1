# Modular Road Risk Assessment Panel

A road safety risk assessment tool for corridors that do not have the data the existing
tools require.

Not "a crash model with a web interface". The model is the easy part. The product is the
path from *a road, a police crash table, and open data* to *a defensible, ranked risk
assessment* — in places with no AADT, no road inventory, and no survey budget.

---

## Where this is

| Stage | State |
|---|---|
| **Stage 1 — engine core** | Built. Registry, contract, gates, ladder, both modes, sign guard, run log, CLI. Mode B scores from context-aware weights sourced from the AASHTO HSM, the Elvik Power Model and iRAP. |
| **Stage 2 — geospatial pipeline** | Corridor resolution from OSM, linear referencing, segmentation, panel skeleton, crash snapping, all twelve Tier A factors behind one adapter contract, fusion — client data outranks open data, disagreements are named, every factor carries a confidence tier per unit — and the first two Tier B factors. Vision-model inference and persistence outstanding. |
| **Stage 3 — model depth** | Mostly done. Standard errors now account for the panel: every factor is a property of a segment repeated down every period, so the independent-rows fit was counting one segment dozens of times. Correcting it widens intervals up to 3.9× and takes two factors' significance away. A spline diagnostic hunts the U-shape behind a wrong sign, reporting only the shape the smoothing grid agrees on. And `--bayes` fits a random-intercept GLMM that reports **credible intervals instead of p-values** and estimates how much segments differ from one another — in pure Python, seconds per fit, policing its own approximation on every run. `--priors` then makes the registry's own cited weights the starting belief and reports, per factor, how much of the answer came from the literature rather than from your road. Every Mode A run is then cross-validated over held-out stretches of the corridor — calibration, CURE plots and the optimism of random folds, reported by default and including when they fail. And `--spatial` fits a CAR field over the corridor chain, so neighbouring segments are correlated rather than strangers — reporting how much of the variation is spatial, and saying plainly when the corridor is too short to tell. **Stage 3 is complete.** |
| **Stage 4 — report** | Started. Re-scoped: there is one renderer and it lives in the UI, so the PDF is a print stylesheet over the same page rather than a second template in a second language. **4.1 is done** — the engine and the geography now serialise to two JSON payloads that between them carry everything a report needs, including every factor's source, tier, licence and confidence, the corridor's geometry for the map, and what the client owes the people whose data this used. **4.2 is done** — one ranked table whichever mode produced it, worst segment first, with a confidence interval on every expected count in Mode A and no count at all in Mode B. Bad segments that sit together become blackspots with real chainage extents, and a run breaks wherever the road does. The page itself and the limitations page are 4.3 onward. |
| Stage 5 — web layer | Not started |

Full breakdown in [`STEPS.md`](STEPS.md). What has actually been built, and what each
piece does, in [`IMPLEMENTED.md`](IMPLEMENTED.md).

The two design briefs — one on what the product is, one on what data it eats and how it
runs — are kept out of this repository deliberately. See `.gitignore`.

---

## Install

```bash
uv venv --python 3.12 && uv pip install -e ".[dev]"
```

Python 3.11+. Core has no geospatial or network dependencies — it is a plain library
over a dataframe.

## Try it

```bash
roadrisk demo
```

Generates a synthetic corridor with known coefficients and assesses it end to end. To
watch the engine refuse Mode A on a crash-only panel:

```bash
roadrisk demo --crash-rows-only
```

To watch the sign guard catch a wrong sign and the rung 3 spline explain it — a panel
where curvature is genuinely safest in the middle of its range, so a straight line
through it comes back negative:

```bash
roadrisk demo --u-shape curve_density
```

The spline runs automatically on any contradiction. `--shape FACTOR` runs it on demand,
before there is a reversal to explain. It reports only the shape the smoothing grid
agrees on and only turns that survive resampling the corridor by unit — the first
version chose its penalty by AIC and drew a bend in pure noise.

To get credible intervals instead of p-values, and an estimate of how much segments
differ from one another:

```bash
roadrisk demo --units 40 --periods 12 --bayes
```

A negative-binomial GLMM with a random intercept per segment. It runs in seconds rather
than minutes because the segment effects are integrated out and only the handful of
parameters left is approximated — the INLA strategy — and it **checks its own
approximation on every run**, descending to MCMC or refusing outright rather than
reporting an interval it cannot vouch for. Pure Python: no compiler, no MCMC toolchain.

`--bayes` chooses how the numbers are arrived at, never which mode or rung the engine
picks. A test asserts the same panel returns the same mode, rung and factors either way.

To use the registry's own cited weights as the starting belief, and see how much of
each answer came from them rather than from your road:

```bash
roadrisk assess panel.csv --priors
```

Three numbers per factor — what the literature says, what your corridor says on its own,
and the two combined — with the share attributable to the literature printed beside each
one, and the engine naming which of the three this run designates. On a thin corridor the
published weights steady intervals too wide to act on; on a rich one they fall away to
near nothing, which is the check that they are not doing the work. Off by default.

To see the declared factors and their weight status:

```bash
roadrisk registry
```

To build a panel from a corridor centreline and assess it in one go:

```bash
roadrisk corridor --demo --facility-type rural_two_lane --region middle_east --severity injury
```

To assess a real panel:

```bash
roadrisk assess panel.csv --out runs/corridor-01
```

To run a real corridor — a CSV of ordered `latitude`,`longitude` vertices, plus a crash
table with `latitude`, `longitude` and `period`:

```bash
roadrisk corridor centreline.csv --crashes crashes.csv --out runs/corridor-01
```

Add `--osm` and `--rasters` to fill the panel from open data:

```bash
roadrisk corridor centreline.csv --crashes crashes.csv --osm --rasters
```

That takes the panel from two factor columns to twelve, from three sources:

| Source | Cost | Factors |
|---|---|---|
| Centreline geometry | arithmetic | `curve_radius_min`, `curve_density` |
| OpenStreetMap, one Overpass call | one request | `speed_limit`, `lanes`, `lit`, `surface_paved`, `sidewalk_present`, `median_present`, `junction_density`, `access_density`, `ramp_density`, `poi_density`, `building_density` |
| Copernicus DEM, ESA WorldCover | COG windows | `grade_pct`, `landuse_urban` |
| OSM graph centrality, Mapillary *(Tier B)* | shortest paths, a free token | `traffic_proxy`, `roadside_object_density` |

Each value is printed with the adapter, tier, licence and coverage behind it, and every
factor the data could not support is listed separately with the coverage that failed.
Without the flags the pipeline never touches the network. `--rasters` additionally needs
GDAL, which is quarantined in its own extra:

```bash
pip install "roadrisk-panel[raster]"
```

### The corridors this has been run against

```bash
python tools/validate_corridor.py --list
python tools/validate_corridor.py          # N201, the second corridor
```

Two real roads, deliberately unalike: Cyprus **B9** through the Troodos (25 km, windy,
mountainous) and Dutch **N201** (33.5 km, flat, polder into the edge of Amsterdam). The
second was chosen by measurement rather than off a map — `access_density` and
`ramp_density` had to *separate*, and on N201 they do, at VIF 1.00 and 1.00. On B9 they
cannot: one unit of fifty has a ramp anywhere near it.

Crash data for these roads is synthetic, so what the runs validate is the geometry and
adapter path, not any road. **A real police extract is now worth more than a third
corridor.**

### Making the second corridor cheap

```bash
roadrisk corridor --ref B9 --bbox 34.80,32.80,35.05,33.05 --osm --traffic --cache .cache
```

Remote fetches are remembered by *geography*, not by corridor: the road-network request
is built from a half-degree grid cell, so two different roads through the same county
ask an identical question and the second one never leaves the disk. Measured on two real
Cyprus roads — **55.5 s cold, 1.2 s for the next corridor in the same region.**

The cache never lets a run look fresher than it is. Every hit is reported with the date
of the data it served, and past a fortnight the report tells you to clear it.

### Supplying your own data

Anything you have already measured goes in as a CSV keyed by `unit_id`, one row per unit:

```bash
roadrisk corridor centreline.csv --crashes crashes.csv --osm --client inventory.csv
```

It wins every factor it covers, because the registry declares the client slot first in
the chain — there is no branch in the code that prefers it. And it does not silently
overwrite the open source it beat: where the two disagree, the run names the units.

```
⚠  Sources disagree — speed_limit
   'client_speed_survey' won on registry priority; 'osm_maxspeed' disagrees.
   Compared on 16 unit(s) both measured, agreeing on 13 (81%).
   Units that differ: …-0006, …-0007, …-0008
   One of the two sources is wrong about them, and nothing here can say which.
```

### Getting a centreline

Easiest — let the tool fetch it, by road reference and bounding box:

```bash
roadrisk corridor --ref B9 --bbox 34.80,32.80,35.05,33.05 --crashes crashes.csv
```

Fetching **by reference** rather than routing between two points is deliberate: a router
returns the *fastest* path and will leave the road you asked about without telling you.
`ref="B9"` cannot return anything that is not the B9. The fetcher stitches the fragments
OSM returns, bridges small gaps, detects divided roads from their `oneway` tags, and
refuses a fragmented collection rather than handing back half a corridor.

If you prefer to supply the line yourself, **export it from OpenStreetMap — do not draw
it by hand.** OSM's own vertices are already dense through bends, which is the only place
curvature detail matters, and a hand-drawn line usually is not. The tool prints the full
recipe:

```bash
roadrisk centreline-help
```

In short: run an Overpass query for the road's `ref` at [overpass-turbo.eu](https://overpass-turbo.eu),
export GeoJSON, merge the pieces into one line in QGIS, export the vertices as CSV.

That is the same OSM data the automatic routing step (2.2b) will fetch once it exists —
you are just doing it in a browser until then. If you do trace by hand, keep vertices
dense through bends, never cut a corner, pick one carriageway on a divided road, and do
not double back. The engine measures your vertex spacing and warns if it is too coarse
to trust the curvature.

## Use as a library

```python
from roadrisk.core import assess

assessment = assess(panel)          # panel is a pandas DataFrame
print(assessment.banner)            # MODE A — FITTED FROM YOUR DATA · 7 factors · 2,412 crashes
print(assessment.refusal_receipt)   # populated only when Mode A was refused
```

---

## The rules the code enforces

These are product decisions, implemented as code rather than documented as intentions.

**The engine picks the mode. The user cannot.** There is no "use Mode A anyway" flag and
no parameter that creates one. Given the choice, users select Mode A on data that cannot
support it, and the tool prints confident numbers that are fabricated.

**No zero-crash rows, no Mode A.** A count model built only on crash locations cannot
estimate a rate — it can only redescribe the crash table. This single check prevents the
most common and most damaging misuse of the method.

**Mode B cannot produce a count.** Not by convention — the result type has no field to
put one in. Mode B output can never be dressed in Mode A's language.

**An uncited weight is refused.** Mode B will not score using a weight that carries no
`source`. A number the client cannot trace to a named reference is a liability. An
uncited factor is *absent* from the index, never silently weighted zero, and the report
names it.

**A weight is a number plus the context it is valid in.** Each declares its facility
type, region, crash severity and crash scope. A weight restricted to one facility is
inadmissible on another; a fatal-crash weight never scores an injury panel. A regional
mismatch is allowed but reported, because refusing would leave nothing usable outside
North America. Every weight is computed, not chosen, by
[`tools/derive_weights.py`](tools/derive_weights.py) — see
[`docs/WEIGHTS.md`](docs/WEIGHTS.md).

**Where two sources disagree, both are reported.** Never averaged. HSM prices grade at
+0.12 for total crashes on US rural two-lane roads; iRAP prices it at +0.49 for run-off
and head-on crashes globally. Four times apart and not in conflict — they answer
different questions, so the engine marks them not-comparable and prints both.

**A crash-type weight only moves its own crash type.** Published weights are
crash-type specific — iRAP prices grade for run-off crashes and lighting for
intersection crashes. Mode B scores each crash type separately and combines them with a
cited distribution, so a run-off-only weight is not applied as though it moved every
crash on the road. A weight scoped to *all* crashes still enters every type, so nothing
that was already correct changes.

**The same segment measured twelve times is not twelve observations.** Every factor here
is a property of a segment, repeated unchanged down every period, so a 120-unit corridor
over 24 months carries 5,760 rows and 120 independent observations of each covariate.
Standard errors are clustered by unit to say so, and the report prints the uncorrected
one beside it: on a realistic panel the intervals widen up to 3.9× and two factors lose
their significance. Measured against planted truth, the uncorrected 95% intervals
contained the true value **70%** of the time and the corrected ones **95%**. Where there
are too few units for the correction to be trustworthy it is declined rather than
silently applied, and the run says how wrong the intervals are instead.

**A contradicted sign is flagged, never quietly reported.** Every factor declares an
`expected_sign`. A fitted coefficient pointing the other way triggers the diagnostics
automatically — the factor alone, the factor alongside each correlated partner, the
correlation matrix, leave-one-unit-out — and the written verdict states plainly that the
term is not interpretable as causal.

**An adapter cannot declare its own provenance.** A source module names the registry slot
it fills; the tier and licence attached to its values come from *that declaration*. So no
adapter can promote itself to Tier A or attach a licence the registry never agreed to —
and those are exactly the claims a client relies on.

**A cache never makes a run look fresher than it is.** Every stored fetch records when it
was taken, every hit is reported with that date, and past a fortnight the report stops
describing the age and starts telling you to clear it. A silent cache is the same failure
as a confident number: a result that looks like today's and is not.

**A derived quantity is refused when it is mostly a picture of the analysis window.**
Betweenness centrality is computed over the graph you supply, so a badly chosen window
produces a peak in the middle of the corridor that looks exactly like a town. The
traffic proxy is correlated against that window's own shape and withheld when it matches
— a factor that is really measuring the bounding box is worse than no factor.

**A number is never mapped onto a cited scale by assumption.** Mapillary can count poles
per kilometre; `roadside_hazard_score` is measured on the HSM 1-to-7 roadside hazard
rating. Converting one to the other needs a study, so the adapter refuses and says so on
every run, rather than putting a guess behind a published weight.

**Client data outranks open data because the registry says so, not because the code
does.** A factor declares an ordered chain of adapters and the first one that resolves
wins. There is no branch anywhere that prefers client input; reordering the YAML
reorders the outcome.

**Agreement between sources is weaker evidence than disagreement.** Open datasets copy
from each other, so two of them matching can be an echo rather than a corroboration —
it is reported and never raises confidence. Two of them differing means one is
definitely wrong, so it lowers confidence and the units are named.

**A missing tag is not a zero.** OSM `lit` is absent on most of the target market's
roads. Reading absence as "unlit" would manufacture a lighting effect out of mapper
attention, pointing the direction the registry expects. So a factor needs half the
corridor tagged to be emitted at all; below that it is reported as absent, with the
coverage that failed. An untagged unit takes a neighbour's value only across a short gap,
declares zero coverage of its own, and is counted in the notes.

**Nothing is silent.** Every gate result, descent, dropped term and absent column is
recorded in the run log and travels to the report. Degrade loudly.

**Every result is reproducible.** The run manifest fingerprints the engine version, the
registry contents and the input data. Two identical runs fingerprint identically.

---

## Layout

```
src/roadrisk/
├── core/                    plain library — no web, no network, no database
│   ├── registry/            declarative factors (schema, loader, factors.yaml)
│   ├── contract.py          the six required columns; exposure derivation
│   ├── context.py           what kind of corridor, and what crashes were counted
│   ├── crashmix.py          how total crashes split by type; the cited default
│   ├── weights.py           weight selection and source-agreement scoring
│   ├── transforms.py        ln / ln1p / identity / zscore, each guarded
│   ├── diagnostics.py       VIF, correlation, dispersion
│   ├── gates.py             the nine validation checks
│   ├── ladder.py            A-full → A-reduced → A-minimal → B
│   ├── models/              Poisson (reference), NB2 (shipped), Mode B index
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
│   │   ├── base.py          the contract — provenance read from the registry
│   │   ├── curvature.py     alignment; same maths, provenance depends on the line
│   │   ├── osmdata.py       one Overpass call along the corridor, parsed
│   │   ├── osm_tags.py      speed, lanes, lighting, surface, footway, median
│   │   ├── osm_density.py   junctions, accesses, ramps, POIs, buildings per km
│   │   ├── rasters.py       COG windows over HTTPS — the only GDAL in the package
│   │   ├── sampling.py      stations along the corridor, and beside it
│   │   ├── grade.py         gradient from the DEM, over an error-budget baseline
│   │   ├── landcover.py     built-up share of the roadside, sampled off the line
│   │   ├── graph.py         traffic proxy from betweenness, and the artefact gate
│   │   ├── mapillary.py     roadside fixed objects from pre-extracted detections
│   │   ├── client.py        whatever the client measured — first link in every chain
│   │   └── fusion.py        one value per factor, agreement, confidence per unit
│   ├── cache.py             remember fetches by geography, and report their age
│   ├── cached.py            the caching wrappers round each network client
│   └── pipeline.py          the orchestrator
├── demo.py                  synthetic panels for tests and demonstration
└── cli.py                   mode banner, refusal receipt, descent receipt
```

`core/` never imports the layers above it. That rule paid for itself in the M51 panel and
carries over unchanged — and it is why the geospatial dependencies are an optional extra
rather than a hard requirement:

```bash
pip install "roadrisk-panel[geo]"      # shapely + pyproj, for the pipeline
pip install "roadrisk-panel[raster]"   # GDAL, for the DEM and land-cover adapters only
```

The same rule applies downwards. GDAL is the heaviest thing this package can depend on
and exactly two of twelve factors need it, so it sits behind its own extra — and because
both raster adapters take an injectable sampler, the test suite does not need it either.

## The input contract

Required — the job is rejected without them:

`unit_id` · `period` · `time_slot` · `n_crashes` · `length_km` · `duration_hours`

Exposure is `length_km × duration_hours`, and `ln(exposure)` enters as the model offset.
It is structural; the ladder may never drop it.

Optional — every factor in the registry. Each absent column drops exactly one term, and
the run log records what was lost.

## Tests

```bash
pytest
```
