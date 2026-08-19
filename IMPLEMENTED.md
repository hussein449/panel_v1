# Implemented

What has actually been built, in the order it was built. Planned work lives in
[`STEPS.md`](STEPS.md); this file only records what exists and works.

---

## 2026-08-17 (latest) — Step 3.3a: credible intervals, and a wrong diagnosis caught late

**Delivered:** the Bayesian rung. A negative-binomial GLMM with a random intercept per
unit, reporting **credible intervals instead of p-values**, and estimating σ_u — the
between-segment spread rungs 1 and 2 could not measure at all.

```bash
roadrisk demo --units 40 --periods 12 --bayes
roadrisk assess panel.csv --bayes
python tools/validate_posterior.py
```

**Verified:** 573 tests pass (28 new), `ruff check` clean.

### What the environment forced, and what it did not

PyMC was the chosen engine and it installed cleanly. It cannot **sample** here: there is
no C++ compiler, so PyTensor falls back to pure Python, and a 320-row toy model did not
finish 200 draws in ten minutes. The usual escape — PyTensor's Numba backend — is
blocked by a Windows **Smart App Control** policy that refuses unsigned native DLLs.
`nutpie` and JAX ship native binaries and would meet the same wall.

Turning that policy off was declined, correctly: it cannot be re-enabled without
reinstalling Windows. So the requirement — credible intervals, non-negotiable — had to
be met in pure Python, and it was.

Two side-findings worth keeping. The same policy blocked `rasterio` earlier in the
session and cleared about twenty minutes later once Microsoft's reputation service
caught up, so **`--rasters` has been intermittently broken on this machine**. And this
repository lives in a OneDrive-synced folder, which locks files mid-sync; that corrupted
numpy during an install (repaired) and left stale git worktree metadata that would not
delete.

### The method: integrate the segments out, approximate what is left

A 120-unit corridor has 120 random intercepts, which is a 130-dimensional problem.
Integrating each one out by Gauss-Hermite quadrature — one 1-D integral per unit, all
independent given the hyperparameters — leaves about ten parameters. That is the
strategy INLA is built on, and the brief names INLA as acceptable for this rung.

What remains is small enough for a Laplace approximation: find the posterior mode, take
the curvature there, draw from the resulting Gaussian, and re-weight the draws by the
true posterior. **The weights are also the honesty meter** — even weights mean the
approximation held, one weight carrying everything means it did not. Pareto-smoothed
importance sampling and its k-hat statistic, so the check is part of the fit rather than
a ritual somebody has to remember.

### An inference ladder, with receipts

Same shape as the mode ladder and the rung ladder: try the cheap good thing, test it,
descend, and say so.

1. **Laplace + importance check**, escalating quadrature nodes — seconds
2. **MCMC**, warm-started from the Laplace mode *and its covariance* — minutes
3. **Refuse** — nothing reported

Two gates on step 1, not one: k-hat ≤ 0.7 *and* ≥ 400 effective draws. k-hat says the
shape was right and says nothing about whether enough draws survived to place an
interval endpoint. A fit at k-hat 0.67 kept 256 draws of 4,000 and its 2.5% endpoints
visibly disagreed with a long MCMC run whose means it matched to 0.02. A mean is easy; a
tail is what the draws are for.

### The wrong diagnosis, recorded because it nearly shipped

Step 1 refused every wide panel — k-hat 0.76–0.84 at eleven parameters against 0.58 at
eight. The obvious reading was **dimension**: importance sampling really does lose
efficiency exponentially as dimension grows, the numbers fit that story, and nine
combinations of proposal degrees of freedom and scale inflation failed to rescue the
eleven-dimensional case. It was about to be written into the docstring as a property of
the method, with a table.

It was **quadrature error**. Every one of those runs used twelve nodes.

| | k-hat, 12 nodes | k-hat, laddered |
|---|---|---|
| A-reduced, 5 factors (8 dims) | 0.58 | **0.24** |
| A-full, 8 factors (11 dims) | 0.76–0.84 | **0.07–0.32** |

Dimension was never the binding constraint. The marginal likelihood settles to the eye
long before it settles to the precision importance weights need — a weight is a ratio of
two log-posteriors, so error invisible in the fit is not invisible in the weights, and
it accumulates across units.

**The tell was there and I read past it: more data made things worse.** Dimension does
not explain that. Accumulating per-unit error does. A plausible mechanism that predicts
the observed numbers is not therefore the mechanism — which is the same lesson this
package's sign guard exists to teach about coefficients.

The node count is now the first thing the ladder escalates, because adding nodes costs
seconds and descending to MCMC costs minutes. Step 2 now almost never runs. It stays,
because "almost never" is not "never".

### Verified against a slower method that fails differently

k-hat is a good meter, not a perfect one: it measures whether the importance weights
behave, not whether the answer is right. So `tools/validate_posterior.py` runs both
rungs on the same planted panel:

```
Laplace + importance sampling: 6.0s    k-hat 0.18, 5,295 effective draws of 8,000
MCMC reference, 16,000 draws:  330s    R-hat 1.002, 18,224 effective draws

term              planted      MCMC   Laplace    diff           Laplace 95%  truth
speed_limit        +0.900   +0.3734   +0.3652  -0.008  [-0.415, +1.152]  IN
curve_density      +0.250   +0.4179   +0.4196  +0.002  [-0.152, +0.996]  IN
junction_density   +0.300   +0.4083   +0.4069  -0.001  [-0.198, +0.979]  IN
sigma_u            +0.500   +0.6584   +0.6686  +0.010  [+0.493, +0.896]  IN
alpha              +0.600   +0.5960   +0.5965  +0.000  [+0.407, +0.819]  IN

Largest disagreement between the two rungs: 0.0101
Planted values outside the fast rung's 95% interval: 0 of 5
The fast rung was 55x quicker.
```

**The reference is pinned to the fast rung's quadrature node count**, which is not a
detail. Node count defines *which* marginal posterior is being approximated, so a
reference run at a different one is answering a slightly different question and any
disagreement is partly its own doing. The first version of this tool compared 24 nodes
against 48 and would have blamed the approximation for the difference.

`fit_mcmc_reference()` exists for exactly this and is deliberately not wired into the
engine: now that the node ladder makes step 1 succeed on everything tried, the ordinary
entry point never reaches step 2, and a caller who wanted slower, noisier answers with
the same intervals would be choosing badly.

### The log posterior got a third faster, and the validator stopped timing out

Chasing why the validator could not finish inside a ten-minute window turned up two
things in the hot loop, both worth fixing on their own merits — that array is
`walkers x rows x nodes` and it is the whole cost of the slowest path.

**Three transcendental functions where one would do.** `mu` was `exp(eta + offset)`, then
both negative-binomial terms took their own logarithm. But `exp(a + b)` is
`exp(a) * exp(b)`, so the exponential can run over `(walkers, rows)` and
`(walkers, nodes)` separately and their product is a multiply; and `log(mu)` never needs
recovering from `mu`, because `eta + offset` *is* `log(mu)` and it is already in hand.
Both NB terms are then differences against a single `log(r + mu)`. Verified identical to
the old spelling to 2.3e-13 on values of order 1,000 — machine precision.

