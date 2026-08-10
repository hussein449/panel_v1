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
| `[x]` | **1.4** Mode B index | Crash-type-decomposed weighted index from cited weights, ranked score, no counts | Refuses to score on an unsourced weight; a total-only registry scores identically to a flat sum |
| `[x]` | **1.5** Mode A rungs 0–1 | Poisson GLM (reference) + NB2 GLM (shipped), `ln(exposure)` offset | Coefficients, CIs and p-values on a synthetic panel |
| `[x]` | **1.6** Sign guard | Compare fitted signs to `expected_sign`, auto-run diagnostics on contradiction | A planted reversal is flagged, not reported quietly |
| `[x]` | **1.7** Run log + manifest | Append-only event log, reproducibility manifest with hashes | Two identical runs produce the same manifest hash |
| `[x]` | **1.8** Engine orchestrator | `validate → gate → select → fit/score → guard` in one entry point | One call returns a complete, serialisable assessment |
| `[x]` | **1.9** CLI | Mode banner, refusal receipt, descent receipt | `roadrisk assess` prints the receipts from the brief |

---

## Stage 2 — Geospatial pipeline

Turns two coordinates into the panel that Stage 1 consumes. Steps 1–6 of the pipeline brief.

**Re-ordered deliberately.** PostGIS was 2.1; it is now 2.9. A 100 km corridor fits in
memory comfortably, and persistence is a Stage 5 concern. Doing the geometry in memory
first got the pipeline to the engine in one pass instead of behind a migration.

Everything below runs with **no network and no API key**. That is not a limitation
being worked around — it is the shape of the product.

| | Step | Deliverable | Done when |
|---|---|---|---|
| `[x]` | **2.2a** Corridor + linear reference | `Corridor.from_latlon`, UTM projection, chainage, structural gates | A corridor that cannot be linearly referenced is rejected, not silently used |
| `[x]` | **2.2b** Resolve a corridor from OSM | Fetch by road `ref`, stitch, bridge gaps, detect divided roads, trim to start/end | Refuses a fragmented collection; never welds opposing carriageways |
| `[x]` | **2.3** Segmentation | Fixed-length units, chainage continuous and exhaustive, trailing runt merged | No gaps, no overlaps, unit lengths sum to the corridor |
| `[x]` | **2.4** Panel skeleton | `unit_id × period × time_slot`, `n_crashes` initialised to 0 | Zero rows exist by construction; skeleton passes the input contract |
| `[x]` | **2.5** Crash snapping | Project to centreline within tolerance, chainage → unit, period → cell | Every drop counted with a reason; `SnapReport` activates gate check 6 |
| `[x]` | **2.6** Tier A adapters | 12 factors behind one adapter contract, from three sources: centreline geometry, one OSM call, two COG rasters | Each returns value + source + tier + licence |
| `[ ]` | **2.7** Fusion + agreement | Highest-priority adapter wins; agreement where two sources overlap | Confidence tier emitted per factor per unit |
| `[ ]` | **2.8** Tier B adapters | Mapillary detections, graph centrality traffic proxy | Never labelled `aadt` |
| `[ ]` | **2.9** PostGIS + geographic cache | Persistence, and content-addressed caching by adapter + quantised bbox | Second corridor in the same country hits cache |

**Try it:**

```bash
roadrisk corridor --demo --facility-type rural_two_lane --region middle_east --severity injury
```

Add `--osm` for the road's own tags and its conflict-point densities, and `--rasters`
for gradient and roadside land use. Without either flag the pipeline never touches the
network.

**Validated on a real road, 2026-08-10.** Cyprus B9 through the Troodos mountains:
69 OSM fragments → one 25.01 km centreline → 50 units → 1,200 panel rows → 99.8% snap
rate → Mode A. Details and the two defects it exposed in
[`IMPLEMENTED.md`](IMPLEMENTED.md).

### 2.6 — done

```bash
roadrisk corridor centreline.csv --crashes crashes.csv --osm --rasters
```

The adapter contract is the deliverable, not the twelve columns. A module names the
registry slot it fills — `osm_maxspeed`, `copernicus_dem_glo30` — and the tier and
licence travel from *that declaration* onto every value it produces. An adapter cannot
promote itself to Tier A or invent a licence, because it never gets to state either.

| Source | Cost | Factors |
|---|---|---|
| Centreline geometry | arithmetic | `curve_radius_min`, `curve_density` |
| OSM, one Overpass call | one request | `speed_limit`, `lanes`, `lit`, `surface_paved`, `sidewalk_present`, `median_present`, `junction_density`, `access_density`, `ramp_density`, `poi_density`, `building_density` |
| Copernicus DEM, ESA WorldCover | COG windows | `grade_pct`, `landuse_urban` |

