#!/usr/bin/env python3
"""
JobHunter Scraper v2 — Multi-user, on-demand pool architecture
- Serper.dev Google Jobs API (single call, instant results)
- Supabase for storage
- On-demand scraping with 24h TTL cache
- Trusted platforms whitelist only
"""

import os
import re
import requests
from datetime import datetime, timezone, timedelta
from supabase import create_client

# ── Config ────────────────────────────────────────────────────────────────
SERPER_API_KEY  = os.environ.get("SERPER_API_KEY")
SUPABASE_URL    = os.environ.get("SUPABASE_URL")
SUPABASE_KEY    = os.environ.get("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TTL_HOURS = 24

# ── Trusted platforms — whitelist only ────────────────────────────────────
TRUSTED_DOMAINS = [
    "linkedin.com",
    "indeed.com",
    "bayt.com",
    "naukrigulf.com",
    "gulftalent.com",
    "gofindit.com",
]

# ── Junk title filter ─────────────────────────────────────────────────────
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
    return re.sub(r'\s+', ' ', title.strip().lower())


# ── Serper Search ─────────────────────────────────────────────────────────
def serper_search(keyword):
    """
    Single Serper.dev API call — instant results, no waiting.
    Returns list of raw job dicts or empty list on failure.
    """
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={
                "X-API-KEY": SERPER_API_KEY,
                "Content-Type": "application/json"
            },
            json={
                "q": keyword,
                "type": "jobs",
                "location": "United Arab Emirates",
                "gl": "ae",
                "hl": "en",
                "num": 100
            },
            timeout=30
        )

        if response.status_code != 200:
            print(f"  Serper error {response.status_code} for '{keyword}'")
            return []

        data = response.json()
        jobs = data.get("jobs", [])
        print(f"  Found {len(jobs)} jobs for '{keyword}'")
        return jobs

    except Exception as e:
        print(f"  Serper error for '{keyword}': {e}")
        return []


# ── Pool logic ────────────────────────────────────────────────────────────
def is_fresh(last_scraped_str):
    if not last_scraped_str:
        return False
    try:
        last = datetime.fromisoformat(last_scraped_str.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - last < timedelta(hours=TTL_HOURS)
    except Exception:
        return False

def get_or_create_title(keyword):
    normalized = normalize_title(keyword)
    result = supabase.table("title_pool")\
        .select("*")\
        .eq("normalized", normalized)\
        .execute()

    if result.data:
        return result.data[0], False

    insert = supabase.table("title_pool").insert({
        "keyword": keyword,
        "normalized": normalized,
        "request_count": 1
    }).execute()

    return insert.data[0], True

def increment_request_count(title_id):
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
        company = item.get("company", "Unknown").strip()

        if is_junk(title) or is_skip(title) or len(title) < 5:
            continue

        # Serper returns link directly
        link = item.get("link", "")

        if not link or not link.startswith("http"):
            continue

        # Trusted platforms only
        if not any(d in link for d in TRUSTED_DOMAINS):
            continue

        if link in existing_links:
            continue

        # Parse posted date
        posted_at = None
        try:
            posted_raw = item.get("datePosted") or item.get("date")
            if posted_raw:
                posted_at = datetime.fromisoformat(
                    posted_raw.replace("Z", "+00:00")
                ).isoformat()
        except Exception:
            posted_at = None

        supabase.table("job_pool").insert({
            "title": title[:200],
            "company": company[:100],
            "location": item.get("location", "UAE"),
            "posted_at": posted_at,
            "link": link,
            "platform": item.get("source", "Google Jobs"),
            "salary": item.get("salary", ""),
            "description": str(item.get("description") or "")[:1500],
            "search_keyword": normalized,
            "last_scraped": datetime.now(timezone.utc).isoformat(),
        }).execute()

        existing_links.add(link)
        saved += 1

    supabase.table("title_pool")\
        .update({"last_scraped": datetime.now(timezone.utc).isoformat()})\
        .eq("normalized", normalized)\
        .execute()

    print(f"  Saved {saved} new jobs for '{keyword}'")
    return saved


# ── Main entry point ──────────────────────────────────────────────────────
def search_jobs(keyword):
    """
    Main function: given a keyword, return jobs.
    - Checks pool first (24h TTL)
    - If fresh, returns cached results
    - If stale or new, scrapes Serper and saves to pool
    """
    print(f"\nSearching: '{keyword}'")

    title_record, is_new = get_or_create_title(keyword)
    title_id = title_record["id"]

    if not is_new:
        increment_request_count(title_id)

    last_scraped = title_record.get("last_scraped")

    if is_fresh(last_scraped):
        print(f"  Cache hit — last scraped {last_scraped}")
        return get_cached_jobs(keyword)

    print(f"  Cache miss — scraping Serper...")
    items = serper_search(keyword)

    if items:
        save_jobs(keyword, items)

    return get_cached_jobs(keyword)


if __name__ == "__main__":
    jobs = search_jobs("pharmacy manager UAE")
    print(f"\n{'='*50}")
    print(f"Total jobs returned: {len(jobs)}")
    for j in jobs[:3]:
        print(f"  - {j['title']} @ {j['company']} ({j['location']}) — {j['link'][:60]}")
