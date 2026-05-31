#!/usr/bin/env python3
"""
JobHunter Scraper v2 — Multi-user, on-demand pool architecture
- DataForSEO Google Jobs API
- Supabase for storage
- On-demand scraping with 24h TTL cache
- Shared title pool across all users
"""

import os
import re
import time
import requests
from datetime import datetime, timezone, timedelta
from supabase import create_client

# ── Config ────────────────────────────────────────────────────────────────
DATAFORSEO_LOGIN    = os.environ.get("DATAFORSEO_LOGIN")
DATAFORSEO_PASSWORD = os.environ.get("DATAFORSEO_PASSWORD")
SUPABASE_URL        = os.environ.get("SUPABASE_URL")
SUPABASE_KEY        = os.environ.get("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TTL_HOURS = 24  # re-scrape if older than this

# ── Trusted platforms ─────────────────────────────────────────────────────
TRUSTED_DOMAINS = [
    "linkedin.com", "bayt.com", "indeed.com",
    "naukrigulf.com", "gulftalent.com"
]

# ── Junk filter ───────────────────────────────────────────────────────────
JUNK_PATTERNS = [
    re.compile(r"jobs in (uae|dubai|abu dhabi|sharjah).*(20\d\d)", re.I),
    re.compile(r"\d+\+?\s+(jobs|vacancies)", re.I),
    re.compile(r"^\d+\s+(jobs|vacancies)\s*$", re.I),
    re.compile(r"'s post", re.I),
    re.compile(r"jobs?,\s+employment", re.I),
]

SKIP_KEYWORDS = [
    "UAEN", "UAE NATIONAL", "EMIRATI", "NATIONAL ONLY",
    "FEMALE ONLY", "FEMALES ONLY",
]

def is_junk(title):
    return any(p.search(title) for p in JUNK_PATTERNS)

def is_skip(title):
    return any(kw in title.upper() for kw in SKIP_KEYWORDS)

def normalize_title(title):
    """Lowercase, strip extra spaces — for deduplication"""
    return re.sub(r'\s+', ' ', title.strip().lower())


# ── DataForSEO ────────────────────────────────────────────────────────────
def dataforseo_search(keyword):
    """
    Two-step DataForSEO call:
    1. POST task
    2. Wait 5s then GET results
    Returns list of raw job dicts or empty list on failure.
    """
    try:
        # Step 1: Post task
        post_resp = requests.post(
            "https://api.dataforseo.com/v3/serp/google/jobs/task_post",
            auth=(DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD),
            json=[{
                "keyword": keyword,
                "location_name": "United Arab Emirates",
                "language_name": "English",
                "depth": 10
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

        # Step 2: Wait then fetch
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
        print(f"  📋 Found {len(items)} jobs for '{keyword}'")
        return items

    except Exception as e:
        print(f"  ❌ DataForSEO error for '{keyword}': {e}")
        return []


# ── Pool logic ────────────────────────────────────────────────────────────
def is_fresh(last_scraped_str):
    """Returns True if last_scraped is within TTL_HOURS"""
    if not last_scraped_str:
        return False
    try:
        last = datetime.fromisoformat(last_scraped_str.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - last < timedelta(hours=TTL_HOURS)
    except:
        return False

def get_or_create_title(keyword):
    """
    Check if title exists in pool.
    If not, create it.
    Returns (title_record, is_new)
    """
    normalized = normalize_title(keyword)

    result = supabase.table("title_pool")\
        .select("*")\
        .eq("normalized", normalized)\
        .execute()

    if result.data:
        return result.data[0], False

    # Create new title entry
    insert = supabase.table("title_pool").insert({
        "keyword": keyword,
        "normalized": normalized,
        "request_count": 1
    }).execute()

    return insert.data[0], True

def increment_request_count(title_id):
    """Bump request count for a title"""
    record = supabase.table("title_pool")\
        .select("request_count")\
        .eq("id", title_id)\
        .execute()

    if record.data:
        current = record.data[0]["request_count"] or 0
        supabase.table("title_pool")\
            .update({"request_count": current + 1})\
            .eq("id", title_id)\
            .execute()

def get_cached_jobs(keyword):
    """Get jobs from pool for this keyword"""
    normalized = normalize_title(keyword)
    result = supabase.table("job_pool")\
        .select("*")\
        .eq("search_keyword", normalized)\
        .order("posted_at", desc=True)\
        .execute()
    return result.data or []

def save_jobs(keyword, items):
    """Save scraped jobs to pool, skip duplicates"""
    normalized = normalize_title(keyword)
    saved = 0

    # Get existing links to avoid duplicates
    existing = supabase.table("job_pool")\
        .select("link")\
        .eq("search_keyword", normalized)\
        .execute()
    existing_links = {r["link"] for r in (existing.data or [])}

    for item in items:
        title = item.get("title", "").strip()
        company = item.get("employer_name", "Unknown").strip()

        if is_junk(title) or is_skip(title) or len(title) < 5:
            continue

        # Get link — DataForSEO returns it as source_url
        link = item.get("source_url", "")
        platform = item.get("source_name", "Google Jobs")

        # Skip if no valid link
        if not link or not link.startswith("http"):
            continue

        if link in existing_links:
            continue

        # Parse posted date
        try:
            posted_raw = item.get("timestamp")
            posted_at = None
            if posted_raw:
                posted_at = datetime.fromisoformat(
                    posted_raw.replace(" +00:00", "+00:00")
                ).isoformat()
        except:
            posted_at = None

        # Get description
        description = (
            item.get("description") or
            item.get("snippet") or
            item.get("job_highlights", {}).get("Qualifications", [""])[0]
            if isinstance(item.get("job_highlights"), dict) else ""
        ) or ""

        supabase.table("job_pool").insert({
            "title": title[:200],
            "company": company[:100],
            "location": item.get("location", "UAE"),
            "posted_at": posted_at,
            "link": link,
            "platform": platform,
            "salary": item.get("salary", ""),
            "description": str(description)[:1500],
            "search_keyword": normalized,
            "last_scraped": datetime.now(timezone.utc).isoformat(),
        }).execute()

        existing_links.add(link)
        saved += 1

    # Update last_scraped on title_pool
    supabase.table("title_pool")\
        .update({"last_scraped": datetime.now(timezone.utc).isoformat()})\
        .eq("normalized", normalized)\
        .execute()

    print(f"  💾 Saved {saved} new jobs for '{keyword}'")
    return saved


# ── Main entry point ──────────────────────────────────────────────────────
def search_jobs(keyword):
    """
    Main function: given a keyword, return jobs.
    - Checks pool first
    - If fresh (<24h), returns cached results
    - If stale or new, scrapes DataForSEO and saves to pool
    """
    print(f"\n🔍 Searching: '{keyword}'")

    title_record, is_new = get_or_create_title(keyword)
    title_id = title_record["id"]

    if not is_new:
        increment_request_count(title_id)

    last_scraped = title_record.get("last_scraped")

    if is_fresh(last_scraped):
        print(f"  ✅ Cache hit — last scraped {last_scraped}")
        return get_cached_jobs(keyword)

    print(f"  🌐 Cache miss — scraping DataForSEO...")
    items = dataforseo_search(keyword)

    if items:
        save_jobs(keyword, items)

    return get_cached_jobs(keyword)


if __name__ == "__main__":
    # Quick test
    jobs = search_jobs("pharmacy manager UAE")
    print(f"\n{'='*50}")
    print(f"Total jobs returned: {len(jobs)}")
    for j in jobs[:3]:
        print(f"  - {j['title']} @ {j['company']} ({j['location']}) — {j['link'][:60]}")