**A fixed chunk of 16 walkers.** An ensemble of 24 went through as 16 and then 8, and the
second call paid nearly a full call's overhead for half a call's work. The batch is now
split by an element budget instead, so a short corridor does its whole ensemble in one
call and a long one is still bounded.

| | per iteration | 16,000 draws |
|---|---|---|
| before | 41.7 ms | 11.1 min |
| one transcendental instead of three | 34.0 ms | 9.1 min |
| plus element-budget chunking | **27.4 ms** | **7.3 min** |

Every Bayesian fit is a third quicker, and the validation tool now completes in the
foreground rather than being killed part-way through its reference run.

### The dispersion trap, closed by a test

PyMC parameterises the negative binomial as `var = mu + mu²/alpha`; statsmodels and this
package use `var = mu + alpha·mu²`. Passing one for the other produces a dispersion
wrong by a factor of `alpha²` and nothing complains. The convention is asserted by a
test on a panel with a planted α, not trusted to a comment.

### `--bayes` chooses how, never what

`assess()` still exposes no way to force a mode or a rung — that rule is about data
adequacy, and a caller who could overrule it would. Choosing an estimator is a different
question, and a test keeps it different: the same panel returns the same mode, the same
rung and the same factor list under either. NB2 stays on the result beside the
posterior, because it is the comparison every reviewer expects to see cited.

### What is not built

- **3.3b — registry weights as priors.** The priors are weakly informative `Normal(0,1)`
  today, not the registry's cited weights. `core/weights.py` already does the hard half.
  The trap when it lands: `expected_sign` must be a *soft* prior, never a constraint, or
  the sign guard becomes structurally incapable of firing.
- **3.3c — spatial CAR/BYM.** Blocked in a specific way, written up in `STEPS.md`: the
  quadrature works *because* units are independent, and a spatial field couples them.
  The Laplace machinery generalises to it; the quadrature cannot.

---

## 2026-08-17 — A second corridor, and what it proved was not enough

**Delivered:** `tools/validate_corridor.py`, a named registry of real roads the pipeline
can be re-run against, and **the second corridor** — Dutch **N201** — chosen by
measurement against the criterion `STEPS.md` has carried since Stage 2.

```bash
python tools/validate_corridor.py          # N201, the second corridor
python tools/validate_corridor.py B9       # the first one, as a control
python tools/validate_corridor.py --list
```

### Chosen by measuring, not off a map

The criterion was already written down: *"pick one where access density and ramp density
separate — the M51 ramp/RAF inversion is not diagnosable on a single corridor."* That is
a measurable property, so five real roads were fetched and measured against it.

| Road | Units | access only | ramp only | both | r |
|---|---|---|---|---|---|
| **N201** (NL) | 67 | **18** | **15** | 5 | **−0.06** |
| JO 15 (Jordan) | 107 | 13 | 33 | 7 | −0.06 |
| A1 (CY, divided) | 137 | 8 | 34 | 14 | +0.14 |
| N247 (NL) | 52 | 28 | 1 | 4 | +0.08 |
| B9 (CY) — the first corridor | 50 | **36** | **0** | 1 | −0.03 |

**B9 could never have settled it.** Zero units carry a ramp and no access; one unit of
fifty has a ramp near it at all. `ramp_density` is very nearly constant there, and a
constant column is dropped before fitting. The open decision was right, and now it is
right with a number attached.

N201 wins on the units in the *single-mechanism* cells — 18 with accesses and no ramp,
15 with a ramp and no access. It runs from open polder into the edge of Amsterdam, so
the two mechanisms genuinely occur apart from each other. Measured on the corridor,
**VIF 1.00 and 1.00**: as close to orthogonal as real data offers.

**And VIF is the wrong test here, which the tool found out by getting it wrong.** B9
also scores 1.00 and 1.00 — because `ramp_density` barely varies there, and a column
that barely varies is uncorrelated with everything. A near-constant column is not an
independent one. The counts in the single-mechanism cells are the honest test, so that
is what decides, and the tool now prints `SEPARATES` or `DOES NOT SEPARATE` and refuses
to read anything into a VIF of 1 next to an empty cell.

Jordan's Desert Highway separates nearly as well and is in the actual target market. It
was not chosen because OSM carries no `maxspeed` along it, so the panel loses
`speed_limit` — but it is kept in the registry with that written down, because a
corridor that exposes a coverage gap in the target region is worth more than a tidy one
once there is crash data to go with it.

### The live run

```
810 vertices  ->  33.50 km  ->  67 units  ->  1,608 panel rows
snapped 506 of 600 (84.3%)
11 of 13 factors resolved
MODE A — FITTED FROM YOUR DATA · 5 factors · 506 crashes   (rung A-reduced)
```

Two factors refused and said why: `sidewalk_present` (10% of the corridor tagged,
below the 50% floor) and `median_present` (no way states the tag anywhere). Flat country
after a mountain road, and 67 units against B9's 50 — the pipeline handled a corridor of
a completely different character without a change.

### What the second corridor proved, and what it did not

It proved the separation exists. Then it produced a finding nobody was looking for:

```
ramp_density did NOT reach the fit, and the reason matters:
  Attempted A-full. Failed crash count: 506 available, 700 required.
  Stepped to A-reduced (5 factors). Dropped: building_density, lit,
  ramp_density, curve_radius_min, poi_density — by registry priority.
  'ramp_density' is 8 of 10 by the registry's declared drop_priority (50).
```

**`ramp_density` is eighth. A-full keeps seven.** So on a corridor where every
higher-priority factor resolves, `ramp_density` is shed before fitting *at every rung of
the ladder* — not for want of crashes, but because the registry ranks seven other
factors above it and A-full stops at seven.

That is a real limit on the open decision and it was invisible with one corridor.
**Separation in the data is necessary and not sufficient.** To diagnose the ramp/access
inversion, all three have to hold: a corridor that separates them (N201 does), enough
crashes to buy the terms (real data, not these), and a specification that actually
carries `ramp_density` — which today means fitting it deliberately rather than waiting
for the ladder to include it.

### The crashes are synthetic, and the run says so three times

Nobody has given us a police extract for the N201. What this validates is the geometry
and adapter path — fetch, stitch, project, segment, snap, twelve Tier A factors, fusion,
provenance — and the shape of the design matrix that comes out. The sign guard reports
contradictions on three factors, and the tool states plainly that this is expected: the
synthetic crashes carry no true effect, so every fitted sign is noise and about half
point the wrong way. The mode banner is a statement about the pipeline, not the road.

**The critical path has moved, not closed.** It is no longer "find a second corridor".
It is "get real crash data for one".

---

## 2026-08-17 — Step 3.2: the spline that hunts the U-shape

