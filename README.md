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
| **Stage 2 — geospatial pipeline** | Corridor resolution from OSM, linear referencing, segmentation, panel skeleton, crash snapping, sixteen Tier A factor columns behind one adapter contract, fusion — client data outranks open data, disagreements are named, every factor carries a confidence tier per unit — and two Tier B factors. Seven real corridors later it also **refuses a road that is not built**, matches a reference by national spelling (`A6`, `A 6`, `A-6` are one road), bridges the roundabouts that used to break a British A-road into thirds, tells a crash that missed the carriageway apart from a crash that was never on this road at all, and offers a **street-level imagery second opinion** on whether anybody has driven the corridor. Vision-model inference and persistence outstanding. |
| **Stage 3 — model depth** | **Complete.** Standard errors now account for the panel: every factor is a property of a segment repeated down every period, so the independent-rows fit was counting one segment dozens of times. Correcting it widens intervals up to 3.9× and takes two factors' significance away. A spline diagnostic hunts the U-shape behind a wrong sign, reporting only the shape the smoothing grid agrees on. And `--bayes` fits a random-intercept GLMM that reports **credible intervals instead of p-values** and estimates how much segments differ from one another — in pure Python, seconds per fit, policing its own approximation on every run. `--priors` then makes the registry's own cited weights the starting belief and reports, per factor, how much of the answer came from the literature rather than from your road. Every Mode A run is then cross-validated over held-out stretches of the corridor — calibration, CURE plots and the optimism of random folds, reported by default and including when they fail. And `--spatial` fits a CAR field over the corridor chain, so neighbouring segments are correlated rather than strangers — reporting how much of the variation is spatial, and saying plainly when the corridor is too short to tell. Since then a real French motorway has hardened the diagnostics themselves: the CURE curve is a **distribution** where a factor has tied values rather than one arbitrary ordering, the collinearity check reports the design that was actually fitted rather than the candidate set, a rung's seats no longer go to a factor that is flat on this road, and a wrong sign is graded by what the estimate is worth — suppression by a named partner, a coefficient that cannot be told apart from zero, and a genuine specification problem are now three different findings. |
| **Stage 4 — report** | **Complete.** Two coordinates in, a report a client can read out. `roadrisk corridor --demo --out run/ --pdf` writes `report.html` — one self-contained file you open by double-clicking, no server and no network — and prints it to a paged PDF with the mode banner on every page. **There is one renderer and it lives in the UI**, so the paper and the screen cannot disagree and Stage 5.3 imports the same component rather than a copy of it. Inside: the ranked segments and the blackspot runs they form, with real chainage; a risk strip and a map of the corridor drawn from the centreline itself; every factor with its source, tier, licence and confidence; what the client owes the people whose data this used; and a limitations page assembled from what the run actually did, which no flag, argument or config removes. It now **ends on a verdict** rather than on a licensing table — what the assessment is worth, what it found, and where to send somebody — with every number read off the sections above rather than recomputed. It grades the assessment, never the road. |
| **Stage 5 — web layer** | **5.1 and 5.3 complete — the product is a website, and the front page is a map.** Find a road, click it, attach a crash CSV, press the button: no reference typed, no bounding box, no project made by hand. Under it: `roadrisk serve`, then `POST /jobs` with `{"demo": true}`, and a finished assessment comes back in about three seconds with no broker, no network and no data; the layering rule — `core` is imported *from*, never *by* — is a test rather than a convention, written before the packages that could break it existed; the payload is a **frozen contract** of ~60 Pydantic models that forbid undeclared fields, with `web/src/report/types.ts` generated from them; runs live in Postgres, tenant-scoped from the first migration, and re-render without a refit; and fourteen HTTP paths carry the rule that **a refusal is a result, not an error** — a panel breaking the input contract is a 422 that creates no job, a run that descended to Mode B is a 200 carrying its receipts, and infrastructure breaking is a job whose status says so, with a cause and never a stack trace. Jobs run in a bounded pool **inside the web process** — a job orphaned by a restart is reclaimed and run again, but durability across machines is Celery, which is not built. Adapters now fan out across threads, and one that fails costs its own factor rather than the corridor. The report is a **library plus two thin entry points**, so the single file you email and the page an app mounts are the same component — verified identical to the character. The map screen says in a number how much road is in the frame, because the zoom decides the corridor, and refuses in words a view too tight to assess. Still to come: real identities and row-level policies rather than a tenant header (5.4a), and a public URL (6.2). |
| Stage 6 — deploy | Not started. |

Full breakdown in [`STEPS.md`](STEPS.md). What has actually been built, and what each
piece does, in [`IMPLEMENTED.md`](IMPLEMENTED.md). Every real road this has been run
against — and the defect each one found — in [`TESTS.md`](TESTS.md). Where the weights
come from, in [`docs/WEIGHTS.md`](docs/WEIGHTS.md); why none of them is European, in
[`docs/EUROPEAN_EVIDENCE.md`](docs/EUROPEAN_EVIDENCE.md).

The two design briefs — one on what the product is, one on what data it eats and how it
runs — are kept out of this repository deliberately. See `.gitignore`.

---

## Install

```bash
uv venv --python 3.12 && uv pip install -e ".[dev]"
```

Python 3.11+. Core has no geospatial or network dependencies — it is a plain library
over a dataframe.

**On Windows, check Smart App Control first.** With it on, Windows blocks unsigned native
binaries, which is every compiled wheel here — numpy, pandas, pydantic-core — and the
failure reads as `An Application Control policy has blocked this file`, not as anything to
do with this package. Signed interpreters do not help: the block lands on the extension
modules, not on `python.exe`. Development moved to WSL2 for this reason on 2026-08-24, and
that is the recommendation — it also makes the `[raster]` extra, which needs GDAL, far
easier to install.

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

