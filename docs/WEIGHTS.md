# Mode B Weights — Sources and Derivations

Every `default_weight` in the factor registry, where it came from, and the arithmetic
that turned a published crash modification factor into a registry weight.

**Regenerate everything:**

```bash
python tools/derive_weights.py
```

Not one number below was chosen. Each is computed from a published equation, and a test
(`test_registry_weights_match_the_derivation_script`) fails if the registry ever drifts
from the script.

---

## Provenance of the equations themselves — read this first

The HSM equations reproduced below were verified verbatim against the **NCHRP draft text
for the second edition of the Highway Safety Manual**, which reproduces Chapter 10
(rural two-lane two-way roads) with the equation numbering used here.

They were **not** verified against a purchased copy of the printed AASHTO HSM. Each one
was additionally checked against the worked examples in that same document — the
arithmetic reproduces the published example answers exactly, which is good evidence the
equations were read correctly, but it is not the same as checking the book.

**Before any of this reaches a paying client, verify against a licensed copy of the
AASHTO HSM.** That is a one-afternoon task and it closes the last provenance gap.

---

## Why a derivation is needed at all

Published CMFs are **multipliers on a safety performance function that already contains
AADT**. The registry needs **log-scale coefficients on transformed columns**.

The reason is not cosmetic. A Mode B weight has to sit on the same scale as a Mode A
coefficient — that is what makes the two modes comparable, and what makes *"Mode B is
the prior, Mode A is that prior updated by data"* a true statement about the code rather
than a slogan.

The conversion: a CMF of `c` corresponds to a log-scale contribution of `ln(c)`.

- Where the CMF is already log-linear in the variable (roadside hazard rating), the
  coefficient falls straight out and the weight is **exact**.
- Where it is not, `ln(CMF)` is fitted against the registry's declared transform by
  least squares over a stated range. The fitted intercept is discarded — Mode B is an
  ordinal ranking, so a constant shifts every unit equally and cannot change the order.
- R² is reported so a poor linearisation is visible rather than hidden.

---

## Summary

| Factor | Transform | Weight | Fit | Source |
|---|---|---|---|---|
| `speed_limit` | `ln` | **+1.6000** | exact | Elvik (2009) Power Model, TØI 1034/2009 |
| `access_density` | `ln1p` | **+0.1658** | R² 0.965 | HSM Eq. 10-17 |
| `grade_pct` | `ln1p` | **+0.1212** | R² 1.000 † | HSM Table 10-11 |
| `curve_radius_min` | `ln` | **−0.1855** | R² 0.878 | HSM Eq. 10-13 |
| `lit` | `identity` | **−0.0817** | exact | HSM Eq. 10-21 + Table 10-12 |
| `roadside_hazard_score` | `identity` | **+0.0668** | exact | HSM Eq. 10-20 |

† Three points and two fitted parameters. The R² is near-saturated and is not evidence
of anything; the source table is.

All six agree with the `expected_sign` already declared in the registry, which is a
weak but real consistency check — the signs were declared from mechanism before any
weight was looked up.

---

## 1 · `roadside_hazard_score` — +0.0668

**Source:** AASHTO HSM Equation 10-20, roadside design, rural two-lane two-way segments.
RHR scale from Zegeer et al.; CMF from Harwood et al.

> CMF₁₀ᵣ = e^(−0.6869 + 0.0668 × RHR) ⁄ e^(−0.4865)

Base condition RHR = 3, on a 1 (best) to 7 (worst) scale.

**Derivation.** Since −0.6869 + 0.0668 × 3 = −0.4865 exactly, the expression simplifies
to `CMF = exp(0.0668 × (RHR − 3))`, so `ln(CMF) = 0.0668 × (RHR − 3)`. The log-scale
coefficient on RHR **is** 0.0668. No linearisation, no range, no assumption.

**Check.** RHR = 4 → CMF = 1.069, matching the published worked example value of 1.07.

**Assumption.** The column must be on the HSM RHR 1–7 scale. A vision model emitting its
own 0–1 hazard score must be mapped onto RHR first, and that mapping is itself a
modelling decision that belongs in the report.

This is the cleanest weight in the set and the one to trust most.

---

## 2 · `lit` — −0.0817

**Source:** AASHTO HSM Equation 10-21, lighting, with Table 10-12 defaults for roadway
type 2U. Underlying research: Elvik and Vaa.

> CMF₁₁ᵣ = 1.0 − [(1.0 − 0.72 × pᵢₙᵣ − 0.83 × pₚₙᵣ) × pₙᵣ]

