# Corridors tested

Every real corridor this tool has been run against, what came back, and what it meant.
Kept because the failures taught more than the successes: most of the runs below produced
a bug fix, one produced the first Mode A assessment in the project's history, and the
latest produced the first A-full fit.

Synthetic corridors — `roadrisk demo`, the API's demo job — are not recorded here. They
test the machinery. These test the product.

| # | Corridor | Date | Mode | Crashes | What it was for |
|---|---|---|---|---|---|
| 1 | Ελαιώνων (U274), Cyprus | 2026-08-28 | B | none | First real road through the new front page |
| 2 | A10, Cyprus | 2026-08-29 | B | none | Found: the road is not built |
| 3 | F929, Cyprus | 2026-08-30 | B | none | Confirmed the length and context fixes |
| 4 | **A6 Derby–Buxton, England** | **2026-08-31** | **A** | 284 real | **First fitted model** — curvature significant |
| 5 | **A82 Lomond–Glen Coe, Scotland** | **2026-08-31** | **A** | 162 real | **Same method, opposite answer** |
| 6 | **A3 Paris, France** | **2026-09-04** | **A** | 1,403 real | **First A-full run; first French road** |

---

## 6 · A3, Paris — the first corridor with enough crashes to fill the model

**18.69 km · 37 segments · 72 months (2019-01 … 2024-12) · 2,664 panel rows
· 1,403 crashes supplied, 1,231 placed · Mode A, A-full**

Porte de Bagnolet north-east to the A1 junction at Le Blanc-Mesnil. Crashes from the
French BAAC files on data.gouv.fr (Licence Ouverte), filtered to `catr = 1` (autoroute)
and road number 3 inside the corridor's bounding box.

The road was asked for as **`A3`**. OSM spells it **`A 3`**. This is the run that proves
the ref-spacing fix (`4220fb3`) works: the corridor came back whole, 287 points, not
self-intersecting, no warnings, 18.69 km traced against a 16.09 km straight line
(sinuosity 1.16 — right for a motorway bending around the Paris suburbs).

### Why this run matters

Every previous corridor sat on a lower rung. This is the first to clear **700 crashes**
and reach **A-full**, and the density is not close: **33.3 crashes per segment**, against
the A6's 1.56 and the A82's 0.53. At that density the model is being asked a question it
can actually answer.

```
Negative binomial (NB2), unit-clustered SEs, 37 clusters
converged · alpha 0.216 · Pearson dispersion 1.06 · AIC 4660.6 · BIC 4713.6
```

Pearson dispersion of 1.06 means the negative binomial is absorbing the overdispersion
almost exactly — a well-specified count model, not a strained one.

### What came out

| Factor | Estimate | p | 95% CI | Read |
|---|---|---|---|---|
| `access_density` | **+0.440** | **2.8 × 10⁻⁸** | +0.285 … +0.595 | Real, right sign |
| `lanes` | **+1.387** | **1.1 × 10⁻⁴** | +0.686 … +2.089 | Real, but see below |
| `speed_limit` | +0.479 | 0.35 | −0.530 … +1.489 | Nothing |
| `grade_pct` | +0.341 | 0.24 | −0.226 … +0.908 | Nothing |
| `poi_density` | +0.019 | 0.64 | −0.062 … +0.100 | Nothing |
| `curve_density` | −0.034 | 0.71 | −0.211 … +0.143 | Wrong sign, noise |
| `junction_density` | −0.003 | 0.95 | −0.098 … +0.092 | Wrong sign, noise |

**`access_density` is the finding.** More slip roads and accesses per kilometre, more
crashes — the merge-and-weave effect an urban motorway is expected to show, at
p = 2.8 × 10⁻⁸ and with the sign the literature predicts.

**`lanes` should not be read as a cause.** The transform is `ln`, so 1.387 says crashes
scale as roughly `lanes^1.4`. But `traffic_proxy` had no column on this run, so exposure
is length × duration alone — the model cannot separate *busy* from *long*, and `lanes` is
the only term in the specification that tracks how much traffic a section carries. It is
almost certainly standing in for volume. Widening a motorway does not multiply its crashes
by 2.6, and this run does not claim it does.

**The sign guard did its job.** `junction_density` and `curve_density` both fitted
negative against a declared `+`. Both are far from significant, and the guard refused to
interpret either — it reported the univariate estimate (`junction_density` is **+0.163**
on its own, the expected direction), the correlation with `access_density` (r = 0.45),
and a leave-one-out refit that flipped sign 8 times in 25. That is the correct behaviour:
the contradiction is confounding with `access_density`, not a discovery.

