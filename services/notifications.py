"""
services/notifications.py — Notification pipeline: daily / weekly / instant.
Daily now has two modes:
  - NEW matches found today   → email the fresh batch
  - No new matches today      → send catch-up of top 10 unactioned matches
    (so users ALWAYS get a daily digest as long as they have pending jobs)
"""
import config
from core.db import safe_select


def _load_top_unactioned(user_id, limit=10):
    """Return top unactioned 60%+ matches posted within the last 20 days, deduped by link."""
    from config import get_supabase
    from datetime import datetime, timezone, timedelta
    try:
        rows = get_supabase().table("user_job_matches").select(
            "job_id,score,match_reason").eq("user_id", user_id).eq(
            "status", "new").gte("score", config.MATCH_THRESHOLD).order(
            "score", desc=True).limit(limit * 3).execute().data or []
    except Exception:
        return []
    if not rows:
        return []
    ids = [r["job_id"] for r in rows]
    smap = {r["job_id"]: r for r in rows}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    try:
        jobs = get_supabase().table("job_pool").select("*").in_(
            "id", ids).gte("posted_at", cutoff).execute().data or []
    except Exception:
        return []
    for j in jobs:
        r = smap.get(j["id"], {})
        j["score"] = r.get("score", 0)
        j["match_reason"] = r.get("match_reason")
    jobs.sort(key=lambda x: x.get("score", 0), reverse=True)
    seen_links, deduped = set(), []
    for j in jobs:
        link = (j.get("link") or "").strip()
        if not link:
            continue  # skip linkless jobs — users can't apply to them
        if link in seen_links:
            continue
        seen_links.add(link)
        deduped.append(j)
        if len(deduped) >= limit:
            break
    return deduped


def _send_email(user_email, user_name, jobs, is_catchup=False):
    try:
        from email_service import send_job_matches_email
        return send_job_matches_email(user_email, user_name, jobs, is_catchup=is_catchup)
    except ImportError:
        print("  ⚠️ email_service not available")
        return False
    except Exception as e:
        print(f"  ⚠️ email send failed: {e}")
        return False


def send_push(user_id, title, body):
    """PLACEHOLDER — wired when Capacitor mobile app ships (FCM/OneSignal)."""
    return False


def notify_daily(user, new_matches, log=print):
    if not config.NOTIFY_DAILY:
        return False

    if new_matches:
        ok = _send_email(user["email"], user.get("name", ""), new_matches, is_catchup=False)
        if ok:
            log(f"  📧 Daily email → {user['email']} ({len(new_matches)} new matches)")
        return ok

    # No new matches scored today — send catch-up of best unactioned matches
    catchup = _load_top_unactioned(user["id"], limit=10)
    if not catchup:
        log(f"  ⏭️  No matches to send for {user['email']}")
        return False

    ok = _send_email(user["email"], user.get("name", ""), catchup, is_catchup=True)
    if ok:
        log(f"  📧 Catch-up email → {user['email']} ({len(catchup)} unactioned matches)")
    return ok


def notify_instant(user, job, log=print):
    """High-score single-job alert. OFF until NOTIFY_INSTANT=true."""
    if not config.NOTIFY_INSTANT:
        return False
    ok = _send_email(user["email"], user.get("name", ""), [job])
    if ok:
        log(f"  ⚡ Instant alert → {user['email']}: {job.get('title')}")
    return ok


def notify_weekly(user, log=print):
    """Weekly summary of all unactioned 60%+ matches. OFF until NOTIFY_WEEKLY=true."""
    if not config.NOTIFY_WEEKLY:
        return False
    jobs = _load_top_unactioned(user["id"], limit=20)
    if not jobs:
        return False
    ok = _send_email(user["email"], user.get("name", ""), jobs)
    if ok:
        log(f"  📅 Weekly digest → {user['email']} ({len(jobs)} open matches)")
    return ok
