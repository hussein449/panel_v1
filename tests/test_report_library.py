"""Step 5.3a — the report is a library, and the entry points render none of it.

The deliverable is a split: `<Report run={run} />` on one side, two thin entry points on
the other. The done-when is that *the app renders the same component tree* as the
single-file bundle — and the way that is made true here is by construction rather than by
comparison. **There is one `Report`.** Both entries import it, neither has any part of the
report inside it, and so there is no second tree for the first one to differ from.

That property is exactly the kind that holds on the day it is written and quietly stops
holding four steps later, when somebody needs one extra heading on the web page and adds
it to the entry point because that is where they happen to be. So it is asserted, the same
way `tests/test_layering.py` asserts the Python layering rather than trusting the
docstring that had described it for five stages.

**Why this is a Python test over TypeScript sources.** Node is not installed in the
environment this suite runs in — the JavaScript toolchain lives on the Windows side, and
`web/node_modules` only exists there. A test that needed `npm` would not run, which means
it would not be run. Parsing the imports is enough for what is being claimed: this is a
question about which module owns which code, not about what React does with it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "web" / "src"
LIBRARY = WEB / "report"
ENTRIES = WEB / "entries"

#: An import of something inside the report library, from anywhere.
IMPORT_FROM = re.compile(r"""from\s+["']([^"']+)["']""")

#: A JSX element with a capitalised name — a component being *rendered*.
#:
#: The lookbehind is what separates `<Report run={run} />` from `useState<Run | null>`:
#: a type parameter always follows an identifier, and a JSX tag never does. Without it
#: this matches every generic in the file and reports `Run` as a component.
COMPONENT_TAG = re.compile(r"(?<![A-Za-z0-9_])<([A-Z][A-Za-z0-9_]*)")

#: What an entry point is allowed to put on the page.
#:
#: `Report` and `Boundary` come out of the library. `StrictMode` is React's own and
#: renders nothing. `Loader` is the standalone bundle's file picker, which is not part of
#: any report — it is what the page shows when it has no run to draw, and it belongs to
#: the surface that can be opened with nothing in it.
ENTRY_MAY_RENDER = frozenset({"Report", "Boundary", "StrictMode", "App", "Loader"})


def sources(directory: Path) -> dict[Path, str]:
    return {
        path: path.read_text(encoding="utf-8")
        for path in sorted(directory.rglob("*.ts*"))
    }


def test_the_library_and_the_entries_both_exist() -> None:
    """A rename that flattened this back would otherwise make every test below vacuous."""
    assert (LIBRARY / "Report.tsx").is_file()
    assert (LIBRARY / "index.ts").is_file()
    assert (ENTRIES / "standalone.tsx").is_file()
    assert (ENTRIES / "mount.tsx").is_file()


def test_there_is_exactly_one_report_component() -> None:
    """The whole basis of "the app renders the same component tree".

    Two `Report`s kept in visual sync by hand is precisely what step 4.3 refused when it
    put the renderer in the UI rather than writing a separate print template, and it is
    what an app tab would quietly reintroduce.
    """
    defining = [
        path
        for path, text in sources(WEB).items()
        if re.search(r"export default function Report\b", text)
    ]
    assert defining == [LIBRARY / "Report.tsx"], (
        f"Expected one Report component, in the library. Found: {defining}"
    )


@pytest.mark.parametrize("entry", ["standalone.tsx", "mount.tsx"])
def test_an_entry_point_renders_nothing_of_the_report(entry: str) -> None:
    """An entry decides where the run comes from and where the tree is mounted.

    Not what is in it. The moment an entry renders a section, a figure or a heading of
    its own, the two surfaces have started to differ and nothing else would notice —
    the bundle and the app would simply drift, one heading at a time.
    """
    text = (ENTRIES / entry).read_text(encoding="utf-8")

    rendered = {name for name in COMPONENT_TAG.findall(text)}
    unexpected = sorted(rendered - ENTRY_MAY_RENDER)

    assert not unexpected, (
        f"{entry} renders {unexpected}, which belongs in web/src/report/. An entry "
        "point supplies a run and a mount point; everything drawn comes from the "
        "library, or the two surfaces will not stay the same report."
    )


@pytest.mark.parametrize("entry", ["standalone.tsx", "mount.tsx"])
def test_an_entry_point_reaches_the_report_only_through_its_public_surface(
    entry: str,
) -> None:
    """`../report`, never `../report/sections` or `../report/figures`.

    An entry that reached inside would be depending on the library's arrangement rather
    than on what it exports, and moving a section between files would break a surface
    that has no business knowing where sections live.
    """
    text = (ENTRIES / entry).read_text(encoding="utf-8")
    reaching = [
        target
        for target in IMPORT_FROM.findall(text)
        if target.startswith("../report/") or target.startswith("./report/")
    ]
    assert not reaching, f"{entry} imports past the library's surface: {reaching}"


def test_the_library_never_imports_an_entry_point() -> None:
    """Downhill only, exactly as `core` may not import `cli`.

    A library that reached back into an entry would be a library that only works in the
    page it was written for, and the second surface would be the one to find out.
    """
    reaching = [
        f"{path.relative_to(WEB)} imports {target}"
        for path, text in sources(LIBRARY).items()
        for target in IMPORT_FROM.findall(text)
        if "entries" in target
    ]
    assert not reaching, "The report library reached into an entry point:\n  " + "\n  ".join(
        reaching
    )


def test_the_library_holds_the_error_boundary() -> None:
    """Both entries need it, and for the same reason.

    While there was one entry the boundary could sit beside the mounting code without
    anybody noticing the difference. With two, leaving it there means either writing it
    twice or shipping one surface that fails silently to a blank page — which is the
    exact failure it was written to prevent.
    """
    assert (LIBRARY / "Boundary.tsx").is_file()
    for entry in ("standalone.tsx", "mount.tsx"):
        text = (ENTRIES / entry).read_text(encoding="utf-8")
        assert "Boundary" in text, f"{entry} mounts the report without a boundary"
        assert "class Boundary" not in text, f"{entry} has its own copy of the boundary"


def test_the_single_file_bundle_still_points_at_the_standalone_entry() -> None:
    """The `file://` half of the done-when, as far as a Python test can see it.

    `index.html` is what the single-file build compiles. If it still referenced the old
    `main.tsx` the build would fail loudly, but if it referenced `mount.tsx` it would
    succeed and produce a page that mounts nothing — a report that opens to white.
    """
    html = (WEB.parent / "index.html").read_text(encoding="utf-8")
    assert "/src/entries/standalone.tsx" in html
    assert "main.tsx" not in html


def test_the_shipped_bundle_is_not_left_behind_by_the_split() -> None:
    """The committed `report.html` is what `pip install` ships and what tests render.

    It is a build artefact of these sources, and the JavaScript toolchain that rebuilds
    it does not run in this environment — so the one thing a Python test can check is
    that the file is present and is a real report rather than an empty shell.
    """
    bundle = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "roadrisk"
        / "report"
        / "static"
        / "index.html"
    )
    text = bundle.read_text(encoding="utf-8")

    assert len(text) > 100_000, "the shipped bundle looks empty"
    assert 'id="roadrisk-run"' in text, "the bundle has nowhere to put a run"
    assert "createRoot" in text, "the bundle does not mount anything"
