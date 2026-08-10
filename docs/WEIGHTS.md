# Mode B Weights — Sources, Derivations and Selection

Every weight in the factor registry: where it came from, the arithmetic that turned a
published multiplier into a registry weight, the context it is valid in, and how the
engine chooses between sources that disagree.

**Regenerate everything:**

```bash
python tools/derive_weights.py            # report
python tools/derive_weights.py --yaml     # registry-ready fragments
```

Not one number below was chosen. Two tests enforce that in both directions: the registry
may not drift from the script, and no weight may be introduced by hand that the script
does not produce.

---

## The rule that shapes all of this

**A weight is not a number. It is a number plus the context it is valid in.**

The first sourcing pass shipped bare numbers with citations, and every caveat that
followed traced to the same gap: nothing recorded the facility type, region, crash
severity or crash scope a weight was estimated for, so US rural two-lane injury-crash
coefficients were applied to any corridor anywhere, silently.

Each weight now declares:

| Field | Why it exists |
|---|---|
| `family` | `hsm`, `irap` or `elvik` — which body of evidence |
| `facility_type` | Restricted weights are **inadmissible** elsewhere |
| `region` | Never a filter, always a reported concern |
| `severity` | A fatal weight must never score an injury panel |
| `scope` | Total crashes vs run-off/head-on — different quantities |
| `assumes` | Derivation conditions, checked against the actual run |
| `caveat` | An intrinsic limitation, surfaced on every run |

---

## Provenance — read this before trusting any HSM number

The HSM equations were verified verbatim against the **NCHRP draft text for the second
edition of the Highway Safety Manual**, which reproduces Chapter 10 with the equation
numbering used here. Each was additionally checked against the worked examples in that
same document, and the arithmetic reproduces the published answers exactly.

`tests/test_published_equations.py` writes each equation out a second time, independently
of the derivation script, and asserts the published worked-example answer. If the script
and the test ever disagree, one of them misread the manual.

**This is not the same as checking the book.** Two gaps remain:

1. It is the **draft** 2nd-edition text, not a licensed copy.
2. **HSM 2nd edition (2024) is published and changed Parts C and D.** Some Chapter 10
   content may be superseded. Nothing here is edition-pinned to a verifiable artefact.

Closing this needs a licensed AASHTO HSM. It is on the open-decisions list in `STEPS.md`
and it is cheap — one afternoon with the book.

This is also the reason **iRAP is the preferred family**: it is free, openly documented,
global, and — unlike HSM CMFs and the Power Model, which are treatment-effect constructs
being repurposed — **cross-sectional by construction**, which is exactly what Mode B
does.

---

## Why a derivation is needed at all

Published CMFs and risk factors are **multipliers**. The registry needs **log-scale
coefficients on transformed columns**, so that a Mode B weight sits on the same scale as
a Mode A coefficient. That is what makes *"Mode B is the prior, Mode A is that prior
updated by data"* a fact about the code rather than a slogan.

A multiplier `c` corresponds to a log-scale contribution of `ln(c)`. Where the
relationship is already log-linear the coefficient falls straight out. Otherwise
`ln(multiplier)` is fitted against the declared transform by least squares over a stated
range, with R² reported.

**Band midpoint rule.** Sources state multipliers per band with the top band unbounded.
One rule throughout: interior bands use their true midpoint; the unbounded top band uses
`threshold + half the width of the band below`. HSM's ">6%" becomes 7.5; iRAP's ">10%"
becomes 11.25. A rule beats a preference, and it must be the same rule for both.

---

## The weights

Thirteen weights across eight factors. **Eight are global**, which is what makes the
tool usable outside North America.

