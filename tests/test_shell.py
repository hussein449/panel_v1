"""Step 5.3b — the banner is a layout element, and no route can omit it.

The deliverable is a website around the report: routes, one layout, and two banners that
are not the same fact. The done-when is that **the mode banner is unmissable on every
screen**, and the way that is made true is structural rather than diligent — a page is a
child of the layout, and a child cannot remove its parent.

That property is exactly the kind that holds on the day it is written and quietly stops
holding when somebody adds the twelfth route, which is the one it will be missing from.
So it is asserted here, the same way `tests/test_layering.py` asserts the Python layering
and `tests/test_report_library.py` asserts the report is imported rather than copied.

**Two banners, two different facts, and both are checked.**

* The **deployment** banner, in the root layout: what this service is — that the tenant
  header is not authentication, that jobs run inside the API process and do not survive a
  restart. Every screen.
* The **mode** banner, in the run segment's layout: which mode produced the numbers on
  screens about a run. Every screen about a run, including the ones 5.3c and 5.3d add.

**Why a Python test over TypeScript sources.** The same reason 5.3a gives: these are
questions about which module owns which code, and answering them by parsing is worth more
than a JavaScript test suite that would need a Node environment this suite cannot assume.
What parsing cannot see — that the banner is in the HTML a browser is actually served —
is checked by `tools/check_shell.py` against a running shell, and neither replaces the
other.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[1]
SHELL = REPO / "web" / "shell"
APP = SHELL / "app"
WIRE_TS = SHELL / "lib" / "wire.ts"
GENERATOR = REPO / "tools" / "generate_types.py"

#: Directories that are build output or downloaded code, not source.
IGNORED = {"node_modules", ".next"}

#: A JSX element with a capitalised name — a component being *rendered*. The lookbehind
#: separates `<Report run={run} />` from `useState<Run | null>`; see 5.3a's test, where
#: the missing version of it reported a type parameter as a component.
COMPONENT_TAG = re.compile(r"(?<![A-Za-z0-9_])<([A-Z][A-Za-z0-9_]*)")

IMPORT_FROM = re.compile(r"""from\s+["']([^"']+)["']""")


def sources(root: Path) -> dict[Path, str]:
    """Every TypeScript source under `root`, excluding build output."""
    return {
        path: path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*.ts*"))
        if not IGNORED.intersection(path.parts)
    }


def pages() -> list[Path]:
    return [
        path
        for path in sorted(APP.rglob("page.tsx"))
        if not IGNORED.intersection(path.parts)
    ]


def test_the_shell_exists() -> None:
    """A rename that moved these would otherwise make every test below vacuous."""
    assert (APP / "layout.tsx").is_file(), "there is no root layout"
    assert (SHELL / "next.config.mjs").is_file()
    assert (SHELL / "components" / "DeploymentBanner.tsx").is_file()
    assert pages(), "the app has no routes at all"


def test_there_is_exactly_one_root_layout() -> None:
    """Two root layouts is two banners to keep in step, and eventually one that is not.

    A root layout is the file that renders `<html>`. Next allows a second one under a
    route group, which is a perfectly ordinary thing to reach for when a route wants
    different chrome — and it would take that route out from under this banner without
    anything else changing.
    """
    roots = [
        path.relative_to(SHELL)
        for path, text in sources(SHELL).items()
        if "<html" in text
    ]
    assert roots == [Path("app/layout.tsx")], (
        f"Expected exactly one root layout, at app/layout.tsx. Found: {roots}"
    )


def test_the_root_layout_renders_the_banner_unconditionally() -> None:
    """No `&&`, no ternary, and before the page.

    A banner behind a condition is a banner that is absent in whichever case nobody
    thought about — and the cases here are precisely the ones where it matters most: no
    tenant configured, the API unreachable, health throwing. `DeploymentBanner` handles
    all three by *changing what it says*, which is why it must never be the thing that is
    skipped.
    """
    text = (APP / "layout.tsx").read_text(encoding="utf-8")

    rendered = [line for line in text.splitlines() if "<DeploymentBanner" in line]
    assert len(rendered) == 1, f"expected one <DeploymentBanner />, found {rendered}"

    line = rendered[0]
    for token in ("&&", "?", ":"):
        assert token not in line, (
            f"the banner is rendered conditionally: {line.strip()!r}. It must change "
            "what it says, never whether it is there."
        )

    assert text.index("<DeploymentBanner") < text.index("{children}"), (
        "the banner is rendered after the page. It is the first thing on the screen."
    )


def test_the_banner_never_renders_nothing() -> None:
    """The other half of the rule above, one level in.

    An unconditional `<DeploymentBanner />` whose component returns null on the path
    nobody tested is the same absence with more steps.
    """
    text = (SHELL / "components" / "DeploymentBanner.tsx").read_text(encoding="utf-8")
    assert "return null" not in text, "the banner has a path that renders nothing"


def test_only_the_layout_knows_about_the_banner() -> None:
    """If a page can include it, a page can forget it.

    The failure this prevents is not somebody deleting the banner. It is the banner
    becoming each page's responsibility — at which point it is on eleven screens and
    missing from the twelfth, and nothing says so.
    """
    importers = [
        path.relative_to(SHELL)
        for path, text in sources(SHELL).items()
        if "DeploymentBanner" in text and path.name != "DeploymentBanner.tsx"
    ]
    assert importers == [Path("app/layout.tsx")], (
        f"The banner is referenced outside the root layout: {importers}"
    )


def test_there_is_no_pages_directory() -> None:
    """The one way to serve a route that the App Router's layout never wraps.

    A `pages/` directory is not an error in Next — it is the older router, it works, and
    a route in it is rendered without any of this app's layouts. It is the single
    cleanest way to add a screen with no banner on it without touching a line of what is
    tested above.
    """
    assert not (SHELL / "pages").exists(), (
        "web/shell/pages/ exists. The Pages Router bypasses app/layout.tsx entirely, "
        "so a route in there would have no banner."
    )


def test_every_screen_is_under_the_root_layout() -> None:
    """Every route file is in `app/`, and therefore inside `app/layout.tsx`."""
    for page in pages():
        assert APP in page.parents, f"{page} is a route outside app/"


def test_every_screen_about_a_run_states_the_mode() -> None:
    """The mode banner is the run segment's layout, not each run page's job.

    A run already has more than one screen — the report and the files it wrote — and
    5.3c adds a map, 5.3d a detail layer. Each is a child of this layout, so each states
    which mode produced what it is showing. This is the deployment banner's argument one
    level down.
    """
    run_layout = APP / "runs" / "[runId]" / "layout.tsx"
    assert run_layout.is_file(), "the run segment has no layout"

    text = run_layout.read_text(encoding="utf-8")
    assert "<RunModeBanner" in text, "the run layout does not state the mode"
    assert text.index("<RunModeBanner") < text.index("{children}")

    under_runs = [page for page in pages() if run_layout.parent in page.parents]
    assert under_runs, "no screens under the run layout"
    for page in under_runs:
        assert "<RunModeBanner" not in page.read_text(encoding="utf-8"), (
            f"{page.relative_to(SHELL)} renders the mode banner itself. It belongs to "
            "the layout, or the next screen added here will be the one without it."
        )


def test_the_shell_does_not_define_a_second_report() -> None:
    """The other half of 5.3a's claim, now that there is an app to break it in.

    `tests/test_report_library.py` asserts there is one `Report` in `web/src`. It cannot
    see this app, and this app is exactly where a second one would appear — somebody
    needing one more heading on the web page and adding it where they happen to be.
    """
    defining = [
        path.relative_to(SHELL)
        for path, text in sources(SHELL).items()
        if re.search(r"function Report\b|const Report\b", text)
    ]
    assert not defining, f"The shell defines its own report: {defining}"


def test_the_shell_renders_no_part_of_the_report() -> None:
    """One component, imported. Not a page that draws some of it and mounts the rest.

    `ReportView` is this app's entry point in the sense 5.3a means: it supplies a run and
    a mount point, and everything drawn comes from the library. The moment it renders a
    section or a heading of its own, the page and the file that gets emailed have started
    to differ and nothing else would notice.
    """
    view = SHELL / "components" / "ReportView.tsx"
    text = view.read_text(encoding="utf-8")
    rendered = set(COMPONENT_TAG.findall(text))
    assert rendered <= {"Report", "Boundary"}, (
        f"ReportView renders {sorted(rendered)}; only the library's Report and its "
        "Boundary belong there."
    )
    assert "Boundary" in text, "the report is mounted without an error boundary"


def test_the_shell_reaches_the_report_only_through_its_package_surface() -> None:
    """`roadrisk-report`, never a relative path into `web/src/report/sections`.

    The library's arrangement is its own business. An app that reached inside it would
    break when a section moved between files, and would be depending on something the
    package never promised.
    """
    reaching = [
        f"{path.relative_to(SHELL)} imports {target}"
        for path, text in sources(SHELL).items()
        for target in IMPORT_FROM.findall(text)
        if "src/report" in target or "src/entries" in target
    ]
    assert not reaching, "The shell reached into the report library:\n  " + "\n  ".join(
        reaching
    )


def test_the_report_library_never_imports_the_shell() -> None:
    """Downhill only, exactly as `core` may not import `cli`.

    A library that reached into the app it happens to be rendered by would stop being a
    library — and the single-file bundle, which has no app around it, would be the
    surface that found out.
    """
    library = REPO / "web" / "src"
    reaching = [
        f"{path.relative_to(library)} imports {target}"
        for path, text in sources(library).items()
        for target in IMPORT_FROM.findall(text)
        if "shell" in target
    ]
    assert not reaching, "The report library reached into the shell:\n  " + "\n  ".join(
        reaching
    )


#: The header being *sent* — quoted, as a key — rather than named in prose. Several
#: screens tell the reader that this header is not a credential, which is the opposite
#: of the thing being guarded against.
SENDS_TENANT = re.compile(r'"X-Tenant-Id"')


def test_one_module_sends_the_tenant_header() -> None:
    """The seam step 5.4a replaces, kept to one file while it is still a placeholder.

    `X-Tenant-Id` scopes rows and proves nothing. When it becomes a real identity there
    has to be one place that changes — and a header pasted into three fetches is three
    places, one of which will keep sending the environment's tenant long after there are
    sessions.
    """
    setting = [
        path.relative_to(SHELL)
        for path, text in sources(SHELL).items()
        if SENDS_TENANT.search(text)
    ]
    assert setting == [Path("lib/api.ts")], (
        f"The tenant header is set in more than one place: {setting}"
    )


#: What counts as a source file in the shell. Deliberately not everything — the build
#: writes a `tsconfig.tsbuildinfo` beside these, and that one *is* meant to be ignored.
SOURCE_SUFFIXES = {".ts", ".tsx", ".css", ".mjs", ".json"}


def test_no_shell_source_is_hidden_from_git() -> None:
    """Written because it happened: `runs/` in `.gitignore` swallowed the run segment.

    That pattern was written for output directories and matches a folder of that name at
    any depth — including `web/shell/app/runs/`, which holds the layout carrying the mode
    banner. Everything built, every test passed, the fetch check found the banner on all
    eleven screens, and the files would simply not have been in the commit.

    Nothing fails when this happens. It is caught by reading `git status` carefully, which
    is not a mechanism.
    """
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not on PATH, so what it ignores cannot be asked")

    paths = [
        path
        for path in sorted(SHELL.rglob("*"))
        if path.is_file()
        and path.suffix in SOURCE_SUFFIXES
        and not IGNORED.intersection(path.parts)
    ]
    assert paths, "no shell sources found at all"

    # `check-ignore --stdin` exits 1 when nothing is ignored, which is the good case, so
    # the return code is not the answer — the output is.
    result = subprocess.run(
        [git, "check-ignore", "--stdin"],
        input="\n".join(str(path) for path in paths),
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    hidden = [line for line in result.stdout.splitlines() if line.strip()]
    assert not hidden, "These shell sources are ignored by git:\n  " + "\n  ".join(hidden)


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


def test_the_committed_wire_types_are_what_the_api_generates() -> None:
    """`web/shell/lib/wire.ts` is generated, for the reason 5.1a gives about the payload.

    A hand-written `Job` in this app is the step 4.7 defect one layer out: `JobStatus`
    grows a sixth value, the shell knows five, and a job in the new state renders as
    nothing at all under a heading that looks fine.
    """
    pytest.importorskip("fastapi", reason="the wire types come from the API models")
    generated = _load_generator().render_wire()
    assert WIRE_TS.read_text(encoding="utf-8") == generated, (
        "web/shell/lib/wire.ts no longer matches the API and store models.\n"
        "Run: python tools/generate_types.py"
    )


def test_the_generated_wire_types_say_they_are_generated() -> None:
    """A generated file that does not announce itself gets hand-edited exactly once."""
    header = WIRE_TS.read_text(encoding="utf-8")[:1200]
    assert "GENERATED FILE" in header
    assert "tools/generate_types.py" in header