Table 10-12 (2U): pᵢₙᵣ = 0.382, pₚₙᵣ = 0.618, pₙᵣ = 0.370.

**Derivation.**

```
0.72 × 0.382 = 0.27504
0.83 × 0.618 = 0.51294
1.0 − 0.78798 = 0.21202
0.21202 × 0.370 = 0.078447
CMF = 1 − 0.078447 = 0.92155      →   weight = ln(0.92155) = −0.0817
```

A fully lit rural two-lane segment carries about **8% fewer total crashes**.

**Assumptions.** The column is the *proportion* of the segment lit, 0 to 1, so the weight
scales linearly between unlit and fully lit. HSM Table 10-12 proportions come from
Washington State HSIS data 2002–2006; night-crash share varies enormously by country and
replacing these with local proportions is a cheap, high-value calibration.

---

## 3 · `speed_limit` — +1.6000

**Source:** Elvik (2009), the Power Model, TØI Report 1034/2009 — exponent **1.6 for all
injury accidents on rural roads and freeways**, as reproduced in FHWA-HRT-17-098
Chapter 2, Table 1.

The same table gives 4.1 for fatal accidents, 4.6 for fatalities, and 2.2 for all injured
road users.

**Derivation.** The Power Model is `N ∝ V^k`. Taking logs, `ln(N) = k × ln(V)`. The
registry declares a `ln` transform on this column, so the weight **is** the exponent.
Exact, no fitting.

**⚠ This is the least trustworthy weight in the registry, and the largest.**

- The Power Model relates **mean operating speed** to crashes. This column is **posted
  limit**. A change in posted limit moves operating speed by materially less than 1:1, so
  applying 1.6 to posted limit **overstates** the effect and inflates this term relative
  to the other five.
- The exponent is severity-specific. The registry assumes the panel counts injury
  crashes. If it counts fatal crashes, the correct exponent is 4.1.
- Posted limit is frequently constant along a whole corridor, in which case the engine's
  variance check drops the term before it ever reaches the model.

Treat +1.6 as an upper bound and recalibrate against measured operating speed (Tier C) at
the first opportunity. This is the single highest-value calibration available to Mode B.

---

## 4 · `grade_pct` — +0.1212

**Source:** AASHTO HSM Table 10-11, grades, rural two-lane two-way segments.

| Terrain | Grade | CMF |
|---|---|---|
| Level | ≤ 3% | 1.00 |
| Moderate | 3% < grade ≤ 6% | 1.10 |
| Steep | > 6% | 1.16 |

**Derivation.** Bands represented by midpoints 1.5% / 4.5% / 7.5%. Least-squares fit of
`ln(CMF)` on `ln(1 + grade)`:

| Grade | ln(1+g) | CMF | ln(CMF) |
|---|---|---|---|
| 1.5% | 0.9163 | 1.00 | 0.0000 |
| 4.5% | 1.7047 | 1.10 | 0.0953 |
| 7.5% | 2.1401 | 1.16 | 0.1484 |

Slope = **0.1212**.

**Assumptions.** Column must be **absolute** grade in percent — HSM Table 10-11 does not
distinguish upgrade from downgrade, so neither does this weight. The steep band is
unbounded above and 7.5% was chosen to represent it; a corridor with sustained grades
well above 8% is under-weighted by this term.

---

## 5 · `curve_radius_min` — −0.1855

**Source:** AASHTO HSM Equation 10-13, horizontal curves, rural two-lane two-way
segments. Regression model of Zegeer et al.

> CMF₃ᵣ = (1.55 × L_c + 80.2⁄R − 0.012 × S) ⁄ (1.55 × L_c)

where L_c = curve length in miles, R = radius in feet, S = 1 if a spiral transition is
present, 0 if not.

**Check.** L_c = 0.1 mi, R = 1,200 ft, S = 0 → CMF = 1.431, matching the published worked
example value of 1.43.

**Derivation.** Assuming a 0.5 km segment (0.3107 mi) fully in curve with no spiral,
`ln(CMF)` is fitted on `ln(R)` for R from 50 m to 1,600 m. Slope = **−0.1855**,
R² = 0.878.

**Assumptions — this is the weakest of the six.**

- **R² 0.878.** A `1 + c/R` relationship is only roughly log-linear, so the weight is a
  compromise across the radius range. It under-weights very tight curves.
- **Tied to the segmentation length.** HSM Eq. 10-13 depends on curve length, so the
  0.5 km assumption is baked into the number. **Change the segmentation and this weight
  must be regenerated.**
- Column must be minimum radius in **metres**; the foot conversion is inside the weight.
- The adapter must cap radius on tangent sections — an uncapped infinity fails the `ln`
  transform, by design.

