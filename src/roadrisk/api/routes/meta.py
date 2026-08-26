"""What this deployment is, and whether it is up.

Deliberately the only routes that do not require a tenant: a health check that needed a
credential would be checked by nobody, and every load balancer would report the service
down for the one reason it is not.
"""

from __future__ import annotations

from fastapi import APIRouter

from roadrisk import __version__
from roadrisk.api.deps import RegistryDep, SettingsDep
from roadrisk.api.schemas import Health
from roadrisk.contract import SCHEMA_VERSION

router = APIRouter(tags=["meta"])


@router.get(
    "/health",
    response_model=Health,
    summary="Whether the service is up, and what it can actually do",
)
def health(settings: SettingsDep, registry: RegistryDep) -> Health:
    """Report the versions and the two capabilities this deployment does not yet have.

    `runner` and `auth` are null at 5.1c and that is the point of returning them: a
    client can tell that a job it posts will be stored and queued and never executed,
    rather than watching one sit in `queued` and drawing its own conclusions.
    """
    return Health(
        status="ok",
        engine_version=__version__,
        schema_version=SCHEMA_VERSION,
        registry_version=registry.version,
        runner=None,
        auth=None,
        artefacts_available=settings.artefact_root is not None,
    )
