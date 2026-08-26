-- 0002 — how many times a job has been started, so a restart can reclaim it.
--
-- Step 5.1d put jobs in a thread pool inside the web process, and left a hole nobody
-- noticed until it was pointed at: a process that stops while a job is `running` leaves
-- that row `running` for ever. The runner deliberately refuses to start a job that is
-- not `queued` — that is what stops two runners producing two runs from one submission
-- — so nothing ever picks it up again, and `GET /jobs/{id}` goes on answering
-- "running, please wait" to a client who will wait for the rest of their life.
--
-- The inputs were never at risk: `params` holds the panel or the corridor reference, so
-- the work can simply be done again. What was missing was any way to know it should be.
--
-- `attempts` is what makes reclaiming safe rather than merely possible. Without it, a
-- job whose own execution is what killed the process would be requeued on every start,
-- and the service would sit in a loop, taking itself down over and over, on a schedule
-- set by the thing it cannot survive. With it, reclaiming gives up and says so.
--
-- Not a heartbeat, and not a lease owner. Both are the right answer for many workers on
-- many machines, and both are step 5.2a's to add along with Celery. This column is the
-- honest amount of machinery for the deployment that exists: one process, started by
-- `roadrisk serve`, where everything still `running` at startup is by definition
-- nobody's.

ALTER TABLE job ADD COLUMN IF NOT EXISTS attempts integer NOT NULL DEFAULT 0;

-- Reclaiming reads `status = 'running'` across every tenant — the one operator-level
-- query in this schema that is not tenant-scoped, because a process restarting does not
-- belong to a tenant. Partial, because the rows it looks for are a handful at most and
-- only ever at startup.
CREATE INDEX IF NOT EXISTS job_running_idx ON job (started_at) WHERE status = 'running';
