# Implemented

What has actually been built, in the order it was built. Planned work lives in
[`STEPS.md`](STEPS.md); this file only records what exists and works.

---

## 2026-08-26 (latest) — Step 5.1c: the product, over HTTP

**Delivered:** `roadrisk/api/` — thirteen paths over 5.1b's store, the refusal contract
enforced by exception handler rather than by intention, `factors.yaml` served with the
hash of the file it was read from, and `docs/openapi.json` generated from the app.

```bash
pip install "roadrisk-panel[api]"
roadrisk serve                       # http://127.0.0.1:8000, docs at /docs
python tools/generate_openapi.py     # rewrite docs/openapi.json
pytest tests/test_api.py
```

### Nothing here describes the payload, the rows or the factors a second time

The response body of `GET /runs/{id}` is `roadrisk.contract` (5.1a). The response bodies
of the project, corridor and job routes are `roadrisk.store.records` (5.1b) — frozen
Pydantic models that already forbid extras. The factor list is the `Registry` the loader
validated at startup. **There is no list of factor names anywhere in `roadrisk/api/`**,
and a test parses the package with `ast` looking for one, because the way that stops
being true is never a decision — it is one endpoint that needed a special case for
`traffic_proxy` and got one.

Three things *are* written separately here, each because the wire shape and the row shape
genuinely differ:

- **Create bodies carry no `tenant_id`.** It comes from the header. A body that could
  name one would let a client file rows under somebody else's tenant, and since every
  request model forbids extras, sending it is a 422.
- **`ArtefactOut` replaces `uri` with `href`.** The stored URI is a path on our disk.
- **`RunSummary` drops the payload.** A run is about 300 kB; fifty of them is not a
  listing.

### The refusal contract, which is the whole reason this step was worth care

A REST instinct collapses every non-success onto 4xx and 5xx, and doing that here would
have swallowed this project's entire honesty layer into a generic error handler.

| Outcome | What it is | Pinned by |
|---|---|---|
| Panel breaks the input contract | **422**, column named, **and no job exists** | `test_a_contract_violation_at_submit_is_422_and_creates_no_job` |
| Descent to Mode B, dropped terms, refused weight | **200**, carrying its receipts | `test_a_mode_b_descent_is_a_200_carrying_its_receipt` |
| Something breaks | 500 with a logged reference, **no traceback in the body** | `test_an_unhandled_error_is_a_500_with_a_reference_and_no_traceback` |

The first test asserts the *second* half of the rule — that the project's job list is
empty afterwards — rather than trusting that the route returned before it got there.
"No job created" is the half a client can actually verify.

**One envelope for every refusal, including FastAPI's own.** Its default validation error
is a bare `{"detail": [...]}` list, re-shaped here into the same `{"error": {...}}` as
everything else. A client that has to parse two error shapes will parse one and guess at
the other. Codes rather than status alone, because 422 is doing two jobs: a malformed
body and a panel that breaks the contract are both 422 and are not the same problem — one
is retried after fixing JSON, the other after fixing data.

### 202 before there is anything behind it, deliberately

`POST /jobs` stores a job and returns 202 with a `Location`. Nothing executes it; it stays
`queued` until 5.1d. That is the point. A cold corridor is 55.5 s (2.9) and `--bayes` on
the demo corridor runs for tens of minutes (4.7) — no HTTP request survives either — so if
this only began returning 202 once Celery existed, 5.2 would change the contract and break
every client written against 5.1.

**`GET /health` reports `runner: null`.** A job that will never run, reported as `queued`,
is a working service that lies. The same response reports `auth: null` and
`artefacts_available`, and the OpenAPI description carries both facts at the top, so a
client reads them rather than inferring them from a job that never moves.

### Everything refusable is refused before the job exists

A panel through `prepare_panel`; a shape factor checked against `factors.yaml`; a corridor
with neither an OSM reference nor a bounding box, which no fetch can resolve; a panel
larger than this deployment accepts. The shape-factor check is worth spelling out: `assess`
already reports names it could not put a spline on, which is right for a factor that exists
but did not survive into the fitted specification. A name **no factor has** is a typo, it
will never mean anything, and the refusal names only the wrong one.

`job.params` is a written-down `JobSpec` rather than a loose dictionary, so 5.1d reads a
submission back instead of re-deriving what it meant. The panel is stored *as submitted*,
not as prepared — `exposure` and `log_exposure` are derived, and freezing the derivation
inside a row would put a copy of the input contract next to the data it describes.

### Artefact download is a file-read primitive, and is treated as one

The database holds a `file://` URI. Serving it means calling `open()` on a path that came
out of a column — written by the CLI today, by a worker at 5.2a. That does not become safe
by being trusted; it becomes safe by being bounded.

So `$ROADRISK_ARTEFACT_ROOT` is an **allow-list with no default**, and with none set every
download is refused with a 409 naming the variable. The failure mode of the safe default is
a 409; the failure mode of the convenient one is `/etc/passwd`. Four more ways it says no,
each a real case: a path outside the root — resolved *before* it is compared, so a symlink
out of the root is caught; a file that is gone, because artefacts are stored by reference
and nothing stops one being moved; a size that no longer matches the record, because then
it is not the artefact that record describes and serving it under that sha256 would be a
lie; and a non-`file://` scheme, which is a **501** rather than a fetch — a server that
will `GET` any URL out of its own database on request is a proxy for reaching whatever it
can reach.

The recorded sha256 is returned as the `ETag`, so a client can verify what arrived without
this route re-hashing a third of a megabyte per request. The size check is free; `stat`
already happened.

### CRUD needed a D, and the D exposed the cascade

"Project and corridor CRUD" has no U or D under it in 5.1b, so the store grew
`update_project`, `delete_project`, `update_corridor` and `delete_corridor` — parametrised
over both backends like everything else in that file.

**Migration 0001 cascades from project through corridor, job and run.** That is correct
for dropping a tenant and catastrophic for one careless request: a single
`DELETE /projects/{id}` would destroy every stored assessment filed under it, and a stored
run is what a client paid for. The guard lives in the store, in both backends, so no caller
can reach past it, and the refusal names what is still there. There is no force flag —
emptying a project means deleting what is in it, deliberately.

Deleting a *corridor* is refused too, even though the schema would allow it: `corridor_id`
is `ON DELETE SET NULL` on both job and run, so nothing would be destroyed — but the link
would be. A run keeps its geometry inside the payload and would quietly stop being filed
against the road it describes.

### Three defects this step found in code it did not write

**`PostgresStore._maybe` does not commit, and an `UPDATE ... RETURNING` through it looks
like it works.** It returns the new row, the change is visible to the connection that made
it, and it is rolled back when that connection closes. The first `update_project` was
written that way, which is the obvious way. The test that catches it is the one that
*re-reads* rather than asserting on the return value, and it is worth stating as a rule:
for a write, assert on a later read.

**5.1b's one-connection store is not safe behind an API, and it said so.** Its own "known,
deliberately left" note called it "correct for a CLI and wrong for 5.1c". The precise
reason is worse than latency: FastAPI runs synchronous routes in a thread pool, psycopg3
connections are not safe to share across threads, and a shared one does not fail loudly —
it interleaves two statements and returns the wrong rows to somebody. So the app holds a
*provider* that opens a store per request and closes it. A pool goes behind that provider
when connection latency is worth measuring; nothing above it changes.

**Rich was silently eating the extra out of every install command we print.** Writing
`roadrisk serve` without the api extra installed printed:

```
The api extra is not installed. Run: pip install "roadrisk-panel"
```

`[api]` is Rich markup. It looks for a style called `api`, finds none, drops the tag — and
the message now tells you to install the package you already have, with the one thing it is
about removed from it.

**This package already knew.** `centreline-help` renders its Overpass recipe through
`Text()` rather than a bare string precisely because Rich eats `[out:json]`, the comment
saying so has been in `cli.py` since Stage 2, and there is a test class named for it. The
knowledge did not travel: 5.1b wrote it twice (`roadrisk store`'s group help and its
missing-extra message) and 5.1c wrote it twice more (the `serve` docstring and its
missing-extra message). All four are backslash-escaped now.

Found by running the command with the dependency deliberately absent — the branch is
unreachable on a machine where the install worked — and the fourth instance was found by
the test rather than by me, which is the argument for writing it. The new test class
asserts every place this package prints an extra, unwrapping Rich's boxed help first,
because the command can be split across two lines with a border character in the middle
of it.

### The licence policy moved down a layer, and that is the interesting part

`GET /registry` serves each adapter's tier and licence — and what that licence obliges. A
client reading `"licence": "ODbL"` has been told nothing it can act on; what it needs is
that crediting the source in a report discharges it and republishing the panel as a dataset
does not. That distinction already existed, in `roadrisk/geo/attribution.py`, as a table
keyed by `Licence`.

Reaching for it from the API would have made **shapely a dependency of answering
`GET /registry`**, because importing `roadrisk.geo.attribution` runs `roadrisk/geo/__init__`
first. Copying the text would have been the 5.1a defect with new names. So the table moved
to `roadrisk/core/registry/schema.py`, beside the enum it is keyed by, where it always
belonged — a licence's obligations are a property of the licence, not of a geospatial
pipeline. `geo.attribution` re-exports it, and the tuple became a `LicencePolicy`
NamedTuple on the way, so `credit_required` and `share_alike_database` have names at the
point of use rather than being positions 0 and 1.

A `TIER_MEANING` table joined it, and a test asserts both cover every member of their enum
— a tier nobody has described would otherwise be published to clients as a bare letter.

### `docs/openapi.json`, and what its check deliberately ignores

`tools/generate_openapi.py` writes the document from the app, the way `generate_types.py`
writes the TypeScript. A served `/openapi.json` answers none of the questions a committed
one does: 5.3b's Next.js shell wants a description at build time, a reviewer wants to read
the surface without installing the package, and "what did this endpoint look like last
release" should be answerable from `git log`.