**Delivered:** rung 3. A penalised spline on any one factor, everything else linear,
producing a shape, a plot and a verdict — and structurally incapable of producing a
number that could reach a client.

```bash
roadrisk demo --u-shape curve_density
roadrisk assess panel.csv --shape curve_density
```

**Verified:** 545 tests pass (46 new), `ruff check` clean.

### The mechanism, and why the other four diagnostics cannot see it

The sign guard has hunted contradictions since 1.6 with four diagnostics — the factor
alone, the factor beside each correlated partner, the correlation matrix,
leave-one-unit-out. Every one of them hunts the brief's **first** suspect, confounding:
they ask which *other term* the wrong sign lives with.

None of them can see the third. A linear term forced through a U-shape has no
correlated partner to blame — the specification itself is the fault, and every one of
those four diagnostics comes back clean. The brief puts the mechanism plainly:

> Reality is plausibly a U-shape: dead-straight is dangerous (speed, fatigue), gentle
> curve is fine, sharp curve is dangerous. **A linear fit through a U-shape can return a
> negative coefficient — exactly the M51 symptom.**

Now the guard runs the spline on every contradiction, and the answer is one of two
useful things: *this is why*, or *this is not why, look at the other two suspects*.

### The defect it had, and how it was caught

The first version chose its smoothing penalty by AIC. On a panel whose curvature effect
was **planted linear**, it drew an inverted U and reported it.

That is the worst failure this module could have. A diagnostic that finds a bend
whenever it is asked would "explain" every sign reversal ever put to it, and it is worse
than no diagnostic, because its answer is the one that stops people looking.

The grid told the truth even when AIC did not:

| Penalty | Linear panel (truth: monotonic) | Planted U (truth: a U) |
|---|---|---|
| 0.1 | **inverted U** ← AIC's pick | U |
| 1 | increasing | U |
| 10 | increasing | U |
| 100 | increasing | decreasing |
| 1000 | increasing | decreasing |

One penalty of five found a bend in noise; three of five found a U that was really
there. **So the headline is the shape the grid agrees on**, the curve drawn is the
best-fitting fit that agrees with it, and every penalty's answer is reported either way.

A cluster-aware information criterion was tried first — charging `ln(units)` per
parameter instead of 2, on the reasoning that AIC over a panel over-fits for the same
reason rung 1's intervals were too narrow. It was measured and abandoned: the effective
degrees of freedom differ by ~3 between penalties while the deviances differ by 20–100,
so it changed the chosen penalty on **none** of the test panels. The problem was never
the accounting.

### The band is a cluster bootstrap, because 3.1 said so

A spline's nominal confidence band would be too narrow here for exactly the reason rung
1's intervals were: every factor is a property of a segment repeated down every period.
Having paid for that correction three days ago, drawing a naive band now would be
undoing it in a new place.

So the band comes from resampling **units** with replacement and refitting, and it
produces a better headline than a band: *the same shape came back on 40 of 40 corridors
resampled by unit*. A turn that a majority of resamples do not reproduce is refused as
an explanation — `explains_contradiction` requires it, and a test pins that.

### An interaction between the two rungs worth recording

On the planted-U panel, `curve_density` fits **−0.203**. Naively that is p < 0.001. With
3.1's clustering it is **p = 0.16**.

Both rungs are right, and together they say something neither says alone: 120 units
cannot resolve this effect, *and* the reason the linear term points the wrong way is
that the relationship bends. The sign guard keys on the sign rather than on
significance, so the spline still runs — which is correct. A wrong sign that cannot be
dismissed as noise and cannot be confirmed either is precisely when the shape is worth
knowing.

### What the fixture taught

`synthetic_panel(u_shaped=...)` plants a genuine bowl. Where the bowl's vertex sits
turned out to be a real trade-off rather than a free parameter:

| Vertex at | Linear coefficient | Shape found |
|---|---|---|
| 60th percentile | −0.05 | U |
| **65th** | **−0.16** | **U** |
| 70th | −0.46 | decreasing |
| 80th | −0.90 | decreasing |

**The more lopsided the bowl, the stronger the reversal it produces and the less
visible the U becomes.** At the 80th percentile four fifths of the corridor sits on one
arm and "decreasing" is the honest reading of the curve. The diagnostic and the defect
it hunts get harder to see together, which is worth knowing before trusting a clean
result on a real road.

### What it refuses

- **Fewer than 20 distinct values.** `speed_limit` takes five on a demo panel; five
  points is not a curve. Every factor here is unit-constant, so this is a statement
  about how many units the corridor has, and it is said that way.
- **A factor not in the fitted specification.** Named in a warning, never ignored.
- **A turn inside the outer 15% of the range**, or one whose arms recover less than a
  quarter of the curve's span. Splines are least constrained at their edges and will
  turn up there for free.

### The plot is text, deliberately

```
        partial effect on ln(crash rate), centred
  +1.01 |.
        |..
        |*****...                             ..
        |......**..                       ...*****
   0.00 |----------**----------------****---------
        |           .***.........****...
  -0.53 |               .........
        +-----------------------------------------
         0.20              1.03               1.86
         curve_density, transformed scale
```

`core` depends on pandas and statsmodels and nothing else, the CLI is the only surface
this project has, and a plot nobody can see without installing a plotting stack is not a
plot. The curve travels as data on `ShapeCurve` — x, y, and the bootstrap band — which
is the seam the HTML report in 4.1 will draw a real chart from.

### It cannot ship a number, and that is asserted

`ShapeDiagnostic` has no coefficient, no standard error, no p-value, no predicted count
and no interval. Not by convention — by type, the same guarantee `IndexResult` gives in
the other direction. `linear_estimate` is the shipped fit's own number, carried for
comparison and never computed here. A test enumerates the forbidden attribute names and
fails the moment one appears, and the serialised payload puts the curve under
`reference`, never under `fit`.

### What is deferred

The brief's rung 3 has a second half: *"use to diagnose, then convert the finding into
an interpretable term for the shipped model."* The conversion is **not built**. When the
spline finds a U the verdict names the fix — split the factor at the turning point, or
carry it as two terms — and a human does it. Automating that means letting a diagnostic
rewrite the specification it was checking, which needs the turning point to be stable
enough to define a breakpoint on; on 120 units it is not, and the resampling is what
says so.

---

## 2026-08-14 — Step 3.1: standard errors that account for the panel

**Delivered:** rung 2 — NB2 with standard errors clustered by unit. On a panel with
realistic segment-level heterogeneity the intervals widen by up to **3.9×** and two
factors lose their significance.

```bash
roadrisk demo --unit-dispersion 0.5
```

**Verified:** 499 tests pass (21 new), `ruff check` clean.

### Why this matters more here than in most panels

Every factor is **unit-constant**. Curvature, gradient, lane count, every density — each
is a property of a segment, repeated unchanged down every period of that segment. A
120-unit corridor over 24 months has 5,760 rows and **120 independent observations of
each covariate**. Rung 1 computed its intervals as though it had 5,760.