| Factor | Family | Weight | Fit | Facility | Region | Severity | Scope |
|---|---|---|---|---|---|---|---|
| `speed_limit` | elvik | **+1.6000** | exact | any | global | injury | total |
| `speed_limit` | elvik | **+4.1000** | exact | any | global | fatal | total |
| `operating_speed_85` | elvik | **+1.6000** | exact | any | global | injury | total |
| `operating_speed_85` | elvik | **+4.1000** | exact | any | global | fatal | total |
| `surface_paved` | irap | **−1.0986** | exact | any | global | all | total |
| `curve_radius_min` | irap | **−0.7232** | R² 0.938 | any | global | all | run-off/head-on |
| `curve_radius_min` | hsm | **−0.1855** | R² 0.878 | rural 2-lane | N. America | all | total |
| `grade_pct` | irap | **+0.4863** | R² 0.795 | any | global | all | run-off/head-on |
| `grade_pct` | hsm | **+0.1212** | R² 1.000 † | rural 2-lane | N. America | all | total |
| `access_density` | hsm | **+0.1658** | R² 0.965 | rural 2-lane | N. America | all | total |
| `lit` | irap | **−0.1398** | exact | any | global | all | intersection |
| `lit` | hsm | **−0.0817** | exact | rural 2-lane | N. America | all | total |
| `roadside_hazard_score` | hsm | **+0.0668** | exact | rural 2-lane | N. America | all | total |

† Three points, two fitted parameters. Near-saturated and not evidence of anything; the
source table is.

Every weight agrees with the `expected_sign` declared from mechanism before any source
was looked up. That is validated at load, per weight — one bad source cannot slip in
behind a good one.

---

## The crash-type decomposition

Published weights are **crash-type specific**. iRAP prices grade for run-off and head-on
crashes; it prices street lighting for intersection crashes. Summing those into one
number treats a run-off-only weight as though it moved every crash on the road.

So the score is built per crash type and then combined:

```
log_score[type] = sum of  w_j * x_j    for weights scoped `type` or `total`
combined        = sum of  share[type] * exp(log_score[type])
row score       = ln(combined)
```

**A `total`-scope weight enters every bucket**, so a registry of only total-scope
weights produces *exactly* the score it did before this existed. The change is a strict
correction, not a re-scaling — there is a test asserting it. The final `ln` keeps the
result on the Mode A coefficient scale, so the prior/posterior correspondence survives.

A scoped weight is diluted by its share. With `run_off_head_on` at 64.3%, a weight
contributing +0.8 to that bucket alone contributes
`ln(0.643·e^0.8 + 0.357) = +0.55` to the combined score, not +0.8.

### The buckets, and where the shares come from

`TOTAL` is a marker, not a bucket. The four buckets partition all crashes exactly once,
so shares sum to one and nothing is double-counted or lost.

| Bucket | Share | Built from HSM Table 10-4 (fatal & injury, rural two-lane) |
|---|---|---|
| `run_off_head_on` | **64.26%** | ran off road 54.5 + overturned 3.7 + head-on 3.4 + opposite-direction sideswipe 2.66 |
| `other` | **24.64%** | animal 3.8 + other single-vehicle 0.7 + rear-end 16.4 + same-direction sideswipe 1.14 + other multi-vehicle 2.6 |
| `intersection` | **10.00%** | angle collision |
| `pedestrian` | **1.10%** | collision with pedestrian 0.7 + with bicycle 0.4 |

Source: AASHTO HSM Table 10-4, *Default Distribution by Collision Type for Specific Crash
Severity Levels on Rural Two-Lane, Two-Way Roadway Segments*, fatal-and-injury column,
HSIS Washington 2002–2006.

The fatal-and-injury column is used rather than all-severity because the registry's speed
weights are injury-specific.

**This default carries the same regional transfer problem as any other HSM number**, and
the engine says so on every run that uses it. Supplying a local crash-type distribution
is one of the cheapest improvements available — most crash databases can produce it
directly. `uniform_mix()` exists for callers who genuinely have no defensible split and
would rather say so than borrow Washington State's.

### Why this matters beyond correctness

The ranking now carries a score column *per crash type*. A unit that ranks badly can be
read for **which** problem it has — a run-off problem and an intersection problem call
for different countermeasures, and a single combined number hides which one it is.

---

## Selection

Given several weights for one factor, the engine picks one. It never averages.

**Admissibility** is strict on the two dimensions where the wrong weight is a
*correctness* error rather than a transfer approximation:

- **Facility type** — a weight restricted to one facility is inadmissible on another.
  `any` is admissible everywhere.
- **Severity** — a fatal weight must never score an injury panel. 1.6 versus 4.1 is a
  factor-of-two error, not a nuance.

**Region is deliberately not a filter.** Filtering on it would leave almost nothing
admissible outside North America, which helps nobody. Instead it is the *first* ranking
dimension, with three tiers:

