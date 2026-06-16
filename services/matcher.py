"""
services/matcher.py — Per-user matching orchestration.
Guarantees: every job scored at most ONCE per user (already_scored filter),
skipped/applied jobs never re-emailed, quality score attached to matches.
"""
import threading
import config
from collections import Counter
from datetime import datetime, timezone, timedelta
from config import get_supabase
from core.db import safe_select, safe_upsert, safe_update
from core.error_log import log_error
from services.scraper import search_jobs
from services.scorer import score_jobs_for_user
from services.classifier import quality_score
from utils.filters import is_gender_restricted

def _infer_user_industry(user_id):
    """Derive user's primary industry from their highest-scoring matches (≥70)."""
    try:
        rows = get_supabase().table("user_job_matches").select(
            "job_id").eq("user_id", user_id).gte("score", 70).limit(60).execute().data or []
        if not rows:
            return None
        ids = [r["job_id"] for r in rows]
        jobs = get_supabase().table("job_pool").select("industry").in_("id", ids).execute().data or []
        industries = [j["industry"] for j in jobs if j.get("industry") and j["industry"] != "Other"]
        if not industries:
            return None
        return Counter(industries).most_common(1)[0][0]
    except Exception:
        return None


def _user_titles(user_id):
    links = safe_select("user_titles", columns="title_id", user_id=user_id)
    if not links:
        return []
    ids = [l["title_id"] for l in links]
    try:
        return get_supabase().table("title_pool").select(
            "keyword,normalized,last_scraped").in_("id", ids).execute().data or []
    except Exception as e:
        print(f"  ⚠️ titles fetch: {e}")
        log_error("matcher._user_titles", str(e))
        return []

def _already_scored(user_id):
    rows = safe_select("user_job_matches", columns="job_id", user_id=user_id)
    return {r["job_id"] for r in rows}

def _dedupe(jobs, scored_ids):
    out, links, fps = [], set(), set()
    for j in jobs:
        if j.get("id") in scored_ids:
            continue
        link, fp = j.get("link", ""), j.get("fingerprint", "")
        if (link and link in links) or (fp and fp in fps):
            continue
        if link:
            links.add(link)
        if fp:
            fps.add(fp)
        out.append(j)
    return out

def _save_matches(user_id, scored_jobs, emailed_flag):
    matched = []
    for job in scored_jobs:
        score = job.get("score", 0) or 0
        if score < 1:
            continue
        qs = quality_score(job)
        # Persist quality_score to job_pool so frontend can query it directly
        if job.get("id") and not job.get("quality_score"):
            safe_update("job_pool", {"quality_score": qs}, label="quality_score", id=job["id"])
        job["quality_score"] = qs
        safe_upsert("user_job_matches", {
            "user_id": user_id, "job_id": job["id"], "score": score,
            "match_reason": job.get("match_reason"),
            "quality_score": qs,
            "emailed": emailed_flag and score >= config.MATCH_THRESHOLD,
        }, on_conflict="user_id,job_id", label="match save")
        if score >= config.MATCH_THRESHOLD:
            matched.append(job)
    matched.sort(key=lambda x: (x.get("score", 0), x.get("quality_score", 0)), reverse=True)
    return matched

def search_and_score_for_user(user, logger=None):
    """Daily-cron path: scrape-backed search, score NEW jobs only, return 60%+ matches."""
    log = logger.add if logger else print
    user_id, gender = user.get("id"), user.get("gender")
    titles = _user_titles(user_id)
    if not titles:
        log(f"  No titles for user {user_id}")
        return []
    scored_ids = _already_scored(user_id)
    all_jobs = []
    for t in titles:
        all_jobs.extend(search_jobs(t["keyword"], user_gender=gender, logger=logger))
    all_jobs = _dedupe(all_jobs, scored_ids)
    if not all_jobs:
        return []
    if len(all_jobs) > config.MAX_JOBS_PER_USER:
        log(f"  ⚠️ Capping {len(all_jobs)} → {config.MAX_JOBS_PER_USER} new jobs")
        all_jobs = all_jobs[:config.MAX_JOBS_PER_USER]
    log(f"  🤖 Scoring {len(all_jobs)} new jobs...")
    scored = score_jobs_for_user(all_jobs, user)
    matched = _save_matches(user_id, scored, emailed_flag=True)
    log(f"  ✅ {len(matched)} at {config.MATCH_THRESHOLD}%+")
    return matched

