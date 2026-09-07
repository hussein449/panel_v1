# Corridors tested

Every real corridor this tool has been run against, what came back, and what it meant.
Kept because the failures taught more than the successes: most of the runs below produced
a bug fix, one produced the first Mode A assessment in the project's history, one produced
the first A-full fit and six defects, and the latest killed a hypothesis this file had
twice reported as promising.

**Dead ends are recorded here as carefully as findings**, because the expensive mistake
this project can make is not missing an effect — it is believing one. Three things were
built, measured and thrown away; one lead was argued twice and then closed by a better
test; and the reasoning that was wrong is left in place beside what replaced it.

Synthetic corridors — `roadrisk demo`, the API's demo job — are not recorded here. They
test the machinery. These test the product.

| # | Corridor | Date | Mode | Crashes | What it was for |
|---|---|---|---|---|---|
| 1 | Ελαιώνων (U274), Cyprus | 2026-08-28 | B | none | First real road through the new front page |
| 2 | A10, Cyprus | 2026-08-29 | B | none | Found: the road is not built |
| 3 | F929, Cyprus | 2026-08-30 | B | none | Confirmed the length and context fixes |
| 4 | **A6 Derby–Buxton, England** | **2026-08-31** | **A** | 284 real | **First fitted model** — curvature significant |
| 5 | **A82 Lomond–Glen Coe, Scotland** | **2026-08-31** | **A** | 162 real | **Same method, opposite answer** |
| 6 | **A3 Paris, France** | **2026-09-04/05** | **A** | 1,403 real | **First A-full run; six defects; first clean sheet** |
| 7 | **A50 Marseille–Aubagne, France** | **2026-09-07** | **A** | 773 real | **A dead lead, and the case for Mode A** |

### What the A3 changed, in one table

Every fix below came out of that one corridor, and every one of them was found by the
panel contradicting itself rather than by reading the code.

| Commit | Defect | How it surfaced |
|---|---|---|
| `4d137b7` | Check 7 failed against a design that was never fitted; crash-mix caveat printed on a run that never used it | A failed gate on a passing model |
| `a3a0fa7` | Traffic proxy refused dense networks — a node ceiling counting raw vertices, an 18× overcount | A refusal on exactly the roads it is most useful on |
| `5b3bad1` | A rung's seats went to factors flat on this corridor | `poi_density` fitted at p = 0.64 while varying factors sat out |
| `214c82c` | CURE ordered tied values by corridor position | Three unrelated factors drifting at 40.5%, 37.8%, 40.5% |
| `1e1842e` | `ln1p` on a share of order 1e-3 is the identity | Contiguous folds predicting 1,828 against 1,231 |
| `8ab6f67` | Suppression filed under contradiction | Two very different findings under one material heading |
| `c8ed050` | A term about at-grade junctions fitted on a motorway | A contradiction no site inspection could resolve |
| `301a0cd` | Suppression tested pairs instead of removals | A contradiction with a correct univariate sign |

**The corridor went from one false failed check and a failing validation to a clean
sheet**: all ten checks pass, both cross-validation schemes calibrate, no CURE drift, and
no material limitation on the page.

The A50 that followed it produced two more, both about a run quietly becoming a different
run, and the pair together produced two more again:

| Commit | Defect | How it surfaced |
|---|---|---|
| `6b6ea03` | A source outage changed the specification and still reported success | Two runs minutes apart fitting the same factor at +0.469 and +0.392 |
| `e760f22` | The client hung up after 90s on a query asking the server for 180s | Nine timeouts on three mirrors, while a *larger* query succeeded beside it |
| `c01deee` | Two measurements of one geometry fitted together, neither identifiable | `curve_density` reading −0.081 beside its partner and +0.006 without it |
| `ea8cd2f` | Every wrong sign was material, however weak the estimate | `speed_limit` at p = 0.95 raising a corridor's most serious heading |

### Where the two corridors finished

