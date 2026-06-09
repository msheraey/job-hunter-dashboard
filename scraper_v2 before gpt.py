#!/usr/bin/env python3
"""
JobHunter Scraper v2 — Multi-user, on-demand pool architecture
- DataForSEO Google Jobs API
- Supabase for storage (service role key — bypasses RLS)
- On-demand scraping with 24h TTL cache
- AI scoring via Groq (free) with Claude Haiku fallback
- Gender eligibility filter
- Daily spend ceiling protection
- Full run logging to Supabase scrape_logs table
"""

import os
import re
import time
import requests
import json
from datetime import datetime, timezone, timedelta
from supabase import create_client

# ── Config ─────────────────────────────────────────────────────────────────
DATAFORSEO_LOGIN    = os.environ.get("DATAFORSEO_LOGIN")
DATAFORSEO_PASSWORD = os.environ.get("DATAFORSEO_PASSWORD")
SUPABASE_URL        = os.environ.get("SUPABASE_URL")
SUPABASE_KEY        = os.environ.get("SUPABASE_SERVICE_KEY")
GROQ_API_KEY        = os.environ.get("GROQ_API_KEY")
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TTL_HOURS = 24
MAX_DAILY_SCRAPES = 200

# ── Trusted platforms ──────────────────────────────────────────────────────
TRUSTED_DOMAINS = [
    "linkedin.com", "indeed.com", "bayt.com",
    "naukrigulf.com", "gulftalent.com", "gofindit.com"
]

# ── Filters ────────────────────────────────────────────────────────────────
JUNK_PATTERNS = [
    re.compile(r"jobs in (uae|dubai|abu dhabi|sharjah).*(20\d\d)", re.I),
    re.compile(r"\d+\+?\s+(jobs|vacancies)", re.I),
    re.compile(r"^\d+\s+(jobs|vacancies)\s*$", re.I),
    re.compile(r"'s post", re.I),
    re.compile(r"jobs?,\s+employment", re.I),
]

NATIONALITY_SKIP = ["UAEN", "UAE NATIONAL", "EMIRATI", "NATIONAL ONLY"]

FEMALE_ONLY_PATTERNS = [
    re.compile(r"\bfemale(s)?\s+only\b", re.I),
    re.compile(r"\bladies\s+only\b", re.I),
    re.compile(r"\bfemale\s+candidates?\s+only\b", re.I),
    re.compile(r"\bonly\s+female(s)?\b", re.I),
]

MALE_ONLY_PATTERNS = [
    re.compile(r"\bmale(s)?\s+only\b", re.I),
    re.compile(r"\bgentlemen\s+only\b", re.I),
    re.compile(r"\bmale\s+candidates?\s+only\b", re.I),
    re.compile(r"\bonly\s+male(s)?\b", re.I),
]

def is_junk(title):
    return any(p.search(title) for p in JUNK_PATTERNS)

def is_nationality_restricted(title):
    return any(kw in title.upper() for kw in NATIONALITY_SKIP)

def is_gender_restricted(text, user_gender):
    if not user_gender or user_gender == "prefer_not_to_say":
        return False
    combined = text.upper() if text else ""
    if user_gender == "male":
        return any(p.search(combined) for p in FEMALE_ONLY_PATTERNS)
    if user_gender == "female":
        return any(p.search(combined) for p in MALE_ONLY_PATTERNS)
    return False

def normalize_title(title):
    return re.sub(r'\s+', ' ', title.strip().lower())

def validate_title(title):
    t = title.strip()
    if len(t) < 3 or len(t) > 80:
        return False
    if not re.search(r'[a-zA-Z]', t):
        return False
    return True