`--check` compares the **surface** — paths, methods, status codes, parameter names, schema
names — and not the bytes. A FastAPI upgrade legitimately rewords a description or reorders
an `anyOf`, and a check that failed on that is a check people learn to regenerate past
without reading. A separate test asserts the document's `Licence` and `Tier` enums are the
registry's own, so the published contract cannot describe a licence the registry is
incapable of holding.

**50 new tests, 869 passing, 3 skipped. `ruff check` clean.** Without a database that
reads 843 passing and 29 skipped: `tests/test_api.py` runs on `MemoryStore` and needs no
server, and the Postgres half of `tests/test_store.py` skips loudly as it always has.
Verified beyond the suite as well — a real uvicorn process over a real socket against
real Postgres, where the per-request store, the 422-with-no-job and `GET /registry` all
behave as they do in-process.

### Known, and deliberately left

- **No pagination cursor.** `GET /runs` takes a capped `limit` and returns newest-first.
  Nothing has enough runs for the difference to matter, and a cursor designed against no
  query shape is a cursor designed twice.
- **No `POST /runs`.** Importing a `run.json` is `roadrisk store import`, which is a local
  operation on a file. Over HTTP it is a large upload with no client asking for it yet.
- **No re-render endpoint.** `roadrisk store show --report` renders a stored run to a
  report; the API does not. 5.3a splits the report into a component and 5.3b serves it, so
  building a second renderer here would be building the thing that step then replaces.
- **`PATCH` is read-modify-write with no `If-Match`.** Two editors racing would have the
  second win silently. There is one editor. The `ETag` machinery already exists on the
  artefact route when that stops being true.
- **No rate limiting and no request-body size cap.** The panel row cap is enforced after
  parsing, which bounds what reaches `jsonb` and not what reaches the parser. That is a
  deployment concern — a reverse proxy's job — and pretending otherwise in application
  code would give it a home where it does not belong.

---

## 2026-08-26 (earlier) — Step 5.1b: runs that outlive the process that made them

**Delivered:** `roadrisk/store/` — six Postgres tables around a `jsonb` payload, numbered
SQL migrations, two backends behind one protocol, and the storage half of the command
line. A run written by the CLI imports and re-renders from the database with nothing
refitted.

```bash
export ROADRISK_DATABASE_URL=postgresql:///roadrisk
roadrisk store init
roadrisk store import run/run.json --project <id>
roadrisk store show <run-id> --report out/     # rendered, not refitted
```

### Tenancy is in the first migration, and that is the whole argument

*"Two tenants cannot see each other's runs"* is filed under 5.4 in the original plan, next
to authentication. It does not belong there. Auth is who you are; tenancy is **which rows
exist at all**, and that is a property of the schema. Retro-fitting an owner column later
means rewriting every query and every test written against them in between, at exactly the
moment there are most of both.

So `tenant_id` is on every table, including the ones where a join could derive it, and
every method on the interface takes a tenant as a required argument with no default. Not a
filter a caller may add — a parameter they cannot omit. 5.4a's row-level policies then
attach to a column that is already there.

### Carrying that column opens a hole, and the two-backend suite found it

A plain `REFERENCES project (id)` checks that the project exists. It does not check that it
is *yours*. So a run could be inserted with `tenant_id` of one tenant and `project_id`
belonging to another — and every single-table query, which is all of them, would go on
looking perfectly correct.

The test caught it because it runs against both backends: it **passed** against
`MemoryStore`, which happens to check the parent explicitly, and **failed** against
Postgres, which did not. That divergence is precisely what a shared conformance suite
exists to expose, and it surfaced on the first run.

Every parent reference is now composite — `FOREIGN KEY (tenant_id, project_id) REFERENCES
project (tenant_id, id)` — with the `UNIQUE (tenant_id, id)` constraints that makes
possible. Crossing tenants is no longer a mistake the application must avoid making; it is
a row the database will not accept. Three tests pin it, one per table that has a parent.

### A defect this step found in the payload itself, which reached much further

The first Postgres insert of a Mode B run failed with:

```
invalid input syntax for type json
DETAIL:  Token "Infinity" is invalid.
CONTEXT: ...o negative binomial.", "data": {"ratio": Infinity...
```

A crash-free panel has mean zero, so its variance-to-mean ratio is infinite, and it lands
in the run log. Python's `json.dumps` writes that as a bare `Infinity` — which is a Python
extension and **not JSON**. Every strict reader refuses it.

Step 4.4 had already found this and guarded the *HTML embedding*, with `_finite()` plus
`allow_nan=False`, and the comment there explains exactly why. What it did not guard was
everything else. So:

- `run.json`, `assessment.json` and `corridor.json` written beside the report were **not
  valid JSON** for any Mode B run;
- the report page's own file picker, which does `JSON.parse(await file.text())`, could not
  read back the files the CLI had just written;
- and `jsonb` refused them outright.

The fix is one line in the right place: `build_run` sanitises at assembly, so the disk, the
page, the database and the API all inherit a payload that is actually JSON rather than
nearly JSON. The helper moved to `roadrisk.contract.jsonsafe` — where "what valid JSON for
this payload means" belongs — and `non_finite_paths` names the offender, because *one
non-finite float* sends somebody hunting through 300 kB and
`$.assessment.log[17].data.ratio` does not.

**`null`, not zero.** A non-finite value here is a quantity that genuinely could not be
computed. JSON's word for that is `null`, which every renderer in this project already
draws as absent. Zero would be a number nobody measured.

### Two backends, one conformance suite

`MemoryStore` needs nothing and is what the whole test suite runs against; `PostgresStore`
sits behind the `store` extra and skips loudly when `$ROADRISK_DATABASE_URL` is unset. Every
test is parametrised over both. An in-memory stand-in tested only by itself drifts from the
database it stands in for, and every drift is a defect that appears in production and
nowhere else — which is not a hypothetical, since that is how the tenancy hole above was
found.

The memory store therefore enforces what the database enforces: tenant scoping, parents
that must resolve, payload validation on the way in, and a `NotFound` that does not
distinguish *absent* from *someone else's*. Telling those apart tells a caller whether an id
is real, which turns a list of guessed identifiers into a census of another tenant's runs.

### The payload is validated on the way in, never on the way out

A store that accepted a malformed payload would hand the problem to whoever read it back —
months later, probably in front of a client. So `store_run` runs it through
`roadrisk.contract` first and refuses with the failing paths named. 5.1a is what makes that
one line instead of a schema.

The indexed columns — mode, rung, fingerprint, engine and schema version — are **read out of
the payload**, not passed in. There is no parameter for any of them anywhere. That absence
is the guarantee: a row cannot describe a different run than its own payload, because nobody
is in a position to tell it to.

### Migrations: numbered SQL, hashed on the way in

Not Alembic. Autogeneration wants ORM models to diff against and there are none — the data
model is six tables of scalars around a blob, and an ORM over that would put a translation
layer between the schema people review and the queries that run. What is left of Alembic
once autogeneration is gone is a version table and an ordering.

Each applied migration is recorded with the **hash of the file that produced it**. A
database that has silently diverged from the migration claiming to describe it is worse than
one that was never migrated, and no amount of `IF NOT EXISTS` rescues it — so the mismatch
is refused, naming the file.

### Three defects found by running it rather than reading it

- **A malformed `--project` printed a traceback.** `UUID(...)` unguarded raises `ValueError`
  and typer renders the stack, which tells a reader nothing about which of three ids was
  wrong and looks like a crash rather than a rejected argument. Every id now goes through
  one helper that names the option.
- **`store list` printed ids that could not be copied.** Rich assumes an 80-column terminal
  when stdout is not a TTY and shrinks columns to fit, putting an ellipsis through the
  middle of every run id — and that id is the argument to every other command in the group.
  Redirected output is given room now.
- **A rejected insert poisoned the connection.** Postgres puts a connection into a failed
  transaction after any error and refuses everything until it ends. Without a rollback, one
  constraint doing its job left the store unusable for every later call, and the error a
  caller saw named neither the operation that failed nor the one refused because of it. A
  rejected write is a *normal* outcome here — the composite tenant keys exist precisely so
  that some inserts get refused.

### What the round trip actually preserves

`roadrisk store show --report` renders a stored run back to a report with nothing refitted.
The result is the same document and **not** byte-identical, which is worth stating exactly:
`jsonb` is a normalised representation and sorts object keys by length, so the embedded JSON
comes back with `corridor` before `assessment`. Measured on the demo corridor: 147,953
characters differ, the length is identical, the payloads compare equal as data, and the
reproducibility fingerprint is untouched.

The alternative column type, `json`, keeps the text verbatim and cannot be indexed. Indexing
is worth more here, and nothing downstream hashes the rendered HTML — the fingerprint is a
value *inside* the payload.

**37 new tests, 819 passing, 3 skipped. `ruff check` clean.**

### Known, and deliberately left

- **No connection pooling and no async.** One connection per store, opened and closed by the
  caller. Correct for a CLI and wrong for 5.1c, which will want a pool — but the interface
  does not change, only what sits behind `_open_store`.
- **PostGIS is still not enabled.** Nothing here holds geometry: a corridor stores the
  *request* that produces one, and the resolved centreline lives in the run payload with the
  rest of what that particular fetch found. The extension arrives when there is a spatial
  query to run, which is the call topic's flood-and-fire overlay, and not before.
- **Artefact files are never garbage-collected.** Deleting a run cascades the row and leaves
  the file. That is deliberate for now — the alternative is a delete path that removes
  client deliverables, which wants more thought than this step is the place for.
- **The `run` table has no index on the payload.** Nothing queries into it yet. 5.4c's
  corridor comparison is what will want a GIN index, against real query shapes.

---

