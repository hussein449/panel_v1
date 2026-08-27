"""Postgres, behind the `store` extra.

Plain SQL over psycopg3, no ORM. The data model is six tables of scalars around a
`jsonb` payload; an object-relational mapper over that would be indirection paid for
with nothing, and it would put a translation layer between the schema people review and
the queries that actually run.

**Every statement filters on `tenant_id` in its own `WHERE`.** Not through a join, not
through a session variable — a literal predicate on the table being read. That is what
step 5.4a's row-level policies will make redundant, and until they exist it is the only
thing standing between two tenants. A query here without a tenant predicate is a defect
whether or not it returns the right rows today.
"""

from __future__ import annotations

import json
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from roadrisk.store.base import (
    GIVE_UP_PREFIX,
    GIVE_UP_SUFFIX,
    BBox,
    NotFound,
    refuse_if_held,
)
from roadrisk.store.migrate import migrate
from roadrisk.store.payload import read_run_columns, storable
from roadrisk.store.records import (
    Artefact,
    ArtefactKind,
    Corridor,
    Job,
    JobStatus,
    Project,
    Run,
    Tenant,
)

#: Read from the environment by :meth:`PostgresStore.from_env`. Named for this project
#: rather than the generic `DATABASE_URL`, so that pointing a shell at some other
#: application's database cannot silently make this one write into it.
DSN_ENV = "ROADRISK_DATABASE_URL"


