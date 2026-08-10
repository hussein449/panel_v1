# Implemented

What has actually been built, in the order it was built. Planned work lives in
[`STEPS.md`](STEPS.md); this file only records what exists and works.

---

## 2026-08-10 (latest) — Validated on a real road: Cyprus B9

**Delivered:** the pipeline run end to end on real OSM geometry, and two defects found
by doing so. Also a feasibility answer for step 2.2b.

**Road:** Cyprus **B9**, Limassol up into the Troodos mountains. Chosen because it is
genuinely windy, so curvature has something real to find, and because it is in the
target region rather than a US test fixture.

```
69 way fragments from OSM  ->  linemerge  ->  3 pieces, longest = 99.9% of length
708 vertices, 25.01 km, 50 units, 1,200 panel rows
snap 499/500 (99.8%), projection EPSG:32636
MODE A — FITTED FROM YOUR DATA · 2 factors · 499 crashes
```

### Feasibility answer for 2.2b (automatic corridor resolution)

The jigsaw problem is smaller than feared. `way["ref"="B9"](bbox)` returned 69
fragments, and **shapely's `linemerge` reassembled them into a single line carrying
99.9% of the total length** — unordered and mixed-direction input handled for free.

So the remaining work is not the stitching. It is: choosing between the carriageways of
a divided road, bridging gaps where a way lost its `ref` tag, and trimming to the
requested start and end. Materially less than the "2–3 days" estimated.

### Defect 1 — the default resample interval was set by guesswork

20 m was a guess. Real OSM geometry on this road has a median vertex spacing of
**24.7 m**, so the under-sampled-centreline warning fired on perfectly ordinary data.
A warning that cries wolf on normal input trains people to ignore it.

Default raised to **30 m**, chosen by measuring rather than guessing. The interval
stays *fixed* rather than adapting per corridor, because curvature has to be comparable
between corridors.

### Defect 2 — the test fixture was manufacturing the signal it tested for

The first real run produced `curve_radius_min = −0.4644, p < 0.0001`. Convincing, and
completely spurious.

Crashes were being placed by **vertex index**. Traced centrelines put vertices closer
together through bends, so sampling by index concentrated crashes in curves and
produced a curvature effect out of pure drawing style. Placing them uniformly along
**distance** instead, the coefficient collapsed to **−0.0237, p = 0.69** — correctly
nothing, because the synthetic crashes carry no curvature effect.

Fixed in `geo/demo.py`, and pinned by
`test_the_pipeline_does_not_manufacture_signal`: crashes with no true curvature effect
must not yield a significant curvature coefficient. A pipeline that invents a
relationship from how a road was drawn would be worse than useless.

This is also a live demonstration of the confounding the whole product exists to catch
— found in our own tooling first.

### What the run confirms

- Fetch, stitch, project, segment, snap and assess all work on real geometry.
- Gate check 6 is live: 99.8%, passed.
- Sign guard clean.
- No signal is manufactured from geometry alone.

**256 tests pass**, `ruff check` clean.

---

## 2026-08-10 — Stage 2: the geometry path

**Delivered:** `roadrisk.geo` — coordinates in, contract-valid panel out. The seam
between Stage 2 and Stage 1 is closed: geography produces the panel, the engine judges
it, and neither knows how the other works.

**Verified:** 249 tests pass (51 new), `ruff check` clean.

```bash
roadrisk corridor --demo --facility-type rural_two_lane --region middle_east --severity injury
```

```
demo: 10.84 km in 22 units, 528 panel rows, 772 crashes, 123 zero-crash rows
Snapped   772 of 900 (85.8%)
Dropped   beyond_tolerance 65, missing_coordinates 31, period_not_in_panel 32
🟢 MODE A — FITTED FROM YOUR DATA · 2 factors · 772 crashes
```

### Layering

`geo` imports `core`; `core` never imports `geo`. The geospatial dependencies are an
**optional extra** (`pip install "roadrisk-panel[geo]"`) so the engine stays installable
and runnable with nothing but pandas and statsmodels. Importing `roadrisk.geo` without
them raises a message naming the extra rather than a bare `ModuleNotFoundError`.

### Re-ordered on purpose

PostGIS was step 2.1 and is now 2.9. A 100 km corridor fits in memory comfortably, and
persistence is a Stage 5 concern. Doing the geometry in memory first reached the engine
in one pass instead of stalling behind a migration.

### What was built

- **`crs.py`** — UTM projection. All geometry is metric; doing it in degrees produces
  segment lengths wrong by a latitude-dependent factor, which would poison exposure.
  Public signatures always name `latitude`/`longitude` because positional pairs invite
  the (lat, lon) versus (lon, lat) error.
