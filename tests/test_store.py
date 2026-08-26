"""Step 5.1b — storage, checked the same way against both backends.

Every test here is parametrised over `MemoryStore` and `PostgresStore`. That is the
point of the file: an in-memory stand-in tested only by itself drifts from the database
it stands in for, and every drift is a defect that appears in production and nowhere
else. If a rule matters — tenancy, payload validation, what `NotFound` discloses — it is
asserted against both or it is not asserted.

The Postgres half skips when `$ROADRISK_DATABASE_URL` is unset, which is the honest
behaviour for a package whose engine needs no database. The skip is loud rather than
silent, because a suite that quietly stops covering the backend it ships is worse than
one that never covered it.
"""

from __future__ import annotations

import json
import os
from typing import Any
from uuid import uuid4

import pytest

from roadrisk.core.engine import assess
from roadrisk.demo import synthetic_panel
from roadrisk.report import build_run
from roadrisk.store import (
    Artefact,
    ArtefactKind,
    Corridor,
    InUse,
    Job,
    JobStatus,
    MemoryStore,
    NotFound,
    PayloadRejected,
    Project,
    Tenant,
)

DSN = os.environ.get("ROADRISK_DATABASE_URL")

TABLES = ("artefact", "run", "job", "corridor", "project", "tenant")


@pytest.fixture(scope="session")
def mode_a_payload() -> dict[str, Any]:
    """A genuine run. Fixtures made of hand-written dictionaries prove nothing here."""
    return build_run(assess(synthetic_panel(n_units=25, n_periods=8, seed=4)))


@pytest.fixture(scope="session")
def mode_b_payload() -> dict[str, Any]:
    """A refused panel. Mode B is the floor, and a job carrying one still succeeded."""
    panel = synthetic_panel(n_units=25, n_periods=8, seed=4)
    return build_run(assess(panel[panel["n_crashes"] == 0]))


@pytest.fixture(scope="session")
def postgres_session():
    """One migrated, emptied database for the session, or a skip that says why."""
    if not DSN:
        pytest.skip(
            "ROADRISK_DATABASE_URL is not set, so the Postgres backend is not "
            "exercised. Set it to e.g. postgresql:///roadrisk to run these."
        )
    psycopg = pytest.importorskip("psycopg")
    from roadrisk.store.postgres import PostgresStore

    connection = psycopg.connect(DSN)
    store = PostgresStore(connection)
    store.migrate()
    with connection.cursor() as cursor:
        cursor.execute(f"TRUNCATE {', '.join(TABLES)} CASCADE")
    connection.commit()
    yield store
    store.close()


@pytest.fixture(params=["memory", "postgres"])
def store(request):
    """Both backends, one test body."""
    if request.param == "memory":
        return MemoryStore()
    return request.getfixturevalue("postgres_session")


@pytest.fixture
def tenant(store) -> Tenant:
    """A fresh tenant per test, so the shared Postgres session cannot cross-talk."""
    return store.create_tenant(Tenant(name=f"tenant-{uuid4().hex[:8]}"))


@pytest.fixture
def project(store, tenant) -> Project:
    return store.create_project(Project(tenant_id=tenant.id, name="cyprus"))


# -- the done-when -------------------------------------------------------------


def test_a_stored_run_re_renders_with_no_refit(store, tenant, project, mode_a_payload):
    """Step 5.1b's done-when, and the whole reason the contract came first.

    Nothing is fitted here. The payload goes in, comes back out of storage, and renders
    to the same report a client would have been handed — with no engine object anywhere
    in scope, months or engine versions later.
    """
    from roadrisk.report import render_report

    stored = store.store_run(tenant.id, project.id, mode_a_payload)
    read_back = store.get_run(tenant.id, stored.id)

    assert read_back.payload == mode_a_payload

    html = render_report(read_back.payload)
    assert html.lstrip().startswith("<!doctype html")
    assert read_back.payload["assessment"]["manifest"]["fingerprint"] in html


