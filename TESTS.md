# Corridors tested

Every real corridor this tool has been run against, what came back, and what it meant.
Kept because the failures taught more than the successes: three of the four runs below
produced a bug fix, and the fourth produced the first Mode A assessment in the project's
history.

Synthetic corridors — `roadrisk demo`, the API's demo job — are not recorded here. They
test the machinery. These test the product.

| # | Corridor | Date | Mode | Crashes | What it was for |
|---|---|---|---|---|---|
| 1 | Ελαιώνων (U274), Cyprus | 2026-08-28 | B | none | First real road through the new front page |
| 2 | A10, Cyprus | 2026-08-29 | B | none | Found: the road is not built |
| 3 | F929, Cyprus | 2026-08-30 | B | none | Confirmed the length and context fixes |
| 4 | **A6 Derby–Buxton, England** | **2026-08-31** | **A** | **284 real** | **First fitted model** |

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
