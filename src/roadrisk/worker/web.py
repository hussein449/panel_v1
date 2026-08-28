"""The web application, composed with the queue.

A module of its own so that the string `roadrisk serve` hands to uvicorn reads as what it
is — `roadrisk.worker.web:create_app`, the web half of the worker deployment — rather
than as a factory hiding in a file named after runners. `--reload` re-imports that name in
a fresh process, so it has to be a name and not an object.
"""

from roadrisk.worker.runner import create_app

__all__ = ["create_app"]
