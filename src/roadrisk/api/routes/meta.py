"""What this deployment is, and whether it is up.

Deliberately the only routes that do not require a tenant: a health check that needed a
credential would be checked by nobody, and every load balancer would report the service
down for the one reason it is not.
"""

from __future__ import annotations

from fastapi import APIRouter

from roadrisk import __version__
from roadrisk.api.deps import RegistryDep, RunnerDep, SettingsDep
from roadrisk.api.schemas import Health
from roadrisk.contract import SCHEMA_VERSION

router = APIRouter(tags=["meta"])


@router.get(
    "/health",
    response_model=Health,
    summary="Whether the service is up, and what it can actually do",
)
def health(
    settings: SettingsDep, registry: RegistryDep, runner: RunnerDep
) -> Health:
    """Report the versions, and what this deployment can and cannot actually do.

    `runner` names what executes jobs, or is null when nothing does. That distinction is
    the point of returning it: a job sitting in `queued` means "wait" if there is a
    runner and "nothing is listening" if there is not, and no amount of polling tells
    the two apart. `auth` is still null and will be until step 5.4a.
    """
    return Health(
        status="ok",
        engine_version=__version__,
        schema_version=SCHEMA_VERSION,
        registry_version=registry.version,
        runner=getattr(runner, "name", None),
        auth=None,
        artefacts_available=settings.artefact_root is not None,
    )
