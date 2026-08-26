"""Step 5.2a — an adapter failure fails its own branch, and nothing else.

That sentence is the step's done-when, and it is a property of how the work is
*arranged* rather than of what runs it. It has to hold before anything runs in parallel,
because a branch that can poison its neighbours poisons a chord too — so it is tested
here, with no broker, no network and no Celery.

The second property is the one that makes parallelism safe to turn on: **a threaded run
and a sequential run produce the same payload, byte for byte.** Fusion groups by factor
and the panel takes its column order from the result, so without it two runs of the same
corridor would be laid out differently depending on which server answered first.
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from roadrisk.geo.adapters import AdapterNotDeclared, AdapterResult
from roadrisk.geo.branches import (
    Branch,
    SequentialFanout,
    ThreadedFanout,
    run_branch,
)
from roadrisk.geo.demo import monthly_periods, synthetic_centreline, synthetic_crashes
from roadrisk.geo.pipeline import build_corridor_panel

GRADE_SLOT = (("grade_pct", "copernicus_dem_glo30"),)


def exploding_sampler(*_args, **_kwargs):
    """A raster sampler that fails the way a missing GDAL or a dead window does."""
    raise RuntimeError("GDAL could not open the window")


@pytest.fixture(scope="module")
def corridor_inputs():
    points = synthetic_centreline(length_km=4.0)
    periods = monthly_periods(4)
    return points, periods, synthetic_crashes(points, periods, n_crashes=120)


# -- one branch ----------------------------------------------------------------


def test_a_failing_branch_returns_a_receipt_rather_than_raising() -> None:
    """`run_branch` never raises, because its caller has nobody to raise at.

    A fanout is collecting results and a Celery task is on another machine. A branch
    that ended with neither a result nor a receipt is a factor that vanished with no
    explanation, which is the one thing this package exists to prevent.
    """

    def boom() -> list[AdapterResult]:
        raise RuntimeError("the mirror returned 504 for the third time")

    branch = Branch(name="The Copernicus DEM sample", slots=GRADE_SLOT, run=boom)

    (result,) = run_branch(branch)

    assert result.resolved == []
    assert [(s.factor, s.adapter) for s in result.skipped] == [
        ("grade_pct", "copernicus_dem_glo30")
    ]
    assert "RuntimeError: the mirror returned 504" in result.skipped[0].reason
    assert "grade_pct" in result.notes[0]


def test_a_receipt_names_the_exception_type_not_a_traceback() -> None:
    """The type is what tells a reader whether to re-run or open a ticket.

    `CorridorError` is a busy mirror, `RasterioIOError` is a missing GDAL, `KeyError` is
    ours. A traceback in a client-facing report tells them the shape of our source tree
    instead.
    """

    def boom() -> list[AdapterResult]:
        raise KeyError("elements")

    (result,) = run_branch(Branch(name="x", slots=GRADE_SLOT, run=boom))

    assert result.skipped[0].reason.startswith("KeyError:")
    assert "Traceback" not in result.skipped[0].reason
    assert "pipeline.py" not in result.skipped[0].reason


def test_a_registry_mismatch_is_never_swallowed() -> None:
    """The one failure that must not degrade into a missing factor.

    A renamed declaration or a typo'd adapter name is wrong on every corridor and for
    ever. Degrading it would dress a permanently broken adapter as a flaky source: the
    factor would go quietly missing on every run, and the report would say in good faith
    that the data was not there.
    """

    def boom() -> list[AdapterResult]:
        raise AdapterNotDeclared("registry v0.2.0 does not declare 'osm_maxspeeed'")

    with pytest.raises(AdapterNotDeclared):
        run_branch(Branch(name="x", slots=GRADE_SLOT, run=boom))


def test_a_branch_with_no_slots_still_reports_that_it_failed() -> None:
    """A client table that failed while being read never got far enough to say which
    factors it would have filled. The honest shape of not knowing is a note and no list
    of named absences — not an invented list, and not silence.
    """

    def boom() -> list[AdapterResult]:
        raise ValueError("unit_id column is not unique")

    (result,) = run_branch(Branch(name="The client's own values", slots=(), run=boom))

    assert result.skipped == []
    assert "ValueError: unit_id column is not unique" in result.notes[0]


# -- the whole corridor --------------------------------------------------------


def test_a_dead_adapter_costs_one_factor_and_not_the_corridor(corridor_inputs) -> None:
    """Step 5.2a's done-when, over the real pipeline.

    Before this step the raster adapters were unguarded, so a sampler that threw lost a
    corridor whose crashes were already snapped and whose curvature was already
    computed. Now the factor is reported missing and the run continues.
    """
    points, periods, crashes = corridor_inputs

    built = build_corridor_panel(
        points,
        periods=periods,
        name="demo",
        crashes=crashes,
        elevation=exploding_sampler,
    )

    assert built.n_units > 1 and built.n_rows > 1
    assert built.total_crashes > 0, "The crashes were snapped before the adapter ran."
    assert "curve_density" in built.factor_columns, "Curvature is unaffected."
    assert "grade_pct" not in built.factor_columns

    skipped = {s.factor: s.reason for r in built.adapters for s in r.skipped}
    assert "grade_pct" in skipped
    assert "GDAL could not open the window" in skipped["grade_pct"]

    assert any("grade_pct" in warning for warning in built.warnings), (
        "A lost factor has to be visible at the top of the run, not only in a table."
    )


def test_the_loss_is_read_from_the_registry_rather_than_restated(
    corridor_inputs, shipped_registry
) -> None:
    """A branch says which registry slots it fills; the factors lost come from there.

    The alternative is a second list of factor names inside the pipeline, which is the
    drift step 5.1a exists to prevent — it would agree with itself for ever and with
    `factors.yaml` never.
    """
    points, periods, crashes = corridor_inputs

    built = build_corridor_panel(
        points,
        periods=periods,
        name="demo",
        crashes=crashes,
        elevation=exploding_sampler,
    )

    declared = {f.name for f in shipped_registry.factors}
    reported = {s.factor for r in built.adapters for s in r.skipped}
    assert reported <= declared, f"Skipped factors not in the registry: {reported - declared}"

    for result in built.adapters:
        for skip in result.skipped:
            factor = shipped_registry.by_name(skip.factor)
            assert any(a.name == skip.adapter for a in factor.adapters), (
                f"{skip.adapter} is not declared for {skip.factor}"
            )


def test_threaded_and_sequential_produce_the_same_payload(corridor_inputs) -> None:
    """Byte for byte, not merely equivalent.

    `ThreadPoolExecutor.map` yields in input order however the branches finish, which is
    what keeps this true. Without it, fusion's grouping — and therefore the panel's
    column order and the report's layout — would depend on which server answered first,
    and two runs of one corridor would differ for a reason nobody could explain.
    """
    points, periods, crashes = corridor_inputs

    def build(fanout):
        return build_corridor_panel(
            points,
            periods=periods,
            name="demo",
            crashes=crashes,
            elevation=exploding_sampler,
            fanout=fanout,
        )

    sequential = build(SequentialFanout()).as_dict()
    threaded = build(ThreadedFanout()).as_dict()

    assert json.dumps(sequential, sort_keys=True) == json.dumps(threaded, sort_keys=True)


def test_the_threaded_fanout_actually_overlaps(corridor_inputs) -> None:
    """Otherwise it is a thread pool that costs a pool and buys nothing.

    Three branches that each sleep — standing in for a socket, which is what the 55.5 s
    cold corridor is actually made of — must finish in about one sleep rather than
    three.
    """
    delay = 0.2
    seen: set[int] = set()
    lock = threading.Lock()

    def sleeper() -> list[AdapterResult]:
        with lock:
            seen.add(threading.get_ident())
        time.sleep(delay)
        return [AdapterResult(name="slow")]

    branches = [
        Branch(name=f"branch {n}", slots=(), run=sleeper, needs_network=True)
        for n in range(3)
    ]

    started = time.monotonic()
    results = ThreadedFanout(max_workers=3).run(branches)
    elapsed = time.monotonic() - started

    assert len(results) == 3
    assert len(seen) > 1, "Every branch ran on the same thread — nothing overlapped."
    assert elapsed < delay * 3, f"{elapsed:.2f}s is not an overlap of three {delay}s waits"


def test_one_branch_does_not_pay_for_a_pool(corridor_inputs) -> None:
    """A corridor with nothing to overlap runs in place.

    The offline suite builds hundreds of these — curvature and nothing else — and a pool
    per corridor would be pure overhead against a single branch that never waits.
    """
    ran_on: list[int] = []

    def here() -> list[AdapterResult]:
        ran_on.append(threading.get_ident())
        return [AdapterResult(name="only")]

    ThreadedFanout().run([Branch(name="only", slots=(), run=here)])

    assert ran_on == [threading.get_ident()]


def test_a_failing_branch_inside_a_pool_still_reports_itself(corridor_inputs) -> None:
    """A receipt written in another thread has to arrive like one written in place.

    This is the property the chord rests on: at 5.2a a branch fails on another machine,
    and the run has to carry the same sentence it would have carried here.
    """

    def boom() -> list[AdapterResult]:
        raise RuntimeError("that mirror is down")

    results = ThreadedFanout(max_workers=2).run(
        [
            Branch(name="fine", slots=(), run=lambda: [AdapterResult(name="fine")]),
            Branch(name="The DEM sample", slots=GRADE_SLOT, run=boom),
        ]
    )

    assert [r.name for r in results] == ["fine", "The DEM sample"], (
        "Declaration order, not completion order."
    )
    assert results[1].skipped[0].factor == "grade_pct"