`panel.py` has said so since Stage 2 — *"the effective sample size for such a factor is
the number of units, not the number of rows; plain NB2 does not know that, which is the
argument for the random-intercept rung"* — and this is that rung.

| | Naive p | Clustered p | Interval |
|---|---|---|---|
| `access_density` | < 0.0001 | **0.65** | 3.86× wider |
| `junction_density` | < 0.0001 | **0.05** | 2.90× wider |
| `curve_density` | < 0.0001 | 0.03 | 3.00× wider |

`access_density` moving from p < 0.0001 to p = 0.65 is the brief's warning reproduced
exactly: *"this alone may change the geometry p-value."* It was never significant. The
first fit was counting one segment forty-eight times.

### The coefficients do not move, and that is the point

Only the covariance changes, so the report prints **both standard errors side by side**
with the ratio between them:

```
factor              β        SE naive   SE panel      ×
access_density   +0.0645       0.0370     0.1429   3.86
junction_density +0.2848       0.0501     0.1456   2.90
```

A correction nobody can see the size of is a correction nobody believes. Rung 1's
standard errors are kept on the result for exactly this, and a test pins the arithmetic:
the ratio of the two columns is the widening factor.

It also means the correction can neither create nor hide a sign reversal, so the sign
guard is untouched. Its diagnostic refits deliberately still use the uncorrected fit —
they read point estimates only, which clustering does not move, so the clustered fit
would cost a second optimisation to return identical answers. Every p-value the guard
*reports* comes from the shipped, corrected fit.

### The intervals are honest, and that is measured rather than asserted

The obvious objection to any correction that widens intervals is that it might just be
widening them. The synthetic panel's coefficients are *planted*, so the question is
answerable: a 95% interval promises that across many datasets the true value lands inside
it 95% of the time.

Sixty panels, both models, counting how often the planted truth was inside:

| | rung 1 | rung 2 |
|---|---|---|
| Segments have character (realistic) | **70%** | **95%** |
| Segments all alike (nothing to fix) | 94% | 91% |

The first row is the defect quantified: rung 1 promised to be wrong 5% of the time and
was wrong 30% of the time. `poi_density` was inside its own 95% interval on **57%** of
panels while printing p < 0.0001.

The second row is the control. Where the rows genuinely are independent, rung 1 was
already honest and the correction does not inflate it past nominal — a correction that
widened regardless would show up there as coverage climbing above 95%, intervals too
wide, which is its own kind of wrong.

Kept as `tools/validate_coverage.py`, and as three tests that fail if rung 1 ever stops
being overconfident or rung 2 ever stops delivering its 95%.

### Below twenty units the correction is declined, loudly

The sandwich estimator is consistent in the number of *clusters*, not of rows. Below a
couple of dozen units it is biased downwards: it would report intervals that are still
too small while appearing to have fixed the problem, and the caveat would become
invisible — which is worse than not applying it at all.

So it is refused, and refusing is not a reason to stop describing the problem. The run
states the effective sample size, estimates how much too narrow the intervals are, and
says significance on that corridor is unproven. **The M51, with seven units, is exactly
this case** — the corridor this project keeps referring back to, and now the one the gate
was written for.

Between twenty and forty clusters the correction is applied and declared unreliable.

### A fixture weakness this exposed

`synthetic_panel` drew its overdispersion **per row**. That makes each observation of a
segment independent, which is not what a panel is — and on that fixture rung 2 correctly
found almost nothing to correct, widening intervals by 1.0×.

Real segments carry persistent unobserved traits: a bad junction layout, a school, poor
drainage. A fixture without them lets every model fitted to it look better than it would
on a road.

**It is now on by default**, and the caution about flipping it turned out to be
unfounded: all 499 tests pass either way. The estimates still recover their planted
values, the signs are still correct, and the sign guard is still clean — the NB
dispersion parameter simply rises from 0.64 to 1.13 as it absorbs some of the
segment-level variance. `--unit-dispersion 0` restores the old behaviour, and on that
setting the correction correctly finds almost nothing.

One recovery gets visibly worse: `access_density` is planted at +0.20 and comes back at
+0.06. That is not a regression, it is the point — with 120 segments and realistic
heterogeneity that effect is not identifiable, and the clustered p-value of 0.65 says so.
The old fixture reported it as p < 0.0001.

### What is deferred, and why

This is **not** the random-intercept GLMM the step names. A random intercept models the
heterogeneity between segments and changes the *estimates* as well as their spread;
clustering corrects the spread only.

The brief calls rung 2 a *"cheap upgrade"* and MCMC is not cheap — PyMC, convergence
diagnostics, minutes per run, and a whole reporting surface for posterior summaries.
Step **3.3** already requires that dependency for the Bayesian hierarchical model, so the
GLMM belongs there, paid for once. The step stays `[~]` rather than being declared done.

---

## 2026-08-14 — Step 2.9: the geographic cache

**Delivered:** `roadrisk.geo.cache` and `.cached`. A second corridor in the same region
costs **1.2 seconds against 55.5**, validated live on two real Cyprus roads.

```bash
roadrisk corridor --ref B9 --bbox 34.80,32.80,35.05,33.05 --osm --traffic --cache .cache
```

**Verified:** 478 tests pass (31 new), `ruff check` clean, and the step's own done-when
demonstrated end to end by `tools/validate_cache.py`.

| | Time | |
|---|---|---|
| B9, cold cache | 55.5 s | the first corridor pays |
| E601 — a *different* road, same region | 1.2 s | cache hit |
| B9 again | 1.1 s | cache hit |

### The rounding belongs to the adapter, not the cache

The first version rewrote the bounding box inside the Overpass query text as it passed
through the caching wrapper. It worked, and it was wrong in a way worth recording: it
meant a run *with* a cache fetched a different region from a run without one. **A cache
that changes the answer is not a cache** — it is a second code path nobody tests. It also
put string-parsing of somebody else's query language into the caching layer.

The strategic-network query is now built from a grid cell in the first place. Two
corridors in the same county produce a byte-identical query on their own, cached or not,
and `cached.py` went back to being a dictionary with a clock.

### The grid size was measured, and it is a real trade

At a tenth of a degree the second corridor **missed**. B9 and E601 are a few kilometres
apart and, with the 20 km margin already applied, their padded boxes still differed by
more than one cell. That is the whole failure mode of quantisation: too fine and nothing
ever collides.

Half a degree shares. The price is that the first corridor fetches a 1° × 1° region
rather than a snug one — 55.5 s against the 11.8 s a tight box took. That is the trade
the brief asks for in as many words: *"a second corridor in the same country is nearly
free"* is a claim about the second corridor, not the first. It is also mildly good for
the measure itself, since a wider network cuts off fewer of the through-routes
betweenness is trying to count.

### A cache must never make a run look fresher than it is

Everything else in this package exists to stop a number looking more certain than it is,
and a silent cache is the same failure in different clothes: a run quietly built on a
three-month-old road network while presenting itself as today's assessment.

