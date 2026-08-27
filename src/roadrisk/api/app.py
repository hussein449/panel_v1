"""The application, assembled.

A factory rather than a module-level `app`, for one practical reason and one structural
one. Practically, the test suite needs an app over a `MemoryStore` and a deployment
needs one over Postgres, and a module-level object would have to read the environment at
import time to know which — so importing the module would open a database connection.
Structurally, the store provider is the seam 5.2a swaps and 5.4a puts identities behind;
a factory makes that an argument rather than a monkey-patch.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import FastAPI

from roadrisk import __version__
from roadrisk.api import errors
from roadrisk.api.deps import StoreProvider, per_request_postgres, shared_store
from roadrisk.api.routes import ROUTERS
from roadrisk.api.runner import InlineRunner, Runner, ThreadedRunner
from roadrisk.api.settings import ApiSettings
from roadrisk.contract import SCHEMA_VERSION
from roadrisk.core.registry import Registry, load_registry
from roadrisk.store import JobStatus, MemoryStore, Tenant
from roadrisk.store.postgres import DSN_ENV

log = logging.getLogger("roadrisk.api")

#: How old a `running` job must be before a starting process reclaims it, in seconds.
#: Unset means reclaim everything — correct for one process, wrong for several. See
#: :func:`_reclaim_before`.
RECLAIM_AFTER_ENV = "ROADRISK_RECLAIM_AFTER_SECONDS"

#: Which runner this process gets: ``in-process`` (a bounded thread pool, the default),
#: ``inline`` (runs inside the request — for a single-user machine that would rather
#: wait than poll), or ``none`` (a deployment that only serves stored runs).
RUNNER_ENV = "ROADRISK_RUNNER"

#: How many jobs the in-process pool runs at once. Two, because a fit is CPU-bound and
#: this is sharing a process with the web server — the point of the pool is a *bound*,
#: not throughput. Throughput is 5.2a, on machines that do nothing else.
RUNNER_WORKERS_ENV = "ROADRISK_RUNNER_WORKERS"
DEFAULT_RUNNER_WORKERS = 2

#: A tenant id to create in the **in-memory** store at startup. See :func:`_seed_tenant`.
#: `roadrisk serve --tenant` sets it; a Postgres deployment ignores it and has a command.
MEMORY_TENANT_ENV = "ROADRISK_MEMORY_TENANT"

#: Distinguishes "no runner argument was given" from "a runner of None was given".
#: Both are meaningful and they are not the same: the first takes the environment's
#: answer, the second is a caller stating that nothing should execute jobs.
_UNSET: Any = object()

#: Shown at the top of the generated documentation. Every sentence in it is something a
#: client would otherwise have to discover by watching a job never finish or by
#: assuming a header is a credential. Step 5.3b makes the same two facts a layout
#: element on every screen; this is the API's version of that banner.
DESCRIPTION = f"""
Corridor road-risk assessment from open data, with provenance.

**Start here: `POST /jobs` with `{{"project_id": "…", "demo": true}}`.** It assesses a
synthetic 10 km corridor, needs no data and no network, and finishes in seconds — submit
it, poll `GET /jobs/{{id}}` until it succeeds, then read `GET /jobs/{{id}}/run`. The
report that comes back says on its own face that there is no real road in it.

**Two things about this deployment, stated here rather than discovered.**

* **Jobs run inside this process.** `POST /jobs` returns `202` and a bounded pool picks
  the job up; work in flight does not survive a restart, and there is no retry. Step
  5.2a moves execution onto workers. `GET /health` names the runner this process has,
  and reports `null` if it has none — in which case a job stays `queued` for ever.
* **`X-Tenant-Id` is not authentication.** It scopes every read to one tenant, which is
  what keeps two clients' runs apart, but nothing verifies the claim. Step 5.4a
  replaces it with real identities and row-level policies in the database.

**A refusal is a result, not an error.** A panel that breaks the input contract is a
`422` naming the column, and no job is created. An assessment that descended to Mode B,
dropped a term or declined to score an unsourced weight is a **`200`** — those are
findings the run carries, not failures. Infrastructure breaking is a job whose status is
`failed`, with a cause and never a stack trace.

