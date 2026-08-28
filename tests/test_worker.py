"""Step 5.2a — jobs that outlive the process which accepted them.

The deliverable was *across machines*, and the honest largest version of that on one
machine is **across processes**: the API puts a job on a queue and returns, nothing in
that process runs it, and a separate `roadrisk worker` picks it up and finishes it. That
is what `test_a_worker_in_another_process_finishes_a_job_the_api_only_queued` does, with
a real broker and a real database, and it is the only test here that proves the step.

Everything else is the refusals around it. A worker with no queue, a worker with no
database, and a `filesystem://` URL whose path kombu would otherwise ignore — each one
would produce a worker that starts, looks healthy, and does nothing.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip(
    "celery",
    reason=(
        "The worker extra is not installed, so the queue is not exercised. "
        'Run: pip install "roadrisk-panel[worker]"'
    ),
)

from roadrisk.api.deps import shared_store  # noqa: E402
from roadrisk.store import Job, MemoryStore, Project, Tenant  # noqa: E402
from roadrisk.worker import BROKER_URL_ENV, CeleryRunner, transport_options  # noqa: E402
from roadrisk.worker.app import worker_store_provider  # noqa: E402
from roadrisk.worker.tasks import assess, bind  # noqa: E402

DSN = os.environ.get("ROADRISK_DATABASE_URL")


def test_a_worker_without_a_queue_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    """No default broker, for the reason there is no default artefact root.

    A worker that quietly picked `redis://localhost` would start, connect to nothing, and
    report itself healthy while every job stayed queued.
    """
    from roadrisk.worker.app import broker_url

    monkeypatch.delenv(BROKER_URL_ENV, raising=False)
    with pytest.raises(RuntimeError, match=BROKER_URL_ENV):
        broker_url()


def test_a_worker_without_a_database_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    """A queue across processes needs a store across processes.

    `MemoryStore` is a real store, and it is the right default for `roadrisk serve` on one
    machine — but its state *is* the object. A worker holding one would drain a queue of
    jobs it cannot see and write runs nobody can read.
    """
    from roadrisk.store.postgres import DSN_ENV

    monkeypatch.delenv(DSN_ENV, raising=False)
    with pytest.raises(RuntimeError, match=DSN_ENV):
        worker_store_provider()


def test_the_filesystem_brokers_path_is_actually_read(tmp_path: Path) -> None:
    """Kombu ignores the URL's path and takes its folders from transport options.

    Which makes `filesystem:///var/tmp/queue` look like it works and then queue into the
    process's working directory — two processes agreeing on a URL and disagreeing about
    where the queue is. The path is read here instead.
    """
    options = transport_options(f"filesystem://{tmp_path}")

    assert options["data_folder_in"] == str(tmp_path)
    assert options["data_folder_out"] == str(tmp_path)
    assert (tmp_path / "control").is_dir()

    # Anything else is a server, and a server needs no folders.
    assert transport_options("redis://localhost:6379/0") == {}


def test_the_task_runs_a_job_and_writes_down_what_happened() -> None:
    """The task body, without a broker in the way.

    `apply` runs it here and now, which is what makes this a test of the task rather than
    of Celery. A demo corridor needs no network and no crash extract, so what is being
    checked is the one thing the task does: reach `execute`, and let it write a status.
    """
    store = MemoryStore()
    tenant = store.create_tenant(Tenant(name="worker"))
    project = store.create_project(Project(tenant_id=tenant.id, name="worker"))
    job = store.create_job(
        Job(
            tenant_id=tenant.id,
            project_id=project.id,
            params={"source": "demo", "options": {}, "panel": None},
        )
    )

    bind(shared_store(store))
    try:
        assess.apply(args=[str(tenant.id), str(job.id)]).get()
    finally:
        bind(None)

    finished = store.get_job(tenant.id, job.id)
    assert finished.status == "succeeded", finished.error
    assert store.find_run_for_job(tenant.id, job.id) is not None


def test_a_job_that_does_not_exist_does_not_take_the_worker_down() -> None:
    """A message for a row that is gone — a deleted project, a wiped database.

    `execute` never raises, because since 5.1d its caller has had nobody to raise at. The
    task inherits that: it swallows and logs rather than letting Celery mark a failure
    nobody will read, and the next message is still served.
    """
    store = MemoryStore()
    bind(shared_store(store))
    try:
        assess.apply(args=[str(uuid4()), str(uuid4())]).get()
    finally:
        bind(None)


def test_health_names_celery_when_the_queue_is_behind_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`GET /health` is where a client learns what this deployment does with a job.

    `in-process` and `celery` differ in exactly one way that matters to somebody polling:
    work in flight survives a restart of the thing they submitted to.
    """
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from roadrisk.api.app import create_app

    monkeypatch.setenv(BROKER_URL_ENV, f"filesystem://{tmp_path}")
    client = TestClient(create_app(runner=CeleryRunner()))

    assert client.get("/health").json()["runner"] == "celery"