| Distance | Meaning |
|---|---|
| **0** | Estimated in this region. Best available. |
| **1** | Estimated globally. Built to travel, so a fair second. |
| **2** | Estimated in a *different* named region. Usable, but it is someone else's road system — and it is reported as a concern every time. |

**Ranking order:** region distance → exact facility beats `any` → exact severity beats
`all` → family preference (iRAP → HSM → Elvik) → source, for determinism.

**Region is first on purpose.** Facility mismatch is already handled by admissibility, so
that dimension only separates "exact facility" from "unrestricted" — and unrestricted is
not *wrong*, merely less specific. Region transfer is the largest single error source in
Mode B. A global weight that happens not to name a facility type is a better bet for a
Cyprus corridor than a US rural two-lane weight that names one exactly.

**Worked example.** The same panel, assessed as a rural two-lane road in three places:

| Factor | Europe | North America | Middle East |
|---|---|---|---|
| `grade_pct` | **+0.4863** iRAP (global) | **+0.1212** HSM (local) | **+0.4863** iRAP (global) |
| `lit` | **−0.1398** iRAP (global) | **−0.0817** HSM (local) | **−0.1398** iRAP (global) |
| `speed_limit` | +1.6 Elvik (global) | +1.6 Elvik (global) | +1.6 Elvik (global) |
| `access_density` | +0.1658 HSM ⚠ reached | +0.1658 HSM | +0.1658 HSM ⚠ reached |

A Cyprus corridor takes the global weights. Where no local or global source exists the
American weight is still used — dropping the term would be worse — but every such reach
is flagged.

`access_density` is now the only remaining ⚠ on a non-US corridor among the factors this
panel carries, down from three before the iRAP Reference Guide was sourced. Each global
weight added removes one more.

**Consequence worth knowing:** an undeclared run admits only unrestricted weights. On
the shipped registry that is one factor. Declaring `--facility-type rural_two_lane
--region north_america --severity injury` admits four. The engine will not guess what
kind of road it was handed.

---

## Agreement

Where two or more admissible weights exist for one factor:

- **Different `scope`** → not comparable, no score. HSM prices total crashes; iRAP's
  grade factor prices run-off and head-on. An agreement score between them would compare
  different quantities.
- **Different sign** → score 0 and a flag. *(Unreachable through a registry — the
  `expected_sign` validator rejects a contradicting source at load. Kept as defence in
  depth.)*
- **Otherwise** → `min(|w₁|, |w₂|) / max(|w₁|, |w₂|)`.

The selected weight always comes from the selection rule. Agreement is *reported*, never
used to average.

**`grade_pct` is the worked example.** HSM says +0.12 for total crashes on US rural
two-lane roads. iRAP says +0.49 for run-off and head-on crashes globally. Four times
apart, and **not in conflict** — they answer different questions. Averaging them would
produce a number neither source supports. The engine keeps both, marks them
not-comparable, and prints both.

---

## Assumption checks

Two weights were derived under conditions the run may not match. Both declare them, and
the engine warns when the run differs by more than 25%:

| Weight | Assumes | Why it matters |
|---|---|---|
| `curve_radius_min` | `segment_length_km: 0.5` | HSM Eq. 10-13 depends on curve length, so the weight is tied to the segmentation. Change the segmentation and regenerate it. |
| `access_density` | `reference_aadt: 10000` | The source CMF depends on AADT, which Mode B does not have. |

`segment_length_km` is **measured** from the panel, not declared, so the check cannot be
gamed by declaring a convenient value.

---

## Per-weight detail

### `roadside_hazard_score` — HSM +0.0668, exact

> CMF₁₀ᵣ = e^(−0.6869 + 0.0668 × RHR) ⁄ e^(−0.4865)

Since −0.6869 + 0.0668 × 3 = −0.4865 exactly, this reduces to
`ln(CMF) = 0.0668 × (RHR − 3)`. No linearisation, no range, no assumption beyond the
scale. **Check:** RHR 4 → 1.069, published example 1.07.

*Units:* HSM roadside hazard rating, integer 1–7, base 3. A vision model emitting its own
0–1 score must be mapped onto RHR first, and that mapping belongs in the report.