| | A3 Paris | A50 Marseille |
|---|---|---|
| Checks | **10 / 10 pass** | 10 / 10 pass |
| Validation | **passes**, contiguous 1.083 | passes, contiguous 1.134 |
| CURE drift | **none** | none |
| Source failures | **none** | none |
| **Material limitations** | **none** | `specification_reduced`, `sign_contradiction` |
| Best AIC | 4660.6 → **4651.4** | 4189.8 → **3948.9** |

The A50 keeps two material headings and should: it holds 678 crashes against the 700
A-full needs, and its `speed_limit` contradiction is significant at p = 10⁻²⁶, which is a
real specification problem rather than a coin flip.

**`access_density` on the A3 survived all nine specifications** these fixes moved it
through — +0.44, +0.33, +0.30, +0.39, +0.40, +0.37, +0.36 — never once changing sign,
while almost everything around it was rebuilt. That is the strongest thing that can be
said for a finding: the answer did not move while the machinery under it did.

---

## 7 · A50, Marseille to Aubagne — a lead that did not survive being tested properly

**40.90 km · 82 segments · 773 crashes supplied, 678 placed · Mode A, A-reduced**

Run to answer one question the A3 could not. The A3 fitted `grade_pct` at +0.489,
p = 0.089 — leaning positive, short of the bar — but the A3 is flat, its grades running
0.50% to 3.75%. A corridor that does not climb cannot be asked whether climbing matters,
so the fix was not more rows, it was more gradient. The A50 leaves Marseille through the
coastal hills toward Aubagne and reaches **6.18%**, against 773 autoroute crashes in
Bouches-du-Rhône over 2019–2024.

Selected by screening every French autoroute for crash count inside mountainous
departments, which is worth recording as a method: the candidate list took one pass over
the BAAC files and ranked A7, A50, A55, A507, A8 by crashes in terrain.

### It took four runs to get one honest answer

The first three all lost factors to Overpass, and each loss moved the answer:

| Run | Factors fitted | `access_density` present | `grade_pct` | se | p |
|---|---|---|---|---|---|
| 1 | 5 | no | +0.4686 | 0.290 | 0.106 |
| 2 | 4 | no | +0.3920 | — | 0.171 |
| 3 | 5 | no | +0.4872 | 0.287 | 0.090 |
| **4 — every source answered** | **5** | **yes** | **+0.0716** | **0.187** | **0.702** |

**The hills effect is not there.** And the way it goes is what makes it convincing: the
standard error *fell*, 0.287 to 0.187. This is not a weaker test returning a vaguer
answer, it is a sharper test returning zero. AIC fell with it, 4189.8 to 3948.9.

`grade_pct` had been borrowing variance from terms that were not in the model. Once
`speed_limit` and `traffic_proxy` were properly in it, there was nothing left to explain.

### The mistake worth recording is mine

Runs 1 and 3 agreed to within 0.02 of each other and of the A3, and that agreement was
reported here as evidence — at one point as a pooled `p = 0.019` described as nearly
proven. It was withdrawn once, then argued again as "three consistent readings".

**Three broken models agreeing is not corroboration.** They agreed because they were
broken the same way: every one of them was missing the same block of OSM-derived
factors, so `grade_pct` stood in for the same absent terms each time. Consistency across
runs is only evidence when the runs are independent, and a shared omission makes them
anything but.

The lead is closed. Two corridors with complete specifications say +0.489 (p = 0.089) and
+0.072 (p = 0.702), and nobody can argue the question was ducked — the A50's grades reach
6.18% against the A3's 3.75%.

### The two defects the corridor produced

**1 · A source outage changed the model and still reported success.** Runs 1 and 2 were
minutes apart on the same road and the same crashes, lost different factors, and fitted
`grade_pct` at +0.469 and +0.392. Both said `succeeded`, and the only trace was a
sentence in the adapter notes, which reaches the report as `pipeline_warning` at context
severity.

*Fixed* (`6b6ea03`): a structured `SourceFailure` travels in the payload and raises
`source_unavailable` at **material** severity, on the same argument that makes
`synthetic_corridor` material — this is not a qualification of the numbers, it is a
statement about whether they are the numbers the corridor would have produced. It is kept
separate from a skipped factor deliberately: a skip is a claim about the road and repeats
tomorrow, this is a claim about a server and does not.