# ── Logger class ───────────────────────────────────────────────────────────
class RunLogger:
    def __init__(self, run_type="scraper"):
        self.run_type = run_type
        self.lines = []
        self.total_scraped = 0
        self.total_saved = 0
        self.log_id = None
        self.started_at = datetime.now(timezone.utc).isoformat()
        self._create_log_entry()

    def _create_log_entry(self):
        try:
            result = supabase.table("scrape_logs").insert({
                "started_at": self.started_at,
                "status": "running",
                "log_text": f"[{self.run_type}] Started\n",
                "total_scraped": 0,
                "total_saved": 0
            }).execute()
            self.log_id = result.data[0]["id"]
            print(f"📋 Log entry created: {self.log_id}")
        except Exception as e:
            print(f"⚠️ Could not create log entry: {e}")

    def add(self, msg, print_it=True):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        self.lines.append(line)
        if print_it:
            print(msg)
        # Save to DB every 5 lines
        if len(self.lines) % 5 == 0:
            self._flush()

    def _flush(self):
        if not self.log_id:
            return
        try:
            supabase.table("scrape_logs").update({
                "log_text": "\n".join(self.lines),
                "total_scraped": self.total_scraped,
                "total_saved": self.total_saved,
            }).eq("id", self.log_id).execute()
        except Exception as e:
            print(f"⚠️ Log flush error: {e}")

    def finish(self, success=True, error=None):
        if not self.log_id:
            return
        try:
            update = {
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "status": "success" if success else "error",
                "log_text": "\n".join(self.lines),
                "total_scraped": self.total_scraped,
                "total_saved": self.total_saved,
            }
            if error:
                update["error"] = str(error)[:1000]
            supabase.table("scrape_logs").update(update).eq("id", self.log_id).execute()
            print(f"📋 Log saved — status: {'success' if success else 'error'}")
        except Exception as e:
            print(f"⚠️ Log finish error: {e}")


# ── Spend ceiling ──────────────────────────────────────────────────────────
def get_today_scrape_count():
    try:
        today = datetime.now(timezone.utc).date().isoformat()
        result = supabase.table("title_pool").select("id").gte("last_scraped", today).execute()
        return len(result.data or [])
    except:
        return 0

def is_over_daily_ceiling():
    count = get_today_scrape_count()
    if count >= MAX_DAILY_SCRAPES:
        print(f"⚠️ Daily ceiling reached ({count}/{MAX_DAILY_SCRAPES})")
        return True
    return False


# ── DataForSEO ─────────────────────────────────────────────────────────────
def dataforseo_search(keyword, logger=None):
    def log(msg):
        if logger:
            logger.add(msg)
        else:
            print(msg)

    try:
        log(f"  📡 Posting task to DataForSEO for '{keyword}'...")
        post_resp = requests.post(
            "https://api.dataforseo.com/v3/serp/google/jobs/task_post",
            auth=(DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD),
            json=[{
                "keyword": keyword,
                "location_name": "United Arab Emirates",
                "language_name": "English",
                "depth": 100
            }],
            timeout=30
        )
        post_data = post_resp.json()
        tasks = post_data.get("tasks", [])

        if not tasks or tasks[0].get("status_code") not in [20000, 20100]:
            log(f"  ❌ task_post failed: {post_data.get('status_message','unknown error')}")
            return []

        task_id = tasks[0].get("id")
        log(f"  ✅ Task created: {task_id} — waiting 10s...")

        # Retry fetching results — DataForSEO can take 10-30s
        items = None
        for attempt in range(5):
            wait = 8 if attempt == 0 else 6
            time.sleep(wait)
            log(f"  📥 Fetching results (attempt {attempt + 1}/5)...")
            get_resp = requests.get(
                f"https://api.dataforseo.com/v3/serp/google/jobs/task_get/advanced/{task_id}",
                auth=(DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD),
                timeout=30
            )
            get_data = get_resp.json()
            result_tasks = get_data.get("tasks", [])
            if result_tasks and result_tasks[0].get("result"):
                items = result_tasks[0]["result"][0].get("items", [])
                break
            log(f"  ⏳ Not ready yet, retrying...")

        if items is None:
            log(f"  ⚠️ No results after 5 attempts for task {task_id}")
            return []

        log(f"  📋 Got {len(items)} raw results")
        return items

    except Exception as e:
        log(f"  ❌ DataForSEO error: {e}")
        return []


# ── AI Scoring ─────────────────────────────────────────────────────────────
def _extract_score(text):
    """Pull an integer 0-100 score from any messy AI response."""
    if not text:
        return None
    # Try JSON first
    try:
        cleaned = re.sub(r'```json|```', '', text).strip()
        # grab first {...} block if present
        m = re.search(r'\{[^}]*\}', cleaned, re.DOTALL)
        if m:
            val = json.loads(m.group(0)).get("score")
            if val is not None:
                return max(0, min(100, int(val)))
    except Exception:
        pass
    # Fallback: first number 0-100 in the text
    m = re.search(r'\b(\d{1,3})\b', text)
    if m:
        return max(0, min(100, int(m.group(1))))
    return None


INDUSTRY_LIST = [
    "Healthcare & Pharmacy", "Retail", "FMCG", "Logistics & Supply Chain",
    "Technology", "Finance & Banking", "Hospitality & Tourism",
    "Real Estate", "Automotive", "Education", "Construction & Engineering",
    "Media & Marketing", "HR & Recruitment", "Other"
]