### Where it is weak

**Validation did not pass.** Two of the three parts were fine:

| Scheme | Observed | Predicted | Ratio |
|---|---|---|---|
| Random units | 1,231 | 1,209 | **1.018** |
| Contiguous stretches | 1,231 | 1,085 | 1.135 |

Random-fold calibration at 1.8% is genuinely good. Contiguous stretches under-predict by
13.5%, still inside the ±20% the HSM treats as ordinary — held-out *stretches* are harder
than held-out *segments*, which is the point of running both.

**The CURE test is what failed**, on three factors — `junction_density` (41% of the range
outside bounds), `poi_density` (41%) and `access_density` (38%) — and all three drift
*worst around 0.00*. That is one problem wearing three hats: **28 of the 37 segments have
zero junctions**, so these are not really density variables on this corridor, they are
near-binary presence flags forced through a continuous term. The model is systematically
wrong on the segments that have none. The fix is a presence flag or longer units, not more
data.

### Two defects this run exposed — both fixed

**1 · Check 7 failed against a model that was never fitted.** The first run reported:

```
[failed] Collinearity (VIF) — 1 term(s) exceed VIF 5 — speed_limit = 5.4
```

That VIF was computed on the **12 available factors**, before the ladder runs.
`MODE_A_RUNGS` caps A-full at **7 factors** (`ladder.py:66`), so the shipped design had
seven, and `_resolve_collinearity` shed nothing from it — meaning the model actually
fitted had max VIF **below** 5. A client reads a failed collinearity check and concludes
their results are unusable. They were not. The gate was honest about a design the engine
had discarded, and a report that says a result failed a check it passed is worse than one
that says nothing.

*Fixed:* `check_vif` now takes `fitted=` and says which design it measured; the ladder
runs it again on the subset it is about to fit; and `_shipped_checks` lets that result
supersede the candidate one, so exactly one check 7 reaches the report. Mode B keeps the
candidate check, because Mode B scores every available factor and there is no other
design to describe. Re-run on the same corridor:

```
[passed] No collinearity above threshold across the fitted model; highest VIF is 1.8
```

**2 · The default crash mix was for the wrong kind of road, and was cited on a run that
never used it.** Context was declared `facility_type: motorway`, and the fallback split
of crashes by type is *HSM Table 10-4, rural two-lane two-way* — a distribution claiming
two thirds of crashes are run-off or head-on, on a road built with no oncoming traffic to
run into. Worse, the caveat about it was printed on a **Mode A** run. The split is only
consulted by the weighted index; a fitted model never touches it. The report was
apologising for an assumption the run had not made.

*Fixed:* `CrashMix` now records the facility it was **measured on**, `RunContext` exposes
`crash_mix_facility_mismatch`, and the limitation is emitted only when an index exists —
as a **material** finding naming both road types when they disagree, and as the old
caveat when they do not. No number was invented: the engine now says the split does not
fit, rather than quietly substituting one that does not exist.

### The traffic proxy, and the guard that was counting the wrong thing

`traffic_proxy` was never missing. `geo/adapters/graph.py` is complete, `"traffic"` is a
valid adapter over the API, and it is a checkbox on the page. Turning it on produced:

```
the strategic network within 20 km of this corridor exceeds 60,000 vertices
```

**`MAX_GRAPH_NODES` is documented as a ceiling on the graph, and was checked against raw
OSM vertices.** The same module says OSM carries "ten to fifteen vertices per junction",
and betweenness runs on junctions. Measured on this corridor:

| Window | Raw vertices | Contracted junctions | Betweenness |
|---|---|---|---|
| 5 km margin, 0.1° grid | 141,260 | 8,689 | 5 s |
| 10 km, 0.2° | 372,907 | 23,057 | 14 s |
| **20 km, 0.5° — the default it refused** | **674,358** | **37,935** | **25 s** |

An 18× overcount, and it bit hardest on dense urban networks — which is exactly where
"which road carries the through traffic" is the question worth asking.

*Fixed:* the refusal now runs on contracted junctions, after contraction. A separate
`MAX_GRAPH_VERTICES` bounds the contraction itself. The A3 then resolved on the first
try: 93,734 strategic ways contracted to 38,061 junctions and 58,252 links.

### What the traffic proxy changed

