"""Step 5.1d — what actually executes a job, and the seam 5.2a replaces.

Three things live here and they are deliberately separate:

* :func:`execute` — the work. A plain function over a store and a job id, with no web
  framework, no broker and no runner object in scope. 5.2a's Celery task calls this
  same function; what changes is who calls it and from where.
* :class:`Runner` — the interface. One method, `submit`, which takes responsibility for
  a queued job and says nothing about when it will run.
* Two implementations. :class:`InlineRunner` runs the job before `submit` returns;
  :class:`ThreadedRunner` hands it to a bounded pool and returns immediately.

**Why two.** The synchronous one is what the step asks for and what the tests use — a
test that has to poll a thread is a flaky test, and a CLI that wants a run wants it
before the process exits. But `POST /jobs` promised a **202** in 5.1c, and a cold
corridor is 55.5 s: an inline runner behind the API would turn that promise into a
minute-long request that a proxy times out. So the server gets the threaded one and the
contract holds.

**A thread pool is not a job queue, and that is why 5.2a exists.** Work in flight is
lost if the process stops, there is no retry, and nothing survives a deploy. What the
pool does buy is a **bound**: unbounded background work inside a web process is how the
web process dies. Jobs past the limit sit in `queued`, which is exactly what that status
means, and the client is not lied to.

**The status vocabulary is the refusal contract, one layer down.** `succeeded` means the
job ran to completion, *not* that Mode A was reached — a run that descended to Mode B,
dropped terms or refused an unsourced weight succeeded and carries those findings.
`rejected` is the panel breaking the input contract. `failed` is the machinery breaking,
with a cause and never a traceback.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from roadrisk.api.schemas import JobOptions, JobSpec
from roadrisk.core.errors import ContractViolation, RoadRiskError
from roadrisk.core.registry import Registry
from roadrisk.store import Job, JobStatus, Run, Store

log = logging.getLogger("roadrisk.api.runner")

#: How long the demo corridor is, and how many crashes are scattered along it. The same
#: figures `roadrisk corridor --demo` uses, because a demonstration that behaved
#: differently depending on which surface you reached it through would demonstrate
#: nothing about either.
DEMO_LENGTH_KM = 10.0
DEMO_CRASHES = 900


@runtime_checkable
class Runner(Protocol):
    """Something that takes responsibility for a queued job.

    `submit` says nothing about *when*. That is the whole point of the interface: the
    API returns 202 either way, and whether the work happens in this thread, in a pool,
    or on a machine in another region is a deployment decision rather than a contract.
    """

    #: Reported by `GET /health`. A deployment with no runner reports null there, so a
    #: client can tell "not started yet" from "nothing is listening" — which is the
    #: distinction 5.1c had to make in prose because there was nothing to name.
    name: str

    def submit(self, tenant_id: UUID, job_id: UUID) -> None: ...


class InlineRunner:
    """Runs the job before `submit` returns.

    Correct for a test, which wants a result rather than a race, and for any caller
    that is going to wait anyway. Wrong behind HTTP: `POST /jobs` would block for the
    length of the assessment, which is tens of seconds cold and minutes with `--bayes`.
    """

    name = "inline"

    def __init__(self, provider: Any, *, registry: Registry | None = None) -> None:
        self._provider = provider
        self._registry = registry

    def submit(self, tenant_id: UUID, job_id: UUID) -> None:
        with self._provider() as store:
            execute(store, tenant_id, job_id, registry=self._registry)


class ThreadedRunner:
    """Hands the job to a bounded pool and returns immediately.

    The store is opened *inside* the worker thread, from the same provider the request
    used. It is never the request's store: psycopg3 connections are not safe to share
    across threads, and the request's store is closed the moment the response is sent.
    """

    name = "in-process"

    def __init__(
        self,
        provider: Any,
        *,
        max_workers: int = 2,
        registry: Registry | None = None,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="roadrisk-job"
        )

    def submit(self, tenant_id: UUID, job_id: UUID) -> None:
        self._pool.submit(self._run, tenant_id, job_id)

    def _run(self, tenant_id: UUID, job_id: UUID) -> None:
        # Nothing may escape a pool thread. An exception here is not raised at anybody:
        # the future is never awaited, so it would be swallowed by the executor and the
        # job would sit in `running` for ever with no cause recorded. `execute` already
        # turns every failure into a status; this is the belt for the case where the
        # store itself is unreachable and even that could not be written down.
        try:
            with self._provider() as store:
                execute(store, tenant_id, job_id, registry=self._registry)
        except Exception:  # pragma: no cover - only when the store itself is gone
            log.exception("Job %s could not be executed or marked failed", job_id)

    def shutdown(self, *, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait)


def execute(
    store: Store,
    tenant_id: UUID,
    job_id: UUID,
    *,
    registry: Registry | None = None,
) -> Run | None:
    """Run one job to completion and record what happened. Never raises.

    Every outcome is written to the job's status, because the caller is a pool thread or
    a Celery worker and there is nobody to raise at. A job that ends without a status
    change is a job nobody can diagnose.

    Args:
        store: A store this thread owns. Not one borrowed from a request.
        tenant_id: Whose job it is. Required, like everywhere else in the store.
        job_id: The job. Must be `queued`; anything else is left alone.
        registry: Factor registry. Defaults to the one shipped with the package.

    Returns:
        The stored run, or None if the job was rejected, failed, or was not queued.
    """
    job = store.get_job(tenant_id, job_id)
    if job.status is not JobStatus.QUEUED:
        # Not an error, and deliberately silent. Two runners racing the same job, or a
        # retry after a restart, must not produce two runs from one submission — and
        # this is the only place that can be decided, because `create_job` happened in
        # a different process.
        return None

    store.update_job_status(tenant_id, job_id, JobStatus.RUNNING)
    try:
        payload = _assess(store, job, registry)
        run = store.store_run(
            tenant_id,
            job.project_id,
            payload,
            job_id=job.id,
            corridor_id=job.corridor_id,
        )
    except ContractViolation as exc:
        # The panel was refused. Nothing malfunctioned, so this is not `failed` — the
        # receipt naming the offending column is the entire result of the job.
        store.update_job_status(tenant_id, job_id, JobStatus.REJECTED, error=str(exc))
        return None
    except Exception as exc:
        store.update_job_status(tenant_id, job_id, JobStatus.FAILED, error=_cause(exc))
        log.exception("Job %s failed", job_id)
        return None

    store.update_job_status(tenant_id, job_id, JobStatus.SUCCEEDED)
    return run


def _cause(exc: BaseException) -> str:
    """A sentence, never a traceback.

    The traceback is logged where an operator can read it. What is written into the job
    row is read by a client, and a stack trace tells them the shape of our source tree
    instead of what went wrong.
    """
    detail = " ".join(str(exc).split())
    if not detail:
        return f"{type(exc).__name__} with no message."
    return f"{type(exc).__name__}: {detail}"


# -- the work ------------------------------------------------------------------


def _assess(store: Store, job: Job, registry: Registry | None) -> dict[str, Any]:
    """Turn one job into a run payload.

    Reads the job's own `params` back through :class:`JobSpec` rather than poking at the
    dictionary, so a submission means the same thing here as it did at the boundary that
    accepted it.
    """
    from roadrisk.core.context import RunContext
    from roadrisk.core.engine import assess
    from roadrisk.report import build_run

    spec = JobSpec.model_validate(job.params)
    options = spec.options
    context = RunContext(
        facility_type=options.facility_type,
        region=options.region,
        severity=options.severity,
    )

    if spec.source == "panel":
        import pandas as pd

        assert spec.panel is not None  # the submit boundary guarantees it
        assessment = assess(
            pd.DataFrame(spec.panel),
            registry=registry,
            context=context,
            **_engine_options(options),
        )
        return build_run(assessment)

    built = _build_corridor(store, job, spec, registry)
    assessment = assess(
        built.panel,
        registry=registry,
        snap=built.snap,
        corridor_units=built.corridor_units,
        context=context,
        **_engine_options(options),
    )
    return build_run(assessment, built)


def _engine_options(options: JobOptions) -> dict[str, Any]:
    """The options `assess` takes, and only those.

    Written out rather than splatted from the model, because `JobOptions` also carries
    pipeline settings — unit length, tolerance, periods, adapters — and passing those to
    the engine would be a `TypeError` discovered by a client rather than by a reviewer.

    Nothing here can force a mode, a rung or a term. `assess` exposes no argument for
    them and a test asserts it never grows one: whether a panel can support seven terms
    is a question about data adequacy, and a caller who could overrule it would.
    """
    return {
        "shape_factors": tuple(options.shape_factors),
        "estimator": options.estimator,
        "use_registry_priors": options.use_registry_priors,
        "use_spatial": options.use_spatial,
    }


def _build_corridor(
    store: Store, job: Job, spec: JobSpec, registry: Registry | None
) -> Any:
    """Build the geography half, for a demo corridor or a real one.

    The `roadrisk.geo` import is deliberately here rather than at module scope. The
    geospatial pipeline is an optional extra, and a machine that installed the API to
    serve stored runs should not fail to import the API because shapely is absent — it
    should fail *this job*, with a cause, which is the third row of the refusal
    contract exactly as written.
    """
    try:
        from roadrisk.geo.demo import (
            monthly_periods,
            synthetic_centreline,
            synthetic_crashes,
        )
        from roadrisk.geo.pipeline import build_corridor_panel
    except ModuleNotFoundError as exc:
        raise RunnerUnavailable(
            "This service cannot build a corridor: the geospatial extra is not "
            f'installed ({exc.name}). Run: pip install "roadrisk-panel[geo]". '
            "Submitting a panel you have already built needs none of it."
        ) from exc

    options = spec.options
    crashes = _crash_frame(spec)
    # **A supplied crash table decides the calendar.** `monthly_periods` invents
    # 2024-01 onwards, which is right for a demo and quietly catastrophic for real data:
    # give it crashes from 2019 and every one falls outside the panel, is counted under
    # "period not in panel", and the run describes a road with no crashes on it —
    # confidently, and in Mode B, which is the exact failure this project exists to
    # refuse. The periods a crash table actually covers are the only honest calendar for
    # a panel built to receive it.
    periods = (
        _periods_from(crashes)
        if crashes is not None
        else monthly_periods(options.n_periods)
    )
    unit_length_m = options.unit_length_m or 500.0

    if spec.source == "demo":
        points = synthetic_centreline(length_km=DEMO_LENGTH_KM)
        return build_corridor_panel(
            points,
            periods=periods,
            name="demo",
            crashes=synthetic_crashes(points, periods, n_crashes=DEMO_CRASHES),
            target_length_m=unit_length_m,
            tolerance_m=options.tolerance_m,
            registry=registry,
            # The whole reason this flag exists. It travels in the payload, and the
            # limitations page reports it at material severity, so a demonstration
            # report that reaches somebody who did not ask for one still says on its
            # own face that there is no road here.
            synthetic=True,
        )

    if job.corridor_id is None:  # pragma: no cover - the submit boundary refuses this
        raise RunnerUnavailable("This job names no corridor and carries no panel.")

    corridor = store.get_corridor(job.tenant_id, job.corridor_id)
    points = _fetch_centreline(corridor)
    return build_corridor_panel(
        points,
        periods=periods,
        name=corridor.name,
        crashes=crashes,
        target_length_m=corridor.unit_length_m or unit_length_m,
        tolerance_m=options.tolerance_m,
        registry=registry,
        ref=corridor.ref or corridor.osm_name,
        **_clients(options),
    )


def _crash_frame(spec: JobSpec) -> Any:
    """The submitted crash table as a dataframe, or None.

    Columns are left exactly as submitted. `build_corridor_panel` takes the column names
    as arguments and does the snapping itself, so converting anything here would be this
    module holding a second opinion about a contract that already has one.
    """
    if not spec.crashes:
        return None
    import pandas as pd

    return pd.DataFrame(spec.crashes)


def _periods_from(crashes: Any) -> list[str]:
    """The calendar a crash table covers, in order.

    Sorted as strings, which is why the CLI's `YYYY-MM` convention matters: it sorts
    chronologically on its own. A period label that does not is still handled correctly
    — the panel is a set of cells and the order only decides how they are listed — but
    it reads oddly in a report, and that is the caller's choice to make.

    Every period is kept, including ones with a single crash. Trimming to a "busy"
    window would drop the zero-crash cells that Mode A is built on.
    """
    return sorted({str(period) for period in crashes["period"].tolist()})


def _fetch_centreline(corridor: Any) -> list[tuple[float, float]]:
    """Resolve the road from OSM. The submit boundary has already checked both inputs.

    Which tag identifies the road is the corridor's own record to hold — the store
    refuses a row carrying both, so there is nothing to choose between here.
    """
    from roadrisk.geo.osm import (
        BoundingBox,
        HttpOverpassClient,
        Selector,
        fetch_corridor_by,
    )

    south, west, north, east = corridor.bbox
    selector = (
        Selector.by_ref(corridor.ref)
        if corridor.ref is not None
        else Selector.by_name(corridor.osm_name)
    )
    result = fetch_corridor_by(
        selector,
        BoundingBox(south=south, west=west, north=north, east=east),
        client=HttpOverpassClient(),
    )
    return list(result.points)


def _clients(options: JobOptions) -> dict[str, Any]:
    """Turn the requested adapter names into the clients the pipeline takes.

    Constructed here rather than at submit because they hold sockets and tokens, and a
    client built during a request that is then executed minutes later in a pool thread
    is a connection nobody owns.
    """
    from roadrisk.geo.adapters.mapillary import HttpMapillaryClient
    from roadrisk.geo.osm import HttpOverpassClient

    wanted = set(options.adapters)
    clients: dict[str, Any] = {}
    if "osm" in wanted:
        clients["osm_client"] = HttpOverpassClient()
    if "traffic" in wanted:
        clients["network_client"] = HttpOverpassClient(timeout_s=240.0)
    if "mapillary" in wanted:
        clients["mapillary_client"] = HttpMapillaryClient()
    if "rasters" in wanted:
        from roadrisk.geo.adapters.rasters import elevation_sampler, landcover_sampler

        clients["elevation"] = elevation_sampler()
        clients["landcover"] = landcover_sampler()
    return clients


class RunnerUnavailable(RoadRiskError):
    """This deployment cannot do what the job asks, and says which piece is missing.

    A `RoadRiskError` rather than a bare exception because that is what it is: a refusal
    with a stated reason. It reaches a client as the job's `error`, never as a 500.
    """


__all__ = [
    "DEMO_CRASHES",
    "DEMO_LENGTH_KM",
    "InlineRunner",
    "Runner",
    "RunnerUnavailable",
    "ThreadedRunner",
    "execute",
]
