"""
services/link_checker.py — Checks job posting URLs and marks dead ones.

HEAD request per link (with GET fallback for HEAD-blocking sites).
404/410 → link_active = false. Everything else is left untouched so
temporary network blips don't falsely kill live postings.

Run automatically from daily_job.py (step 1.5) or on demand via
POST /api/check-links (admin only).
"""
import concurrent.futures
import requests
from datetime import datetime, timezone, timedelta
from config import get_supabase
from core.error_log import log_error

_TIMEOUT = 8          # seconds per request
_WORKERS = 12         # concurrent HEAD requests
_BATCH   = 500        # max jobs per run (avoid hammering)
_DEAD_CODES = {404, 410}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; JobHunterBot/1.0; "
        "+https://jobhunter.ae)"
    )
}


def _is_dead(url: str) -> bool | None:
    """
    Returns True  → link is dead (mark inactive)
            False → link appears alive
            None  → inconclusive (skip)
    """
    try:
        r = requests.head(
            url, timeout=_TIMEOUT, allow_redirects=True,
            headers=_HEADERS,
        )
        if r.status_code in _DEAD_CODES:
            return True
        if r.status_code == 405:
            # Site blocks HEAD — try GET with stream to avoid downloading body
            r = requests.get(
                url, timeout=_TIMEOUT, allow_redirects=True,
                headers=_HEADERS, stream=True,
            )
            r.close()
            return r.status_code in _DEAD_CODES
        if r.status_code < 400:
            return False
        return None  # 5xx, 429, etc. — don't touch
    except requests.exceptions.ConnectionError:
        return True   # DNS / connection refused → dead
    except requests.exceptions.Timeout:
        return None
    except Exception:
        return None


def check_links(log=print) -> dict:
    """
    Fetch up to _BATCH jobs posted in the last 30 days where
    link_active is true (or null), check each URL, and update the DB.
    Returns a summary dict.
    """
    sb = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    try:
        rows = (
            sb.table("job_pool")
            .select("id,link")
            .gte("posted_at", cutoff)
            .neq("link_active", False)   # true OR null
            .not_.is_("link", "null")
            .limit(_BATCH)
            .execute()
            .data or []
        )
    except Exception as e:
        log(f"  ❌ link_checker: DB fetch failed: {e}")
        log_error("link_checker.fetch", str(e))
        return {"checked": 0, "dead": 0, "error": str(e)}

    if not rows:
        log("  ℹ️ link_checker: no links to check")
        return {"checked": 0, "dead": 0}

    log(f"  🔗 Checking {len(rows)} job links…")
    dead_ids: list[str] = []

    def _check(row):
        url = row.get("link", "")
        if not url or not url.startswith("http"):
            return None
        result = _is_dead(url)
        if result is True:
            return row["id"]
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        for job_id in pool.map(_check, rows):
            if job_id:
                dead_ids.append(job_id)

    # Bulk-update dead links in one round-trip
    if dead_ids:
        try:
            sb.table("job_pool").update({"link_active": False}).in_("id", dead_ids).execute()
        except Exception as e:
            log(f"  ❌ link_checker: DB update failed: {e}")
            log_error("link_checker.update", str(e))

    log(f"  ✅ link_checker: {len(rows)} checked, {len(dead_ids)} dead")
    return {"checked": len(rows), "dead": len(dead_ids)}