- **`corridor.py`** — linear referencing and the structural gates. Rejects fewer than
  two distinct points, corridors under 100 m, and vertex sets that collapse. A
  self-intersecting centreline is **warned about, not rejected** — it is legal geometry
  with ambiguous linear referencing near the crossing.
- **`segmentation.py`** — fixed-length units with continuity asserted explicitly rather
  than trusted. A trailing offcut below half the target is merged into the previous
  unit; without that rule a 502 m corridor yields a 2 m unit whose exposure is near
  zero and whose rate, if anything lands on it, is absurd.
- **`panel.py`** — the skeleton. Zero-crash rows exist because road exists.
- **`snapping.py`** — every crash that does not land is counted with a reason. This is
  what finally **activates gate check 6**, which has been reporting "skipped, not
  measured" since it was written.
- **`geometry.py`** — curvature, the first Tier A adapter. Pure computation, no network.
- **`pipeline.py`** — the orchestrator.

### Curvature is verified against known shapes

The circumradius is exact, so it can be tested rather than eyeballed: circles of radius
100 / 500 / 900 / 2000 m are recovered to within 1e-6, and a straight line caps. Curve
*density* counts runs, not bendy samples — a 300 m sweeping bend is one curve, not
fifteen, or the metric would measure sampling rate.

### A real limitation the tests found

The plan was "resample the centreline so curvature does not depend on digitisation".
The test asserting that **failed**, and it was right to.

Resampling removes the dependence on lines traced *more* finely than the measurement
interval — that part works. But it cannot rescue a line traced *coarsely*: the chords
have already cut the corners, and resampling interpolates along them, producing
near-straight runs meeting at artificially sharp joints. Curvature then reads far
tighter than the real road.

So the module measures the source vertex spacing and says so. An under-sampled
centreline gets a prominent warning telling the reader not to trust the number and what
to do about it. The test now asserts both halves — that extra vertices change nothing,
and that an under-sampled line is detected.

### What is not built

- **Routing** (2.2b). `Corridor` takes a centreline that is already resolved — from a
  GPX trace, a shapefile, or a routing engine. Turning two coordinates into a centreline
  constrained to a named road needs the OSM graph.
- **Every other Tier A adapter** — DEM grade, OSM tags, junction/access/ramp density,
  POI, land cover. These need network access and per-source handling.
- **Fusion, Tier B, PostGIS, caching.**

Until the adapters land, a corridor panel carries two factor columns. Both feed
registry factors that already have cited weights, so the loop closes — but Mode B on a
real corridor will stay thin until 2.6 is finished.

**Delivered:** the index no longer flattens crash types into one number. It scores each
crash type separately and combines them with a cited distribution.

**Verified:** 198 tests pass, `ruff check` clean.

### The problem

Published weights are crash-type specific. iRAP prices grade for run-off and head-on
crashes; it prices street lighting for intersection crashes. The index was summing them
into one score, which treats a run-off-only weight as though it moved **every** crash on
the road. That overstates every scoped weight, and it got worse with each iRAP weight
added — the sourcing work was quietly making the flattening error bigger.

### The fix

```
log_score[type] = sum of  w_j * x_j    for weights scoped `type` or `total`
combined        = sum of  share[type] * exp(log_score[type])
row score       = ln(combined)
```

A scoped weight moves only its own bucket and the share dilutes it. With
`run_off_head_on` at 64.3%, a weight contributing +0.8 to that bucket contributes
**+0.55** to the combined score, not +0.8.

**Nothing that was already correct moves.** A `total`-scope weight enters every bucket,
so a registry of only total-scope weights produces *exactly* the score it did before —
asserted by `test_a_total_only_registry_scores_exactly_as_a_flat_sum`. The final `ln`
keeps the result on the Mode A coefficient scale, so the prior/posterior correspondence
survives the split.

### The shares are cited, not invented

`core/crashmix.py` holds the default, built from **AASHTO HSM Table 10-4** (default
distribution by collision type, rural two-lane two-way segments, fatal-and-injury
column, HSIS Washington 2002–2006):

| Bucket | Share |
|---|---|
| `run_off_head_on` | 64.26% |
| `other` | 24.64% |
| `intersection` | 10.00% |
| `pedestrian` | 1.10% |

`CrashMix` validates that shares partition total crashes — missing bucket, negative
share, or a sum that is not 1.0 all raise. The default carries the same regional
transfer problem as any other HSM figure and the engine says so on every run that uses
it. `uniform_mix()` exists for callers with no defensible split who would rather say so
than borrow Washington State's.

### What it looks like