So every entry records when it was fetched, every hit is counted, and the age of the
oldest thing used travels into the run's warnings next to the values it produced. Past a
fortnight the note stops being a date and becomes an instruction to clear the cache.
Expiry is per source, because the sources age differently — OpenStreetMap changes daily,
Mapillary changes when somebody drives past with a camera, and Copernicus DEM is a fixed
product that will never change again.

### A defect a test caught before the network could

`FileCache.put` called `mkdir` outside its `try`, so a cache directory that could not be
created — a read-only volume, a file already sitting at that path — raised and killed the
run. A cache that cannot write should cost a run its speed and nothing else. Found by the
test asserting exactly that, and fixed by moving one line.

### PostGIS is deliberately not built

The other half of this step is persistence, and the step's own note already explains why
it moved here from 2.1: *persistence is a Stage 5 concern*. Nothing in the pipeline needs
a database today — a corridor fits in memory, the CLI is single-user, and there is no
multi-tenant story until 5.4. A schema written now would be guessing at what the API
wants, and it would put a service dependency into a package whose entire shape is "runs
with no network and no API key". It lands with 5.1, against real requirements.

---

## 2026-08-10 — Step 2.8: Tier B, and a gate against measuring the window

**Delivered:** `traffic_proxy` from graph centrality, with a window-artefact gate, and
`roadside_object_density` from Mapillary detections.

```bash
roadrisk corridor centreline.csv --crashes crashes.csv --osm --traffic --mapillary
```

**Verified:** 436 tests pass (35 new), `ruff check` clean, traffic proxy validated live
on Cyprus B9 at three margins. Mapillary is **not** validated — see below.

### The window is the trap, and the gate is the deliverable

Betweenness is computed over the graph you supply. A graph shaped like a ribbon around
the corridor produces a parabola peaking in the middle of the ribbon — an artefact of
the query, and indistinguishable at a glance from a town on the road. Two defences:

**Fetch a region, not a ribbon.** This is the one OSM fetch in the package that uses a
bounding box rather than the corridor-following `around` filter, and the reason is
methodological rather than cost: through traffic routes through an *area*, and a ribbon
graph has nowhere else to go.

**Then test for the artefact anyway.** The finished proxy is correlated against a
symmetric parabola centred on the corridor. A real town peaks wherever the town is; the
artefact peaks dead centre by construction. Above 0.7 the run says so; above 0.9 the
factor is withheld.

Measured on Cyprus B9:

| Margin | Junctions | Artefact correlation | Peak unit (of 49) |
|---|---|---|---|
| 5 km | 114 | 0.38 | 1 |
| 10 km | 277 | 0.69 | 26 |
| 20 km | 592 | 0.41 | 19 |

**The honest reading is not flattering: the along-corridor pattern is not stable under a
change of window.** It is not that the artefact decays with width — it does not, on this
road — but that an arbitrary analysis choice moves both the shape and where it peaks.
That is the most useful thing this adapter can report about its own output, and it is
why `traffic_proxy` stays uncited and the notes are as loud as they are. The margin
defaults to the widest of the three on the methodological ground that it cuts off fewest
through-routes, not because the number looked better.

The gate is not theoretical: driven through the CLI on a synthetic grid corridor it
refuses at **0.99** and says why.

### A defect the live run exposed: contraction was contracting nothing

The first version walked each OSM way and closed a run at that way's last vertex. That
looks like junction contraction and achieves almost none of it, because OSM splits a
road at arbitrary points — a surface change, a bridge, an editor's convenience — so the
shared ends of consecutive ways are not junctions at all.

Measured: the Cyprus B9 region came back as **483 ways contracted to 480 junctions and
506 links** — one link per way, no contraction whatsoever, while the module's own
docstring claimed contraction was what made betweenness affordable.

Fixed by building the vertex graph first and collapsing chains of degree-two vertices
wherever they run, across way boundaries rather than within them. The same region now
contracts to **114 junctions and 140 links**, a four-fold reduction, and a road split
into fifteen ways collapses to one link — pinned by a test.

This also moved the artefact numbers, which is why the table above supersedes the one
measured before the fix.

### Mapillary: validated against the live API, and it took three defects to get there

Every other source here is keyless, so every other adapter was validated on a real road
straight away. Mapillary needs a free access token, which this environment does not
have — so it was validated by a human running `tools/validate_mapillary.py`, and the
three rounds that took are worth recording because each one hid the next.

**1 · The bounding box was too large.** A 25 km corridor's box is 0.053 x 0.137 degrees,
and the map-features endpoint refuses it. The adapter now tiles *along the corridor* —
not as a grid over the bounding box, because a road is a line and gridding would spend
four requests in five on ground the road never touches. Tile length is computed from
latitude, since a degree of longitude shrinks as you go north.

**2 · The failure said nothing, and my error handling said something wrong.** Mapillary
answers an oversized request with `HTTP 500 "An unknown error occurred"`. The adapter
caught every exception, printed the *type* and guessed `"check the token is valid"` —
sending a real user to look in exactly the wrong place. Twice, in fact: the same habit
then hid a second cause. The client now reads the API's own message out of the response
body, and distinguishes a refusal from a transport failure.

**3 · An empty result is not an empty world.** With a token lacking the `read` scope,
every query returns `HTTP 200 {"data":[]}` — Meta's Graph APIs return empty rather than
erroring on a missing scope. That is indistinguishable from a rural road with no
imagery, which is exactly what the corridor under test *was*. It took a control query
over central Amsterdam to separate the two, and that control is now part of the tool:
`python tools/validate_mapillary.py amsterdam`.

**What the live data then confirmed.** `object--street-light` and
`object--support--utility-pole` come back exactly as spelled in `HAZARD_OBJECTS`;
`object--trash-can` appears and is correctly not counted; geometry is
`{"coordinates": [lon, lat]}`, which is the order the parser assumes; ids are strings,
which is what the de-duplicator keys on. Had any of those been wrong the adapter would
have counted zero on every corridor on earth while looking like it worked.

**And one more thing the live data taught.** The real limit is the volume of the
*answer*, not the area of the *question* — Mapillary's words are "Please reduce the
amount of data you're asking for". So the same tile that is comfortable through farmland
is refused in a city centre. A refused tile now halves itself and retries, up to three
times, rather than the alternative of sizing every tile for Manhattan and firing a
thousand requests at a free API for a rural road.

**What the layer actually contains, versus what the registry hoped.** The registry note
said "poles, trees, walls". Only the first is true: map features are *point* detections
of manufactured objects, because those are what a detector can localise to a point.
Trees and walls are segmentation classes with no point geometry and are not in this
layer at any price. The note is corrected and the objects counted are named in the
source string rather than implied.

### Then the validated run changed the factor's definition twice

