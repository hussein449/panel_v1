-- Step 2.9 — where a run is, as four indexed numbers.
--
-- The geometry has been persisted since 5.1b: it is inside `payload`, which is what lets
-- a stored run re-render months later with no refit. What had no query behind it was
-- *finding* a run by where it is — every listing was by tenant and project. These four
-- columns are lifted from the centreline on insert, exactly as `mode`, `rung` and
-- `fingerprint` are, so a row cannot describe a different road than the one it holds.
--
-- **Not PostGIS.** A geometry column and a GiST index answer predicates this product does
-- not yet ask — distance to a point, intersection with a polygon — and they would put a
-- database extension between an operator and a working install. Every spatial question
-- the web layer actually asks is *which runs overlap this view*, which is four
-- comparisons. When the hazard layers arrive and the question becomes *which runs
-- intersect this flood outline*, that is when a geometry column earns its extension.

ALTER TABLE run
    ADD COLUMN IF NOT EXISTS extent_west  double precision,
    ADD COLUMN IF NOT EXISTS extent_south double precision,
    ADD COLUMN IF NOT EXISTS extent_east  double precision,
    ADD COLUMN IF NOT EXISTS extent_north double precision;

-- All four or none. A run with no geometry is not a run at an empty box, and half a box
-- is a filter that silently matches the wrong things.
ALTER TABLE run
    DROP CONSTRAINT IF EXISTS run_extent_whole;
ALTER TABLE run
    ADD CONSTRAINT run_extent_whole CHECK (
        num_nulls(extent_west, extent_south, extent_east, extent_north) IN (0, 4)
    );

-- The box has to be the right way up and on the planet. The engine cannot produce
-- anything else from a centreline, which is the point: if this ever fires, something
-- upstream has invented coordinates.
ALTER TABLE run
    DROP CONSTRAINT IF EXISTS run_extent_sane;
ALTER TABLE run
    ADD CONSTRAINT run_extent_sane CHECK (
        extent_west IS NULL OR (
            extent_west BETWEEN -180 AND 180 AND
            extent_east BETWEEN -180 AND 180 AND
            extent_south BETWEEN -90 AND 90 AND
            extent_north BETWEEN -90 AND 90 AND
            extent_west <= extent_east AND
            extent_south <= extent_north
        )
    );

-- Backfill, so that adding the column does not make every run stored before it
-- unfindable. The centreline is `payload -> corridor -> corridor -> geometry`, an array
-- of [lon, lat] pairs; a run with no corridor produces no rows here and keeps its nulls.
UPDATE run
SET extent_west  = box.west,
    extent_south = box.south,
    extent_east  = box.east,
    extent_north = box.north
FROM (
    SELECT r.id,
           min((point ->> 0)::double precision) AS west,
           min((point ->> 1)::double precision) AS south,
           max((point ->> 0)::double precision) AS east,
           max((point ->> 1)::double precision) AS north
    FROM run AS r,
         LATERAL jsonb_array_elements(
             r.payload -> 'corridor' -> 'corridor' -> 'geometry'
         ) AS point
    WHERE jsonb_typeof(r.payload -> 'corridor' -> 'corridor' -> 'geometry') = 'array'
    GROUP BY r.id
) AS box
WHERE run.id = box.id
  AND run.extent_west IS NULL;

-- One index for the one question: which of this tenant's runs overlap this view. Two
-- boxes overlap when neither is wholly to the side of the other, so both ends of both
-- axes are compared and the leading columns are what narrows first.
CREATE INDEX IF NOT EXISTS run_extent_idx
    ON run (tenant_id, extent_west, extent_east, extent_south, extent_north)
    WHERE extent_west IS NOT NULL;