## 2026-08-24 — Step 5.1a: one description of the payload, and TypeScript projected from it

**Delivered:** `roadrisk/contract/` — the JSON payload as ~60 Pydantic models at the
bottom of the layer order — the conformance suite that keeps it honest, and
`web/src/types.ts` generated from it rather than maintained by hand.

```bash
python tools/generate_types.py            # rewrite the TypeScript
python tools/generate_types.py --check    # what the test runs
pytest tests/test_payload_contract.py
```

### Why a second description of the payload is worth its cost

`as_dict()` decides what travels. The contract decides what is *allowed* to travel. Those
are the same information written twice, which is normally a defect — and here it is the
point, because the test between them is the only thing that can notice drift.

The argument is step 4.7, which this file already records: `posterior.coefficients` is a
mapping keyed by factor, the page had it typed as a list, `.find()` returned nothing, every
coefficient silently fell back to its **frequentist** interval, and the column header kept
saying *credible interval*. It survived three steps because the types agreed with
themselves. Nothing ever compared them against a real payload.

Now something does, on every run of the suite.

### `extra="forbid"` is the mechanism, not a style choice

A permissive model accepts any payload that happens to contain the fields it knows about.
The engine can grow a key, the report can start depending on it, and the two descriptions
drift apart in silence — which is exactly the failure this package exists to prevent, so a
permissive contract would be theatre.

Forbidding extras inverts it: a new key in `as_dict()` fails the conformance test until it
is declared. Adding a field to the engine is now a two-file change, and that is the price.
A test asserts every model in the package still forbids extras, because relaxing one to
`extra="ignore"` would make it quietly partial again and nothing else would notice.

### Six real payloads, chosen so the branches are populated

Validation passes trivially against a payload whose optional sections are all `None`, so
the fixtures are genuine engine runs picked to light up different halves of the shape:

| Fixture | What it populates |
|---|---|
| Mode A | `fit`, `predictions`, `ranking`, `validation`, a named spline |
| Mode B | `index`, refusal and descent receipts, a ranking with no counts |
| Bayes | `posterior` — the section the 4.7 defect lived in |
| Priors | `evidence` — textbook, corridor and mixture side by side |
| Spatial | `spatial` — the Leroux field and whether it was identified |
| Corridor | the whole geography half: geometry, provenance, attribution, cache |

A separate test asserts those branches are *actually* non-null, so that a fixture quietly
ceasing to reach a rung — a tightened gate, a dependency change — shows up as a failure
rather than as coverage silently evaporating.

### Generating the TypeScript immediately caught a modelling error of mine

135 fields were written `Field(default_factory=list)`. That reads as convenience and means
**optional** to Pydantic, so every one of them projected into TypeScript as `?` — and
`tsc` produced about thirty errors of the form *'ranking.units' is possibly 'undefined'*.

The engine emits those keys unconditionally. Only 4.2's deliberately-omitted count fields
are ever genuinely absent. I had modelled the convenience of the Python constructor rather
than the shape of the payload, and nothing on the Python side would ever have told me:
validation passes either way. It took projecting the models into a language with a stricter
reading of *optional* to see it.

Fixed, and then re-verified the only way that means anything — all six payloads still
conform with the 135 fields required, which is the proof that the engine really does always
emit them.

### It also found a real gap in the run record

`Run` requires `limitations`. They are assembled by `build_run` and stored in neither
`assessment.json` nor `corridor.json` — so the report bundle's own file picker, which
reassembles a run from those two halves, **could not reconstruct them**. A reader who had
a run directory but not the generated report got a report missing the one page step 4.6
says nothing may remove.

The page was already honest about it — handed nothing, the limitations section prints
*"No limitations were recorded for this run. That is itself a defect"* — so nothing was
silently lost. But it was a false alarm every time, and the fix is to stop discarding them:
`run.json`, the whole envelope, is now written beside the two halves, and the picker reads
it first.

That defect had been sitting in the bundle since 4.3. It surfaced as a **type error**.

### Two more mismatches the hand-written types carried

- **`checks[].threshold` and `.observed` are prose**, not numbers — `"max VIF < 5"` against
  `"max 1.3 (lit)"`. The hand-written types declared both `number | null`, which no run has
  ever produced. Latent, because the page never reads either field.
- **Blackspot chainage is nullable**, and the page tested for it with `=== undefined`.
  A corridor-less run would have put `null` through `Math.round` and into an `x` coordinate.

Both are now unstateable: the contract is the only description, and `tsc --noEmit` passes
against it.

### `schema_version`, and why it is not the engine version

Every run now carries `schema_version` — `1.0` — separate from `engine_version`. It moves
when the payload's *shape* changes, not when the engine does, so a consumer reading a run
stored months ago can tell whether it still knows how to read it. That is what 5.1b's
promise — a stored run re-renders without a refit — actually rests on. It is optional on
the model rather than required, because runs written before this step do not have it, and
a contract that refused to read them would defeat its own purpose.

### Where it sits in the layer order

`contract` is beneath everything, including `core`. It imports nothing, so anything may
depend on it without acquiring a dependency on anything else. The 5.0 layering test was
extended for it, and `report` — which is otherwise forbidden from importing any other
layer — is allowed this one, on the grounds that the models name no engine type and so
cannot put an engine object in the report's scope. That exception is written down in the
test rather than merely taken.

**16 new tests, 782 passing, 3 skipped. `ruff check` clean, `tsc --noEmit` clean.**

### Known, and deliberately left

- **Enum-valued fields are typed `str`, not literal unions.** `mode`, `rung`, `family` and
  their neighbours carry an enum's `.value`, and a union would describe today better. It
  would also mean a run stored under one engine version failing to validate under the next
  one that adds a rung — the exact property 5.1b must not have.
- **`predictions` is the payload's bulk.** 960 records on a 40×12 demo, 5,760 on a real
  120-unit corridor over 24 periods, and `run.json` for the demo corridor is 311 kB. That
  is a live question for 5.1c's response size, not for this step.
- **The generator emits no runtime validators**, only types. The page trusts the payload it
  is handed, which is correct while the payload comes from the same process that wrote it
  and becomes a question again when it arrives over a network.

### Fixed on the way past: the cache's failure handler was the thing that failed

Development moved to WSL this day, because Windows enabled Smart App Control and it blocks
unsigned native binaries — numpy, pandas and pydantic-core among them. The first full suite
on Linux failed one test, and it was not an artefact of the move.

`FileCache.put` wraps its write in `except OSError`, under the comment *"a cache that cannot
write is a slow pipeline, not a broken one"*. The handler then calls
`temporary.unlink(missing_ok=True)` to tidy up — **outside any try**. `missing_ok` swallows
`FileNotFoundError` and nothing else, so on a cache path whose parent is a file the unlink
raises `NotADirectoryError`, and the handler written to absorb the failure became the thing
that propagated it.

Windows had hidden it by reporting that same condition as `ENOENT`, which `missing_ok` does
absorb. So the test that names the promise —
`test_an_unwritable_cache_is_a_slow_pipeline_not_a_broken_one` — passed on one platform and
failed on the other, for the whole of Stage 2, and only ever ran on the one where it passed.

The cleanup now sits inside `suppress(OSError)`. Three other tests skip on Linux for
environmental reasons rather than defects: `arviz` is absent, and there is no Chrome or Edge
in WSL for the two PDF-printing tests.

---

## 2026-08-24 — Step 5.0: the rule, before there is code able to break it

**Delivered:** the layering rule, as a test. `roadrisk.core` must never be imported *by* —
only imported *from*. That has been written in the package docstring and in `STEPS.md`
since Stage 0, it has held for five stages, and nothing enforced it.

```bash
pytest tests/test_layering.py
```

### Why now, and not later

Stage 5 adds two packages whose entire job is to sit above `core` and call into it. That is
exactly when a convention stops being enough: an import in the wrong direction is one line
to write, invisible in review, and a refactor to undo once anything depends on it.

The rule is also the reason several other things in this package are true. The geospatial
dependencies are an optional extra because `core` never reaches for them. GDAL — needed by
two adapters of seventeen — is never pulled in by an assessment. `report` renders from JSON
because it cannot name an engine type. None of those survive a single wrong import, and
none of them announce their own death when it happens.

### Parsed, not imported

Half this package is behind extras the test suite deliberately does not install: `geo`
needs shapely and pyproj, the raster adapters need GDAL through rasterio, the MCMC fallback
needs emcee. A test that imported modules to inspect their dependencies **could not see the
layers it most needs to police** — it would skip them, or fail for the wrong reason.

So the whole thing is `ast` over the source. It sees every import in the repository whether
or not it could be executed on this machine, and it costs 0.3 s.

### Four rules, and the fourth is the one the docstring would have missed

| Rule | What it protects |
|---|---|
| Imports point downhill only | `core → demo → geo → report → api → worker → cli` |
| `core` imports nothing but `core` | The engine runs on pandas and statsmodels alone |
| `report` imports nothing but `report` | 4.1's done-when — a stored run re-renders without a refit |
| `roadrisk/__init__.py` stays a leaf | The loophole |

**The loophole.** `core` imports `roadrisk` for `__version__`. If the package root ever
re-exported something from `roadrisk.geo`, then importing the engine would import shapely —
and every direct import would still point downhill, and the other three rules would still
pass. The rule as stated for five stages does not cover it, because the violation is
transitive and the rule is about direct imports.

Proven rather than argued: planting `from roadrisk.geo import demo` in `__init__.py` did not
merely fail this test, it broke `import roadrisk` outright with a circular-import error
from `roadrisk.geo.adapters`. The loophole is not theoretical and it is not cheap.

### `demo` sits above `core`, which took a moment's thought

`roadrisk/demo.py` generates the synthetic panels the engine is tested on, so the instinct
is to file it as a utility underneath everything. It is the opposite: a synthetic panel is
an *input* to the library, not part of it, and an engine able to reach for its own test
fixture is a different and worse package. It ranks above `core` and `core` may not import
it.