def _extract_score_and_industry(text):
    """Extract score (int) and industry (str) from AI response."""
    score = None
    industry = None
    try:
        cleaned = re.sub(r'```json|```', '', text).strip()
        m = re.search(r'\{[^}]*\}', cleaned, re.DOTALL)
        if m:
            data = json.loads(m.group(0))
            val = data.get("score")
            if val is not None:
                score = max(0, min(100, int(val)))
            industry = data.get("industry")
    except Exception:
        pass
    if score is None:
        m = re.search(r'\b(\d{1,3})\b', text)
        if m:
            score = max(0, min(100, int(m.group(1))))
    return score, industry


def score_job_with_groq(job_title, job_company, job_description, user_profile):
    industry_options = ", ".join(INDUSTRY_LIST)
    prompt = f"""You are a job matching expert. Score how well this job matches the candidate and identify the job industry.

JOB:
Title: {job_title}
Company: {job_company}
Description: {job_description[:500] if job_description else 'Not provided'}

CANDIDATE:
{user_profile}

Return ONLY JSON: {{"score": 75, "industry": "Retail", "reason": "brief reason"}}
Score 0-100. Be strict. Industry must be exactly one of: {industry_options}"""

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.1-8b-instant", "messages": [{"role": "user", "content": prompt}], "max_tokens": 120, "temperature": 0.1},
            timeout=15
        )
        data = resp.json()
        if "choices" not in data:
            err = data.get("error", {})
            msg = err.get("message", str(data)[:120]) if isinstance(err, dict) else str(err)[:120]
            print(f"    ⚠️ Groq error ({resp.status_code}): {msg} — trying Haiku")
            return score_job_with_haiku(job_title, job_company, job_description, user_profile)
        content = data["choices"][0]["message"]["content"].strip()
        score, industry = _extract_score_and_industry(content)
        if score is None:
            return score_job_with_haiku(job_title, job_company, job_description, user_profile)
        return score, industry
    except Exception as e:
        print(f"    ⚠️ Groq failed: {e} — trying Haiku")
        return score_job_with_haiku(job_title, job_company, job_description, user_profile)


def score_job_with_haiku(job_title, job_company, job_description, user_profile):
    industry_options = ", ".join(INDUSTRY_LIST)
    prompt = f"""Score this job match 0-100 and identify the industry. Return only JSON: {{"score": N, "industry": "Industry Name"}}
Industry must be one of: {industry_options}
Job: {job_title} at {job_company}
Description: {job_description[:300] if job_description else ""}
Candidate: {user_profile[:500]}"""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 80, "messages": [{"role": "user", "content": prompt}]},
            timeout=15
        )
        data = resp.json()
        if "content" not in data:
            err = data.get("error", {})
            msg = err.get("message", str(data)[:120]) if isinstance(err, dict) else str(err)[:120]
            print(f"    ❌ Haiku error ({resp.status_code}): {msg}")
            return 0, None
        content = data["content"][0]["text"].strip()
        score, industry = _extract_score_and_industry(content)
        return (score if score is not None else 0), industry
    except Exception as e:
        print(f"    ❌ Haiku also failed: {e}")
        return 0, None



def score_jobs_for_user(jobs, user):
    profile_parts = []
    if user.get("profile_summary"):
        profile_parts.append(f"Summary: {user['profile_summary']}")
    if user.get("cv_text"):
        profile_parts.append(f"CV: {user['cv_text'][:1000]}")
    if not profile_parts:
        return jobs
    user_profile = "\n".join(profile_parts)
    MAX_SCORE_PER_REQUEST = 40
    to_score = jobs[:MAX_SCORE_PER_REQUEST]
    for i, job in enumerate(to_score):
        result = score_job_with_groq(
            job.get("title", ""), job.get("company", ""),
            job.get("description", ""), user_profile
        )
        # result is now (score, industry) tuple
        if isinstance(result, tuple):
            score, industry = result
        else:
            score, industry = result, None
        job["score"] = score if isinstance(score, int) else 0
        # Write industry back to job_pool if not already set
        if industry and job.get("id") and not job.get("industry"):
            try:
                supabase.table("job_pool").update({"industry": industry}).eq("id", job["id"]).is_("industry", "null").execute()
                job["industry"] = industry
            except Exception:
                pass
        # Small delay every 5 jobs to avoid hitting Groq TPM rate limit
        if (i + 1) % 5 == 0:
            time.sleep(1)
    for job in jobs[MAX_SCORE_PER_REQUEST:]:
        if not isinstance(job.get("score"), int):
            job["score"] = 0
    return jobs



