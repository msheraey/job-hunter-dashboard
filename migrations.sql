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

-- created_at timestamp for analytics (new-today counts, etc.)
ALTER TABLE user_job_matches ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now();
