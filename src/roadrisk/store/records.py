"""What is stored, as types.

These are rows, not payloads. The distinction matters: `roadrisk.contract` describes the
JSON a run *is*, and this describes the handful of columns the database needs to find it
again. A run's payload is stored whole and opaque; everything here exists so that a query
never has to open it.

**`tenant_id` is on every record, including the ones where it looks redundant.** A
corridor already belongs to a project and a project already belongs to a tenant, so the
column could be derived by joining. Deriving it means every query that forgets the join
returns another tenant's rows, and the failure is silent and total. Carrying it means the
filter is one column on the table being read, and 5.4a's row-level policies have
something local to attach to.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class Record(BaseModel):
    """A stored row. Frozen, because a row read back is a record of what happened."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class JobStatus(StrEnum):
    """Where a job is, and nothing about what it concluded.

    The distinction this vocabulary exists to protect: **a job that descended to Mode B
    succeeded.** Refusing Mode A, dropping a term, declining to score an unsourced
    weight — those are findings the run carries, not failures of the job. `failed` is
    reserved for the machinery breaking: Overpass returning 429, a missing token, a
    worker dying. Collapsing the two would put the engine's honesty into an error log
    where nobody reads it.
    """

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    #: The panel broke the input contract, so there was nothing to assess. Distinct from
    #: `failed` because nothing malfunctioned — the job was refused, and the receipt
    #: naming the offending column is the whole result.
    REJECTED = "rejected"


class ArtefactKind(StrEnum):
    """What a stored file is. The bytes never enter the database."""

    REPORT_HTML = "report.html"
    REPORT_PDF = "report.pdf"
    RUN_JSON = "run.json"
    RANKING_CSV = "ranking.csv"


class Tenant(Record):
    """Who owns rows. One per customer; a single local user is a tenant of one."""

    id: UUID = Field(default_factory=uuid4)
    name: str
    created_at: datetime | None = None


class Project(Record):
    """A body of work — usually one road authority's network, or one study."""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    name: str
    #: Per-project spend cap in whole currency units, enforced by 5.2b's runner before
    #: the call that would breach it. Null means uncapped, which is a deliberate choice
    #: rather than a default — the column exists here so the cap has somewhere to live
    #: before the accounting that reads it does.
    spend_cap: float | None = None
    created_at: datetime | None = None


class Corridor(Record):
    """A road, as the parameters needed to fetch and segment it again.

    Deliberately *not* the resolved geometry. Geometry belongs to a run, because the
    OSM extract behind it changes: two runs of the same corridor a month apart are two
    different centrelines and must not be conflated. What is stable is the request —
    this reference, this bounding box, this unit length.
    """

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    project_id: UUID
    name: str
    #: Road reference as OSM knows it, e.g. "B9". Null for a client-supplied centreline.
    ref: str | None = None
    #: south, west, north, east in degrees.
    bbox: tuple[float, float, float, float] | None = None
    unit_length_m: float = 500.0
    created_at: datetime | None = None


class Job(Record):
    """One request to assess a corridor, and where it got to.

    `params` is the assessment's own options — estimator, priors, spatial, which
    adapters to run. Stored as given so that a job can be re-run identically, and so
    that the manifest's fingerprint has something to be checked against.
    """

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    project_id: UUID
    corridor_id: UUID | None = None
    status: JobStatus = JobStatus.QUEUED
    params: dict[str, Any] = Field(default_factory=dict)
    #: How many times a runner has started this job.
    #:
    #: It exists so that reclaiming an orphaned job after a restart is safe rather than
    #: merely possible. A job whose own execution is what stopped the process would
    #: otherwise be requeued on every start, and the service would take itself down in a
    #: loop, on a schedule set by the one thing it cannot survive. Past the limit,
    #: reclaiming gives up and says so in `error`.
    attempts: int = 0
    #: Why the machinery failed, or why the panel was refused. Never both, and never a
    #: stack trace — a caller reading this is owed a cause, not a traceback.
    error: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class Run(Record):
    """A finished assessment: the whole payload, plus the few things worth indexing.

    The payload is stored entire and is the only source of truth. Every other column
    here is a copy of something inside it, lifted out so a list of runs can be drawn
    without opening any of them — and each one is written from the payload on insert,
    never supplied separately, so they cannot disagree with it.
    """

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    project_id: UUID
    job_id: UUID | None = None
    corridor_id: UUID | None = None

    #: The payload's own shape version, from `roadrisk.contract.SCHEMA_VERSION`. This is
    #: what makes the promise re-readable: a consumer can tell whether it still knows
    #: how to read a run stored months ago before it tries.
    schema_version: str | None = None
    engine_version: str
    #: The reproducibility manifest's fingerprint. Two identical runs share one, which
    #: is worth knowing without parsing 300 kB of JSON.
    fingerprint: str
    mode: str
    rung: str

    payload: dict[str, Any]
    created_at: datetime | None = None


class Artefact(Record):
    """A file belonging to a run, stored by reference.

    `report.html` is a third of a megabyte and a PDF is more. They are blobs, they are
    regenerable from the payload, and a database is the wrong place for them — so what
    is kept is where it went, how big it was and what it hashed to. `uri` is a `file://`
    path today and an object-store URL at 6.2; nothing else here changes when it does.
    """

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    run_id: UUID
    kind: ArtefactKind
    uri: str
    size_bytes: int
    sha256: str
    created_at: datetime | None = None
