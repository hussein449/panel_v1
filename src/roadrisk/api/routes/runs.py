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

from fastapi import APIRouter, Query, status
from fastapi.responses import FileResponse

from roadrisk.api.deps import SettingsDep, StoreDep, TenantId
from roadrisk.api.errors import REFUSAL_RESPONSES, ApiRefusal, ErrorCode
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
) -> list[RunSummary]:
    """Summaries, not payloads.

    A run is around 300 kB of JSON. Fifty of them is fifteen megabytes, which is not a
    listing — it is a download nobody asked for. Every field in a summary was lifted out
    of the payload by the store on insert, so a summary cannot describe a different run
    than the one it points at.
    """
    capped = min(limit or settings.default_page_size, settings.max_page_size)
    runs = store.list_runs(tenant_id, project_id, limit=capped)
    return [RunSummary.of(run) for run in runs]


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
