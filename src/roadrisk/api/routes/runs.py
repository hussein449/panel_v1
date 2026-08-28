"""Runs, and the files that belong to them.

**A finished run is a 200 whatever it concluded.** A descent to Mode B, a dropped term,
a refused weight, a validation gate that failed — every one of those is content the run
carries, and none of them is an HTTP error. This is the row of the refusal contract that
is easiest to get wrong, because a REST instinct reads "the engine refused" and reaches
for 4xx. The engine refusing *is the assessment*.

**Artefact download is a file-read primitive, and is treated as one.** The database
holds a `file://` URI written by whatever put the artefact there — the CLI today, a
worker at 5.2a. Serving it means opening a path that came out of a column. So there is
an allow-list root, there is no default, and with none configured every download is
refused. The failure mode of the safe default is a 409 naming an environment variable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import FileResponse

from roadrisk.api.deps import SettingsDep, StoreDep, TenantId
from roadrisk.api.errors import HTTP_422, REFUSAL_RESPONSES, ApiRefusal, ErrorCode
from roadrisk.api.schemas import ArtefactOut, RunSummary
from roadrisk.api.settings import ARTEFACT_ROOT_ENV, ApiSettings
from roadrisk.store import Artefact, ArtefactKind, Run

router = APIRouter(tags=["runs"], responses=REFUSAL_RESPONSES)

#: What each artefact is served as. Written out rather than guessed from the extension,
#: because the extension is part of a URI written by something else — a worker at 5.2a,
#: an object store at 6.2 — and a `.csv` arriving without one would be served as
#: `application/octet-stream` to a client that had asked for a ranking.
#:
#: Everything here goes out as an attachment rather than inline, and `report.html` is
#: the reason. Serving HTML inline from this origin means the browser executes it here;
#: the bytes are a file on a disk this service does not own the write path to, and a
#: report is a document to save rather than a page to visit. 5.3b serves the report as
#: an application, from a component, which is a different thing entirely.
MEDIA_TYPES: dict[ArtefactKind, str] = {
    ArtefactKind.REPORT_HTML: "text/html; charset=utf-8",
    ArtefactKind.REPORT_PDF: "application/pdf",
    ArtefactKind.RUN_JSON: "application/json",
    ArtefactKind.RANKING_CSV: "text/csv; charset=utf-8",
}


@router.get(
    "/runs",
    response_model=list[RunSummary],
    summary="Finished runs, newest first, without their payloads",
)
def list_runs(
    tenant_id: TenantId,
    store: StoreDep,
    settings: SettingsDep,
    project_id: Annotated[
        UUID | None,
        Query(description="Narrow to one project. Omitted lists every project."),
    ] = None,
    limit: Annotated[int | None, Query(ge=1)] = None,
    bbox: Annotated[
        str | None,
        Query(
            description=(
                "Keep only runs whose road overlaps this box: `south,west,north,east` "
                "in degrees. **A run with no geometry never matches** — a panel you "
                "supplied directly has rows and no road, and that is a reason to miss "
                "it rather than to match everything."
            ),
            examples=["34.89,33.20,34.91,33.31"],
        ),
    ] = None,
) -> list[RunSummary]:
    """Summaries, not payloads.

    A run is around 300 kB of JSON. Fifty of them is fifteen megabytes, which is not a
    listing — it is a download nobody asked for. Every field in a summary was lifted out
    of the payload by the store on insert, so a summary cannot describe a different run
    than the one it points at.

    **`bbox` is step 2.9's other half.** The geometry has been stored since 5.1b; what
    had no query behind it was finding a run by *where it is*. The extent is four numbers
    lifted from the centreline, so this is four comparisons rather than a geometry type —
    `migrations/0003_run_extent.sql` says why that is a decision and not a shortcut.
    """
    capped = min(limit or settings.default_page_size, settings.max_page_size)
    runs = store.list_runs(tenant_id, project_id, limit=capped, within=_box(bbox))
    return [RunSummary.of(run) for run in runs]


def _box(raw: str | None) -> tuple[float, float, float, float] | None:
    """`"south,west,north,east"` as four floats, or a refusal naming what was wrong.

    Refused here rather than passed on, for the reason `CorridorBody` refuses an inverted
    box at submit: a box the wrong way up matches nothing and reports no error, which is
    the worst way available for a filter to fail.
    """
    if raw is None:
        return None

    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 4:
        raise ApiRefusal(
            HTTP_422,
            ErrorCode.INVALID_REQUEST,
            "bbox must be four numbers, 'south,west,north,east' in degrees. Got "
            f"{len(parts)}: {raw!r}.",
            field="bbox",
        )

    try:
        south, west, north, east = (float(part) for part in parts)
    except ValueError:
        raise ApiRefusal(
            HTTP_422,
            ErrorCode.INVALID_REQUEST,
            f"bbox must be four numbers in degrees, got {raw!r}.",
            field="bbox",
        ) from None

    if not (-90.0 <= south <= 90.0 and -90.0 <= north <= 90.0):
        raise ApiRefusal(
            HTTP_422,
            ErrorCode.INVALID_REQUEST,
            "bbox latitudes must be between -90 and 90 (south, north).",
            field="bbox",
        )
    if not (-180.0 <= west <= 180.0 and -180.0 <= east <= 180.0):
        raise ApiRefusal(
            HTTP_422,
            ErrorCode.INVALID_REQUEST,
            "bbox longitudes must be between -180 and 180 (west, east).",
            field="bbox",
        )
    if south > north or west > east:
        raise ApiRefusal(
            HTTP_422,
            ErrorCode.INVALID_REQUEST,
            f"bbox is inside out: south ({south}) must not be above north ({north}), "
            f"and west ({west}) must not be right of east ({east}). A box crossing the "
            "antimeridian has to be asked for as two.",
            field="bbox",
        )

    return (south, west, north, east)


@router.get(
    "/runs/{run_id}",
    response_model=Run,
    summary="One run, whole — including everything it refused to conclude",
)
def get_run(run_id: UUID, tenant_id: TenantId, store: StoreDep) -> Run:
    """Return the run and its payload.

    **200 whatever the assessment concluded.** A run that descended to Mode B carries
    its descent receipt, the terms it dropped and the weights it would not score, and
    all of that is inside `payload`. Turning any of it into a status code would move
    the honesty layer into an error handler, which is where nobody reads it.

    The payload is not re-validated on the way out. `store_run` validated it on the way
    in and there is nowhere for it to have changed since — validating again would be a
    second answer to a question already answered, and the two could disagree.
    """
    return store.get_run(tenant_id, run_id)


@router.get(
    "/runs/{run_id}/report.html",
    summary="The report for this run, rendered on demand",
    response_class=Response,
    responses={
        200: {
            "description": "One self-contained HTML document, served as an attachment.",
            "content": {"text/html": {}},
        },
        501: {"description": "This build ships no compiled report page."},
    },
)
def render_run_report(run_id: UUID, tenant_id: TenantId, store: StoreDep) -> Response:
    """Put the stored payload inside the compiled page and hand back the document.

    **Rendered, never stored.** A run assessed by this service writes no files — it is a
    payload, and `list_artefacts` returns nothing for it. That is a deliberate property
    rather than a gap: a payload re-renders months later under a report page that has
    since been improved, and a stored HTML file would freeze the page a run was made
    with. So the way to download a report is to build it now, from the run, with the
    renderer the CLI and the website both already use.

    It is therefore *not* an artefact and is not served through the artefact path: there
    is no URI, no disk, no `$ROADRISK_ARTEFACT_ROOT` and no allow-list to check, because
    nothing here opens a file whose path came out of a column. The one thing it shares
    with that path is `Content-Disposition: attachment` — this is a document to save,
    and serving HTML inline would mean this origin executing it.
    """
    run = store.get_run(tenant_id, run_id)

    # Imported here, not at module scope. `roadrisk.report` reads the compiled page off
    # disk at call time, and a build that shipped without it should fail this request
    # with a cause rather than fail to import the whole API.
    from roadrisk.report import ReportTemplateError, render_report

    try:
        document = render_report(run.payload)
    except ReportTemplateError as exc:
        raise ApiRefusal(
            status.HTTP_501_NOT_IMPLEMENTED,
            ErrorCode.UNSUPPORTED,
            f"This build cannot render a report: {exc}. The page is compiled from "
            "web/src/report by `npm run build` and committed with the package.",
        ) from exc

    return Response(
        content=document,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="report-{run_id}.html"'
        },
    )


@router.get(
    "/runs/{run_id}/artefacts",
    response_model=list[ArtefactOut],
    summary="The files this run produced",
)
def list_artefacts(
    run_id: UUID, tenant_id: TenantId, store: StoreDep
) -> list[ArtefactOut]:
    """List them with a URL, never with the path they sit at on this server."""
    return [_artefact_out(artefact) for artefact in store.list_artefacts(tenant_id, run_id)]


@router.get(
    "/runs/{run_id}/artefacts/{kind}",
    summary="Download one artefact",
    response_class=FileResponse,
    responses={
        200: {"description": "The bytes. `ETag` is the sha256 recorded at import."},
        409: {
            "description": "Recorded, but this server will not or cannot serve it — "
            "no artefact root configured, outside it, missing, or changed since."
        },
        501: {"description": "Stored somewhere this build cannot fetch from."},
    },
)
def download_artefact(
    run_id: UUID,
    kind: ArtefactKind,
    tenant_id: TenantId,
    store: StoreDep,
    settings: SettingsDep,
) -> FileResponse:
    """Serve the file, having proved it is one this server is allowed to open.

    The `ETag` is the sha256 the store recorded, so a client can verify what arrived
    against what was registered without this route re-hashing a third of a megabyte on
    every request. The size *is* checked, because `stat` is free and a file whose length
    no longer matches the record is not the artefact the record describes.
    """
    artefacts = {a.kind: a for a in store.list_artefacts(tenant_id, run_id)}
    artefact = artefacts.get(kind)
    if artefact is None:
        raise ApiRefusal(
            status.HTTP_404_NOT_FOUND,
            ErrorCode.NOT_FOUND,
            f"Run {run_id} has no {kind.value}. It has "
            f"{', '.join(sorted(k.value for k in artefacts)) or 'no artefacts'}.",
        )

    path = _resolve(artefact, settings)
    return FileResponse(
        path,
        media_type=MEDIA_TYPES[kind],
        filename=kind.value,
        headers={"ETag": f'"{artefact.sha256}"'},
    )


# -- the allow-list ------------------------------------------------------------


def _resolve(artefact: Artefact, settings: ApiSettings) -> Path:
    """Turn a stored URI into a path this server has agreed to read, or refuse.

    Five ways this says no, and each one is a real case rather than defensive noise:

    * **not a `file://` URI** — an object-store URL at 6.2. Refused rather than fetched,
      because a server that will `GET` any URL out of its own database on request is a
      proxy for reaching whatever it can reach.
    * **no root configured** — the allow-list is empty, so nothing is servable.
    * **outside the root** — including by way of a symlink, since the path is resolved
      before it is compared.
    * **gone** — the record says a file was there; artefacts are stored by reference and
      nothing stops one being moved.
    * **a different size than recorded** — then it is not the artefact this record
      describes, and serving it under that record's sha256 would be a lie.
    """
    parsed = urlparse(artefact.uri)
    if parsed.scheme != "file":
        raise ApiRefusal(
            status.HTTP_501_NOT_IMPLEMENTED,
            ErrorCode.ARTEFACT_UNAVAILABLE,
            f"That artefact is stored as {parsed.scheme or 'an unknown scheme'}:, "
            "which this build does not fetch from. Object storage arrives at 6.2.",
        )

    root = settings.artefact_root
    if root is None:
        raise ApiRefusal(
            status.HTTP_409_CONFLICT,
            ErrorCode.ARTEFACT_UNAVAILABLE,
            f"No artefact root is configured, so this service serves no files. Set "
            f"${ARTEFACT_ROOT_ENV} to the directory artefacts are written under. It "
            "is an allow-list rather than a convenience: without it, serving an "
            "artefact means opening whatever path a row happens to contain.",
        )

    path = Path(url2pathname(unquote(parsed.path))).resolve()
    if not path.is_relative_to(root):
        raise ApiRefusal(
            status.HTTP_409_CONFLICT,
            ErrorCode.ARTEFACT_UNAVAILABLE,
            f"That artefact is recorded outside ${ARTEFACT_ROOT_ENV}, so this service "
            "will not open it. It exists and is registered; it is simply not one this "
            "deployment is allowed to read.",
        )
    if not path.is_file():
        raise ApiRefusal(
            status.HTTP_409_CONFLICT,
            ErrorCode.ARTEFACT_UNAVAILABLE,
            "That artefact is registered but the file is gone. Artefacts are stored by "
            "reference — the record survives, the file is on somebody's disk.",
        )
    actual = path.stat().st_size
    if actual != artefact.size_bytes:
        raise ApiRefusal(
            status.HTTP_409_CONFLICT,
            ErrorCode.ARTEFACT_UNAVAILABLE,
            f"That file is {actual:,} bytes and the record says {artefact.size_bytes:,}"
            ", so it is no longer the artefact this run produced. Refused rather than "
            "served under a hash it would not match.",
        )
    return path


def _artefact_out(artefact: Artefact) -> ArtefactOut:
    return ArtefactOut(
        id=artefact.id,
        run_id=artefact.run_id,
        kind=artefact.kind,
        size_bytes=artefact.size_bytes,
        sha256=artefact.sha256,
        created_at=artefact.created_at,
        href=f"/runs/{artefact.run_id}/artefacts/{artefact.kind.value}",
    )
