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

from datetime import datetime
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


class InUse(StoreError):
    """The delete would have taken other rows with it, so it is refused.

    Migration 0001 declares ``ON DELETE CASCADE`` from project down through corridor,
    job and run. That is right for dropping a *tenant* and exactly wrong for one
    careless request: a single ``DELETE FROM project`` destroys every stored assessment
    filed under it, and a stored run is a client deliverable.

    So deleting is guarded here rather than left to the schema, in both backends, so
    that no caller can reach past it. There is no force flag — emptying a project means
    deleting what is in it, deliberately. The message names what is still there,
    because "cannot delete" is not something anybody can act on.
    """


#: The give-up message, in two halves with the attempt count between them.
#:
#: Split rather than formatted, because Postgres builds it per row inside one `UPDATE`
#: — ``%s || attempts::text || %s`` — while the memory store formats it in Python. One
#: wording, two ways of assembling it, and the conformance suite asserts they agree.
#: Writing the sentence twice is how they would stop agreeing.
GIVE_UP_PREFIX = "Started "
GIVE_UP_SUFFIX = (
    " time(s) and never finished — the process running it stopped each time. Not "
    "started again, in case running it is what stops the process. Submit it again to "
    "try once more."
)


def give_up_reason(attempts: int) -> str:
    """What a job says when reclaiming has stopped trying to rescue it.

    Shared by both backends for the same reason :func:`refuse_if_held` is: the
    conformance suite asserts on the wording, and a caller who has learned to read one
    refusal must not meet a different sentence from the other backend.
    """
    return f"{GIVE_UP_PREFIX}{attempts}{GIVE_UP_SUFFIX}"


def refuse_if_held(what: str, held: dict[str, int]) -> None:
    """Raise :class:`InUse` naming exactly what is still there, or return.

    Shared by both backends rather than written twice, for the same reason
    :func:`roadrisk.store.payload.read_run_columns` is: two implementations of one rule
    are two chances to word it differently, and the conformance suite asserts on the
    message. A caller who has learned to read one refusal must not meet a different one
    from the other backend.

    Args:
        what: The row being deleted, already worded — "Project <id>".
        held: Child noun to count. Zeroes are ignored; anything else refuses.
    """
    remaining = [
        f"{count} {noun}{'s' if count != 1 else ''}"
        for noun, count in held.items()
        if count
    ]
    if not remaining:
        return
    raise InUse(
        f"{what} still holds {', '.join(remaining)}. Deleting it would take them with "
        "it, and a stored run is a deliverable — delete what it holds first."
    )


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

    def update_project(self, tenant_id: UUID, project: Project) -> Project:
        """Replace the editable fields of a project with the record supplied.

        A whole record rather than a bag of optional arguments, so that "set the spend
        cap to null" and "leave the spend cap alone" are not the same call. Partial
        edits are the caller's business — an HTTP `PATCH` reads the row, applies the
        fields the client actually sent, and hands the result back here.

        `id` and `tenant_id` identify the row and are never changed by it: moving a
        project between tenants is not an edit, it is a different operation nobody has
        asked for.

        Raises:
            NotFound: No such project for this tenant.
        """
        ...

    def delete_project(self, tenant_id: UUID, project_id: UUID) -> None:
        """Delete a project that holds nothing.

        Raises:
            NotFound: No such project for this tenant.
            InUse: It still holds corridors, jobs or runs. See :class:`InUse` — the
                schema would cascade, and a run is a deliverable.
        """
        ...

    # -- corridors -------------------------------------------------------------

    def create_corridor(self, corridor: Corridor) -> Corridor: ...

    def get_corridor(self, tenant_id: UUID, corridor_id: UUID) -> Corridor: ...

    def list_corridors(self, tenant_id: UUID, project_id: UUID) -> list[Corridor]: ...

    def update_corridor(self, tenant_id: UUID, corridor: Corridor) -> Corridor:
        """Replace the editable fields of a corridor. See :meth:`update_project`.

        `project_id` is editable in principle and is not editable here: a corridor that
        changed project would take its runs' filing with it and leave every listing
        that had already been drawn wrong.

        Raises:
            NotFound: No such corridor for this tenant.
        """
        ...

    def delete_corridor(self, tenant_id: UUID, corridor_id: UUID) -> None:
        """Delete a corridor that nothing references.

        The schema is more forgiving here than for a project — `job.corridor_id` and
        `run.corridor_id` are `ON DELETE SET NULL`, so nothing is destroyed. What is
        destroyed is the *link*: a run would keep its geometry inside the payload and
        lose the road it was filed against, silently. That is refused too.

        Raises:
            NotFound: No such corridor for this tenant.
            InUse: A job or a run still points at it.
        """
        ...

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
        """Move a job along. `error` is a cause, never a traceback.

        Moving a job to `running` counts an attempt, because that is the moment the
        thing that might not survive begins.
        """
        ...

    def reclaim_running_jobs(
        self,
        *,
        started_before: datetime | None = None,
        max_attempts: int = 3,
    ) -> list[Job]:
        """Take back jobs left `running` by a process that is gone.

        **The one read here that is not scoped to a tenant, and it is deliberate.**
        Every other method takes a tenant with no default, because a query that forgets
        the filter returns somebody else's rows and looks healthy doing it. This one is
        an *operator* action — a process is starting, and a process does not belong to a
        tenant — so pretending it could be tenant-scoped would mean asking a caller to
        supply an identity that has nothing to do with what is being done. It is named
        so that reading it says as much.

        A job under the attempt limit goes back to `queued`; one at or over it is
        `failed`, with a cause naming the attempts. See `Job.attempts` for why the
        second case has to exist.

        Args:
            started_before: Only reclaim jobs that started before this. `None` means all
                of them, which is correct for a single-process deployment where anything
                still `running` at startup is by definition nobody's. Set it above your
                longest job if more than one process shares this database, or a starting
                process will reclaim a job another one is still working on.
            max_attempts: Past this many starts, a job is failed instead of requeued.

        Returns:
            The jobs that were changed, with their new status.
        """
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

    def find_run_for_job(self, tenant_id: UUID, job_id: UUID) -> Run | None:
        """The run a job produced, or None if it has not produced one.

        The reference points from run to job rather than the other way round — a job
        exists before its run does, so the column has to live on the row created second.
        That makes "what did this job produce" a lookup rather than a field, which is
        what this is.

        None rather than :class:`NotFound`, because a queued job legitimately has no
        run and that is not an error. `NotFound` is still raised for a job that is not
        this tenant's, so the disclosure rule holds.
        """
        ...

    # -- artefacts -------------------------------------------------------------

    def add_artefact(self, artefact: Artefact) -> Artefact: ...

    def list_artefacts(self, tenant_id: UUID, run_id: UUID) -> list[Artefact]: ...

    # -- lifecycle -------------------------------------------------------------

    def close(self) -> None: ...
