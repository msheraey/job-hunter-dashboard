"""
services/notifications.py — Notification pipeline: daily / weekly / instant.
ALL THREE BUILT; instant + weekly are OFF by default (config flags).
Flip NOTIFY_INSTANT=true in Railway env after app launch — zero code changes.
Email via Resend now; push notifications slot in at send_push() when the
mobile app (Capacitor) ships.
"""
import config
from core.db import safe_select

def _send_email(user_email, user_name, jobs, subject_prefix="🎯"):
    try:
        from email_service import send_job_matches_email
        return send_job_matches_email(user_email, user_name, jobs)
    except ImportError:
        print("  ⚠️ email_service not available")
        return False
    except Exception as e:
        print(f"  ⚠️ email send failed: {e}")
        return False

def send_push(user_id, title, body):
    """PLACEHOLDER — wired when Capacitor mobile app ships (FCM/OneSignal)."""
    return False

def notify_daily(user, matches, log=print):
    if not config.NOTIFY_DAILY or not matches:
        return False
    ok = _send_email(user["email"], user.get("name", ""), matches)
    if ok:
        log(f"  📧 Daily email → {user['email']} ({len(matches)} matches)")
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
    rows = safe_select("user_job_matches", user_id=user["id"])
    fresh = [r for r in rows if (r.get("status") or "new") == "new"
             and (r.get("score") or 0) >= config.MATCH_THRESHOLD]
    if not fresh:
        return False
    from config import get_supabase
    ids = [r["job_id"] for r in fresh][:20]
    try:
        jobs = get_supabase().table("job_pool").select("*").in_("id", ids).execute().data or []
    except Exception as e:
        print(f"  ⚠️ weekly jobs read: {e}")
        return False
    smap = {r["job_id"]: r["score"] for r in fresh}
    for j in jobs:
        j["score"] = smap.get(j["id"], 0)
    jobs.sort(key=lambda x: x["score"], reverse=True)
    ok = _send_email(user["email"], user.get("name", ""), jobs)
    if ok:
        log(f"  📅 Weekly digest → {user['email']} ({len(jobs)} open matches)")
    return ok