`--facility-type motorway` exists so that a motorway can stop being declared as something
else. No weight in the registry is scoped to it, so declaring it admits exactly the
unrestricted weights and nothing more — **which is the point, not a shortcoming.** The
option a reader reaches for instead is `rural_two_lane`, which is not a near miss but a
different road, and it quietly admits the HSM's two-lane-two-way weights: `access_density`
is HSM Eq. 10-17, *"rural two-lane two-way segments"*, and a motorway has no driveways at
all, so the number would be admitted on a premise that is false rather than approximate.
The dropdown on the website says the same thing — this option buys a smaller answer, and
here is why.

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

That takes the panel from two factor columns to sixteen, and `--traffic --mapillary` adds
the two Tier B ones:

| Source | Cost | Factors |
|---|---|---|
| Centreline geometry | arithmetic | `curve_radius_min`, `curve_density` |
| OpenStreetMap, one Overpass call | one request | `speed_limit`, `lanes`, `lane_width`, `lit`, `surface_paved`, `sidewalk_present`, `median_present`, `junction_density`, `access_density`, `ramp_density`, `poi_density`, `building_density` |
| Copernicus DEM, ESA WorldCover | COG windows | `grade_pct`, `landuse_urban` |
| OSM graph centrality, Mapillary *(Tier B)* | shortest paths, a free token | `traffic_proxy`, `roadside_object_density` |

`lane_width` is the newest of them and the one the European literature talks about most —
PRACT's inventory raises lane or carriageway width on 41 of its 238 pages, more than
curvature, gradient or roadside. It is read from `width:lanes` where OSM has it and from
`width ÷ lanes` otherwise, and where only `width` is tagged the unit **reports nothing
rather than assuming two lanes**: assuming would invent the exact quantity the column
exists to measure, silently, on precisely the badly mapped roads this product is for. It
carries no weight — the two figures reachable from the European documents trace to
"pertinent literature" rather than to a named study — so it cannot move a Mode B index,
and Mode A fits it from your crashes the day it is measured.

Each value is printed with the adapter, tier, licence and coverage behind it, and every
factor the data could not support is listed separately with the coverage that failed.
Without the flags the pipeline never touches the network. `--rasters` additionally needs
GDAL, which is quarantined in its own extra:

```bash
pip install "roadrisk-panel[raster]"
```

### Getting a report out of it

```bash
roadrisk corridor --demo --out run/ --pdf
```

`run/report.html` is one self-contained file. No server, no network, no sibling assets:
the run is written *into* the document rather than fetched, because a browser will not
`fetch()` a local file and a corridor assessed offline has to produce a report readable
offline. Open it by double-clicking it, or email it.

`--pdf` prints that same page to A4 — the mode banner and a page number on every sheet,
tables that keep their headers across a break, the risk ramp still in colour. It is the
document *printed*, not a second one rendered, so the paper and the screen cannot
disagree. It needs Chrome or Edge; without one the HTML is unaffected and any browser
can print it by hand.

When the report is all you want, and not the panel and the four CSVs beside it:

```bash
roadrisk corridor --demo --report out/
```

The report ends with a page titled *what this assessment cannot tell you*, assembled
from what the run actually did — the checks that failed, the terms that were dropped,
the factors that were inferred rather than measured, the crashes that never landed on
the road. It takes no argument, it is never empty, and nothing removes it.

### The corridors this has been run against

```bash
python tools/validate_corridor.py --list
python tools/validate_corridor.py          # N201, the second corridor
```

That harness exercises the geometry and adapter path on two roads chosen to be unalike —
Cyprus **B9** through the Troodos (25 km, windy, mountainous) and Dutch **N201** (33.5 km,
flat, polder into the edge of Amsterdam) — with synthetic crashes, so what it validates is
the pipeline rather than any road. N201 was chosen by measurement rather than off a map:
`access_density` and `ramp_density` had to *separate*, and on N201 they do, at VIF 1.00 and
1.00. On B9 they cannot — one unit of fifty has a ramp anywhere near it.

**Seven real corridors have been assessed since — four of them against real police crash
tables — and [`TESTS.md`](TESTS.md) records every one** of them: what came back, what it
meant, and the bug each produced.

| # | Corridor | Mode | Crashes | What it was for |
|---|---|---|---|---|
| 1 | Ελαιώνων (U274), Cyprus | B | none | First real road through the new front page |
| 2 | A10, Cyprus | B | none | Found: **the road is not built** |
| 3 | F929, Cyprus | B | none | Confirmed the length and context fixes |
| 4 | **A6 Derby–Buxton, England** | **A** | 284 real | **First fitted model** — curvature significant at p = 4.7e-07 |
| 5 | **A82 Lomond–Glen Coe, Scotland** | **A** | 162 real | **Same method, opposite answer** — curvature explains nothing |
| 6 | **A3 Paris, France** | **A** | 1,403 real | **First A-full run**; eight fixes; first clean sheet |
| 7 | **A50 Marseille–Aubagne, France** | **A** | 773 real | A dead lead, and the clearest case for Mode A yet |

Three things are worth taking from that table before you read the file.

**Most of the defects this project has fixed were found by a real road, not by a test.**
Fourteen fixes came out of these corridors contradicting themselves — a failed gate on a
model that was never fitted, three unrelated factors drifting at exactly 40%, a fold
predicting 1,022 crashes against 311 observed, one factor fitted at +0.469 and +0.392
minutes apart on identical inputs. None of them was reachable from a synthetic panel,
because a synthetic panel has no ties, no busy mirrors and no motorway.

