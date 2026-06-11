#!/usr/bin/env python3
"""
Email service for JobHunter
Uses Resend API to send job match notifications and CV/cover letters
"""

import os
import resend
from datetime import datetime

resend.api_key = os.environ.get("RESEND_API_KEY")
FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")


def send_job_matches_email(user_email, user_name, jobs):
    """
    Send daily job matches email to user.
    Only jobs with score >= 60 are included.
    """
    if not jobs:
        print(f"  No jobs to send to {user_email}")
        return False

    # Filter 60%+
    matched = [j for j in jobs if j.get("score", 0) >= 60]
    if not matched:
        print(f"  No 60%+ matches for {user_email}")
        return False

    matched.sort(key=lambda x: x.get("score", 0), reverse=True)

    # Build email HTML
    job_rows = ""
    for job in matched:
        score = job.get("score", 0)
        if score >= 80:
            badge_color = "#22c55e"
        elif score >= 60:
            badge_color = "#f59e0b"
        else:
            badge_color = "#6b7280"

        salary_str = f"<br><small style='color:#6b7280'>{job.get('salary','')}</small>" if job.get("salary") else ""
        posted_str = ""
        if job.get("posted_at"):
            try:
                posted_dt = datetime.fromisoformat(str(job["posted_at"]).replace("Z", "+00:00"))
                posted_str = f"<br><small style='color:#9ca3af'>Posted: {posted_dt.strftime('%b %d, %Y')}</small>"
            except:
                pass

        job_rows += f"""
        <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;padding:20px;margin-bottom:16px;">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                <div style="flex:1;">
                    <h3 style="margin:0 0 4px 0;font-size:16px;color:#111827;">{job.get('title','')}</h3>
                    <p style="margin:0;color:#6b7280;font-size:14px;">{job.get('company','')} · {job.get('location','UAE')}</p>
                    <p style="margin:4px 0 0 0;color:#9ca3af;font-size:13px;">{job.get('platform','').replace('via ','')}{salary_str}{posted_str}</p>
                </div>
                <div style="text-align:center;margin-left:16px;">
                    <div style="background:{badge_color};color:white;border-radius:20px;padding:6px 14px;font-weight:700;font-size:15px;">{score}%</div>
                    <small style="color:#9ca3af;font-size:11px;">match</small>
                </div>
            </div>
            <div style="margin-top:16px;display:flex;gap:10px;">
                <a href="{job.get('link','#')}" style="background:#2563eb;color:white;padding:8px 18px;border-radius:8px;text-decoration:none;font-size:14px;font-weight:600;">View & Apply</a>
            </div>
        </div>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
    <body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f9fafb;margin:0;padding:0;">
        <div style="max-width:600px;margin:0 auto;padding:32px 16px;">

            <div style="text-align:center;margin-bottom:32px;">
                <h1 style="color:#2563eb;font-size:28px;margin:0;">JobHunter</h1>
                <p style="color:#6b7280;margin:4px 0 0 0;">AI Job Matching for the Emirates</p>
            </div>

            <div style="background:#2563eb;border-radius:12px;padding:24px;text-align:center;margin-bottom:24px;">
                <h2 style="color:white;margin:0 0 8px 0;font-size:22px;">🎯 {len(matched)} New Job Match{'es' if len(matched) != 1 else ''}</h2>
                <p style="color:#bfdbfe;margin:0;">Hi {user_name or 'there'} — here are your best matches today</p>
            </div>

            {job_rows}

            <div style="text-align:center;padding:24px;color:#9ca3af;font-size:13px;">
                <p>You're receiving this because you set up job alerts on <a href="https://uaejobhunter.lovable.app" style="color:#2563eb;">JobHunter</a>.</p>
                <p>Only showing jobs with 60%+ match to your profile.</p>
            </div>
        </div>
    </body>
    </html>
    """

    try:
        response = resend.Emails.send({
            "from": FROM_EMAIL,
            "to": user_email,
            "subject": f"🎯 {len(matched)} new job match{'es' if len(matched) != 1 else ''} today — JobHunter",
            "html": html
        })
        print(f"  ✅ Email sent to {user_email} ({len(matched)} matches)")
        return True
    except Exception as e:
        print(f"  ❌ Email error for {user_email}: {e}")
        return False


def send_cv_cover_letter_email(user_email, user_name, job_title, company, cv_text, cover_letter_text):
    """
    Send generated CV and cover letter to user.
    """
    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f9fafb;margin:0;padding:0;">
        <div style="max-width:600px;margin:0 auto;padding:32px 16px;">

            <div style="text-align:center;margin-bottom:32px;">
                <h1 style="color:#2563eb;font-size:28px;margin:0;">JobHunter</h1>
            </div>

            <div style="background:#059669;border-radius:12px;padding:24px;text-align:center;margin-bottom:24px;">
                <h2 style="color:white;margin:0 0 8px 0;">📄 Your Tailored Application</h2>
                <p style="color:#a7f3d0;margin:0;">{job_title} at {company}</p>
            </div>

            <div style="background:white;border:1px solid #e5e7eb;border-radius:12px;padding:24px;margin-bottom:16px;">
                <h3 style="color:#111827;margin:0 0 16px 0;border-bottom:2px solid #2563eb;padding-bottom:8px;">Cover Letter</h3>
                <div style="color:#374151;font-size:14px;line-height:1.7;white-space:pre-wrap;">{cover_letter_text}</div>
            </div>

            <div style="background:white;border:1px solid #e5e7eb;border-radius:12px;padding:24px;margin-bottom:16px;">
                <h3 style="color:#111827;margin:0 0 16px 0;border-bottom:2px solid #2563eb;padding-bottom:8px;">Tailored CV</h3>
                <div style="color:#374151;font-size:14px;line-height:1.7;white-space:pre-wrap;">{cv_text}</div>
            </div>

            <div style="text-align:center;padding:24px;color:#9ca3af;font-size:13px;">
                <p>Generated by <a href="https://uaejobhunter.lovable.app" style="color:#2563eb;">JobHunter</a> AI</p>
            </div>
        </div>
    </body>
    </html>
    """

    try:
        response = resend.Emails.send({
            "from": FROM_EMAIL,
            "to": user_email,
            "subject": f"📄 Your tailored CV & cover letter — {job_title} at {company}",
            "html": html
        })
        print(f"  ✅ CV email sent to {user_email}")
        return True
    except Exception as e:
        print(f"  ❌ CV email error: {e}")
        return False