```
Crash-type decomposition — where the risk sits
┌─────────────────┬───────┬────────────┬───────────────────────────┐
│ Crash type      │ Share │ Mean score │ Terms entering it         │
├─────────────────┼───────┼────────────┼───────────────────────────┤
│ run_off_head_on │ 64.3% │    +7.8101 │ 3 (grade_pct scoped here) │
│ intersection    │ 10.0% │    +7.2417 │ 3 (lit scoped here)       │
│ pedestrian      │  1.1% │    +7.3127 │ 2 (all total-scope)       │
│ other           │ 24.6% │    +7.3127 │ 2 (all total-scope)       │
└─────────────────┴───────┴────────────┴───────────────────────────┘
```

The ranking gained a score column per crash type, so a bad unit can be read for **which**
problem it has. A run-off problem and an intersection problem call for different
countermeasures; a single combined number hides which one it is. The "no counts"
invariant is unchanged — the test now asserts the invariant properly rather than a fixed
column list.

### What this unblocks

The four attributes rejected from the iRAP Guide were rejected partly *because* the model
was flattened. With buckets:

- **Number of lanes** now has somewhere to go — iRAP's factor is head-on-overtaking only.
  It still needs `expected_sign` resolved first: our `lanes` is a volume proxy expecting
  `+` for total crashes, iRAP's is `−` for one crash type. Those are two different
  mechanisms in one column, which is the composite-masking trap the brief warns about.
  Splitting exposure from risk is the real fix, and it is not a five-minute change.
- **Median type** and **intersection type** remain blocked on their own issues
  (traversability normalisation; per-junction rather than per-km), not on the flattening.

### Cost

Every scoped weight is now weaker than it was, because it is no longer being
over-applied. Absolute scores shift; the *ranking* is what Mode B outputs and it moves
only where the flattening was actually distorting it — which is the point.

**Delivered:** the iRAP Methodology Reference Guide v3.10 was obtained and worked
through. Four new weights, and the region-transfer flag largely disappears outside
North America.

**Verified:** 178 tests pass, `ruff check` clean.

| | Before | After |
|---|---|---|
| Weights | 10 | **13** |
| Sourced factors | 7 | **8** |
| **Global** weights | 4 | **8** |

New: `curve_radius_min` (iRAP, −0.7232), `surface_paved` (iRAP, −1.0986, previously
uncited entirely), `lit` (iRAP, −0.1398). `grade_pct`'s citation upgraded from a
second-hand fact sheet to the Guide itself.

### The effect on a non-US corridor

| Factor | Europe — before | Europe — after |
|---|---|---|
| `grade_pct` | +0.4863 iRAP | +0.4863 iRAP |
| `lit` | −0.0817 HSM ⚠ | **−0.1398 iRAP** |
| `access_density` | +0.1658 HSM ⚠ | +0.1658 HSM ⚠ |
| `speed_limit` | +1.6 Elvik | +1.6 Elvik |

Three ⚠ down to one. `access_density` is the only factor in this panel still reaching
for American evidence.

### Curvature was the prize

The Guide publishes curvature as four categories — 1.0 / 1.8 / 3.5 / 6.0 — **and gives
the radius range each corresponds to** (>900 m, 500–900, 200–500, 0–200). That is what
makes a categorical attribute convertible to a continuous weight at all. It also fits
better than the HSM equivalent: R² 0.938 against 0.878, and unlike the HSM weight it
does not depend on segment length, so it is not tied to the segmentation.

### Four attributes examined and deliberately not used

Recorded in `docs/WEIGHTS.md` so nobody re-treads it:

- **Sight distance** — binary adequate/poor at intersections; our factor is continuous
  metres. No published threshold to map between them, so any mapping would be invented.
- **Number of lanes** — head-on-overtaking only, where more lanes means *less* risk
  (1 lane 1.00 → 2 lanes 0.02). Our `lanes` is a volume proxy for total crashes and
  expects the opposite sign. The `expected_sign` validator would have rejected it, and
  correctly.
- **Median type** — 0–100 traversability values, one multiplicand of the Star Rating
  Score rather than a CMF. Needs the surrounding SRS normalisation. Best remaining
  candidate.
- **Intersection type** — per-intersection factors, not per-km density. Confirms why
  `junction_density` has been hard to source all along.

### One finding for the report

The Guide states iRAP uses the **same** risk factors for posted speed limit and
85th-percentile operating speed, defaulting to `max()` of the two. That does not remove
our posted-speed caveat — the Elvik exponent is still an operating-speed quantity, and
taking a maximum is not substitution — but it shows a respected global methodology
treating posted limit as a legitimate input to a speed risk curve.

### Housekeeping

`references/` is gitignored. The Guide is a licensed document: read it, derive from it,
cite it — never redistribute it, least of all from a public repository.

---

## 2026-08-10 — Region drives source selection

**Delivered:** the corridor's region now picks which body of evidence is used, instead
of merely annotating the choice after the fact.