**Dead ends are recorded as carefully as findings.** Three things were built, measured and
thrown away; the presence-flag transform that was supposed to fix the CURE drift made
every metric worse and was reverted, and it was that failure which showed the drift was
never about the factors at all. A lead on gradient was argued twice in that file as
promising and then killed by a corridor that could actually test it — three earlier runs
agreed because all three were missing the same block of factors, and three broken models
agreeing is not corroboration.

**The A6/A82 and A3/A50 pairs are the argument for Mode A.** Same engine, same country,
same crash source, same road class — and almost nothing agrees. `access_density` is
p = 8e-07 on one and 0.53 on the other; `speed_limit` is 0.95 on one and 2e-23 on the
other. One corridor is a merging problem and the other a speed-and-congestion problem.
Mode B would have applied the same borrowed weight to both and announced the same cause.

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
OSM returns, bridges the gaps at junctions, detects divided roads from their `oneway`
tags, and refuses a fragmented collection rather than handing back half a corridor.

Three things that fetch has learned from real roads:

**A reference is matched by national spelling, not by equality.** OSM writes `A6` in
Britain, `A 6` in France, and some networks hyphenate — a sample of 5,035 referenced ways
in southern Paris carried the space on 100% of them — so every French road used to come
back as *"OSM returned no ways tagged ref='A6'"*, a true sentence that reads as *this road
does not exist*. `A6` now becomes the anchored pattern `^A[ -]?6$`. That is not a fuzzy
match and the guarantee is exactly as strong: it is anchored at both ends, so `A6` still
cannot reach `A66`, `A6b` or `A61`, and every run of letters or digits is escaped. A
*name* stays an exact match, because a name is free text and tolerating separators there
really would be fuzzy.

**A roundabout is not a break in the road.** A British A-road runs into a roundabout and
out the other side; the roundabout is its own way and usually carries no `ref`, so the
road's own ways stop and restart tens of metres apart. The 25 m bridging tuned on Cyprus
B-roads therefore broke every one of them: two thirds of the A6 — 75 pieces, 26.9 km —
was being discarded as "not connected". At 60 m the A82 goes from refused at 50% to
94.1 km, the A66 from refused at 24% to a corridor, and the A6 from 48.0 km to 57.2 km —
185 crashes placed where 150 were before. Only ends are bridged, only between
ways already carrying the same selector, and the fragmentation gate still refuses a
collection that will not assemble into one road.

**A road that is not built is refused at the fetch.** The Cyprus A10 is tagged
`highway=construction` on all 22 of its ways, and the pipeline happily assessed it: 8.53 km,
17 segments, a ranked table and a blackspot list for a motorway nobody has driven on. Every
symptom was reported correctly and separately — 30% centreline coverage, zero of six tag
factors clearing their floor, vertex spacing three times the measurement interval — and
the one sentence explaining all four was never said. It is now checked where the tag is:
all-not-open is refused outright and the message names the tag, while a partly-built road
keeps its open carriageway and warns that the chainage no longer runs the length of the
route.

**And a second opinion on that tag, because a tag is a label somebody typed.** It can be
wrong both ways: a road that opened last month may still read `construction`, and a road
tagged open may have been shut for years. The `imagery` source asks an independent
question — *has a vehicle driven here with a camera, and when* — from Mapillary, which is
CC-BY-SA and already wired into this package for `roadside_object_density`. Not a
commercial map, and the reason is the licence rather than the price: this panel is an
ODbL-derived database, and building or correcting one from a proprietary map is what those
terms prohibit.

**The evidence is asymmetric and the module is built around saying so.** Photographs on
the road are strong evidence it is open — somebody was physically there, in a vehicle, on
a date. *No* photographs are very weak evidence of anything, because Mapillary's coverage
is absent across whole regions and this product exists for the places with the worst data.
So a positive result is a finding, a negative result is an absence of information, and a
test asserts it never says the road does not exist. It can never refuse a corridor either:
a missing token or a busy API becomes the note the answer would have gone in. Switch it on
from the assess page, or pass `"imagery"` in a job's `adapters`.

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

## Keep runs, and serve them

A run has been a directory of files since Stage 2, which is right for one person on one
machine. Two optional extras make it a service instead.

```bash
pip install "roadrisk-panel[store]"          # psycopg
export ROADRISK_DATABASE_URL=postgresql:///roadrisk
roadrisk store init                          # numbered SQL migrations, hashed
roadrisk store new-tenant "acme roads"       # prints the id everything is scoped to
roadrisk store new-project "cyprus"
roadrisk store import run/run.json --project <id>
roadrisk store show <run-id> --report out/   # rendered, not refitted
```

```bash
pip install "roadrisk-panel[api]"            # fastapi + uvicorn
roadrisk serve                               # http://127.0.0.1:8000 · docs at /docs
roadrisk serve --tenant                      # …and a tenant, for the in-memory store
```

Without a database the whole service runs in memory, and `--tenant` is what makes that a
real way to try it: every route that touches a row needs a tenant, and the command that
creates one needs a database. It generates an id, creates the tenant and prints it. With
`$ROADRISK_DATABASE_URL` set the flag is refused, because there `roadrisk store new-tenant`
is the command and the tenant outlives the process.

**Try it in one request.** Open `/docs`, create a project, then post a demo job — a
synthetic 10 km corridor that needs no data, no network and no crash extract:

```bash
curl -X POST localhost:8000/jobs -H "X-Tenant-Id: $TENANT" \
  -H 'Content-Type: application/json' -d '{"project_id":"…","demo":true}'
```

