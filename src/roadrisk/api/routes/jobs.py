"""Jobs — the resource that is asynchronous from its first endpoint, and why.

Measured in this repository: a cold corridor is 55.5 s (step 2.9), `--bayes` on the demo
corridor runs for tens of minutes (4.7), and MCMC is minutes when it is reached at all.
No HTTP request survives that, so `POST /jobs` returns **202** with a `Location` and
nothing to show yet.

It returns 202 *today*, with no runner behind it. That is deliberate rather than
unfinished: if this only started returning 202 once Celery existed, 5.2 would change the
contract and break every client written against 5.1. 5.1d attaches an in-process runner
and 5.2a swaps it for a chord; neither changes what a client was promised here.

**What submit is for.** Everything that can be refused without running anything is
refused here, so that a job which could never succeed never becomes a queued job:

* a panel that breaks the input contract — 422, the column named, no job created;
* a shape factor no entry in `factors.yaml` declares — a typo, and finding it in a run
  log a quarter of an hour later helps nobody;
* a corridor with neither an OSM reference nor a bounding box, which no fetch can
  resolve;
* a panel larger than this deployment accepts.

What is emphatically **not** refused here is a descent to Mode B, a dropped term or an
unsourced weight. Those are results, they belong to the run, and they arrive as 200.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response, status

from roadrisk.api.deps import RegistryDep, SettingsDep, StoreDep, TenantId
from roadrisk.api.errors import (
    HTTP_413,
    HTTP_422,
    REFUSAL_RESPONSES,
    ApiRefusal,
    ErrorCode,
)
from roadrisk.api.schemas import JobSpec, JobSubmission
from roadrisk.core.contract import prepare_panel
from roadrisk.core.registry import Registry
from roadrisk.store import Job

router = APIRouter(tags=["jobs"], responses=REFUSAL_RESPONSES)


@router.post(
    "/jobs",
    response_model=Job,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit an assessment. Accepted, not performed",
    responses={
        202: {"description": "Queued. Poll `Location`, which is `GET /jobs/{id}`."},
        413: {"description": "The panel is larger than this deployment accepts."},
        422: {
            "description": "The panel broke the input contract, or the request could "
            "not describe a runnable job. No job was created."
        },
    },
)
def submit_job(
    body: JobSubmission,
    tenant_id: TenantId,
    store: StoreDep,
    settings: SettingsDep,
    registry: RegistryDep,
    response: Response,
) -> Job:
    """Accept a job, or refuse it before it exists.

    Note the order. Every check that can refuse happens *before* `create_job`, so a
    422 leaves no row behind — "no job created" is the half of the refusal contract
    that a client can actually verify, by listing the project's jobs and finding it
    empty.
    """
    store.get_project(tenant_id, body.project_id)
    _reject_unknown_shape_factors(body.params.shape_factors, registry)

    if body.corridor_id is not None:
        corridor = store.get_corridor(tenant_id, body.corridor_id)
        if corridor.project_id != body.project_id:
            raise ApiRefusal(
                HTTP_422,
                ErrorCode.INVALID_REQUEST,
                f"Corridor {corridor.id} belongs to project {corridor.project_id}, "
                f"not {body.project_id}.",
                field="body.corridor_id",
            )
        if corridor.ref is None or corridor.bbox is None:
            # A corridor may legitimately have neither — the record's own docstring
            # says so, for a client-supplied centreline. There is no way to supply one
            # over HTTP yet, so a job on such a corridor has no geometry to fetch and
            # is refused now rather than failing in a worker at 5.1d.
            raise ApiRefusal(
                HTTP_422,
                ErrorCode.INVALID_REQUEST,
                f"Corridor {corridor.id} has "
                f"{'no OSM reference' if corridor.ref is None else 'no bounding box'}, "
                "so there is nothing to fetch. Give it both, or submit a panel you "
                "have already built.",
                field="body.corridor_id",
            )
        spec = JobSpec(source="corridor", options=body.params)
    else:
        assert body.panel is not None  # guaranteed by JobSubmission's validator
        _check_panel(body.panel, settings.max_panel_rows)
        spec = JobSpec(source="panel", options=body.params, panel=body.panel)

    job = store.create_job(
        Job(
            tenant_id=tenant_id,
            project_id=body.project_id,
            corridor_id=body.corridor_id,
            params=spec.model_dump(mode="json"),
        )
    )
    response.headers["Location"] = f"/jobs/{job.id}"
    return job


@router.get(
    "/jobs/{job_id}",
    response_model=Job,
    summary="Where a job got to",
)
def get_job(job_id: UUID, tenant_id: TenantId, store: StoreDep) -> Job:
    """Read a job's status.

    `succeeded` means the job ran to completion, **not** that Mode A was reached. A run
    that descended to Mode B, dropped a term or refused an unsourced weight succeeded,
    and carries those findings. `failed` is the machinery breaking, with a cause in
    `error` and never a stack trace. `rejected` is the panel breaking the input
    contract, where nothing malfunctioned.

    At 5.1c nothing executes jobs, so every job here stays `queued`. `GET /health`
    reports `runner: null` for exactly that reason.
    """
    return store.get_job(tenant_id, job_id)


@router.get(
    "/projects/{project_id}/jobs",
    response_model=list[Job],
    summary="Every job in a project, newest first",
)
def list_jobs(project_id: UUID, tenant_id: TenantId, store: StoreDep) -> list[Job]:
    return store.list_jobs(tenant_id, project_id)


# -- submit-time checks --------------------------------------------------------


def _reject_unknown_shape_factors(names: list[str], registry: Registry) -> None:
    """A shape factor must be something `factors.yaml` declares.

    `assess` already reports names it could not put a spline on, which is right for a
    factor that exists but did not survive into the fitted specification. A name no
    factor has at all is a different thing — it is a typo, it will never mean anything,
    and it costs nothing to say so at submit.
    """
    declared = set(registry.names)
    unknown = [name for name in names if name not in declared]
    if not unknown:
        return
    raise ApiRefusal(
        HTTP_422,
        ErrorCode.INVALID_REQUEST,
        f"No factor is called {', '.join(repr(name) for name in unknown)}. "
        f"GET /registry lists the {len(declared)} that exist.",
        field="body.params.shape_factors",
    )


def _check_panel(rows: list[dict[str, object]], max_rows: int) -> None:
    """Run the submitted panel through the input contract, here and now.

    Cheap — it is column checks and two multiplications over a frame that fits in
    memory — and it is the only moment at which "no job created" can be true. A
    `ContractViolation` propagates to the handler in `roadrisk.api.errors`, which turns
    it into a 422 carrying the engine's own message, column named.

    The prepared frame is thrown away. What gets stored is the panel as submitted:
    `exposure` and `log_exposure` are derived, and keeping the derivation inside a row
    would freeze a copy of the contract next to the data it describes.
    """
    if len(rows) > max_rows:
        raise ApiRefusal(
            HTTP_413,
            ErrorCode.TOO_LARGE,
            f"That panel has {len(rows):,} rows and this deployment accepts "
            f"{max_rows:,}. A 100 km corridor at 500 m units over 24 monthly periods "
            "is about 4,800.",
            field="body.panel",
        )

    import pandas as pd

    prepare_panel(pd.DataFrame(rows))