Verified as a side effect: `demo.py` imports nothing from `roadrisk` at all.

### `api` and `worker` are declared before they exist

They are in the layer order with nothing in them. That is the point of doing this as 5.0
rather than after 5.1 — the constraint is in place before the code that could violate it is
written, so it never has to be retro-fitted against work that already assumed otherwise.

A separate test fails on any package that appears on disk without being placed in the order,
so a future `roadrisk/billing/` cannot pass by being unmentioned. A layer nobody has placed
is a layer nothing constrains.

### A test that cannot fail is decoration

Everything above passes today because the rule has held, which means none of it demonstrates
that a violation would be *caught*. Two answers to that:

- One test plants a violation in a temporary file and reads the failure back, so the
  detection logic is exercised on every run.
- All four rules were checked once against violations planted in the real source and then
  reverted. Each names the file, the line and the rule it broke:

```
roadrisk\core\engine.py:1196 imports roadrisk.geo.pipeline — 'core' may not import 'geo'
roadrisk\report\limitations.py:587 imports roadrisk.core.engine
roadrisk\__init__.py:11 imports roadrisk.report
```

### The graph as it stands

Clean, and strictly layered, with no relative imports anywhere:

| Layer | Imports |
|---|---|
| `core` | `core`, and `roadrisk` for the version string |
| `demo` | nothing from `roadrisk` |
| `geo` | `core`, `geo` |
| `report` | `report` — **not `core`, not `geo`** |
| `cli` | everything |

`report` importing neither `core` nor `geo` is worth noticing: 4.1 said a report renders
from `assessment.json` and `corridor.json` with no engine object in scope, and the import
graph now shows that this is structurally true rather than merely observed. `build_run` is
duck-typed against anything with an `as_dict()`.

**6 new tests, 769 passing. `ruff check` clean.**

### Known, and deliberately left

- **The relative-import branch is untested against real code**, because the package has no
  relative imports. It is implemented anyway, so the test does not quietly cease to apply
  the first time somebody writes one.
- **`DICT_ONLY` will need to admit the contract package at 5.1a.** The payload schema is
  pure description with no engine types, so importing it does not cost `report` the property
  this test exists to protect — but it is a deliberate relaxation and should be recorded as
  one rather than made quietly.

---

## 2026-08-21 — Step 4.7: coordinates to a readable report in one command. Stage 4 complete.

**Delivered:** the seam. One command from a road to something a client can open, with
every estimator the engine has reachable from the geometry path — and a mislabelling bug
found by finally running that path end to end.

```bash
roadrisk corridor --demo --report out/          # report.html + the JSON behind it
roadrisk corridor --demo --out out/ --pdf       # the whole run record, printed too
roadrisk assess panel.csv --bayes --report out/ # credible intervals, on a panel
```

### `corridor` could not reach the Bayesian rung at all

It called `assess()` with a context and nothing else. No estimator, no priors, no spatial
flag, no splines. **The whole of Stage 3 was unreachable from the geometry path** — a
corridor assessed from coordinates could only ever produce p-values, while the brief asks
for credible intervals in the report and `assess` had offered them since 3.3.

`--shape`, `--bayes`, `--priors` and `--spatial` now exist on both commands, defined
once and shared, so the two cannot drift apart. A test asserts the option sets match.

### `--report`, for when the report is all you want

`--out` writes the run record — panel, provenance, confidence, snap detail, the JSON, the
report. `--report` writes the report and the two JSON payloads it was built from, and
nothing else. A path ending `.html` is taken as the filename; anything else is a
directory.

The JSON travels either way because it has to: the report's own no-JavaScript fallback
tells a reader the same numbers are in `assessment.json` and `corridor.json`, and that
sentence has to be true wherever the file lands.

### The bug this step existed to find

Running `--bayes` through to a rendered page for the first time surfaced something that
had shipped in 4.3 and survived three steps of review:

**`posterior.coefficients` is a mapping keyed by factor name, not a list.** The page's
TypeScript typed it as an array and looked a factor up with `.find()`. That returns
`undefined` for every row — so every coefficient silently fell back to its *frequentist*
confidence interval, while the column header, keyed only off the posterior's existence,
kept saying **"95% credible interval"**.

Frequentist numbers under a Bayesian heading is the one mislabelling this report must
never make, and nothing caught it: the types were wrong, so the compiler agreed; the
fallback was silent, so the page looked right; and no test had ever rendered a converged
posterior. It took an actual `--bayes` run, read on screen, to see it.

Fixed at three levels — the type now says `Record<string, PosteriorSummary>` with a
comment explaining why the distinction matters, the lookup is by key, and two tests pin
it: one asserting `as_dict()` produces a mapping keyed by factor, one asserting the
bundle contains no `.find(` over coefficients.

**A second, related mislabelling closed with it.** A posterior that *exists* is not a
posterior that can be *believed*. When the inference ladder runs out of rungs — Laplace
refused, MCMC failed to mix — `posterior` is present, unconverged and carries nothing.
Reading its mere presence as "we have credible intervals" was the same bug in another
costume. The page now requires `converged` and a non-empty mapping, says plainly that a
Bayesian fit was attempted and could not be believed, quotes the last line of the
descent, and the limitations page records that the intervals shown are the narrower
frequentist ones.

### What `--bayes` costs on the demo corridor

Worth writing down, because it looks like a hang and is not.

`roadrisk corridor --demo --bayes` with the default 24 periods runs for **tens of
minutes**. The engine is behaving correctly: Laplace is refused at 24, 48 and 96
quadrature nodes (Pareto k̂ 0.82, above the 0.7 gate), it descends to MCMC, the chains do
not mix (R-hat 1.45 on σ_u against a 1.01 gate), and it **reports nothing rather than an
interval from chains that have not mixed**. That is the honesty machinery working, at the
cost of a long wait on a synthetic corridor whose σ_u is barely identified from 22
segments.

Nothing here was tuned to make that faster. Loosening a convergence gate to speed up a
demo would be exactly the trade this project exists not to make. `--periods 8` finishes
in 5 seconds; a real panel that clears the gates — 120 units, 24 periods — takes 50.

**Stage 4 is complete.** Coordinates in, a printed, sourced, caveated report out.

**11 new tests, 763 passing.**

### Known, and deliberately left

- **The demo's default period count is not tuned for `--bayes`.** Changing it would
  change the demo for every other flag too, and that is a product decision rather than a
  fix.
- **`--report` and `--out` can both be given.** They write two reports to two places,
  which is what was asked for.

---

## 2026-08-21 — Step 4.6: what this assessment cannot tell you

**Delivered:** the limitations page. Its own sheet at the back of every report,
assembled from what the run actually did, with nothing anywhere that turns it off.

### It is data, not prose

Written as paragraphs inside the layout it would be two things at once: something
somebody could quietly delete, and something that goes stale the moment the engine
changes. Built from the payload it can do neither. It cannot describe a run other than
the one it came from, and a new failure mode reaches the page the day it is implemented
rather than the day someone remembers to write it down.

Almost all of the material was already on the assessment — the checks that failed, the
terms that were dropped, the factors that were missing, the receipts, the validation
outcome, the crash mix. What was missing was a module that reads those and says what
each one **costs the reader**.

Severity is about that cost, not about how bad a thing sounds:

| | |
|---|---|
| **material** | Changes what you may conclude. Read before the numbers. |
| **caveat** | Qualifies a number without invalidating it. |
| **context** | Worth knowing; changes nothing on its own. |

### Nothing removes it

`collect_limitations` takes two arguments and neither of them is a flag. `build_run` has
no parameter with "limit" or "skip" in its name. The page renders it with no condition,
no ternary and no prop that can empty it. Tests assert each of those by inspecting the
signatures rather than by trusting the code to stay that way.

**And the list is never empty.** A run with nothing at all wrong with it still carries
the standing caveats — this is an association rather than a cause, and everything here
comes from one road — because a report whose limitations page said nothing would be
making a claim it cannot support. `collect_limitations({}, None)` on a completely empty
payload returns them, which is the strongest version of that test there is.

If it somehow *does* arrive empty, the page says so and calls itself defective rather
than rendering silence.

### What it picks up

Mode B's ranking-only status · the refusal and descent receipts · every failed check,
hard ones as material and soft ones as caveats · every skipped check, because *a check
that did not run is not a check that passed* · missing, collinear and constant factors ·
sign contradictions · validation that failed or could not run · the default crash mix ·
an undeclared context · the unpinned HSM edition · posted speed standing in for
operating speed · crashes that did not land on the corridor, with their reasons · a
self-intersecting centreline · stale cached source data · Tier B and lower factors,
which *are not measurements* · factors carried rather than measured on most segments.

### Two things fixed by printing it and reading it

**A wall of registry prose.** The first version pasted every missing factor's
`missing_behaviour` into one paragraph. On a corridor with twenty absent factors that
produced half a page of developer documentation — *"On M51, adding speed doubled the
curvature coefficient"*, *"the suppressor is lost"*, *"this is the factor iRAP charges
50-200 USD/km to obtain"* — in the middle of a client report. The factor names are
useful and traceable and stay. The prose is documentation for whoever maintains the
registry, and it stays in the run record where it belongs.

**Three pairs of duplicate headings.** Two items titled *"How the validation was set
up"* with different text under each, and two more titled *"Something in the pipeline is
worth knowing about"*. A repeated heading reads as a bug whatever it says underneath, so
each group is now one entry. A test asserts no two limitations share a title.

### On paper

The page starts a new sheet — it is the one section a reader goes looking for, and it is
last, so nothing is pushed around by giving it one.

