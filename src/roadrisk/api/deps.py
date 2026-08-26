"""What every route is handed, and the two decisions behind it.

**A store per request, not a store per process.** 5.1b recorded that its one-connection
store was "correct for a CLI and wrong for 5.1c", and it is worth being precise about
why: FastAPI runs synchronous routes in a thread pool, psycopg3 connections are not
safe to share across threads, and a shared one does not fail loudly — it interleaves
two statements and returns the wrong rows to somebody. So the app holds a *provider*
that opens a store for the request and closes it afterwards. A pool goes behind that
provider when connection latency is worth measuring; nothing above it changes.

**The tenant is a required header, and it is not authentication.** 5.4a puts Supabase
identities and row-level policies underneath this. Until then anybody may claim to be
any tenant, and pretending otherwise would be worse than saying it: this is the seam
auth attaches to, not a lock. What it does buy today is that the store's rule survives
the trip over HTTP — every read is still scoped to exactly one tenant, and there is
still no way to ask for all of them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request, status

from roadrisk.api.errors import ApiRefusal, ErrorCode
from roadrisk.api.settings import ApiSettings
from roadrisk.core.registry import Registry
from roadrisk.store import Store

#: How the app gets a store for one request. A context manager, so that "close it
#: afterwards" and "do not close the shared one" are both expressible without the
#: routes having to know which they were given.
StoreProvider = Callable[[], AbstractContextManager[Store]]

#: The header that carries the tenant. Named for this project rather than reusing
#: `Authorization`, so that the day a real credential arrives there is no ambiguity
#: about which one a proxy is looking at.
TENANT_HEADER = "X-Tenant-Id"


def shared_store(store: Store) -> StoreProvider:
    """Hand every request the same store, and never close it.

    Correct for :class:`~roadrisk.store.MemoryStore`, whose state *is* the object, and
    for a test that wants to inspect what the API wrote. Wrong for Postgres — see the
    module docstring.
    """

    @contextmanager
    def provide() -> Iterator[Store]:
        yield store

    return provide


def per_request_postgres(dsn: str) -> StoreProvider:
    """Open a Postgres store for each request and close it when the request ends.

    Migrations are deliberately *not* run here. A web process that migrates on the way
    to answering a request migrates once per worker, concurrently, during a deploy —
    `roadrisk store init` is the one place that happens, run by a person or a release
    step who can read what it did.
    """
    from roadrisk.store.postgres import PostgresStore

    @contextmanager
    def provide() -> Iterator[Store]:
        store = PostgresStore.connect(dsn, migrate_to_latest=False)
        try:
            yield store
        finally:
            store.close()

    return provide


def get_settings(request: Request) -> ApiSettings:
    return request.app.state.settings  # type: ignore[no-any-return]


def get_registry(request: Request) -> Registry:
    """The factor registry, loaded once at startup.

    Once, because `factors.yaml` ships inside the package: it changes when a release
    changes, and re-reading it per request would let a half-written file reach a client.
    """
    return request.app.state.registry  # type: ignore[no-any-return]


def get_store(request: Request) -> Iterator[Store]:
    provider: StoreProvider = request.app.state.store_provider
    with provider() as store:
        yield store


def get_tenant(
    x_tenant_id: Annotated[
        str | None,
        Header(
            alias=TENANT_HEADER,
            description=(
                "Which tenant's rows this request may see. Required on every route "
                "that touches a row. **This is not authentication** — step 5.4a "
                "replaces it with a real identity and row-level policies in the "
                "database. An unknown tenant is not an error: it is a tenant with no "
                "rows, which is what tenancy means."
            ),
        ),
    ] = None,
) -> UUID:
    if not x_tenant_id:
        raise ApiRefusal(
            status.HTTP_401_UNAUTHORIZED,
            ErrorCode.TENANT_REQUIRED,
            f"Every row here belongs to a tenant, so {TENANT_HEADER} is required and "
            "has no default. Create one with `roadrisk store new-tenant`. Note that "
            "this header is a placeholder for the identity step 5.4a introduces; it "
            "scopes rows, it does not prove who you are.",
            field=TENANT_HEADER,
        )
    try:
        return UUID(x_tenant_id)
    except ValueError as exc:
        raise ApiRefusal(
            status.HTTP_400_BAD_REQUEST,
            ErrorCode.TENANT_REQUIRED,
            f"{TENANT_HEADER} must be a UUID, got {x_tenant_id!r}.",
            field=TENANT_HEADER,
        ) from exc


TenantId = Annotated[UUID, Depends(get_tenant)]
StoreDep = Annotated[Store, Depends(get_store)]
SettingsDep = Annotated[ApiSettings, Depends(get_settings)]
RegistryDep = Annotated[Registry, Depends(get_registry)]


__all__ = [
    "TENANT_HEADER",
    "RegistryDep",
    "SettingsDep",
    "StoreDep",
    "StoreProvider",
    "TenantId",
    "get_registry",
    "get_settings",
    "get_store",
    "get_tenant",
    "per_request_postgres",
    "shared_store",
]
