-- migrations_partition_old_jobs.sql — OPTIONAL, advanced. Run manually, only once
-- old_jobs has grown large enough that archiving/reads are slow.
--
-- Postgres can't partition an existing table in place — this rebuilds old_jobs
-- as a partitioned table (RANGE on moved_at, monthly). Review row counts and
-- take a backup/snapshot before running. Not auto-applied by the app.

BEGIN;

ALTER TABLE old_jobs RENAME TO old_jobs_unpartitioned;

CREATE TABLE old_jobs (
  LIKE old_jobs_unpartitioned
) PARTITION BY RANGE (moved_at);

-- Seed a few months of partitions; add more as needed (one per month going forward).
CREATE TABLE IF NOT EXISTS old_jobs_y2026m05 PARTITION OF old_jobs
  FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE IF NOT EXISTS old_jobs_y2026m06 PARTITION OF old_jobs
  FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
CREATE TABLE IF NOT EXISTS old_jobs_y2026m07 PARTITION OF old_jobs
  FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
CREATE TABLE IF NOT EXISTS old_jobs_default PARTITION OF old_jobs DEFAULT;

INSERT INTO old_jobs SELECT * FROM old_jobs_unpartitioned;

CREATE INDEX IF NOT EXISTS idx_old_jobs_moved_at ON old_jobs (moved_at DESC);

-- Once verified: DROP TABLE old_jobs_unpartitioned;

COMMIT;

-- Ongoing maintenance: create next month's partition before it starts, e.g.
-- CREATE TABLE old_jobs_y2026m08 PARTITION OF old_jobs
--   FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
