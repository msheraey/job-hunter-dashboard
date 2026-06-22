#!/usr/bin/env python3
"""
daily_job.py — Cron orchestrator (entry point unchanged for Railway cron).
Steps: validate env → self-test → archive → scrape → score+notify each user.
Run modes:  python daily_job.py            (daily)
            python daily_job.py weekly     (weekly digests, when flag enabled)
"""
import sys
from config import validate_env
import config

def run_daily():
    from core.logger import RunLogger
    from core.selftest import run_all
    from services.archiver import archive_old_jobs
    from services.scraper import run_full_scrape
    from services.matcher import search_and_score_for_user
    from services.notifications import notify_daily
    from core.db import safe_select

    logger = RunLogger("daily_job")
    logger.add("🌅 Daily job started")
    try:
        # STEP 0 — self-test: abort before wasting budget if core deps are down
        health = run_all()
        for k, v in health.items():
            if isinstance(v, dict):
                logger.add(f"  {'🟢' if v['ok'] else '🔴'} {k}: {v['msg']}")
        if not health.get("all_ok"):
            logger.add("❌ Core dependency down (supabase/dataforseo) — aborting run")
            logger.finish(success=False, error="self-test failed")
            return
        if not health.get("scoring_ok"):
            logger.add("❌ No scoring provider available — aborting run")
            logger.finish(success=False, error="no scoring provider")
            return

        logger.add("\n📦 STEP 1: Archiving old jobs...")
        archive_old_jobs(log=logger.add)

        logger.add("\n🔗 STEP 1.5: Checking job links...")
        from services.link_checker import check_links
        check_links(log=logger.add)

        logger.add("\n📡 STEP 2: Scraping all titles...")
        run_full_scrape(logger)

        logger.add("\n👥 STEP 3: Loading users...")
        from config import get_supabase as _sb
        def _all_users():
            off, batch = 0, 50
            while True:
                page = _sb().table("users").select("*").range(off, off + batch - 1).execute().data or []
                yield from page
                if len(page) < batch:
                    break
                off += batch
        users = list(_all_users())
        logger.add(f"✅ {len(users)} active users")

        logger.add("\n🤖 STEP 4: Scoring & notifying...")
        total_matches, emails = 0, 0
        for i, u in enumerate(users, 1):
            logger.add(f"\n[{i}/{len(users)}] {u.get('email')}")
            try:
                matches = search_and_score_for_user(u, logger=logger)
                total_matches += len(matches)
                if notify_daily(u, matches, log=logger.add):
                    emails += 1
            except Exception as e:
                logger.add(f"  ❌ User failed (continuing): {str(e)[:150]}")

        logger.add(f"\n✅ Daily job complete — {len(users)} users, {total_matches} matches, {emails} emails")
        logger.finish(success=True)
    except Exception as e:
        logger.add(f"❌ Fatal: {e}")
        logger.finish(success=False, error=e)

def run_weekly():
    from core.logger import RunLogger
    from services.notifications import notify_weekly
    from core.db import safe_select
    logger = RunLogger("weekly_digest")
    if not config.NOTIFY_WEEKLY:
        logger.add("ℹ️ NOTIFY_WEEKLY is off — nothing to do")
        logger.finish(success=True)
        return
    users = safe_select("users")
    sent = sum(1 for u in users if notify_weekly(u, log=logger.add))
    logger.add(f"✅ Weekly digests sent: {sent}")
    logger.finish(success=True)

if __name__ == "__main__":
    validate_env()
    if len(sys.argv) > 1 and sys.argv[1] == "weekly":
        run_weekly()
    else:
        run_daily()
