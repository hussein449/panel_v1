"""Step 5.1b — where runs live when the process that made them has gone.

A run has been a directory of files since Stage 2, and for a single-user CLI that is the
right answer: nothing needs a database, and adding one would have put a service
dependency into a package whose whole shape is *runs with no network and no API key*.
Step 2.9 recorded that deferral and said persistence lands with 5.1, against real
requirements. These are those requirements.

**What it stores, and what it deliberately does not.** The payload goes in whole, as
`jsonb`, validated against `roadrisk.contract` on the way in — a store that accepted a
malformed run would hand the problem to whoever read it back, months later, probably in
front of a client. Artefacts go in *by reference*: a report is a third of a megabyte, a
PDF more, both are regenerable from the payload, and a database is the wrong place for
them.

**Tenancy is in the first migration, not bolted on at 5.4.** "Two tenants cannot see each
other's runs" is a property of storage rather than of authentication — auth is who you
are, tenancy is which rows exist at all. Every table carries `tenant_id`, every read
takes one as a required argument, and 5.4a's row-level policies will attach to the
column that is already there rather than to one added underneath a year of queries.

**Two implementations, one conformance suite.** :class:`MemoryStore` needs nothing and is
what the test suite runs against; :class:`PostgresStore` is behind the ``store`` extra.
The same tests run against both, because an in-memory stand-in tested only by itself
drifts, and every drift is a defect that appears in production and nowhere else.

This package imports `roadrisk.contract` and nothing else in `roadrisk`. It holds no
engine object and cannot fit a model.
"""

from __future__ import annotations

from roadrisk.store.base import (
    InUse,
    NotFound,
    PayloadRejected,
    Store,
    StoreError,
    give_up_reason,
    refuse_if_held,
)
from roadrisk.store.memory import MemoryStore
from roadrisk.store.migrate import (
    MIGRATIONS,
    Migration,
    MigrationMismatch,
    discover,
    migrate,
)
from roadrisk.store.payload import read_run_columns
from roadrisk.store.records import (
    Artefact,
    ArtefactKind,
    Corridor,
    Job,
    JobStatus,
    Project,
    Record,
    Run,
    Tenant,
)

__all__ = [
    "MIGRATIONS",
    "Artefact",
    "ArtefactKind",
    "Corridor",
    "InUse",
    "Job",
    "JobStatus",
    "MemoryStore",
    "Migration",
    "MigrationMismatch",
    "NotFound",
    "PayloadRejected",
    "Project",
    "Record",
    "Run",
    "Store",
    "StoreError",
    "Tenant",
    "discover",
    "give_up_reason",
    "migrate",
    "read_run_columns",
    "refuse_if_held",
]


def postgres_store(dsn: str, **kwargs: object) -> Store:
    """Open a Postgres-backed store.

    Imported lazily so that `roadrisk.store` stays usable — and importable — without
    psycopg installed. The memory backend is the default for a reason; needing a
    database to read the module that says a database is optional would be its own joke.
    """
    from roadrisk.store.postgres import PostgresStore

    return PostgresStore.connect(dsn, **kwargs)  # type: ignore[arg-type]