It returns `202` immediately. Poll `GET /jobs/{id}` until it says `succeeded` — about
three seconds — then read `GET /jobs/{id}/run`. **The report that comes back says on its
own face that there is no real road in it**: the flag travels into the payload and the
limitations page leads with it, so a demonstration cannot be mistaken for an assessment
by whoever you send it to.

With `$ROADRISK_DATABASE_URL` set, every request opens a Postgres store; without it the
whole service runs in memory and forgets everything when it stops, which is a real way to
try it. `GET /health` says which, and says two other things plainly:

- **`runner`** — what executes jobs, by name, and the answer changes what you can expect.
  `in-process` is a bounded thread pool inside this process: work in flight does not
  survive a restart, though it is not *lost* — a job left `running` by a stopped process
  is reclaimed the next time the service starts, and one that keeps stopping the process
  is failed with a message rather than looped on. `celery` is a queue that separate
  workers drain, and there work does survive a restart. `runner: null` means nothing is
  listening at all, which is worth telling apart from *busy*.
- **`auth: null`** — `X-Tenant-Id` is required on every route that touches a row, and
  nothing verifies it. It scopes rows; it does not prove who you are. Step 5.4a replaces
  it with real identities and row-level policies in the database. `roadrisk serve` binds
  loopback by default for that reason.

**A refusal is a result, not an HTTP error**, which is the one thing worth knowing before
writing a client:

| Outcome | Response |
|---|---|
| Your panel breaks the input contract | `422`, the column named, and **no job is created** |
| The engine descended to Mode B, dropped terms, refused an unsourced weight | `200` — those are findings the run carries |
| Infrastructure broke | the job's status is `failed`, with a cause. Never a stack trace |

**Jobs can outlive the process that took them.** By default they run in a pool inside the
API, which is right for one machine. Point it at a queue instead and any number of workers
can drain it:

```bash
pip install "roadrisk-panel[worker,store]"
export ROADRISK_BROKER_URL=filesystem:///var/tmp/roadrisk-queue   # or redis://…
roadrisk serve --queue        # accepts jobs, runs none of them
roadrisk worker               # takes them off the queue
```

A worker insists on both a broker and a database, and says so if either is missing: a
queue across processes needs a store across processes, and the in-memory store is one
process's own memory. There is no result backend — the job row **is** the result, and a
second copy of it could disagree.

The unit of distribution is a **job**, not an adapter. Spreading one assessment's fetches
across machines would spread them across caches, and the cache is what turns 55.5 s into
1.2 s for the next corridor in the same region — so that waits for shared object storage,
and [`STEPS.md`](STEPS.md) says so where you would look for it.

**A run knows where it is.** Its bounding box is lifted from the centreline when it is
stored, so a listing can be filtered by place without opening a payload:

```bash
curl "localhost:8000/runs?bbox=34.89,33.20,34.91,33.31" -H "X-Tenant-Id: $TENANT"
```

Four numbers, `south,west,north,east` in degrees. A run with no geometry — a panel you
supplied directly has rows and no road — never matches, and a box that is inside out is a
422 rather than an empty answer. This is deliberately not PostGIS: every spatial question
the product asks is *which runs overlap this view*, which is four comparisons, and an
extension between you and a working install has to earn its place.

`GET /registry` serves `factors.yaml` — every factor, every adapter, its tier, its licence
and what that licence obliges you to do — with the hash of the file it was read from, so
you can tell whether a run was assessed under the registry you are now looking at. The
whole surface is in [`docs/openapi.json`](docs/openapi.json), generated from the app by
`python tools/generate_openapi.py`.

Artefact download is off until you say where artefacts live:

```bash
export ROADRISK_ARTEFACT_ROOT=/srv/roadrisk/artefacts
```

Serving an artefact means opening a path that came out of a database column, so that
variable is an allow-list rather than a convenience, and it has no default.

---

## And a website over it

```bash
cd web && npm ci                             # one install for the report and the app
cd shell
ROADRISK_API_URL=http://127.0.0.1:8000 ROADRISK_TENANT_ID=<the tenant> npm run dev
```

**The front page is a map, and the form is one row under it.** Find a road, click it,
attach a crash CSV if you have one, and press the button — that is the whole flow, and it
is the only screen most people need. Clicking works because the basemap is vector tiles
carrying OSM's own tags, so the click yields the `ref` or the `name` the fetch will go
looking for rather than something the page invented. The **search area is the map view**,
which the page says outright because it is the input that decides how much road gets
assessed.

That layout is the second attempt and the first one is worth recording. It was a 24rem
sidebar of five numbered steps beside a squeezed map, each step carrying several
paragraphs explaining why it mattered — all of it true, most of it worth saying once, and
a narrow column is the worst possible place to put an essay. What a reader got was a page
they scrolled past a map they could barely see, to reach a button at the bottom of an
argument. Now the map takes the full width, the two controls that belong *to* the map
(search, and what you picked) sit on it, and the prose is **folded rather than deleted**.

**The map says how much road is in the frame, in a number.** The bounding box *is* the
viewport, so the zoom level decides how much road gets assessed, and nothing on screen
used to say so. One real run took 1.83 km of a 2.95 km road, produced four segments, and
returned infinity from the collinearity check — not "collinear", *undefined*, because four
observations cannot support ten factors — while the blackspot rule dutifully selected "the
worst 20%" of four segments. All of it was settled before the button was pressed. The
picked road is now measured off the basemap's own geometry and reported as *about N
segments* with a verdict: under ten is refused in words, under twenty is called thin,
above that is fine. It is labelled an estimate wherever it appears, because vector tiles
simplify as you zoom out and the OSM extract decides the real length. The verdict itself
stays on the map, in colour, at all times; only the paragraph explaining how it is
estimated folds away.