Payload shape version `{SCHEMA_VERSION}`. Factors, tiers and licences come from
`factors.yaml`; `GET /registry` serves it with the hash of the file it was read from.
"""


def create_app(
    *,
    store_provider: StoreProvider | None = None,
    settings: ApiSettings | None = None,
    registry: Registry | None = None,
    runner: Runner | None = _UNSET,
) -> FastAPI:
    """Build the application.

    Args:
        store_provider: How each request gets a store. Defaults to a Postgres store per
            request when ``$ROADRISK_DATABASE_URL`` is set, and to a single in-process
            :class:`~roadrisk.store.MemoryStore` otherwise — which is a real service
            that forgets everything when it stops, and is the right default for someone
            trying the API out before they have a database.
        settings: Defaults to :meth:`ApiSettings.from_env`.
        registry: Defaults to the `factors.yaml` shipped with the package. Loaded once,
            here, so a malformed registry stops the process at startup instead of
            failing one request in a way that looks like a client error.
        runner: What executes submitted jobs. Defaults to
            :class:`~roadrisk.api.runner.ThreadedRunner`, which is what keeps
            ``POST /jobs`` a 202 — an inline runner behind HTTP would turn the 55.5 s
            cold corridor into a request a proxy times out. Pass ``None`` explicitly
            for a deployment that only serves stored runs; jobs then stay ``queued``
            and ``GET /health`` reports ``runner: null``.

            **This is the seam 5.2a replaces.** A Celery runner lives in
            ``roadrisk.worker``, which sits *above* this package and therefore cannot
            be imported from here — so it arrives as an argument, from whoever composes
            the process, rather than as a branch in this function.
    """
    app = FastAPI(
        title="Road Risk Panel",
        version=__version__,
        description=DESCRIPTION,
        summary="Corridor risk from open data, with every number traceable.",
    )

    app.state.settings = settings or ApiSettings.from_env()
    app.state.registry = registry or load_registry()
    app.state.store_provider = store_provider or _default_provider()
    app.state.runner = (
        _default_runner(app.state.store_provider, app.state.registry)
        if runner is _UNSET
        else runner
    )

    errors.install(app)
    for router in ROUTERS:
        app.include_router(router)

    if app.state.runner is not None:
        _reclaim_orphans(app.state.store_provider, app.state.runner)
    return app


def _reclaim_orphans(provider: StoreProvider, runner: Runner) -> None:
    """Take back jobs a previous process left `running`, and start them again.

    **The hole step 5.1d left.** A process that stops mid-job leaves that row `running`
    for ever: the runner refuses to start a job that is not `queued` — which is what
    stops two runners producing two runs from one submission — so nothing ever picks it
    up again, and `GET /jobs/{id}` goes on answering *running, please wait* to a client
    who will wait for the rest of their life. The inputs were never at risk; the only
    thing missing was any way to know the work should be done again.

    Done here rather than in a request, because a restart is exactly when it is knowable
    and because doing it per request would mean every reader paying for a sweep.

    Only when there is a runner. A deployment that executes nothing must not requeue
    work it cannot do — that would be moving jobs from one kind of stuck to another.

    Failures are logged and swallowed: a database that cannot be reached at startup is a
    problem, and refusing to serve `GET /health` because of it makes that problem harder
    to diagnose rather than easier.
    """
    try:
        with provider() as store:
            reclaimed = store.reclaim_running_jobs(started_before=_reclaim_before())
    except Exception:
        log.exception("Could not reclaim orphaned jobs at startup")
        return

    requeued = [job for job in reclaimed if job.status is JobStatus.QUEUED]
    for job in requeued:
        runner.submit(job.tenant_id, job.id)

    if reclaimed:
        log.warning(
            "Reclaimed %d job(s) left running by a previous process: %d requeued, "
            "%d failed after too many attempts.",
            len(reclaimed),
            len(requeued),
            len(reclaimed) - len(requeued),
        )


def _reclaim_before() -> datetime | None:
    """How old a `running` job must be before a starting process takes it back.

    `None` — reclaim everything still running — is the default and is correct for the
    deployment that exists: `roadrisk serve` starts one uvicorn process with one pool,
    so anything `running` when it starts is by definition nobody's.

    Set `$ROADRISK_RECLAIM_AFTER_SECONDS` above your longest job if more than one
    process shares a database, or a starting process will take back a job another one is
    still working on. That is the case a heartbeat or a lease owner solves properly, and
    it belongs with the Celery work in 5.2a rather than here.
    """
    raw = os.environ.get(RECLAIM_AFTER_ENV)
    if not raw:
        return None
    try:
        seconds = float(raw)
    except ValueError as exc:
        raise ValueError(
            f"${RECLAIM_AFTER_ENV} must be a number of seconds, got {raw!r}."
        ) from exc
    return datetime.now(UTC) - timedelta(seconds=seconds)


def _default_provider() -> StoreProvider:
    dsn = os.environ.get(DSN_ENV)
    if dsn:
        return per_request_postgres(dsn)
    store = MemoryStore()
    _seed_tenant(store)
    return shared_store(store)


def _seed_tenant(store: MemoryStore) -> None:
    """Create the tenant named by ``$ROADRISK_MEMORY_TENANT``, if there is one.

    **The gap step 5.3b walked into.** Running in memory is offered as a real way to try
    the service, and it was not one: every route that touches a row requires a tenant,
    tenants are made by `roadrisk store new-tenant`, and that needs a database. So the
    memory deployment had no tenant, no way to make one, and answered *No tenant …* to
    everything a client could usefully ask. `roadrisk serve --tenant` closes it, and the
    environment is how it reaches this factory — the same channel the runner uses, for
    the same reason: uvicorn is handed the factory by name so that `--reload` works, and
    there is nowhere for the CLI to pass an argument.

    Postgres deliberately does not read this. A store that outlives the process has a
    command for creating tenants, run by a person who can see what it did.

    A malformed value stops the process rather than being ignored: the alternative is a
    service that starts, looks healthy, and refuses every request for a reason nobody
    can see.
    """
    raw = os.environ.get(MEMORY_TENANT_ENV, "").strip()
    if not raw:
        return
    try:
        tenant_id = UUID(raw)
    except ValueError as exc:
        raise ValueError(
            f"${MEMORY_TENANT_ENV} must be a UUID, got {raw!r}. It is the id of the "
            "tenant to create in the in-memory store; `roadrisk serve --tenant` "
            "generates one."
        ) from exc

    store.create_tenant(Tenant(id=tenant_id, name="local"))
    log.warning(
        "In-memory tenant %s created at startup. It exists for as long as this process "
        "does, and so does everything filed under it.",
        tenant_id,
    )


def _default_runner(provider: StoreProvider, registry: Registry) -> Runner | None:
    """Read `$ROADRISK_RUNNER`, because the factory is called with no arguments.

    `roadrisk serve` hands uvicorn this function *by name* — that is what makes
    `--reload` work, since uvicorn re-imports the target in a fresh process — so there
    is nowhere for the CLI to pass anything in. The environment is the only channel,
    which is the same answer storage already gives.
    """
    choice = os.environ.get(RUNNER_ENV, "in-process").strip().lower()
    if choice == "none":
        return None
    if choice == "inline":
        return InlineRunner(provider, registry=registry)
    if choice == "in-process":
        return ThreadedRunner(
            provider, max_workers=_worker_count(), registry=registry
        )
    raise ValueError(
        f"${RUNNER_ENV} must be one of in-process, inline or none — got {choice!r}."
    )


def _worker_count() -> int:
    raw = os.environ.get(RUNNER_WORKERS_ENV)
    if not raw:
        return DEFAULT_RUNNER_WORKERS
    try:
        count = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"${RUNNER_WORKERS_ENV} must be a whole number, got {raw!r}."
        ) from exc
    if count < 1:
        raise ValueError(f"${RUNNER_WORKERS_ENV} must be at least 1, got {count}.")
    return count


__all__ = [
    "DEFAULT_RUNNER_WORKERS",
    "DESCRIPTION",
    "RECLAIM_AFTER_ENV",
    "RUNNER_ENV",
    "RUNNER_WORKERS_ENV",
    "create_app",
]