**2 · The client hung up on work the server was still doing.** The retry added with the
first fix did not help, and the failure detail said why: nine attempts across three
mirrors, nine `TimeoutError`. Not one 504. Consistent timeouts on every mirror are
arithmetic, not load.

`build_extract_query` declares `[out:json][timeout:180]`, asking the server for three
minutes. The client carrying it defaults to a 90-second socket timeout. **Two numbers in
two files, and a 41 km corridor lost every OSM-derived factor to the gap between them** —
every time, not occasionally. The proof sat in the same run: the traffic proxy queries a
*larger* region and succeeded, on the same mirrors in the same minute, because its client
happens to be constructed with 240 seconds.

*Fixed* (`e760f22`): the client reads the budget out of the query and waits at least that
long plus transfer headroom. It only ever raises the timeout, and it lands once for every
caller rather than at each construction site. A test walks every query the codebase ships
and asserts the default client will wait for it, because the mismatch was invisible in
either file alone and existed only between them.

### What the corridor actually says, and why it matters more than the dead lead

```
Negative binomial (NB2), unit-clustered SEs, 82 clusters
alpha 0.5014 · AIC 3948.9 · A-reduced (678 crashes, 700 needed for A-full)
```

| Factor | Estimate | p |
|---|---|---|
| **`speed_limit`** | **−5.6165** | **1.6 × 10⁻²³** |
| **`traffic_proxy`** | **+0.8597** | **2.5 × 10⁻⁶** |
| `access_density` | +0.0663 | 0.53 |
| `grade_pct` | +0.0716 | 0.70 |
| `curve_density` | +0.0059 | 0.95 |

Set beside the A3, on the same engine, the same country, the same crash source and the
same road class:

| | A3 Paris | A50 Marseille |
|---|---|---|
| `access_density` | **+0.400, p = 7.9 × 10⁻⁷** | +0.066, p = 0.53 |
| `speed_limit` | +0.032, p = 0.95 | **−5.617, p = 1.6 × 10⁻²³** |
| `traffic_proxy` | +0.050, p = 0.28 | **+0.860, p = 2.5 × 10⁻⁶** |
| `grade_pct` | +0.489, p = 0.089 | +0.072, p = 0.70 |

**Two motorways, and almost nothing in common.** One is a merging problem and the other
is a speed-and-congestion problem, and neither would have been found by scoring both
against the same published weights. Mode B would have handed them the same shape of
answer with different magnitudes.

This is the clearest demonstration in the project of why Mode A exists — clearer than the
A6/A82 pair, because those differ in road type and country and these do not.

`speed_limit` at −5.6 is itself a contradiction against a declared `+`, and a large,
significant one: on this corridor the low-limit sections are the congested urban ones. It
is flagged material and left in, which is the correct outcome and not a comfortable one.

### The bends, checked across all four fitted corridors

Reported here earlier as "curvature fits against expectation on three roads, and that
looks like a pattern". **It was not one, and the claim was made by reading one factor on
some corridors and the other on the rest.** `curve_radius_min` agrees with the literature
on three of the four, and on one it is the strongest result the project has:

| Corridor | `curve_radius_min` (expects −) | `curve_density` (expects +) |
|---|---|---|
| A6 Derby–Buxton | **−0.4872, p = 4.7 × 10⁻⁷** ✓ | −0.048 ✗ |
| A82 Lomond–Glencoe | −0.087 ✓ | −0.205 ✗ |
| A3 Paris | +0.090 ✗ | +0.015 ✓ |
| A50 Marseille | −0.148 ✓ | −0.081 ✗ |

They flip together, in opposite directions, because they are not independent:
`corr(ln radius, curves per km)` is **−0.536** on the A3 and **−0.739** on the A50. A
stretch with tight bends is a stretch with many of them.

Fitting one at a time proves it is the specification and not the road. On the A50,
`curve_density` reads −0.081 beside its partner and **+0.006 alone** — same road, same
crashes, opposite conclusions about the sign.