def test_the_payload_survives_a_json_round_trip(store, tenant, project, mode_a_payload):
    """Postgres hands back parsed `jsonb`, not the bytes it was given.

    `jsonb` is a normalised representation: it sorts object keys by length and then
    bytewise, drops duplicates and canonicalises numbers. So a re-rendered report is not
    byte-identical to the original — the embedded JSON has `corridor` before
    `assessment`, because it is shorter — while being the same document. Every *value*
    must survive exactly, which is what this compares.

    The alternative column type, `json`, preserves the text verbatim and cannot be
    indexed. Indexing is worth more here than byte-identity, and nothing downstream
    hashes the rendered HTML — the reproducibility fingerprint is a value inside the
    payload and comes back untouched.
    """
    stored = store.store_run(tenant.id, project.id, mode_a_payload)
    read_back = store.get_run(tenant.id, stored.id)

    assert read_back.payload == mode_a_payload
    assert json.dumps(read_back.payload, sort_keys=True) == json.dumps(
        mode_a_payload, sort_keys=True
    )
    assert (
        read_back.payload["assessment"]["manifest"]["fingerprint"]
        == mode_a_payload["assessment"]["manifest"]["fingerprint"]
    )


# -- tenancy -------------------------------------------------------------------


def test_one_tenant_cannot_read_anothers_rows(store, tenant, project, mode_a_payload):
    """5.1b's half of "two tenants cannot see each other's runs".

    This is the application-level half. 5.4a puts row-level policies underneath it so
    the database refuses rather than trusting the query — but the schema and the
    interface have to make the filter unforgettable first, which is what this asserts.
    """
    mine = store.store_run(tenant.id, project.id, mode_a_payload)
    corridor = store.create_corridor(
        Corridor(tenant_id=tenant.id, project_id=project.id, name="B9", ref="B9")
    )
    job = store.create_job(Job(tenant_id=tenant.id, project_id=project.id))

    intruder = store.create_tenant(Tenant(name="intruder"))

    for call in (
        lambda: store.get_run(intruder.id, mine.id),
        lambda: store.get_project(intruder.id, project.id),
        lambda: store.get_corridor(intruder.id, corridor.id),
        lambda: store.get_job(intruder.id, job.id),
    ):
        with pytest.raises(NotFound):
            call()

    assert store.list_runs(intruder.id) == []
    assert store.list_projects(intruder.id) == []


def test_not_found_does_not_reveal_that_a_row_exists(
    store, tenant, project, mode_a_payload
):
    """Absent and someone-else's must be indistinguishable.

    Telling them apart tells a caller whether an id is real, which turns a list of
    guessed identifiers into a census of another tenant's runs.
    """
    mine = store.store_run(tenant.id, project.id, mode_a_payload)
    intruder = store.create_tenant(Tenant(name="intruder"))

    with pytest.raises(NotFound) as theirs:
        store.get_run(intruder.id, mine.id)
    with pytest.raises(NotFound) as nothing:
        store.get_run(intruder.id, uuid4())

    assert type(theirs.value) is type(nothing.value)
    assert "exist" not in str(theirs.value).lower()


# -- the payload boundary ------------------------------------------------------


def test_a_malformed_payload_is_refused_on_the_way_in(store, tenant, project):
    """The boundary is the write, not the read.

    A store that accepted a malformed payload would hand the problem to whoever read it
    back — months later, probably in front of a client — so it is refused here, with the
    failing path named rather than a bare "invalid".
    """
    with pytest.raises(PayloadRejected) as caught:
        store.store_run(tenant.id, project.id, {"assessment": {"mode": "A"}})
    assert "assessment" in str(caught.value)

    with pytest.raises(PayloadRejected):
        store.store_run(tenant.id, project.id, {})


def test_a_payload_with_an_undeclared_field_is_refused(
    store, tenant, project, mode_a_payload
):
    """5.1a's `extra="forbid"`, enforced at the storage boundary too."""
    drifted = {**mode_a_payload, "invented_by_a_future_engine": True}
    with pytest.raises(PayloadRejected):
        store.store_run(tenant.id, project.id, drifted)


def test_indexed_columns_are_read_from_the_payload_not_supplied(
    store, tenant, project, mode_a_payload
):
    """They are copies, so the only safe source is the thing being copied.

    There is no parameter for mode, rung or fingerprint anywhere in `store_run`. That
    absence is the guarantee: a row cannot describe a different run than its payload,
    because nobody is in a position to tell it to.
    """
    stored = store.store_run(tenant.id, project.id, mode_a_payload)
    assessment = mode_a_payload["assessment"]

    assert stored.mode == assessment["mode"]
    assert stored.rung == assessment["rung"]
    assert stored.fingerprint == assessment["manifest"]["fingerprint"]
    assert stored.engine_version == mode_a_payload["engine_version"]
    assert stored.schema_version == mode_a_payload["schema_version"]