**Verified:** 173 tests pass, `ruff check` clean.

### The bug this fixed

Region was recorded and ranked, but as a flat exact/not-exact test. On a European
corridor a **global** weight and a **North American** weight therefore tied, and the
family preference order broke the tie arbitrarily. European roads were one coin-flip
away from being scored on US rural two-lane evidence while a global source sat unused.

`region_distance()` replaces it with three tiers — local (0), global (1), another named
region (2) — so global evidence always beats foreign evidence, and local always wins.

### And a reordering

Region is now the **first** ranking dimension, ahead of facility specificity. Facility
mismatch is already handled by admissibility, so that dimension only separates "exact"
from "unrestricted", and unrestricted is not wrong — merely less specific. Region
transfer is the largest error source in Mode B, so it wins.

The effect, same panel assessed as a rural two-lane road in three places:

| Factor | Europe | North America | Middle East |
|---|---|---|---|
| `grade_pct` | **+0.4863** iRAP | **+0.1212** HSM | **+0.4863** iRAP |
| `access_density` | +0.1658 HSM ⚠ | +0.1658 HSM | +0.1658 HSM ⚠ |
| `lit` | −0.0817 HSM ⚠ | −0.0817 HSM | −0.0817 HSM ⚠ |
| `speed_limit` | +1.6 Elvik | +1.6 Elvik | +1.6 Elvik |

A Cyprus corridor now takes the global grade weight, not the American one. Where no
local or global source exists the American weight is still used — dropping the term
would be worse — but every reach carries a `region_transfer` concern naming both
regions and saying what would remove it.

Region granularity, not country: published weights are estimated on regional datasets,
never on "Cyprus". Stage 2 will derive the region from the corridor's admin boundary
automatically — the GADM and OSM-relation adapters are already declared for it.

Four regions added for the target market: `asia`, `africa`, `middle_east`,
`latin_america`.

### Why this makes the iRAP set worth more

Every ⚠ above is a factor with no local *or* global source. Each global weight added
removes one from every non-US run. That is now the clearest argument for completing the
iRAP sourcing.

---

## 2026-08-10 (earlier) — Weights become context-aware; the caveats close

**Delivered:** the three caveats flagged in the previous entry, fixed at their shared
root cause rather than individually. A weight is no longer a bare number with a
citation; it declares the context it is valid in, and the engine picks accordingly.

**Verified:** 166 tests pass, `ruff check` clean, and the two demo runs below differ in
exactly the intended way.

### The root cause

All three caveats — draft-text provenance, the posted-versus-operating speed exponent,
and US-rural-two-lane transfer — were symptoms of one gap: **nothing recorded what
context a weight was valid in.** So US rural two-lane injury-crash coefficients were
applied to any corridor anywhere, silently.

Each weight now declares `family`, `facility_type`, `region`, `severity`, `scope`,
`assumes` and `caveat`. `Factor.default_weight` is gone; `Factor.weights` is a list.
The loader raises a named migration error on the old schema rather than letting
pydantic produce a riddle.

### Selection, and what it refuses

Admissibility is strict where the wrong weight is a *correctness* error: a weight
restricted to one facility type is inadmissible on another, and a fatal-crash weight
never scores an injury panel. Region is deliberately **not** a filter — filtering on it
would leave almost nothing admissible outside North America, so a regional mismatch is
recorded as a concern and surfaced instead. That is the transfer problem stated out
loud rather than hidden or used as an excuse to refuse.

Visible consequence, and the verification the plan asked for:

```
roadrisk demo --crash-rows-only                                    → 1 term
roadrisk demo --crash-rows-only --facility-type rural_two_lane \
              --region north_america --severity injury             → 4 terms
```

An undeclared run admits only unrestricted weights. The engine does not guess what kind
of road it was handed.

### Agreement — the caveat turned into the differentiator

Where two sources cover one factor, the engine reports how far apart they are and never
averages them. `grade_pct` is the worked example: HSM says **+0.12** for total crashes
on US rural two-lane roads, iRAP says **+0.49** for run-off and head-on crashes
globally. Four times apart, and **not in conflict** — they answer different questions.
The engine marks them not-comparable on `scope` and prints both.

Adding `CrashScope` was the non-obvious part. Without it a naive agreement score would
have compared a total-crash weight against a run-off-only weight and reported a
meaningless 0.25.

### Caveat 2, fixed by splitting the factor

`operating_speed_85` is now a distinct registry factor. The Elvik exponents are
methodologically correct there and carry **no caveat at all**. On `speed_limit` they
carry a permanent one, surfaced on every run. Both are severity-tagged — 1.6 injury,
4.1 fatal — and the engine cannot apply one to the other's panel.

