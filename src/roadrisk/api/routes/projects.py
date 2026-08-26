"""Projects — create, read, update, delete.

The delete is the interesting one. Migration 0001 cascades from project through
corridor, job and run, so an unguarded `DELETE /projects/{id}` destroys every stored
assessment filed under it — and a stored run is what a client paid for. The guard lives
in the store, in both backends, so this route cannot reach past it; here it becomes a
409 that names what is still there.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response, status

from roadrisk.api.deps import StoreDep, TenantId
from roadrisk.api.errors import REFUSAL_RESPONSES
from roadrisk.api.schemas import ProjectCreate, ProjectPatch
from roadrisk.store import Project

router = APIRouter(prefix="/projects", tags=["projects"], responses=REFUSAL_RESPONSES)


@router.post(
    "",
    response_model=Project,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project",
)
def create_project(
    body: ProjectCreate, tenant_id: TenantId, store: StoreDep
) -> Project:
    """File a new project under the tenant in the header.

    The tenant is never in the body. A body that could name one would let a client file
    rows under somebody else's tenant, and since the model forbids extras, sending
    `tenant_id` is a 422 rather than a silent success under the wrong owner.
    """
    return store.create_project(
        Project(tenant_id=tenant_id, name=body.name, spend_cap=body.spend_cap)
    )


@router.get("", response_model=list[Project], summary="Every project this tenant has")
def list_projects(tenant_id: TenantId, store: StoreDep) -> list[Project]:
    return store.list_projects(tenant_id)


@router.get("/{project_id}", response_model=Project, summary="One project")
def get_project(project_id: UUID, tenant_id: TenantId, store: StoreDep) -> Project:
    return store.get_project(tenant_id, project_id)


@router.patch("/{project_id}", response_model=Project, summary="Rename, or set the cap")
def patch_project(
    project_id: UUID, body: ProjectPatch, tenant_id: TenantId, store: StoreDep
) -> Project:
    """Apply only the fields actually sent.

    `exclude_unset` is what makes `"spend_cap": null` mean *remove the cap* and an
    absent `spend_cap` mean *leave it alone*. Collapsing those two would make it
    impossible to uncap a project through this API without guessing.
    """
    merged = store.get_project(tenant_id, project_id).model_dump()
    merged.update(body.model_dump(exclude_unset=True))
    return store.update_project(tenant_id, Project.model_validate(merged))


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project that holds nothing",
    responses={409: {"description": "It still holds corridors, jobs or runs."}},
)
def delete_project(project_id: UUID, tenant_id: TenantId, store: StoreDep) -> Response:
    """Refused while anything is filed under it. There is no force flag.

    Emptying a project means deleting what is in it, one thing at a time, on purpose.
    The alternative is one request that quietly destroys a quarter's work because the
    schema said `CASCADE`.
    """
    store.delete_project(tenant_id, project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