**The weight context is on the page, marked recommended.** The assess action used to send
`adapters` and nothing else, so facility type, region and severity fell back to
any/global/all — under which only weights declaring no scope at all are admissible. One
run measured eleven Tier A factors at full coverage and scored on exactly one of them, and
no screen connected those two facts because no screen asked.

**And every working source is reachable from it.** Rasters, the traffic proxy and
Mapillary were all implemented, all tested, and all switchable only from the Advanced job
form, so every run made on the front page reported `grade_pct` absent — one of the eight
factors in the entire registry carrying a cited weight, produced by an adapter that had
been working the whole time. Step 4 now offers all four, each saying what it costs and
what it buys: hills and land use, the traffic proxy, roadside objects, and the imagery
check. Measured on a short A6 stretch with every box ticked, **14 factors delivered
against 8 before**.

The crash file is optional and the page is blunt about what omitting it costs: without a
crash table the engine has nothing to fit and the run can only be Mode B. With one, a
real road goes from a click to a fitted model in about a minute:

```
MODE A — FITTED FROM YOUR DATA · 3 factors · 379 crashes
E904 · 9.37 km · 19 units · 379 of 400 crashes snapped (94.7%)
```

Nothing else is asked. The corridor is cut into 500 m segments, OSM fills the panel, a
project is found or made, and the engine picks its own mode as it always has — there is
still no screen anywhere in this product that offers a way to overrule that.

Everything the old front page did is still here, one click further away: **Advanced** in
the nav is projects, corridors and the ten-field job form, for choosing rather than
starting. `--demo` and the explainer moved to **About**.

Two outside services, and each is switchable off:

