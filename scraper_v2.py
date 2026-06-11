#!/usr/bin/env python3
"""
JobHunter Scraper v2 — Multi-user, on-demand pool architecture
- DataForSEO Google Jobs API (LIVE endpoint - immediate results)
- Supabase for storage (service role key — bypasses RLS)
- On-demand scraping with 48h TTL cache
- AI scoring via Google Gemini 2.0 Flash (fast & reliable)
- Gender eligibility filter
- Daily spend ceiling protection
- Full run logging to Supabase scrape_logs table
- Auto-archive jobs older than 30 days
"""

import os
import re
import time
import requests
import json
import threading
from collections import deque
from datetime import datetime, timezone, timedelta
from supabase import create_client

# ── Config ─────────────────────────────────────────────────────────────────
DATAFORSEO_LOGIN    = os.environ.get("DATAFORSEO_LOGIN")
DATAFORSEO_PASSWORD = os.environ.get("DATAFORSEO_PASSWORD")
SUPABASE_URL        = os.environ.get("SUPABASE_URL")
SUPABASE_KEY        = os.environ.get("SUPABASE_SERVICE_KEY")
GEMINI_API_KEY      = os.environ.get("GEMINI_API_KEY")
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY")

# Validate required env vars at startup
REQUIRED_ENV_VARS = [
    "DATAFORSEO_LOGIN",
    "DATAFORSEO_PASSWORD", 
    "SUPABASE_URL",
    "SUPABASE_SERVICE_KEY",
    "GEMINI_API_KEY"
]
for var in REQUIRED_ENV_VARS:
    if not os.environ.get(var):
        raise RuntimeError(f"Missing required env var: {var}")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TTL_HOURS = 48  # Re-scrape each title every 48h
MAX_DAILY_SCRAPES = 200
JOB_MAX_DAYS = 30  # Jobs older than this are moved to old_jobs

# ── Rate Limiter for Gemini (DISABLED for paid tier) ────────────────────────
class RateLimiter:
    def __init__(self, requests_per_minute=10):
        self.requests_per_minute = requests_per_minute
        self.requests = deque()
        self.lock = threading.RLock()
        self.enabled = False  # DISABLED for paid Gemini tier

    def wait_if_needed(self):
        if not self.enabled:
            return  # No rate limiting for paid tier
        with self.lock:
            while True:
                now = time.time()
                while self.requests and self.requests[0] < now - 60:
                    self.requests.popleft()

                if len(self.requests) < self.requests_per_minute:
                    break

                wait_time = 60 - (now - self.requests[0]) + 0.5
                print(f"    🕐 Gemini rate limiter: waiting {wait_time:.1f}s ({len(self.requests)}/{self.requests_per_minute} RPM)")
                time.sleep(wait_time)

            self.requests.append(time.time())

gemini_limiter = RateLimiter(requests_per_minute=10)  # Disabled by default

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

