"""Step 5.1c — the product, over HTTP.

Until now this has been a command you run on your own machine against a folder you must
not delete. This is the layer that makes it a service: projects and corridors are rows a
client creates, a job is a resource with a status, and a finished run is a URL.

**Everything here is a consumer.** The payload shape is `roadrisk.contract` (5.1a), the
rows are `roadrisk.store` (5.1b), and the factors, tiers and licences come out of
`factors.yaml` at startup. Nothing in this package describes any of those a second time,
which is the whole lesson of 5.1a: two descriptions of one contract in two places is how
`posterior.coefficients` spent three steps silently rendering the wrong interval.

**Three things this layer is responsible for getting right.**

*A refusal is a result, not an HTTP error.* The REST instinct collapses every
non-success onto 4xx and 5xx, and doing that here would swallow the entire honesty layer
into a generic error handler. Three outcomes stay distinct, and `roadrisk.api.errors`
is where that is enforced:

===============================================  =======  =============================
Outcome                                          HTTP     Why
===============================================  =======  =============================
``ContractViolation`` at submit                  **422**  The panel was rejected. No job
                                                          exists. The column is named.
Mode B, a dropped term, a refused weight         **200**  Mode B is the floor. The
                                                          engine's refusals are content,
                                                          and the run carries them.
Overpass 429, no token, no GDAL                  job      Infrastructure failed. Never a
                                                 ``failed``  500 with a stack trace.
===============================================  =======  =============================

*The job resource is asynchronous from its first endpoint.* Measured in this repository:
a cold corridor is 55.5 s (2.9), ``--bayes`` on the demo corridor runs for tens of
minutes (4.7). No HTTP request survives that. ``POST /jobs`` returns **202** today with
nothing behind it, so that 5.1d attaching a runner and 5.2a attaching Celery change what
executes a job and not what a client was promised.

*Tenancy is a required argument, not a filter.* `roadrisk.store` made every read take a
tenant with no default; this keeps that true over the wire. ``X-Tenant-Id`` is required
on every route that touches a row, and 5.4a replaces the one dependency that reads it
with a real credential. **It is not authentication and the API says so** — see
:mod:`roadrisk.api.deps`.

**Why this package may import `core` when `report` and `store` may not.** Those two are
dict-only by rule, so a run stored months ago re-renders without the engine that made
it. The API is a different job: it reads `factors.yaml` through the registry loader and
it validates a submitted panel through `prepare_panel`, and both of those *are* engine
questions. Answering them with a copy would be the 5.1a defect again.
"""

from __future__ import annotations

from roadrisk.api.app import create_app
from roadrisk.api.deps import StoreProvider, per_request_postgres, shared_store
from roadrisk.api.errors import ApiRefusal, ErrorBody, ErrorCode, Refusal
from roadrisk.api.settings import ApiSettings

__all__ = [
    "ApiRefusal",
    "ApiSettings",
    "ErrorBody",
    "ErrorCode",
    "Refusal",
    "StoreProvider",
    "create_app",
    "per_request_postgres",
    "shared_store",
]
