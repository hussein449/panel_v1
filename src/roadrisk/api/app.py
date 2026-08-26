"""The application, assembled.

A factory rather than a module-level `app`, for one practical reason and one structural
one. Practically, the test suite needs an app over a `MemoryStore` and a deployment
needs one over Postgres, and a module-level object would have to read the environment at
import time to know which — so importing the module would open a database connection.
Structurally, the store provider is the seam 5.2a swaps and 5.4a puts identities behind;
a factory makes that an argument rather than a monkey-patch.
"""

from __future__ import annotations

import os

from fastapi import FastAPI

from roadrisk import __version__
from roadrisk.api import errors
from roadrisk.api.deps import StoreProvider, per_request_postgres, shared_store
from roadrisk.api.routes import ROUTERS
from roadrisk.api.settings import ApiSettings
from roadrisk.contract import SCHEMA_VERSION
from roadrisk.core.registry import Registry, load_registry
from roadrisk.store import MemoryStore
from roadrisk.store.postgres import DSN_ENV

#: Shown at the top of the generated documentation. Every sentence in it is something a
#: client would otherwise have to discover by watching a job never finish or by
#: assuming a header is a credential. Step 5.3b makes the same two facts a layout
#: element on every screen; this is the API's version of that banner.
DESCRIPTION = f"""
Corridor road-risk assessment from open data, with provenance.

**Two things this deployment does not yet do, stated here rather than discovered.**

* **Nothing executes jobs.** `POST /jobs` stores a job and returns `202`. It stays
  `queued` until step 5.1d attaches a runner. `GET /health` reports `runner: null`.
* **`X-Tenant-Id` is not authentication.** It scopes every read to one tenant, which is
  what keeps two clients' runs apart, but nothing verifies the claim. Step 5.4a
  replaces it with real identities and row-level policies in the database.

**A refusal is a result, not an error.** A panel that breaks the input contract is a
`422` naming the column, and no job is created. An assessment that descended to Mode B,
dropped a term or declined to score an unsourced weight is a **`200`** — those are
findings the run carries, not failures. Infrastructure breaking is a job whose status is
`failed`, with a cause.

Payload shape version `{SCHEMA_VERSION}`. Factors, tiers and licences come from
`factors.yaml`; `GET /registry` serves it with the hash of the file it was read from.
"""


def create_app(
    *,
    store_provider: StoreProvider | None = None,
    settings: ApiSettings | None = None,
    registry: Registry | None = None,
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

    errors.install(app)
    for router in ROUTERS:
        app.include_router(router)
    return app


def _default_provider() -> StoreProvider:
    dsn = os.environ.get(DSN_ENV)
    return per_request_postgres(dsn) if dsn else shared_store(MemoryStore())


__all__ = ["DESCRIPTION", "create_app"]