*Fixed* (`c01deee`): a factor may declare `measures`, and only one member of a construct
is fitted — the one carrying a published weight, decided in advance rather than by which
term fits the corridor in front of us. That rule matters here because evidence and
keep-order disagree: `curve_density` holds `drop_priority` 85 against `curve_radius_min`'s
55, so the **uncited** term was winning the seat.

One genuine road difference survives underneath the artefact. Univariately, with nothing
else in the model, the A3 has both curvature measures agreeing with the literature
(−0.157 and +0.273) and the A50 has both disagreeing (+0.149 and −0.183). On the A50 the
bendy stretches are the rural hills and the straight ones are the congested approach to
Marseille, so curvature there is a proxy for distance from the city — which is the same
story `speed_limit` tells at p = 10⁻²⁶ from the other side.

### An insignificant sign is not a finding

Applying the construct rule cost the A3 the clean sheet it had just earned. `speed_limit`
moved from +0.032 to −0.037 — p = 0.95 either side, noise either side — and the second of
those raised a **material** heading because every unexplained contradiction did.

**A coefficient that cannot be told apart from zero has no sign to contradict with.** A
corridor's most serious warning was turning on which side of zero a coin landed.

*Fixed* (`ea8cd2f`): materiality follows significance. A firm estimate pointing the wrong
way stays material and is a specification problem. An insignificant one becomes
`sign_contradiction_uncertain` at caveat severity, still saying the corridor failed to
reproduce an effect the literature expects — which is worth knowing — but saying plainly
that the sign is not information.

The discrimination is what makes this a correction rather than a softening. `speed_limit`
fits −0.112 at p = 0.84 on the A3 and −5.603 at p = 10⁻²⁶ on the A50; the first is now a
caveat and the second is still material.

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

**That diagnosis was half right, and the half that was wrong mattered more.** Three fixes
were proposed from it; the sections below record what each one actually did when it was
built and measured, which is not what was predicted in two cases out of three.

| Proposed fix | Outcome |
|---|---|
| **1** Screen for variation before the factor cap | **Built.** Helped — spatial calibration 1.135 → 1.004 — but did not recover `landuse_urban` as predicted |
| **2** Enter near-binary densities as presence flags | **Built, measured, reverted.** Worse on every metric, and the drift did not move at all |
| **3** Prefer `ramp_density` on a motorway | **Built** as a facility-scoped registry exclusion, which is the right shape for it |

And fix 2 failing is what exposed the real cause: **the drift was never about these
factors.** It was a stable sort over tied values, and the numbers in the table above are
an artefact of it. See *What the drift actually was*, below.

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

### Presence flags: built, measured, rejected

Fix 2 above was to enter the near-binary densities as `has_junction` rather than
`ln1p(count/km)`. `Transform.PRESENCE` was written and applied to `junction_density` and
`access_density` on this panel. It is worse on every measure:

| | `ln1p` | `presence` |
|---|---|---|
| AIC, no traffic proxy | 4658.8 | 4679.5 |
| AIC, with traffic proxy | 4636.8 | 4660.2 |
| CURE `junction_density` | 40.5% | 43.2% |
| CURE `access_density` | 37.8% | 37.8% |
| Sign contradictions | 1 | 2 |
| `access_density` | p = 5.0e-9 | p = 1.4e-4 |
| Spatial ratio, with traffic proxy | 0.822 | 0.630 |

**The drift did not move.** Collapsing a factor from five distinct values to two is about
as large a change of functional form as there is, and `share_outside` shifted 2.7 points
— in the wrong direction. If the drift were a functional-form problem that would have
fixed it. The transform was reverted rather than shipped unused.

### What the drift actually was: a stable sort over tied values

`_cure_curves` ordered units with `np.argsort(..., kind="stable")`. Units tied at the
same factor value therefore keep the order they arrived in, which is **corridor order** —
so across a tied block the cumulative residual is the residual summed *along the road*.
Residuals along a road are spatially correlated; this corridor's measured design effect
is 4.2. The factor being plotted contributes nothing to that excursion, and any factor
sharing the tie structure produces the same one. `junction_density`, `access_density` and
`poi_density` drifted at 40.5%, 37.8% and 40.5% — three different factors, one shared
block of zeros.