def refresh_matches_for_user(user, logger=None):
    """Dashboard path: instant return of stored matches; score new pool jobs;
    background-scrape any titles with no pool yet."""
    log = logger.add if logger else print
    user_id, gender = user.get("id"), user.get("gender")
    titles = _user_titles(user_id)
    if not titles:
        return {"matches": [], "pending_titles": []}
    scored_ids = _already_scored(user_id)
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.JOB_MAX_DAYS)
    pending, to_score = [], []
    for t in titles:
        all_pooled = safe_select("job_pool", search_keyword=t["normalized"])
        if not all_pooled:
            # Only mark pending if not already scraped recently — a fresh scrape
            # with 0 results means the title is too niche; don't retry endlessly
            from services.scraper import is_fresh
            if not is_fresh(t.get("last_scraped")):
                pending.append(t["keyword"])
            continue
        # Enforce same date cutoff as search_jobs() — exclude stale but keep undated
        pooled = []
        for pj in all_pooled:
            p = pj.get("posted_at")
            if p:
                try:
                    pd = datetime.fromisoformat(str(p).replace("Z", "+00:00"))
                    if pd.tzinfo is None:
                        pd = pd.replace(tzinfo=timezone.utc)
                    if pd < cutoff:
                        continue
                except (ValueError, TypeError):
                    pass
            pooled.append(pj)
        for j in pooled:
            if gender and gender != "prefer_not_to_say" and is_gender_restricted(
                    f"{j.get('title','')} {j.get('description','')}", gender):
                continue
            to_score.append(j)
    to_score = _dedupe(to_score, scored_ids)
    if to_score:
        if len(to_score) > config.MAX_JOBS_PER_USER:
            to_score = to_score[:config.MAX_JOBS_PER_USER]
        log(f"  🤖 Scoring {len(to_score)} new pooled jobs...")
        scored = score_jobs_for_user(to_score, user)
        _save_matches(user_id, scored, emailed_flag=False)
    if pending:
        def bg():
            for kw in pending:
                try:
                    search_jobs(kw, user_gender=gender)
                except Exception as e:
                    print(f"  ❌ bg scrape {kw}: {e}")
                    log_error("matcher.refresh_matches_for_user.bg_scrape", str(e), context=kw)
        threading.Thread(target=bg, daemon=True).start()
        log(f"  🌐 Background scraping {len(pending)} titles")

    # Return all stored 60%+ matches, excluding skipped/applied
    try:
        rows = get_supabase().table("user_job_matches").select(
            "job_id,score,status,match_reason,quality_score").eq(
            "user_id", user_id).gte("score", config.MATCH_THRESHOLD).eq(
            "status", "new").execute().data or []
    except Exception as e:
        print(f"  ⚠️ matches read: {e}")
        log_error("matcher.refresh_matches_for_user.matches_read", str(e))
        rows = []
    if not rows:
        return {"matches": [], "pending_titles": pending}
    ids = [r["job_id"] for r in rows]
    rmap = {r["job_id"]: r for r in rows}
    try:
        jobs = get_supabase().table("job_pool").select("*").in_("id", ids).execute().data or []
    except Exception as e:
        print(f"  ⚠️ jobs read: {e}")
        log_error("matcher.refresh_matches_for_user.jobs_read", str(e))
        jobs = []
    for j in jobs:
        r = rmap.get(j["id"], {})
        j["score"] = r.get("score", 0)
        j["status"] = r.get("status", "new")
        j["match_reason"] = r.get("match_reason") or j.get("match_reason")
        j["quality_score"] = r.get("quality_score") or quality_score(j)
    jobs.sort(key=lambda x: (x.get("score", 0), x.get("quality_score", 0)), reverse=True)
    # Deduplicate by link — same job may be scraped from multiple platforms
    seen_links, deduped = set(), []
    for j in jobs:
        link = (j.get("link") or "").strip()
        if link and link in seen_links:
            continue
        if link:
            seen_links.add(link)
        deduped.append(j)

    # Tag each match as industry-specific or cross-industry
    user_industry = _infer_user_industry(user_id)
    for j in deduped:
        j["industry_match"] = bool(
            user_industry and j.get("industry") and j["industry"] == user_industry
        )

    return {"matches": deduped, "pending_titles": pending, "user_industry": user_industry}

def set_job_status(user_id, job_id, status):
    """Update job status. Accepted: new | skipped | applied | interview | offer | rejected."""
    if status not in ("new", "skipped", "applied", "interview", "offer", "rejected"):
        return False
    return safe_upsert("user_job_matches",
                       {"user_id": user_id, "job_id": job_id, "status": status},
                       on_conflict="user_id,job_id", label="status")


def update_match_notes(user_id, job_id, notes):
    """Store free-text notes against a match (recruiter name, follow-up date, etc.)."""
    return safe_upsert("user_job_matches",
                       {"user_id": user_id, "job_id": job_id, "notes": notes},
                       on_conflict="user_id,job_id", label="notes")