| Service | What for | Off |
|---|---|---|
| [OpenFreeMap](https://openfreemap.org) | the basemap, and the tags a click reads | `ROADRISK_MAP_STYLE=none` |
| [Nominatim](https://nominatim.openstreetmap.org) | place search, so finding a road is not a long pan | `ROADRISK_GEOCODER_URL=none` |

Both are proxied through this app rather than called from the browser: Nominatim's terms
require an identifying `User-Agent`, which a page cannot set, and proxying keeps a
viewer's address off somebody else's service for a search they typed here. A test lists
both hosts and fails when a third appears.

**Download the report from any run screen.** A run assessed by this service writes no
files — it is a payload, which is what lets one stored months ago re-render under a
report page that has since been improved — so `GET /runs/{id}/report.html` builds the
document on request, with the same renderer the CLI uses. There is no artefact root to
configure and nothing on a disk to go stale.

Projects, corridors, jobs and runs, with the report itself as one of the screens — the
same `<Report>` component the single-file bundle is built from, so what you read here and
what arrives in somebody's inbox cannot drift apart. Printing the run page produces the
report and only the report; the app's chrome is hidden in `@media print`.

**Point at a segment** on the risk strip, on the corridor map or in the ranked table and
it lights up in all three, with its rank, score and interval in a readout underneath. That
is an enhancement laid over the document, never a replacement for it: every mark keeps the
native SVG `<title>` that a browser shows with no JavaScript running and a screen reader
announces, and a test counts them in the HTML the server sent.

**A run also has a map.** The corridor in Web Mercator over an OpenStreetMap basemap, each
segment in its risk colour with a tick across the road where one segment ends and the next
begins, and a click that says where every number on that segment came from — the value,
the adapter that produced it, its tier, its licence, and whether it was measured there or
carried from the segment next door.

The basemap is the one thing in this product that fetches from somebody else: vector tiles
through [OpenFreeMap](https://openfreemap.org), no key and no account, with the credit its
licence requires shown on the map. Point `$ROADRISK_MAP_STYLE` at another MapLibre style to
use your own, or set it to `none` for a deployment that must make no external request — the
map then draws the corridor on an empty background and everything else works unchanged.

That map is the screen's, and the report keeps its own. The report's corridor is inline
SVG in equirectangular projection so that no external image request exists anywhere in a
document that gets emailed. They are deliberately not consolidated, and a test asserts
that the shipped `report.html` contains neither MapLibre nor a tile URL.

**Two banners, and neither can be taken off a screen.** The root layout carries what this
deployment is — that `X-Tenant-Id` is not authentication, that jobs run inside the API
process and do not survive a restart, that artefact download is off — every line of it read
off `GET /health` rather than written into the page, so it stops saying so when it stops
being true. The run segment's layout carries the *mode*: `A-full`, `B`, the rung, and
whether the corridor was synthetic. A page is a child of its layout and cannot remove it,
which is why the banner is there rather than in each page; `pytest tests/test_shell.py`
asserts the arrangement, and `python tools/check_shell.py` fetches every route and looks
for the banner in the HTML that came back.

Everything works with JavaScript switched off — the forms post to the server, and a
refusal comes back on the page with the column the API named. The one exception is the job
page's automatic refresh, which has a link beside it that does the same thing.

The browser only ever talks to this app, never to the API: the tenant header belongs to a
process you control, so artefact downloads are proxied rather than linked.

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
factor with each other term *removed*, the correlation matrix, leave-one-unit-out — and
the written verdict states plainly that the term is not interpretable as causal.

**Suppression by a named partner is not a contradiction.** Drivers slow for bends, so
speed absorbs curvature, and `curve_density` fitting negative beside `speed_limit` and
positive without it is ordinary behaviour for correlated terms — not the same finding as a
factor that points the wrong way and nothing explains. A contradiction is classified as
suppression only when the factor points the declared way **on its own** — otherwise there
is no correct sign for a partner to have suppressed — and removing exactly one other term
puts it back, which identifies that partner rather than leaving the cause somewhere among
the rest. That second test asks about *removal*, not about pairs: a two-term refit drops
five other terms and their confounding with them, so a bystander passes it as easily as an
absorber does. Suppression is reported at context severity with the partner named;
everything else stays material and says that no single factor accounts for it. The
planted-reversal test is the guard: a genuinely negative factor must survive six drop-one
refits still unexplained, or this becomes a way to explain findings away.

**A coefficient that cannot be told apart from zero has no sign to contradict with.** The
A3 fitted `speed_limit` at +0.032 and, one factor later, at −0.037 — p = 0.95 both times,
noise both times — and only the second was raised as the corridor's most serious warning.
Materiality now follows significance: a firm estimate pointing the wrong way is a
specification problem and stays material, an insignificant one is graded down to a caveat
saying plainly that its sign is not information. Graded down, not hidden — it still says
the corridor did not reproduce an effect the literature expects.

**A term about a feature the road does not have is not fitted.** A motorway is grade
separated by definition: traffic joins and leaves by slip road, and there are no at-grade
junctions on it to count. `junction_density` nevertheless put a material contradiction on
every A3 report, estimated from 9 of 37 segments. A factor may declare
`not_applicable_on` with a required reason — an exclusion nobody wrote an argument for is
indistinguishable from one added to make a corridor look better — and an undeclared
facility type excludes nothing, because guessing the road type to drop a term is the same
class of error the exclusion exists to prevent.

**Two views of one geometry are not fitted together.** `curve_radius_min` and
`curve_density` are measured off the same centreline and correlate at −0.54 to −0.74: a
stretch with tight bends is a stretch with many of them. Asking a model to separate them
over 37 segments produces a sign that flips depending on whether its partner is in the
room. Factors may declare a shared `measures` construct, and only one member is fitted —
chosen by a **standing rule decided in advance**: prefer the factor carrying a published
weight, because a quantity somebody has already related to crashes elsewhere is a better
bet than one nobody has. Choosing instead by which term fits the corridor in front of us
would be selecting on the outcome, and every p-value downstream would be worth less.

**A rung's seats do not go to a factor that is flat on this road.** A-full fits seven
terms and used to choose them by the registry's declared priority alone — an ordering
decided for roads in general. On the A3 that spent a seat on `poi_density`, which holds one
value across 84% of the corridor and fits at p = 0.64. Any factor sitting on one value
across 80% or more of the units now moves to the back of the keep order — *demoted, not
dropped*, because a rung fits up to N terms and removing one outright would sometimes hand
back a smaller model than the data supports. The threshold is 0.8 because 0.7 would have
been wrong: `access_density` is concentrated on one value across 76% of that same corridor
and is its strongest term at p = 5e-9. Concentration is a reason to prefer another factor;
it is never on its own a reason to disbelieve one.

**A held-out factor says which of the four things happened to it.** `missing` is a column
nobody supplied. `not_applicable_here` is a feature the road does not have.
`superseded` is data that was present and usable, set aside because something
better-evidenced measures the same property. `demoted_for_no_variation` is a column that
barely moves. They are four different statements about a run and the payload keeps them
apart, because "the factor is not in the model" is not a finding a reader can act on.

**A diagnostic reports the factor's shape, not the road's.** CURE curves are cumulative
residuals ordered by factor value, and a stable sort leaves units tied at one value in
corridor order — so across a block of ties the statistic is the residual summed *along the
road*, which on a spatially correlated corridor drifts on its own. Three unrelated factors
on the A3 drifted at 40.5%, 37.8% and 40.5% off one shared block of zeros. Permuting within
ties, fewer than 3% of equally valid orderings would have reported a drift at all. The
statistic under ties is therefore a distribution: the median over 200 seeded orderings is
reported with its 5th and 95th percentiles beside it and a `tie_sensitive` flag when that
interval straddles the threshold. A factor with no ties has one ordering and is unaffected,
and the planted-U-shape test still fires — a diagnostic averaged into never firing would
be worse than the bug it replaced.

**A check reports the model that shipped, not the one that was considered.** The
collinearity gate runs before the ladder across every available factor; A-full fits at most
seven of them. The A3 shipped a design with a max VIF of 1.8 while the report announced a
failure at 5.4, which a client reads as a reason to throw out results that are fine. The
ladder now re-runs the check on the subset it is about to fit and that result supersedes
the candidate one, so exactly one reaches the report and it says which design it measured.
Mode B keeps the candidate check, because it scores every available factor and there is no
other design to describe.

**A caveat is not printed on a run that never used the thing it qualifies.** The crash-type
split is consulted only by the weighted index; a fitted model never touches it. The A3 was
Mode A and carried the caveat anyway. And the fallback split is HSM Table 10-4, rural
two-lane two-way — two thirds run-off and head-on, on a road built with no oncoming traffic
to run into. The mix now records the facility it was measured on, the limitation is emitted
only when an index exists, and where the two road types disagree it says so and names both
rather than substituting a number that does not exist.

**A source outage changes the model, so it is reported like one.** A fetch failure never
raises — the pipeline degrades so a busy volunteer server does not cost somebody their
crash data — but degrading silently means a transient outage does not produce an error,
it produces a *different answer*. The A50 was run twice minutes apart on the same road and
the same 773 crashes, fitted five factors and four, and reported `grade_pct` at +0.469 and
+0.392: a fifth of the coefficient, manufactured entirely by which mirror answered. A
failure is now a structured record that travels in the payload and raises a **material**
limitation, on the same argument `synthetic_corridor` is material — everything else on that
page holds if the run is repeated, and this one says the run is not repeatable. It is kept
deliberately apart from a skipped factor: a skip is a claim about the road and says the
same thing tomorrow; this says a server was busy.

**A client never hangs up on work the server was told it could still be doing.** An
Overpass query declares `[timeout:180]`, asking the server to keep working for three
minutes, and the default client's socket timeout was 90 seconds — so it abandoned every
request halfway through, and a 41 km corridor silently lost nine factors to a gap between
two numbers in two files. The client now reads the budget out of the query it is carrying
and waits at least that long, raising a caller's timeout but never lowering it. A test
walks every query the codebase ships and asserts the default client will wait for each of
them, because the mismatch was invisible in both files individually and existed only
between them.

**A crash somewhere else is not a failure of the crash table.** Handing a national extract
to one 48 km corridor is the ordinary way to use this tool, and most of that extract is
elsewhere by construction. The A6 run failed its snap check at 52.8% with *"the panel is
not a faithful record of what happened on this road"* — about a panel that was a faithful
record of the corridor. Measured, the distances were bimodal: p50 of 9 m, p75 of 9.2 km.
Past 500 m a crash is not a near miss, it is somewhere else — GPS error is metres, a dual
carriageway separates by tens, a service road by less than a hundred — so those are
counted and named separately, and the check takes its rate over the crashes that were near
the road at all. Genuinely poor geocoding still fails it: a test supplies 90 near misses
and 10 distant ones and asserts the check fails with the same sentence.

**A verdict grades the assessment, never the road.** The report ends on what the
assessment is worth, what it found and where to send somebody. It does not grade the
corridor, and the module says why: a safety letter would need corridors scored against
each other on a common scale, and this engine fits one road at a time from that road's own
crashes, so a grade over two runs would be invented — and it would be the most quotable
number in the document. Mode B gets its own standing rather than a poor grade of Mode A,
because calling it provisional would imply more of the same evidence promotes it. Only
crashes do. The finding it names is **the most confident term that agrees with the
literature**, not the largest coefficient: each factor enters on its own transformed
scale, so the estimates are not on a common ruler, and a term the sign guard has flagged is
excluded outright however confident, because the guard has already said it is not
interpretable as a cause.

**`region` records where a weight was estimated, not who published it.** The one weight
the European evidence sweep produced comes from the Norwegian handbook
*Trafikksikkerhetshåndboken*, and the registry declares it `global` — because the page
itself says the figure is a literature study pooling 47 international studies. Calling it
European because a Norwegian institute printed it would attach a false context to a true
number, which is the one thing the context fields exist to prevent. So the registry still
holds **zero weights estimated in Europe**, and every European corridor still reaches for
North American or global evidence, which every report says at length. The survey behind
that is [`docs/EUROPEAN_EVIDENCE.md`](docs/EUROPEAN_EVIDENCE.md).

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
├── contract/                the JSON payload as types — the bottom layer, imports nothing
│   ├── assessment.py        the engine's half; corridor.py the geography's
│   ├── run.py               the envelope, and the shape version carried on every run
│   └── jsonsafe.py          Infinity is not JSON, and this is where that is enforced
├── core/                    plain library — no web, no network, no database
│   ├── registry/            declarative factors (schema, loader, factors.yaml)
│   ├── contract.py          the six required columns; exposure derivation
│   ├── context.py           what kind of corridor, and what crashes were counted
│   ├── crashmix.py          how total crashes split by type; the cited default
│   ├── weights.py           weight selection and source-agreement scoring
│   ├── transforms.py        ln / ln1p / identity / zscore, each guarded
│   ├── diagnostics.py       VIF, correlation, dispersion
│   ├── gates.py             the nine validation checks
│   ├── ladder.py            A-full → A-reduced → A-minimal → B; and what loses a seat
│   ├── models/              Poisson (reference), NB2 (shipped), Bayes, CAR, Mode B index
│   ├── validation.py        held-out stretches, calibration, and CURE under ties
│   ├── signguard.py         expected_sign: contradiction, suppression, or a coin flip
│   ├── ranking.py           one ranked table for both modes; blackspots break at gaps
│   ├── runlog.py            append-only event log, reproducibility manifest
│   └── engine.py            the one entry point
├── geo/                     geography → panel. Optional extra; core never imports it
│   ├── crs.py               UTM projection — all geometry is metric, never degrees
│   ├── corridor.py          linear referencing and the structural gates
│   ├── segmentation.py      fixed-length units, continuity asserted not assumed
│   ├── panel.py             the skeleton — zero rows exist because road exists
│   ├── snapping.py          crashes onto the corridor, every drop given a reason
│   ├── geometry.py          curvature, computed from the centreline alone
│   ├── osm.py               fetch by ref or name; stitch, bridge, gate, refuse a building site
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
│   │   ├── imagery.py       has anybody driven this road, and when — a second opinion
│   │   ├── client.py        whatever the client measured — first link in every chain
│   │   └── fusion.py        one value per factor, agreement, confidence per unit
│   ├── branches.py          adapters as independently-failable units, and the fan-out
│   ├── cache.py             remember fetches by geography, and report their age
│   ├── cached.py            the caching wrappers round each network client
│   └── pipeline.py          the orchestrator
├── report/                  the seam between a finished run and the page that shows it
│   ├── limitations.py       what this run cannot support, read off the run itself
│   ├── pdf.py               print the written report; the browser is a dependency of nothing
│   └── static/index.html    the built report — committed, so installing needs no Node
├── store/                   where runs live once the process that made them has gone
│   ├── base.py              the interface — every read takes a tenant, with no default
│   ├── records.py           six tables of scalars around a jsonb payload
│   ├── memory.py            needs no server, and is not a toy — the suite runs on it
│   ├── postgres.py          plain SQL over psycopg3, no ORM
│   └── migrations/          numbered SQL, each recorded with the hash that produced it
├── api/                     the product over HTTP. Optional extra; nothing below imports it
│   ├── errors.py            the refusal contract — one envelope, three distinct outcomes
│   ├── deps.py              a store per request; the tenant seam 5.4a replaces
│   ├── schemas.py           what crosses the wire, and what is reused rather than redescribed
│   ├── runner.py            the work, the interface, and the seam the worker fills
│   └── routes/              meta, registry, projects, corridors, jobs, runs
├── worker/                  jobs that outlive the process that took them. Above `api`
│   ├── app.py               the Celery app, and why the unit is a job and not a branch
│   ├── tasks.py             the one task: two strings, and a row does the rest
│   └── runner.py            the runner `create_app` has taken as an argument since 5.1d
├── demo.py                  synthetic panels for tests and demonstration
├── storecli.py              `roadrisk store` — kept apart so `assess` never needs psycopg
└── cli.py                   mode banner, refusal receipt, descent receipt

web/                         one report, imported three times. Nothing else renders it
├── src/report/              the library — what the bundle, a host page and the app import
│   ├── Report.tsx           the whole report — what a client reads, and what prints
│   ├── sections.tsx         summary, ranking, model, sources, checks, verdict, limits
│   ├── verdict.ts           what the assessment is worth — read off the run, never recomputed
│   ├── figures.tsx          risk strip, corridor map, CURE, calibration, spline — all SVG
│   ├── format.ts            every formatter survives a null, because the payload has them
│   ├── focus.tsx            which segment the reader is pointing at, shared by all three
│   ├── risk.ts              the colour scale, so the map and the document cannot disagree
│   ├── Boundary.tsx         a rendering failure must not become a blank page
│   ├── styles.css           one stylesheet, screen and `@page` alike
│   ├── types.ts             the JSON contract, as TypeScript. Generated, not written
│   └── index.ts             the public surface every entry imports
├── src/entries/
│   ├── standalone.tsx       the file:// bundle: the injected run, or a file picker
│   └── mount.tsx            mountReport(element, run), for a page somebody else owns
└── shell/                   the website. One React with the report, so report.html cannot move
    ├── app/page.tsx         the front door: a map, and one row of controls under it
    ├── app/layout.tsx       the deployment banner — the one thing no route can omit
    ├── app/runs/[runId]/    layout.tsx states the mode; page.tsx mounts <Report>; map/
    ├── app/api/places/      the Nominatim proxy — a viewer's address never leaves this app
    ├── app/…                about, projects, corridors, jobs, registry, the download proxy
    ├── components/          RoadPicker, the banners, the report's mount point, the maps
    └── lib/                 api.ts sets the tenant header, once · measure.ts sizes the frame
                             · geocode.ts searches for a place · wire.ts is generated
```

The page is compiled to a single self-contained HTML file and **committed**, so
installing this package never needs a JavaScript toolchain. Only changing the page does:

```bash
cd web && npm ci && npm run build
```

`npm run build:lib` emits the same report as an importable module for a host page that is
not React, with React left external. That output is *not* committed — nothing on the
Python side consumes it, and neither is the shell's build.

`web/` is one npm workspace, so there is one React that the report and the app both
resolve to — two copies in a document is a broken hooks dispatcher rather than a large
download. It also means the app takes the report's React version rather than the other way
round: adding a website must not change the file `pip install` ships.

`core/` never imports the layers above it. That rule paid for itself in the M51 panel and
carries over unchanged — and it is why the geospatial dependencies are an optional extra
rather than a hard requirement:

```bash
pip install "roadrisk-panel[geo]"      # shapely + pyproj, for the pipeline
pip install "roadrisk-panel[raster]"   # GDAL, for the DEM and land-cover adapters only
pip install "roadrisk-panel[store]"    # psycopg, for keeping runs
pip install "roadrisk-panel[api]"      # fastapi + uvicorn, for serving them
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

**1,108 pass and 42 skip**, in about four and a half minutes.

**The forty-two that skip are the whole Postgres store.** `MemoryStore` and
`PostgresStore` implement one protocol and the conformance suite runs against both — but
only the half that needs no server runs by default, which means the backend a deployment
actually uses is the one that never gets exercised. Point it at a database and they stop
skipping:

```bash
createdb roadrisk
ROADRISK_DATABASE_URL=postgresql:///roadrisk pytest
```

The fixtures migrate the database themselves, so an empty one is all this needs. It costs
about thirteen seconds.

The web side is checked separately, and `npm run build` is a typecheck as well as a build:

```bash
cd web && npm ci && npm run build   # the report: tsc --noEmit, then the bundle
cd shell && npm run lint            # the app: tsc --noEmit
```

If `npm run build` leaves `src/roadrisk/report/static/index.html` modified, the committed
bundle had gone stale — that file is a build artefact of `web/src/report/` that ships
inside the wheel, so that `pip install` needs no JavaScript toolchain. Commit the rebuild.

All of the above runs on every push and every pull request — see
[`.github/workflows/ci.yml`](.github/workflows/ci.yml), which additionally runs the suite
on Python 3.11 as well as 3.12, because `requires-python = ">=3.11"` is a promise and a
promise nothing checks is a wish.

**And none of it is the test that matters most.** A suite proves the code does what it was
written to do; a real corridor is the only thing that shows what it was written to do was
wrong. Seven of them are in [`TESTS.md`](TESTS.md), with the defect each one exposed and
the reasoning that turned out to be mistaken left in place beside what replaced it.
