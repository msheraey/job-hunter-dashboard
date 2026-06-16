# JobHunter — AI-Powered Job Matching Platform

> **Live:** [jobhunter.ae](https://jobhunter.ae) · **Backend:** Railway · **Frontend:** Lovable · **DB:** Supabase

JobHunter scrapes UAE job listings daily, scores them against each user's CV using AI, and emails personalised matches. It also generates ATS-ready tailored CVs and cover letters as DOCX files on demand.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Repository Structure](#repository-structure)
- [How It Works](#how-it-works)
- [API Reference](#api-reference)
- [Environment Variables](#environment-variables)
- [Database Setup](#database-setup)
- [Deployment](#deployment)
- [Roadmap](#roadmap)

---

## Architecture Overview

```
Lovable Frontend (jobhunter.ae)
        │
        ▼
Flask API  ──────────────────────────────────────────────┐
(api/app.py)                                             │
        │                                                │
        ├── services/scraper.py                          │
        │     DataForSEO Live endpoint (primary)         │
        │     DataForSEO Async (automatic fallback)      │
        │     48h TTL cache — shared across all users    │
        │                                                │
        ├── services/scorer.py                           │
        │     Groq llama-3.3-70b  → free, ~0.5s/job     │
        │     Gemini 2.5 Flash    → fallback             │
        │     Claude Haiku 4-5    → final fallback       │
        │     Circuit breaker per provider               │
        │                                                │
        ├── services/matcher.py                          │
        │     Per-user: scrape → dedupe → score → save  │
        │     Already-scored filter (no re-scoring ever) │
        │                                                │
        ├── services/cv_generator.py + docx_builder.py  │
        │     Parse CV → AI tailors → DOCX rendered      │
        │     Completeness repair (no roles ever dropped) │
        │                                                │
        └── services/premium.py                         │
              ATS score · Salary · Red flags             │
              Interview prep · Company info              │
                                                         │
Supabase ────────────────────────────────────────────────┘
  job_pool · title_pool · users · user_titles
  user_job_matches · scrape_logs · old_jobs
  user_linked_accounts
```

**Key design decisions:**
- **Pool architecture** — jobs are scraped once and shared. All N users benefit from one DataForSEO call. Scraping cost does not scale with user count.
- **Already-scored filter** — each job is AI-scored exactly once per user, ever. Daily scoring budget is spent only on new, unseen jobs.
- **Provider chain with circuit breakers** — if Groq is down, Gemini takes over automatically. If Gemini is also down, Haiku takes over. A broken provider costs ~zero seconds after 4 failures (breaker opens for 2 minutes, then retries).
- **Completeness guarantee on CV generation** — the user's full work history is parsed before AI involvement. If the AI omits any role, it is re-injected from the parsed skeleton before the DOCX is built.

---

## Repository Structure

```
jobhunter/
│
├── web_dashboard_cloud.py   Entry shim — Railway CMD unchanged (gunicorn web_dashboard_cloud:app)
├── daily_job.py             Cron orchestrator — python daily_job.py [weekly]
├── config.py                All env vars, constants, feature flags, Supabase client
├── prompts.py               Every AI prompt centralised here — iterate without touching logic
├── email_service.py         Resend email dispatch
├── migrations.sql           Run once in Supabase SQL Editor before first deploy
├── requirements.txt
├── Dockerfile
│
├── core/                    Infrastructure (no business logic)
│   ├── retry.py             Exponential backoff, jitter, circuit breaker
│   ├── logger.py            RunLogger — persistent logs in scrape_logs table
│   ├── db.py                Safe Supabase helpers (safe_select, safe_insert, etc.)
│   └── selftest.py          Startup health checks — tests every API before running
│
├── services/                Business logic — one responsibility per file
│   ├── scraper.py           DataForSEO Live (primary) + Async (fallback), TTL cache
│   ├── scorer.py            AI scoring: Groq → Gemini → Haiku chain
│   ├── matcher.py           Per-user match orchestration (search + score + save)
│   ├── classifier.py        Job quality score — heuristic, zero AI cost
│   ├── synonyms.py          Semantic title expansion (AI-generated synonyms per title)
│   ├── archiver.py          30-day archive — moves stale jobs to old_jobs
│   ├── cv_generator.py      CV + cover letter generation with completeness guarantee
│   ├── cv_parser.py         PDF/DOCX CV upload → plain text extraction
│   ├── cv_parser_structured.py  Structured CV skeleton extractor (completeness backstop)
│   ├── docx_builder.py      Renders CV/CL JSON → ATS-friendly Word documents
│   ├── premium.py           ATS score, salary estimate, red flags, interview prep, company info
│   ├── notifications.py     Daily/weekly/instant notification pipeline (flag-controlled)
│   ├── auth.py              Social login scaffold (Supabase Auth)
│   └── account_links.py     Job site account linking scaffold
│
├── utils/
│   └── filters.py           Junk/gender/nationality filters, title normalisation, industry inference
│
├── api/
│   ├── app.py               Flask app — all 29 routes, CORS, error handling
│   └── dashboard.py         Self-contained admin dashboard (HTML/JS, auto-refreshes)
│
└── auth/                    OAuth scaffolds (structure only — build phase 2)
    ├── social_login.py
    ├── site_linking.py
    └── providers/
        ├── linkedin.py      Real OAuth — buildable now
        ├── indeed.py        Stub — no public OAuth, session-link later
        ├── bayt.py          Stub
        ├── naukrigulf.py    Stub
        └── gulftalent.py    Stub
```

---

## How It Works

### Daily Cron (`daily_job.py`)

Runs every day at 09:00 Dubai time via Railway cron (`0 5 * * *`).

```
Step 0  Self-test     — checks Supabase, DataForSEO, scoring APIs before spending any budget
Step 1  Archive       — moves jobs older than 30 days to old_jobs table
Step 2  Scrape        — fetches all 27 titles via DataForSEO Live endpoint (48h TTL cache)
Step 3  Load users    — fetches all active users
Step 4  Score + Email — for each user: collect new pool jobs → AI score → save matches → email 60%+
```

If any core dependency (Supabase, DataForSEO) fails the self-test, the run aborts cleanly with a logged reason instead of wasting budget.

### Scoring Chain

Each job goes through the following chain until a score is returned:

```
Groq llama-3.3-70b  →  ~0.5s, free, 600 RPM
        ↓ (circuit open or 429)
Gemini 2.5 Flash    →  ~1-2s, paid recommended
        ↓ (circuit open or 429)
Claude Haiku 4-5    →  ~3s, reliable fallback
        ↓ (all fail)
score = 0 (job silently skipped this cycle, retried tomorrow)
```

Each provider has a circuit breaker: 4 consecutive failures → circuit opens for 120 seconds → half-open probe → recover.

### CV Generation

```
1. cv_parser.py         extracts plain text from uploaded PDF/DOCX
2. cv_parser_structured parses the text into a complete role skeleton
3. prompts.py           builds a prompt listing ALL N roles with explicit "include every one" instruction
4. scorer.ai_complete() runs through Groq → Gemini → Haiku chain
5. cv_generator.py      validates output: if any roles missing, re-injects from step 2 skeleton
6. docx_builder.py      renders the validated JSON into ATS-friendly DOCX (native Word styles)
7. api/app.py           returns both DOCX files as base64 + triggers background email
```

**ATS rules enforced in the DOCX:** single column, no layout tables, no text boxes, native Word bullet list styles, standard Calibri font, contact info as plain body text (not in document header/footer).

---

## API Reference

All endpoints at `https://job-hunter-dashboard-production-6300.up.railway.app`

### System

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check |
| `GET` | `/api/self-test` | Full dependency health check — tests all APIs and tables |
| `GET` | `/api/analytics` | User count, job pool size, match count, title count |
| `GET` | `/api/system-health` | Alias for self-test |
| `GET` | `/api/credit-status` | DataForSEO account balance |
| `GET` | `/api/logs` | Last 30 cron run summaries |
| `GET` | `/api/logs/<log_id>` | Full log text for a specific run |

### Triggers

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/run-scraper` | Trigger a full scrape in background |
| `POST` | `/api/score-and-email` | Trigger score + email for all users in background |

### User / Matches

| Method | Path | Body | Description |
|--------|------|------|-------------|
| `POST` | `/api/refresh-matches` | `{user_id}` | Returns existing matches + scores new pool jobs |
| `POST` | `/api/job-status` | `{user_id, job_id, status}` | status: `new` / `skipped` / `applied` |
| `POST` | `/api/add-title` | `{user_id, title}` | Add job title; triggers background scrape + synonym expansion |
| `POST` | `/api/can-edit-titles` | `{user_id}` | Returns count and max (10) |
| `POST` | `/api/delete-title` | `{user_id, title_id}` | Remove tracked title |
| `POST` | `/api/delete-user` | `{user_id}` | Delete user and all their data |

### CV & Cover Letter

| Method | Path | Body | Description |
|--------|------|------|-------------|
| `POST` | `/api/upload-cv` | `multipart: user_id + file` | Parse PDF/DOCX/TXT → save to users.cv_text |
| `POST` | `/api/generate-cv` | `{user_id, job_id}` | Generate CV + CL; returns text preview + DOCX as base64 |
| `POST` | `/api/download-cv` | `{user_id, job_id}` | Stream CV DOCX file directly |
| `POST` | `/api/download-cover-letter` | `{user_id, job_id}` | Stream cover letter DOCX file directly |

### Premium Intelligence

All require `{user_id, job_id}` in the POST body.

| Method | Path | Returns |
|--------|------|---------|
| `POST` | `/api/premium/ats-score` | `{ats_score, missing_keywords, strengths, improvements}` |
| `POST` | `/api/premium/salary` | `{min_aed, max_aed, confidence, basis}` |
| `POST` | `/api/premium/red-flags` | `{risk_level, flags, positives, advice, live_search_used}` |
| `POST` | `/api/premium/interview-prep` | `{likely_questions, questions_to_ask, key_selling_points}` |
| `POST` | `/api/premium/company-info` | `{company, website, linkedin}` |

### Archive

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/old-jobs` | Paginated list of archived jobs (`?limit=100&offset=0`) |
| `POST` | `/api/restore-job` | `{job_id}` — Move job back from archive to pool |

---

## Environment Variables

Set these in Railway → Project → Variables.

### Required

| Variable | Description |
|----------|-------------|
| `DATAFORSEO_LOGIN` | DataForSEO account email |
| `DATAFORSEO_PASSWORD` | DataForSEO account password |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Supabase service role key (bypasses RLS) |

### Scoring (at least one required)

| Variable | Description |
|----------|-------------|
| `GROQ_API_KEY` | Groq API key — **recommended primary** (free, fast, 600 RPM) |
| `GEMINI_API_KEY` | Google AI Studio key — secondary scorer |
| `ANTHROPIC_API_KEY` | Anthropic key — final fallback (Claude Haiku) |

### Optional

| Variable | Description | Default |
|----------|-------------|---------|
| `RESEND_API_KEY` | Resend API key for email delivery | — |
| `SERPER_API_KEY` | Serper web search — enriches red-flags and company-info endpoints | — |
| `NOTIFY_DAILY` | Enable daily email digests | `true` |
| `NOTIFY_WEEKLY` | Enable weekly digest (activate post-launch) | `false` |
| `NOTIFY_INSTANT` | Enable instant high-score alerts (activate post-launch) | `false` |
| `SEMANTIC_EXPAND` | Auto-generate synonym titles when user adds a title | `true` |
| `ADMIN_TOKEN` | Shared secret required (`X-Admin-Token` header) to call `/api/run-scraper` and `/api/score-and-email`. Without it those routes return 503. | — |
| `SUPABASE_JWT_SECRET` | Supabase project JWT secret (Settings → API → JWT Settings). Enables verifying bearer tokens on user-facing routes; without it, requests fall back to the legacy unauthenticated `user_id` in the body. | — |
| `REDIS_URL` | Shares AI-provider circuit breaker state across Railway workers. Falls back to in-memory (per-worker) state when unset. | — |
| `REQUIRE_AUTH` | Reserved for strict JWT enforcement once the frontend reliably sends tokens and Supabase Auth is reactivated. Currently informational only — not yet enforced in code. | `false` |
| `PUBLIC_BASE_URL` | This deployment's public URL (e.g. the Railway domain). Enables the DataForSEO pingback webhook so late-finishing scrapes still get saved. | — |

---

## Database Setup

Run `migrations.sql` **once** in Supabase → SQL Editor before deploying. Safe to re-run (all `IF NOT EXISTS`).

`migrations_partition_old_jobs.sql` is a separate, optional, advanced migration — only run it once `old_jobs` has grown large enough that archiving/reads are slow. It rebuilds the table (RANGE-partitioned by month), so take a backup first; it is not part of the routine `migrations.sql` flow.

### Tables

| Table | Purpose |
|-------|---------|
| `users` | User accounts — email, CV text, profile summary, notification prefs |
| `title_pool` | All job search keywords — shared across users, with TTL timestamps |
| `user_titles` | Many-to-many: which titles each user tracks |
| `job_pool` | Active job listings — shared cache, scraped once per title |
| `user_job_matches` | Per-user AI scores, status (new/skipped/applied), match reason |
| `old_jobs` | Jobs archived after 30 days — can be restored |
| `scrape_logs` | Full run logs — every cron and manual trigger |
| `user_linked_accounts` | Job site OAuth links (scaffold — used in phase 2) |

### Schema notes

- `job_pool` has `embedding vector(384)` column (created by migrations) — unused until the embeddings pipeline is built. The column is there so the table doesn't need altering later.
- `user_job_matches.status` values: `new` (default) | `skipped` | `applied`
- RLS is currently **disabled** — the backend uses the service role key. Re-enable with per-user policies before scaling beyond ~100 users.

---

## Deployment

### Railway (backend)

1. Run `migrations.sql` in Supabase SQL Editor
2. Upload repo contents to GitHub (replace old files; entry point names `web_dashboard_cloud.py` and `daily_job.py` are unchanged)
3. Railway auto-deploys on push
4. Set all environment variables in Railway → Variables
5. Cron is configured as `0 5 * * *` (09:00 Dubai time)

### Manual triggers

```bash
# Via API (from any HTTP client) — requires X-Admin-Token: <ADMIN_TOKEN>
curl -X POST https://<host>/api/run-scraper -H "X-Admin-Token: $ADMIN_TOKEN"
curl -X POST https://<host>/api/score-and-email -H "X-Admin-Token: $ADMIN_TOKEN"
```

The admin dashboard's Settings tab has an "Admin token" field that stores
the token in the browser and attaches it automatically to these two buttons.

```bash
# Direct (Railway console or SSH)
python daily_job.py          # full daily run
python daily_job.py weekly   # weekly digest (when NOTIFY_WEEKLY=true)
```

### Auth rollout (JWT)

The backend can verify Supabase JWTs (`core/jwt_auth.py`) but stays in
lenient mode — it accepts the legacy unauthenticated `user_id` body field
when no bearer token is present, so nothing breaks mid-rollout. To turn
real auth on end-to-end:

1. Set `SUPABASE_JWT_SECRET` in Railway (Supabase → Settings → API → JWT Settings)
2. Reactivate Supabase Auth in the Supabase dashboard (currently suspended)
3. Deploy the `jobhunterae` frontend patch that attaches `Authorization: Bearer <session token>` to API calls
4. Once all three are live and verified, flip `REQUIRE_AUTH=true` and update the resolver to reject unauthenticated requests outright instead of falling back

### Health check after deploy

```
GET /health            → {"status": "ok", ...}
GET /api/self-test     → per-service status with messages
GET /                  → admin dashboard (auto-refreshes every 30s)
```

---

## Roadmap

See `FRONTEND_ROADMAP.md` for the full frontend queue (filters, sorters, analytics tab, mobile swipe gestures).

### Backend — next priorities

- **RLS re-enable** — per-user Supabase policies before scaling real users
- **DataForSEO Live billing** — confirm paid credits are active (Live endpoint costs ~2× async but eliminates all timeouts)
- **Groq as primary scorer** — confirm `GROQ_API_KEY` is set in Railway; Groq is free, 600 RPM, ~0.5s/job
- **SERPER_API_KEY** — adds live web search to red flags and company info endpoints
- **Embeddings pipeline** — schema is ready (`vector(384)` columns exist); build cosine pre-filter when user base grows past ~200 users
- **Capacitor mobile app** — push notification wiring in `services/notifications.py` at `send_push()`
- **Auto-apply** — LinkedIn OAuth is the only one with a real API; others need session-based browser automation

### Feature flags (flip in Railway env, zero code changes)

| Flag | Default | What it activates |
|------|---------|-------------------|
| `NOTIFY_WEEKLY` | `false` | Weekly email digest every Sunday |
| `NOTIFY_INSTANT` | `false` | Instant alert when a job scores 85%+ |
| `SEMANTIC_EXPAND` | `true` | Auto-generate synonym search titles |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Lovable (React) |
| Backend | Python 3.11, Flask, Gunicorn |
| Database | Supabase (PostgreSQL) |
| Hosting | Railway |
| Job data | DataForSEO Google Jobs API |
| AI scoring | Groq / Gemini / Claude Haiku (chain) |
| Email | Resend |
| CV parsing | pypdf, python-docx |
| DOCX generation | python-docx |
| Web search (optional) | Serper |

---

*Built by Mohammed Alsheraery · [linkedin.com/in/msheraery](https://linkedin.com/in/msheraery) · [github.com/msheraey](https://github.com/msheraey)*
