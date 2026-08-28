-- A road that has a name and no reference.
--
-- `ref` was the only way to identify a road, because `geo/osm.py` fetched by `ref` and
-- nothing else. That is right for the roads this product was aimed at — trunk, primary,
-- most secondary carry one — and it put every residential and urban street out of reach
-- entirely, which the map picker makes obvious the moment somebody clicks one.
--
-- So a corridor now records *which tag* identified it. The column is `osm_name` rather
-- than `name`, because `name` is already this table's own human label for the corridor
-- and the two are different things: a corridor called "Kings Road, north section" may be
-- fetched by `osm_name = 'Kings Road'`.
--
-- **Why a name is allowed at all, given the rule it appears to weaken.** `ref='B9'`
-- cannot return anything that is not the B9, and that guarantee is the reason routing
-- was rejected in 2.2b. A name carries no such guarantee — but the fetch does not rely
-- on the guarantee. It relies on the fragmentation gate: two unrelated High Streets in
-- one box produce a collection whose longest run carries about half the length, and that
-- is refused with a message saying so. The name floor is higher than the reference floor
-- for exactly this reason. See `MIN_LONGEST_SHARE_NAME`.

ALTER TABLE corridor
    ADD COLUMN IF NOT EXISTS osm_name text;

-- One selector, or none. Both set is not a corridor that is doubly identified — it is a
-- row where nothing can say which query produced the centreline, and two runs of it a
-- month apart could resolve different roads. None set is still legal: that is the
-- client-supplied centreline the `ref` column has always allowed for.
-- This one cannot fail on data already here: every existing row has `osm_name` null, so
-- the count is whatever `ref` alone contributes, which is 0 or 1.
ALTER TABLE corridor
    DROP CONSTRAINT IF EXISTS corridor_one_selector;
ALTER TABLE corridor
    ADD CONSTRAINT corridor_one_selector CHECK (
        num_nonnulls(ref, osm_name) <= 1
    );

-- **A selector-needs-a-box constraint deliberately is not here.** A corridor with a
-- reference and no bounding box is unfetchable and the API refuses to create one — but
-- rows like that may already exist, written before that check did, and a migration whose
-- CHECK fails on data already in the table does not report a design problem. It aborts,
-- and takes the whole upgrade with it. The refusal belongs at submit, where it can name
-- the field and the row does not exist yet.