def test_mode_b_is_stored_and_is_not_an_error(store, tenant, project, mode_b_payload):
    """A refusal is a result. Mode B goes in like anything else, on a job that succeeded.

    The vocabulary matters here: `failed` is the machinery breaking. A run that refused
    Mode A and descended is a finding, and a store that filed it as an error would put
    the engine's honesty into a log nobody reads.
    """
    job = store.create_job(Job(tenant_id=tenant.id, project_id=project.id))
    stored = store.store_run(tenant.id, project.id, mode_b_payload, job_id=job.id)
    assert stored.mode == "B"

    finished = store.update_job_status(tenant.id, job.id, JobStatus.SUCCEEDED)
    assert finished.status is JobStatus.SUCCEEDED
    assert finished.error is None
    assert finished.finished_at is not None


# -- jobs ----------------------------------------------------------------------


def test_a_job_moves_through_its_states_and_stamps_them(store, tenant, project):
    job = store.create_job(
        Job(tenant_id=tenant.id, project_id=project.id, params={"bayes": True})
    )
    assert job.status is JobStatus.QUEUED
    assert job.params == {"bayes": True}
    assert job.started_at is None

    running = store.update_job_status(tenant.id, job.id, JobStatus.RUNNING)
    assert running.started_at is not None
    assert running.finished_at is None

    failed = store.update_job_status(
        tenant.id, job.id, JobStatus.FAILED, error="Overpass returned 429"
    )
    assert failed.status is JobStatus.FAILED
    assert failed.error == "Overpass returned 429"
    assert failed.finished_at is not None
    assert failed.started_at == running.started_at


def test_a_job_belonging_to_another_tenant_cannot_be_advanced(store, tenant, project):
    job = store.create_job(Job(tenant_id=tenant.id, project_id=project.id))
    intruder = store.create_tenant(Tenant(name="intruder"))
    with pytest.raises(NotFound):
        store.update_job_status(intruder.id, job.id, JobStatus.SUCCEEDED)


# -- artefacts -----------------------------------------------------------------


def test_artefacts_are_stored_by_reference_never_as_bytes(
    store, tenant, project, mode_a_payload
):
    """A report is a third of a megabyte and regenerable. The database keeps the address.

    The record has no field for content, which is the enforcement: `uri` is a `file://`
    path today and an object-store URL at 6.2, and nothing else changes when it does.
    """
    run = store.store_run(tenant.id, project.id, mode_a_payload)
    added = store.add_artefact(
        Artefact(
            tenant_id=tenant.id,
            run_id=run.id,
            kind=ArtefactKind.REPORT_HTML,
            uri="file:///runs/abc/report.html",
            size_bytes=338_145,
            sha256="0" * 64,
        )
    )
    assert not hasattr(added, "content")
    assert not hasattr(added, "bytes")

    listed = store.list_artefacts(tenant.id, run.id)
    assert [a.id for a in listed] == [added.id]
    assert listed[0].kind is ArtefactKind.REPORT_HTML

    intruder = store.create_tenant(Tenant(name="intruder"))
    with pytest.raises(NotFound):
        store.list_artefacts(intruder.id, run.id)


# -- editing and deleting ------------------------------------------------------
#
# Added at 5.1c, because "project and corridor CRUD" over HTTP needs a U and a D under
# it. Both are parametrised over the two backends like everything else here: an update
# that commits in one and not the other is exactly the class of defect this file exists
# to catch, and it is one the Postgres helpers make easy to write by accident.


def test_an_update_survives_being_read_back(store, tenant, project):
    """Not "the method returned the new name" — that a *later read* sees it.

    Which is the whole test. `PostgresStore._maybe` does not commit; it is the read
    helper. An `UPDATE ... RETURNING` run through it returns the new row, stays visible
    to the connection that wrote it, and is rolled back when that connection closes. A
    test that only inspected the return value would pass against a store that loses
    every edit.
    """
    store.update_project(
        tenant.id, project.model_copy(update={"name": "renamed", "spend_cap": 250.0})
    )
    reread = store.get_project(tenant.id, project.id)
    assert (reread.name, reread.spend_cap) == ("renamed", 250.0)


def test_an_update_cannot_move_a_row_between_tenants(store, tenant, project):
    """`tenant_id` identifies the row; it is not one of the fields being replaced."""
    intruder = store.create_tenant(Tenant(name="intruder"))
    with pytest.raises(NotFound):
        store.update_project(
            intruder.id, project.model_copy(update={"name": "mine now"})
        )
    assert store.get_project(tenant.id, project.id).name == "cyprus"


