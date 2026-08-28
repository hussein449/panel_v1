"""Step 5.2a — jobs that outlive the process which accepted them.

    roadrisk serve --queue      # the API, putting jobs on the queue
    roadrisk worker             # a process that drains it

Two facts about this package, both of which are the reason it exists:

* **The unit of distribution is a job, not an adapter branch.** `app.py` gives the
  measurement behind that, and it is the decision the boxed note under 5.2a asked for.
* **It sits above the API in the layer order.** `roadrisk.api` cannot import this, which
  is why `create_app` takes a runner as an argument and why `roadrisk.worker.web` exists
  to supply one.

`roadrisk.worker.web` is an alias for `runner`, so that the name handed to uvicorn reads
as what it is: the web application, composed with the queue.
"""

from roadrisk.worker.app import (
    BROKER_URL_ENV,
    TASK_NAME,
    broker_url,
    celery_app,
    configure,
    transport_options,
)
from roadrisk.worker.runner import CeleryRunner, create_app
from roadrisk.worker.tasks import assess

__all__ = [
    "BROKER_URL_ENV",
    "TASK_NAME",
    "CeleryRunner",
    "assess",
    "broker_url",
    "celery_app",
    "configure",
    "create_app",
    "transport_options",
]