@pytest.mark.skipif(
    not DSN,
    reason=(
        "$ROADRISK_DATABASE_URL is unset, so the across-processes test cannot run — a "
        "worker in another process needs a store in another process. Set it to e.g. "
        "postgresql:///roadrisk."
    ),
)
def test_a_worker_in_another_process_finishes_a_job_the_api_only_queued(
    tmp_path: Path,
) -> None:
    """**Step 5.2a's done-when, as close as one machine gets to *across machines*.**

    Submit through the API with the queue behind it. Nothing in that process runs the
    job — assert that, because a test that merely watched a job succeed would pass just
    as well against the thread pool it replaced. Then start a real `roadrisk worker` as a
    separate operating-system process and watch the same row finish.

    The broker is kombu's filesystem transport: a directory two processes agree on. It
    polls, so it is not for production — but it needs no server, which is what makes this
    the rare distributed test that can run anywhere.
    """
    pytest.importorskip("fastapi")
    pytest.importorskip("psycopg")
    from fastapi.testclient import TestClient

    from roadrisk.store.postgres import PostgresStore
    from roadrisk.worker.web import create_app

    broker = f"filesystem://{tmp_path / 'queue'}"
    environment = {**os.environ, BROKER_URL_ENV: broker, "ROADRISK_DATABASE_URL": DSN}
    os.environ[BROKER_URL_ENV] = broker

    store = PostgresStore.connect(DSN)
    tenant = store.create_tenant(Tenant(name=f"queued {uuid4()}"))
    project = store.create_project(Project(tenant_id=tenant.id, name="queued"))

    client = TestClient(create_app())
    submitted = client.post(
        "/jobs",
        json={"project_id": str(project.id), "demo": True},
        headers={"X-Tenant-Id": str(tenant.id)},
    )
    assert submitted.status_code == 202
    job_id = submitted.json()["id"]

    # Nothing here runs it. This is the assertion that distinguishes a queue from a pool.
    time.sleep(1.0)
    assert store.get_job(tenant.id, submitted.json()["id"]).status == "queued"

    worker = subprocess.Popen(
        [sys.executable, "-m", "roadrisk.cli", "worker", "--loglevel", "warning"],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 120
        status = "queued"
        while time.monotonic() < deadline:
            status = store.get_job(tenant.id, submitted.json()["id"]).status
            if status in {"succeeded", "failed", "rejected"}:
                break
            time.sleep(0.5)
    finally:
        worker.terminate()
        try:
            output = worker.communicate(timeout=20)[0]
        except subprocess.TimeoutExpired:  # pragma: no cover - a wedged worker
            worker.kill()
            output = worker.communicate()[0]

    assert status == "succeeded", f"job {job_id} ended {status}\n{output}"
    assert store.find_run_for_job(tenant.id, submitted.json()["id"]) is not None
    store.close()