class PostgresStore:
    """Runs that outlive the process that made them."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    # -- construction ----------------------------------------------------------

    @classmethod
    def connect(cls, dsn: str, *, migrate_to_latest: bool = True) -> PostgresStore:
        """Open a connection, optionally bringing the schema up to date."""
        import psycopg

        connection = psycopg.connect(dsn)
        store = cls(connection)
        if migrate_to_latest:
            store.migrate()
        return store

    @classmethod
    def from_env(cls, **kwargs: Any) -> PostgresStore:
        """Connect using ``$ROADRISK_DATABASE_URL``."""
        import os

        dsn = os.environ.get(DSN_ENV)
        if not dsn:
            raise RuntimeError(
                f"{DSN_ENV} is not set. It should be a Postgres connection string, for "
                "example postgresql:///roadrisk for a local socket."
            )
        return cls.connect(dsn, **kwargs)

    def migrate(self, directory: Path | None = None) -> list[str]:
        return migrate(self._connection, directory)

    # -- tenants ---------------------------------------------------------------

    def create_tenant(self, tenant: Tenant) -> Tenant:
        row = self._one(
            "INSERT INTO tenant (id, name) VALUES (%s, %s) RETURNING id, name, created_at",
            (tenant.id, tenant.name),
        )
        return Tenant(id=row[0], name=row[1], created_at=row[2])

    def get_tenant(self, tenant_id: UUID) -> Tenant:
        row = self._maybe(
            "SELECT id, name, created_at FROM tenant WHERE id = %s", (tenant_id,)
        )
        if row is None:
            raise NotFound(f"No tenant {tenant_id}.")
        return Tenant(id=row[0], name=row[1], created_at=row[2])

    # -- projects --------------------------------------------------------------

    _PROJECT_COLUMNS = "id, tenant_id, name, spend_cap, created_at"

    def create_project(self, project: Project) -> Project:
        row = self._one(
            "INSERT INTO project (id, tenant_id, name, spend_cap) "
            f"VALUES (%s, %s, %s, %s) RETURNING {self._PROJECT_COLUMNS}",
            (project.id, project.tenant_id, project.name, project.spend_cap),
        )
        return _project(row)

    def get_project(self, tenant_id: UUID, project_id: UUID) -> Project:
        row = self._maybe(
            f"SELECT {self._PROJECT_COLUMNS} FROM project "
            "WHERE tenant_id = %s AND id = %s",
            (tenant_id, project_id),
        )
        if row is None:
            raise NotFound(f"No project {project_id}.")
        return _project(row)

    def list_projects(self, tenant_id: UUID) -> list[Project]:
        rows = self._all(
            f"SELECT {self._PROJECT_COLUMNS} FROM project "
            "WHERE tenant_id = %s ORDER BY created_at DESC",
            (tenant_id,),
        )
        return [_project(row) for row in rows]

    def update_project(self, tenant_id: UUID, project: Project) -> Project:
        # Read first, then write with `_one`. `_maybe` does not commit — it is the read
        # helper — and an UPDATE ... RETURNING run through it would look like it
        # worked, be visible to this connection, and vanish on close.
        self.get_project(tenant_id, project.id)
        row = self._one(
            "UPDATE project SET name = %s, spend_cap = %s "
            f"WHERE tenant_id = %s AND id = %s RETURNING {self._PROJECT_COLUMNS}",
            (project.name, project.spend_cap, tenant_id, project.id),
        )
        return _project(row)

    def delete_project(self, tenant_id: UUID, project_id: UUID) -> None:
        self.get_project(tenant_id, project_id)
        refuse_if_held(
            f"Project {project_id}",
            {
                noun: self._count(
                    f"SELECT count(*) FROM {noun} WHERE tenant_id = %s AND project_id = %s",
                    (tenant_id, project_id),
                )
                for noun in ("corridor", "job", "run")
            },
        )
        self._one(
            "DELETE FROM project WHERE tenant_id = %s AND id = %s RETURNING id",
            (tenant_id, project_id),
        )

    # -- corridors -------------------------------------------------------------

    _CORRIDOR_COLUMNS = (
        "id, tenant_id, project_id, name, ref, "
        "bbox_south, bbox_west, bbox_north, bbox_east, unit_length_m, created_at"
    )

    def create_corridor(self, corridor: Corridor) -> Corridor:
        box = corridor.bbox or (None, None, None, None)
        row = self._one(
            "INSERT INTO corridor (id, tenant_id, project_id, name, ref, "
            "bbox_south, bbox_west, bbox_north, bbox_east, unit_length_m) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            f"RETURNING {self._CORRIDOR_COLUMNS}",
            (
                corridor.id,
                corridor.tenant_id,
                corridor.project_id,
                corridor.name,
                corridor.ref,
                *box,
                corridor.unit_length_m,
            ),
        )
        return _corridor(row)

    def get_corridor(self, tenant_id: UUID, corridor_id: UUID) -> Corridor:
        row = self._maybe(
            f"SELECT {self._CORRIDOR_COLUMNS} FROM corridor "
            "WHERE tenant_id = %s AND id = %s",
            (tenant_id, corridor_id),
        )
        if row is None:
            raise NotFound(f"No corridor {corridor_id}.")
        return _corridor(row)

    def list_corridors(self, tenant_id: UUID, project_id: UUID) -> list[Corridor]:
        rows = self._all(
            f"SELECT {self._CORRIDOR_COLUMNS} FROM corridor "
            "WHERE tenant_id = %s AND project_id = %s ORDER BY created_at DESC",
            (tenant_id, project_id),
        )
        return [_corridor(row) for row in rows]

    def update_corridor(self, tenant_id: UUID, corridor: Corridor) -> Corridor:
        self.get_corridor(tenant_id, corridor.id)
        box = corridor.bbox or (None, None, None, None)
        row = self._one(
            "UPDATE corridor SET name = %s, ref = %s, bbox_south = %s, bbox_west = %s, "
            "bbox_north = %s, bbox_east = %s, unit_length_m = %s "
            f"WHERE tenant_id = %s AND id = %s RETURNING {self._CORRIDOR_COLUMNS}",
            (
                corridor.name,
                corridor.ref,
                *box,
                corridor.unit_length_m,
                tenant_id,
                corridor.id,
            ),
        )
        return _corridor(row)

    def delete_corridor(self, tenant_id: UUID, corridor_id: UUID) -> None:
        self.get_corridor(tenant_id, corridor_id)
        refuse_if_held(
            f"Corridor {corridor_id}",
            {
                noun: self._count(
                    f"SELECT count(*) FROM {noun} WHERE tenant_id = %s AND corridor_id = %s",
                    (tenant_id, corridor_id),
                )
                for noun in ("job", "run")
            },
        )
        self._one(
            "DELETE FROM corridor WHERE tenant_id = %s AND id = %s RETURNING id",
            (tenant_id, corridor_id),
        )

    # -- jobs ------------------------------------------------------------------

    _JOB_COLUMNS = (
        "id, tenant_id, project_id, corridor_id, status, params, attempts, error, "
        "created_at, started_at, finished_at"
    )

    def create_job(self, job: Job) -> Job:
        row = self._one(
            "INSERT INTO job (id, tenant_id, project_id, corridor_id, status, params) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            f"RETURNING {self._JOB_COLUMNS}",
            (
                job.id,
                job.tenant_id,
                job.project_id,
                job.corridor_id,
                job.status.value,
                json.dumps(job.params),
            ),
        )
        return _job(row)

    def get_job(self, tenant_id: UUID, job_id: UUID) -> Job:
        row = self._maybe(
            f"SELECT {self._JOB_COLUMNS} FROM job WHERE tenant_id = %s AND id = %s",
            (tenant_id, job_id),
        )
        if row is None:
            raise NotFound(f"No job {job_id}.")
        return _job(row)

    def list_jobs(self, tenant_id: UUID, project_id: UUID) -> list[Job]:
        rows = self._all(
            f"SELECT {self._JOB_COLUMNS} FROM job "
            "WHERE tenant_id = %s AND project_id = %s ORDER BY created_at DESC",
            (tenant_id, project_id),
        )
        return [_job(row) for row in rows]

    def update_job_status(
        self,
        tenant_id: UUID,
        job_id: UUID,
        status: JobStatus,
        *,
        error: str | None = None,
    ) -> Job:
        row = self._maybe(
            "UPDATE job SET status = %s, error = %s, "
            # An attempt is counted at the moment the thing that might not survive
            # begins, not when it ends — the whole point is to number the starts that
            # never reached an end.
            "attempts = CASE WHEN %s = 'running' THEN attempts + 1 ELSE attempts END, "
            "started_at = CASE WHEN %s = 'running' AND started_at IS NULL "
            "                  THEN now() ELSE started_at END, "
            "finished_at = CASE WHEN %s IN ('succeeded', 'failed', 'rejected') "
            "                   THEN now() ELSE finished_at END "
            f"WHERE tenant_id = %s AND id = %s RETURNING {self._JOB_COLUMNS}",
            (
                status.value,
                error,
                status.value,
                status.value,
                status.value,
                tenant_id,
                job_id,
            ),
        )
        if row is None:
            raise NotFound(f"No job {job_id}.")
        self._connection.commit()
        return _job(row)

    def reclaim_running_jobs(
        self,
        *,
        started_before: datetime | None = None,
        max_attempts: int = 3,
    ) -> list[Job]:
        # No tenant predicate, and it is the only query in this file without one. See
        # the interface: a process starting up does not belong to a tenant, and asking
        # a caller for an identity that has nothing to do with the operation would make
        # the rule harder to read rather than easier to keep.
        #
        # One statement rather than a select and a loop of updates, so that two
        # processes starting at the same moment cannot both reclaim the same row and
        # both count it.
        rows = self._all(
            "UPDATE job SET "
            "  status = CASE WHEN attempts < %s THEN 'queued' ELSE 'failed' END, "
            # Built per row from this row's own attempts, so the sentence reports what
            # actually happened to *this* job rather than the limit it hit.
            "  error = CASE WHEN attempts < %s THEN NULL "
            "                ELSE %s || attempts::text || %s END, "
            "  finished_at = CASE WHEN attempts < %s THEN NULL ELSE now() END "
            "WHERE status = 'running' "
            "  AND (%s::timestamptz IS NULL OR started_at < %s::timestamptz) "
            f"RETURNING {self._JOB_COLUMNS}",
            (
                max_attempts,
                max_attempts,
                GIVE_UP_PREFIX,
                GIVE_UP_SUFFIX,
                max_attempts,
                started_before,
                started_before,
            ),
        )
        self._connection.commit()
        return [_job(row) for row in rows]

    # -- runs ------------------------------------------------------------------

    _RUN_COLUMNS = (
        "id, tenant_id, project_id, job_id, corridor_id, schema_version, "
        "engine_version, fingerprint, mode, rung, payload, created_at, "
        "extent_west, extent_south, extent_east, extent_north"
    )

    #: Two boxes overlap when neither is wholly to one side of the other. Written out
    #: rather than reached for a geometry type: see `migrations/0003_run_extent.sql` for
    #: why PostGIS is not what answers this.
    _OVERLAPS = (
        "extent_west IS NOT NULL AND extent_west <= %s AND extent_east >= %s "
        "AND extent_south <= %s AND extent_north >= %s"
    )

    def store_run(
        self,
        tenant_id: UUID,
        project_id: UUID,
        payload: dict[str, Any],
        *,
        job_id: UUID | None = None,
        corridor_id: UUID | None = None,
    ) -> Run:
        payload = storable(payload)
        columns = read_run_columns(payload)
        record = Run(
            tenant_id=tenant_id,
            project_id=project_id,
            job_id=job_id,
            corridor_id=corridor_id,
            payload=payload,
            **columns,
        )
        row = self._one(
            "INSERT INTO run (id, tenant_id, project_id, job_id, corridor_id, "
            "schema_version, engine_version, fingerprint, mode, rung, payload, "
            "extent_west, extent_south, extent_east, extent_north) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            f"RETURNING {self._RUN_COLUMNS}",
            (
                record.id,
                record.tenant_id,
                record.project_id,
                record.job_id,
                record.corridor_id,
                record.schema_version,
                record.engine_version,
                record.fingerprint,
                record.mode,
                record.rung,
                json.dumps(record.payload),
                record.extent_west,
                record.extent_south,
                record.extent_east,
                record.extent_north,
            ),
        )
        return _run(row)

    def get_run(self, tenant_id: UUID, run_id: UUID) -> Run:
        row = self._maybe(
            f"SELECT {self._RUN_COLUMNS} FROM run WHERE tenant_id = %s AND id = %s",
            (tenant_id, run_id),
        )
        if row is None:
            raise NotFound(f"No run {run_id}.")
        return _run(row)

    def list_runs(
        self,
        tenant_id: UUID,
        project_id: UUID | None = None,
        *,
        limit: int = 50,
        within: BBox | None = None,
    ) -> list[Run]:
        where = ["tenant_id = %s"]
        values: list[Any] = [tenant_id]

        if project_id is not None:
            where.append("project_id = %s")
            values.append(project_id)

        if within is not None:
            south, west, north, east = within
            where.append(f"({self._OVERLAPS})")
            values.extend([east, west, north, south])

        values.append(limit)
        rows = self._all(
            f"SELECT {self._RUN_COLUMNS} FROM run WHERE {' AND '.join(where)} "
            "ORDER BY created_at DESC LIMIT %s",
            tuple(values),
        )
        return [_run(row) for row in rows]

    def find_run_for_job(self, tenant_id: UUID, job_id: UUID) -> Run | None:
        # `get_job` first, so a job belonging to another tenant raises NotFound rather
        # than returning None. None has to mean "this job has produced nothing yet";
        # letting it also mean "not yours" would tell a caller that a guessed id is not
        # real, which is the disclosure `NotFound` exists to prevent.
        self.get_job(tenant_id, job_id)
        row = self._maybe(
            f"SELECT {self._RUN_COLUMNS} FROM run WHERE tenant_id = %s AND job_id = %s "
            "ORDER BY created_at DESC LIMIT 1",
            (tenant_id, job_id),
        )
        return _run(row) if row is not None else None

    # -- artefacts -------------------------------------------------------------

    _ARTEFACT_COLUMNS = (
        "id, tenant_id, run_id, kind, uri, size_bytes, sha256, created_at"
    )

    def add_artefact(self, artefact: Artefact) -> Artefact:
        row = self._one(
            "INSERT INTO artefact (id, tenant_id, run_id, kind, uri, size_bytes, sha256) "
            f"VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING {self._ARTEFACT_COLUMNS}",
            (
                artefact.id,
                artefact.tenant_id,
                artefact.run_id,
                artefact.kind.value,
                artefact.uri,
                artefact.size_bytes,
                artefact.sha256,
            ),
        )
        return _artefact(row)

    def list_artefacts(self, tenant_id: UUID, run_id: UUID) -> list[Artefact]:
        self.get_run(tenant_id, run_id)
        rows = self._all(
            f"SELECT {self._ARTEFACT_COLUMNS} FROM artefact "
            "WHERE tenant_id = %s AND run_id = %s ORDER BY created_at DESC",
            (tenant_id, run_id),
        )
        return [_artefact(row) for row in rows]

    # -- lifecycle -------------------------------------------------------------

    def close(self) -> None:
        self._connection.close()

    # -- plumbing --------------------------------------------------------------
    #
    # Every one of these rolls back before re-raising. Postgres puts a connection into
    # a failed transaction after any error and refuses everything until it is ended, so
    # without this one rejected insert — a constraint doing exactly its job — would
    # leave the store unusable for every later call. The failure a caller then sees is
    # "current transaction is aborted", which names neither the operation that failed
    # nor the one that was refused because of it.
    #
    # A rejected write is a normal outcome here, not an exceptional one: the composite
    # tenant keys exist precisely so that some inserts get refused.

    def _rollback(self) -> None:
        # Suppressed because this runs while another exception is on its way up, and
        # that one is the useful error. A connection too broken to roll back cannot be
        # rescued here, and masking the original failure with the rescue's failure
        # would lose the only message a caller can act on.
        with suppress(Exception):  # pragma: no cover - only if the socket is gone
            self._connection.rollback()

    def _one(self, sql: str, params: tuple[Any, ...]) -> tuple[Any, ...]:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(sql, params)
                row = cursor.fetchone()
            self._connection.commit()
        except Exception:
            self._rollback()
            raise
        assert row is not None
        return row

    def _maybe(self, sql: str, params: tuple[Any, ...]) -> tuple[Any, ...] | None:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.fetchone()
        except Exception:
            self._rollback()
            raise

    def _all(self, sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(sql, params)
                return list(cursor.fetchall())
        except Exception:
            self._rollback()
            raise

    def _count(self, sql: str, params: tuple[Any, ...]) -> int:
        row = self._maybe(sql, params)
        return int(row[0]) if row else 0


# -- row mapping ---------------------------------------------------------------
#
# Written out rather than done by dictionary, so that a column added to the schema and
# not to the record — or the reverse — is a failure here and not a silently absent field.


def _project(row: tuple[Any, ...]) -> Project:
    return Project(
        id=row[0], tenant_id=row[1], name=row[2], spend_cap=row[3], created_at=row[4]
    )


def _corridor(row: tuple[Any, ...]) -> Corridor:
    box = row[5:9]
    return Corridor(
        id=row[0],
        tenant_id=row[1],
        project_id=row[2],
        name=row[3],
        ref=row[4],
        bbox=None if box[0] is None else (box[0], box[1], box[2], box[3]),
        unit_length_m=row[9],
        created_at=row[10],
    )


def _job(row: tuple[Any, ...]) -> Job:
    return Job(
        id=row[0],
        tenant_id=row[1],
        project_id=row[2],
        corridor_id=row[3],
        status=JobStatus(row[4]),
        params=row[5] or {},
        attempts=row[6],
        error=row[7],
        created_at=row[8],
        started_at=row[9],
        finished_at=row[10],
    )


def _run(row: tuple[Any, ...]) -> Run:
    return Run(
        id=row[0],
        tenant_id=row[1],
        project_id=row[2],
        job_id=row[3],
        corridor_id=row[4],
        schema_version=row[5],
        engine_version=row[6],
        fingerprint=row[7],
        mode=row[8],
        rung=row[9],
        payload=row[10],
        created_at=row[11],
        extent_west=row[12],
        extent_south=row[13],
        extent_east=row[14],
        extent_north=row[15],
    )


def _artefact(row: tuple[Any, ...]) -> Artefact:
    return Artefact(
        id=row[0],
        tenant_id=row[1],
        run_id=row[2],
        kind=ArtefactKind(row[3]),
        uri=row[4],
        size_bytes=row[5],
        sha256=row[6],
        created_at=row[7],
    )


_ = datetime  # re-exported for the type annotations above
