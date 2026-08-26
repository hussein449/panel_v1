"""The routers, one module per resource."""

from __future__ import annotations

from roadrisk.api.routes import corridors, jobs, meta, projects, registry, runs

#: Mounted in this order by :func:`roadrisk.api.app.create_app`, which is also the
#: order they appear in the OpenAPI document and therefore in generated documentation.
#: Meta and registry first, because they are what a client reads before it can send
#: anything meaningful.
ROUTERS = (
    meta.router,
    registry.router,
    projects.router,
    corridors.router,
    jobs.router,
    runs.router,
)

__all__ = ["ROUTERS"]
