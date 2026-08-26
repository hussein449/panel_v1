"""An in-memory store. Needs no server, and is not a toy.

The whole test suite runs against this, and the same conformance tests run against
Postgres when a database is available. That is what keeps it a faithful stand-in rather
than a convenient fiction — an in-memory implementation only tested by itself will
diverge, and every divergence is a bug that appears in production and nowhere else.

So it enforces what the database enforces: tenancy on every read, foreign keys that must
resolve, payload validation on the way in, and `NotFound` that does not distinguish
"absent" from "someone else's".
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from roadrisk.store.base import NotFound, PayloadRejected
from roadrisk.store.payload import read_run_columns, storable
from roadrisk.store.records import (
    Artefact,
    Corridor,
    Job,
    JobStatus,
    Project,
    Run,
    Tenant,
)


def _now() -> datetime:
    return datetime.now(UTC)


class MemoryStore:
    """Everything in dictionaries. Lost when the process ends, which is the point."""

    def __init__(self) -> None:
        self._tenants: dict[UUID, Tenant] = {}
        self._projects: dict[UUID, Project] = {}
        self._corridors: dict[UUID, Corridor] = {}
        self._jobs: dict[UUID, Job] = {}
        self._runs: dict[UUID, Run] = {}
        self._artefacts: dict[UUID, Artefact] = {}

    # -- tenants ---------------------------------------------------------------

    def create_tenant(self, tenant: Tenant) -> Tenant:
        stored = tenant.model_copy(update={"created_at": tenant.created_at or _now()})
        self._tenants[stored.id] = stored
        return stored

    def get_tenant(self, tenant_id: UUID) -> Tenant:
        found = self._tenants.get(tenant_id)
        if found is None:
            raise NotFound(f"No tenant {tenant_id}.")
        return found

    # -- projects --------------------------------------------------------------

    def create_project(self, project: Project) -> Project:
        self.get_tenant(project.tenant_id)
        stored = project.model_copy(
            update={"created_at": project.created_at or _now()}
        )
        self._projects[stored.id] = stored
        return stored

    def get_project(self, tenant_id: UUID, project_id: UUID) -> Project:
        found = self._projects.get(project_id)
        if found is None or found.tenant_id != tenant_id:
            raise NotFound(f"No project {project_id}.")
        return found

    def list_projects(self, tenant_id: UUID) -> list[Project]:
        return sorted(
            (p for p in self._projects.values() if p.tenant_id == tenant_id),
            key=_created,
            reverse=True,
        )

    # -- corridors -------------------------------------------------------------

    def create_corridor(self, corridor: Corridor) -> Corridor:
        self.get_project(corridor.tenant_id, corridor.project_id)
        stored = corridor.model_copy(
            update={"created_at": corridor.created_at or _now()}
        )
        self._corridors[stored.id] = stored
        return stored

    def get_corridor(self, tenant_id: UUID, corridor_id: UUID) -> Corridor:
        found = self._corridors.get(corridor_id)
        if found is None or found.tenant_id != tenant_id:
            raise NotFound(f"No corridor {corridor_id}.")
        return found

    def list_corridors(self, tenant_id: UUID, project_id: UUID) -> list[Corridor]:
        return sorted(
            (
                c
                for c in self._corridors.values()
                if c.tenant_id == tenant_id and c.project_id == project_id
            ),
            key=_created,
            reverse=True,
        )

    # -- jobs ------------------------------------------------------------------

    def create_job(self, job: Job) -> Job:
        self.get_project(job.tenant_id, job.project_id)
        if job.corridor_id is not None:
            self.get_corridor(job.tenant_id, job.corridor_id)
        stored = job.model_copy(update={"created_at": job.created_at or _now()})
        self._jobs[stored.id] = stored
        return stored

    def get_job(self, tenant_id: UUID, job_id: UUID) -> Job:
        found = self._jobs.get(job_id)
        if found is None or found.tenant_id != tenant_id:
            raise NotFound(f"No job {job_id}.")
        return found

    def list_jobs(self, tenant_id: UUID, project_id: UUID) -> list[Job]:
        return sorted(
            (
                j
                for j in self._jobs.values()
                if j.tenant_id == tenant_id and j.project_id == project_id
            ),
            key=_created,
            reverse=True,
        )

    def update_job_status(
        self,
        tenant_id: UUID,
        job_id: UUID,
        status: JobStatus,
        *,
        error: str | None = None,
    ) -> Job:
        job = self.get_job(tenant_id, job_id)
        changes: dict[str, Any] = {"status": status, "error": error}
        if status is JobStatus.RUNNING and job.started_at is None:
            changes["started_at"] = _now()
        if status in _TERMINAL:
            changes["finished_at"] = _now()
        stored = job.model_copy(update=changes)
        self._jobs[job_id] = stored
        return stored

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
        self.get_project(tenant_id, project_id)
        if job_id is not None:
            self.get_job(tenant_id, job_id)
        if corridor_id is not None:
            self.get_corridor(tenant_id, corridor_id)

        payload = storable(payload)
        columns = read_run_columns(payload)

        stored = Run(
            tenant_id=tenant_id,
            project_id=project_id,
            job_id=job_id,
            corridor_id=corridor_id,
            payload=payload,
            created_at=_now(),
            **columns,
        )
        self._runs[stored.id] = stored
        return stored

    def get_run(self, tenant_id: UUID, run_id: UUID) -> Run:
        found = self._runs.get(run_id)
        if found is None or found.tenant_id != tenant_id:
            raise NotFound(f"No run {run_id}.")
        return found

    def list_runs(
        self, tenant_id: UUID, project_id: UUID | None = None, *, limit: int = 50
    ) -> list[Run]:
        matching = [
            r
            for r in self._runs.values()
            if r.tenant_id == tenant_id
            and (project_id is None or r.project_id == project_id)
        ]
        return sorted(matching, key=_created, reverse=True)[:limit]

    # -- artefacts -------------------------------------------------------------

    def add_artefact(self, artefact: Artefact) -> Artefact:
        self.get_run(artefact.tenant_id, artefact.run_id)
        stored = artefact.model_copy(
            update={"created_at": artefact.created_at or _now()}
        )
        self._artefacts[stored.id] = stored
        return stored

    def list_artefacts(self, tenant_id: UUID, run_id: UUID) -> list[Artefact]:
        self.get_run(tenant_id, run_id)
        return sorted(
            (
                a
                for a in self._artefacts.values()
                if a.tenant_id == tenant_id and a.run_id == run_id
            ),
            key=_created,
            reverse=True,
        )

    # -- lifecycle -------------------------------------------------------------

    def close(self) -> None:
        return None


_TERMINAL = frozenset(
    {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.REJECTED}
)

#: Rows are ordered newest-first. Records created without a timestamp sort last rather
#: than crashing the comparison.
_EPOCH = datetime.min.replace(tzinfo=UTC)


def _created(record: Any) -> datetime:
    return record.created_at or _EPOCH


__all__ = ["MemoryStore", "NotFound", "PayloadRejected"]
