"""The storage interface, and the one thing its shape is designed to prevent.

**Every read takes a tenant, as a required argument.** Not a filter a caller may add,
not a session variable set somewhere earlier — a parameter with no default, on every
method that returns rows. The reason is that the failure mode here is silent and total:
a query missing its tenant filter returns other people's runs and looks perfectly
healthy doing it. Making the tenant impossible to omit turns that from a thing reviewers
must notice into a thing the type checker does.

Step 5.4a will put row-level security underneath this, so the database refuses a
cross-tenant read rather than trusting the query to be well formed. This interface is
what makes that a strengthening rather than a rewrite.

**Two implementations, one test suite.** `MemoryStore` needs nothing and is what the
whole suite runs against; `PostgresStore` is behind the `store` extra. The same
conformance tests run against both, which is the only way the in-memory one stays a
faithful stand-in rather than a convenient fiction.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from roadrisk.store.records import (
    Artefact,
    Corridor,
    Job,
    JobStatus,
    Project,
    Run,
    Tenant,
)


class StoreError(RuntimeError):
    """Base for every error this layer raises."""


class NotFound(StoreError):
    """No such row — for this tenant.

    Deliberately not distinguished from "exists, but belongs to someone else". Telling
    the two apart tells a caller whether an id is real, which is a disclosure in itself:
    it turns a list of guessed identifiers into a census of another tenant's runs.
    """


class PayloadRejected(StoreError):
    """The run payload does not conform to `roadrisk.contract`.

    Raised on the way *in*, never on the way out. A store that accepted a malformed
    payload would hand the problem to whoever read it back — probably months later,
    probably in front of a client — so the boundary is the write.
    """


@runtime_checkable
class Store(Protocol):
    """What every storage backend must do.

    The vocabulary is deliberately small. This is not a general-purpose data layer: it
    holds runs so that they can be listed and re-rendered, and everything it offers
    exists to serve one of those two things.
    """

    # -- tenants ---------------------------------------------------------------

    def create_tenant(self, tenant: Tenant) -> Tenant: ...

    def get_tenant(self, tenant_id: UUID) -> Tenant: ...

    # -- projects --------------------------------------------------------------

    def create_project(self, project: Project) -> Project: ...

    def get_project(self, tenant_id: UUID, project_id: UUID) -> Project: ...

    def list_projects(self, tenant_id: UUID) -> list[Project]: ...

    # -- corridors -------------------------------------------------------------

    def create_corridor(self, corridor: Corridor) -> Corridor: ...

    def get_corridor(self, tenant_id: UUID, corridor_id: UUID) -> Corridor: ...

    def list_corridors(self, tenant_id: UUID, project_id: UUID) -> list[Corridor]: ...

    # -- jobs ------------------------------------------------------------------

    def create_job(self, job: Job) -> Job: ...

    def get_job(self, tenant_id: UUID, job_id: UUID) -> Job: ...

    def list_jobs(self, tenant_id: UUID, project_id: UUID) -> list[Job]: ...

    def update_job_status(
        self,
        tenant_id: UUID,
        job_id: UUID,
        status: JobStatus,
        *,
        error: str | None = None,
    ) -> Job:
        """Move a job along. `error` is a cause, never a traceback."""
        ...

    # -- runs ------------------------------------------------------------------

    def store_run(
        self,
        tenant_id: UUID,
        project_id: UUID,
        payload: dict[str, Any],
        *,
        job_id: UUID | None = None,
        corridor_id: UUID | None = None,
    ) -> Run:
        """Validate a payload against the contract and keep it.

        The indexed columns — mode, rung, fingerprint, engine and schema version — are
        read *out of the payload* here rather than passed in, so there is no way for
        them to describe a different run than the one being stored.

        Raises:
            PayloadRejected: The payload does not conform to `roadrisk.contract`.
        """
        ...

    def get_run(self, tenant_id: UUID, run_id: UUID) -> Run: ...

    def list_runs(
        self, tenant_id: UUID, project_id: UUID | None = None, *, limit: int = 50
    ) -> list[Run]:
        """Newest first. Returns rows with their payloads; see the note in the module."""
        ...

    # -- artefacts -------------------------------------------------------------

    def add_artefact(self, artefact: Artefact) -> Artefact: ...

    def list_artefacts(self, tenant_id: UUID, run_id: UUID) -> list[Artefact]: ...

    # -- lifecycle -------------------------------------------------------------

    def close(self) -> None: ...