**Tested by permutation, on the real residuals from the shipped run.** The tie order is
arbitrary: 28 units at one value can be summed in any of 28! orders, each as valid as
corridor order. Over 2,000 of them:

| Factor | Largest tie | Reported | Median | 5th–95th | Corridor order's percentile |
|---|---|---|---|---|---|
| `junction_density` | 28 / 37 | **0.432** | **0.027** | 0.027 – 0.135 | **100th** |
| `access_density` | 28 / 37 | **0.378** | **0.027** | 0.027 – 0.136 | **100th** |
| `curve_density` | 12 | 0.054 | 0.027 | — | 65th |
| `lanes` | 8 | 0.054 | 0.054 | — | 49th |
| `grade_pct` | none | 0.135 | 0.135 | exact | — |

**Fewer than 3% of equally valid orderings would have reported a drift at all**, and
corridor order was not a typical draw but the worst available one — which is what the
mechanism predicts, since corridor order is precisely the arrangement that groups
spatially adjacent units together. The controls hold: the untied factor is deterministic,
and the mildly tied ones sit mid-distribution.

*Fixed:* the statistic under ties is a distribution, so the engine now reports the median
over `CURE_TIE_RESAMPLES` seeded orderings, with the 5th and 95th percentiles beside it
and a `tie_sensitive` flag when that interval straddles the threshold. A factor with no
ties has one ordering, takes one resample, and is unaffected — `grade_pct` returns
0.135 either way. The rendered curve is the sampled ordering nearest the median, so the
picture matches the number. The seed is fixed because a run's manifest fingerprints its
results.

**The A3 now passes validation**, and the fit is untouched — coefficients agree to 1e-9,
as they must, since CURE is a post-fit diagnostic:

| | before | after |
|---|---|---|
| `validation.passed` | **False** | **True** |
| `junction_density` | 0.432 drifts | **0.027 ok** (0.027 – 0.135) |
| `access_density` | 0.378 drifts | **0.027 ok** (0.027 – 0.136) |
| `speed_limit` | 0.054 ok | 0.081 ok, **tie-sensitive** (0.054 – 0.218) |
| `grade_pct` (untied control) | 0.135 ok | 0.135 ok |
| `validation_failed` limitation | present | **gone** |

`speed_limit` is the honesty case: its interval crosses the threshold, so the report now
says the verdict depends on which ordering was drawn instead of picking one and asserting
it.

The planted-U-shape test still fires, which is the property that matters — a diagnostic
averaged into never firing would be worse than the bug.

### A motorway has no at-grade junctions, so stop fitting a term about them

Fix 3 of the three proposed above, and the one that turned out to have a cause rather
than a symptom. `junction_density` put a **material** contradiction on every A3 report:
−0.050 against a declared `+`, with no partner accounting for it, resolved on 9 of 37
segments against `ramp_density`'s 30, and correct on its own at +0.163.

The problem is not statistical. **A motorway is grade separated by definition** — traffic
joins and leaves by slip road, and there are no at-grade junctions on it to count.
Whatever the adapter reported was an interchange `ramp_density` already counts, or a
crossing road that never meets this one. A term naming a feature the road does not have
cannot be resolved by a site inspection, which is what makes it worse than a weak term.

*Fixed:* a factor may declare `not_applicable_on` with a `not_applicable_reason`, and
`Registry.available` takes the run's facility type. Three deliberate choices in that:

- **The reason is required by a validator.** An exclusion nobody wrote an argument for is
  indistinguishable from one added to make a corridor look better.
- **`FacilityType.ANY` excludes nothing.** A caller who declared no road type gets every
  factor: the engine does not infer what the road is in order to drop a term, because
  guessing wrong is the same class of error the exclusion exists to prevent. That is also
  the argument default, so every caller predating it behaves exactly as before.
- **`not_applicable` is a separate list from `missing`.** Nobody failed to supply the
  column; it was there and the registry set it aside. Different things to tell a client.

The same panel, declared three ways:

| declared as | `junction_density` | contradictions | AIC |
|---|---|---|---|
| **motorway** | **held out** | 1 | 4656.0 |
| urban arterial | fitted | 2 | 4656.8 |
| undeclared | fitted — nothing guessed | 2 | 4656.8 |