### `lit` — HSM −0.0817, exact

> CMF₁₁ᵣ = 1.0 − [(1.0 − 0.72 × pᵢₙᵣ − 0.83 × pₚₙᵣ) × pₙᵣ]

Table 10-12 (2U): pᵢₙᵣ = 0.382, pₚₙᵣ = 0.618, pₙᵣ = 0.370 → CMF 0.9216 → weight
ln(0.9216). A fully lit rural two-lane segment carries ~8% fewer total crashes.

*Caveat:* those proportions are Washington State HSIS data 2002–2006. Night-crash share
varies enormously by country; replacing them with local values is cheap and high-value.

### `speed_limit` / `operating_speed_85` — Elvik +1.6 (injury), +4.1 (fatal), exact

Power Model `N ∝ V^k`, so `ln(N) = k·ln(V)` and the weight *is* the exponent.

**The split is the fix.** The Power Model relates *operating* speed to crashes. Applied
to `operating_speed_85` it carries no caveat at all. Applied to `speed_limit` it is an
upper bound, because posted limit moves operating speed by materially less than 1:1 —
and that weight declares a permanent `caveat` saying so, surfaced on every run.

Deflating the posted weight would need a transfer coefficient nobody has published for
*cross-sectional* ranking (the 25–50% figures in the literature are before-after, a
different quantity). Inventing one would be worse than declaring the limitation.

Measuring operating speed on even one corridor remains the single highest-value
calibration available to Mode B.

### `grade_pct` — HSM +0.1212 / iRAP +0.4863

HSM Table 10-11: 1.00 / 1.10 / 1.16 for ≤3%, 3–6%, >6%, midpoints 1.5 / 4.5 / 7.5.
iRAP: 1.0 / 1.2 / 1.7 for <7.5%, 7.5–10%, >10%, midpoints 3.75 / 8.75 / 11.25.

*Units:* absolute grade in percent. Neither source distinguishes upgrade from downgrade.

### `curve_radius_min` — HSM −0.1855, R² 0.878

> CMF₃ᵣ = (1.55 × L_c + 80.2⁄R − 0.012 × S) ⁄ (1.55 × L_c)

Fitted over 50–1600 m assuming a 0.5 km segment fully in curve, no spiral. **Check:**
0.1 mi / 1,200 ft → 1.431, published example 1.43.

*Weakest fit in the registry* — a `1 + c/R` relationship is only roughly log-linear, so
it under-weights very tight curves. Declared as a caveat. *Units:* metres.

### `access_density` — HSM +0.1658, R² 0.965

> CMF₆ᵣ = [0.322 + DD × k] ⁄ [0.322 + 5 × k],  k = 0.05 − 0.005 × ln(AADT)

Fitted over 3–20 accesses/km at AADT 10,000. **Check:** DD 6 @ 10,000 → 1.012, published
example 1.01. *Units:* accesses per **km**, both sides; the mile conversion is inside the
weight.

---

## Still uncited — 14 factors

Each factor's `notes` in `factors.yaml` records its own reason. Summary:

| Factor | Why not |
|---|---|
| `traffic_proxy` | Our own construct. No published weight exists for graph centrality, and the HSM AADT exponent does not transfer precisely because this is not AADT. |
| `junction_density` | HSM models intersections as separate entities with their own SPFs; iRAP prices intersection type per intersection. Neither prices junction *frequency* along a segment. |
| `curve_density` | Both sources price curve *severity* via radius, not curve *frequency* per km. |
| `ramp_density` | **Deliberate.** The sign inverts on M51 and is not diagnosable on one corridor. Sourcing a weight before the sign is understood would lend false confidence to a term known to behave badly. |
| `lanes` | Both sources price lane *width*, not *count*. |
| `median_present` | **Best next candidate.** HSM Chapter 11 divided/undivided SPFs, and iRAP prices median type directly. |
| `sidewalk_present` | FHWA and iRAP both price this for *pedestrian* crashes. Enters with scope `pedestrian`, which needs a severity-aware index first. |
| `roadside_object_density` | iRAP prices roadside severity as *nearest object* and *distance to it*, not object density per km. A mapping decision, not a lookup. |
| `sight_distance_proxy` | iRAP prices it binary (adequate/poor) at intersections; our factor is continuous metres along a segment, with no published threshold to map between them. |
| `poi_density`, `population_density`, `building_density`, `night_ratio` | No standard published weight on a comparable scale. |

