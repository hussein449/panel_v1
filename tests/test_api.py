"""Step 5.1c — the API, and the three outcomes it must keep apart.

The largest design risk in Stage 5 is that a REST instinct collapses every non-success
onto 4xx and 5xx, which would swallow this project's entire honesty layer into a generic
error handler. So the tests that matter most here are not the CRUD ones:

* a panel breaking the input contract is **422**, the column is named, and **no job
  exists afterwards**;
* a run that descended to Mode B is **200**, carrying its descent receipt;
* infrastructure failing is the job's status, never a 500 with a stack trace.

Everything runs against `MemoryStore` through Starlette's in-process test client, so
there is no server, no port and no database. Backend conformance is `tests/test_store.py`'s
job and is proved against both there; repeating it here would double the runtime to
re-answer a question already answered.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

pytest.importorskip(
    "fastapi",
    reason=(
        "The api extra is not installed, so the HTTP layer is not exercised. "
        'Run: pip install "roadrisk-panel[api]"'
    ),
)

from fastapi.testclient import TestClient  # noqa: E402

from roadrisk.api import create_app, shared_store  # noqa: E402
from roadrisk.api.settings import ApiSettings  # noqa: E402
from roadrisk.core.engine import assess  # noqa: E402
from roadrisk.core.registry import (  # noqa: E402
    LICENCE_POLICY,
    TIER_MEANING,
    Licence,
    Tier,
)
from roadrisk.demo import synthetic_panel  # noqa: E402
from roadrisk.report import build_run  # noqa: E402
from roadrisk.store import (  # noqa: E402
    Artefact,
    ArtefactKind,
    MemoryStore,
    Project,
    Tenant,
)

API_SOURCE = Path(__file__).resolve().parents[1] / "src" / "roadrisk" / "api"


# -- fixtures ------------------------------------------------------------------


@pytest.fixture(scope="session")
def mode_a_payload() -> dict[str, Any]:
    """A genuine run. A hand-written dictionary would prove nothing about the shape."""
    return build_run(assess(synthetic_panel(n_units=25, n_periods=8, seed=4)))


@pytest.fixture(scope="session")
def mode_b_payload() -> dict[str, Any]:
    """A refused panel. Mode B is the floor, and a run carrying one still succeeded."""
    panel = synthetic_panel(n_units=25, n_periods=8, seed=4)
    return build_run(assess(panel[panel["n_crashes"] == 0]))


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def settings(tmp_path: Path) -> ApiSettings:
    """An artefact root per test, so the allow-list is a real directory."""
    root = tmp_path / "artefacts"
    root.mkdir()
    return ApiSettings(artefact_root=root.resolve())


@pytest.fixture
def client(store: MemoryStore, settings: ApiSettings) -> TestClient:
    return TestClient(create_app(store_provider=shared_store(store), settings=settings))


@pytest.fixture
def tenant(store: MemoryStore) -> Tenant:
    return store.create_tenant(Tenant(name="acme roads"))


@pytest.fixture
def auth(tenant: Tenant) -> dict[str, str]:
    return {"X-Tenant-Id": str(tenant.id)}


@pytest.fixture
def project(client: TestClient, auth: dict[str, str]) -> dict[str, Any]:
    response = client.post("/projects", json={"name": "cyprus"}, headers=auth)
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def corridor(
    client: TestClient, auth: dict[str, str], project: dict[str, Any]
) -> dict[str, Any]:
    response = client.post(
        f"/projects/{project['id']}/corridors",
        json={"name": "B9", "ref": "B9", "bbox": [34.6, 32.9, 35.1, 33.5]},
        headers=auth,
    )
    assert response.status_code == 201
    return response.json()


def a_valid_panel(rows: int = 4) -> list[dict[str, Any]]:
    """The smallest thing the input contract accepts. Not a realistic assessment."""
    return [
        {
            "unit_id": f"u{index // 2}",
            "period": f"2024-0{1 + index % 2}",
            "time_slot": "all",
            "n_crashes": index % 3,
            "length_km": 0.5,
            "duration_hours": 720.0,
        }
        for index in range(rows)
    ]


# -- the refusal contract ------------------------------------------------------


def test_a_contract_violation_at_submit_is_422_and_creates_no_job(
    client: TestClient, auth: dict[str, str], project: dict[str, Any]
) -> None:
    """The first row of the refusal contract, both halves of it.

    422 with the column named is the visible half. "No job created" is the half that
    matters and the only one a client can verify, so it is checked by listing the
    project's jobs afterwards and finding it empty — not by trusting that the route
    returned before it got there.
    """
    panel = [dict(row) for row in a_valid_panel()]
    for row in panel:
        del row["length_km"]

    response = client.post(
        "/jobs", json={"project_id": project["id"], "panel": panel}, headers=auth
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "contract_violation"
    assert "length_km" in error["message"]

    listed = client.get(f"/projects/{project['id']}/jobs", headers=auth)
    assert listed.json() == []


def test_a_mode_b_descent_is_a_200_carrying_its_receipt(
    client: TestClient,
    auth: dict[str, str],
    store: MemoryStore,
    tenant: Tenant,
    project: dict[str, Any],
    mode_b_payload: dict[str, Any],
) -> None:
    """The second row, and the one a REST instinct gets wrong.

    The engine refusing Mode A *is* the assessment. A run that descended, dropped terms
    and declined to score unsourced weights is a completed piece of work, and every one
    of those decisions is content inside the payload. Turning any of it into a status
    code would move the honesty layer into an error handler, where nobody reads it.
    """
    run = store.store_run(tenant.id, uuid_of(project), mode_b_payload)

    response = client.get(f"/runs/{run.id}", headers=auth)

    assert response.status_code == 200
    body = response.json()
    assert body["payload"]["assessment"]["mode"] == "B"
    assert body["payload"]["assessment"]["receipts"], (
        "A Mode B run must arrive carrying the receipts that explain the descent. A "
        "200 with the findings stripped out would be worse than a 4xx."
    )
    assert body["payload"]["limitations"], "4.6's page is not removable by transport."


def test_every_refusal_wears_the_same_shape(
    client: TestClient, auth: dict[str, str], project: dict[str, Any]
) -> None:
    """Including FastAPI's own validation errors, which are a bare list by default.

    A client that has to parse two error shapes will parse one and guess at the other.
    """
    refusals = [
        client.get("/projects"),  # no tenant at all
        client.get(f"/projects/{uuid4()}", headers=auth),  # not found
        client.post("/projects", json={"nope": 1}, headers=auth),  # FastAPI's own 422
        client.post(
            "/jobs",
            json={"project_id": project["id"]},  # neither corridor nor panel
            headers=auth,
        ),
    ]
    for response in refusals:
        assert response.status_code >= 400
        body = response.json()
        assert set(body) == {"error"}, body
        assert set(body["error"]) == {"code", "message", "field", "errors"}
        assert body["error"]["message"].strip()


def test_an_unhandled_error_is_a_500_with_a_reference_and_no_traceback(
    store: MemoryStore, settings: ApiSettings, auth: dict[str, str]
) -> None:
    """"Never a 500 with a stack trace" is a promise to the client, not the operator.

    The traceback is logged in full. What crosses the wire is a sentence and the
    reference it was logged under, so an operator can find it and a client is not handed
    the shape of our source tree.
    """

    class Exploding(MemoryStore):
        def list_projects(self, tenant_id):  # type: ignore[no-untyped-def]
            raise RuntimeError("psycopg: connection is closed")

    app = create_app(
        store_provider=shared_store(Exploding()), settings=settings
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/projects", headers=auth)

    assert response.status_code == 500
    body = response.json()["error"]
    assert body["code"] == "internal"
    assert "psycopg" not in body["message"]
    assert "Traceback" not in body["message"]


# -- the done-when: factors, tiers and licences read from factors.yaml ----------


def test_the_registry_served_is_the_registry_declared(
    client: TestClient, shipped_registry
) -> None:
    """Every factor, in descent order, with each adapter's tier and licence.

    Compared against the loaded `factors.yaml` rather than against a list written here,
    because a list written here is the second description that step 5.1a exists to
    prevent — it would agree with itself forever and with the registry never.
    """
    body = client.get("/registry").json()

    assert body["version"] == shipped_registry.version
    assert body["sha256"] == shipped_registry.sha256
    assert body["factor_count"] == len(shipped_registry.factors)
    assert {f["name"] for f in body["factors"]} == set(shipped_registry.names)

    priorities = [f["drop_priority"] for f in body["factors"]]
    assert priorities == sorted(priorities, reverse=True), (
        "Served most-important-first — the reverse of the order the ladder sheds "
        "terms in, which is the order a client planning what data to buy reads."
    )

    served = {f["name"]: f for f in body["factors"]}
    for factor in shipped_registry.factors:
        adapters = served[factor.name]["adapters"]
        assert [a["name"] for a in adapters] == [a.name for a in factor.adapters]
        assert [a["tier"] for a in adapters] == [a.tier.value for a in factor.adapters]
        assert [a["licence"] for a in adapters] == [
            a.licence.value for a in factor.adapters
        ]


def test_no_factor_name_is_written_down_anywhere_in_the_api(shipped_registry) -> None:
    """*Read* from `factors.yaml`, not copied out of it.

    The done-when says the API's factors come from the registry. The way that stops
    being true is never a deliberate decision — it is one endpoint that needed a
    special case for `traffic_proxy` and got one. This is what would notice.

    Checked against string *constants*, parsed with `ast`, rather than by searching the
    text. Two reasons. A grep is wrong in both directions: one factor really is called
    `lit`, which appears inside "faci**lit**y" in half these files, and a name written
    into a comment is prose rather than a dependency. And a hard-coded special case is
    a string literal — `== "traffic_proxy"`, `in ("lanes", ...)` — which is exactly
    what this sees and nothing else is.
    """
    import ast

    declared = set(shipped_registry.names)
    guilty = set()
    for path in API_SOURCE.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value in declared:
                guilty.add(f"{path.name}:{node.lineno} {node.value!r}")

    assert not guilty, f"Factor names hard-coded in the API layer: {sorted(guilty)}"


def test_the_licence_glossary_covers_every_licence_the_registry_can_hold() -> None:
    """A licence with no described obligation would be published as a bare string.

    Which tells a client nothing they can act on — the whole point of
    `roadrisk.geo.attribution` is that "ODbL" and "credit the source" are different
    amounts of information, and that republishing the panel is a different act from
    citing it in a report.
    """
    assert set(LICENCE_POLICY) == set(Licence)
    assert set(TIER_MEANING) == set(Tier)
    assert all(policy.note.strip() for policy in LICENCE_POLICY.values())


def test_the_served_obligations_are_the_ones_the_engine_applies(
    client: TestClient,
) -> None:
    """Not a second copy of the licence text with the same words in it."""
    served = {row["code"]: row for row in client.get("/registry").json()["licences"]}
    for licence, policy in LICENCE_POLICY.items():
        assert served[licence.value]["credit_required"] == policy.credit_required
        assert (
            served[licence.value]["share_alike_database"]
            == policy.share_alike_database
        )
        assert served[licence.value]["obligation"] == policy.note


def test_the_openapi_document_is_generated_and_committed() -> None:
    """`docs/openapi.json` describes the API as it currently is.

    The surface — paths, methods, status codes, parameters, schema names — not the
    prose. A check that failed because FastAPI reworded a description is a check people
    learn to regenerate past without reading.
    """
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "tools" / "generate_openapi.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=root,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_openapi_enums_are_the_registrys_own(client: TestClient) -> None:
    """So the published contract cannot describe a licence the registry cannot hold."""
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert set(schemas["Licence"]["enum"]) == {licence.value for licence in Licence}
    assert set(schemas["Tier"]["enum"]) == {tier.value for tier in Tier}


# -- tenancy over the wire -----------------------------------------------------


def test_no_tenant_header_is_refused_and_says_it_is_not_a_credential(
    client: TestClient,
) -> None:
    response = client.get("/projects")
    assert response.status_code == 401
    error = response.json()["error"]
    assert error["code"] == "tenant_required"
    assert error["field"] == "X-Tenant-Id"


def test_one_tenants_rows_are_invisible_to_another(
    client: TestClient, project: dict[str, Any]
) -> None:
    """404, not 403.

    Distinguishing "does not exist" from "exists and is not yours" tells a caller
    whether an id is real, which turns a list of guessed identifiers into a census of
    somebody else's work. The store refuses to make that distinction and the API must
    not reintroduce it.
    """
    stranger = {"X-Tenant-Id": str(uuid4())}
    assert client.get(f"/projects/{project['id']}", headers=stranger).status_code == 404
    assert client.get("/projects", headers=stranger).json() == []


def test_a_body_cannot_smuggle_a_tenant_id(
    client: TestClient, auth: dict[str, str]
) -> None:
    """The tenant comes from the header and from nowhere else.

    Every request model forbids extras, so a body naming a tenant is a 422 rather than
    a row quietly filed under somebody else's ownership.
    """
    response = client.post(
        "/projects", json={"name": "sneaky", "tenant_id": str(uuid4())}, headers=auth
    )
    assert response.status_code == 422
    assert "tenant_id" in response.json()["error"]["message"]


def test_a_malformed_tenant_header_names_itself(client: TestClient) -> None:
    response = client.get("/projects", headers={"X-Tenant-Id": "not-a-uuid"})
    assert response.status_code == 400
    assert response.json()["error"]["field"] == "X-Tenant-Id"


# -- projects and corridors ----------------------------------------------------


def test_a_project_round_trips_through_create_list_and_get(
    client: TestClient, auth: dict[str, str], project: dict[str, Any]
) -> None:
    assert client.get(f"/projects/{project['id']}", headers=auth).json() == project
    assert client.get("/projects", headers=auth).json() == [project]


def test_patch_distinguishes_clearing_a_cap_from_leaving_it(
    client: TestClient, auth: dict[str, str], project: dict[str, Any]
) -> None:
    """`"spend_cap": null` removes it; an absent `spend_cap` leaves it alone.

    Collapsing those two would make it impossible to uncap a project through this API
    without guessing, and 5.2b reads that column before every call that would breach it.
    """
    url = f"/projects/{project['id']}"
    assert client.patch(url, json={"spend_cap": 250.0}, headers=auth).json()[
        "spend_cap"
    ] == 250.0

    renamed = client.patch(url, json={"name": "cyprus b9"}, headers=auth).json()
    assert (renamed["name"], renamed["spend_cap"]) == ("cyprus b9", 250.0)

    uncapped = client.patch(url, json={"spend_cap": None}, headers=auth).json()
    assert uncapped["spend_cap"] is None


def test_an_inverted_bounding_box_is_refused_at_submit(
    client: TestClient, auth: dict[str, str], project: dict[str, Any]
) -> None:
    """Migration 0001 refuses a half-specified box; it cannot refuse an upside-down one.

    A `CHECK` constraint that knew north from south would be encoding geography into the
    schema. So it is refused here, rather than discovered as an empty Overpass result
    with no explanation attached.
    """
    response = client.post(
        f"/projects/{project['id']}/corridors",
        json={"name": "upside down", "bbox": [35.1, 32.9, 34.6, 33.5]},
        headers=auth,
    )
    assert response.status_code == 422
    assert "north" in response.json()["error"]["message"]


def test_deleting_a_project_that_holds_something_is_409_and_says_what(
    client: TestClient,
    auth: dict[str, str],
    project: dict[str, Any],
    corridor: dict[str, Any],
) -> None:
    """The schema cascades. An unguarded delete here destroys stored deliverables."""
    response = client.delete(f"/projects/{project['id']}", headers=auth)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "in_use"
    assert "1 corridor" in response.json()["error"]["message"]

    assert client.get(f"/projects/{project['id']}", headers=auth).status_code == 200


def test_an_empty_project_deletes(
    client: TestClient, auth: dict[str, str], project: dict[str, Any]
) -> None:
    assert client.delete(f"/projects/{project['id']}", headers=auth).status_code == 204
    assert client.get(f"/projects/{project['id']}", headers=auth).status_code == 404


# -- jobs ----------------------------------------------------------------------


def test_a_submitted_job_is_202_queued_with_a_location(
    client: TestClient,
    auth: dict[str, str],
    project: dict[str, Any],
    corridor: dict[str, Any],
) -> None:
    """202 today, with nothing behind it, deliberately.

    If this only started returning 202 once Celery existed, step 5.2 would change the
    contract and break every client written against 5.1. What 5.1d and 5.2a change is
    what executes a job, not what a client was promised.
    """
    response = client.post(
        "/jobs",
        json={"project_id": project["id"], "corridor_id": corridor["id"]},
        headers=auth,
    )

    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "queued"
    assert response.headers["Location"] == f"/jobs/{job['id']}"
    assert client.get(f"/jobs/{job['id']}", headers=auth).json()["status"] == "queued"


def test_health_admits_that_nothing_executes_jobs(client: TestClient) -> None:
    """A job that will never run, reported as `queued`, is a service that lies.

    `runner: null` is the honest answer at 5.1c, and it is why the client can tell the
    difference between "not started yet" and "nothing is listening".
    """
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["runner"] is None
    assert body["auth"] is None


def test_a_job_carries_everything_needed_to_run_it_later(
    client: TestClient, auth: dict[str, str], project: dict[str, Any]
) -> None:
    """`job.params` is a `JobSpec`, so 5.1d reads a submission back rather than guessing.

    The panel is stored as submitted rather than as prepared: `exposure` and
    `log_exposure` are derived, and freezing the derivation inside a row would put a
    copy of the input contract next to the data it describes.
    """
    from roadrisk.api.schemas import JobSpec

    panel = a_valid_panel()
    response = client.post(
        "/jobs",
        json={
            "project_id": project["id"],
            "panel": panel,
            "params": {"region": "europe", "estimator": "bayes"},
        },
        headers=auth,
    )
    assert response.status_code == 202

    spec = JobSpec.model_validate(response.json()["params"])
    assert spec.source == "panel"
    assert spec.options.region.value == "europe"
    assert spec.panel == panel
    assert "exposure" not in spec.panel[0]


def test_a_job_must_name_exactly_one_source(
    client: TestClient, auth: dict[str, str], project: dict[str, Any]
) -> None:
    both = client.post(
        "/jobs",
        json={
            "project_id": project["id"],
            "corridor_id": str(uuid4()),
            "panel": a_valid_panel(),
        },
        headers=auth,
    )
    assert both.status_code == 422
    assert "exactly one" in both.json()["error"]["message"]


def test_a_shape_factor_no_registry_entry_declares_is_a_typo_caught_now(
    client: TestClient,
    auth: dict[str, str],
    project: dict[str, Any],
    corridor: dict[str, Any],
) -> None:
    """`assess` reports names it could not spline; a name no factor has is different.

    That one will never mean anything, and finding it in a run log a quarter of an hour
    later helps nobody.
    """
    response = client.post(
        "/jobs",
        json={
            "project_id": project["id"],
            "corridor_id": corridor["id"],
            "params": {"shape_factors": ["curve_radius_min", "not_a_factor"]},
        },
        headers=auth,
    )
    assert response.status_code == 422
    message = response.json()["error"]["message"]
    assert "not_a_factor" in message
    assert "curve_radius_min" not in message, "Only the name that is wrong is named."


def test_a_corridor_with_nothing_to_fetch_is_refused_before_it_is_queued(
    client: TestClient, auth: dict[str, str], project: dict[str, Any]
) -> None:
    """A corridor may legitimately have no ref and no box — for a client centreline.

    There is no way to supply one over HTTP yet, so a job on such a corridor has no
    geometry to resolve. Refusing at submit beats failing in a worker at 5.1d.
    """
    bare = client.post(
        f"/projects/{project['id']}/corridors",
        json={"name": "client centreline"},
        headers=auth,
    ).json()

    response = client.post(
        "/jobs",
        json={"project_id": project["id"], "corridor_id": bare["id"]},
        headers=auth,
    )
    assert response.status_code == 422
    assert "nothing to fetch" in response.json()["error"]["message"]


def test_a_panel_larger_than_this_deployment_accepts_is_413(
    store: MemoryStore, tenant: Tenant, auth: dict[str, str], tmp_path: Path
) -> None:
    """The cap bounds what reaches `jsonb`, and says what a real panel looks like."""
    app = create_app(
        store_provider=shared_store(store),
        settings=ApiSettings(artefact_root=tmp_path, max_panel_rows=2),
    )
    client = TestClient(app)
    project = client.post("/projects", json={"name": "p"}, headers=auth).json()

    response = client.post(
        "/jobs",
        json={"project_id": project["id"], "panel": a_valid_panel(rows=4)},
        headers=auth,
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "too_large"


# -- runs and artefacts --------------------------------------------------------


def test_a_listing_of_runs_carries_no_payloads(
    client: TestClient,
    auth: dict[str, str],
    store: MemoryStore,
    tenant: Tenant,
    project: dict[str, Any],
    mode_a_payload: dict[str, Any],
) -> None:
    """A run is about 300 kB. Fifty of them is not a listing, it is a download."""
    store.store_run(tenant.id, uuid_of(project), mode_a_payload)

    listed = client.get("/runs", headers=auth).json()

    assert len(listed) == 1
    assert "payload" not in listed[0]
    assert listed[0]["mode"] and listed[0]["fingerprint"]


def test_an_artefact_downloads_with_the_hash_it_was_registered_under(
    client: TestClient,
    auth: dict[str, str],
    store: MemoryStore,
    tenant: Tenant,
    settings: ApiSettings,
    project: dict[str, Any],
    mode_a_payload: dict[str, Any],
) -> None:
    """The ETag is the recorded sha256, so a client can verify what arrived.

    Re-hashing a third of a megabyte on every request to prove what is already written
    down would be work done twice; handing over the recorded digest lets the client do
    it once, if it cares.
    """
    run = store.store_run(tenant.id, uuid_of(project), mode_a_payload)
    artefact = write_artefact(store, tenant, run.id, settings, b"<html>report</html>")

    listed = client.get(f"/runs/{run.id}/artefacts", headers=auth).json()
    assert listed[0]["href"] == f"/runs/{run.id}/artefacts/report.html"
    assert "uri" not in listed[0], "A client has no use for our filesystem layout."

    response = client.get(listed[0]["href"], headers=auth)
    assert response.status_code == 200
    assert response.content == b"<html>report</html>"
    assert response.headers["etag"] == f'"{artefact.sha256}"'
    assert response.headers["content-type"].startswith("text/html")


def test_an_artefact_outside_the_root_is_refused(
    client: TestClient,
    auth: dict[str, str],
    store: MemoryStore,
    tenant: Tenant,
    tmp_path: Path,
    project: dict[str, Any],
    mode_a_payload: dict[str, Any],
) -> None:
    """Serving an artefact means opening a path that came out of a database column.

    That is a file-read primitive pointed at the server's disk, and it does not become
    safe by being written by a trusted CLI today — 5.2a puts a worker on the other end
    of it. The root is an allow-list, and the path is resolved before it is compared, so
    a symlink inside the root pointing out of it is refused too.
    """
    escapee = tmp_path / "secrets.html"
    escapee.write_bytes(b"not yours")

    run = store.store_run(tenant.id, uuid_of(project), mode_a_payload)
    store.add_artefact(
        Artefact(
            tenant_id=tenant.id,
            run_id=run.id,
            kind=ArtefactKind.REPORT_HTML,
            uri=escapee.resolve().as_uri(),
            size_bytes=escapee.stat().st_size,
            sha256=hashlib.sha256(escapee.read_bytes()).hexdigest(),
        )
    )

    response = client.get(f"/runs/{run.id}/artefacts/report.html", headers=auth)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "artefact_unavailable"
    assert b"not yours" not in response.content


def test_with_no_root_configured_nothing_is_servable(
    store: MemoryStore,
    tenant: Tenant,
    auth: dict[str, str],
    tmp_path: Path,
    mode_a_payload: dict[str, Any],
) -> None:
    """The safe default fails with a 409 naming a variable. The convenient one
    serves `/etc/passwd`."""
    app = create_app(store_provider=shared_store(store), settings=ApiSettings())
    client = TestClient(app)
    project = store.create_project(Project(tenant_id=tenant.id, name="p"))
    run = store.store_run(tenant.id, project.id, mode_a_payload)

    file = tmp_path / "report.html"
    file.write_bytes(b"x")
    store.add_artefact(
        Artefact(
            tenant_id=tenant.id,
            run_id=run.id,
            kind=ArtefactKind.REPORT_HTML,
            uri=file.resolve().as_uri(),
            size_bytes=1,
            sha256=hashlib.sha256(b"x").hexdigest(),
        )
    )

    response = client.get(f"/runs/{run.id}/artefacts/report.html", headers=auth)
    assert response.status_code == 409
    assert "ROADRISK_ARTEFACT_ROOT" in response.json()["error"]["message"]
    assert client.get("/health").json()["artefacts_available"] is False


def test_an_artefact_that_changed_since_it_was_recorded_is_refused(
    client: TestClient,
    auth: dict[str, str],
    store: MemoryStore,
    tenant: Tenant,
    settings: ApiSettings,
    project: dict[str, Any],
    mode_a_payload: dict[str, Any],
) -> None:
    """Then it is not the artefact the record describes, and its sha256 is a lie.

    `stat` is free; re-hashing is not. Checking the size catches the case that actually
    happens — a file replaced or truncated — without paying for the one that does not.
    """
    run = store.store_run(tenant.id, uuid_of(project), mode_a_payload)
    write_artefact(store, tenant, run.id, settings, b"<html>report</html>")

    assert settings.artefact_root is not None
    (settings.artefact_root / "report.html").write_bytes(b"replaced, and longer now")

    response = client.get(f"/runs/{run.id}/artefacts/report.html", headers=auth)
    assert response.status_code == 409
    assert "no longer the artefact" in response.json()["error"]["message"]


def test_asking_for_an_artefact_a_run_does_not_have_says_what_it_does_have(
    client: TestClient,
    auth: dict[str, str],
    store: MemoryStore,
    tenant: Tenant,
    settings: ApiSettings,
    project: dict[str, Any],
    mode_a_payload: dict[str, Any],
) -> None:
    run = store.store_run(tenant.id, uuid_of(project), mode_a_payload)
    write_artefact(store, tenant, run.id, settings, b"<html>report</html>")

    response = client.get(f"/runs/{run.id}/artefacts/report.pdf", headers=auth)
    assert response.status_code == 404
    assert "report.html" in response.json()["error"]["message"]


def test_an_artefact_stored_somewhere_this_build_cannot_read_is_501(
    client: TestClient,
    auth: dict[str, str],
    store: MemoryStore,
    tenant: Tenant,
    project: dict[str, Any],
    mode_a_payload: dict[str, Any],
) -> None:
    """Object storage arrives at 6.2. Until then it is refused, not fetched.

    A server that will `GET` any URL out of its own database on request is a proxy for
    reaching whatever that server can reach.
    """
    run = store.store_run(tenant.id, uuid_of(project), mode_a_payload)
    store.add_artefact(
        Artefact(
            tenant_id=tenant.id,
            run_id=run.id,
            kind=ArtefactKind.REPORT_HTML,
            uri="https://internal.example/report.html",
            size_bytes=1,
            sha256="0" * 64,
        )
    )

    response = client.get(f"/runs/{run.id}/artefacts/report.html", headers=auth)
    assert response.status_code == 501


def test_a_run_stored_by_the_cli_is_the_run_the_api_serves(
    client: TestClient,
    auth: dict[str, str],
    store: MemoryStore,
    tenant: Tenant,
    project: dict[str, Any],
    mode_a_payload: dict[str, Any],
) -> None:
    """One payload, four consumers — the disk, the page, the database and now the wire.

    `json.dumps` on both sides rather than a dictionary comparison, because equality
    between dictionaries would pass on a payload that is not serialisable, which is
    exactly the defect 5.1b found in Mode B's infinite dispersion ratio.
    """
    run = store.store_run(tenant.id, uuid_of(project), mode_a_payload)

    served = client.get(f"/runs/{run.id}", headers=auth).json()["payload"]

    assert json.dumps(served, sort_keys=True) == json.dumps(
        mode_a_payload, sort_keys=True
    )


# -- helpers -------------------------------------------------------------------


def uuid_of(record: dict[str, Any]):
    from uuid import UUID

    return UUID(record["id"])


def write_artefact(
    store: MemoryStore,
    tenant: Tenant,
    run_id: Any,
    settings: ApiSettings,
    content: bytes,
) -> Artefact:
    """Put a real file inside the allow-list and register it, as the CLI import does."""
    assert settings.artefact_root is not None
    path = settings.artefact_root / "report.html"
    path.write_bytes(content)
    return store.add_artefact(
        Artefact(
            tenant_id=tenant.id,
            run_id=run_id,
            kind=ArtefactKind.REPORT_HTML,
            uri=path.resolve().as_uri(),
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )
    )