| | without | with |
|---|---|---|
| AIC / BIC | 4660.6 / 4713.6 | **4636.8 / 4689.8** |
| alpha · Pearson dispersion | 0.2157 · 1.0585 | **0.1988 · 1.0411** |
| `traffic_proxy` | — | **+10.193, p = 0.0083** |
| `lanes` | +1.3874, p = 1.1e-4 | **+0.9135**, p = 0.027 |
| `grade_pct` | +0.3406, p = 0.24 | **+0.5940, p = 0.029** |
| `speed_limit` | +0.4791 | −0.3119 |
| `access_density` | +0.4400 | +0.3256, p = 1.1e-4 |
| `poi_density` | +0.0193, p = 0.64 | dropped by keep-order |
| blackspot 1 expected vs 266 observed | 237.3 | **272.1** |

**`lanes` fell by a third**, which is the confirmation that it had been standing in for
volume: `traffic_proxy` carries `drop_priority: 100`, enters first, and takes back the
exposure signal `lanes` was holding. `grade_pct` became significant only once volume was
controlled for. Both are the textbook consequence of adding an omitted exposure term.

**The coefficient looks alarming and is not.** Betweenness is a share bounded well below
one — this corridor spans 0.0007 to 0.065 — so `ln1p` barely compresses it and the
coefficient is large because the variable is small. End to end the linear predictor moves
0.634, which is **1.9× expected crashes** between the least and most central segment.

**It is not free.** Two costs, both reported by the run rather than found afterwards:

- `low_confidence_factors` — *"On more than half the corridor, traffic_proxy was filled
  in from a neighbouring value rather than resolved for that segment."* Tier B, inferred,
  and interpolated on most segments.
- Held-out **contiguous stretches got worse**: ratio 1.135 → 0.822, MAD 0.575 → 0.667,
  optimism 0.010 → 0.108. A factor that varies smoothly along the corridor is exactly the
  one that cannot be recovered when a contiguous stretch is held out. Random-unit folds
  stayed calibrated (1.018 → 1.054).

Worth having. Not worth pretending it is a measurement.

### Why validation fails, and why one factor fits backwards

Both are the same fact, and it is not a bug. Per-unit values, in corridor order:

| Factor | Zero on | Distinct | r with crashes | CURE |
|---|---|---|---|---|
| `junction_density` | **28 / 37 (76%)** | 5 | +0.191 | **drifts** |
| `access_density` | **28 / 37 (76%)** | 6 | +0.490 | **drifts** |
| `poi_density` | **31 / 37 (84%)** | 7 | +0.047 | **drifts** |
| `curve_density` | 10 / 37 (27%) | 6 | +0.273 | ok |
| `lanes` · `grade_pct` · `speed_limit` | 0 | 24 – 37 | +0.40 · +0.32 · −0.34 | ok |

**Correlation between zero share and CURE share-outside: +0.912.** The factors that drift
are the factors that are mostly zero, and nothing else drifts.

The data is right — the A3 is grade separated, so it genuinely has interchanges at nine
segments and none between them. The *specification* is wrong: `ln1p(density)` is a smooth
curve fitted to a spike at zero plus nine points. `junction_density` is estimated from
nine informative segments against a stronger, correlated neighbour, and leave-one-out
flips its sign 8 times in 25. It is not contradicting the literature. It is unidentified.

**Three fixes, in order of value:**

1. **Screen for variation before the factor cap.** *(Built — see below.)* A-full keeps
   the 7 highest `drop_priority`, never looking at the corridor. On the A3 that spent a
   slot on `poi_density`, which holds one value across 84% of the road and correlates
   with crashes at 0.05.
2. **Enter near-binary densities as presence flags.** Above roughly 60% zeros,
   `ln1p(count/km)` is a spike-and-slab. `has_junction` is the honest term, and would end
   the CURE drift.
3. **Prefer `ramp_density` on a motorway.** Nonzero on 30 of 37 segments against
   `junction_density`'s 9. A motorway has interchanges, not junctions.

None of these are defects. They are specification choices the engine currently makes in
advance instead of from the corridor in front of it.

### The variation screen, and the prediction it did not meet

Built as `MAX_MODAL_SHARE = 0.8` in `ladder.py`: before a rung slices its factors from
the keep order, any factor holding one value across 80% or more of the units is moved to
the **back** of that order. Demoted, never dropped — a rung fits *up to* N terms, and
removing a factor outright would sometimes return a smaller model than the data supports.

The threshold sits at 0.8 because 0.7 would have been wrong: `access_density` is
concentrated on one value across 76% of this corridor and is still its strongest term.
Concentration is a reason to prefer another factor, never on its own a reason to disbelieve
one. There is a test pinning that.

