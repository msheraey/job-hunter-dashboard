"""
config.py — Single source of truth: env vars, constants, feature flags.
Every other module imports from here. No credentials anywhere else.
"""
import os
import threading
from supabase import create_client

# ── Credentials ──────────────────────────────────────────────
DATAFORSEO_LOGIN    = os.environ.get("DATAFORSEO_LOGIN")
DATAFORSEO_PASSWORD = os.environ.get("DATAFORSEO_PASSWORD")
SUPABASE_URL        = os.environ.get("SUPABASE_URL")
SUPABASE_KEY        = os.environ.get("SUPABASE_SERVICE_KEY")
GROQ_API_KEY        = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY      = os.environ.get("GEMINI_API_KEY")
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY")
RESEND_API_KEY      = os.environ.get("RESEND_API_KEY")
SERPER_API_KEY      = os.environ.get("SERPER_API_KEY")  # optional — premium company lookup
SERPAPI_KEY         = os.environ.get("SERPAPI_KEY")  # optional — SerpApi Google Jobs, tried before DataForSEO
ADMIN_TOKEN         = os.environ.get("ADMIN_TOKEN")  # required to call admin trigger routes
REDIS_URL           = os.environ.get("REDIS_URL")  # optional — shared circuit-breaker state across workers
PUBLIC_BASE_URL     = os.environ.get("PUBLIC_BASE_URL")  # optional — this deployment's public URL, enables DataForSEO pingback

# ── CORS ──────────────────────────────────────────────────────
ALLOWED_ORIGINS = ["https://jobhunter.ae", "https://www.jobhunter.ae"]

# ── Tuning constants ─────────────────────────────────────────
TTL_HOURS            = 48     # re-scrape each title every 48h
JOB_MAX_DAYS         = 30     # archive jobs older than this
MAX_DAILY_SCRAPES    = 200    # DataForSEO daily ceiling
MAX_JOBS_PER_USER    = 50     # AI scoring cap per user per run
MAX_SECONDS_PER_USER = 300    # hard scoring time budget per user
TITLE_TIMEOUT_S      = 90     # hard cap per title scrape (async fallback)
LIVE_TIMEOUT_S       = 40     # DataForSEO Live endpoint request timeout
MATCH_THRESHOLD      = 60     # email matches at or above this score
SCRAPE_DEPTH         = 100    # results per title

# ── Feature flags ────────────────────────────────────────────
NOTIFY_DAILY    = os.environ.get("NOTIFY_DAILY", "true").lower() == "true"
NOTIFY_WEEKLY   = os.environ.get("NOTIFY_WEEKLY", "false").lower() == "true"
NOTIFY_INSTANT  = os.environ.get("NOTIFY_INSTANT", "false").lower() == "true"  # OFF until app launch
SEMANTIC_EXPAND = os.environ.get("SEMANTIC_EXPAND", "true").lower() == "true"

# ── Trusted job platforms ────────────────────────────────────
# Allowlist of known legitimate job boards and ATS platforms with UAE presence.
# Only links whose domain contains one of these strings are saved.
TRUSTED_DOMAINS = [
    # UAE & Gulf-specific boards
    "bayt.com", "naukrigulf.com", "gulftalent.com", "dubizzle.com",
    "laimoon.com", "drjobs.ae", "careers.ae", "gulfworkforce.com",
    "xpatjobs.com", "gofindit.com", "tiptopjob.com",
    # Global boards with strong UAE volume
    "linkedin.com", "indeed.com", "glassdoor.com", "monster.com",
    "ziprecruiter.com", "careerjet.com", "simplyhired.com", "jora.com",
    "totaljobs.com", "reed.co.uk", "cv-library.co.uk",
    # Major ATS platforms used by UAE corporates (DEWA, Emirates, Etihad, ADNOC, banks, etc.)
    "workday.com", "myworkdayjobs.com", "taleo.net", "successfactors.com",
    "greenhouse.io", "lever.co", "smartrecruiters.com", "icims.com",
    "jobvite.com", "bamboohr.com", "breezyhr.com", "recruitee.com",
    # Industry-specific with UAE listings
    "hozpitality.com", "hospitalityonline.com", "healthcaresource.com",
]

INDUSTRY_LIST = [
    "Healthcare & Pharmacy", "Retail", "FMCG", "Logistics & Supply Chain",
    "Technology", "Finance & Banking", "Hospitality & Tourism",
    "Real Estate", "Automotive", "Education", "Construction & Engineering",
    "Media & Marketing", "HR & Recruitment", "Other",
]

REQUIRED_ENV = ["DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD", "SUPABASE_URL", "SUPABASE_SERVICE_KEY"]

# ── Supabase client (thread-safe lazy singleton) ─────────────
_supabase = None
_supabase_lock = threading.Lock()

def get_supabase():
    global _supabase
    if _supabase is None:
        with _supabase_lock:
            if _supabase is None:
                if not SUPABASE_URL or not SUPABASE_KEY:
                    raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY not set")
                _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase

def validate_env():
    """Abort early with a clear message instead of failing mid-run."""
    missing = [v for v in REQUIRED_ENV if not os.environ.get(v)]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")
    if not any([GROQ_API_KEY, GEMINI_API_KEY, ANTHROPIC_API_KEY]):
        raise RuntimeError("Need at least one scoring key: GROQ_API_KEY / GEMINI_API_KEY / ANTHROPIC_API_KEY")
    return True