That exposed a paged-media subtlety worth recording: `break-after: avoid` on a heading
only binds it to the element *immediately* after it, which here is the band's lead
paragraph. Heading and lead were stranded together at the foot of a page with every item
overleaf. The lead has to carry the avoidance on to the list, and the first item has to
refuse to start a page on its own.

**25 new tests, 753 passing.**

### Known, and deliberately left

- **Severity is assigned by rule, not judged.** A soft check failure is a caveat and a
  hard one is material, always. There is no case yet where that is wrong, and a rule
  that can be read off the code beats one that cannot.
- **No per-limitation link to the section it came from.** A reader who wants the detail
  behind *"check 4 failed"* scrolls to the checks table. Cross-links are cheap and can
  wait for someone to ask.

---

## 2026-08-21 — Step 4.5: the PDF is the report printed, not a second one rendered

**Delivered:** a six-page A4 document with the mode banner on every page, page counters,
tables that keep their headers across a break, and the risk ramp still in colour.

```bash
roadrisk corridor --demo --pdf --out run/
# → run/report.html   run/report.pdf
```

### There is still only one renderer

The PDF is `report.html` loaded into a headless browser and printed. Not converted, not
re-rendered, not templated a second time — **printed**. The screen and the paper cannot
disagree because there is only one document, and every rule that turns it into a printed
one is `@media print` CSS on the page itself.

This is what the Stage 4 re-scope was for. A Jinja template plus a React UI would have
been two renderers in two languages, drifting the first time either changed. Instead the
question *"does the PDF match what the client saw?"* has no way to be answered wrongly.

**WeasyPrint was reconsidered and is still out.** It cannot render this page at all: the
report is a React application, so its content does not exist until a script has run.
Printing the page clients actually read is the only way to be certain the file matches.

### The running banner, and the flag that lies

The brief wants the mode banner on every page of the PDF. A page banner has to come from
paged-media CSS — there is no element that repeats — and Chrome supports `@page` margin
boxes and page counters but **not `string-set`**.

It does not need to. One report is one mode, so the banner is identical on every page and
is baked into a `@page { @top-center { content: "…" } }` rule at render time. The banner
text is escaped for a CSS string context first: a stray quote would end the string and
leave a broken rule, which fails as *a PDF with no running header* rather than as an
error.

`--print-to-pdf-no-header` is not optional and is easy to get wrong. The flag that reads
like the obvious one, `--no-pdf-header-footer`, is **silently ignored**, and without the
right one Chrome stamps a date and the file's own `file:///` URL onto every page of a
client deliverable. A test pins the correct flag.

### Colour is information here, not decoration

Browsers drop background fills when printing, on the reasonable theory that they are
decoration and ink is expensive. In this document the risk ramp, the mode banner and
every status tag **are** the information — a risk strip printed white says nothing at
all. `print-color-adjust: exact` overrides the helpfulness.

### Paged defects, found by printing it and looking

- **A one-word-per-line citation.** Seven columns on A4 squeezed the source column into a
  ribbon reading *"Circumradius / of the / centreline / resampled to"*. The first fix —
  `table-layout: fixed` — made it **worse**: equal columns squeezed it further and the
  last two headers collided outright. The actual culprit was `white-space: nowrap` on the
  header row, which is right on screen where width is spare and is exactly what steals it
  on paper. Letting print headers wrap fixed both.
- **Split tables and orphaned headings.** `thead { display: table-header-group }` so the
  blackspot table carries its header onto page two, `break-after: avoid` on every heading,
  `break-inside: avoid` on figures, receipts, caveats and table rows.
- **The screen's page furniture.** The shell background, the card border and the
  Print button are chrome; paper has its own, so they are removed rather than printed.

### Printing it without a person

`roadrisk.report.to_pdf()` drives the browser, and `--pdf` on `assess` and `corridor`
calls it. **The browser is not a dependency of anything.** Nothing is needed to produce a
report — the HTML is complete on its own and any reader can press Ctrl+P — so a missing
browser is reported as *what to do instead*, with the path to the HTML and the
`ROADRISK_BROWSER` override, and the exit code stays whatever the assessment itself
earned. This exists for the runs that have to be stored or emailed without a person in
the loop, which is what the Stage 5 worker will need.

Discovery checks `ROADRISK_BROWSER`, then `PATH`, then the usual install locations on
Windows, macOS and Linux. An explicit path that does not exist returns nothing rather
than falling back to a different browser — quietly printing with something other than
what was asked for would make a reproducibility claim that is not true.

**16 new tests, 728 passing.**

### Known, and deliberately left

- **A4 only.** No Letter, no landscape, no margin options. One page size until somebody
  needs a second.
- **No PDF outline or internal links.** Chrome generates neither from headings here. A
  six-page document does not need a table of contents; a forty-page one would.
- **Chrome and Edge only.** Firefox and Safari have no headless print-to-PDF flag worth
  relying on. Both are perfectly good for printing by hand.

---

## 2026-08-20 — Step 4.4: pictures, and three ways a report can go blank

**Delivered:** the figures. A risk strip along the chainage, the corridor in plan, CURE
plots, calibration bars and the spline diagnostic — all SVG, all drawn from arrays that
were already in the payload.

And three separate bugs found by *opening the thing and looking at it*, each of which
turned a complete assessment into a blank or near-blank page.

### The figures

| Figure | What it answers |
|---|---|
| **Risk strip** | Where along this road is the problem, and is it one place or several |
| **Corridor map** | The same, on the shape of the actual road |
| **CURE plots** | Is any factor entered in the wrong shape |
| **Calibration** | Does the model get the level right on road it did not see |
| **Spline** | What shape a relationship has — filed under reference, never a finding |

No plotting library, no image requests, nothing fetched. A test asserts there is not one
`<img>` in the document: a figure that needed a CDN would be a blank rectangle in an
emailed report, which is the one thing this page exists to survive.

### The colour scale was computed, not chosen

Risk is a magnitude, so it gets a **sequential ramp — one hue, light to dark**. Never a
rainbow, never a categorical palette pressed into service as a value scale.

The six steps were run through a validator rather than eyeballed, and the first four
candidates **failed**: the pale end sat at 1.22:1, then 1.52, then 1.65, then 2.00
against a white page — below the 2:1 floor at which a mark stops reading as a mark. The
shipped ramp starts at `#e9a468` (2.11:1) and passes every check: monotone lightness,
visible gaps between steps, hue spread 18°. Because it varies by lightness rather than
hue it survives being printed in grey, and colour is never the only channel — the ranked
table carries the same numbers beside every figure.

### Three ways the report went blank, all fixed

**1. Scripts blocked → a white page with no explanation.** `<div id="root"></div>` shipped
empty, so anywhere JavaScript does not run — a sandboxed preview pane, an email client's
viewer — the reader got nothing at all. The root now ships with a message saying the file
is intact, that it needs a browser, and where the same numbers are. React replaces it on
mount, so nobody who can read the report ever sees it.

**2. One `NaN` → a file picker instead of the report.** This is the nastiest of the three.
`ValidationReport` produced `mean_absolute_deviation: NaN` for a fold that had nothing to
compare, Python wrote it as a bare `NaN` token, and **`JSON.parse` rejects that**. The
page cannot tell an unparseable run from an absent one, so it did exactly what it was
built to do with no run — it offered a file picker. A complete assessment, silently
replaced by an upload prompt.

Non-finite floats are now nulled recursively at the seam — `null` is what JSON has for
"could not be computed", and losing a whole report over one uncomputable diagnostic
would be the worse trade — and `allow_nan=False` then refuses to serialise anything
non-finite that survives. A test parses a real run with `parse_constant` set to raise,
because `json.loads` accepts `NaN` by default and a browser never does.

**3. One null → the entire tree unmounted.** With the NaNs turned into nulls, a formatter
called `.toLocaleString()` on one and threw. React unmounts everything on an uncaught
error, so one missing diagnostic erased every number, every receipt and every licence,
leaving white.

Two fixes. Every formatter now takes `number | null | undefined` and renders an en dash
rather than throwing — the payload legitimately contains nulls, and the types now say so.
And there is an **error boundary**: a rendering failure is held to a message that names
the error, says the assessment itself is intact, and points at the JSON beside it.

The pattern in all three is the same, and it is the one this project applies everywhere
else: **fail loudly, never silently**. A report that cannot draw itself must say so.

### Also fixed by looking

- **A duplicated scale key.** The strip and the map sit together and share one ramp; two
  identical legends stacked was noise. The map's caption now says "on the same scale as
  the strip above".
- **Calibration drew bars of zero.** When the held-out folds contain no crashes, observed
  and expected are both zero and the factor is undefined — a bar chart of that reads as
  *"the model predicted nothing"* rather than *"there was nothing to check it against"*.
  It now says the latter, in a sentence.

**11 new tests, 712 passing.**

### Known, and deliberately left

- **No hover tooltips beyond native `<title>`.** Every mark carries one, which works
  without JavaScript and prints harmlessly. A richer hover layer is a screen-only
  feature and belongs with 5.3, not in a document.
- **The map is equirectangular, scaled about the corridor's own mean latitude.** Over
  tens of kilometres the distortion is far below the width of the drawn line. A corridor
  spanning degrees of latitude would need a real projection.
- **No print stylesheet yet.** 4.5.

---

## 2026-08-20 — Step 4.3: something a client can actually read

**Delivered:** the report. One HTML file, written beside the run, that opens by
double-clicking it.

```bash
roadrisk corridor --demo --out run/
# → run/report.html
```

### One renderer, and why it is not Jinja

The original plan for this stage said *"same template serves the web page and the
PDF"*, which assumed a Jinja template rendered in Python. Stage 5.3 is React. Those two
together are **two renderers in two languages**, kept in visual sync by hand, drifting
the first time either changes.

So there is one renderer and it lives in the UI. `web/src/Report.tsx` is what a client
reads on screen, what will print to PDF at 4.5, and what 5.3 imports as its report tab —
not a copy of it. The JS toolchain arrives at 4.3 instead of 5.3, which is paying early
rather than paying extra: Stage 5 was always going to need it.