**Measured by rebuilding the A3 panel from the run record and assessing it twice, once
with the screen and once without.** Same 2,664 rows, same 1,231 crashes, one difference:

| | screen off | screen on |
|---|---|---|
| 7th seat | `poi_density` (84% one value, p = 0.64) | **`curve_radius_min`** |
| Spatial validation ratio | 1.135 | **1.004** |
| CURE drift | `junction_density`, `access_density`, **`poi_density`** | `junction_density`, `access_density` |
| Sign contradictions | 2 | **1** |
| AIC | 4660.6 | 4658.8 |
| `access_density` | +0.4400, p = 2.8e-8 | +0.4430, **p = 5.0e-9** |
| Optimism | 0.0102 | 0.0220 |

Better calibration, one fewer false contradiction, one fewer drifting factor. Modest and
real.

**But the seat went to `curve_radius_min`, not `landuse_urban`, and predicting otherwise
was wrong.** Keep order is `drop_priority` descending, so demoting `poi_density` (65)
promotes `curve_radius_min` (55) — not `landuse_urban`, which sits at 33, near the bottom
of the registry.

**That is the screen working as designed, not failing.** It removes factors that cannot
inform *anything*, which is a property of a column's own distribution. Promoting
`landuse_urban` on the grounds that it correlates with crashes at 0.46 would be selecting
terms by their relationship to the outcome — the garden of forking paths, and it would
inflate every p-value that survived it. The registry's ordering is a judgement made once,
in advance, for all roads, which is exactly where a judgement like that belongs.

**So `landuse_urban` entering the model is a registry question, not an engine one.** If
roadside development deserves to outrank curvature and lighting, that is an edit to
`drop_priority` in `factors.yaml`, argued from the literature rather than from this
corridor's correlations.

**With `traffic_proxy` enabled the screen changes nothing at all** — `poi_density` is
demoted, but `traffic_proxy` (priority 100) had already taken the seat it would have lost.
Identical coefficients, identical AIC. Worth recording: the screen is a no-op exactly when
something better is already doing its job.

### One thing this run did right without being asked

A later re-run hit an **Overpass outage on every mirror** and came back with 4 factors
instead of 12. It did not hide it:

```
osm_tags: resolved=[]
  "The OSM attribute fetch failed, so every OSM-derived factor is absent from
   this panel: every Overpass mirror failed — TimeoutError; HTTPError; ..."
```

Worth recording because the failure mode is silent-looking from the outside — the run
succeeds, the model converges, and only the adapter note says the road was never
measured.

### Also worth noting

`curve_radius_min` — the A6's headline result — **never entered the specification.** It
was available, but the 7-factor cap on A-full dropped it by keep-order. So this run says
nothing about whether bend severity matters on the A3; the model was not allowed to ask.

### Ranking

Segments are ranked on expected crashes per unit of exposure. Four blackspots in the worst
20%, and the top one is contiguous and large:

| Blackspot | Chainage | Length | Observed | Expected |
|---|---|---|---|---|
| **1** | 11,000 – 13,000 m | 2.0 km | **266** | 237 |
| 2 | 17,500 – 18,694 m | 1.19 km | 121 | 117 |
| 3 | 15,000 – 15,500 m | 0.5 km | 32 | 45 |
| 4 | 4,500 – 5,000 m | 0.5 km | 38 | 44 |

Blackspot 1 is four consecutive segments carrying **266 of the corridor's 1,231 crashes
in 11% of its length**. That is the kind of output the product exists to produce.

### Interpretation

**The results make sense and the retrieved data is sound.** 88.2% of nearby crashes
placed on the corridor, 7 rejected as belonging to another road, geometry clean, the
count family chosen correctly, one strong result with the right sign, one result honestly
marked as a probable exposure proxy, and five factors correctly reported as finding
nothing. The weaknesses are named in the report rather than hidden by it.

**Score: 8/10 as it ran; 9/10 after the two fixes above.** What remains is the CURE
drift, and `traffic_proxy` being absent — which is the single change that would most
improve this corridor, because it is what `lanes` is currently standing in for.

---

## 5 · A82 Loch Lomond to Glen Coe — the same method, the opposite answer

**113.9 km · 228 segments · 162 crashes supplied, 120 placed · Mode A, A-minimal**

Run after the gap fix below, on a notorious Scottish single-carriageway mountain road.
Every check passed, including the one that matters most here:

