# Build Steps

The full build, broken into ordered steps. Each step has one deliverable and one way to
know it is done. Status is tracked here; what was actually built is logged in
[`IMPLEMENTED.md`](IMPLEMENTED.md).

**Status key** — `[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked

**Sequencing rule, from the brief:** make the model defensible on two corridors → make it
modular → then sell it. Stage 1 and Stage 3 are the credibility path. Stage 5 is not.

---

## Stage 0 — Foundations

| | Step | Deliverable | Done when |
|---|---|---|---|
| `[x]` | **0.1** Repo skeleton | Package layout, `pyproject.toml`, gitignore, README | `pip install -e .` works |
| `[x]` | **0.2** Factor registry schema | Pydantic models for `Factor` / `Registry`, YAML loader | A malformed registry fails loudly with the field named |
| `[x]` | **0.3** Input contract + transforms | Required columns, typing, exposure derivation, `ln`/`ln1p`/`identity`/`zscore` | A panel missing a required column is rejected with the column named |

---

## Stage 1 — Engine core *(no geospatial, no web)*

This is the part that has to be right. It is pure Python over a dataframe.

| | Step | Deliverable | Done when |
|---|---|---|---|
| `[x]` | **1.1** Diagnostics | VIF, correlation matrix, variance-to-mean dispersion | VIF matches statsmodels on a known design |
| `[x]` | **1.2** Validation gates | The 9 checks from Part Seven-B, each returning HARD / SOFT / INFO | A crash-only panel (no zero rows) is refused |
| `[x]` | **1.3** Mode ladder | `A-full → A-reduced → A-minimal → B` descent, drops by registry priority | Every descent names the failed check and the dropped term |
| `[x]` | **1.4** Mode B index | Weighted index from `default_weight`, ranked score, no counts | Refuses to score on an unsourced weight |
| `[x]` | **1.5** Mode A rungs 0–1 | Poisson GLM (reference) + NB2 GLM (shipped), `ln(exposure)` offset | Coefficients, CIs and p-values on a synthetic panel |
| `[x]` | **1.6** Sign guard | Compare fitted signs to `expected_sign`, auto-run diagnostics on contradiction | A planted reversal is flagged, not reported quietly |
| `[x]` | **1.7** Run log + manifest | Append-only event log, reproducibility manifest with hashes | Two identical runs produce the same manifest hash |
| `[x]` | **1.8** Engine orchestrator | `validate → gate → select → fit/score → guard` in one entry point | One call returns a complete, serialisable assessment |
| `[x]` | **1.9** CLI | Mode banner, refusal receipt, descent receipt | `roadrisk assess` prints the receipts from the brief |

---

## Stage 2 — Geospatial pipeline

Turns two coordinates into the panel that Stage 1 consumes. Steps 1–6 of the pipeline brief.

| | Step | Deliverable | Done when |
|---|---|---|---|
| `[ ]` | **2.1** PostGIS schema | Corridors, units, panel, crashes, factor values, runs | Migrations apply clean |
| `[ ]` | **2.2** Corridor resolve | Snap two coords to the OSM graph, route constrained to road `ref`, linear reference | Rejects a route that leaves the named road |
| `[ ]` | **2.3** Segmentation | Cut to homogeneous units — fixed length or break at junctions / class changes | Chainage is continuous, no gaps or overlaps |
| `[ ]` | **2.4** Panel skeleton | `unit_id × period × time_slot`, `n_crashes` initialised to 0 | Zero rows exist by construction, never from the crash table |
| `[ ]` | **2.5** Crash snapping | Project crashes to centreline within tolerance, chainage → unit, timestamp → period | Reports how many snapped, how many dropped, and why |
| `[ ]` | **2.6** Tier A adapters | OSM tags, curvature, DEM grade, junction / access / ramp density, POI, land cover | Each returns value + source + tier + licence |
| `[ ]` | **2.7** Fusion + agreement | Highest-priority adapter wins; agreement score where two sources overlap | Confidence tier emitted per factor per unit |
| `[ ]` | **2.8** Tier B adapters | Mapillary detections, graph centrality traffic proxy | Never labelled `aadt` |
| `[ ]` | **2.9** Geographic cache | Content-addressed by adapter + quantised bbox + params | Second corridor in the same country hits cache |

---

## Stage 3 — Model depth

| | Step | Deliverable | Done when |
|---|---|---|---|
| `[ ]` | **3.1** NB GLMM | Random intercept per unit, via Bambi/PyMC | Standard errors widen versus plain NB2 |
| `[ ]` | **3.2** GAM diagnostic | Spline on geometry, hunts the U-shape | Produces the diagnostic plot, never ships a number |
| `[ ]` | **3.3** Bayesian hierarchical + spatial | CAR/BYM, `expected_sign` encoded as prior | Credible intervals replace p-values in the report |
| `[ ]` | **3.4** Out-of-sample validation | Spatial CV, CURE plots, calibration on held-out units | Reported by default, including when bad |

---

## Stage 4 — Report

| | Step | Deliverable | Done when |
|---|---|---|---|
| `[ ]` | **4.1** Report template | Jinja HTML — method, mode, factors with source/tier/licence/confidence | Same template serves the web page and the PDF |
| `[ ]` | **4.2** PDF export | WeasyPrint, branded | Every number traceable to a source in the document |
| `[ ]` | **4.3** Limitations page | Data sources, dropped terms, unvalidated assumptions, what it does not cover | Cannot be disabled by config |

---

## Stage 5 — Web layer

`core/` must never be imported *by* — only imported *from*.

| | Step | Deliverable | Done when |
|---|---|---|---|
| `[ ]` | **5.1** FastAPI | Project CRUD, job submit, result read | OpenAPI schema generated from the registry |
| `[ ]` | **5.2** Celery worker | Pipeline as a chord: fan-out adapters, join, fit | Per-project spend cap enforced in the runner |
| `[ ]` | **5.3** Next.js + MapLibre | Corridor map, ranked units, factor provenance, mode banner | Mode banner unmissable on every screen |
| `[ ]` | **5.4** Accounts + storage | Supabase auth, saved projects, corridor comparison | Two tenants cannot see each other's runs |

---

## Stage 6 — Deploy

| | Step | Deliverable | Done when |
|---|---|---|---|
| `[ ]` | **6.1** Containers | Dockerfiles for api / worker, compose for local | `docker compose up` runs a corridor |
| `[ ]` | **6.2** Hosting | Vercel + Fly/Render + Supabase + Cloudflare R2 | Public URL resolves over TLS on a custom domain |

---

## Open decisions

Things that need a human call, not a code change.

1. ~~**Mode B default weights are unsourced.**~~ **RESOLVED as far as it can be
   without spend, 2026-08-10.** Seven of twenty-one factors carry ten weights derived
   from the AASHTO HSM, the Elvik Power Model and iRAP, each computed by
   `tools/derive_weights.py` and documented in [`docs/WEIGHTS.md`](docs/WEIGHTS.md).
   Weights are context-aware — the engine picks by facility type, region and crash
   severity, reports what it reached for, and scores agreement between sources.
   **Two things still need a human:**
   - **A licensed AASHTO HSM.** Equations were read from the NCHRP draft text of the
     2nd edition and are double-checked against their published worked examples by
     `tests/test_published_equations.py`, but HSM2 (2024) changed Parts C and D and
     nothing here is edition-pinned to a verifiable artefact. One afternoon with the
     book closes it.
   - **The iRAP Methodology Reference Guide v3.10** — free, but behind SSO registration
     at `resources.irap.org`. Only `grade` could be verified from a retrievable fact
     sheet. The Guide would plausibly source `median_present`, `surface_paved`,
     `sight_distance_proxy` and `roadside_object_density`, and add a global cross-check
     to every HSM weight. Highest-value next step for Mode B.
2. **Measure operating speed on one corridor.** `speed_limit` carries a permanent
   caveat because the Power Model exponent applies to operating speed, not posted
   limit; `operating_speed_85` exists and is uncaveated but has no data. A single
   Tier C speed pull removes the largest known weakness in the index.
3. **Second corridor.** Still the critical path. Pick one where access density and ramp
   density separate — the M51 ramp/RAF inversion is not diagnosable on a single corridor.
4. **Rung 4 engine.** PyMC/NumPyro keeps one language; R + INLA is materially faster for
   CAR/BYM at panel scale. Defer until MCMC actually hurts.