It takes a plain object and nothing else. No fetching, no routing, no engine types —
everything it renders came out of `Assessment.as_dict()` and `CorridorPanel.as_dict()`,
which is exactly what 4.1 built and why a run stored months ago renders identically
today.

### The report opens with nothing running

That is the done-when for this step, and it is not an arbitrary bar. A corridor can be
assessed with **no network and no API key**. A report that then needed a web server to
be read would have put the network back into the one product that does without it.

Two consequences, both forced:

**The run is injected, not fetched.** A browser will not `fetch()` a local file —
`file://` requests are blocked by CORS with no origin to grant one. So the payload is
written *into* the document as a JSON script block and the page reads it out of its own
DOM. `roadrisk.report.render_report` does the injection; the page does
`getElementById("roadrisk-run")`.

**Everything is inlined.** No stylesheet, no asset directory, no CDN — one file, 314 KB
for the demo corridor. A report is a thing you email, and an emailed report that loses
its formatting is not a deliverable. A test asserts there is not a single `<link>`
element in the output, which also disarms the one piece of the bundle that can call
`fetch` at all: Vite's module-preload polyfill walks `<link rel="modulepreload">` tags,
and there are none.

### Injection is the dangerous part, so it is the tested part

A value containing `</script>` would end the block early and spill the rest of the run
into the document as markup. In JSON a `<` can only ever appear inside a string literal,
so escaping every one as `<` is both sufficient and lossless — a corridor genuinely
named `</script><img src=x onerror=alert(1)>` survives the round trip intact and cannot
break out. The payload is ASCII-only for the same reason: the document's encoding cannot
change what the page parses.

And a template that has drifted **fails loudly**. If the front end ever renames the
placeholder, `render_report` raises rather than quietly handing a client a report with
no run in it and a file picker where the numbers should be.

### What is on the page

Everything the CLI already prints, in the order a reader needs it rather than the order
the engine computes it:

- **The mode banner**, first thing, coloured, with the rung beside it
- **Four headline tiles** — corridor length, segments, crashes, worst segment
- **Receipts** — the refusal and the descent, in a box that cannot be scrolled past
- **Where to look first** — blackspot runs with chainage extents, then the worst 20
  segments with observed, expected and the 95% interval
- **What the model found** — coefficients, with credible intervals substituted
  automatically when a posterior is present, and the clustering note underneath
- **Where every number came from** — one row per factor: source, tier, licence,
  coverage, confidence, and who contested it
- **The data this rests on** — the panel, and every crash the snapping dropped, by reason
- **What was checked** — all nine gates and what each one means
- **Credits and licensing** — the credit lines, and the share-alike sentence a client
  redistributing the panel needs to have read

Mode B's count columns are not rendered as dashes. The page reads `has_intervals` and
omits the columns, because a column of dashes invites a reader to think a number was
missing rather than never estimated.

### Also

- **The bundle is committed.** Installing this package never needs Node; only changing
  the page does. `cd web && npm run build` rewrites
  `src/roadrisk/report/static/index.html`.
- **A fallback file picker.** Opened on its own, the bundle offers to read
  `assessment.json` and `corridor.json` from disk, so a run directory without a
  generated report is still readable. Nothing is uploaded — `FileReader` works where
  `fetch` does not.
- **`assess --out` writes a report too**, with the geography half absent. The page drops
  the provenance and licensing sections rather than inventing them.

**15 new tests, 701 passing.** The page's rendering was verified by opening the built
file in a browser; what the suite pins is everything that would silently produce a
report with no run in it.

### Known, and deliberately left

- **No figures.** No map, no CURE plots, no spline curves, no risk strip along the
  chainage. Every one of those is a picture and pictures are 4.4. The corridor geometry
  is already in the payload waiting for them.
- **No print stylesheet.** Printing it today gives browser defaults. `@page`, the running
  banner and the page counters are 4.5.
- **No limitations page.** 4.6, and it will be generated from the run rather than
  written into the layout.
- **Light theme only, deliberately.** This is a document before it is a web page. A
  report that changed colour with the reader's OS setting would print differently for
  different people.

---

## 2026-08-20 — Step 4.2: one ranked table, and runs that break where the road breaks

**Delivered:** the answer to the question a client actually asks. Not *"what are the
coefficients"* — **which bit of road do I look at first, and is it one bad segment or a
length of road with a problem.**

```bash
roadrisk corridor --demo --out run/
```

```
                       Worst 10 of 22 units
┌────┬───────────┬──────────┬──────────┬──────────┬──────────────┐
│  # │ Unit      │    Score │ Observed │ Expected │ 95% interval │
├────┼───────────┼──────────┼──────────┼──────────┼──────────────┤
│  1 │ demo-0020 │ 0.004269 │       46 │     37.4 │  32.1 – 43.6 │
│  2 │ demo-0018 │ 0.004235 │       40 │     37.1 │  32.4 – 42.6 │
└────┴───────────┴──────────┴──────────┴──────────┴──────────────┘

         Blackspots — runs in the worst 20%
┌───┬───────┬─────────────────────────┬────────────┐
│ 3 │     3 │ 7,000–8,500 m (1,500 m) │ demo-0016  │
└───┴───────┴─────────────────────────┴────────────┘
```

### One table, two modes, and the number that must not leak

Mode A produces an expected crash rate from a fitted model. Mode B produces a weighted
index score from published weights. These are not the same kind of number and never will
be. But *"which segment first"* is **one** question, and a report that answers it twice
in two shapes has handed the reader the join.

So there is one ranked table. Both modes fill in `unit_id`, `rank`, `percentile` and
`score`, worst first. Mode A additionally fills in what it actually estimated — observed,
expected, an interval, exposure, rate. Mode B fills in none of those.

**They are absent from Mode B's rows, not present and null.** A null count is still a
count-shaped hole, and a renderer meeting `"expected": null` puts a dash in a column that
should not have existed — which reads as *"not available"* rather than *"this mode does
not produce one"*. `UnitRisk.as_dict()` omits the keys, and a test asserts none of the
six count fields appears anywhere in a serialised Mode B ranking. The same rule reaches
the blackspots: a Mode B blackspot has no observed and no expected either.

Mode B's crash-type components do ride along, because a unit that ranks badly should be
readable for *why* — a run-off problem and an intersection problem call for different
countermeasures.

### The interval, and what kind of interval it is

Each unit's expected count is the sum of its rows' fitted means. The interval around it
comes from the delta method: with a log link `d(mu)/d(beta) = mu * x`, so the gradient of
the unit total is `sum(mu_r * x_r)`, and the variance is that gradient through the fit's
own parameter covariance.

**It is a confidence interval on the expected count** — where the model's estimate of the
mean sits. It is not a prediction interval for next year's actual count, which would be
wider and is a different question. The module docstring says so rather than leaving a
reader to assume the more flattering reading.

**The panel correction travels for free.** When the fit clustered its standard errors by
unit — which rung 2 does whenever there are enough clusters — the covariance this reads
is the clustered one, because it comes from the fitted model rather than being
re-derived. Step 3.1's widening reaches the ranking without a line of code saying so.

**And it refuses rather than inventing.** A fit that exposes no parameter covariance
produces a ranking with expected counts and no interval, plus a note saying the order is
unaffected and the uncertainty around it is simply not reported.

### Blackspots break where the road breaks

A single bad segment is usually a bad segment. Six bad segments in a row is a length of
road with a problem. So flagged units are grouped into contiguous runs — and the
interesting part is what ends a run.

A run continues only while the next unit is **both flagged and physically adjacent**.
Adjacency is decided by chainage when the caller supplies it: a unit whose start does not
meet the previous unit's end is the far side of a gap, and a blackspot spanning it would
be describing road the panel does not cover. That is the difference between *"these eight
units are one blackspot"* and *"these are two blackspots either side of a junction"*.

`assess()` gained one optional argument for this — `corridor_units`, a list of
`(unit_id, start_m, end_m)` in corridor order. `CorridorPanel.corridor_units` builds it
from the segmentation, and the CLI passes it. With it, blackspots carry real chainage
extents. Without it, order falls back to sorted unit ids and adjacency is positional —
the same assumption the spatial field makes at 3.3c — and the ranking **says so in its
notes** rather than leaving it implicit.

Three things end a run, each with a test: a chainage gap, a unit the panel does not
contain, and a unit that did not clear the threshold. Runs are then ordered against each
other by their worst member, so blackspot #1 contains the worst segment on the corridor.

The default threshold is the worst quintile. A blackspot list that flags half the corridor
is a list nobody acts on.

### Also

- **`ranking.csv` is now written for both modes.** It came from Mode B's index before, so
  a Mode A run produced no ranking file at all.
- The CLI prints the ranked table and the blackspot runs on every assessment.

**24 new tests, 686 passing.**

### Known, and deliberately left

- **The threshold is not tunable from the CLI.** `DEFAULT_THRESHOLD_PERCENTILE` is a
  constant. Exposing it is a flag and a docstring, and worth doing when someone asks for
  a different band rather than before.
- **Blackspots do not aggregate across a corridor's own discontinuities.** A corridor is
  one chain by construction, so this only matters once comparison across corridors exists.

---

## 2026-08-20 — Step 4.1: the report model, and the licence nobody reads

**Delivered:** the seam between the engine and anything that renders it. Two payloads —
`assessment.json` and `corridor.json` — that between them carry everything a report
needs, and carry it as JSON rather than as Python.

### Why this is a step and not plumbing

`Assessment.as_dict()` has described itself as *"the shape the API and the report
template consume"* since Stage 1. It was nearly true. Two things were missing, and both
were the kind of missing that only shows up when something tries to consume it.

