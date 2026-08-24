"""Step 5.0 — the boundary, made a test.

``roadrisk.core`` must never be imported *by* — only imported *from*. That rule is
written in the package docstring and in `STEPS.md`, it has held for five stages, and
until now nothing enforced it. Stage 5 is about to add two packages whose whole job is
to sit above core and call into it, which is precisely when a convention stops being
enough: an import in the wrong direction is one line to write, invisible in review, and
a refactor to undo once anything depends on it.

**Why it is checked statically rather than by importing anything.** Half of this package
is behind optional extras — `geo` needs shapely and pyproj, the raster adapters need
GDAL through rasterio, the MCMC fallback needs emcee — and the test suite deliberately
installs none of them. A test that imported modules to inspect their dependencies could
not see the layers it most needs to police. Parsing the source with `ast` sees every
import in the repository whether or not it could be executed here.

**Three rules, and the third is the one that would have been missed.** A module can obey
the layering rule while breaking it in effect: `roadrisk.core` imports `roadrisk` for its
version string, so the day `roadrisk/__init__.py` re-exports something from `roadrisk.geo`
is the day importing the engine pulls in shapely — with every direct import still pointing
downhill and every existing check still green. The package root has to stay a leaf.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
PACKAGE_ROOT = SRC / "roadrisk"

#: The layers, lowest first. A module may import from its own layer and from any layer
#: to its left, and from nothing to its right.
#:
#: `contract` is beneath everything, including `core`. It is pure description — the
#: shape a payload is allowed to have — and it imports nothing, so anything may depend
#: on it without acquiring a dependency on anything else.
#:
#: `api` and `worker` are declared before they are built, deliberately — the point of
#: this step is that the rule exists before there is code able to break it.
#:
#: `demo` sits above `core` because it *produces* what the engine consumes: a synthetic
#: panel is an input to the library, not part of it, and an engine that reached for its
#: own test fixture would be a different kind of package.
LAYERS: tuple[str, ...] = (
    "contract",
    "core",
    "demo",
    "geo",
    "report",
    "api",
    "worker",
    "cli",
)

RANK: dict[str, int] = {name: index for index, name in enumerate(LAYERS)}

#: `report` renders from JSON and never from a live engine object — step 4.1's
#: done-when, and what lets a run stored months ago be re-rendered without a refit.
#: The general layering rule would let it import `core`; this one does not.
#:
#: `contract` is admitted deliberately, and it is the only admission. The models there
#: describe JSON and name no engine type, so importing them cannot put an engine object
#: in the report's scope — which is the property this rule exists to protect. Anything
#: else added to this set should be argued for the same way.
DICT_ONLY: frozenset[str] = frozenset({"report"})

DICT_ONLY_MAY_IMPORT: frozenset[str] = frozenset({"contract"})


@dataclass(frozen=True)
class Reference:
    """One `roadrisk.*` import, and where it was written."""

    path: Path
    line: int
    source_layer: str
    target: str

    @property
    def target_layer(self) -> str | None:
        """The layer imported, or None for the bare package."""
        parts = self.target.split(".")
        return parts[1] if len(parts) > 1 else None

    def __str__(self) -> str:
        relative = self.path.relative_to(SRC)
        return f"{relative}:{self.line} imports {self.target}"


def _layer_of(path: Path) -> str:
    """Which layer a file belongs to.

    A subpackage is named by its directory; a top-level module by its own stem, so
    `cli.py` is the `cli` layer without needing a package around it.
    """
    parts = path.relative_to(PACKAGE_ROOT).parts
    return parts[0] if len(parts) > 1 else path.stem


def _resolve(node: ast.ImportFrom, path: Path) -> str | None:
    """Turn a `from . import x` into the absolute module it means.

    There are no relative imports in the package today. Resolving them anyway is what
    stops this test quietly ceasing to apply the first time somebody writes one.
    """
    # One dot means the containing package, for a module and for an `__init__` alike:
    # both resolve against the directory they sit in. Each further dot climbs one more.
    base = ["roadrisk", *path.parent.relative_to(PACKAGE_ROOT).parts]
    for _ in range(node.level - 1):
        if len(base) > 1:
            base = base[:-1]
    return ".".join([*base, node.module]) if node.module else ".".join(base)


def _references(path: Path) -> list[Reference]:
    """Every `roadrisk.*` import in one file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    layer = _layer_of(path)
    found: list[Reference] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "roadrisk" or alias.name.startswith("roadrisk."):
                    found.append(Reference(path, node.lineno, layer, alias.name))
        elif isinstance(node, ast.ImportFrom):
            target = _resolve(node, path) if node.level else node.module
            if target and (target == "roadrisk" or target.startswith("roadrisk.")):
                found.append(Reference(path, node.lineno, layer, target))
    return found