```
CHECK 6  PASSED  100.0% (120 of 120 near the corridor)
```

**Every crash near the corridor landed on it.** Dispersion 1.001, converged, AIC 1350.4.

### And curvature explained nothing

| | A6 Derby–Buxton | A82 Lomond–Glen Coe |
|---|---|---|
| `curve_radius_min` | −0.4872, **p = 4.7 × 10⁻⁷** | −0.0872, p = 0.478 |
| `curve_density` | −0.0475, p = 0.849 | −0.2046, p = 0.288 |

Same factor, same model, same country, same crash source, opposite result. Two
explanations were tested and **both were wrong**, which is worth recording because the
obvious answers were plausible.

**Tested: signal dilution.** The A82 carried 0.53 crashes per unit against the A6's 1.56,
and 139 of its 228 units had never had a crash. So the corridor was re-run unchanged
except `unit_length_m: 500 → 1500`, giving 76 units at 1.58 crashes each — the A6's
density exactly. Result: still nothing (`curve_density` p = 0.64), and `curve_radius_min`
left the specification altogether.

**Tested: no variation to explain.** A factor that is constant cannot explain anything, and
Glen Coe is bends end to end. Measured from the geometry, the A82 varies **more** than the
A6, not less:

| | A6 @ 500 m | A82 @ 500 m |
|---|---|---|
| `curve_radius_min` median | 154 m | 305 m |
| range | 6 – 1,394 m | 10 – 5,000 m |
| **spread (sd/mean)** | **0.97** | **1.67** |

### Interpretation

**On this road, with this data, bend severity does not predict crashes.** That is the
finding, and neither convenient explanation survives contact with the numbers.

Plausible reasons, none of them tested here and none claimed: drivers slow for bends they
can see are severe, so geometry stops discriminating on a road that is severe throughout;
A82 crashes may be driven by overtaking, unfamiliar tourist traffic or weather rather than
alignment; and 120 crashes is still a thin table, so a modest real effect could sit inside
the confidence interval unseen — it spans −0.33 to +0.15.

**Why this matters more than the A6 result.** Mode B, on both roads, would have applied
iRAP's curvature weight and announced that bends drive the risk. Mode A fitted the same
factor to two real crash histories and found it true on one road and absent on the other.
**That difference is the entire argument for having Mode A**, and it is the first time
this project has been able to demonstrate it.

The honest next step on the A82 is more crashes — the full road holds 365 — not more
modelling of these 120.

---

---

## 4 · A6 Derby to Buxton — the first Mode A run

The one that matters. Everything before it was Mode B, which is a ranking from published
weights; this is a crash model fitted from the road's own history.

### The road

| | |
|---|---|
| Selector | `ref=A6`, OpenStreetMap |
| Bounding box | 52.90, −1.90, 53.30, −1.40 (south, west, north, east) |
| Resolved length | **48.00 km** — the longest continuous run inside the box |
| Segments | **96** at 500 m |
| Road class | `trunk`, `primary`, `trunk_link` — all open |
| Median vertex spacing | **16.1 m**, finer than the 30 m curvature interval |
| Declared context | `rural_two_lane` · `europe` · all severities |
| Adapters | `osm`, `imagery` |

The vertex spacing is why this corridor worked where others did not. On U274 and the A10
the centreline was coarser than the measurement interval, and both reports carried
*"curvature reads TIGHTER than the real road and must not be trusted"* — about the factor
carrying the largest weight. The A6 has no such warning.

### The crash data

**GB STATS19**, UK Department for Transport, Open Government Licence v3.0. Free, no
registration, direct download.

- 513,801 collisions, 2021–2025
- Filtered on `first_road_class == 3 AND first_road_number == 6` — collisions the
  reporting officer recorded **as being on the A6**, not merely near it
- Then to the bounding box: **284 crashes**
- Columns needed: `latitude`, `longitude`, `period` (`YYYY-MM`, derived from `date`)

Severity mix in the wider Derbyshire sample: 2 fatal, 46 serious, 89 slight.

### The panel

```
5,664 rows  =  96 units × 59 periods
150 crashes placed on the corridor
5,517 zero-crash rows (97.4%)
total exposure 2,068,795 km-hours
```

### What was fitted

**Negative binomial (NB2) GLM with unit-clustered standard errors**, converged, 96
clusters, AIC 1377.4, Pearson dispersion 1.012.

