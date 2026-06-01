#!/usr/bin/env python3
"""
JobHunter Scraper v2 — Multi-user, on-demand pool architecture
- DataForSEO Google Jobs API
- Supabase for storage (service role key — bypasses RLS)
- On-demand scraping with 24h TTL cache
- AI scoring via Groq (free) with Claude Haiku fallback
- Gender eligibility filter
- Daily spend ceiling protection
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
SUPABASE_KEY        = os.environ.get("SUPABASE_SERVICE_KEY")  # service role — bypasses RLS
GROQ_API_KEY        = os.environ.get("GROQ_API_KEY")
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TTL_HOURS = 24
MAX_DAILY_SCRAPES = 200  # hard spend ceiling — stop scraping if exceeded

# ── Trusted platforms only ─────────────────────────────────────────────────
TRUSTED_DOMAINS = [
    "linkedin.com", "indeed.com", "bayt.com",
    "naukrigulf.com", "gulftalent.com", "gofindit.com"
]

# ── Junk/skip filters ──────────────────────────────────────────────────────
JUNK_PATTERNS = [
    re.compile(r"jobs in (uae|dubai|abu dhabi|sharjah).*(20\d\d)", re.I),
    re.compile(r"\d+\+?\s+(jobs|vacancies)", re.I),
    re.compile(r"^\d+\s+(jobs|vacancies)\s*$", re.I),
    re.compile(r"'s post", re.I),
    re.compile(r"jobs?,\s+employment", re.I),
]

NATIONALITY_SKIP = [
    "UAEN", "UAE NATIONAL", "EMIRATI", "NATIONAL ONLY",
]

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
    """
    Returns True if the job should be filtered out for this user's gender.
    user_gender: 'male', 'female', or None
    """
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
    """Basic sanity check — reject gibberish"""
    t = title.strip()
    if len(t) < 3 or len(t) > 80:
        return False
    if not re.search(r'[a-zA-Z]', t):
        return False
    if re.match(r'^[^a-zA-Z]*$', t):
        return False
    return True

# ── Spend ceiling ──────────────────────────────────────────────────────────
def get_today_scrape_count():
    """Count scrapes done today"""
    try:
        today = datetime.now(timezone.utc).date().isoformat()
        result = supabase.table("title_pool")\
            .select("id")\
            .gte("last_scraped", today)\
            .execute()
        return len(result.data or [])
    except:
        return 0

def is_over_daily_ceiling():
    count = get_today_scrape_count()
    if count >= MAX_DAILY_SCRAPES:
        print(f"  ⚠️ Daily scrape ceiling reached ({count}/{MAX_DAILY_SCRAPES}) — serving cache only")
        return True
    return False

# ── DataForSEO ─────────────────────────────────────────────────────────────
def dataforseo_search(keyword):
    try:
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
            print(f"  ❌ task_post failed for '{keyword}': {post_data}")
            return []

        task_id = tasks[0].get("id")
        print(f"  ✅ Task created: {task_id}")

        time.sleep(10)

        get_resp = requests.get(
            f"https://api.dataforseo.com/v3/serp/google/jobs/task_get/advanced/{task_id}",
            auth=(DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD),
            timeout=30
        )
        get_data = get_resp.json()
        result_tasks = get_data.get("tasks", [])

        if not result_tasks or not result_tasks[0].get("result"):
            print(f"  ⚠️ No results yet for task {task_id}")
            return []

        items = result_tasks[0]["result"][0].get("items", [])
        print(f"  📋 Found {len(items)} raw jobs for '{keyword}'")
        return items

    except Exception as e:
        print(f"  ❌ DataForSEO error for '{keyword}': {e}")
        return []

# ── AI Scoring ─────────────────────────────────────────────────────────────
def score_job_with_groq(job_title, job_company, job_description, user_profile):
    """Score job against user profile using Groq (free tier)"""
    prompt = f"""You are a job matching expert. Score how well this job matches the candidate's profile.

