"""
services/archiver.py — Move jobs older than JOB_MAX_DAYS to old_jobs.
Strips columns old_jobs doesn't have (prevents PGRST204 errors).
"""
from datetime import datetime, timezone, timedelta
import config
from config import get_supabase
from core.db import safe_insert, safe_delete

ALLOWED_COLS = {"title", "company", "location", "posted_at", "link", "platform",
                "description", "search_keyword", "salary", "last_scraped",
                "fingerprint", "industry"}

def job_age_days(posted_at):
    if not posted_at:
        return None
    try:
        pd = datetime.fromisoformat(str(posted_at).replace("Z", "+00:00"))
        if pd.tzinfo is None:
            pd = pd.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - pd).days
    except (ValueError, TypeError):
        return None

def archive_old_jobs(log=print):
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.JOB_MAX_DAYS)
    try:
        old = get_supabase().table("job_pool").select("*").lt(
            "posted_at", cutoff.isoformat()).execute().data or []
    except Exception as e:
        log(f"  ⚠️ Archive query failed: {e}")
        return 0
    if not old:
        log(f"📦 No jobs older than {config.JOB_MAX_DAYS} days")
        return 0
    moved = 0
    for job in old:
        clean = {k: v for k, v in job.items() if k in ALLOWED_COLS}
        clean["original_id"] = job["id"]
        clean["age_days_at_move"] = job_age_days(job.get("posted_at"))
        clean["moved_at"] = datetime.now(timezone.utc).isoformat()
        if safe_insert("old_jobs", clean, label="archive"):
            deleted = safe_delete("job_pool", id=job["id"])
            if not deleted:
                log(f"  ⚠️ Archive: job {job['id']} inserted to old_jobs but pool delete failed — will retry next run")
            safe_delete("user_job_matches", job_id=job["id"])
            moved += 1
    log(f"📦 Archived {moved} jobs")
    return moved

def get_old_jobs(limit=100, offset=0):
    try:
        return get_supabase().table("old_jobs").select("*").order(
            "moved_at", desc=True).limit(limit).offset(offset).execute().data or []
    except Exception as e:
        print(f"  ⚠️ old_jobs read: {e}")
        return []