# ── CV + Cover Letter ──────────────────────────────────────────────────────
def generate_cv_cover_letter(user, job):
    prompt = f"""You are an expert UAE career writer. Write a tailored cover letter and a tailored CV for this job application.

JOB: {job.get('title')} at {job.get('company')}
Location: {job.get('location', 'UAE')}
Description: {job.get('description', '')[:800]}

CANDIDATE PROFILE:
{user.get('profile_summary', '')}

CANDIDATE CV:
{user.get('cv_text', '')[:2500]}

Write a professional, specific cover letter (3-4 short paragraphs) and a tailored CV that highlights the most relevant experience for THIS role.

Format your response EXACTLY like this, using these exact delimiter lines:

===COVER_LETTER===
(the full cover letter here)
===TAILORED_CV===
(the full tailored CV here)
===END==="""

    def _call(model, max_tokens):
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens, "temperature": 0.4},
            timeout=60
        )
        return resp.json()["choices"][0]["message"]["content"]

    def _parse(text):
        cover, cv = "", ""
        if "===COVER_LETTER===" in text and "===TAILORED_CV===" in text:
            after_cl = text.split("===COVER_LETTER===", 1)[1]
            cover = after_cl.split("===TAILORED_CV===", 1)[0].strip()
            after_cv = after_cl.split("===TAILORED_CV===", 1)[1]
            cv = after_cv.split("===END===", 1)[0].strip()
        return cover, cv

    try:
        content = _call("llama-3.3-70b-versatile", 3500)
        cover, cv = _parse(content)
        # Fallback: if delimiters missing, try to salvage by using the whole text as CV
        if not cover and not cv:
            # try JSON as a last resort
            try:
                cleaned = re.sub(r'```json|```', '', content).strip()
                result = json.loads(cleaned)
                cover = result.get("cover_letter", "")
                cv = result.get("tailored_cv", "")
            except:
                pass
        if not cover and not cv and content.strip():
            # last-ditch: split roughly in half so the email isn't empty
            cover = content.strip()
        return cover, cv
    except Exception as e:
        print(f"❌ CV generation error: {e}")
        return "", ""


# ── Pool logic ─────────────────────────────────────────────────────────────
def is_fresh(last_scraped_str):
    if not last_scraped_str:
        return False
    try:
        last = datetime.fromisoformat(str(last_scraped_str).replace("Z", "+00:00"))
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - last < timedelta(hours=TTL_HOURS)
    except:
        return False


def get_or_create_title(keyword):
    normalized = normalize_title(keyword)
    result = supabase.table("title_pool").select("*").eq("normalized", normalized).execute()
    if result.data:
        current = result.data[0].get("request_count", 0) or 0
        supabase.table("title_pool").update({"request_count": current + 1}).eq("id", result.data[0]["id"]).execute()
        return result.data[0], False
    insert = supabase.table("title_pool").insert({
        "keyword": keyword, "normalized": normalized, "request_count": 1
    }).execute()
    return insert.data[0], True


def get_cached_jobs(keyword):
    normalized = normalize_title(keyword)
    result = supabase.table("job_pool").select("*").eq("search_keyword", normalized).order("posted_at", desc=True).execute()
    return result.data or []


def save_jobs(keyword, items, logger=None):
    def log(msg):
        if logger:
            logger.add(msg)
        else:
            print(msg)

    normalized = normalize_title(keyword)
    saved = 0

    existing = supabase.table("job_pool").select("link").eq("search_keyword", normalized).execute()
    existing_links = {r["link"] for r in (existing.data or [])}

    for item in items:
        title = item.get("title", "").strip()
        company = item.get("employer_name", "Unknown").strip()

        if is_junk(title) or is_nationality_restricted(title) or len(title) < 5:
            continue

        link = item.get("source_url", "")
        platform = item.get("source_name", "Google Jobs").replace("via ", "")

        if not link or not link.startswith("http"):
            continue
        if not any(d in link for d in TRUSTED_DOMAINS):
            continue
        if link in existing_links:
            continue

        try:
            posted_raw = item.get("timestamp")
            posted_at = None
            if posted_raw:
                posted_at = datetime.fromisoformat(posted_raw.replace(" +00:00", "+00:00")).isoformat()
        except:
            posted_at = None

        description = (item.get("description") or item.get("snippet") or "")[:1500]

        try:
            supabase.table("job_pool").insert({
                "title": title[:200],
                "company": company[:100],
                "location": item.get("location", "UAE"),
                "posted_at": posted_at,
                "link": link,
                "platform": platform[:100],
                "description": description,
                "search_keyword": normalized,
                "salary": item.get("salary", ""),
                "last_scraped": datetime.now(timezone.utc).isoformat(),
            }).execute()
            existing_links.add(link)
            saved += 1
        except Exception as e:
            log(f"  ⚠️ Save error: {e}")

    supabase.table("title_pool").update({
        "last_scraped": datetime.now(timezone.utc).isoformat()
    }).eq("normalized", normalized).execute()

    log(f"  💾 Saved {saved} new jobs for '{keyword}'")
    return saved


