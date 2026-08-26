"""Step 5.1b — the storage commands.

A separate module from `cli.py`, which is already 1,900 lines, and separate for a
reason beyond size: everything here needs a database, and nothing else in the package
does. Keeping it apart means `roadrisk assess` and `roadrisk corridor` never import
psycopg, and a machine without the `store` extra still runs the whole assessment path.

The done-when for this step lives in `roadrisk store show --report`: a run written by
the CLI, imported, and rendered back into a report without refitting anything. Nothing
in that path constructs an engine object.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

import typer
from rich.console import Console
from rich.table import Table

from roadrisk.report import REPORT_FILENAME, render_report
from roadrisk.store import (
    Artefact,
    ArtefactKind,
    NotFound,
    PayloadRejected,
    Project,
    StoreError,
    Tenant,
)
from roadrisk.store.postgres import DSN_ENV

# Rich assumes an 80-column terminal when stdout is not a TTY, and then shrinks columns
# to fit — which puts an ellipsis through the middle of a run id. Every other command
# here takes that id as an argument, so an elided one cannot be copied and cannot be
# piped, and the listing stops being something you can act on. Redirected output is
# given room instead; interactive output still follows the real terminal.
console = Console(width=None if sys.stdout.isatty() else 200)

store_app = typer.Typer(
    name="store",
    help=(
        "Keep runs in Postgres so they outlive the process that made them. "
        # Backslash-escaped for Rich, which reads `[store]` as a markup tag, finds no
        # such style, and drops it — printing an install command with the extra it
        # exists to name removed from it.
        f"Needs ${DSN_ENV} and `pip install \"roadrisk-panel\\[store]\"`."
    ),
    no_args_is_help=True,
)

EXIT_REJECTED = 2
EXIT_UNAVAILABLE = 3


def _open_store() -> Any:
    """Connect, or say what is missing rather than raising an import error at them."""
    dsn = os.environ.get(DSN_ENV)
    if not dsn:
        console.print(
            f"[red]${DSN_ENV} is not set.[/red] It should be a Postgres connection "
            "string — for a local socket that is [bold]postgresql:///roadrisk[/bold]."
        )
        raise typer.Exit(EXIT_UNAVAILABLE)
    try:
        from roadrisk.store.postgres import PostgresStore
    except ImportError as exc:  # pragma: no cover - depends on install shape
        console.print(
            "[red]The store extra is not installed.[/red] "
            'Run: pip install "roadrisk-panel\\[store]"'
        )
        raise typer.Exit(EXIT_UNAVAILABLE) from exc
    try:
        return PostgresStore.connect(dsn)
    except Exception as exc:
        console.print(f"[red]Cannot reach the database:[/red] {exc}")
        raise typer.Exit(EXIT_UNAVAILABLE) from exc


def _uuid(raw: str, what: str) -> UUID:
    """Parse an id, or say which one was wrong.

    Unguarded, `UUID(...)` raises `ValueError` and typer prints a traceback — which
    tells a user reading it nothing about which of the three ids they passed was
    malformed, and looks like a crash rather than a rejected argument.
    """
    try:
        return UUID(raw)
    except ValueError as exc:
        console.print(f"[red]{what} is not a UUID:[/red] {raw!r}")
        raise typer.Exit(EXIT_REJECTED) from exc


def _tenant_id(value: str | None) -> UUID:
    raw = value or os.environ.get("ROADRISK_TENANT")
    if not raw:
        console.print(
            "[red]No tenant.[/red] Pass --tenant, or set $ROADRISK_TENANT. "
            "Every read is scoped to one — there is no way to ask for all of them."
        )
        raise typer.Exit(EXIT_REJECTED)
    return _uuid(raw, "--tenant")


@store_app.command("init")
def init() -> None:
    """Create the schema, or bring it up to date. Safe to run twice."""
    store = _open_store()
    try:
        applied = store.migrate()
    except StoreError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(EXIT_REJECTED) from exc
    if applied:
        console.print(f"[green]Applied migration(s):[/green] {', '.join(applied)}")
    else:
        console.print("Schema is already up to date.")
    store.close()


@store_app.command("new-tenant")
def new_tenant(
    name: Annotated[str, typer.Argument(help="A label for whoever owns these runs.")],
) -> None:
    """Create a tenant and print its id. Everything else is scoped to one of these."""
    store = _open_store()
    tenant = store.create_tenant(Tenant(name=name))
    console.print(f"[green]tenant[/green] {tenant.id}  {tenant.name}")
    console.print(f"Set it once with: export ROADRISK_TENANT={tenant.id}")
    store.close()


@store_app.command("new-project")
def new_project(
    name: Annotated[str, typer.Argument(help="Project name.")],
    tenant: Annotated[str | None, typer.Option("--tenant")] = None,
) -> None:
    """Create a project to file runs under."""
    store = _open_store()
    project = store.create_project(Project(tenant_id=_tenant_id(tenant), name=name))
    console.print(f"[green]project[/green] {project.id}  {project.name}")
    store.close()


@store_app.command("import")
def import_run(
    path: Annotated[
        Path,
        typer.Argument(
            help="A run.json written by `roadrisk corridor --out` or `--report`."
        ),
    ],
    project: Annotated[str, typer.Option("--project", help="Project id to file under.")],
    tenant: Annotated[str | None, typer.Option("--tenant")] = None,
    with_artefacts: Annotated[
        bool,
        typer.Option(
            "--artefacts/--no-artefacts",
            help=(
                "Record the report and PDF sitting beside run.json, by reference. "
                "The files are not copied and their bytes never enter the database."
            ),
        ),
    ] = True,
) -> None:
    """Store a run written by the CLI.

    The payload is validated against the contract on the way in: a run that does not
    conform is refused here rather than kept in a shape nothing can read back.
    """
    store = _open_store()
    tenant_id = _tenant_id(tenant)

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        console.print(f"[red]Cannot read {path}:[/red] {exc}")
        raise typer.Exit(EXIT_REJECTED) from exc
    except json.JSONDecodeError as exc:
        console.print(f"[red]{path} is not valid JSON:[/red] {exc}")
        raise typer.Exit(EXIT_REJECTED) from exc

    try:
        run = store.store_run(tenant_id, _uuid(project, "--project"), payload)
    except PayloadRejected as exc:
        console.print(f"[red]Refused:[/red] {exc}")
        raise typer.Exit(EXIT_REJECTED) from exc
    except NotFound as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(EXIT_REJECTED) from exc

    console.print(
        f"[green]run[/green] {run.id}  mode {run.mode} · rung {run.rung} · "
        f"engine {run.engine_version} · fingerprint {run.fingerprint}"
    )

    if with_artefacts:
        for kind in ArtefactKind:
            beside = path.parent / kind.value
            if not beside.exists() or beside.resolve() == path.resolve():
                continue
            store.add_artefact(
                Artefact(
                    tenant_id=tenant_id,
                    run_id=run.id,
                    kind=kind,
                    uri=beside.resolve().as_uri(),
                    size_bytes=beside.stat().st_size,
                    sha256=_sha256(beside),
                )
            )
            console.print(f"  artefact {kind.value} → {beside}")

    store.close()


@store_app.command("list")
def list_runs(
    tenant: Annotated[str | None, typer.Option("--tenant")] = None,
    project: Annotated[str | None, typer.Option("--project")] = None,
    limit: Annotated[int, typer.Option("--limit")] = 20,
) -> None:
    """Recent runs, newest first. Drawn from the indexed columns, not the payloads."""
    store = _open_store()
    runs = store.list_runs(
        _tenant_id(tenant), _uuid(project, "--project") if project else None, limit=limit
    )
    if not runs:
        console.print("No runs.")
        store.close()
        return

    # The run id must never be elided. It is the argument to every other command here,
    # so an id that arrives with an ellipsis in the middle cannot be copied and cannot
    # be piped — the listing becomes something to look at rather than something to act
    # on. `no_wrap` plus an explicit width keeps it whole at any terminal size.
    #
    # The fingerprint is the opposite case and is abbreviated deliberately: it is for
    # recognising that two runs are the same, which twelve characters does, and nothing
    # takes it as an argument.
    table = Table(box=None, pad_edge=False)
    table.add_column("run", no_wrap=True, width=36)
    for column in ("mode", "rung", "engine"):
        table.add_column(column, no_wrap=True)
    table.add_column("fingerprint", no_wrap=True)
    table.add_column("stored", no_wrap=True)
    for run in runs:
        table.add_row(
            str(run.id),
            run.mode,
            run.rung,
            run.engine_version,
            run.fingerprint[:12],
            run.created_at.strftime("%Y-%m-%d %H:%M") if run.created_at else "—",
        )
    console.print(table)
    store.close()


@store_app.command("show")
def show_run(
    run_id: Annotated[str, typer.Argument(help="Run id.")],
    tenant: Annotated[str | None, typer.Option("--tenant")] = None,
    report: Annotated[
        Path | None,
        typer.Option(
            "--report",
            help="Re-render the stored run to a report here. No refit happens.",
        ),
    ] = None,
) -> None:
    """Read a stored run back, and optionally render it.

    This is step 5.1b's done-when. Nothing is fitted: the payload comes out of the
    database and goes straight into the same renderer a client's report came from,
    which is only possible because the payload — not an engine object — is what was
    stored.
    """
    store = _open_store()
    try:
        run = store.get_run(_tenant_id(tenant), _uuid(run_id, "run id"))
    except NotFound as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(EXIT_REJECTED) from exc

    console.print(
        f"[bold]{run.id}[/bold]  mode {run.mode} · rung {run.rung} · "
        f"engine {run.engine_version} · schema {run.schema_version or '—'}"
    )
    console.print(f"fingerprint {run.fingerprint}")

    artefacts = store.list_artefacts(run.tenant_id, run.id)
    for artefact in artefacts:
        console.print(f"  {artefact.kind.value}  {artefact.size_bytes:,} bytes  {artefact.uri}")

    if report is not None:
        target = report if report.suffix.lower() == ".html" else report / REPORT_FILENAME
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_report(run.payload), encoding="utf-8")
        console.print(f"[green]Report:[/green] {target}  (rendered, not refitted)")

    store.close()


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()