Deflating the posted weight was considered and rejected: the 25–50% transfer figures in
the literature are *before-after*, and Mode B is *cross-sectional*. Inventing a transfer
coefficient would have been worse than declaring the limitation.

### Caveat 1, narrowed but not closed

`tests/test_published_equations.py` writes each HSM equation out a second time,
independently of the derivation script, and asserts the worked-example answer the
source publishes — RHR 4 → 1.07, DD 6 @ AADT 10,000 → 1.01, curve 0.1 mi / 1,200 ft →
1.43. A transcription error can no longer pass silently.

That is not the same as checking the book, and **HSM 2nd edition (2024) is published
and changed Parts C and D**. Closing this needs a licensed copy. It stays on the
open-decisions list.

### Assumption checks

`curve_radius_min` declares `segment_length_km: 0.5`; `access_density` declares
`reference_aadt: 10000`. The engine compares them against the actual run and warns
above 25% deviation. `segment_length_km` is **measured** from the panel, not declared,
so the check cannot be gamed.

### What I could not get

iRAP publishes Road Attribute Risk Factor fact sheets per attribute, and they are the
right source for this product — global, and cross-sectional by construction, which is
what Mode B actually does. Only **grade** was retrievable; the consolidated Methodology
Reference Guide v3.10 sits behind free SSO registration.

So iRAP contributes one weight instead of the five or six it could. Completing that set
is the highest-value next step for Mode B and needs one free registration.

### Note on an unreachable branch

`assess_agreement` scores a sign conflict at zero and flags it. A registry cannot reach
that path — the `expected_sign` validator rejects a contradicting source at load. It is
kept as defence in depth, tested by constructing the selection directly, and the
docstring says so rather than leaving a reader to wonder.

---

## 2026-08-10 — Mode B weights sourced; Mode B now scores

**Delivered:** six of twenty registry factors now carry weights derived from published
crash modification factors, so Mode B produces a ranking instead of refusing. Full
sourcing, every equation verbatim and every assumption named, in
[`docs/WEIGHTS.md`](docs/WEIGHTS.md).

**Verified:** 120 tests pass, `ruff check` clean, `roadrisk demo --crash-rows-only` now
scores 120 units on four cited terms.

| Factor | Transform | Weight | Fit | Source |
|---|---|---|---|---|
| `speed_limit` | `ln` | +1.6000 | exact | Elvik (2009) Power Model, TØI 1034/2009 |
| `access_density` | `ln1p` | +0.1658 | R² 0.965 | HSM Eq. 10-17 |
| `grade_pct` | `ln1p` | +0.1212 | R² 1.000 | HSM Table 10-11 |
| `curve_radius_min` | `ln` | −0.1855 | R² 0.878 | HSM Eq. 10-13 |
| `lit` | `identity` | −0.0817 | exact | HSM Eq. 10-21 + Table 10-12 |
| `roadside_hazard_score` | `identity` | +0.0668 | exact | HSM Eq. 10-20 |

### Not one of these numbers was chosen

`tools/derive_weights.py` computes every weight from the published equation, and a test
(`test_registry_weights_match_the_derivation_script`) fails if the registry drifts from
the script. Hand-editing a weight is now a test failure, not a silent change.

The conversion problem is real and worth stating: published CMFs are multipliers on an
SPF that already contains AADT, while the registry needs log-scale coefficients on
transformed columns. Two of the six were already log-linear and converted exactly; four
required fitting `ln(CMF)` against the declared transform over a stated range, with R²
reported so a weak linearisation is visible.

Weights had to land on the Mode A coefficient scale, not a standardised one. That is
what makes *"Mode B is the prior, Mode A is that prior updated by data"* a fact about
the code rather than a slogan.

### Three honest caveats, all recorded in the registry itself

1. **The equations were read from the NCHRP draft text of the HSM 2nd edition**, not
   from a licensed copy of the printed AASHTO manual. Each was checked against the
   worked examples in that same document and reproduces the published answers exactly —
   good evidence, but not the book. Verify before a paying client sees output.
2. **`speed_limit` = +1.6 is an upper bound.** The Power Model relates *operating* speed
   to crashes; the column is *posted* limit, which moves operating speed by much less
   than 1:1. It is the largest and least certain weight in the registry.
3. **Every HSM weight was estimated on US rural two-lane highways.** The target market
   is not that. This is the largest source of error in Mode B and is defensible only
   because Mode B is an ordinal ranking — a common scaling error leaves the order
   intact. It would not be defensible for a predicted count, which is one more reason
   the engine refuses to emit one.

### Design gap this exposed and closed

`score_index` refused outright if *any* available factor lacked a citation. With a
partly-sourced registry that meant six good weights were blocked by fourteen missing
ones — the opposite of "degrade loudly, never silently skip".

