"""
services/scraper.py — DataForSEO scraping.
PRIMARY: Live endpoint (synchronous, ~3-8s, no polling, no timeouts).
FALLBACK: Async task_post/task_get (if Live errors), capped at TITLE_TIMEOUT_S.
"""
import time
import requests
import config
from config import get_supabase
from core.retry import CircuitBreaker
from core.db import safe_select, safe_update, safe_insert
from utils.filters import (is_junk, is_nationality_restricted, normalize_title,
                           validate_title, make_fingerprint, is_gender_restricted)
from datetime import datetime, timezone, timedelta

live_breaker = CircuitBreaker("dataforseo_live", threshold=3, cooldown=300)

def _payload(keyword):
    return [{
        "keyword": keyword.strip(),
        "location_name": "United Arab Emirates",
        "language_name": "English",
        "depth": config.SCRAPE_DEPTH,
    }]

def _live_search(keyword, log):
    """Synchronous Live endpoint — results in the same response."""
    r = requests.post(
        "https://api.dataforseo.com/v3/serp/google/jobs/live/advanced",
        auth=(config.DATAFORSEO_LOGIN, config.DATAFORSEO_PASSWORD),
        json=_payload(keyword), timeout=config.LIVE_TIMEOUT_S,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Live HTTP {r.status_code}: {r.text[:150]}")
    data = r.json()
    task = (data.get("tasks") or [{}])[0]
    if task.get("status_code") != 20000:
        raise RuntimeError(f"Live task error: {task.get('status_message')}")
    result = (task.get("result") or [{}])[0]
    items = result.get("items") or []
    log(f"  ⚡ Live: {len(items)} results")
    return items

def _async_search(keyword, log):
    """Fallback: async flow with hard deadline. Slow but works when Live is down."""
    deadline = time.time() + config.TITLE_TIMEOUT_S
    r = requests.post(
        "https://api.dataforseo.com/v3/serp/google/jobs/task_post",
        auth=(config.DATAFORSEO_LOGIN, config.DATAFORSEO_PASSWORD),
        json=_payload(keyword), timeout=15,
    )
    if r.status_code != 200:
        log(f"  ❌ Async post HTTP {r.status_code}")
        return []
    task = (r.json().get("tasks") or [{}])[0]
    if task.get("status_code") not in (20000, 20100) or not task.get("id"):
        log(f"  ❌ Async task error: {task.get('status_message')}")
        return []
    task_id = task["id"]
    for attempt, wait in enumerate([3, 5, 8, 12, 15, 20, 25, 30]):
        if time.time() > deadline:
            log(f"  ⏱️ Title timeout ({config.TITLE_TIMEOUT_S}s) — skipping")
            return []
        time.sleep(wait)
        try:
            g = requests.get(
                f"https://api.dataforseo.com/v3/serp/google/jobs/task_get/advanced/{task_id}",
                auth=(config.DATAFORSEO_LOGIN, config.DATAFORSEO_PASSWORD), timeout=15,
            )
            if g.status_code != 200:
                continue
            result = ((g.json().get("tasks") or [{}])[0].get("result") or [None])[0]
            if result and result.get("items"):
                log(f"  ✅ Async: {len(result['items'])} results (attempt {attempt+1})")
                return result["items"]
        except requests.RequestException:
            continue
    log("  ❌ Async: no results after all attempts")
    return []

def dataforseo_search(keyword, log=print):
    """Live primary → async fallback, with circuit breaker on Live."""
    if live_breaker.is_open():
        log("  ⛔ Live circuit open — using async")
        return _async_search(keyword, log)
    try:
        items = _live_search(keyword, log)
        live_breaker.record_success()
        return items
    except Exception as e:
        live_breaker.record_failure()
        log(f"  ⚠️ Live failed ({str(e)[:100]}) — falling back to async")
        return _async_search(keyword, log)

# ── Cache / pool logic ───────────────────────────────────────
def is_fresh(last_scraped):
    if not last_scraped:
        return False
    try:
        last = datetime.fromisoformat(str(last_scraped).replace("Z", "+00:00"))
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - last < timedelta(hours=config.TTL_HOURS)
    except (ValueError, TypeError):
        return False

def get_today_scrape_count():
    try:
        today = datetime.now(timezone.utc).date().isoformat()
        r = get_supabase().table("title_pool").select("id", count="exact").gte("last_scraped", today).execute()
        return r.count or 0
    except Exception as e:
        print(f"  ⚠️ scrape count: {e}")
        return 0

def is_over_daily_ceiling():
    return get_today_scrape_count() >= config.MAX_DAILY_SCRAPES

def get_or_create_title(keyword):
    normalized = normalize_title(keyword)
    rows = safe_select("title_pool", normalized=normalized, label="title lookup")
    if rows:
        safe_update("title_pool", {"request_count": (rows[0].get("request_count") or 0) + 1}, id=rows[0]["id"])
        return rows[0], False
    row = safe_insert("title_pool", {"keyword": keyword, "normalized": normalized, "request_count": 1})
    return row, True

def get_cached_jobs(keyword):
    try:
        return get_supabase().table("job_pool").select("*").eq(
            "search_keyword", normalize_title(keyword)).order("posted_at", desc=True).execute().data or []
    except Exception as e:
        print(f"  ⚠️ cache read: {e}")
        return []

def save_jobs(keyword, items, log=print):
    normalized = normalize_title(keyword)
    existing = {r["link"] for r in safe_select("job_pool", columns="link", search_keyword=normalized)}
    saved = 0
    for item in items:
        title = (item.get("title") or "").strip()
        company = (item.get("employer_name") or "Unknown").strip()
        link = item.get("source_url") or ""
        if (is_junk(title) or is_nationality_restricted(title) or len(title) < 5
                or not link.startswith("http")
                or not any(d in link for d in config.TRUSTED_DOMAINS)
                or link in existing):
            continue
        posted_at = None
        raw = item.get("timestamp")
        if raw:
            try:
                posted_at = datetime.fromisoformat(raw.replace(" +00:00", "+00:00")).isoformat()
            except (ValueError, TypeError):
                posted_at = None
        row = {
            "title": title[:200], "company": company[:100],
            "location": item.get("location", "UAE"), "posted_at": posted_at,
            "link": link, "platform": (item.get("source_name") or "Google Jobs").replace("via ", "")[:100],
            "description": ((item.get("description") or item.get("snippet") or ""))[:1500],
            "search_keyword": normalized, "salary": item.get("salary", ""),
            "last_scraped": datetime.now(timezone.utc).isoformat(),
            "fingerprint": make_fingerprint(title, company, item.get("location")),
        }
        if safe_insert("job_pool", row, label="job save"):
            existing.add(link)
            saved += 1
    safe_update("title_pool", {"last_scraped": datetime.now(timezone.utc).isoformat()}, normalized=normalized)
    log(f"  💾 Saved {saved} new jobs for '{keyword}'")
    return saved

def search_jobs(keyword, user_gender=None, logger=None):
    log = logger.add if logger else print
    if not validate_title(keyword):
        log(f"❌ Invalid title: '{keyword}'")
        return []
    log(f"🔍 '{keyword}'")
    title_record, _ = get_or_create_title(keyword)
    if title_record and is_fresh(title_record.get("last_scraped")):
        log("  ✅ Cache fresh")
        jobs = get_cached_jobs(keyword)
    elif is_over_daily_ceiling():
        log("  ⚠️ Daily ceiling — stale cache")
        jobs = get_cached_jobs(keyword)
    else:
        items = dataforseo_search(keyword, log)
        if items:
            saved = save_jobs(keyword, items, log)
            if logger:
                logger.total_scraped += 1
                logger.total_saved += saved
        jobs = get_cached_jobs(keyword)

    cutoff = datetime.now(timezone.utc) - timedelta(days=config.JOB_MAX_DAYS)
    fresh = []
    for j in jobs:
        p = j.get("posted_at")
        if p:
            try:
                pd = datetime.fromisoformat(str(p).replace("Z", "+00:00"))
                if pd.tzinfo is None:
                    pd = pd.replace(tzinfo=timezone.utc)
                if pd < cutoff:
                    continue
            except (ValueError, TypeError):
                pass
        fresh.append(j)
    jobs = fresh

    if user_gender and user_gender != "prefer_not_to_say":
        jobs = [j for j in jobs if not is_gender_restricted(
            f"{j.get('title','')} {j.get('description','')}", user_gender)]
    return jobs

def run_full_scrape(logger):
    titles = safe_select("title_pool", label="titles")
    if not titles:
        logger.add("ℹ️ No titles in pool")
        return
    logger.add(f"📋 {len(titles)} titles to process")
    for i, t in enumerate(titles, 1):
        logger.add(f"[{i}/{len(titles)}] {t['keyword']}")
        search_jobs(t["keyword"], logger=logger)
    logger.add(f"✅ Scrape done — {logger.total_scraped} scraped, {logger.total_saved} new jobs")