JOB:
Title: {job_title}
Company: {job_company}
Description: {job_description[:500] if job_description else 'Not provided'}

CANDIDATE PROFILE:
{user_profile}

Return ONLY a JSON object like this, nothing else:
{{"score": 75, "reason": "Strong match on management experience"}}

Score 0-100. Be strict — only score high if it's genuinely relevant."""

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama3-8b-8192",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 100,
                "temperature": 0.1
            },
            timeout=15
        )
        content = resp.json()["choices"][0]["message"]["content"].strip()
        content = re.sub(r'```json|```', '', content).strip()
        result = json.loads(content)
        return int(result.get("score", 0))
    except Exception as e:
        print(f"    ⚠️ Groq scoring failed: {e} — trying Claude Haiku")
        return score_job_with_haiku(job_title, job_company, job_description, user_profile)


def score_job_with_haiku(job_title, job_company, job_description, user_profile):
    """Fallback: score using Claude Haiku"""
    prompt = f"""Score this job match 0-100. Return only JSON: {{"score": N}}

Job: {job_title} at {job_company}
Description: {job_description[:300] if job_description else ''}
Candidate: {user_profile[:500]}"""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 50,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=15
        )
        content = resp.json()["content"][0]["text"].strip()
        content = re.sub(r'```json|```', '', content).strip()
        result = json.loads(content)
        return int(result.get("score", 0))
    except Exception as e:
        print(f"    ❌ Haiku scoring also failed: {e}")
        return 0


def score_jobs_for_user(jobs, user):
    """Score a list of jobs against a user's profile"""
    profile_parts = []
    if user.get("profile_summary"):
        profile_parts.append(f"Summary: {user['profile_summary']}")
    if user.get("cv_text"):
        profile_parts.append(f"CV: {user['cv_text'][:1000]}")
    if not profile_parts:
        return jobs  # no profile to score against

    user_profile = "\n".join(profile_parts)
    scored = []
    for job in jobs:
        score = score_job_with_groq(
            job.get("title", ""),
            job.get("company", ""),
            job.get("description", ""),
            user_profile
        )
        job["score"] = score
        scored.append(job)
    return scored


# ── CV + Cover Letter Generation ───────────────────────────────────────────
def generate_cv_cover_letter(user, job):
    """Generate tailored CV and cover letter for a specific job"""
    prompt = f"""Generate a tailored CV and cover letter for this job application.

JOB:
Title: {job.get('title')}
Company: {job.get('company')}
Description: {job.get('description', '')[:800]}

CANDIDATE:
{user.get('profile_summary', '')}

CV TEXT:
{user.get('cv_text', '')[:2000]}

Return ONLY a JSON object:
{{
  "cover_letter": "...",
  "tailored_cv": "..."
}}

Make both professional, specific to the job, and appropriate for UAE market."""

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama3-70b-8192",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 2000,
                "temperature": 0.3
            },
            timeout=30
        )
        content = resp.json()["choices"][0]["message"]["content"].strip()
        content = re.sub(r'```json|```', '', content).strip()
        result = json.loads(content)
        return result.get("cover_letter", ""), result.get("tailored_cv", "")
    except Exception as e:
        print(f"  ❌ CV generation error: {e}")
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
    result = supabase.table("title_pool")\
        .select("*")\
        .eq("normalized", normalized)\
        .execute()

    if result.data:
        # Increment request count
        current = result.data[0].get("request_count", 0) or 0
        supabase.table("title_pool")\
            .update({"request_count": current + 1})\
            .eq("id", result.data[0]["id"])\
            .execute()
        return result.data[0], False

    insert = supabase.table("title_pool").insert({
        "keyword": keyword,
        "normalized": normalized,
        "request_count": 1
    }).execute()
    return insert.data[0], True