| Factor | Estimate | Std error | p | 95% CI |
|---|---|---|---|---|
| `curve_radius_min` | **−0.4872** | 0.0967 | **4.7 × 10⁻⁷** | −0.677 to −0.298 |
| `curve_density` | −0.0475 | 0.2495 | 0.849 | −0.537 to +0.442 |
| intercept | −7.047 | 0.654 | 4.5 × 10⁻²⁷ | −8.329 to −5.765 |

All nine checks passed. Crashes per parameter 37.5 (floor is 10). Max VIF 1.0.

### Interpretation

**`curve_radius_min` is real and strong.** A tighter minimum bend radius on a segment
means more crashes, at p ≈ 0.0000005, with a confidence interval nowhere near zero. The
sign matches what the literature predicts, so the sign guard raised no contradiction
against it. **This is the first coefficient this project has produced from a real road's
own crashes rather than from a borrowed published weight** — which is the entire point of
Mode A, and the answer to the fact that the registry holds *zero* weights estimated in
Europe.

**`curve_density` is noise, and the report says so twice.** p = 0.85, and the confidence
interval spans zero comfortably. It also came out with the opposite sign to the one the
literature expects, which the sign guard flagged as material: *"it is standing in for
something else on this corridor rather than causing anything, and it is not interpretable
as a cause."* That is the honesty layer working — the model was not allowed to quietly
report a wrong-signed term as a finding.

**Only two factors, because the rung is A-minimal.** 150 placed crashes clears the
A-minimal floor of 100 but not A-reduced's 400, so the ladder descended and fitted a
reduced specification. More crashes would buy more factors, not better ones.

**The ranking now carries prediction intervals**, which Mode B structurally cannot do.
Segment 0000 is worst at 4.70 expected crashes against 3 observed; segment 0035 second at
4.66 expected against 6 observed. 13 blackspot runs. Cross-validation optimism 0.0022 —
negligible, so the fit is not being carried by a handful of folds.

**One real caveat the run raised itself:** the centreline crosses itself, so linear
referencing is ambiguous near the crossing and a crash there could snap to either branch.
Worth splitting the corridor at that point on a serious run.

### What this run cost to set up

About 90 seconds of download and one filter expression. No survey vehicle, no AADT, no
road inventory, no licence fee.

---

## 3 · F929, Cyprus — the length and context fixes, confirmed

**15.46 km · 31 segments · no crash file · Mode B**

Run to confirm three changes made after the A10. All three showed up:

- **Check 6** now reads *"No crash table was supplied, so there was nothing to snap"*
  instead of falsely claiming the panel was supplied pre-built
- **Check 8** is SKIPPED instead of PASSED on a variance-to-mean ratio of `inf`
- The **imagery check ran**: *"7 photograph(s) within 25 m of the centreline, none newer
  than 2022-04-11 — about 4 years ago. The road was open then. Nothing here says whether
  it still is."*

**Interpretation.** The corridor-length readout did its job — 31 segments against U274's
4, and collinearity fell from infinity to a VIF of 1.9. Score spread widened from 0.018 to
about 0.35, so the ranking separates instead of being flat noise.

But only **1 of 6 tag factors cleared its coverage floor**: F929 carries just 5 OSM ways
over 15.46 km, so no speed limit, lanes or lighting. Two factors scored. The output is
usable as a screening ranking and is honest about being one.

---

## 2 · A10 Αυτοκινητόδρομος Λευκωσίας-Παλαιχωρίου — a road that does not exist

**8.53 km · 17 segments · no crash file · Mode B**

The most valuable failure so far. The report was internally consistent, said nothing
untrue, and was completely worthless — because **every one of the A10's 22 OpenStreetMap
ways is tagged `highway=construction`.** The motorway is still being built.

Verified independently against Overpass:

| The report said | OSM said |
|---|---|
| median vertex spacing 95 m | **93.7 m** |
| only 30% of the centreline within 20 m of a road way | a construction way is not a road way |
| 0 of 6 tag factors cleared the coverage floor | maxspeed on 5 of 22 ways |
| `ramp_density` and `poi_density` matched nothing | nothing is beside an unopened road |

**Interpretation.** Four true statements, reported separately and correctly, and the one
sentence explaining all four — *the road is not built* — was never said. That is the
expensive failure mode for this product: not a wrong number, a missing frame.

**Fixed.** `highway=construction`, `proposed`, `planned`, `abandoned`, `disused`, `razed`
and `demolished` are now refused at the fetch, naming the tag found. A partly-built road
keeps its open section and warns. `FacilityType.MOTORWAY` was added at the same time,
because the A10 had been declared `rural_two_lane` — admitting a driveway-density weight
for a road with no driveways.

