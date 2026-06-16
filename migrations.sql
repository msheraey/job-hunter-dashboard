-- migrations.sql — Run ONCE in Supabase SQL Editor before deploying this build.
-- Safe to re-run (IF NOT EXISTS everywhere).

-- Skip/Applied buttons
ALTER TABLE user_job_matches ADD COLUMN IF NOT EXISTS status text DEFAULT 'new';
ALTER TABLE user_job_matches ADD COLUMN IF NOT EXISTS match_reason text;

-- Rich job classification (filled by scorer on first score)
ALTER TABLE job_pool ADD COLUMN IF NOT EXISTS seniority text;
ALTER TABLE job_pool ADD COLUMN IF NOT EXISTS remote_status text;
ALTER TABLE job_pool ADD COLUMN IF NOT EXISTS visa_likelihood text;
ALTER TABLE job_pool ADD COLUMN IF NOT EXISTS industry text;

-- Embeddings: schema-ready, pipeline deferred (decision June 11)
CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE job_pool ADD COLUMN IF NOT EXISTS embedding vector(384);
ALTER TABLE users    ADD COLUMN IF NOT EXISTS cv_embedding vector(384);

-- Job-site account linking (scaffold; auto-apply phase)
CREATE TABLE IF NOT EXISTS user_linked_accounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  site text NOT NULL CHECK (site IN ('linkedin','indeed','bayt','naukrigulf','gulftalent')),
  status text NOT NULL DEFAULT 'unlinked' CHECK (status IN ('unlinked','linked','expired')),
  linked_at timestamptz,
  meta jsonb,
  UNIQUE (user_id, site)
);

-- Notification preferences (pipeline flags live in env; per-user prefs here)
ALTER TABLE users ADD COLUMN IF NOT EXISTS notify_pref text DEFAULT 'daily';
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_active timestamptz;

-- quality_score on matches (mirrors job_pool.quality_score; lets frontend query it directly)
ALTER TABLE user_job_matches ADD COLUMN IF NOT EXISTS quality_score int;

-- created_at timestamp for analytics
ALTER TABLE user_job_matches ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now();

-- Application tracking: extended statuses + free-text notes per match
ALTER TABLE user_job_matches ADD COLUMN IF NOT EXISTS interview_date timestamptz;
ALTER TABLE user_job_matches ADD COLUMN IF NOT EXISTS notes text;

-- Job pool enrichments from premium features
ALTER TABLE job_pool ADD COLUMN IF NOT EXISTS salary_min_aed int;
ALTER TABLE job_pool ADD COLUMN IF NOT EXISTS salary_max_aed int;
ALTER TABLE job_pool ADD COLUMN IF NOT EXISTS summary_bullets text;  -- JSON array cached here
ALTER TABLE job_pool ADD COLUMN IF NOT EXISTS link_active boolean DEFAULT true;

-- Indexes — hot read paths (per-title counts, archiving scan, match board/refresh queries)
CREATE INDEX IF NOT EXISTS idx_job_pool_search_keyword ON job_pool (search_keyword);
CREATE INDEX IF NOT EXISTS idx_job_pool_posted_at ON job_pool (posted_at);
CREATE INDEX IF NOT EXISTS idx_ujm_user_status_score ON user_job_matches (user_id, status, score DESC);
CREATE INDEX IF NOT EXISTS idx_ujm_job_id ON user_job_matches (job_id);
CREATE INDEX IF NOT EXISTS idx_old_jobs_moved_at ON old_jobs (moved_at DESC);

-- SerpApi monthly quota tracking (free plan: 250 searches/month)
CREATE TABLE IF NOT EXISTS serpapi_usage (
  month text PRIMARY KEY,        -- 'YYYY-MM'
  call_count int NOT NULL DEFAULT 0,
  updated_at timestamptz DEFAULT now()
);

-- Centralized error capture (live-request + breaker failures that bare print()'d before)
CREATE TABLE IF NOT EXISTS error_log (
  id bigserial PRIMARY KEY,
  created_at timestamptz DEFAULT now(),
  source text NOT NULL,     -- e.g. 'matcher._user_titles', 'circuit_breaker'
  message text NOT NULL,
  context text               -- short extra detail; never PII/secrets
);
CREATE INDEX IF NOT EXISTS idx_error_log_created_at ON error_log (created_at DESC);

-- Persist RunLogger's existing in-memory error counter (was tracked, never saved)
ALTER TABLE scrape_logs ADD COLUMN IF NOT EXISTS error_count int DEFAULT 0;
