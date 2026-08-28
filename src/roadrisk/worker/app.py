"""The Celery application, and the one decision step 5.2a existed to make.

**What is distributed, and what deliberately is not.** The boxed note under 5.2a offered
two shapes and said the choice between them was the first thing to make when this was
picked up: fan out over *branches* — one task per adapter — or fan out over *fetches* and
let the results meet in the cache. This does neither. It fans out over **jobs**: one task,
one corridor, start to finish.

The reason is a measurement already in this repository. The fetch cache is a directory on
one machine, and it is what turns 55.5 s into 1.2 s for the next corridor in the same
region. Spreading an assessment's *branches* across machines spreads its fetches across
caches, so every worker pays the cold price and the second corridor is never cheap. The
branch-level chord is not merely a larger change than it looks — until the cache is
shared, which is object storage at 6.2, it would be **slower than the threads it
replaces**. So it waits for 6.2, and the row in *What is left* says so.

What the queue buys at job granularity is exactly what the note said was missing:
**durability and more than one machine.** A submitted job is a message a broker holds,
not a future inside the accepting process, so a deploy no longer eats work in flight —
and any number of workers can drain the same queue.

**There is no result backend, and that is not an omission.** The result of a job is a row:
its status, and the run it produced. Celery keeping a second copy would be a second answer
to a question the database already answers, and the two could disagree.

**No broker is assumed.** `$ROADRISK_BROKER_URL` has no default, for the reason
`$ROADRISK_ARTEFACT_ROOT` has none: the failure mode of no default is a message naming the
variable, and the failure mode of a convenient default is a service that looks healthy and
queues into nothing.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from celery import Celery
from celery.signals import worker_ready

from roadrisk.api.app import reclaim_before
from roadrisk.api.deps import StoreProvider, per_request_postgres
from roadrisk.core.registry import Registry, load_registry
from roadrisk.store import JobStatus
from roadrisk.store.postgres import DSN_ENV

log = logging.getLogger("roadrisk.worker")

#: Where the queue is. No default — see the module docstring.
BROKER_URL_ENV = "ROADRISK_BROKER_URL"

#: The one task. Named explicitly rather than by module path, so that moving this file
#: does not orphan messages already sitting in a queue.
TASK_NAME = "roadrisk.assess"

#: Built at import with no broker, so that importing this package needs no configuration
#: — a test, `roadrisk --help`, and the layering check all do it. :func:`configure` is
#: what points it at a queue, and Celery reads the broker at connection time rather than
#: at construction, which is what makes that legal.
celery_app = Celery("roadrisk")
celery_app.conf.update(
    # The job row is the result. See the module docstring.
    result_backend=None,
    task_ignore_result=True,
    task_serializer="json",
    accept_content=["json"],
    # One job at a time per worker process by default: a fit is CPU-bound and a corridor
    # holds a store connection while it runs. Concurrency belongs to
    # `roadrisk worker --concurrency`, where the operator knows the machine.
    worker_prefetch_multiplier=1,
    # Acknowledge on delivery, not after. `acks_late` would have the broker redeliver a
    # job whose worker died — but `execute` refuses to start anything that is not
    # `queued`, and a dead worker leaves the row `running`, so the redelivery would be
    # refused and the job would sit there for ever. Recovery is the reclaim below, which
    # is the mechanism the API has used since 5.1d. Two recovery mechanisms that do not
    # know about each other produce a job that neither will touch.
    task_acks_late=False,
    timezone="UTC",
    enable_utc=True,
)


def broker_url() -> str:
    """Read `$ROADRISK_BROKER_URL`, or say what it is for and give two examples."""
    url = os.environ.get(BROKER_URL_ENV, "").strip()
    if not url:
        raise RuntimeError(
            f"${BROKER_URL_ENV} is not set, so there is no queue to put jobs in. It is "
            "a Celery broker URL — redis://localhost:6379/0 for a real deployment, or "
            "filesystem:///var/tmp/roadrisk-queue for one machine with no server to "
            "install. This package ships no broker and will not guess at one."
        )
    return url


def configure(url: str | None = None) -> Celery:
    """Point the app at a queue. Called by the runner and by `roadrisk worker`."""
    resolved = url or broker_url()
    celery_app.conf.broker_url = resolved
    celery_app.conf.broker_transport_options = transport_options(resolved)
    return celery_app


def transport_options(url: str) -> dict[str, Any]:
    """What `filesystem://` needs, which is a directory rather than a server.

    Kombu's filesystem transport takes its folders from transport options and **ignores
    the URL's path**, which makes `filesystem:///var/tmp/queue` look like it works and
    then queue into the process's working directory. So the path is read here and turned
    into the options the transport actually reads.

    Worth supporting at all because it is the only broker that needs nothing installed:
    one machine, two processes, a directory between them. Not for production — it polls a
    filesystem — but it is what makes `roadrisk worker` runnable on a laptop, and it is
    what the cross-process test in `tests/test_worker.py` runs against.
    """
    if not url.startswith("filesystem://"):
        return {}

    path = Path(urlparse(url).path or "/var/tmp/roadrisk-queue")
    control = path / "control"
    for directory in (path, control):
        directory.mkdir(parents=True, exist_ok=True)

    return {
        "data_folder_in": str(path),
        "data_folder_out": str(path),
        "control_folder": str(control),
        # Delete a message once it has been read. Keeping them is a debugging aid that
        # becomes a disk which fills up.
        "store_processed": False,
    }


def worker_store_provider() -> StoreProvider:
    """How a worker reaches the store, which has to be a database.

    **A queue across processes needs a store across processes.** `MemoryStore` is a real
    store and the right default for `roadrisk serve` on one machine — but its state *is*
    the object, so a worker holding one would drain a queue of jobs it cannot see and
    write runs nobody can read. Refused at startup, naming the variable, rather than
    discovered as a worker that looks healthy and finds no work.
    """
    dsn = os.environ.get(DSN_ENV)
    if not dsn:
        raise RuntimeError(
            f"A worker needs ${DSN_ENV}. The queue hands it a job id, and the job is a "
            "row — with the in-memory store it would be looking for that row inside its "
            "own process, where nothing put one. Point it at the database the API uses."
        )
    return per_request_postgres(dsn)


def worker_registry() -> Registry:
    """Loaded once per worker process, for the reason the API loads it once per app.

    A malformed `factors.yaml` should stop a worker starting rather than fail one job in
    a way that reads like a client error.
    """
    return load_registry()


def submit(tenant_id: Any, job_id: Any) -> None:
    """Put one job on the queue.

    The import is late because `tasks` imports this module for the app; one of the two
    directions has to be, or neither loads.
    """
    from roadrisk.worker.tasks import assess

    assess.delay(str(tenant_id), str(job_id))


@worker_ready.connect
def _reclaim_on_start(**_: Any) -> None:
    """Take back jobs a dead worker left `running`, and put them back on the queue.

    The same mechanism `create_app` runs at startup, moved to where the work now happens.
    With `acks_late` off, a worker that dies takes its message with it: the row stays
    `running` and nothing would pick it up again. This is what does — the next worker to
    start, guarded by `job.attempts` so that a job whose own execution kills the process
    is failed rather than looped on.

    It assumes, as the API's copy does, that a reclaiming process is not racing a live
    one. `$ROADRISK_RECLAIM_AFTER_SECONDS` is the answer for a fleet — set it above your
    longest job — and a heartbeat or a lease owner is the proper one, which belongs with
    6.2.

    Failures are logged and swallowed: a worker that cannot reach the database at startup
    has a problem, and refusing to start would make it a harder one to see.
    """
    try:
        provider = worker_store_provider()
        with provider() as store:
            reclaimed = store.reclaim_running_jobs(started_before=reclaim_before())
    except Exception:  # pragma: no cover - only when the store itself is unreachable
        log.exception("Could not reclaim orphaned jobs at worker startup")
        return

    requeued = [job for job in reclaimed if job.status is JobStatus.QUEUED]
    for job in requeued:
        submit(job.tenant_id, job.id)

    if reclaimed:
        log.warning(
            "Reclaimed %d job(s) left running by a dead worker: %d requeued, %d failed "
            "after too many attempts.",
            len(reclaimed),
            len(requeued),
            len(reclaimed) - len(requeued),
        )


__all__ = [
    "BROKER_URL_ENV",
    "TASK_NAME",
    "broker_url",
    "celery_app",
    "configure",
    "submit",
    "transport_options",
    "worker_registry",
    "worker_store_provider",
]
