"""Step 5.2a — adapters as independently-failable branches, and how they fan out.

The pipeline's own docstring has said *"fan out adapters"* since Stage 2 and it has
never been true: the adapters ran in a straight line, and any one of them raising took
the whole corridor with it. Two things were wrong with that, and this module fixes them
in the order that matters.

**First, isolation.** The done-when for this step is that *an adapter failure fails its
own branch — the factor is reported missing, the job is not failed*. That is not a
Celery property; it is a property of how the work is arranged, and it has to exist
before anything runs in parallel, because a branch that can poison its neighbours
poisons a chord too. Today three of the network fetches degrade — on
:class:`~roadrisk.geo.errors.CorridorError` only — and none of the eight compute
adapters do. A `KeyError` out of a malformed Overpass response, a rasterio error on a
DEM window, a `Timeout` that is not a `CorridorError`: any of those loses a corridor
whose crashes were already snapped and whose curvature was already computed.

**Then, parallelism.** The measured 55.5 s cold corridor is almost entirely network
wait — an OSM ribbon query, a much larger regional network query, and Mapillary — and
those three do not depend on each other. Running them concurrently costs the maximum
rather than the sum.

**Threads, not processes.** What is being overlapped is time spent waiting on a socket,
and the GIL is released for exactly that. Processes would have to pickle the
segmentation — shapely geometry, one entry per unit — to every branch and the resolved
`pandas.Series` back, which is real expense to parallelise work that is not
CPU-bound. Celery arrives for a different reason: durability and other machines, not
speed on this one.

**A branch declares what it fills, and the report reads the loss from the registry.**
Every adapter module already publishes ``SLOTS`` — the ``(factor, adapter)`` pairs it is
declared for, checked against `factors.yaml` before any work is done. A branch carries
those, so when it fails the list of factors now missing is *read from the declaration*
rather than written out a second time somewhere it could drift from.

**Order is preserved regardless of completion order.** A parallel run returns its
results in the order the branches were declared, so fusion, the factor columns and the
payload are identical to the sequential run's. A test asserts it. The alternative — a
payload whose column order depends on which server answered first — would make two runs
of the same corridor differ for no reason anybody could explain.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from roadrisk.geo.adapters.base import AdapterNotDeclared, AdapterResult, SkippedFactor

log = logging.getLogger("roadrisk.geo.branches")

#: Failures that mean this package is wrong rather than that the world is, and are
#: therefore never turned into a missing factor.
#:
#: :class:`AdapterNotDeclared` is raised when the code fills a registry slot that
#: `factors.yaml` does not declare — a renamed declaration, a typo'd adapter name. That
#: is true on every corridor and for ever, so degrading it would dress a permanently
#: broken adapter as a flaky source and nobody would look again.
#:
#: Everything else degrades. Not because everything else is the world's fault, but
#: because absence here is *loud*: a failed branch puts every factor it would have
#: filled into the skipped table with the exception on it, adds a warning at the top of
#: the run, and reaches the limitations page through `factors_absent`. A bug that
#: presents as "grade_pct absent: rasterio.RasterioIOError" is visible in a way that a
#: lost corridor is not.
NEVER_SWALLOWED: tuple[type[BaseException], ...] = (AdapterNotDeclared,)


@dataclass(frozen=True)
class Branch:
    """One independently-failable unit of adapter work.

    A branch is a **source**, not a factor: the OSM ribbon fetch and the two adapters
    that read it are one branch, because they share the one failure mode that matters
    and neither can run without it.
    """

    #: What failed, in the words a report will print. "The OSM attribute fetch", not
    #: "osm_tags" — this ends up in front of a client.
    name: str
    #: ``(factor, adapter)`` pairs, taken from the adapter modules' own ``SLOTS``. What
    #: is lost when this branch fails is read from here rather than restated.
    slots: tuple[tuple[str, str], ...]
    #: The work. May return more than one result: the OSM branch produces the tag
    #: adapter's and the density adapter's.
    run: Callable[[], list[AdapterResult]]
    #: True when this branch spends its time on a socket. Only these are worth
    #: overlapping, and it is what lets a fanout leave the cheap ones alone.
    needs_network: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def factors(self) -> tuple[str, ...]:
        """Every factor this branch could fill, once, in declaration order."""
        return tuple(dict.fromkeys(factor for factor, _ in self.slots))


def run_branch(branch: Branch) -> list[AdapterResult]:
    """Run one branch. Returns what it produced, or a receipt for why it produced
    nothing.

    **Never raises**, except for the failures in :data:`NEVER_SWALLOWED`. A caller is
    either a fanout collecting results or a Celery task with nobody to raise at, and a
    branch that ended without either a result or a receipt is a factor that vanished
    with no explanation — which is the one thing this package exists to prevent.
    """
    try:
        return list(branch.run())
    except NEVER_SWALLOWED:
        raise
    except Exception as exc:
        log.exception("Adapter branch %r failed", branch.name)
        return [failure_result(branch, exc)]


def failure_result(branch: Branch, exc: BaseException) -> AdapterResult:
    """Turn a branch failure into the vocabulary the report already speaks.

    A :class:`~roadrisk.geo.adapters.base.SkippedFactor` per factor, each naming the
    adapter that would have filled it and the exception that stopped it. "We looked and
    it broke" is a different statement from "we did not look", and the report has had
    somewhere to put the difference since Stage 2.
    """
    cause = _cause(exc)
    lost = branch.factors
    return AdapterResult(
        name=branch.name,
        skipped=[
            SkippedFactor(factor=factor, adapter=adapter, reason=cause)
            for factor, adapter in branch.slots
        ],
        notes=[
            f"{branch.name} failed, so "
            + (
                f"{len(lost)} factor(s) are absent from this panel "
                f"({', '.join(lost)})"
                if lost
                else "whatever it would have contributed is absent"
            )
            + f": {cause} Everything else in the run is unaffected."
        ],
    )


def _cause(exc: BaseException) -> str:
    """The exception as one sentence, with its type. Never a traceback.

    The type is kept because it is the part that tells a reader whether to re-run or to
    open a ticket: `CorridorError` is a busy mirror, `RasterioIOError` is a missing
    GDAL, and `KeyError` is ours.
    """
    detail = " ".join(str(exc).split())
    return f"{type(exc).__name__}: {detail}" if detail else f"{type(exc).__name__}."


# -- how the branches are run --------------------------------------------------


@runtime_checkable
class Fanout(Protocol):
    """How a set of branches gets run. The seam Celery attaches to at the chord."""

    name: str

    def run(self, branches: Sequence[Branch]) -> list[AdapterResult]: ...


class SequentialFanout:
    """One after another, in declaration order. The default, and not a fallback.

    A corridor with no network adapters — curvature and a client CSV — has nothing to
    overlap, and the offline test suite runs hundreds of these. Threads would buy
    nothing and cost a pool.
    """

    name = "sequential"

    def run(self, branches: Sequence[Branch]) -> list[AdapterResult]:
        results: list[AdapterResult] = []
        for branch in branches:
            results.extend(run_branch(branch))
        return results


class ThreadedFanout:
    """Network branches concurrently, everything else in place.

    `ThreadPoolExecutor.map` yields in **input** order however the branches finish, which
    is what keeps a parallel run's payload identical to a sequential one's. That is not
    incidental: fusion groups by factor and the panel takes its column order from the
    result, so completion order would otherwise decide how a report is laid out.
    """

    name = "threaded"

    def __init__(self, max_workers: int = 4) -> None:
        self._max_workers = max_workers

    def run(self, branches: Sequence[Branch]) -> list[AdapterResult]:
        if len(branches) < 2:
            return SequentialFanout().run(branches)
        workers = min(self._max_workers, len(branches))
        with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="roadrisk-branch"
        ) as pool:
            produced = list(pool.map(run_branch, branches))
        return [result for group in produced for result in group]


__all__ = [
    "NEVER_SWALLOWED",
    "Branch",
    "Fanout",
    "SequentialFanout",
    "ThreadedFanout",
    "failure_result",
    "run_branch",
]