Run on the Dutch N200 into Amsterdam — a real arterial in a country with dense coverage —
the chain works end to end: 3,959 features fetched, 1,245 roadside objects, a median of
**93 objects per km** varying 0 to 142 between units, at `medium` confidence throughout
because fusion reads Tier B and caps it without being asked. Ten of the eleven class
names are now confirmed against live data.

But the *first* validated run, over central Amsterdam, produced two corrections that no
synthetic test could have found.

**Signage was 54% of the column, and signage is not a struck object.** Of 1,088
detections, 591 were `object--sign--store`, `object--sign--advertisement`,
`object--sign--information` and `object--banner`. Those hang on building facades or
frangible posts — nothing a vehicle leaving the carriageway hits. What they measure is
shopfront density, which is `poi_density`. Counting them would have shipped two columns
measuring the same thing under different names, **collinear by construction** — the exact
trap the junction/access/ramp partition was built to avoid, walked into somewhere else.
Mapillary cannot distinguish a freestanding billboard on a steel post from a sign screwed
to a wall, so the group is excluded whole rather than half-counted.

**The radius was three times too wide.** At 50 m the factor reported a median of 136
objects per kilometre — one every seven metres, which describes a neighbourhood rather
than a verge, because in a city a 50 m band sweeps the parallel streets. 50 m is right
for POIs and buildings, which measure activity and genuinely extend a block back. It is
wrong for *what you would hit*: the AASHTO clear zone is about 9-10 m. Narrowed to
**15 m** — clear zone plus positional error.

Both corrections are pinned by tests that cite the measured numbers as their reason.

### One limitation this cannot fix from here

A unit reporting zero means *no detections*, which is either an empty verge or an
unphotographed one. Telling those apart needs a second query against the imagery
endpoint to ask whether a camera ever passed. That is not built, so a zero is reported at
the same coverage as any other value and the notes say plainly that it must not be read
as a safe roadside.

### One factor deliberately not derived

The registry declares `mapillary_detections` against `roadside_hazard_score` too. It is
not implemented, on purpose, and the adapter emits a skip entry saying so on every run.

That factor's units are the HSM roadside hazard rating: an integer 1 to 7 whose cited
weight is meaningless on any other scale — the registry says so in its own note.
Mapping poles-per-kilometre onto that scale is a modelling decision requiring a study
that relates the two. Inventing it here would put a fabricated number behind a cited
weight, which is the single worst thing this package could do.

### Tier B is capped at medium confidence, by construction

Nobody stated these values; a model inferred them. Fusion already reads the tier and
tiers anything Tier B as `inferred`, so `roadside_object_density` comes out medium on
every unit without this module asking for it. That is the 2.7 machinery working on the
first factor that needed it.

### Two Tier B factors remain, neither in this step's deliverable

`mapillary_vision` — our own inference on sampled frames, the main cost trap in the
pipeline at 50-150 USD per corridor, and the adapter that would need the poles-to-RHR
mapping study before its output means anything. And `dem_viewshed` for
`sight_distance_proxy`, now cheap to attempt because the elevation sampler from 2.6
already exists.

---

## 2026-08-10 — Step 2.7: fusion, agreement, and a confidence tier

**Delivered:** `roadrisk.geo.adapters.fusion` and `.client`. One value per factor per
unit, the losing source kept and compared, and a confidence tier with a reason for every
factor on every unit.

```bash
roadrisk corridor centreline.csv --crashes crashes.csv --osm --client inventory.csv
```

**Verified:** 401 tests pass (33 new), `ruff check` clean.

### Priority is the registry's, not the code's

`factor.adapters` is an ordered chain — `client_data → Tier A/B → drop` — and the winner
is simply the earliest declared adapter that produced a value. Client data wins because
the registry declares it first, not because anything special-cases it. A test passes the
client source *second* on purpose: if call order mattered, OSM would win.

That is the brief's line "client-supplied data is simply the highest-priority adapter,
same code path, no special case" made literal. `unit_frame`, which raised on a collision
as a placeholder for this step, is gone.

### Client data is authoritative, not infallible

Supplying an inventory does not silently overwrite OSM. It wins, and where the two
disagree the run names the units:

```
⚠  Sources disagree — speed_limit
   'client_speed_survey' won on registry priority; 'osm_maxspeed' disagrees.
   Compared on 16 unit(s) both measured, agreeing on 13 (81%).
   Mean absolute difference 5.62, worst 30.
   Units that differ: …-0006, …-0007, …-0008
   One of the two sources is wrong about them, and nothing here can say which.
```

The client slot is found by **Tier D**, not by matching adapter names. The slots are
named for what is being supplied — `client_survey`, `client_alignment`,
`client_speed_survey` — so name-matching would be fragile, and matching on the `client`
*licence* would wrongly pick up `night_ratio`'s `panel_construction` adapter, which is
Tier A and derived from the panel rather than supplied. A test pins that case.

### Agreement is asymmetric evidence

Two sources matching is **weak** evidence. OSM, Overture and a client inventory can all
descend from the same survey, so agreement may be an echo rather than a corroboration —
the note says so in as many words. Two sources differing is **strong** evidence: at
least one of them is definitely wrong about that unit.

So disagreement pulls a unit's confidence to low, and agreement never promotes one. The
asymmetry is deliberate and tested in both directions.

### A confidence tier per factor per unit

The literal deliverable of 2.7, emitted as a long frame — one row per factor per unit —
and written to `confidence.csv` alongside the panel.

| Tier | Reason | Meaning |
|---|---|---|
| `low` | `carried` | imputed from a neighbouring unit, not measured here |
| `low` | `contradicted` | a second source materially disagrees about this unit |
| `medium` | `thin_coverage` | rests on under half the unit's length |
| `medium` | `inferred` | derived by us rather than stated by anyone (Tier B) |
| `high` | `measured` | measured for this unit by the winning source |

Worst reason wins, with one deliberate ordering choice: `carried` outranks
`contradicted`. A carried value is an imputation, so a second source disagreeing with it
is expected and uninformative — the imputation is the thing to fix. For the same reason
**carried units are excluded from the agreement comparison entirely**: comparing an
imputation measures the imputation, not the sources.

### Two details that only show up on real data

**The disagreement threshold needs a floor.** A relative difference blows up near zero:
0.0 versus 0.1 accesses per km reads as total disagreement when the denominator
collapses. The denominator is floored at a tenth of the factor's own spread across the
corridor, which makes the test scale-free without making it meaningless for factors
that legitimately sit near zero.

**Fusion output is ordered by registry `drop_priority`, not alphabetically.** A
provenance table is read top-down, so it should lead with the factors that matter most —
the same order `roadrisk registry` prints and the ladder retains terms in.

### Registry changes

`client_inventory` declared on `poi_density` and `building_density`. Both are plainly
things a client can supply and neither had a Tier D slot, so a client column for them
had nowhere to go. `population_density` deliberately still has none: census data is open
data the client does not measure, and its blocker is delivery format, not availability.

---

## 2026-08-10 — Step 2.6 finished: the two rasters

