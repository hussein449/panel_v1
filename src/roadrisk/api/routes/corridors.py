"""Corridors — create, read, update, delete.

A corridor is a road as the *parameters that fetch and segment it*, not as geometry.
Geometry belongs to a run, because the OSM extract behind a road changes: two runs of
the same corridor a month apart are two different centrelines and conflating them would
make a comparison meaningless. What is stable is the request.

Creation lives under the project — `POST /projects/{id}/corridors` — because a corridor
without a project is not a thing this system can hold. Everything else is addressed by
the corridor's own id, so a client that has one never has to remember which project it
came from.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response, status

from roadrisk.api.deps import StoreDep, TenantId
from roadrisk.api.errors import REFUSAL_RESPONSES
from roadrisk.api.schemas import CorridorCreate, CorridorPatch
from roadrisk.store import Corridor

router = APIRouter(tags=["corridors"], responses=REFUSAL_RESPONSES)


@router.post(
    "/projects/{project_id}/corridors",
    response_model=Corridor,
    status_code=status.HTTP_201_CREATED,
    summary="Declare a road under a project",
)
def create_corridor(
    project_id: UUID, body: CorridorCreate, tenant_id: TenantId, store: StoreDep
) -> Corridor:
    """Create it, or refuse if the project is not this tenant's.

    The store checks the parent against `(tenant_id, project_id)` together, so a
    corridor cannot be filed under another tenant's project even with a valid id for
    it — that is a row Postgres refuses, not a rule this route has to remember.
    """
    return store.create_corridor(
        Corridor(
            tenant_id=tenant_id,
            project_id=project_id,
            name=body.name,
            ref=body.ref,
            osm_name=body.osm_name,
            bbox=body.bbox,
            unit_length_m=body.unit_length_m,
        )
    )


@router.get(
    "/projects/{project_id}/corridors",
    response_model=list[Corridor],
    summary="Every corridor in a project",
)
def list_corridors(
    project_id: UUID, tenant_id: TenantId, store: StoreDep
) -> list[Corridor]:
    return store.list_corridors(tenant_id, project_id)


@router.get("/corridors/{corridor_id}", response_model=Corridor, summary="One corridor")
def get_corridor(corridor_id: UUID, tenant_id: TenantId, store: StoreDep) -> Corridor:
    return store.get_corridor(tenant_id, corridor_id)


@router.patch(
    "/corridors/{corridor_id}",
    response_model=Corridor,
    summary="Change the reference, the box or the unit length",
)
def patch_corridor(
    corridor_id: UUID, body: CorridorPatch, tenant_id: TenantId, store: StoreDep
) -> Corridor:
    # Merged and re-validated rather than `model_copy(update=...)`, which skips
    # validation: a `bbox` arriving as a JSON array would be stored as a list under a
    # field the record declares a tuple, and nothing would say so until something
    # unpacked it.
    merged = store.get_corridor(tenant_id, corridor_id).model_dump()
    merged.update(body.model_dump(exclude_unset=True))
    return store.update_corridor(tenant_id, Corridor.model_validate(merged))


@router.delete(
    "/corridors/{corridor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a corridor nothing references",
    responses={409: {"description": "A job or a run still points at it."}},
)
def delete_corridor(
    corridor_id: UUID, tenant_id: TenantId, store: StoreDep
) -> Response:
    """Refused while a job or a run points at it, even though the schema would allow it.

    `job.corridor_id` and `run.corridor_id` are `ON DELETE SET NULL`, so nothing would
    be destroyed here — but the *link* would be, silently. A run keeps its geometry
    inside the payload and would lose the road it was filed against, which is exactly
    the kind of quiet loss this project spends its effort preventing.
    """
    store.delete_corridor(tenant_id, corridor_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