INDUSTRY_LIST = [
    "Healthcare & Pharmacy", "Retail", "FMCG", "Logistics & Supply Chain",
    "Technology", "Finance & Banking", "Hospitality & Tourism",
    "Real Estate", "Automotive", "Education", "Construction & Engineering",
    "Media & Marketing", "HR & Recruitment", "Other"
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

def map_industry_variation(industry_text):
    """Map industry variations to standard list"""
    if not industry_text:
        return "Other"
    industry_lower = industry_text.lower()
    
    mapping = {
        "health": "Healthcare & Pharmacy",
        "healthcare": "Healthcare & Pharmacy",
        "pharmacy": "Healthcare & Pharmacy",
        "medical": "Healthcare & Pharmacy",
        "retail": "Retail",
        "fmcg": "FMCG",
        "logistics": "Logistics & Supply Chain",
        "supply chain": "Logistics & Supply Chain",
        "tech": "Technology",
        "it": "Technology",
        "finance": "Finance & Banking",
        "banking": "Finance & Banking",
        "hospitality": "Hospitality & Tourism",
        "tourism": "Hospitality & Tourism",
        "real estate": "Real Estate",
        "auto": "Automotive",
        "automotive": "Automotive",
        "education": "Education",
        "construction": "Construction & Engineering",
        "engineering": "Construction & Engineering",
        "media": "Media & Marketing",
        "marketing": "Media & Marketing",
        "hr": "HR & Recruitment",
        "recruitment": "HR & Recruitment"
    }
    
    for key, value in mapping.items():
        if key in industry_lower:
            return value
    
    return "Other"

def infer_industry_from_text(text):
    """Infer industry from job title/description keywords"""
    if not text:
        return "Other"
    text_lower = text.lower()
    
    keywords = {
        "Healthcare & Pharmacy": ["nurse", "pharmacist", "doctor", "clinical", "hospital", "medical", "healthcare", "patient", "clinic", "dental", "radiology", "lab", "technician", "pharmacy"],
        "Technology": ["developer", "engineer", "software", "data", "analyst", "it", "technical", "programmer", "devops", "cloud", "security", "network", "system", "database", "api", "frontend", "backend", "full stack"],
        "Retail": ["sales", "retail", "store", "shop", "merchandise", "cashier", "customer service", "floor manager", "visual merchandising"],
        "Finance & Banking": ["accountant", "finance", "bank", "audit", "tax", "treasury", "credit", "risk", "investment", "controller", "payable", "receivable"],
        "Logistics & Supply Chain": ["logistics", "supply chain", "warehouse", "inventory", "procurement", "purchase", "shipping", "freight", "transport", "distribution", "driver"],
        "Hospitality & Tourism": ["hotel", "restaurant", "catering", "tourism", "travel", "chef", "waiter", "bartender", "front desk", "resort", "guest service"],
        "HR & Recruitment": ["hr", "recruitment", "talent", "people", "human resources", "hiring", "recruiter", "payroll", "employee", "onboarding"],
        "Construction & Engineering": ["civil", "construction", "architect", "engineer", "site", "project manager", "quantity surveyor", "structural", "electrical", "mechanical"],
        "Marketing & Media": ["marketing", "social media", "content", "seo", "digital", "brand", "advertising", "campaign", "communications", "pr"],
        "Education": ["teacher", "professor", "instructor", "education", "school", "university", "trainer", "faculty", "academic", "curriculum"]
    }
    
    for industry, words in keywords.items():
        for word in words:
            if word in text_lower:
                return industry
    
    return "Other"

# ── Job Freshness & Archival ────────────────────────────────────────────────
def get_job_age_days(posted_at):
    """Calculate age of job in days from posted_at date"""
    if not posted_at:
        return None
    try:
        if isinstance(posted_at, str):
            posted_date = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
        else:
            posted_date = posted_at
        if posted_date.tzinfo is None:
            posted_date = posted_date.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - posted_date).days
    except:
        return None

def move_old_jobs_to_archive(logger=None):
    """Move jobs older than JOB_MAX_DAYS from job_pool to old_jobs table"""
    def log(msg):
        if logger:
            logger.add(msg)
        else:
            print(msg)
    
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=JOB_MAX_DAYS)
    
    old_jobs = supabase.table("job_pool").select("*").lt("posted_at", cutoff_date.isoformat()).execute().data or []
    
    if not old_jobs:
        log(f"📦 No jobs older than {JOB_MAX_DAYS} days to archive")
        return 0
    
    ALLOWED_OLD_JOBS_COLS = {
        "title", "company", "location", "posted_at", "link", "platform",
        "description", "search_keyword", "salary", "last_scraped",
        "fingerprint", "industry"
    }

    moved = 0
    for job in old_jobs:
        try:
            age_days = get_job_age_days(job.get("posted_at"))

            clean = {k: v for k, v in job.items() if k in ALLOWED_OLD_JOBS_COLS}
            clean["original_id"] = job["id"]
            clean["age_days_at_move"] = age_days
            clean["moved_at"] = datetime.now(timezone.utc).isoformat()

            supabase.table("old_jobs").insert(clean).execute()

            supabase.table("job_pool").delete().eq("id", job["id"]).execute()
            supabase.table("user_job_matches").delete().eq("job_id", job["id"]).execute()

            moved += 1
        except Exception as e:
            log(f"  ⚠️ Error moving job {job.get('id')}: {e}")
    
    log(f"📦 Moved {moved} jobs to old_jobs (older than {JOB_MAX_DAYS} days)")
    return moved

def get_old_jobs(limit=100, offset=0):
    """Retrieve old jobs from archive (for Old Jobs section in dashboard)"""
    try:
        result = supabase.table("old_jobs").select("*").order("moved_at", desc=True).limit(limit).offset(offset).execute()
        return result.data or []
    except Exception as e:
        print(f"Error fetching old jobs: {e}")
        return []

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
        result = supabase.table("title_pool").select("id", count="exact").gte("last_scraped", today).execute()
        return result.count or 0
    except Exception as e:
        print(f"Error getting scrape count: {e}")
        return 0