The OSM query is bounded by the corridor rather than by its bounding box. The rasters
are read as windows over HTTPS range requests, never as whole tiles, and are the only
part that needs GDAL — hence a separate extra:

```bash
pip install "roadrisk-panel[raster]"
```

**Missing tags are not zeros.** A factor needs half the corridor tagged; an untagged unit
takes its neighbour's value only across a short gap, and says so. Reading an absent `lit`
tag as "unlit" would manufacture a lighting effect out of mapper attention, pointing
exactly the way the registry expects.

**Validated live on Cyprus B9, 2026-08-10.** 12 of 14 attempted factors resolved.
`lit` (32% tagged), `sidewalk_present` (16%) and `median_present` (0%) were refused and
reported. `grade_pct` reads a median 6.1% and a maximum 9.6% climbing into the Troodos.

`population_density` is the one Tier A factor in the brief with no adapter, and the
reason is delivery format rather than data — see the open decisions below.

### 2.2b — done

```bash
roadrisk corridor --ref B9 --bbox 34.80,32.80,35.05,33.05 --region europe --severity injury
```

Fetching **by road reference** rather than routing between two points is deliberate: a
router returns the *fastest* path and will leave the road you asked about without
telling you. `ref="B9"` cannot return anything that is not the B9.

Validated live against two real Cyprus roads:

| | B9 (Troodos, undivided) | A1 (motorway, divided) |
|---|---|---|
| Fragments | 69 | 49 |
| After merge | 3 | 4 |
| Gaps bridged | 2 | 0 |
| Longest share | **100%** | 26% |
| Divided | no | **yes** (49/49 one-way) |
| Result | 25.07 km | 8.11 km, 22.68 km excluded and reported |

The network layer is injectable, so all 34 tests run without touching it.

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
   without spend, 2026-08-10.** Seven of twenty-two factors carry ten weights derived
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
   - ~~**The iRAP Methodology Reference Guide v3.10.**~~ **DONE.** Sourced grade,
     curvature, skid resistance and street lighting. Global weights went 4 → 8, and a
     European or MENA corridor now reaches for American evidence on one factor instead
     of three. `median_type` is the best remaining candidate but needs the Star Rating
     Score traversability normalisation understood first — its values are 0-100
     traversability scores, not CMFs. See `docs/WEIGHTS.md` for the four attributes
     examined and deliberately not used.
2. **Measure operating speed on one corridor.** `speed_limit` carries a permanent
   caveat because the Power Model exponent applies to operating speed, not posted
   limit; `operating_speed_85` exists and is uncaveated but has no data. A single
   Tier C speed pull removes the largest known weakness in the index.
3. **Supply a local crash-type distribution.** Mode B now decomposes the score by crash
   type, and the default shares come from HSM Table 10-4 — Washington State, rural
   two-lane, 2002–2006. Most national crash databases can produce a local split
   directly, and it is one of the cheapest accuracy improvements available. Pass it as
   `RunContext(crash_mix=...)`; `uniform_mix()` is available for corridors where no
   defensible split exists.
4. **Resolve `lanes`.** It is currently a volume proxy expecting `+` for total crashes,
   while iRAP prices lane count at `−` for head-on-overtaking crashes only. Two
   mechanisms in one column — the composite-masking trap the brief warns about. The
   real fix is separating the exposure role from the risk role, not picking a sign.
3. **`population_density` needs a range-readable source, or the 2.9 cache.** It is the
   one Tier A factor in the brief with no adapter, and the obstacle is delivery format
   rather than data. Every other raster here is a cloud-optimised GeoTIFF, so a corridor
   costs a few window reads; neither population source is. Measured 2026-08-10:
   WorldPop's global mosaic answers a `Range` request with **200, not 206** — it ignores
   the header and streams the whole file — and GHSL ships deflated zip tiles whose
   members cannot be windowed. Either way one corridor costs a whole-file download,
   which contradicts the registry's own instruction on the DEM adapter. Three ways out,
   in order of appeal: find a COG mirror (Meta's HRSL on `dataforgood-fb-data` is a
   candidate and would need a new adapter declared); wait for the content-addressed
   cache in 2.9 and pay the download once per region; or drop the factor and let
   `landuse_urban` and `building_density` carry urban context between them.
4. **Second corridor.** Still the critical path. Pick one where access density and ramp
   density separate — the M51 ramp/RAF inversion is not diagnosable on a single corridor.
4. **Rung 4 engine.** PyMC/NumPyro keeps one language; R + INLA is materially faster for
   CAR/BYM at panel scale. Defer until MCMC actually hurts.