# ── Main entry points ──────────────────────────────────────────────────────
def search_jobs(keyword, user_gender=None, logger=None):
    def log(msg):
        if logger:
            logger.add(msg)
        else:
            print(msg)

    if not validate_title(keyword):
        log(f"❌ Invalid title rejected: '{keyword}'")
        return []

    log(f"🔍 Searching: '{keyword}'")
    title_record, is_new = get_or_create_title(keyword)
    last_scraped = title_record.get("last_scraped")

    if is_fresh(last_scraped):
        log(f"  ✅ Cache fresh — last scraped {str(last_scraped)[:16]}")
        jobs = get_cached_jobs(keyword)
    elif is_over_daily_ceiling():
        log(f"  ⚠️ Daily ceiling hit — returning stale cache")
        jobs = get_cached_jobs(keyword)
    else:
        log(f"  🌐 Cache miss — scraping DataForSEO...")
        items = dataforseo_search(keyword, logger=logger)
        if items:
            saved = save_jobs(keyword, items, logger=logger)
            if logger:
                logger.total_scraped += 1
                logger.total_saved += saved
        jobs = get_cached_jobs(keyword)

    if user_gender and user_gender != "prefer_not_to_say":
        before = len(jobs)
        jobs = [j for j in jobs if not is_gender_restricted(
            f"{j.get('title','')} {j.get('description','')}", user_gender
        )]
        filtered = before - len(jobs)
        if filtered:
            log(f"  🚫 Filtered {filtered} gender-restricted jobs")

    return jobs


def run_full_scrape():
    """Run scraper for all titles in pool with full logging"""
    logger = RunLogger("full_scrape")
    logger.add("🚀 Full scrape started")

    try:
        titles = supabase.table("title_pool").select("*").execute().data or []
        if not titles:
            logger.add("ℹ️ No titles in pool")
            logger.finish(success=True)
            return logger.log_id

        logger.add(f"📋 Found {len(titles)} titles to process")

        for i, t in enumerate(titles, 1):
            logger.add(f"\n[{i}/{len(titles)}] {t['keyword']}")
            search_jobs(t["keyword"], logger=logger)

        logger.add(f"\n✅ Full scrape complete — {logger.total_scraped} scraped, {logger.total_saved} new jobs saved")
        logger.finish(success=True)

    except Exception as e:
        logger.add(f"\n❌ Fatal error: {e}")
        logger.finish(success=False, error=e)

    return logger.log_id


def search_and_score_for_user(user, logger=None):
    def log(msg):
        if logger:
            logger.add(msg)
        else:
            print(msg)

    user_id = user.get("id")
    user_gender = user.get("gender")

    title_links = supabase.table("user_titles").select("title_id").eq("user_id", user_id).execute()
    if not title_links.data:
        log(f"  No titles for user {user_id}")
        return []

    title_ids = [t["title_id"] for t in title_links.data]
    titles = supabase.table("title_pool").select("keyword").in_("id", title_ids).execute()

    all_jobs = []
    seen_links = set()
    for t in (titles.data or []):
        jobs = search_jobs(t["keyword"], user_gender=user_gender, logger=logger)
        for j in jobs:
            link = j.get("link", "")
            if link and link not in seen_links:
                seen_links.add(link)
                all_jobs.append(j)

    if not all_jobs:
        return []

    log(f"  🤖 Scoring {len(all_jobs)} unique jobs (deduplicated)...")
    scored_jobs = score_jobs_for_user(all_jobs, user)

    matched = []
    for job in scored_jobs:
        score = job.get("score", 0) or 0
        if score < 1:
            continue
        try:
            supabase.table("user_job_matches").upsert({
                "user_id": user_id,
                "job_id": job["id"],
                "score": score,
                "emailed": score >= 60
            }, on_conflict="user_id,job_id").execute()
        except Exception as e:
            log(f"  ⚠️ Match save error: {e}")
        if score >= 60:
            matched.append(job)

    matched.sort(key=lambda x: x.get("score", 0), reverse=True)
    log(f"  ✅ {len(matched)} jobs at 60%+ match")
    return matched