**Delivered:** `grade_pct` from the Copernicus DEM, `landuse_urban` from ESA WorldCover,
`building_density` from OSM. Step 2.6 is complete at **12 factors** from three sources.

```bash
roadrisk corridor centreline.csv --crashes crashes.csv --osm --rasters
```

**Verified:** 369 tests pass (28 new, none touching the network or GDAL), `ruff check`
clean, and validated live against Cyprus B9.

### Live on the B9

```
69 fragments -> 25.07 km -> 50 units
12 factors resolved, 3 refused and named
grade_pct      min 1.30%  median 6.12%  max 9.57%
landuse_urban  min 0.00   median 0.00   max 0.55
MODE B — curve_radius_min, grade_pct, speed_limit, access_density
```

A road climbing into the Troodos reading a median 6% gradient is the sanity check that
matters. Flat would have meant the sampler was reading the wrong pixel; nothing would
have meant the tile naming was wrong.

### The baseline is the measurement decision, not the resolution

A DEM's vertical error does not cancel when you difference two nearby pixels — it is
amplified by the short distance you divide by:

```
grade noise  ~  sqrt(2) * vertical_error / baseline
```

At the ~2 m local error Copernicus GLO-30 is specified to, differencing over one 30 m
pixel gives about **9 percentage points** of pure noise — larger than any real highway
grade. Over 200 m it gives about 1.4. The HSM prices grade in bands at 3% and 6%, so the
measurement has to separate 3 from 6; 200 m does, 30 m would have produced a column of
plausible numbers with nothing in it, on a factor that carries a cited weight.

So the baseline comes from the error budget, not from the pixel size, and it is part of
the **definition** of the column — a grade over 30 m and a grade over 200 m are
different quantities. The registry says so, and a test pins it: the same flat road under
2 m of synthetic per-pixel noise must read under 4% at a 200 m baseline and more than
three times worse at 30 m.

### Land cover is sampled beside the road, never on it

WorldCover classifies a sealed road as built-up. Sampling the centreline would have
reported almost any paved corridor as 100% urban — a measurement of the road surface,
not of its surroundings, and a column that would have correlated with `surface_paved`
instead of with land use. Each station is sampled at four perpendicular offsets, 40 m
and 80 m either side, and the centreline pixel is never read. A test builds exactly the
trap: built-up on the line, grassland beside it, must score zero.

### What the live run changed: a 92%-tagged factor was being thrown away

The tag adapter shipped last commit refused any factor with a single unit lacking
evidence. That sounded principled. On the real B9 it discarded **`maxspeed` at 92%
coverage and `lanes` at 84%**, because three and five units out of fifty had none.

That is not caution. The registry's own note records that losing `speed_limit` *biases
what remains* — on the M51, adding speed doubled the curvature coefficient rather than
shrinking it. Dropping a 92%-observed factor to avoid carrying a value across 500 m
trades a small, reported approximation for a large, silent one.

An untagged unit now takes the value of the nearest unit that has one, up to 1,500 m,
reports zero coverage of its own, and is counted in the notes. Beyond that distance the
gap is a different piece of road, not a gap in tagging, and the factor still drops. The
50% corridor floor is untouched, so the change recovers `speed_limit` and `lanes` and
leaves `lit` (32%), `sidewalk_present` (16%) and `median_present` (0%) refused exactly
as before.

### Registry changes this forced

- **A new `landuse_urban` factor.** The brief lists it and `population_density`'s own
  `missing_behaviour` already referred to it; it just had no declaration.
- **`CC-BY-4.0` added to the licence enum.** Copernicus DEM and ESA WorldCover both
  require attribution and neither imposes share-alike. Mapping them onto
  `public-domain`, as the DEM adapter was declared, understated what the client must do.
  The DEM's declaration is corrected, and both adapters put the attribution text in the
  run notes.
- **`osm_buildings` declared on `building_density`.** Microsoft's ML footprints stay
  declared first because they cover the target market better; they are not implemented
  because the dataset ships tens of megabytes of GeoJSONL per quadkey tile and cannot be
  windowed to a corridor. OSM buildings cost one extra clause on a query already being
  made.

### The one Tier A factor with no adapter

`population_density`, and the obstacle is delivery format rather than data. Measured,
not assumed: **WorldPop's global mosaic answers a `Range` request with 200, not 206** —
it ignores the header and streams the whole file — and **GHSL ships deflated zip tiles**
whose members cannot be windowed. Either way one corridor costs a whole-file download,
which contradicts this registry's own instruction on the DEM adapter. It is recorded
under the factor and in the open decisions, with three ways out.

### GDAL is quarantined

`rasterio` is a new `raster` extra and nothing else depends on it — not the engine, not
the OSM adapters, not the test suite. Both raster adapters take an injectable
`PointSampler`, so the tests hand them analytic surfaces and assert that a 5% ramp reads
5%. The only untested code is the HTTP window read, and `tools/validate_rasters.py`
exercises that against the live buckets on a real road instead.

---

## 2026-08-10 — Step 2.6: the adapter contract, and ten more factors

**Delivered:** `roadrisk.geo.adapters` — the seam every source plugs into, and the first
ten factors to come through it. A corridor panel went from **2 factor columns to 12**.

```bash
roadrisk corridor centreline.csv --crashes crashes.csv --osm
```

**Verified:** 341 tests pass (51 new, none touching the network), `ruff check` clean.

### The contract is the deliverable, not the columns

Part Six of the pipeline brief asks each adapter to return *value, source, tier and
licence*. Three rules make that more than a data shape:

**Tier and licence are read from the registry, never asserted by the adapter.** A module
names the slot it fills — `osm_maxspeed`, `osm_graph_nodes` — and the tier and licence
travel from that declaration onto every value. So an adapter cannot promote itself from
Tier B to Tier A, invent a licence, or fill a slot nobody declared. `require_slots` runs
before any work, so a renamed slot fails on the next run rather than on the one corridor
where the tag finally appears.

**A partial column is refused.** A factor resolved for some units and not others changes
which rows the model sees, and the effect looks exactly like a finding.

**An unresolved factor is named, with the reason.** "`surface_paved`: 0% of the corridor
carries the tag" is useful. Omitting the row is not.

Two adapters resolving the same factor raises rather than picking a winner — that is
step 2.7, and guessing here would hide the disagreement 2.7 exists to measure.

### What now resolves

| Source | Factors |
|---|---|
| Centreline geometry | `curve_radius_min`, `curve_density` |
| OSM way tags | `speed_limit`, `lanes`, `lit`, `surface_paved`, `sidewalk_present`, `median_present` |
| OSM graph and POIs | `junction_density`, `access_density`, `ramp_density`, `poi_density` |

Everything except curvature comes from **one** Overpass call. Fanning out one query per
factor would multiply the load on a volunteer-run service by six for data that arrives in
the same response.

### The query follows the road, not its bounding box

