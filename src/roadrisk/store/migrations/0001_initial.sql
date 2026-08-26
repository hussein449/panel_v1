-- 0001 — the initial schema.
--
-- Written for step 5.1b. Two decisions in here are load-bearing and are recorded where
-- they are made rather than in a document that can drift from them.
--
-- 1. `tenant_id` is on EVERY table, including the ones where it is derivable by a join.
--    A corridor belongs to a project and a project belongs to a tenant, so the column
--    is redundant in the normalised sense. It is not redundant in the sense that
--    matters: a query that forgets a join returns another tenant's rows and looks
--    healthy doing it, and step 5.4a's row-level policies need a column on the table
--    being read rather than a path back to one. Retro-fitting this later would mean
--    rewriting every query and every test written against them in between.
--
--    Carrying the column raises its own question — what stops a row naming one tenant
--    while its parent names another? A plain `REFERENCES project (id)` does not: it
--    checks the project exists, not that it is yours, so a run could be filed under
--    somebody else's project and every single-table query would keep looking correct.
--    So every reference here is COMPOSITE, `(tenant_id, parent_id)` against a parent
--    keyed the same way. Crossing tenants is then not a mistake the application must
--    avoid making; it is a row the database will not accept.
--
-- 2. The run payload is `jsonb` and it is the source of truth. Every scalar column on
--    `run` is a copy of something inside it, lifted so a list can be drawn without
--    opening 300 kB of JSON per row. They are written from the payload on insert and
--    never supplied by a caller, so they cannot describe a different run than the one
--    stored.
--
-- Postgres, not PostGIS. Nothing here holds geometry: a corridor stores the *request*
-- that produces one, and the resolved centreline lives inside the run payload with the
-- rest of what that particular fetch found. The extension arrives when there is a
-- spatial query to run — the flood and fire overlay of the call topic's fourth outcome
-- — and not before, so that it is a decision rather than a drift.

CREATE TABLE IF NOT EXISTS tenant (
    id          uuid PRIMARY KEY,
    name        text        NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS project (
    id          uuid PRIMARY KEY,
    tenant_id   uuid        NOT NULL REFERENCES tenant (id) ON DELETE CASCADE,
    name        text        NOT NULL,
    -- Whole currency units. Null is uncapped, and is a choice somebody made rather
    -- than a default nobody noticed. 5.2b's runner reads this before the call that
    -- would breach it, not after.
    spend_cap   double precision,
    created_at  timestamptz NOT NULL DEFAULT now(),

    -- Redundant given the primary key, and required: it is what lets children
    -- reference (tenant_id, project_id) together rather than project_id alone.
    UNIQUE (tenant_id, id)
);

CREATE INDEX IF NOT EXISTS project_tenant_idx ON project (tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS corridor (
    id             uuid PRIMARY KEY,
    tenant_id      uuid        NOT NULL REFERENCES tenant (id) ON DELETE CASCADE,
    project_id     uuid        NOT NULL,
    name           text        NOT NULL,
    -- OSM road reference, e.g. 'B9'. Null when the centreline came from the client.
    ref            text,
    -- south, west, north, east in degrees. Four columns rather than a box type,
    -- because nothing here does geometry yet and a float is honest about that.
    bbox_south     double precision,
    bbox_west      double precision,
    bbox_north     double precision,
    bbox_east      double precision,
    unit_length_m  double precision NOT NULL DEFAULT 500.0,
    created_at     timestamptz NOT NULL DEFAULT now(),

    -- Either all four or none. A half-specified box is a corridor nobody can fetch,
    -- and it is cheaper to refuse it here than to discover it in a worker.
    CONSTRAINT corridor_bbox_all_or_nothing CHECK (
        num_nonnulls(bbox_south, bbox_west, bbox_north, bbox_east) IN (0, 4)
    ),

    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, project_id)
        REFERENCES project (tenant_id, id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS corridor_project_idx
    ON corridor (tenant_id, project_id, created_at DESC);

CREATE TABLE IF NOT EXISTS job (
    id           uuid PRIMARY KEY,
    tenant_id    uuid        NOT NULL REFERENCES tenant (id) ON DELETE CASCADE,
    project_id   uuid        NOT NULL,
    corridor_id  uuid,
    -- 'succeeded' means the job ran to completion, NOT that Mode A was reached. A run
    -- that descended to Mode B, dropped a term or refused an unsourced weight
    -- succeeded — those are findings it carries. 'failed' is the machinery breaking;
    -- 'rejected' is the panel breaking the input contract, where nothing malfunctioned
    -- and the receipt naming the column is the entire result.
    status       text        NOT NULL DEFAULT 'queued',
    params       jsonb       NOT NULL DEFAULT '{}'::jsonb,
    error        text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    started_at   timestamptz,
    finished_at  timestamptz,

    CONSTRAINT job_status_known CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed', 'rejected')
    ),

    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, project_id)
        REFERENCES project (tenant_id, id) ON DELETE CASCADE,
    -- MATCH SIMPLE, the default: with corridor_id null the reference is not checked,
    -- which is what an optional parent means. It is never half-checked.
    FOREIGN KEY (tenant_id, corridor_id)
        REFERENCES corridor (tenant_id, id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS job_project_idx
    ON job (tenant_id, project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS job_status_idx ON job (status) WHERE status IN ('queued', 'running');

CREATE TABLE IF NOT EXISTS run (
    id              uuid PRIMARY KEY,
    tenant_id       uuid        NOT NULL REFERENCES tenant (id) ON DELETE CASCADE,
    project_id      uuid        NOT NULL,
    job_id          uuid,
    corridor_id     uuid,

    -- The payload's own shape version, not the engine's. It moves when the shape
    -- changes, which is what lets a reader tell whether it still knows how to read a
    -- run stored months ago before it tries to.
    schema_version  text,
    engine_version  text        NOT NULL,
    fingerprint     text        NOT NULL,
    mode            text        NOT NULL,
    rung            text        NOT NULL,

    payload         jsonb       NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT run_mode_known CHECK (mode IN ('A', 'B')),

    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, project_id)
        REFERENCES project (tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, job_id)
        REFERENCES job (tenant_id, id) ON DELETE SET NULL,
    FOREIGN KEY (tenant_id, corridor_id)
        REFERENCES corridor (tenant_id, id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS run_project_idx
    ON run (tenant_id, project_id, created_at DESC);
-- Two identical runs share a fingerprint. Worth finding without opening either.
CREATE INDEX IF NOT EXISTS run_fingerprint_idx ON run (tenant_id, fingerprint);

CREATE TABLE IF NOT EXISTS artefact (
    id          uuid PRIMARY KEY,
    tenant_id   uuid        NOT NULL REFERENCES tenant (id) ON DELETE CASCADE,
    run_id      uuid        NOT NULL,
    -- What the file is. The bytes are never in here: a report is a third of a megabyte,
    -- a PDF more, and both are regenerable from the payload. What is kept is where it
    -- went, how big it was, and what it hashed to.
    kind        text        NOT NULL,
    uri         text        NOT NULL,
    size_bytes  bigint      NOT NULL,
    sha256      text        NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT artefact_kind_known CHECK (
        kind IN ('report.html', 'report.pdf', 'run.json', 'ranking.csv')
    ),

    FOREIGN KEY (tenant_id, run_id) REFERENCES run (tenant_id, id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS artefact_run_idx ON artefact (tenant_id, run_id);