---

## 6 · `access_density` — +0.1658

**Source:** AASHTO HSM Equation 10-17, driveway density, rural two-lane two-way segments.
Derived from the work of Muskaug.

> CMF₆ᵣ = [0.322 + DD × (0.05 − 0.005 × ln(AADT))] ⁄ [0.322 + 5 × (0.05 − 0.005 × ln(AADT))]

where DD = driveways per mile counting both sides. Base condition is 5 driveways/mile;
below that the HSM sets CMF₆ᵣ = 1.00.

**Check.** DD = 6, AADT = 10,000 → CMF = 1.012, matching the published worked example
value of 1.01.

**Derivation.** Evaluated at a reference AADT of 10,000, `ln(CMF)` is fitted on
`ln(1 + accesses per km)` across 3–20 accesses/km. Slope = **+0.1658**, R² = 0.965.

**Assumptions.**

- **The source CMF depends on AADT, which Mode B does not have.** 10,000 is the value
  used in the HSM's own worked example. The AADT term is weak — it enters only as
  `0.05 − 0.005 × ln(AADT)` — but this is an assumption, not a measurement.
- Column must be accesses **per kilometre**, both sides. The mile conversion is inside
  the weight; do not convert the column as well.

---

## The transfer problem

**Every HSM weight above was estimated on US rural two-lane two-way highways.** The
target market for this tool is Lebanon, MENA, South Asia and much of Africa — different
vehicle fleets, different enforcement, different roadside activity, different crash
reporting.

Applying these weights outside that facility type and that country is an extrapolation,
and it is **the largest single source of error in Mode B**.

It is defensible only because Mode B is an **ordinal ranking**. A common scaling error
moves every unit together and leaves the order intact. It would not be defensible for a
predicted count — which is one reason the engine structurally refuses to emit one.

Every assessment must say this. It belongs on the limitations page (Step 4.3).

---

## Still unsourced, and why

Fourteen of twenty factors carry no weight and therefore do not enter the index. They are
not weighted zero — they are absent, and the report names them.

| Factor | Why not sourced |
|---|---|
| `traffic_proxy` | Our own construct — graph centrality has no published crash weight. Deliberately never labelled `aadt`, so the HSM AADT exponent does not transfer. |
| `junction_density` | The HSM models intersections as separate entities with their own SPFs, not as a segment-level density. No transferable CMF exists. |
| `curve_density` | HSM Eq. 10-13 prices curve *severity* via radius, not curve *frequency* per km. Sourcing this needs a different study. |
| `ramp_density` | Open blocker — the term inverts on M51 and is not diagnosable on one corridor. Sourcing a weight before the sign is understood would be premature. |
| `lanes` | The HSM prices lane *width*, not lane *count*. Different quantity. |
| `median_present` | Plausibly sourceable from HSM Chapter 11 (rural multilane) divided/undivided SPFs. Not yet done. |
| `sidewalk_present` | FHWA pedestrian CMFs exist but apply to pedestrian crashes specifically, not total crashes. Needs a severity-aware index first. |
| `surface_paved` | Paved/unpaved is not a condition index. Skid resistance and IRI are the priced Tier D quantities that actually carry the effect. |
| `poi_density`, `population_density`, `building_density`, `roadside_object_density`, `night_ratio`, `sight_distance_proxy` | No standard published weight on any comparable scale. |

**Next best candidates:** `median_present` (HSM Chapter 11) and `curve_density` (a
curve-frequency study rather than a radius CMF). Both are ordinary literature work.

---

## Sources

- [NCHRP draft text for the second edition of the Highway Safety Manual](https://onlinepubs.trb.org/onlinepubs/nchrp/nchrp_wod_297Draft.pdf) — Chapter 10, rural two-lane two-way roads. Equations 10-13, 10-17, 10-20, 10-21 and Tables 10-11, 10-12 verified verbatim here, and checked against the worked examples in the same document.
- [FHWA-HRT-17-098, *Self-Enforcing Roadways: A Guidance Report*, Chapter 2](https://www.fhwa.dot.gov/publications/research/safety/17098/003.cfm) — reproduces the Elvik (2009) Power Model exponents (Table 1).
- Elvik, R. (2009), *The Power Model of the relationship between speed and road safety: update and new analyses*, TØI Report 1034/2009, Institute of Transport Economics, Oslo — the primary source for the speed exponent. Cited via FHWA above; the report itself was not retrieved.
- [FHWA CMF Clearinghouse — HSM resources](https://cmfclearinghouse.fhwa.dot.gov/resources_hsm.php) — for cross-checking CMF provenance.