**The geography did not serialise at all.** `CorridorPanel` had no `as_dict()`.
`provenance` and `confidence` were DataFrame properties that reached a CSV or a terminal
and nowhere else — so the report's central promise, *every factor with its source, tier,
licence and confidence*, lived in a format no renderer could read. Licences were worse
than absent: they were present, as prose inside adapter notes.

**Mode A predicted nothing anyone could see.** `fitted_values` was on `FitResult` and was
dropped by `_fit_as_dict`. Mode B has serialised its per-unit ranking since 1.4;
Mode A's predictions existed only in memory, which is why 4.2 has nothing to rank yet.

### What was built

**`CorridorPanel.as_dict()`** — corridor, segmentation, panel summary, snap report,
adapters with what each resolved and skipped, provenance, per-unit confidence, contested
factors, scored disagreements, cache ages, warnings.

Geometry is included, in WGS84 and GeoJSON's `(longitude, latitude)` order, because the
corridor map is part of the report rather than a separate product and a consumer that has
to reproject is a consumer that will eventually swap the pair. Coordinates are rounded to
six decimals — about 0.1 m, finer than any centreline this tool consumes, and it keeps a
long corridor's geometry from dominating the payload it travels in.

**`predictions` on the Assessment** — one row per panel row: `unit_id`, `period`,
`time_slot`, `observed`, `expected`, `exposure`. Keyed, because 4.2 ranks by unit and an
unkeyed list of numbers is not something anything can group.

Per-row rather than per-unit on purpose. Aggregation is 4.2's job; what belongs at this
seam is the raw material, in the one form that cannot be reconstructed from anything else
in the payload.

**It refuses twice.** A fit that did not converge returns no predictions — a fitted value
from a failed fit is not a prediction, and shipping it would let a report draw a corridor
out of numbers the engine already refused. And if the fitted values ever fail to align
with the panel's index, the answer is no predictions rather than NaN: `json.dumps` emits
a bare `NaN` for those, which is not JSON at all, and the failure would surface as a
report with holes in it rather than as an error.

**Mode B still predicts nothing.** `predictions` is `None` there and serialises as
`null`. A mode that has no predicted count must not acquire one by being serialised, and
a test says so.

### The attribution collector

`roadrisk.geo.attribution` turns the licence riding on every `FactorValues` into the two
sentences a client actually needs. The distinction is the entire point, and it is the one
`Licence`'s own docstring has always made:

- **Who must be credited in the report.** ODbL, CC-BY-SA and CC-BY-4.0 all require it.
  A line of text discharges it.
- **What happens if they redistribute the panel.** ODbL and CC-BY-SA impose share-alike
  on a derived *database*. A report is not a database; the panel CSV is. A client who
  publishes the panel inherits an obligation they will not have read about, and the only
  defensible moment to say so is before they do.

Collapsing the two into "attribution required" would understate the second. Treating
every licence as share-alike would overstate the first — CC-BY-4.0 is a separate rung in
the enum precisely so that it is not read as CC-BY-SA.

Two smaller decisions:

- **A rejected source is owed nothing.** Fusion's loser never reached the report, so it
  creates no obligation. Only the value that won is counted.
- **An unrecognised licence fails safe.** It is reported as unrecognised, marked as
  requiring credit, and told to check its terms — never quietly treated as permissive.

Where an adapter attached explicit credit text — the Copernicus DEM and ESA WorldCover
both do, as notes prefixed `ATTRIBUTION REQUIRED.` — that exact wording travels through
to the credit line instead of being reconstructed here from an adapter's name.

### The test that is the deliverable

`json.dumps(payload, default=str)` is not a check. It is a way of hiding a DataFrame, an
enum or a Timestamp by stringifying it, after which the report is reading a repr and
nobody notices. So the payloads are walked instead, asserting every leaf is a JSON
primitive and naming the path of the first that is not.

Both payloads pass with no `default=` escape hatch. The done-when is then written as the
thing a renderer actually does: dump both to disk, read them back, and assert the report
is reachable with no engine object anywhere in scope.

### Also

`roadrisk corridor --out` now writes `corridor.json` beside `assessment.json`. Without it
the payload existed and nothing emitted it.

**24 new tests, 662 passing.** A demo corridor produces a 155 KB `corridor.json` and a
129 KB `assessment.json`; the corridor's own centreline geometry is the largest single
item in either.

### Known, and deliberately left

- **Nothing ranks yet.** `predictions` is per-row raw material. Ranking, blackspot
  aggregation and the constraint that Mode B rows carry no interval are 4.2.

---

### Fixed on the way past: the banner could not be redirected

Found while running the CLI end to end for this step, and pre-existing. The mode banner
carries a coloured circle and the receipts carry arrows and sigmas. When stdout is a
terminal, Python writes through the Windows console API and all of it survives. Redirect
it — `roadrisk corridor > report.txt`, a CI log, a worker capturing its child — and
Python drops to the locale encoding instead, cp1252 on a Western Windows install, and the
first emoji raises `UnicodeEncodeError` part-way through printing the assessment.

Losing a whole run because a character would not fit the log it was being written into is
not a trade anyone would choose. The CLI now reconfigures both streams to UTF-8 at
startup, falling back to `errors="replace"` for a stream that cannot be reconfigured, so
the floor is a substituted character rather than an exception.

Invisible to the suite until now because Typer's runner captures output differently from
a real redirect, so the three new tests exercise the reconfiguration directly.

---

## 2026-08-19 — Step 3.3c: neighbours, not strangers. Stage 3 complete.

**Delivered:** a Leroux CAR field over the corridor chain, fitted by a joint Laplace
approximation over the latent field, reporting ρ with a credible interval — and saying
plainly when the corridor is too short to tell.

```bash
roadrisk demo --units 80 --periods 12 --spatial
```

**Verified:** 638 tests pass (16 new), `ruff check` clean.

### This was recorded as blocked, and the record was half right

The note under 3.3c said the quadrature in 3.3a integrates each unit's effect out
separately, that this works *only* because units are independent, and that a CAR field
couples them so the integral stops factorising. All true.

What it missed is that the **outer** half of that module never cared where the marginal
came from. The inference ladder operates on a marginal log posterior over a handful of
hyperparameters. Swapping the inner quadrature for a joint Laplace over the whole latent
field left mode-finding, the importance check, the reporting and the refusal paths
untouched. **The block was in one function, not in the design** — and it only became
visible once 3.3a's Laplace machinery existed to reuse.

The reuse is real rather than copied: `_find_mode` and `_hessian` were refactored to take
the log posterior as a callable, so both modules share one optimiser and one numerical
derivative instead of two that could drift apart.

### A corridor is a path graph, which is what makes it affordable

Neighbours are the units either side, so the precision matrix is tridiagonal. Newton's
method needs a banded solve, the determinant needs a banded Cholesky, both O(units), and
one marginal evaluation on eighty units costs about **two milliseconds**. None of the
awkward areal cases — islands, disconnected components, wildly uneven neighbour counts —
occur on a road.

### Leroux, because it nests what already exists

    Q = (1 / sigma_u²) [ (1 - rho) I + rho R ]

`rho = 0` is rung 2's independent random intercept **exactly**; `rho → 1` approaches the
intrinsic CAR limit. So this is a strict generalisation, and "does this corridor cluster"
becomes "is rho credibly above zero" — one posterior rather than two models compared.
A test asserts the nesting: at rho near zero the coefficients agree with the independent
fit.

### Measured against planted truth, in both directions

| Planted | Estimated | Reported as |
|---|---|---|
| ρ = 0.0 | 0.21 [0.01, 0.56] | *no spatial clustering worth modelling* |
| ρ = 0.9, 80 units | **0.89 [0.73, 0.98]** | *neighbouring segments are correlated* |
| ρ = 0.9, 40 units | 0.44 [0.05, 0.86] | *this corridor cannot tell* |

The second row is the point; the first is what stops it being a machine for finding what
it went looking for. Both halves are pinned by tests.

### The caveat was predicted, and is now measured rather than feared

`STEPS.md` warned that a spatial field and a per-unit random intercept both live at unit
level and compete for the same variance, so ρ might not be identifiable on the fifty to a
hundred and twenty units a corridor has. It is — above about eighty. Below that the
interval spans most of the unit line and the report says the corridor **cannot tell**,
rather than presenting 0.44 as a finding. That is an answer about the road, not a failure
of the fit, and the run says which it is.

A draw ladder was added for the same reason the node ladder exists in 3.3a: this
posterior carries one more dimension than the independent one, and on a short corridor
the outer approximation needs more importance draws before its weights behave. Escalating
is cheaper than refusing.

### Two approximations are now stacked, and that is stated

A Laplace over the latent field inside, and the existing Laplace-with-importance-check
over the hyperparameters outside. **The importance check polices only the outer one.**
That is written into the module docstring rather than glossed, and it is why the MCMC
fallback still exists.

### Stage 3 is complete

Panel-clustered standard errors (3.1), the spline that hunts the U-shape (3.2), the
Bayesian random-intercept GLMM (3.3a), the registry's cited weights as priors (3.3b), the
spatial field (3.3c) and out-of-sample validation (3.4). The next thing between this
package and something a client can read is Stage 4.

---

## 2026-08-19 — Step 3.4: does it predict road it has not seen

**Delivered:** cross-validation over contiguous stretches of corridor, CURE plots, and
calibration on held-out units. **Reported on every Mode A run, pass or fail** — there is
no flag that enables it and none that disables it, and a test asserts no such parameter
ever appears.

**Verified:** 622 tests pass (22 new), `ruff check` clean.

### Held-out stretches, not held-out rows

Adjacent segments share their terrain, their design standard, their traffic and the
persistent unobserved character step 3.3a exists to estimate. A random fold leaves a
segment's own neighbours in the training set, so the model half-remembers the answer.
Both schemes are computed and printed together, because the optimism of the easy one
should be visible rather than something a reader takes on trust.