Now it scores on the cited subset and names the rest. An uncited factor is **absent**
from the index, not weighted zero, and both the run log and the CLI say which and why.
Mode B refuses outright only when nothing at all is cited — a path now covered by its
own test fixture, since the shipped registry can no longer exercise it.

### Still open

- Fourteen factors uncited, with the reason recorded per factor in `docs/WEIGHTS.md`.
  `median_present` (HSM Chapter 11) and `curve_density` are the next candidates.
- `traffic_proxy`, `junction_density` and `ramp_density` may never be sourceable —
  the first is our own construct, the second is modelled by the HSM as separate
  intersection entities rather than a segment density, and the third has an unresolved
  sign.

---

## 2026-08-09 — Stage 0 and Stage 1 complete

**Delivered:** the engine core. A plain Python library that takes a panel and returns a
complete, reproducible, self-describing assessment. No geospatial dependencies, no
network, no database.

**Verified:** 113 tests pass, `ruff check` clean, both CLI paths exercised end to end.

```bash
pytest          # 113 passed
ruff check .    # All checks passed
roadrisk demo   # Mode A, A-full, 7 factors, sign guard clean
roadrisk demo --crash-rows-only   # Mode A refused, Mode B refused on unsourced weights
```

---

### 0.1 · Repo skeleton

`pyproject.toml` · `.gitignore` · `README.md`

Hatchling build, `src/` layout, `roadrisk` console script, ruff and pytest configured.
Python floor is 3.11 (for `StrEnum` and `datetime.UTC`); the venv is pinned to 3.12
because 3.14 is ahead of the scientific stack.

---

### 0.2 · Factor registry

`core/registry/schema.py` · `core/registry/loader.py` · `core/registry/factors.yaml`

Pydantic v2 models for `Factor`, `Adapter` and `Registry`. Twenty factors declared,
each with `transform`, `expected_sign`, `drop_priority`, `missing_behaviour`, and an
ordered adapter chain carrying tier and licence.

The registry validates itself and refuses to load if:

- two factors share a `name` or a `column`
- two factors share a `drop_priority` — ties would make descent arbitrary rather than declared
- a `default_weight` is set without a `weight_source`
- a `default_weight` contradicts the factor's own `expected_sign`

Load errors name the offending factor (`factor 'ramp_density' → expected_sign`) rather
than its list index, because a registry is edited by hand.

**Decision — every weight ships unsourced.** `default_weight` is `null` for all twenty
factors and Mode B refuses to score. This is deliberate: the brief's rule is that an
uncited weight is a liability, so the engine enforces it rather than documenting it.
Populating the weights is literature work (HSM CMFs, iRAP tables) and is tracked as an
open decision in `STEPS.md`. Mode A is unaffected — it estimates its own coefficients.

**Decision — no weather term.** Rainfall and temperature are absent, not merely
unweighted. The M51 weather term was withdrawn as a season artefact, and a factor that
correlates with an omitted seasonal cycle is not measuring what its name claims. It
returns only alongside an explicit seasonal control. The reasoning is recorded in the
YAML header so it does not get re-added by accident.

**Recorded in the registry, not just in the brief:** the `ramp_density` inversion
(+0.316 alone, −0.327 alongside roadside activity) is written into that factor's `notes`
along with why it is not diagnosable on M51 — both terms are region-constant across
7 units, so the effective sample size is 7, not 1,085.

---

### 0.3 · Input contract and transforms

`core/contract.py` · `core/transforms.py`

Six required columns. Exposure is derived as `length_km × duration_hours` and
`ln(exposure)` becomes the model offset. Rejections are HARD — the job is refused, never
downgraded to Mode B, because a panel that breaks the contract cannot be ranked either.

Rejects, each naming the offending column and row indices: missing columns, null
identifiers, null crash counts (*"a missing crash count is not the same as zero"*),
negative or fractional counts, non-positive length or duration, non-finite values,
caller-supplied reserved columns, and **duplicate `(unit_id, period, time_slot)` keys**.

The duplicate-key check is an addition, not in the brief. A repeated panel cell
double-counts exposure and inflates significance, and it is the kind of thing a
malformed join produces silently. It caught a real bug within an hour of being written —
see *Bugs found* below.

Transforms are guarded per factor: `ln` rejects non-positive values and suggests `ln1p`;
`ln1p` rejects negatives; `zscore` rejects constants; all reject nulls and infinities.
The infinity message names the case it exists for — curve radius on a tangent section
must be capped by the adapter, and the cap recorded.

---

### 1.1 · Diagnostics

`core/diagnostics.py`

VIF (computed with an intercept present, `inf` on a singular design rather than an
exception), correlation matrix, correlated-partner lookup, variance-to-mean dispersion
with the implied count family, and constant-column detection.

---