def is_over_daily_ceiling():
    count = get_today_scrape_count()
    if count >= MAX_DAILY_SCRAPES:
        print(f"⚠️ Daily ceiling reached ({count}/{MAX_DAILY_SCRAPES})")
        return True
    return False

# 🔧 FIXED: DataForSEO with LIVE endpoint (immediate results, no polling)
def dataforseo_search(keyword, logger=None):
    def log(msg):
        if logger:
            logger.add(msg)
        else:
            print(msg)

    try:
        # Clean and encode the keyword
        clean_keyword = keyword.strip()
        log(f"  📡 Fetching live results from DataForSEO for '{clean_keyword}'...")

        response = requests.post(
            "https://api.dataforseo.com/v3/serp/google/jobs/live/advanced",
            auth=(DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD),
            json=[{
                "keyword": clean_keyword,
                "location_name": "United Arab Emirates",
                "language_name": "English",
                "depth": 100
            }],
            timeout=30
        )
        
        if response.status_code != 200:
            log(f"  ❌ HTTP {response.status_code}: {response.text[:200]}")
            return []
        
        data = response.json()
        
        if not data.get("tasks"):
            log(f"  ❌ No tasks in response")
            return []
        
        task = data["tasks"][0]
        if task.get("status_code") not in [20000, 20100]:
            log(f"  ❌ API error: {task.get('status_message', 'unknown')}")
            return []
        
        result = task.get("result", [])
        if not result:
            log(f"  ❌ No results in response")
            return []
        
        items = result[0].get("items", [])
        log(f"  ✅ Got {len(items)} results directly (live endpoint)")
        
        return items

    except Exception as e:
        log(f"  ❌ DataForSEO error: {e}")
        return []

# ── AI Scoring with Google Gemini 2.0 Flash (FAST & RELIABLE) ─────────────
def _extract_score_and_industry(text):
    """Extract score (int), industry (str), and reason (str) from AI response"""
    score = None
    industry = None
    reason = None

    try:
        cleaned = re.sub(r'```json|```', '', text).strip()

        json_match = re.search(r'\{[^{}]*\}', cleaned, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                if "score" in data:
                    val = data.get("score")
                    if val is not None:
                        score = max(0, min(100, int(val)))
                if "industry" in data:
                    industry = data.get("industry")
                    if industry:
                        industry = map_industry_variation(industry)
                if "reason" in data:
                    reason = str(data["reason"]).strip()[:200] or None
            except json.JSONDecodeError:
                pass
    except Exception:
        pass
    
    if score is None:
        number_match = re.search(r'\b([1-9]?\d|100)\b', text)
        if number_match:
            score = max(0, min(100, int(number_match.group(1))))
    
    if industry is None and text:
        industry = infer_industry_from_text(text)
    
    return score, industry, reason

# 🔧 FIXED: Using correct Gemini 2.0 Flash model
def score_job_with_gemini(job_title, job_company, job_description, user_profile):
    industry_options = ", ".join(INDUSTRY_LIST)
    prompt = f"""You are a job matching expert. Score how well this job matches the candidate and identify the job industry.

JOB:
Title: {job_title}
Company: {job_company}
Description: {job_description[:500] if job_description else 'Not provided'}

CANDIDATE:
{user_profile[:800]}

Return ONLY JSON: {{"score": 75, "industry": "Retail", "reason": "brief reason"}}
Score 0-100. Industry must be exactly one of: {industry_options}"""

    # Rate limiter is disabled for paid tier
    # gemini_limiter.wait_if_needed()
    
    for attempt in range(3):
        try:
            # 🔧 FIXED: Using gemini-2.0-flash (correct model name)
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
            
            payload = {
                "contents": [{
                    "parts": [{"text": prompt}]
                }],
                "generationConfig": {
                    "temperature": 0.1,
                    "maxOutputTokens": 120
                }
            }
            
            resp = requests.post(url, json=payload, timeout=15)
            
            if resp.status_code == 429:
                wait = [1, 2, 3][attempt]
                print(f"    ⏳ Rate limited, waiting {wait}s (attempt {attempt+1}/3)")
                time.sleep(wait)
                continue
            
            if resp.status_code != 200:
                if attempt < 2:
                    time.sleep(1)
                    continue
                print(f"    ⚠️ Gemini error {resp.status_code}: {resp.text[:200]}")
                return 0, None, None
            
            data = resp.json()
            content = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            score, industry, reason = _extract_score_and_industry(content)
            
            if score is not None:
                return score, industry, reason
                
        except Exception as e:
            if attempt < 2:
                time.sleep(1)
                continue
            print(f"    ❌ Gemini failed: {e}")
    
    if ANTHROPIC_API_KEY:
        return score_job_with_haiku(job_title, job_company, job_description, user_profile)
    return 0, None, None

def score_job_with_haiku(job_title, job_company, job_description, user_profile):
    if not ANTHROPIC_API_KEY:
        return 0, None, None
        
    industry_options = ", ".join(INDUSTRY_LIST)
    prompt = f"""Score this job match 0-100 and identify the industry. Return only JSON: {{"score": N, "industry": "Industry Name", "reason": "short reason under 15 words"}}
Industry must be one of: {industry_options}
Job: {job_title} at {job_company}
Description: {job_description[:300] if job_description else ""}
Candidate: {user_profile[:500]}"""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-4-5", "max_tokens": 120, "messages": [{"role": "user", "content": prompt}]},
            timeout=15
        )
        data = resp.json()
        if "content" not in data:
            return 0, None, None
        content = data["content"][0]["text"].strip()
        score, industry, reason = _extract_score_and_industry(content)
        return (score if score is not None else 0), industry, reason
    except Exception as e:
        print(f"    ❌ Haiku failed: {e}")
        return 0, None, None

