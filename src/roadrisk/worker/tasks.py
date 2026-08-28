"""The one task.

One, because the unit of distribution is a job — see `app.py` for why it is not a branch.
A corridor arrives here as two strings and everything else is already in the database,
so there is no serialisation to write in either direction: that was the cost the boxed
note under 5.2a warned about, and choosing the job as the unit is what avoids paying it.

**The task cannot fail.** `execute` never raises — every outcome becomes a status on the
job, because since 5.1d its caller has been a pool thread with nobody to raise at, and now
it is a worker with the same problem. So there is no retry policy here and no error
handler: a job that broke is a `failed` row with a cause, which is a thing a client can
read, rather than a traceback in a log a client cannot.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from roadrisk.api.runner import execute
from roadrisk.worker.app import (
    TASK_NAME,
    celery_app,
    worker_registry,
    worker_store_provider,
)

log = logging.getLogger("roadrisk.worker")

#: Resolved once per worker process rather than per task. The provider hands out a
#: connection per use, so this is a factory rather than a connection — but reading the
#: environment and loading the registry on every message would be work done thousands of
#: times to reach the same answer.
_provider: Any = None
_registry: Any = None


def bind(provider: Any, registry: Any = None) -> None:
    """Give this process its store and registry instead of letting it read the environment.

    The worker's equivalent of `create_app(store_provider=…)`, and it exists for the same
    two reasons: a test wants a store it can inspect, and a host that embeds this wants to
    say which database rather than set a variable and hope. A worker started by
    `roadrisk worker` never calls it and reads the environment, which is the normal path.
    """
    global _provider, _registry
    _provider = provider
    _registry = registry


@celery_app.task(name=TASK_NAME, ignore_result=True)
def assess(tenant_id: str, job_id: str) -> None:
    """Run one job to completion, and write down what happened.

    Strings rather than UUIDs because the wire is JSON, and JSON has no UUID. Parsed
    here, at the edge, so that everything below this line is typed.
    """
    global _provider, _registry
    if _provider is None:
        _provider = worker_store_provider()
    if _registry is None:
        _registry = worker_registry()

    try:
        with _provider() as store:
            execute(store, UUID(tenant_id), UUID(job_id), registry=_registry)
    except Exception:  # pragma: no cover - only when the store itself is gone
        # `execute` already turns every outcome into a status. This is the belt for the
        # case where the store is unreachable and even that could not be written down:
        # the message is already acknowledged, so without this the job would sit in
        # `queued` with nothing said about it anywhere.
        log.exception("Job %s could not be executed or marked failed", job_id)


__all__ = ["assess"]