def test_a_corridor_update_replaces_the_box_and_clears_it(store, tenant, project):
    corridor = store.create_corridor(
        Corridor(
            tenant_id=tenant.id,
            project_id=project.id,
            name="B9",
            ref="B9",
            bbox=(34.6, 32.9, 35.1, 33.5),
        )
    )
    widened = store.update_corridor(
        tenant.id, corridor.model_copy(update={"bbox": (34.0, 32.0, 36.0, 34.0)})
    )
    assert widened.bbox == (34.0, 32.0, 36.0, 34.0)

    cleared = store.update_corridor(
        tenant.id, corridor.model_copy(update={"bbox": None, "ref": None})
    )
    assert store.get_corridor(tenant.id, cleared.id).bbox is None


def test_deleting_a_project_that_holds_a_run_is_refused_and_names_what(
    store, tenant, project, mode_a_payload
):
    """The guard against migration 0001's own cascade.

    `project` references down through corridor, job and run with `ON DELETE CASCADE`,
    which is right for dropping a tenant and catastrophic for one careless request: a
    single statement destroys every stored assessment filed under it, and a stored run
    is what a client paid for. So the delete is guarded in the store — in both
    backends, so no caller can reach past it — and the refusal says what is still
    there, because "cannot delete" is not something anybody can act on.
    """
    store.store_run(tenant.id, project.id, mode_a_payload)

    with pytest.raises(InUse) as caught:
        store.delete_project(tenant.id, project.id)
    assert "1 run" in str(caught.value)

    assert store.get_project(tenant.id, project.id).id == project.id
    assert len(store.list_runs(tenant.id, project.id)) == 1


def test_deleting_a_corridor_a_run_points_at_is_refused(
    store, tenant, project, mode_a_payload
):
    """Even though the schema would allow it, and nothing would be destroyed.

    `run.corridor_id` is `ON DELETE SET NULL`, so a cascade here loses no rows. What it
    loses is the *link*: the run keeps its geometry inside the payload and quietly stops
    being filed against the road it describes.
    """
    corridor = store.create_corridor(
        Corridor(tenant_id=tenant.id, project_id=project.id, name="N201")
    )
    store.store_run(tenant.id, project.id, mode_a_payload, corridor_id=corridor.id)

    with pytest.raises(InUse) as caught:
        store.delete_corridor(tenant.id, corridor.id)
    assert "1 run" in str(caught.value)
    assert store.get_corridor(tenant.id, corridor.id).id == corridor.id


def test_an_empty_project_deletes_and_then_reads_as_absent(store, tenant):
    empty = store.create_project(Project(tenant_id=tenant.id, name="mistake"))
    store.delete_project(tenant.id, empty.id)
    with pytest.raises(NotFound):
        store.get_project(tenant.id, empty.id)
    assert empty.id not in {p.id for p in store.list_projects(tenant.id)}


def test_deleting_another_tenants_project_is_a_not_found_not_a_delete(store, tenant):
    """The disclosure rule holds on the write path too.

    A delete that said "forbidden" for somebody else's id and "not found" for a
    fictional one would turn guessing into a census, which is the whole reason
    `NotFound` refuses to distinguish the two.
    """
    intruder = store.create_tenant(Tenant(name="intruder"))
    theirs = store.create_project(Project(tenant_id=intruder.id, name="theirs"))

    with pytest.raises(NotFound):
        store.delete_project(tenant.id, theirs.id)
    assert store.get_project(intruder.id, theirs.id).id == theirs.id


# -- referential integrity -----------------------------------------------------


def test_a_run_cannot_be_filed_under_a_project_that_is_not_yours(
    store, tenant, mode_a_payload
):
    """Carrying `tenant_id` on every row raises its own question: what stops a row
    naming one tenant while its parent names another?

    A plain `REFERENCES project (id)` does not — it checks the project exists, not that
    it is yours, so the insert succeeds and every single-table query goes on looking
    correct. This test caught exactly that: it passed against `MemoryStore`, which
    checks the parent explicitly, and failed against Postgres, which did not. The schema
    now uses composite `(tenant_id, project_id)` references, so crossing tenants is a
    row the database refuses rather than a mistake the application must remember not to
    make.
    """
    intruder = store.create_tenant(Tenant(name="intruder"))
    theirs = store.create_project(Project(tenant_id=intruder.id, name="theirs"))
    with pytest.raises(Exception) as caught:
        store.store_run(tenant.id, theirs.id, mode_a_payload)
    assert not isinstance(caught.value, AssertionError)


