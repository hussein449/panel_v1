# European evidence: what exists, what is reachable, what is usable

A survey run on 2026-09-01 to answer one question: **can the registry hold weights
estimated in Europe?** Today it holds none — 13 of 14 cited weights are `north_america`
or `global`, and every European corridor reaches across the Atlantic or settles for a
worldwide average, which every report says at length.

The short answer: **the evidence exists in quantity, and almost none of it is reachable
in a form this registry can consume.** That is a sourcing problem, not a modelling one,
and it is worth writing down so the next attempt starts from here.

---

## What was checked

| Source | Status | Usable today |
|---|---|---|
| **Trafikksikkerhetshåndboken** — tshandbok.no | ✅ live, free, revised 2023 | **One weight.** See below |
| **PRACT repository** — pract-repository.eu | ❌ **404, gone** | — |
| PRACT deliverable D4 (CEDR, 2015) | ✅ 238 pp. retrieved | Inventory only |
| **SafetyCube DSS** — roadsafety-dss.eu | ✅ live | Browsable, no bulk export found |
| CEDR road safety guidance | ✅ live | Not yet mined |
| European Road Safety Observatory | ✅ live | Statistics, not effect sizes |
| PIARC road safety manual | ✅ live | Not yet mined |
| EuroRAP | ❌ HTTP 525 | — |
| MASTER (EU, 1998) | ❌ not retrievable | — |

## The one thing harvested

`curve_radius_min = −0.5132`, from TSH Table 1.13.1 — a 50 m curve carries 3.58× the
accidents of a 600 m reference. Exact on two points. Sits between HSM's −0.1855 and
iRAP's −0.7232.

**Declared `region: global`, not `europe`,** because the figure comes from Elvik (2023), a
literature study pooling **47 international studies**. `region` records where a weight was
*estimated*, not who published it. A Norwegian handbook reporting an international
meta-analysis is not European data.

**So the registry still holds zero Europe-scoped weights, and this survey did not change
that.**

## The finding that matters most

**PRACT catalogued 889 CMFs and 273 accident prediction models on European infrastructure
— and the repository holding them is offline.**

The deliverable that describes it survives and names the countries behind the data:
German (55 mentions), Italy (42), Norway (36), Austria (24), UK (23), Netherlands (22),
Portugal (20), Switzerland, Spain, Greece, Belgium, Denmark, Sweden. That is exactly the
evidence base this registry is missing.

But D4 is *"Inventory and Critical Review of existing APMs and CMFs"* — it catalogues and
assesses models, and cites their coefficients rather than publishing them. Mining it
yields pointers, not numbers.

**Accident prediction models are the right target, more than CMFs.** An APM expresses
crash frequency as a function of measured attributes, which is the shape this registry
consumes. A CMF is a *measure* effect — what happens if you widen a lane — and converting
one into an attribute weight requires inventing the before-and-after state, which is
exactly the invention this project refuses.

## Ranked next actions

1. **Chase the national sources PRACT names, individually.** German RAL/RAS, the Norwegian
   models, the Austrian and Italian APMs. Each is a separate document hunt, and each could
   yield genuinely `region: europe` weights. Highest value, highest effort.

2. **Mine SafetyCube DSS by hand, topic by topic.** It is live and its data is explicitly
   downloadable *"at the responsibility of the user"*. There is no API or bulk export, so
   this is manual extraction per risk factor — but it is EU-funded, meta-analysed, and
   quality-rated.

3. **Add a `lane_width` factor.** PRACT discusses lane and carriageway width on 41 of its
   238 pages, more than any other attribute, and this registry has no such factor at all.
   Two quantified findings surfaced even from the inventory text:
   - German RAL: lane width below 3.25 m against a 3.50 m standard → **CMF 1.20**, two-lane
     rural, cross-section RQ11
   - German: accident rates fall about **60%** as road width rises from 5 m to 8 m on
     two-lane single carriageways

   OSM carries `width` and `lanes`, so the adapter side is cheap. This is the best
   effort-to-value ratio on the list.

4. **Consider `region: europe` on the Power Model weights.** Elvik's exponents are already
   in the registry as `global`. They were estimated largely on Nordic data; whether that
   makes them European evidence is a judgement worth making deliberately rather than by
   default — but it should be argued, not assumed.

## What this does not change

Every caveat the reports currently print stays true. A European corridor is still scored
with North American and global evidence, `access_density` is still the largest transfer
error in Mode B, and the honest route out remains **Mode A** — fitting weights from the
road's own crash history, which the A6 run showed works and which needs no registry
change at all.

---

*Sources checked live on 2026-09-01. PRACT repository confirmed 404 on both http and
https.*
