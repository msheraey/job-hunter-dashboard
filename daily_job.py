#!/usr/bin/env python3
"""
JobHunter Daily Cron Job
Runs once per day via Railway cron service.
1. Scrapes all titles in the pool
2. Scores new jobs for every active user
3. Sends daily email digest to each user with 60%+ matches
4. Exits cleanly

Railway cron schedule: 0 5 * * * (5:00 AM UTC = 9:00 AM Dubai)
"""

import os
import sys
from datetime import datetime, timezone

# Import everything from the scraper
from scraper_v2 import (
    supabase,
    run_full_scrape,
    search_and_score_for_user,
    generate_cv_cover_letter,
    RunLogger
)

try:
    from email_service import send_job_matches_email
    EMAIL_ENABLED = True
except ImportError:
    EMAIL_ENABLED = False
    print("⚠️ email_service not found — emails will be skipped")


def run_daily_job():
    print(f"\n{'='*60}")
    print(f"🌅 JobHunter Daily Job — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}\n")

    logger = RunLogger("daily_job")
    logger.add("🚀 Daily job started")

    # ── Step 1: Scrape all titles ──────────────────────────────────
    logger.add("\n📡 STEP 1: Scraping all titles in pool...")
    try:
        run_full_scrape()
        logger.add("✅ Full scrape complete")
    except Exception as e:
        logger.add(f"⚠️ Scrape error (continuing): {e}")

    # ── Step 2: Get all active users ───────────────────────────────
    logger.add("\n👥 STEP 2: Loading active users...")
    try:
        users = supabase.table("users").select("*").eq("is_active", True).execute().data or []
        logger.add(f"✅ Found {len(users)} active users")
    except Exception as e:
        logger.add(f"❌ Could not load users: {e}")
        logger.finish(success=False, error=e)
        sys.exit(1)

    if not users:
        logger.add("ℹ️ No active users — nothing to score or email")
        logger.finish(success=True)
        return

    # ── Step 3: Score + email each user ───────────────────────────
    logger.add(f"\n🤖 STEP 3: Scoring and emailing {len(users)} users...")
    total_emails = 0
    total_matches = 0

    for i, user in enumerate(users, 1):
        user_email = user.get("email", "unknown")
        user_name = user.get("name") or user_email.split("@")[0]
        logger.add(f"\n[{i}/{len(users)}] Processing: {user_email}")

        try:
            matched_jobs = search_and_score_for_user(user, logger=logger)

            if not matched_jobs:
                logger.add(f"  ℹ️ No 60%+ matches for {user_email} today")
                continue

            total_matches += len(matched_jobs)
            logger.add(f"  ✅ {len(matched_jobs)} matches at 60%+")

            # Mark as emailed in DB
            job_ids = [j["id"] for j in matched_jobs if j.get("id")]
            if job_ids:
                try:
                    supabase.table("user_job_matches").update({"emailed": True}).eq(
                        "user_id", user["id"]
                    ).in_("job_id", job_ids).execute()
                except Exception as e:
                    logger.add(f"  ⚠️ Could not mark emailed: {e}")

            # Send email
            if EMAIL_ENABLED:
                try:
                    send_job_matches_email(
                        user_email=user_email,
                        user_name=user_name,
                        matches=matched_jobs
                    )
                    total_emails += 1
                    logger.add(f"  📧 Email sent to {user_email}")
                except Exception as e:
                    logger.add(f"  ⚠️ Email failed for {user_email}: {e}")
            else:
                logger.add(f"  ⚠️ Email skipped (email_service not available)")

        except Exception as e:
            logger.add(f"  ❌ Error processing {user_email}: {e}")
            continue

    # ── Step 4: Summary ────────────────────────────────────────────
    logger.add(f"\n{'='*60}")
    logger.add(f"✅ Daily job complete")
    logger.add(f"   Users processed: {len(users)}")
    logger.add(f"   Total matches found: {total_matches}")
    logger.add(f"   Emails sent: {total_emails}")
    logger.add(f"{'='*60}")

    logger.total_scraped = len(users)
    logger.total_saved = total_emails
    logger.finish(success=True)
    print("\n✅ Daily job finished successfully")


if __name__ == "__main__":
    run_daily_job()