def score_jobs_for_user(jobs, user):
    profile_parts = []
    if user.get("profile_summary"):
        profile_parts.append(f"Summary: {user['profile_summary']}")
    if user.get("cv_text"):
        profile_parts.append(f"CV: {user['cv_text'][:1000]}")
    if not profile_parts:
        return jobs
    user_profile = "\n".join(profile_parts)
    
    MAX_JOBS_PER_RUN = 50
    MAX_SECONDS_PER_USER = 300
    start_time = time.time()

    to_score = jobs[:MAX_JOBS_PER_RUN]

    for i, job in enumerate(to_score):
        if time.time() - start_time > MAX_SECONDS_PER_USER:
            print(f"    ⏱️ Time budget hit ({MAX_SECONDS_PER_USER}s) — scored {i}/{len(to_score)}, moving on")
            for rest in to_score[i:]:
                if not isinstance(rest.get("score"), int):
                    rest["score"] = 0
            break

        score, industry, reason = score_job_with_gemini(
            job.get("title", ""), job.get("company", ""),
            job.get("description", ""), user_profile
        )
        job["score"] = score if isinstance(score, int) else 0
        job["match_reason"] = reason

        if industry and job.get("id") and not job.get("industry"):
            try:
                supabase.table("job_pool").update({"industry": industry}).eq("id", job["id"]).is_("industry", "null").execute()
                job["industry"] = industry
            except Exception:
                pass

        if (i + 1) % 3 == 0:
            time.sleep(2)

    for job in jobs[MAX_JOBS_PER_RUN:]:
        job["score"] = 0

    return jobs

# 🔧 FIXED: CV generation with correct Gemini model
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

Format your response EXACTLY like this:

===COVER_LETTER===
(the full cover letter here)
===TAILORED_CV===
(the full tailored CV here)
===END==="""

    def _call(max_tokens):
        # 🔧 FIXED: Using gemini-2.0-flash (correct model name)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": max_tokens}
        }
        resp = requests.post(url, json=payload, timeout=60)
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]

    def _parse(text):
        cover, cv = "", ""
        if "===COVER_LETTER===" in text and "===TAILORED_CV===" in text:
            after_cl = text.split("===COVER_LETTER===", 1)[1]
            cover = after_cl.split("===TAILORED_CV===", 1)[0].strip()
            after_cv = after_cl.split("===TAILORED_CV===", 1)[1]
            cv = after_cv.split("===END===", 1)[0].strip()
        return cover, cv

    try:
        content = _call(3500)
        cover, cv = _parse(content)
        if not cover and not cv:
            try:
                cleaned = re.sub(r'```json|```', '', content).strip()
                result = json.loads(cleaned)
                cover = result.get("cover_letter", "")
                cv = result.get("tailored_cv", "")
            except:
                pass
        if not cover and not cv and content.strip():
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

        fingerprint = f"{normalize_title(title)}|{company.lower()}|{item.get('location', 'UAE').lower()}"
        fingerprint = re.sub(r'[^a-z0-9|]', '', fingerprint)[:200]

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
                "fingerprint": fingerprint
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

    # Filter out jobs older than 30 days
    if jobs:
        original_count = len(jobs)
        cutoff = datetime.now(timezone.utc) - timedelta(days=JOB_MAX_DAYS)
        filtered_jobs = []
        for j in jobs:
            posted = j.get("posted_at")
            if posted:
                try:
                    if isinstance(posted, str):
                        posted_date = datetime.fromisoformat(posted.replace("Z", "+00:00"))
                    else:
                        posted_date = posted
                    if posted_date.tzinfo is None:
                        posted_date = posted_date.replace(tzinfo=timezone.utc)
                    if posted_date >= cutoff:
                        filtered_jobs.append(j)
                except:
                    filtered_jobs.append(j)
            else:
                filtered_jobs.append(j)
        jobs = filtered_jobs
        if original_count != len(jobs):
            log(f"  🧹 Filtered out {original_count - len(jobs)} jobs older than {JOB_MAX_DAYS} days")

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
    seen_fingerprints = set()

    existing_matches = supabase.table("user_job_matches").select("job_id").eq("user_id", user_id).execute()
    already_scored = {r["job_id"] for r in (existing_matches.data or [])}

    for t in (titles.data or []):
        jobs = search_jobs(t["keyword"], user_gender=user_gender, logger=logger)
        for j in jobs:
            if j.get("id") in already_scored:
                continue
            link = j.get("link", "")
            fingerprint = j.get("fingerprint", "")
            
            if (link and link in seen_links) or (fingerprint and fingerprint in seen_fingerprints):
                continue
            
            if link:
                seen_links.add(link)
            if fingerprint:
                seen_fingerprints.add(fingerprint)
            all_jobs.append(j)

    if not all_jobs:
        return []

    if len(all_jobs) > 50:
        log(f"  ⚠️ Limiting from {len(all_jobs)} to 50 new jobs for scoring")
        all_jobs = all_jobs[:50]

    log(f"  🤖 Scoring {len(all_jobs)} unique jobs...")
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
                "match_reason": job.get("match_reason"),
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

    existing = supabase.table("user_job_matches").select("job_id").eq("user_id", user_id).execute()
    already_scored = {r["job_id"] for r in (existing.data or [])}

    pending_titles = []
    jobs_to_score = []
    seen_links = set()
    seen_fingerprints = set()

    for t in (titles.data or []):
        normalized = t["normalized"]
        pooled = supabase.table("job_pool").select("*").eq("search_keyword", normalized).execute().data or []

        if not pooled:
            pending_titles.append(t["keyword"])
            continue

        for j in pooled:
            if user_gender and user_gender != "prefer_not_to_say":
                if is_gender_restricted(f"{j.get('title','')} {j.get('description','')}", user_gender):
                    continue
            if j["id"] in already_scored:
                continue
            link = j.get("link", "")
            fingerprint = j.get("fingerprint", "")
            
            if (link and link in seen_links) or (fingerprint and fingerprint in seen_fingerprints):
                continue
                
            if link:
                seen_links.add(link)
            if fingerprint:
                seen_fingerprints.add(fingerprint)
            jobs_to_score.append(j)

    if jobs_to_score:
        if len(jobs_to_score) > 50:
            log(f"  ⚠️ Limiting scoring to 50 jobs (from {len(jobs_to_score)})")
            jobs_to_score = jobs_to_score[:50]
        log(f"  🤖 Scoring {len(jobs_to_score)} new pooled jobs...")
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
                    "match_reason": job.get("match_reason"),
                    "emailed": False
                }, on_conflict="user_id,job_id").execute()
            except Exception as e:
                log(f"  ⚠️ Match save error: {e}")

    if pending_titles:
        def _bg_scrape(titles_list, gender):
            for kw in titles_list:
                try:
                    search_jobs(kw, user_gender=gender)
                except Exception as e:
                    print(f"  ❌ bg scrape error for {kw}: {e}")
        _threading.Thread(target=_bg_scrape, args=(pending_titles, user_gender), daemon=True).start()
        log(f"  🌐 Background scraping {len(pending_titles)} new titles: {pending_titles}")

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
