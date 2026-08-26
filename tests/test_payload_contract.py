"""Step 5.1a — does the payload contract still describe the payload.

Not to be confused with `test_contract.py`, which polices the *input* panel. This one
polices the *output*: `roadrisk.contract` mirrors what `Assessment.as_dict()` and
`CorridorPanel.as_dict()` actually emit, and mirrors go stale. This is the thing that
notices.

**The mechanism is `extra="forbid"`.** A permissive model accepts any payload containing
the fields it knows about, so the engine can grow a key, the report can start depending
on it, and the two descriptions drift apart in silence. Forbidding extras turns that into
a failure here: a new key in `as_dict()` breaks these tests until it is declared.

**The case for paying that cost** is step 4.7. `posterior.coefficients` is a mapping
keyed by factor; the page had it typed as a list; every coefficient silently fell back to
its *frequentist* interval while the heading kept saying *credible*; and it survived three
steps of review, because the types agreed with themselves and nothing compared them to a
real payload.

So the fixtures below are not toy dictionaries. Each is a genuine run through the engine,
chosen to light up a different branch of the payload — the Bayesian sections in
particular, which are absent from an ordinary fit and were the parts most at risk of
being transcribed wrongly.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from roadrisk import contract
from roadrisk.contract import Run
from roadrisk.core.engine import assess
from roadrisk.core.models.base import Estimator
from roadrisk.demo import synthetic_panel
from roadrisk.report import build_run

#: Small enough that the Bayesian rungs finish in seconds, large enough to reach Mode A.
#: The ladder is exercised for its *shape* here, not its accuracy — the statistics have
#: their own tests.
UNITS = 30
PERIODS = 8
SEED = 11


@pytest.fixture(scope="module")
def base_panel():
    return synthetic_panel(n_units=UNITS, n_periods=PERIODS, seed=SEED)


@pytest.fixture(scope="module")
def mode_a_run(base_panel) -> dict[str, Any]:
    """An ordinary Mode A fit, with a spline asked for by name."""
    return build_run(assess(base_panel, shape_factors=["curve_density"]))


@pytest.fixture(scope="module")
def mode_b_run(base_panel) -> dict[str, Any]:
    """A crash-free panel. Mode A is refused, Mode B is the floor, receipts are set."""
    return build_run(assess(base_panel[base_panel["n_crashes"] == 0]))


@pytest.fixture(scope="module")
def bayes_run(base_panel) -> dict[str, Any]:
    """Fills `posterior` — the section the 4.7 defect lived in."""
    return build_run(assess(base_panel, estimator=Estimator.BAYES))


@pytest.fixture(scope="module")
def priors_run(base_panel) -> dict[str, Any]:
    """Fills `evidence` — textbook, corridor and mixture side by side."""
    return build_run(
        assess(base_panel, estimator=Estimator.BAYES, use_registry_priors=True)
    )


@pytest.fixture(scope="module")
def spatial_run(base_panel) -> dict[str, Any]:
    """Fills `spatial` — the Leroux CAR field and whether it was identified."""
    return build_run(assess(base_panel, estimator=Estimator.BAYES, use_spatial=True))


@pytest.fixture(scope="module")
def corridor_run() -> dict[str, Any]:
    """The geography half: geometry, segmentation, provenance, attribution, cache."""
    geo = pytest.importorskip("roadrisk.geo.pipeline")
    demo = pytest.importorskip("roadrisk.geo.demo")

    points = demo.synthetic_centreline()
    periods = demo.monthly_periods(6)
    built = geo.build_corridor_panel(
        points, periods=periods, crashes=demo.synthetic_crashes(points, periods)
    )
    assessment = assess(
        built.panel, snap=built.snap, corridor_units=built.corridor_units
    )
    return build_run(assessment, built)


ALL_RUNS = (
    "mode_a_run",
    "mode_b_run",
    "bayes_run",
    "priors_run",
    "spatial_run",
    "corridor_run",
)


@pytest.mark.parametrize("fixture_name", ALL_RUNS)
def test_a_real_payload_conforms(fixture_name: str, request) -> None:
    """The deliverable. Every payload the engine can produce validates, with no extras.

    A failure here is one of two things, and the message says which: a field the engine
    emits that the contract has not declared (`extra_forbidden`), or a field whose type
    the contract has wrong.
    """
    payload = request.getfixturevalue(fixture_name)
    try:
        Run.model_validate(payload)
    except ValidationError as exc:  # pragma: no cover - only on a real divergence
        lines = [
            f"  {'.'.join(str(part) for part in error['loc'])}: "
            f"{error['type']} — {error['msg']}"
            for error in exc.errors()
        ]
        pytest.fail(
            f"{fixture_name} no longer matches roadrisk.contract:\n" + "\n".join(lines)
        )


def test_the_branches_these_fixtures_cover_are_actually_populated(
    mode_a_run, mode_b_run, bayes_run, priors_run, spatial_run, corridor_run
) -> None:
    """Guard against a fixture quietly stopping at a rung it used to reach.

    Validation passes trivially against a payload whose optional sections are all
    `None`. If the Bayesian fit started failing on this panel — a dependency change, a
    tightened gate — the tests above would keep passing while covering nothing.
    """
    assert mode_a_run["assessment"]["fit"] is not None
    assert mode_a_run["assessment"]["reference"]["shapes"], "no spline in the mode A run"

    assert mode_b_run["assessment"]["mode"] == "B"
    assert mode_b_run["assessment"]["receipts"]["refusal"] is not None

    assert bayes_run["assessment"]["posterior"] is not None
    assert priors_run["assessment"]["evidence"] is not None
    assert spatial_run["assessment"]["spatial"] is not None

    assert corridor_run["corridor"] is not None
    assert corridor_run["corridor"]["segmentation"]["units"]
    assert corridor_run["corridor"]["provenance"]


def _contract_models() -> list[type[BaseModel]]:
    return [
        obj
        for _, obj in inspect.getmembers(contract, inspect.isclass)
        if issubclass(obj, BaseModel) and obj is not BaseModel
    ]


def test_every_model_forbids_extras() -> None:
    """The property the whole package rests on, asserted rather than assumed.

    Relaxing one model to `extra="ignore"` would make it silently partial again, and
    nothing else here would notice — the payload would still validate.
    """
    permissive = [
        model.__name__
        for model in _contract_models()
        if model.model_config.get("extra") != "forbid"
    ]
    assert not permissive, (
        "These contract models accept undeclared fields, so they no longer describe "
        f"the payload completely: {sorted(permissive)}"
    )
    assert len(_contract_models()) > 40, "contract models went missing"


def test_an_undeclared_field_is_caught(mode_a_run) -> None:
    """A test that cannot fail is decoration. This plants the drift it exists to catch."""
    drifted = {
        **mode_a_run,
        "assessment": {**mode_a_run["assessment"], "new_engine_field": 42},
    }
    with pytest.raises(ValidationError) as caught:
        Run.model_validate(drifted)
    assert any(
        error["type"] == "extra_forbidden" and error["loc"][-1] == "new_engine_field"
        for error in caught.value.errors()
    )


def test_a_retyped_field_is_caught(mode_a_run) -> None:
    """The other half of drift: a field that stays but changes shape.

    `checks[].threshold` is prose — "max VIF < 5", not a number. The hand-written page
    types declared it `number | null`, which no run has ever produced. That mismatch
    went unnoticed because the page never read the field; this is the shape of check
    that would have caught it.
    """
    checks = [dict(check) for check in mode_a_run["assessment"]["checks"]]
    assert checks, "the mode A run produced no checks"
    assert all(
        check["threshold"] is None or isinstance(check["threshold"], str)
        for check in checks
    ), "checks[].threshold is prose, not a number"

    checks[0]["threshold"] = {"not": "a string"}
    drifted = {
        **mode_a_run,
        "assessment": {**mode_a_run["assessment"], "checks": checks},
    }
    with pytest.raises(ValidationError):
        Run.model_validate(drifted)


def test_mode_b_carries_no_count_through_the_contract(mode_b_run) -> None:
    """4.2's rule, restated where it can be enforced on the wire.

    Mode B ranks; it does not predict. The count-shaped fields are *absent*, not null —
    a null is a hole a renderer fills with a dash, which reads as "not available" rather
    than "this mode does not produce one".
    """
    parsed = Run.model_validate(mode_b_run)
    ranking = parsed.assessment.ranking
    assert ranking is not None
    assert ranking.has_intervals is False

    for unit in ranking.units:
        assert unit.expected is None
        assert unit.expected_low is None
        assert unit.expected_high is None

    emitted = mode_b_run["assessment"]["ranking"]["units"][0]
    for absent in ("expected", "expected_low", "expected_high"):
        assert absent not in emitted, f"Mode B emitted a {absent} key"


REPO = Path(__file__).resolve().parents[1]
GENERATOR = REPO / "tools" / "generate_types.py"
TYPES_TS = REPO / "web" / "src" / "report" / "types.ts"


def _load_generator() -> ModuleType:
    """Import tools/generate_types.py, which is a script rather than a package."""
    if "generate_types" in sys.modules:
        return sys.modules["generate_types"]
    spec = importlib.util.spec_from_file_location("generate_types", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_types"] = module
    spec.loader.exec_module(module)
    return module


def test_the_committed_typescript_is_what_the_contract_generates() -> None:
    """`web/src/report/types.ts` is generated. This is what stops it drifting back.

    The file is committed rather than built, because installing this package must never
    require a Python toolchain to build the front end — the same reason the compiled
    report page is committed. Committed generated files go stale silently; this makes
    that a failing test with the fix in the message.
    """
    generated = _load_generator().render()
    current = TYPES_TS.read_text(encoding="utf-8")
    assert current == generated, (
        "web/src/report/types.ts no longer matches src/roadrisk/contract/.\n"
        "Run: python tools/generate_types.py"
    )


def test_the_generated_typescript_says_it_is_generated() -> None:
    """A generated file that does not announce itself gets hand-edited exactly once."""
    header = TYPES_TS.read_text(encoding="utf-8")[:1200]
    assert "GENERATED FILE" in header
    assert "tools/generate_types.py" in header


def test_the_posterior_coefficients_type_cannot_regress(mode_a_run) -> None:
    """The 4.7 defect, pinned in the one place that can now prevent it.

    `posterior.coefficients` is a mapping keyed by factor name. Typed as an array, a
    lookup returns nothing, every row falls back to its frequentist interval, and the
    heading keeps saying *credible*. The contract makes the wrong type unstateable, and
    this asserts the projection into TypeScript preserves that.
    """
    types = TYPES_TS.read_text(encoding="utf-8")
    posterior = types.split("export interface Posterior {", 1)[1].split("}", 1)[0]
    assert "coefficients: Record<string, PosteriorSummary | null>" in posterior, (
        "posterior.coefficients must project as a mapping, not a list"
    )
    assert "coefficients: PosteriorSummary[]" not in posterior


def test_the_payload_carries_its_own_schema_version(mode_a_run) -> None:
    """A stored run has to say which shape it is, or 5.1b cannot promise to re-read it."""
    from roadrisk.contract import SCHEMA_VERSION

    assert mode_a_run["schema_version"] == SCHEMA_VERSION
    assert Run.model_validate(mode_a_run).schema_version == SCHEMA_VERSION


def test_a_stored_run_needs_no_engine_to_be_read(mode_a_run) -> None:
    """The promise 5.1b depends on: JSON in, typed run out, nothing else in scope.

    Round-tripped through `json` first, because that is what storage and the wire do to
    it — tuples become lists, and anything that only survives in memory does not.
    """
    restored = json.loads(json.dumps(mode_a_run))
    parsed = Run.model_validate(restored)

    assert parsed.assessment.mode
    assert parsed.assessment.manifest.fingerprint
    assert parsed.limitations, "a run with no limitations is a run that lost them"
