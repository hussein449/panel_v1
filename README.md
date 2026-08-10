# Modular Road Risk Assessment Panel

A road safety risk assessment tool for corridors that do not have the data the existing
tools require.

Not "a crash model with a web interface". The model is the easy part. The product is the
path from *a road, a police crash table, and open data* to *a defensible, ranked risk
assessment* — in places with no AADT, no road inventory, and no survey budget.

---

## Where this is

| Stage | State |
|---|---|
| **Stage 1 — engine core** | Built. Registry, contract, gates, ladder, both modes, sign guard, run log, CLI. Mode B scores from context-aware weights sourced from the AASHTO HSM, the Elvik Power Model and iRAP. |
| Stage 2 — geospatial pipeline | Not started |
| Stage 3 — model depth (GLMM, GAM, Bayesian) | Not started |
| Stage 4 — report and PDF | Not started |
| Stage 5 — web layer | Not started |

Full breakdown in [`STEPS.md`](STEPS.md). What has actually been built, and what each
piece does, in [`IMPLEMENTED.md`](IMPLEMENTED.md).

The two design briefs — one on what the product is, one on what data it eats and how it
runs — are kept out of this repository deliberately. See `.gitignore`.

---

## Install

```bash
uv venv --python 3.12 && uv pip install -e ".[dev]"
```

Python 3.11+. Core has no geospatial or network dependencies — it is a plain library
over a dataframe.

## Try it

```bash
roadrisk demo
```

Generates a synthetic corridor with known coefficients and assesses it end to end. To
watch the engine refuse Mode A on a crash-only panel:

```bash
roadrisk demo --crash-rows-only
```

To see the declared factors and their weight status:

```bash
roadrisk registry
```

To assess a real panel:

```bash
roadrisk assess panel.csv --out runs/corridor-01
```

## Use as a library

```python
from roadrisk.core import assess

assessment = assess(panel)          # panel is a pandas DataFrame
print(assessment.banner)            # MODE A — FITTED FROM YOUR DATA · 7 factors · 2,412 crashes
print(assessment.refusal_receipt)   # populated only when Mode A was refused
```

---

## The rules the code enforces

These are product decisions, implemented as code rather than documented as intentions.

**The engine picks the mode. The user cannot.** There is no "use Mode A anyway" flag and
no parameter that creates one. Given the choice, users select Mode A on data that cannot
support it, and the tool prints confident numbers that are fabricated.

**No zero-crash rows, no Mode A.** A count model built only on crash locations cannot
estimate a rate — it can only redescribe the crash table. This single check prevents the
most common and most damaging misuse of the method.

**Mode B cannot produce a count.** Not by convention — the result type has no field to
put one in. Mode B output can never be dressed in Mode A's language.

**An uncited weight is refused.** Mode B will not score using a weight that carries no
`source`. A number the client cannot trace to a named reference is a liability. An
uncited factor is *absent* from the index, never silently weighted zero, and the report
names it.

**A weight is a number plus the context it is valid in.** Each declares its facility
type, region, crash severity and crash scope. A weight restricted to one facility is
inadmissible on another; a fatal-crash weight never scores an injury panel. A regional
mismatch is allowed but reported, because refusing would leave nothing usable outside
North America. Every weight is computed, not chosen, by
[`tools/derive_weights.py`](tools/derive_weights.py) — see
[`docs/WEIGHTS.md`](docs/WEIGHTS.md).

**Where two sources disagree, both are reported.** Never averaged. HSM prices grade at
+0.12 for total crashes on US rural two-lane roads; iRAP prices it at +0.49 for run-off
and head-on crashes globally. Four times apart and not in conflict — they answer
different questions, so the engine marks them not-comparable and prints both.

**A crash-type weight only moves its own crash type.** Published weights are
crash-type specific — iRAP prices grade for run-off crashes and lighting for
intersection crashes. Mode B scores each crash type separately and combines them with a
cited distribution, so a run-off-only weight is not applied as though it moved every
crash on the road. A weight scoped to *all* crashes still enters every type, so nothing
that was already correct changes.

**A contradicted sign is flagged, never quietly reported.** Every factor declares an
`expected_sign`. A fitted coefficient pointing the other way triggers the diagnostics
automatically — the factor alone, the factor alongside each correlated partner, the
correlation matrix, leave-one-unit-out — and the written verdict states plainly that the
term is not interpretable as causal.

**Nothing is silent.** Every gate result, descent, dropped term and absent column is
recorded in the run log and travels to the report. Degrade loudly.

**Every result is reproducible.** The run manifest fingerprints the engine version, the
registry contents and the input data. Two identical runs fingerprint identically.

---

## Layout

```
src/roadrisk/
├── core/                    plain library — no web, no network, no database
│   ├── registry/            declarative factors (schema, loader, factors.yaml)
│   ├── contract.py          the six required columns; exposure derivation
│   ├── context.py           what kind of corridor, and what crashes were counted
│   ├── crashmix.py          how total crashes split by type; the cited default
│   ├── weights.py           weight selection and source-agreement scoring
│   ├── transforms.py        ln / ln1p / identity / zscore, each guarded
│   ├── diagnostics.py       VIF, correlation, dispersion
│   ├── gates.py             the nine validation checks
│   ├── ladder.py            A-full → A-reduced → A-minimal → B
│   ├── models/              Poisson (reference), NB2 (shipped), Mode B index
│   ├── signguard.py         expected_sign enforcement and follow-up diagnostics
│   ├── runlog.py            append-only event log, reproducibility manifest
│   └── engine.py            the one entry point
├── demo.py                  synthetic panels for tests and demonstration
└── cli.py                   mode banner, refusal receipt, descent receipt
```

`core/` never imports the layers above it. That rule paid for itself in the M51 panel and
carries over unchanged.

## The input contract

Required — the job is rejected without them:

`unit_id` · `period` · `time_slot` · `n_crashes` · `length_km` · `duration_hours`

Exposure is `length_km × duration_hours`, and `ln(exposure)` enters as the model offset.
It is structural; the ladder may never drop it.

Optional — every factor in the registry. Each absent column drops exactly one term, and
the run log records what was lost.

## Tests

```bash
pytest
```