---

## 1 · Ελαιώνων (U274), Cyprus — too short to say anything

**1.83 km · 4 segments · no crash file · Mode B**

The first real corridor through the new front page. The data retrieved was **correct** —
every value cross-checked against OSM — and the result was still unusable.

- **VIF returned infinity** on 8 terms: 4 observations cannot support 10 factors
- Scores ran −0.992 to −1.010, a spread of **0.018** across the whole corridor
- The "blackspot" was 1 segment of 4
- The real U274 is 2.95 km; the map viewport had clipped it to 1.83 km

**Interpretation.** Everything that went wrong was decided by a zoom level before the
button was pressed, and nothing on screen said so. This produced the corridor-length
readout — *"≈ 9.4 km in view · about 19 segments"* — and the warning below ten segments.

It also produced two bug fixes, both found by reading the PDF rather than by any test:
check 6 claiming a panel was "supplied pre-built" when the engine had built it, and check
8 reporting **PASSED** on a variance-to-mean ratio of `0/0 = inf`.

---

## Corridors that were refused, and why

Refusals are results. These were attempted for the A6 test and turned down:

| Attempted | Crashes available | Outcome |
|---|---|---|
| A6 Derby → Stockport | 551 (A-reduced) | **Refused** — longest continuous run carried 42% of 120 km |
| A6 Bakewell → Stockport | 260 | **Refused** — 22% of 69.4 km |
| A6 Luton → Bedford | 328 | **Refused** — 13% of 59.4 km |
| A6 Leicester → Kettering | 176 | **Refused** — 12% of 47.8 km |

**Interpretation.** The A6 is genuinely fragmented in OpenStreetMap where it passes
through towns, and the fragmentation gate would not weld the pieces together. That caps
how much road can be assessed in one run and is the main reason the A6 test reached
A-minimal rather than A-reduced. It is the gate working correctly, not a defect — but it
is a real limit on corridor length in dense areas.

---

## The audit: was the A6 corridor the right road?

Run after the A6 result, because a fitted coefficient is only worth what the crash
assignment behind it is worth.

### The crashes that landed are placed well

```
distance from the centreline, of the 150 placed crashes
  median   2.9 m
  p95      9.2 m
  max     15.3 m
```

Every placed crash is within 16 m of the road. 62 of 96 units carry at least one, the
median used unit has 2, the busiest has 8, and they spread evenly from chainage 142 m to
46,960 m of a 48,000 m corridor. **There is no pile-up and no obvious misassignment.**

### But the corridor was only two thirds of the road

```
75 piece(s) totalling 26.88 km carry the same road reference but do not
connect to the main line within 25 m. They are excluded.
```

Of roughly 75 km of A6 in the box, **26.9 km was discarded** and 48.0 km kept. That is
where the 129 `not_on_this_corridor` crashes were: not on other roads at all, but on real
A6 that the stitcher had dropped. The snap-rate fix stopped blaming the crash table, which
was right — but the deeper problem was that the corridor was incomplete.

### The cause: roundabouts, and a 25 m gap tolerance

A British A-road runs *into* a roundabout and out the other side. The roundabout is its
own OSM way and usually carries no `ref`, so the road's own ways stop and restart across
it — a gap the width of the junction, tens of metres. At `max_gap_m = 25` every roundabout
broke the chain.

Measured on four British A-roads:

| Road | at 25 m | at 60 m | at 120 m |
|---|---|---|---|
| **A82** | **refused** — longest run 50% | 94.1 km, **0.6 km lost** | 94.3 km |
| **A470** | **refused** — 57% | **refused** — 57% | 58.1 km |
| **A66** | **refused** — 24% | 28.4 km | 28.4 km |
| **A6** | 48.0 km, 26.9 lost, **150 placed** | 57.2 km, 18.0 lost, **185 placed** | 61.0 km, 14.7 lost, **208 placed** |

On the same A6, same crash table: **150 crashes placed at 25 m, 208 at 120 m.** A quarter
more evidence, from rejoining a corridor that had been cut at every junction.

**Fixed.** `DEFAULT_MAX_GAP_M` raised from 25 m to 60 m — the width of a roundabout. The
25 m figure was tuned on Cyprus B-roads, where junctions are simple and a break really is
an editing artefact. Every safeguard is unchanged: only *ends* are bridged, only between
ways already carrying the same selector, and `MIN_LONGEST_SHARE` still refuses a
collection that will not assemble into one road. A test plants a 45 m junction gap and a
6 km real gap and asserts the first is bridged and the second still refused.