def _source_files() -> list[Path]:
    return sorted(
        path
        for path in PACKAGE_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts and path != PACKAGE_ROOT / "__init__.py"
    )


@pytest.fixture(scope="module")
def references() -> list[Reference]:
    return [reference for path in _source_files() for reference in _references(path)]


def test_every_layer_is_declared() -> None:
    """A new package must join the order, not sit outside it.

    Without this, adding `roadrisk/api/` would produce a layer no rule mentions, and
    the checks below would pass by not applying to it.
    """
    on_disk = {_layer_of(path) for path in _source_files()}
    undeclared = sorted(on_disk - set(LAYERS))
    assert not undeclared, (
        f"Undeclared layer(s): {undeclared}. Add each to LAYERS in this file, in the "
        "position that says what it may import. A layer nobody has placed is a layer "
        "nothing constrains."
    )


def test_imports_only_point_downhill(references: list[Reference]) -> None:
    """The layering rule itself: nothing imports from a layer above its own."""
    violations = [
        reference
        for reference in references
        if reference.target_layer is not None
        and reference.target_layer in RANK
        and RANK[reference.target_layer] > RANK[reference.source_layer]
    ]
    assert not violations, "Imports pointing uphill:\n  " + "\n  ".join(
        f"{reference} — {reference.source_layer!r} may not import "
        f"{reference.target_layer!r}"
        for reference in violations
    )


def test_core_imports_nothing_but_core(references: list[Reference]) -> None:
    """Stated separately from the rule above, because it is the one that matters.

    `roadrisk.core` is a plain library over a dataframe. It has to stay installable and
    runnable with nothing but pandas and statsmodels — that is why the geospatial
    dependencies are an optional extra at all, and why GDAL, needed by two adapters of
    seventeen, is never pulled in by an assessment.
    """
    escaped = [
        reference
        for reference in references
        if reference.source_layer == "core" and reference.target_layer not in (None, "core")
    ]
    assert not escaped, "core reached outside itself:\n  " + "\n  ".join(
        str(reference) for reference in escaped
    )


def test_report_renders_from_json_alone(references: list[Reference]) -> None:
    """`report` holds no engine object, by import graph rather than by intention.

    Step 4.1's done-when is that a report renders from `assessment.json` and
    `corridor.json` with nothing else in scope. The moment this package can name an
    engine type, the cheapest way to fix a missing field is to reach for it — and a
    run stored last month stops rendering, because the object it needs is gone.
    """
    allowed = (None, *DICT_ONLY, *DICT_ONLY_MAY_IMPORT)
    reached = [
        reference
        for reference in references
        if reference.source_layer in DICT_ONLY and reference.target_layer not in allowed
    ]
    assert not reached, (
        "The report layer must consume plain JSON, not engine objects:\n  "
        + "\n  ".join(str(reference) for reference in reached)
    )


def test_the_package_root_stays_a_leaf() -> None:
    """`roadrisk/__init__.py` imports no subpackage, so core's own import of it is free.

    This is the loophole in the layering rule. `core` imports `roadrisk` for
    `__version__`; if the root ever re-exported `roadrisk.geo`, then importing the
    engine would import shapely, every direct import would still point downhill, and
    every other test in this file would still pass.
    """
    root = PACKAGE_ROOT / "__init__.py"
    reached = [
        reference for reference in _references(root) if reference.target_layer is not None
    ]
    assert not reached, (
        "The package root must not import a subpackage — it is imported by core:\n  "
        + "\n  ".join(str(reference) for reference in reached)
    )


def test_the_check_can_actually_fail(tmp_path: Path) -> None:
    """A test that cannot fail is decoration.

    Everything above passes today because the rule has held for five stages, so none of
    it demonstrates that a violation would be caught. This plants one and reads it back.
    """
    planted = tmp_path / "engine.py"
    planted.write_text("from roadrisk.geo.pipeline import build_corridor_panel\n")

    node = ast.parse(planted.read_text()).body[0]
    assert isinstance(node, ast.ImportFrom)
    reference = Reference(
        path=PACKAGE_ROOT / "core" / "engine.py",
        line=node.lineno,
        source_layer="core",
        target=node.module or "",
    )

    assert reference.target_layer == "geo"
    assert RANK[reference.target_layer] > RANK[reference.source_layer]
    assert "core/engine.py:1 imports roadrisk.geo.pipeline" in str(reference).replace(
        "\\", "/"
    )