### 1.2 · Validation gates

`core/gates.py`

All nine checks, each returning a `CheckResult` carrying its threshold, what was
observed, and a message written to be printed verbatim in the report.

| | Check | Type |
|---|---|---|
| 1 | Zero-crash rows present | HARD |
| 2 | Required columns present and typed | HARD |
| 3 | Exposure strictly positive | HARD |
| 4 | Crash count versus estimated parameters | SOFT |
| 5 | Temporal resolution | SOFT |
| 6 | Crash snap rate | SOFT |
| 7 | Collinearity (VIF) | SOFT |
| 8 | Variance-to-mean → count family | INFO |
| 9 | Model convergence | SOFT, at fit time |

Check 6 is **skipped, never passed**, when the panel was supplied pre-built rather than
snapped by the pipeline. Snap quality is then unknown and is not assumed to be good.

Checks 2 and 3 are enforced by the contract before the gates run, but still appear in
the report as passed — all nine are visible, none is implied.

---

### 1.3 · Mode ladder

`core/ladder.py`

`A-full` (≥700 crashes, ≤7 factors) → `A-reduced` (≥400, ≤5) → `A-minimal` (≥100, ≤3) →
`B`. The engine takes the highest rung passing every gate.

- Terms are shed in the registry's declared `drop_priority` order, never at random.
- The highest-VIF term is dropped first when collinearity is the trigger, in a loop
  until VIF is below threshold.
- The exposure offset is never a candidate for dropping — it is structural.
- Every descent produces a receipt naming the rung attempted, the check that failed, and
  what was shed.

**There is no mode override.** `assess()` exposes no `mode`, `force_mode` or `rung`
parameter, and a test asserts that it never grows one.

**Decision — Poisson can ship in exactly one case.** NB2 is the shipped Mode A baseline
and Poisson is a reference fit. The single exception: NB2 fails to converge *and* the
Poisson reference shows no overdispersion, which means the dispersion parameter NB2 was
estimating is genuinely near zero. That substitution is logged with its reason, never
silent.

---

### 1.4 · Mode B index

`core/models/index.py`

Weighted index over the transformed columns, ranked per unit, worst first.

**Mode B structurally cannot produce a count.** `IndexResult` has no field for a
predicted count, a confidence interval or a p-value — not by convention but by type. A
test asserts the ranking frame carries exactly `unit_id`, `score`, `rank`, `percentile`.

**Decision — weights are on the Mode A coefficient scale.** The score is
`Σ(w_j · x_j)` over transformed columns with no additional standardisation. The brief's
unifying idea is that Mode B weights are priors and Mode A is those priors updated by
data; standardising here would break that correspondence and make the two modes
incomparable. Documented at the top of the module so it does not get "tidied" later.

**Decision — the score ranks rate, not burden.** It deliberately does not multiply by
exposure, so a long busy segment does not outrank a short lethal one. Ranking total
burden is a different question needing a different column.

---

### 1.5 · Mode A, rungs 0–1

`core/models/glm.py` · `core/models/base.py`

Poisson GLM (reference) and NB2 via `NegativeBinomialP` with jointly estimated
dispersion (shipped). Both take `ln(exposure)` as an offset. Results are captured in
plain dataclasses — coefficients, standard errors, z, p, 95% CI, α, log-likelihood, AIC,
BIC, Pearson dispersion — so a result serialises and reproduces without a statsmodels
object.

A failed fit returns `converged=False` with a reason rather than raising, so the ladder
can record why a rung was abandoned instead of crashing the job.

BIC is taken from `bic_llf` where available. Plain `bic` on a statsmodels GLM is the
deviance form, which is on a different scale and not comparable across families.

**Verified against known truth.** The synthetic generator plants coefficients; the
engine recovers them:

| Factor | Planted | Recovered |
|---|---|---|
| `speed_limit` | +0.90 | +0.897 |
| `lanes` | +0.35 | +0.443 |
| `junction_density` | +0.30 | +0.406 |
| `curve_density` | +0.25 | +0.289 |
| `access_density` | +0.20 | +0.160 |
| `poi_density` | +0.18 | +0.152 |
| `grade_pct` | +0.15 | +0.084 |
| dispersion α | 0.60 | 0.637 |

Every sign is correct and α is close. The point estimates sit further from truth than
the reported standard errors suggest they should — which is the Rung 2 problem exactly:
the panel measures 120 units repeatedly across 48 cells each, plain NB2 treats those
5,760 rows as independent, and the standard errors are consequently too small. The model
looks more certain than it is. This is visible in the demo output today and is the
argument for Step 3.1.

---

### 1.6 · Sign guard

`core/signguard.py`

Every fitted coefficient is compared to its declared `expected_sign`. On contradiction
the guard automatically runs the diagnostics that found the original M51 problem:

- the factor fitted alone
- the factor fitted alongside each correlated partner (|r| ≥ 0.3), one at a time
- the full correlation matrix
- leave-one-unit-out, capped and with the cap reported

The written verdict states plainly that the term is not interpretable as causal and must
not justify a countermeasure, and distinguishes a significant contradiction (a
specification problem) from an insignificant one (noise cannot be excluded).

**Verified against a planted reversal.** A synthetic panel is generated with
`curve_density` genuinely *reducing* crashes while the registry declares `+`. The guard
catches it, flags it in the log, and runs all four diagnostics unprompted.

Note that leave-one-unit-out is weak by construction on a corridor with thousands of
segments — dropping 1 of 3,800 moves nothing. The cap and the unit count are both
reported so the weakness is visible rather than implied.

---

### 1.7 · Run log and manifest

`core/runlog.py`

Append-only event log with five levels — `info`, `warning`, `descent`, `refusal`,
`flag` — each event carrying a stage, a stable code, a human message and structured
data. Every gate result, descent, dropped term, absent column and sign flag lands here
and travels to the report.

The manifest fingerprints engine version, Python version, package versions, registry
version and SHA-256, and a content hash of the panel including column names. `created_at`
is recorded but excluded from the fingerprint, so two runs over identical inputs
fingerprint identically — tested both ways.

---

### 1.8 · Engine orchestrator

`core/engine.py`

One call: `assess(panel, registry=..., snap=...)` → `Assessment`. Contains the mode, the
rung, the banner, every check, the fit or the index, the sign guard report, both
receipts, the factor provenance, the manifest and the log. `as_dict()` produces the
JSON-serialisable shape the API and the report template will consume.

Absent columns are logged individually with that factor's `missing_behaviour`, so the
report can say what was lost rather than that something was.

---

### 1.9 · CLI

`cli.py` · `demo.py`

`roadrisk assess` · `roadrisk registry` · `roadrisk demo` · `roadrisk version`

The brief's user-facing rules are implemented here first, because the CLI is where their
shape gets decided before the web panel inherits it:

- **Mode banner** — green `🟢 MODE A — FITTED FROM YOUR DATA · 7 factors · 4,571 crashes`
  or yellow `🟡 MODE B — PUBLISHED WEIGHTS · RANKING ONLY · not a crash prediction`
- **Refusal receipt** — printed whenever Mode A was refused, saying what to supply
- **Descent receipt** — printed whenever the ladder stepped down
- **Sign contradictions** in red panels with the full diagnostic trail, impossible to
  scroll past
- Coefficients coloured against their expected sign, with an `Exp.` column

Gate results render as two tables — before fitting, and at fit once the specification
was known — so that check 4 appearing twice with different parameter counts reads as
two genuine evaluations rather than a duplicate row.

`demo.py` sits outside `core/` on purpose: it fabricates data, and nothing that
fabricates data belongs in the assessment path.

---

## Bugs found while building

Both were caught by guards written earlier the same day, which is the argument for
writing the guards first.

**1 · Duplicate panel cells in the synthetic generator.** Period labels were built as
`2024-{month % 12 + 1}`, so a 24-month panel repeated every label and
`MultiIndex.from_product` produced two rows per cell. The contract's duplicate-key check
rejected it immediately, naming the colliding keys. Fixed by carrying the year.

**2 · Constant-column detection never fired.** `zero_variance_columns` tested
`std == 0`, but pandas returns ~1.8e-15 for a genuinely constant column because of
floating-point summation. A corridor with one posted speed limit end to end — ordinary,
and precisely the `maxspeed` case the brief flags — would have reached the fit with a
singular design. Now compared against a relative tolerance scaled to the column's own
magnitude, in both `diagnostics.zero_variance_columns` and the `zscore` transform.
Regression tests cover exact-zero, floating-point-zero and genuinely-varying columns.

---

## What is not built

Stated plainly so nothing here is mistaken for more than it is.

- **No geospatial pipeline.** The engine consumes a panel; it cannot yet build one from
  two coordinates. Corridor resolution, segmentation, crash snapping and every Tier A/B
  adapter are Stage 2.
- **No GLMM, GAM or Bayesian rung.** Mode A is NB2 today. The standard errors are
  understated for panel data, as shown above.
- **No out-of-sample validation.** No spatial CV, no CURE plots, no held-out calibration.
- **No report or PDF.** `as_dict()` is the seam that will feed it.
- **No web layer, no hosting.** Nothing is deployed and there is no public URL yet.
- **Mode B cannot score** until weights are sourced and cited.
- **Still validated on one corridor.** Nothing here changes that. The second corridor
  remains the critical path, and no amount of engine work substitutes for it.
