"""The runner the API talks to, and the web factory that hands it one.

`roadrisk.api.app.create_app` has taken a `runner` argument since 5.1d, with a docstring
saying exactly this: *a Celery runner lives in `roadrisk.worker`, which sits above this
package and therefore cannot be imported from here — so it arrives as an argument, from
whoever composes the process.* This is that composer.

`roadrisk serve` cannot pass the argument itself, because it hands uvicorn a factory **by
name** so that `--reload` can re-import it in a fresh process. So the name it hands over
changes instead: `roadrisk.worker.web:create_app` rather than `roadrisk.api.app:create_app`.
Same application, one argument different, and the layering rule holds — this file may
import the API, and the API still cannot import this.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import FastAPI

from roadrisk.api.app import create_app as create_api
from roadrisk.worker.app import configure, submit


class CeleryRunner:
    """Puts the job on a queue and returns. Something else, somewhere else, runs it.

    The whole interface is `submit`, and it says nothing about *when* — which is the
    point 5.1d made when it wrote the protocol down. `POST /jobs` was already a 202; what
    changes underneath is that the job now survives this process.
    """

    #: Reported by `GET /health`, so a client can tell this deployment from one running
    #: jobs in a thread pool inside itself. The two differ in exactly one way that
    #: matters to somebody polling: work in flight survives a restart here.
    name = "celery"

    def __init__(self, broker: str | None = None) -> None:
        configure(broker)

    def submit(self, tenant_id: UUID, job_id: UUID) -> None:
        submit(tenant_id, job_id)


def create_app(**kwargs: object) -> FastAPI:
    """The API, with the queue behind it.

    Every other argument passes through untouched, so this is the API's factory with one
    thing decided. It raises at startup when `$ROADRISK_BROKER_URL` is unset, which is
    the right moment: a service that accepted jobs and queued them nowhere would look
    perfectly healthy.
    """
    return create_api(runner=CeleryRunner(), **kwargs)  # type: ignore[arg-type]


__all__ = ["CeleryRunner", "create_app"]