Overpass `around` accepts a polyline, so a 25 km corridor asks for a 100 m ribbon rather
than the 25 × 15 km box that encloses it. Through a city that is the difference between a
few thousand elements and a few hundred thousand. The centreline is simplified to 20 m
before it goes in — well below the ribbon width, so simplification cannot move the search
off the road — and the relaxation is reported if a very long corridor forces it.

### Missing tags are not zeros

This is the whole difficulty of the tag adapter and the reason it is 400 lines rather
than 40.

OSM `lit` is absent on most of the target market's roads. Reading absence as "unlit"
would manufacture a lighting effect out of **mapper attention**, and it would point the
direction the registry expects — which is precisely what makes it dangerous. It is the
same failure as the vertex-spacing curvature artefact found last week, in a new place.

So: a sample without the tag is *no evidence*; a unit's value is the mean over the part
of it that is tagged; and a factor is emitted only when every unit has some evidence and
at least half the corridor is tagged. Otherwise it is absent, with the coverage that
failed printed next to it. Nothing is imputed from a neighbouring unit anywhere in this
module.

**The paved-by-default convention is deliberately not applied.** Routers assume an
untagged `highway=primary` is sealed and they are usually right. The iRAP sealed-versus-
unsealed weight is −1.0986, the largest in the registry: usually right is not good enough
when being wrong applies a three-fold risk factor backwards. Explicit tags only.

### The three densities partition the features between them

A T-junction with a residential street is a junction; a driveway is an access; a slip
road is a ramp. Each highway class belongs to exactly one set, so a motorway off-ramp is
counted once and never again.

That matters more than where the boundaries fall. The registry already records that
`ramp_density` and `access_density` correlate at r = 0.365 on the M51 and that the sign
on `ramp_density` inverts between specifications. Counting one feature into two columns
would have *guaranteed* that collinearity rather than merely permitting it — and it would
have looked like a finding about roads. The registry's own description of
`access_density` said "plus minor-road joins"; the note now says why it does not.

Junction degree is computed from vertex coordinates rather than OSM node ids: ways that
meet share a node and therefore share its coordinates exactly, so the answer is identical
and it does not depend on an output field a client or a cache might drop. A vertex
interior to a way contributes two incident edges and an endpoint one, so a road split
into two ways gives degree 2 — correctly not a junction — and a side road ending on it
gives 3.

### A density of zero is a statement about OSM, not about the road

A corridor where nobody mapped the driveways reports zero accesses per kilometre. The
column is then constant, and the engine drops constant columns before fitting, so the
right thing happens — but the *route* matters, and the note says the data was absent
rather than the road being empty. An extract that came back completely empty skips all
four densities instead, because there a zero would mean "not fetched".

### Degrading loudly, twice

A failed Overpass fetch loses the OSM factors and nothing else — the crash counts,
segmentation and curvature survive, and the failure is reported at the top of the run.
Overpass mirrors return 504 under load often enough that a client should not lose their
crash data to a busy volunteer server.

Separately, when fewer than 90% of centreline samples find an OSM road within 20 m, the
run says so: that usually means the centreline is not the road it claims to be.

### What this exposed

Ten new columns is the first time the engine has had a realistic specification to chew
on, and the machinery built for it in Stage 1 came alive without changes: the VIF gate
dropped `curve_radius_min` against `curve_density`, four constant columns
(`lanes`, `lit`, `surface_paved`, `ramp_density` on the test corridor) were dropped
before fitting, and the ladder settled at A-full with five factors. No engine code
needed touching, which is the layering doing its job.

### Still outstanding in 2.6

`grade_pct` from the Copernicus DEM, and the raster context layers — land cover,
population density, building density. They share a problem the whole of the above does
not (reading a cloud-optimised GeoTIFF rather than parsing a tag, and a new optional
dependency to do it) and they land together.

---

## 2026-08-10 — Step 2.2b: fetch the corridor from OSM

**Delivered:** `roadrisk.geo.osm` — a road reference and a bounding box in, an assembled
centreline out. No more manual QGIS export.

```bash
roadrisk corridor --ref B9 --bbox 34.80,32.80,35.05,33.05 --region europe --severity injury
```

**Verified:** 290 tests pass (34 new, none touching the network), `ruff check` clean,
validated live against two real Cyprus roads.

### By reference, not by routing

A routing engine returns the *fastest* path and will leave the road you asked about
without saying so. `ref="B9"` cannot return anything that is not the B9. The brief's
gate — *reject if the route leaves the named road* — becomes unnecessary, and is
replaced by the failure that can actually happen: a scatter of disconnected pieces
rather than a corridor.

### Live results

| | B9 (Troodos, undivided) | A1 (motorway, divided) |
|---|---|---|
| Fragments | 69 | 49 |
| After merge | 3 | 4 |
| Gaps bridged | 2 | 0 |
| Longest share | **100%** | 26% |
| Divided | no | **yes** — 49/49 one-way |
| Result | 25.07 km | 8.11 km, 22.68 km excluded and reported |

### Three bugs, each found by a test or by real data

**1 · Opposing carriageways were being welded together.** The ends of a divided road's
two carriageways sit ~20 m apart — inside any usable gap tolerance. A distance-only
bridger joins them into a line that runs out along one side and back along the other,
doubling the corridor and making every chainage wrong. Fixed with a turn check: a join
whose direction change exceeds 120° is not a continuation.

**2 · The turn check measured the wrong thing.** First version compared the heading of
the *connector* between fragments, which reads the 20 m hop between carriageways as a
90° turn and waves it through. It now compares the two fragments' own headings,
skipping the connector.

**3 · The join index was wrong for prepended fragments.** When the second fragment goes
*before* the first, the weld sits at `len(other)`, not `len(line)`. Measuring at the
wrong index samples the middle of a fragment, where the turn is naturally near zero —
so every bad join passed. This one hid behind bug 2 and only surfaced once that was
fixed.

Bug 3 is why A1 changed from 16.06 km to 8.11 km. The diagnostic settled it: pieces 0
and 1 sit **12.9 m apart at a 179.7° turn** — a carriageway meeting its opposite twin.
The 16 km was a bad weld the index bug let through. 8.11 km is correct.

### Divided roads are detected from the tag, not the geometry

Cyprus A1 returns 49 ways, **every one `oneway=yes`** — which is exactly how OSM stores
a divided road. Its two carriageways are 11 km apart at their furthest, so any
distance-based rule fails precisely where the road is most interesting.

This also forced a second fragmentation threshold. A divided road returns roughly half
its length as the opposite carriageway, so the longest run carries ~50% — and the 0.6
threshold rejected every motorway as "fragmented". Divided roads now use a 0.25 floor,
and always report how much was excluded and why.

### What is still manual

Choosing *which* carriageway is still "the longest one". Selecting a direction
deliberately needs the `oneway` direction plus the user's intent, and the crash table
usually covers both directions anyway — so the honest behaviour for now is to take one,
say so loudly, and let the analyst decide.

---

## 2026-08-10 — Validated on a real road: Cyprus B9

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