### What the iRAP Reference Guide could and could not source

The Guide was obtained and worked through. It publishes numeric risk factor tables per
attribute, per crash type, per road user. Four weights came out of it — grade, curvature,
skid resistance and street lighting. Several attributes were examined and **deliberately
not used**, which is worth recording so nobody re-treads it:

| Attribute | Published values | Why not used |
|---|---|---|
| **Sight distance** | Adequate 1.0, Poor 1.42 | Binary adequate/poor, and for vehicle occupants it prices *intersection* crashes. Our factor is continuous metres along a segment. The Guide gives no metre threshold, so any mapping would be invented. |
| **Number of lanes** | 1 lane 1.00, 2 lanes 0.02, 3 lanes 0.01 | Head-on-overtaking crashes only, where more lanes means less overtaking into oncoming traffic — a 50× drop. Our `lanes` factor is a volume proxy for *total* crashes under a length×duration exposure, expecting the opposite sign. Different mechanism, different scope; sourcing it would be wrong and the `expected_sign` validator would reject it. |
| **Median type** | 0 – 100 across 14 categories | These are median *traversability* values on a 0–100 scale, one multiplicand of the Star Rating Score, not a CMF. Using them as log-scale weights needs the surrounding SRS normalisation, which is a bigger piece of work. Best remaining candidate. |
| **Intersection type** | 6 – 30 per intersection | Per-intersection likelihood factors, not per-km density. Our `junction_density` is per km. Not transferable without replicating how iRAP aggregates intersections into a segment score. |
| **Road condition** | Good 1.0, Medium 1.2, Poor 1.4 | A genuine attribute we do not have a column for. `surface_paved` is sealed/unsealed, a different question. Adding it needs a new factor and an adapter to feed it. |
| **Speed** | Published as *curves*, not tables | The Guide plots five risk curves rather than tabulating them. Speed already has global coverage via Elvik, so nothing is lost. |

**One finding worth carrying into the report.** The Guide states that iRAP uses the
*same* risk factors for posted speed limit and 85th-percentile operating speed, and by
default takes `max(operating speed, speed limit)`. That does not remove the caveat on our
posted-speed weight — the Elvik exponent is still an operating-speed quantity, and taking
a maximum is not the same as substituting one for the other — but it does show a
respected global methodology treating posted limit as a legitimate input to a speed risk
curve.

**Best remaining candidate:** `median_type`, which needs the SRS traversability
normalisation understood first.

---

## Sources

- [NCHRP draft text for the second edition of the Highway Safety Manual](https://onlinepubs.trb.org/onlinepubs/nchrp/nchrp_wod_297Draft.pdf) — Chapter 10. Equations 10-13, 10-17, 10-20, 10-21 and Tables 10-11, 10-12 verified verbatim and checked against the worked examples in the same document.
- [FHWA-HRT-17-098, *Self-Enforcing Roadways: A Guidance Report*, Chapter 2](https://www.fhwa.dot.gov/publications/research/safety/17098/003.cfm) — reproduces the Elvik (2009) Power Model exponents (Table 1): 1.6 injury, 4.1 fatal, 4.6 fatalities, 2.2 injured road users, for rural roads and freeways.
- Elvik, R. (2009), *The Power Model of the relationship between speed and road safety: update and new analyses*, TØI Report 1034/2009, Institute of Transport Economics, Oslo. Cited via FHWA above; the report itself was not retrieved.
- **iRAP Methodology Reference Guide v3.10** — the source for grade, curvature, skid resistance and street lighting risk factors, each read from its published attribute table with crash types and road-user groups stated. Available free after registration at [resources.irap.org](https://resources.irap.org/Key-documents/); attribute fact sheets are also linked from [irap.org/methodology](https://irap.org/methodology/). The Guide is a licensed document — `references/` is gitignored so it can be kept locally and never redistributed.
- [FHWA CMF Clearinghouse — HSM resources](https://cmfclearinghouse.fhwa.dot.gov/resources_hsm.php) — for cross-checking CMF provenance.