### One issue left open

**The A6 centreline crosses itself**, and the run said so at caveat severity. Linear
referencing is ambiguous near a crossing: a crash there can snap to either branch and
receives whichever chainage is marginally closer. It affects a small number of crashes and
the fix is to split the corridor at the crossing, which the report already advises. Not
fixed, recorded.

---

## The snap-rate fix this test produced

The A6 run initially **failed check 6 at 52.8%**, reporting *"the panel is not a faithful
record of what happened on this road"* — about a panel that was a perfectly faithful
record of the corridor.

Measured, the distances from the centreline were bimodal:

```
p10      0.9 m
p50      9.1 m      <- half the table is on the carriageway
p75  9,189.9 m      <- and the rest is kilometres away
max 14,107.1 m
```

Widening the tolerance from 30 m to 150 m recovered **two** crashes out of 134. The
dropped crashes were not mis-geocoded; they were on stretches of the A6 that the fetch had
not returned, because a national extract covers more road than any one corridor.

**Fixed.** Crashes beyond 500 m are now `not_on_this_corridor` rather than
`beyond_tolerance`, and are excluded from the snap rate instead of counted against it —
while still being reported. The same run now reads:

```
CHECK 6 [PASSED]  96.8% (150 of 155 near the corridor)
  A further 129 crash(es) were more than 500 m away and are not on this
  corridor at all — normally a crash table covering more road than was
  assessed, which is not a fault in either.
```

Genuinely poor geocoding still fails the check; a test holds both halves.

---

## How to reproduce the A6 run

```bash
curl -o /tmp/stats19.csv \
  https://data.dft.gov.uk/road-accidents-safety-data/dft-road-casualty-statistics-collision-last-5-years.csv
```

```python
import pandas as pd
d = pd.read_csv("/tmp/stats19.csv", low_memory=False)
a6 = d[(d.first_road_class == 3) & (d.first_road_number == 6)]
box = a6[a6.latitude.between(52.90, 53.30) & a6.longitude.between(-1.90, -1.40)].copy()
box["period"] = pd.to_datetime(box.date, dayfirst=True).dt.strftime("%Y-%m")
box[["latitude", "longitude", "period"]].dropna().to_csv("a6_crashes.csv", index=False)
```

Then on the front page: search **Matlock**, frame the A6, tick the imagery check, declare
`rural_two_lane` · `europe` · all, attach `a6_crashes.csv`.

---

## What the four runs say together

**The geography half is working.** Corridor resolution, segmentation, adapters, fusion,
provenance and licensing all did their jobs on four real roads in two countries, and every
value that was cross-checked against OpenStreetMap was correct.

**Mode B is thin, and the registry is why.** 22 factors are measurable; 8 carry a cited
weight; **none of the 13 weights was estimated in Europe.** Every European corridor
therefore scores on global figures or on North American ones reached across the Atlantic,
which the reports say plainly and at length.

**Mode A is the way out of that, and it now works.** One free national dataset and one
filter produced a fitted coefficient significant at p < 10⁻⁶ from a road's own crash
history. That is worth more than any number of additional Mode B corridors.

**The next thing worth doing is more crashes, not more roads.** A stretch supporting 400+
placed crashes reaches A-reduced and fits more factors; 700+ reaches A-full. The
constraint is OSM fragmentation in towns, not crash-data availability.

**And two roads already disagree.** Curvature is significant at p < 10⁻⁶ on the A6 and
absent on the A82. A borrowed weight would have said the same thing about both. That
disagreement is the product working, not a problem to reconcile.

---

## Choosing a corridor — what these five runs taught

In order of how much each one cost to learn:

1. **The road must be open.** `highway=construction` is refused now, but check what you
   are pointing at. (A10)
2. **Enough units for the checks to mean anything.** Under about ten, VIF returns
   infinity and the ranking spreads across a fraction of its scale. (U274)
3. **Enough crashes per unit, not just enough units.** 1.5 per unit worked; 0.5 did not.
   Corridor length and crash count have to be chosen together, and `unit_length_m` is the
   lever when the road is fixed. (A82)
4. **Dense centreline geometry.** Vertex spacing coarser than the 30 m curvature interval
   makes curvature untrustworthy, and the report says so. Check it before trusting any
   alignment factor. (A10, F929)
5. **Watch the excluded kilometres.** A corridor that quietly drops a third of the road
   produces a snap rate that looks like bad crash data. (A6)