def test_a_corridor_cannot_be_filed_under_a_project_that_is_not_yours(store, tenant):
    """The same hole, one table over. Every parent reference is tenant-scoped."""
    intruder = store.create_tenant(Tenant(name="intruder"))
    theirs = store.create_project(Project(tenant_id=intruder.id, name="theirs"))
    with pytest.raises(Exception) as caught:
        store.create_corridor(
            Corridor(tenant_id=tenant.id, project_id=theirs.id, name="B9")
        )
    assert not isinstance(caught.value, AssertionError)


def test_a_job_cannot_point_at_another_tenants_corridor(store, tenant, project):
    """And once more for the optional reference, which is the easiest one to forget."""
    intruder = store.create_tenant(Tenant(name="intruder"))
    theirs_project = store.create_project(
        Project(tenant_id=intruder.id, name="theirs")
    )
    theirs = store.create_corridor(
        Corridor(tenant_id=intruder.id, project_id=theirs_project.id, name="N201")
    )
    with pytest.raises(Exception) as caught:
        store.create_job(
            Job(tenant_id=tenant.id, project_id=project.id, corridor_id=theirs.id)
        )
    assert not isinstance(caught.value, AssertionError)


def test_listing_is_newest_first_and_scoped(store, tenant, project, mode_a_payload):
    first = store.store_run(tenant.id, project.id, mode_a_payload)
    second = store.store_run(tenant.id, project.id, mode_a_payload)

    listed = store.list_runs(tenant.id, project.id)
    assert [r.id for r in listed[:2]] == [second.id, first.id]
    assert store.list_runs(tenant.id, project.id, limit=1) == listed[:1]


# -- non-finite floats ---------------------------------------------------------


def test_a_mode_b_payload_is_storable_at_all(store, tenant, project, mode_b_payload):
    """The defect this step found, pinned where it was found.

    A crash-free panel has mean zero, so its variance-to-mean ratio is infinite, and it
    lands in the run log. Python writes that as a bare `Infinity`, which is a Python
    extension and not JSON — so `jsonb` refused the insert outright, and the sidecar
    `run.json` written to disk could not be parsed by the report's own file picker.
    Payloads are sanitised at assembly now; this is the test that would have caught it.
    """
    from roadrisk.contract import non_finite_paths

    assert non_finite_paths(mode_b_payload) == []
    stored = store.store_run(tenant.id, project.id, mode_b_payload)
    assert store.get_run(tenant.id, stored.id).payload == mode_b_payload


def test_a_payload_carrying_infinity_is_stored_as_null(store, tenant, project, mode_a_payload):
    """A payload assembled by hand has not been through `build_run`. Belt to the braces."""
    from roadrisk.contract import non_finite_paths

    hand_made = json.loads(json.dumps(mode_a_payload))
    hand_made["assessment"]["log"].append(
        {
            "sequence": 999,
            "timestamp": "2026-01-01T00:00:00Z",
            "level": "info",
            "stage": "test",
            "code": "planted",
            "message": "a ratio with nothing in the denominator",
            "data": {"ratio": float("inf")},
        }
    )
    assert non_finite_paths(hand_made)

    stored = store.store_run(tenant.id, project.id, hand_made)
    read_back = store.get_run(tenant.id, stored.id)
    assert non_finite_paths(read_back.payload) == []
    assert read_back.payload["assessment"]["log"][-1]["data"]["ratio"] is None


# -- migrations ----------------------------------------------------------------


def test_migrations_are_ordered_and_hashed():
    from roadrisk.store import discover

    found = discover()
    assert found, "no migrations on disk"
    assert [m.version for m in found] == sorted(m.version for m in found)
    assert all(len(m.sha256) == 64 for m in found)
    assert all(m.version.isdigit() for m in found), "versions must be zero-padded digits"


def test_migrating_twice_applies_nothing_the_second_time(postgres_session):
    """Idempotent, or a deploy that retries becomes a deploy that breaks."""
    assert postgres_session.migrate() == []


def test_a_changed_migration_is_refused_rather_than_reapplied(postgres_session, tmp_path):
    """A database that has silently diverged from the file describing it is the worst case.

    Re-running would not reconcile them, and `IF NOT EXISTS` would make it look like it
    had. So the mismatch is refused, naming the file.
    """
    from roadrisk.store import MigrationMismatch, discover, migrate

    real = discover()[0]
    edited = tmp_path / f"{real.version}_initial.sql"
    edited.write_text(real.sql + "\n-- a later hand edit\n", encoding="utf-8")

    with pytest.raises(MigrationMismatch) as caught:
        migrate(postgres_session._connection, tmp_path)
    assert real.version in str(caught.value)