def get_cached_jobs(keyword):
    normalized = normalize_title(keyword)
    result = supabase.table("job_pool")\
        .select("*")\
        .eq("search_keyword", normalized)\
        .order("posted_at", desc=True)\
        .execute()
    return result.data or []


def save_jobs(keyword, items):
    normalized = normalize_title(keyword)
    saved = 0

    existing = supabase.table("job_pool")\
        .select("link")\
        .eq("search_keyword", normalized)\
        .execute()
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
                posted_at = datetime.fromisoformat(
                    posted_raw.replace(" +00:00", "+00:00")
                ).isoformat()
        except:
            posted_at = None

        description = (item.get("description") or item.get("snippet") or "")[:1500]

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

    supabase.table("title_pool")\
        .update({"last_scraped": datetime.now(timezone.utc).isoformat()})\
        .eq("normalized", normalized)\
        .execute()

    print(f"  💾 Saved {saved} new jobs for '{keyword}'")
    return saved


# ── Main entry points ──────────────────────────────────────────────────────
def search_jobs(keyword, user_gender=None):
    """
    Main function: given a keyword, return jobs filtered by gender.
    Checks pool first, scrapes if stale/new (respects daily ceiling).
    """
    if not validate_title(keyword):
        print(f"  ❌ Invalid title rejected: '{keyword}'")
        return []

    print(f"\n🔍 Searching: '{keyword}'")

    title_record, is_new = get_or_create_title(keyword)
    last_scraped = title_record.get("last_scraped")

    if not is_fresh(last_scraped):
        if is_over_daily_ceiling():
            print(f"  ⚠️ Ceiling hit — returning stale cache for '{keyword}'")
        else:
            print(f"  🌐 Cache miss — scraping DataForSEO...")
            items = dataforseo_search(keyword)
            if items:
                save_jobs(keyword, items)

    jobs = get_cached_jobs(keyword)

    # Apply gender filter
    if user_gender and user_gender != "prefer_not_to_say":
        before = len(jobs)
        jobs = [
            j for j in jobs
            if not is_gender_restricted(
                f"{j.get('title','')} {j.get('description','')}", user_gender
            )
        ]
        filtered = before - len(jobs)
        if filtered:
            print(f"  🚫 Filtered {filtered} gender-restricted jobs")

    return jobs


def search_and_score_for_user(user):
    """
    Run all of a user's titles, score results against their profile,
    save matches to user_job_matches table.
    Returns list of scored jobs with score >= 60.
    """
    user_id = user.get("id")
    user_gender = user.get("gender")

    # Get user's selected titles
    title_links = supabase.table("user_titles")\
        .select("title_id")\
        .eq("user_id", user_id)\
        .execute()

    if not title_links.data:
        print(f"  No titles for user {user_id}")
        return []

    title_ids = [t["title_id"] for t in title_links.data]
    titles = supabase.table("title_pool")\
        .select("keyword")\
        .in_("id", title_ids)\
        .execute()

    all_jobs = []
    for t in (titles.data or []):
        jobs = search_jobs(t["keyword"], user_gender=user_gender)
        all_jobs.extend(jobs)

    if not all_jobs:
        return []

    # Score all jobs
    print(f"  🤖 Scoring {len(all_jobs)} jobs for user {user_id}...")
    scored_jobs = score_jobs_for_user(all_jobs, user)

    # Save matches to DB
    matched = []
    for job in scored_jobs:
        score = job.get("score", 0)
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
            print(f"    ⚠️ Match save error: {e}")

        if score >= 60:
            matched.append(job)

    matched.sort(key=lambda x: x.get("score", 0), reverse=True)
    print(f"  ✅ {len(matched)} jobs at 60%+ for user {user_id}")
    return matched


if __name__ == "__main__":
    jobs = search_jobs("area manager UAE")
    print(f"\nTotal: {len(jobs)} jobs")
    for j in jobs[:3]:
        print(f"  - {j['title']} @ {j['company']}")