| Scheme | Observed | Predicted | Ratio | MAD |
|---|---|---|---|---|
| contiguous stretches | 2,803 | 2,756 | 1.02 | 1.044 |
| random units | 2,803 | 2,722 | 1.03 | 1.042 |

On the synthetic panel the gap is small, which is itself worth knowing: the generator
draws each segment's character independently, so neighbours are *not* alike and the
spatial concern does not bite. On a real corridor it will. The number is reported either
way, and it is the only honest way to find out which case a corridor is in.

### CURE plots say where a factor is wrong

Calibration says whether the model is wrong on average. Cumulative residuals against a
factor say *where* on its range — the question no single number answers.

```
curve_density: outside its bounds over 22% of the range, worst around 0.25.
          cumulative residual, with ±2σ bounds
     +220 |        .....................
          |  ###********                .......
          | ...         * ****                 ...
          |.             *    ***                 .#
        0 |**--------------------*----------------*.
          |.                      **              .
          | ...                     ** ****    ...
          |    ....                   * ...**#####
     -220 |        .....................
```

This is step 3.2's defect seen from the other side, and the verdict says so: CURE finds
*where*, the spline explains *what shape*. Stage 3's two diagnostics now point at each
other.

### The bounds needed rung 2's correction, and finding that out was the work

The textbook CURE band assumes every residual is an independent draw. This panel's
residuals are not: each factor is a segment property repeated down every period, so a
segment the model fits badly contributes a *run* of same-signed residuals and the
cumulative sum wanders far beyond an independent-increment band.

The first implementation therefore condemned a correctly specified model. Measured on
the synthetic panel, whose effects are **planted linear**:

| Per-unit heterogeneity | Share of curve outside bounds |
|---|---|
| none | 0–6%, correctly nothing |
| 0.25 | 7–23% |
| 0.5, the realistic default | **16–60%, every bit of it spurious** |

Three of four correctly specified factors were being reported as mis-specified. This is
step 3.1's defect — *the same segment measured eighteen times is not eighteen
observations* — arriving somewhere new, and it would have been easy to accept as a real
finding about the model.

**The fix:** residuals are summed within a segment before anything accumulates, which
removes the correlation inside a unit, and the remaining inflation is *measured* rather
than assumed — the variance of the standardised unit residuals, 6.42× on the realistic
panel. The band is widened by it and the factor is reported.

**The correction did not just widen until nothing fires**, which was the obvious way to
get a green light and would have been worthless. A planted U-shape still reads 22%
outside its bounds and still names **only** the guilty factor, with the other three
clean. Both halves are pinned by tests, because a diagnostic that never fires and one
that always fires are equally useless.

### Declined below 25 units

Five folds of five segments measure noise. The run says so, states what is missing —
*any evidence that it predicts road it has not seen* — and is careful not to imply the
fit above it is worse than it is. The same reasoning as rung 2's twenty-cluster floor.

### What it cannot do, said in the run rather than left to be inferred

It validates the specification against the corridor's own crash data. It cannot say
whether that crash data is any good, and on synthetic crashes it is measuring the
generator. Position along the corridor is taken from the sort order of `unit_id`, which
is how the segmentation numbers them — a panel whose ids do not sort into corridor order
would get folds that are contiguous in name only, and that assumption is recorded.

---

## 2026-08-19 — Step 3.3b: the registry's weights become the priors

**Delivered:** the brief's unifying idea, implemented. Mode B's cited weights are Mode
A's prior means, and every factor is reported three ways — what the literature says, what
this corridor says alone, and the two combined — with the share of each answer
attributable to the literature.

```bash
roadrisk demo --units 40 --periods 12 --priors --facility-type rural_two_lane --region europe
roadrisk assess panel.csv --priors
```

**Verified:** 600 tests pass (27 new), `ruff check` clean.

### Three answers, and the engine names one

Showing one number hides where it came from. Showing three without designating one
pushes the choice onto the reader, who will pick the one that suits them — so the engine
designates, the same way it already designates the mode.

```
Factor            Textbook   Your data      The mix   %bk  Reading
speed_limit         +1.600      +0.348       +0.880   34%  prior steadies it
                            [-0.41,+1.12] [+0.21,+1.59]
curve_density            —      +0.487       +0.328    —   shifted 0.5 SE by another prior
```

`%bk` is the auditing device: the share of the mixed answer that came from the published
weight rather than from this road, taken from the precision each side pulls with. It is
readable without any statistics, which is the point.

### It gets weaker as the data gets better, without being told to

The same generator at two sizes, three factors, planted `speed_limit` = +0.90:

| | 691 crashes | 5,782 crashes |
|---|---|---|
| Designated answer | **the mix** | **your data** |
| `speed_limit` alone | +0.375 [−0.41, +1.15] — spans zero | +0.896 [+0.52, +1.27] |
| `speed_limit` mixed | +0.900 [+0.23, +1.60] | +1.026 |
| Prior share | 34% | **11%** |

The rich corridor found the planted value on its own. The thin one could not, and the
literature carried it there. **No rule produces that** — it falls out of the arithmetic,
and it is the check that the priors are not quietly doing the work everywhere.

### Where the confidence in a prior comes from

Not typed in per factor. Derived from what the registry already records: agreement
between sources tightens a prior, each recorded concern widens it. `speed_limit` carries
a standing caveat — the Elvik exponent applies to operating speed and the column holds
posted limit — so its prior loosens without anybody remembering to loosen it.

A finding from doing this: the agreement half rarely fires, because most factors have
exactly one admissible weight for a given context, and one source cannot agree with
itself. In practice the width is driven by concern count.

### Crash scope is a dilution, and it matters more than expected

Mode A fits total crashes; iRAP prices several factors per crash type. A weight covering
run-off and head-on crashes cannot move the total rate by its full value, so it is
diluted by that type's share — the first-order term of the exact combination Mode B
performs. `lit` is the case that makes it concrete: an intersection-crash weight, diluted
by a 10% share, arrives as a prior mean of **−0.014**. Correctly almost silent about
total crashes.

### A defect this exposed in its own first output

The first run reported `curve_density` as *"no cited weight — this road's data alone"*
while its estimate had moved from +0.414 to +0.255 between the two fits.

Coefficients are correlated, so a prior on `speed_limit` drags its neighbours. **A factor
with no weight of its own is not insulated from everyone else's**, and the report was
saying it was. It now measures the movement in standard errors and says
*"shifted 0.5 SE by another prior"*. There is no way to report a mixed fit honestly
without that number.

### Four guards, each against a specific way this could mislead

- **`expected_sign` is never a constraint.** A truncated prior would make
  `P(β has the wrong sign)` identically zero and delete the sign guard by construction.
  Every prior is a plain normal with support on both sides of zero, asserted by a test.
- **Contradiction is judged on the corridor-only fit.** Asking the mixed fit whether it
  disagrees with the textbook asks a question the prior has already influenced.
- **A prior-dominated coefficient may not become a crash count.** Mode B refuses to
  produce a count from published weights alone; the same number arriving through a prior
  gets the same rule, and the designation says so in words.
- **Off by default.** `--bayes` alone is unchanged, so every number published before
  today still reproduces. Part of a prior-informed answer is somebody else's evidence,
  and that is the user's choice to make rather than the engine's.

### The wart, recorded rather than smoothed over

The prior *widths* — 0.35 for a clean cited weight, ×1.25 per concern, floored at 0.15 —
are a judgement, not a citation. A package whose registry refuses uncited weights now
carries uncited confidence levels. They are derived from what the registry already knows
rather than invented per factor, and the floor guarantees roughly 400 crashes' worth of
evidence can always overrule any of them. Keeping the feature opt-in is what stops those
numbers reaching a default result.

---

## 2026-08-17 — Step 3.3a: credible intervals, and a wrong diagnosis caught late

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

*Stated plainly so nothing here is mistaken for more than it is. Kept current — every
line below was true on 2026-08-26, after step 5.1b. The list this replaced was written
when Stage 1 was the whole product and had gone comprehensively out of date.*

- **No web layer, no hosting.** No API, no worker, no accounts, no map UI. Nothing is
  deployed and there is no public URL. The report page is React and Stage 5.3 will
  import it. Stage 5 has begun, and what exists of it is groundwork rather than a web
  layer: the layering rule as a test, the payload contract the API will return, and the
  storage the worker will write to. None of it serves an HTTP request.
- **Persistence exists but nothing is multi-user.** Runs can be kept in Postgres, listed
  and re-rendered, and the schema is tenant-scoped from its first migration — but there
  is no authentication behind those tenants, so a tenant id is a label rather than an
  identity. The database enforces that rows cannot cross tenants; nothing yet enforces
  who you are when you claim to be one. That is 5.4a.
- **No corridor comparison.** Two runs can be stored and listed side by side, and
  nothing reads into a payload to compare them.
- **Still validated on two corridors.** B9 and N201. Nothing in Stages 3 or 4 changed
  that, and nothing will: a third real road is the critical path, and no amount of
  engine or report work substitutes for it.
- **Two open decisions still need a human.** A licensed AASHTO HSM, to pin equations
  read from a draft edition to a verifiable artefact; and one operating-speed survey, to
  remove `speed_limit`'s permanent caveat. Both are recorded in
  [`STEPS.md`](STEPS.md#open-decisions).
- **PostGIS is still deferred.** A 100 km corridor fits in memory and the geographic
  cache covers the repeat-fetch case. Persistence is a Stage 5 concern.
- **No vision-model inference.** `roadside_object_density` comes from pre-extracted
  Mapillary detections, not from running a model over imagery. Tier B factors beyond
  the two that exist are unbuilt.
- **The report is one page size.** A4 portrait, no Letter, no landscape. Its PDF path
  needs Chrome or Edge; the HTML needs nothing, and any browser can print it by hand.