def refresh_matches_for_user(user, logger=None):
    """
    Instant-refresh for a logged-in user:
    1. Score jobs already in the pool for this user's titles that AREN'T scored yet (instant, cheap).
    2. Return ALL the user's 60%+ matches from the DB immediately.
    3. For titles with NO jobs in the pool yet (brand new), kick off a background scrape.
    Returns: { "matches": [...], "pending_titles": [list of titles still being scraped] }
    Only scores jobs not already scored for this user (no wasted AI calls on refresh).
    """
    import threading as _threading

    def log(msg):
        if logger:
            logger.add(msg)
        else:
            print(msg)

    user_id = user.get("id")
    user_gender = user.get("gender")

    title_links = supabase.table("user_titles").select("title_id").eq("user_id", user_id).execute()
    if not title_links.data:
        return {"matches": [], "pending_titles": []}

    title_ids = [t["title_id"] for t in title_links.data]
    titles = supabase.table("title_pool").select("keyword,normalized").in_("id", title_ids).execute()

    # Which job_ids are already scored for this user (so we don't re-score)
    existing = supabase.table("user_job_matches").select("job_id").eq("user_id", user_id).execute()
    already_scored = {r["job_id"] for r in (existing.data or [])}

    pending_titles = []
    jobs_to_score = []
    seen_links = set()

    for t in (titles.data or []):
        normalized = t["normalized"]
        pooled = supabase.table("job_pool").select("*").eq("search_keyword", normalized).execute().data or []

        if not pooled:
            # Brand-new title with nothing in the pool yet — needs scraping
            pending_titles.append(t["keyword"])
            continue

        # Gender filter + skip already-scored + dedup
        for j in pooled:
            if user_gender and user_gender != "prefer_not_to_say":
                if is_gender_restricted(f"{j.get('title','')} {j.get('description','')}", user_gender):
                    continue
            if j["id"] in already_scored:
                continue
            link = j.get("link", "")
            if link and link in seen_links:
                continue
            seen_links.add(link)
            jobs_to_score.append(j)

    # Score only the new (un-scored) pooled jobs
    if jobs_to_score:
        log(f"  🤖 Scoring {len(jobs_to_score)} new pooled jobs for user...")
        scored = score_jobs_for_user(jobs_to_score, user)
        for job in scored:
            score = job.get("score", 0) or 0
            if score < 1:
                continue
            try:
                supabase.table("user_job_matches").upsert({
                    "user_id": user_id,
                    "job_id": job["id"],
                    "score": score,
                    "emailed": False
                }, on_conflict="user_id,job_id").execute()
            except Exception as e:
                log(f"  ⚠️ Match save error: {e}")

    # Kick off background scrape for brand-new titles (non-blocking)
    if pending_titles:
        def _bg_scrape(titles_list, gender):
            for kw in titles_list:
                try:
                    search_jobs(kw, user_gender=gender)
                except Exception as e:
                    print(f"  ❌ bg scrape error for {kw}: {e}")
        _threading.Thread(target=_bg_scrape, args=(pending_titles, user_gender), daemon=True).start()
        log(f"  🌐 Background scraping {len(pending_titles)} new titles: {pending_titles}")

    # Return all the user's current 60%+ matches from DB
    match_rows = supabase.table("user_job_matches").select("job_id,score").eq("user_id", user_id).gte("score", 60).execute().data or []
    if not match_rows:
        return {"matches": [], "pending_titles": pending_titles}

    job_ids = [m["job_id"] for m in match_rows]
    score_map = {m["job_id"]: m["score"] for m in match_rows}
    jobs = supabase.table("job_pool").select("*").in_("id", job_ids).execute().data or []
    for j in jobs:
        j["score"] = score_map.get(j["id"], 0)
    jobs.sort(key=lambda x: x.get("score", 0), reverse=True)

    return {"matches": jobs, "pending_titles": pending_titles}


if __name__ == "__main__":
    run_full_scrape()