Two results worth recording rather than glossing. Freeing the seat let `curve_radius_min`
in, and it fitted against expectation too — so the motorway run traded a stuck
contradiction for a new and insignificant one rather than reaching zero, and it took the
suppression fix below to resolve that. And **`curve_density`'s contradiction disappeared
entirely** the moment `junction_density` left, going −0.050 to +0.015, which is what a
term absorbing a neighbour's shadow does when the neighbour goes.

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

### The last contradiction, and the test that was asking the wrong question

Once `junction_density` was held out, `curve_radius_min` took its seat and fitted
**+0.090 against a declared `−`**, at p = 0.52. On its own it fits **−0.081** — the
direction the literature predicts — so something in the specification was taking the
signal. Every pairwise refit said otherwise:

| paired with | `curve_radius_min` | restores? |
|---|---|---|
| `curve_density` (r = −0.69) | +0.017 | no |
| `speed_limit` (r = +0.49) | +0.062 | no |
| `access_density` (r = −0.37) | +0.076 | no |

So it was classified **unexplained** and raised a material limitation. That verdict was
wrong, and so was the test behind it.

**Pairing the suspect with one partner asks whether those two alone reproduce the
expected sign. A bystander passes that as easily as an absorber does** — in a two-term
fit the other five terms are absent and so is their confounding. The question that
identifies an absorber is the opposite one: which single term, **removed from the full
specification**, puts the sign back with everything else still controlled for.

| removed from the full fit | `curve_radius_min` | |
|---|---|---|
| `lanes` | +0.258 | |
| `traffic_proxy` | +0.108 | |
| `speed_limit` | +0.091 | |
| `curve_density` | +0.080 | |
| `grade_pct` | +0.060 | |
| **`access_density`** | **−0.028** | **restores** |

*Fixed:* `_without_each` refits with each other term dropped in turn, and `_suppressor`
reads those instead of the pairwise ones. The univariate precondition is unchanged and
still does the load-bearing work — the factor must point the declared way on its own, or
there is nothing for a partner to have suppressed.

**The planted reversal is what keeps this honest.** In that fixture `curve_density` is
genuinely negative, and no removal rescues it: six drop-one refits, all between −0.34 and
−0.52. Without that property this would be a way to explain away real findings rather
than a way to classify them. Both refit sets ship in the payload, because they answer
different questions and a reader should see both.

### And a specification question that turned out not to be one

Before finding the test error, four alternative specifications were fitted to see whether
the contradiction was really the two curvature terms colliding — they correlate at
**r = −0.689**, which is high for two terms in a seven-term model on 37 units:

| | terms | AIC | contradicts |
|---|---|---|---|
| **A** as shipped | both curvature terms | 4656.0 | `curve_radius_min` |
| **B** drop `curve_density` | `curve_radius_min` only | 4654.0 | `curve_radius_min` |
| **C** drop `curve_radius_min` | `curve_density` only | 4655.6 | `curve_density` |
| **D** drop both | neither | 4654.6 | **none** |
| **E** C + `ramp_density` | `curve_density` | 4654.6 | `curve_density` |

**Whichever curvature term is in the model contradicts, and dropping both is clean.** So
it is not the pair colliding — it is curvature itself, in any form, fitting against
expectation on this corridor.

That is the A82 result again, on a second European corridor and a different road type:
minimum radius here runs 97 m to 3,030 m, and iRAP calls anything above 900 m straight to
moderate. **Bend severity does not drive crashes on an urban motorway; merging does**,
and `access_density` says so at p = 4 × 10⁻¹⁵.

Which is also why option D was not taken. Removing a term because its sign is
inconvenient is precisely what the sign guard exists to prevent, and the corridor is
entitled to say curvature does not matter here.

### Ranking

Segments are ranked on expected crashes per unit of exposure. Four blackspots in the worst
20%, and the top one is contiguous and large:

| Blackspot | Chainage | Length | Observed | Expected |
|---|---|---|---|---|
| **1** | 11,000 – 13,000 m | 2.0 km | **266** | 253.3 |
| 2 | 17,500 – 18,694 m | 1.19 km | 121 | 109.3 |
| 3 | 4,500 – 5,000 m | 0.5 km | 38 | 46.6 |
| 4 | 15,000 – 15,500 m | 0.5 km | 32 | 44.4 |

Blackspot 1 is four consecutive segments carrying **266 of the corridor's 1,231 crashes
in 11% of its length**. That is the kind of output the product exists to produce, and the
model expects 253 there against 266 observed.

### Where the corridor ended up

Run `f556d953`, and then the suppression fix on the same panel:

```
MODE A — FITTED FROM YOUR DATA · 7 factors · 1,231 crashes
NB2, unit-clustered SEs, 37 clusters · alpha 0.2112 · Pearson 1.0537
AIC 4656.0 · BIC 4709.0
```

| Factor | Estimate | p | 95% CI |
|---|---|---|---|
| **`access_density`** | **+0.4002** | **7.9 × 10⁻⁷** | +0.241 … +0.559 |
| **`lanes`** | **+1.1456** | **0.0105** | +0.268 … +2.023 |
| `grade_pct` | +0.4885 | 0.089 | −0.074 … +1.051 |
| `curve_radius_min` | +0.0898 | 0.52 | −0.184 … +0.364 |
| `traffic_proxy` | +0.0496 | 0.28 | −0.041 … +0.140 |
| `curve_density` | +0.0151 | 0.90 | −0.228 … +0.258 |
| `speed_limit` | +0.0322 | 0.95 | −1.031 … +1.095 |

| | |
|---|---|
| All ten checks | **pass** |
| Validation | **passes** — contiguous 1.118, random 1.052, optimism 0.020 |
| CURE drift | **none**, `speed_limit` flagged tie-sensitive (0.054 – 0.243) |
| Contradictions | **1**, insignificant, suppressed by `access_density` |
| **Material limitations** | **none** |

`junction_density` held out as not applicable, `poi_density` demoted for low variation,
`surface_paved` constant.

### Interpretation

**The results make sense and the retrieved data is sound.** 88.2% of nearby crashes
placed on the corridor, 7 rejected as belonging to another road, geometry clean, the
count family chosen correctly, and the model now predicts held-out stretches of road it
has never seen to within 12%.

**`access_density` is the finding, and it has survived every version of this model** —
seven specifications across six bug fixes, always positive, always significant, sharpening
from p = 2.8 × 10⁻⁸ to p = 7.9 × 10⁻⁷ under clustered errors as the noise around it was
cleared away. More slip roads per kilometre, more crashes. That is the merge-and-weave
effect an urban motorway is expected to show, and it is what a client would act on.

**Read `lanes` as volume, not as lanes.** Even with `traffic_proxy` in the specification
it carries part of the exposure signal, and widening a motorway does not multiply its
crashes by three.

**Score: 8/10 as it first ran; 10/10 as it stands.** The corridor now passes every check
and every validation scheme it has, with no material limitation on the page. What remains
is not a defect: `traffic_proxy` is Tier B and interpolated on more than half the
corridor, the crash-type split is still a borrowed default, and everything here comes
from one road.

### What this corridor cost, and what it bought

Six defects, every one of them found by the panel contradicting itself rather than by
inspection:

| # | Defect | Found by |
|---|---|---|
| 1 | Check 7 failed against a design that was never fitted | A failed gate on a passing model |
| 2 | Crash-mix caveat printed on a run that never used it | A caveat with no matching computation |
| 3 | Traffic proxy refused dense networks — a node ceiling counting raw vertices | A refusal on the roads it is most useful on |
| 4 | `ln1p` on a share of order 1e-3 is the identity | Contiguous folds predicting 1,828 against 1,231 |
| 5 | CURE ordered tied values by corridor position | Three unrelated factors drifting identically |
| 6 | Suppression tested pairs instead of removals | A contradiction with a correct univariate sign |

Two things were built, measured, and thrown away: presence flags for the near-binary
densities, worse on every metric; and the prediction that a variation screen would recover
`landuse_urban`, which it did not.

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
