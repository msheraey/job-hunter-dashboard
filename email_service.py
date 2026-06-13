"""
email_service.py — Resend-based email dispatch for JobHunter.
Light-mode safe, deduped by link, max 20-day-old jobs.
"""
import json
import os
import resend
from datetime import datetime, timezone, timedelta

resend.api_key = os.environ.get("RESEND_API_KEY")
FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")
APP_URL = os.environ.get("APP_URL", "https://jobhunter.ae")

_CUTOFF_DAYS = 20


def _age_label(posted_at):
    if not posted_at:
        return ""
    try:
        pd = datetime.fromisoformat(str(posted_at).replace("Z", "+00:00"))
        if pd.tzinfo is None:
            pd = pd.replace(tzinfo=timezone.utc)
        days = (datetime.now(timezone.utc) - pd).days
        if days == 0:
            return "Posted today"
        if days == 1:
            return "Posted yesterday"
        if days <= 7:
            return f"Posted {days} days ago"
        if days <= 14:
            return "Posted last week"
        return f"Posted {days} days ago"
    except (ValueError, TypeError):
        return ""


def _is_recent(job):
    posted = job.get("posted_at")
    if not posted:
        return True
    try:
        pd = datetime.fromisoformat(str(posted).replace("Z", "+00:00"))
        if pd.tzinfo is None:
            pd = pd.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - pd).days <= _CUTOFF_DAYS
    except (ValueError, TypeError):
        return True


def _dedup_by_link(jobs):
    seen, out = set(), []
    for j in jobs:
        link = (j.get("link") or "").strip()
        if link and link in seen:
            continue
        if link:
            seen.add(link)
        out.append(j)
    return out


def _score_color(score):
    if score >= 85:
        return "#16a34a"
    if score >= 70:
        return "#2563eb"
    if score >= 60:
        return "#d97706"
    return "#6b7280"


def _parse_match_reason(reason_raw):
    """Return (match_bullets, gap_bullets) from stored match_reason field."""
    if not reason_raw:
        return [], []
    try:
        parsed = json.loads(reason_raw)
        if isinstance(parsed, dict):
            return (parsed.get("m") or []), (parsed.get("g") or [])
    except (json.JSONDecodeError, ValueError):
        pass
    # Legacy plain string — treat as single match bullet
    text = reason_raw.strip()
    return ([text] if text else []), []


def _bullets_html(bullets, color, icon="✓"):
    if not bullets:
        return ""
    items = "".join(
        f'<li style="margin:4px 0;color:#374151;font-size:13px;line-height:1.5;">'
        f'<span style="color:{color};font-weight:700;margin-right:6px;">{icon}</span>{b}</li>'
        for b in bullets
    )
    return (
        f'<ul style="margin:10px 0 0 0;padding:0 0 0 4px;list-style:none;'
        f'border-left:3px solid {color};">{items}</ul>'
    )


def _build_job_card(job):
    score = job.get("score", 0)
    badge_color = _score_color(score)
    age = _age_label(job.get("posted_at"))
    salary = job.get("salary") or ""

    if not salary and job.get("salary_min_aed"):
        mn = job["salary_min_aed"]
        mx = job.get("salary_max_aed")
        salary = f"AED {mn:,}–{mx:,}/mo" if mx else f"AED {mn:,}+/mo"

    meta_parts = [job.get("platform", "").replace("via ", "")]
    if age:
        meta_parts.append(age)
    if salary:
        meta_parts.append(salary)
    meta_line = "  ·  ".join(p for p in meta_parts if p)

    match_bullets, gap_bullets = _parse_match_reason(job.get("match_reason"))
    match_html = _bullets_html(match_bullets, badge_color, "✓")
    gap_html = _bullets_html(gap_bullets[:2], "#ef4444", "△") if gap_bullets else ""

    tags = []
    if job.get("remote_status") and job["remote_status"] not in ("onsite", "unknown"):
        tags.append(job["remote_status"].capitalize())
    if job.get("seniority"):
        tags.append(job["seniority"].capitalize())
    tags_html = ""
    if tags:
        tag_spans = "".join(
            f'<span style="background:#f3f4f6;color:#374151;border-radius:4px;'
            f'padding:2px 8px;font-size:11px;margin-right:6px;display:inline-block;">{t}</span>'
            for t in tags
        )
        tags_html = f'<div style="margin-top:10px;">{tag_spans}</div>'

    return f"""
    <div style="background:#ffffff;background-color:#ffffff;border:1px solid #e5e7eb;
                border-radius:12px;padding:20px;margin-bottom:14px;
                border-left:4px solid {badge_color};">
      <table width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <td style="vertical-align:top;">
            <h3 style="margin:0 0 3px 0;font-size:15px;font-weight:700;color:#111827;">
              {job.get('title', '')}
            </h3>
            <p style="margin:0;color:#6b7280;font-size:13px;font-weight:500;">
              {job.get('company', '')} &middot; {job.get('location', 'UAE')}
            </p>
            <p style="margin:4px 0 0 0;color:#9ca3af;font-size:12px;">{meta_line}</p>
            {match_html}
            {gap_html}
            {tags_html}
          </td>
          <td style="vertical-align:top;text-align:center;padding-left:16px;width:64px;">
            <div style="background:{badge_color};background-color:{badge_color};color:#ffffff;
                        border-radius:50%;width:52px;height:52px;line-height:52px;
                        text-align:center;font-weight:800;font-size:16px;">{score}%</div>
            <div style="font-size:10px;color:#9ca3af;margin-top:3px;">match</div>
          </td>
        </tr>
      </table>
      <div style="margin-top:14px;">
        <a href="{job.get('link', '#')}"
           style="background:{badge_color};background-color:{badge_color};color:#ffffff;
                  padding:8px 20px;border-radius:8px;text-decoration:none;
                  font-size:13px;font-weight:600;display:inline-block;">View &amp; Apply →</a>
      </div>
    </div>"""


def _email_wrapper(title_html, subtitle_html, body_html, footer_note=""):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="light">
  <meta name="supported-color-schemes" content="light">
</head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
             background:#f3f4f6;background-color:#f3f4f6;margin:0;padding:0;"
      bgcolor="#f3f4f6">
  <div style="max-width:600px;margin:0 auto;padding:24px 16px;">

    <!-- Header -->
    <div style="text-align:center;margin-bottom:24px;">
      <div style="display:inline-block;background:#2563eb;background-color:#2563eb;
                  color:#ffffff;border-radius:10px;
                  padding:6px 14px;font-size:18px;font-weight:800;letter-spacing:-0.5px;">
        Job<span style="color:#fbbf24;">Hunter</span>
      </div>
      <p style="color:#6b7280;margin:6px 0 0 0;font-size:12px;">AI Job Matching for the UAE</p>
    </div>

    <!-- Hero -->
    <div style="background:#1e40af;background-color:#1e40af;border-radius:14px;
                padding:24px;text-align:center;margin-bottom:22px;">
      {title_html}
      {subtitle_html}
    </div>

    <!-- Body -->
    {body_html}

    <!-- Footer -->
    <div style="text-align:center;padding:20px 0 8px 0;color:#6b7280;font-size:12px;line-height:1.6;">
      <p style="margin:0 0 4px 0;">
        You're receiving this from
        <a href="{APP_URL}" style="color:#2563eb;text-decoration:none;">JobHunter</a>
        because you have active job alerts.
      </p>
      {f'<p style="margin:0;color:#6b7280;">{footer_note}</p>' if footer_note else ''}
    </div>

  </div>
</body>
</html>"""


def send_job_matches_email(user_email, user_name, jobs, is_catchup=False):
    """Send job matches email. Only includes jobs ≤20 days old, deduped by link, score ≥60."""
    if not jobs:
        print(f"  No jobs to send to {user_email}")
        return False

    matched = [j for j in jobs if j.get("score", 0) >= 60]
    matched = [j for j in matched if _is_recent(j)]
    matched = _dedup_by_link(matched)
    if not matched:
        print(f"  No qualifying matches for {user_email}")
        return False

    matched.sort(key=lambda x: x.get("score", 0), reverse=True)
    job_cards = "".join(_build_job_card(j) for j in matched[:15])

    name_display = user_name or "there"
    count = len(matched)

    if is_catchup:
        subject = f"Your top {count} open job matches — JobHunter"
        title_html = '<h2 style="color:#ffffff;margin:0 0 8px 0;font-size:20px;">Your Top Matches</h2>'
        subtitle_html = (
            f'<p style="color:#bfdbfe;margin:0;font-size:14px;">'
            f'Hi {name_display} — no new jobs today, but you have {count} '
            f'great matches still waiting for you</p>'
        )
    else:
        subject = f"{count} new job match{'es' if count != 1 else ''} today — JobHunter"
        title_html = (
            f'<h2 style="color:#ffffff;margin:0 0 8px 0;font-size:20px;">'
            f'{count} New Job Match{"es" if count != 1 else ""}</h2>'
        )
        subtitle_html = (
            f'<p style="color:#bfdbfe;margin:0;font-size:14px;">'
            f'Hi {name_display} — fresh matches scored against your CV today</p>'
        )

    cta_html = f"""
    <div style="text-align:center;margin:20px 0;">
      <a href="{APP_URL}/dashboard"
         style="background:#2563eb;background-color:#2563eb;color:#ffffff;
                padding:12px 32px;border-radius:10px;text-decoration:none;
                font-size:15px;font-weight:700;display:inline-block;">
        Open Dashboard →
      </a>
    </div>"""

    body_html = job_cards + cta_html
    html = _email_wrapper(
        title_html, subtitle_html, body_html,
        footer_note="Only showing jobs with 60%+ match posted in the last 20 days."
    )
    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": user_email,
            "subject": subject,
            "html": html,
        })
        print(f"  ✅ Email sent to {user_email} ({count} matches, catchup={is_catchup})")
        return True
    except Exception as e:
        print(f"  ❌ Email error for {user_email}: {e}")
        return False


def send_cv_cover_letter_email(user_email, user_name, job_title, company,
                               cv_text, cover_letter_text):
    """Send generated CV and cover letter to user."""
    title_html = '<h2 style="color:#ffffff;margin:0 0 8px 0;font-size:20px;">Your Tailored Application</h2>'
    subtitle_html = f'<p style="color:#a7f3d0;margin:0;font-size:14px;">{job_title} at {company}</p>'

    def _text_card(heading, content, color):
        return f"""
        <div style="background:#ffffff;background-color:#ffffff;border:1px solid #e5e7eb;
                    border-radius:12px;padding:24px;margin-bottom:16px;
                    border-top:3px solid {color};">
          <h3 style="color:#111827;margin:0 0 14px 0;font-size:15px;font-weight:700;">{heading}</h3>
          <div style="color:#374151;font-size:13px;line-height:1.7;white-space:pre-wrap;">{content}</div>
        </div>"""

    body_html = (
        _text_card("Cover Letter", cover_letter_text, "#2563eb") +
        _text_card("Tailored CV", cv_text, "#059669") +
        f"""<div style="background:#fffbeb;background-color:#fffbeb;border:1px solid #fde68a;
                       border-radius:10px;padding:14px;margin-top:8px;
                       font-size:12px;color:#92400e;">
          Tip: Download the DOCX from the app for the fully formatted,
          ATS-optimised version. The text above is a plain-text preview only.
        </div>"""
    )

    html = _email_wrapper(title_html, subtitle_html, body_html)
    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": user_email,
            "subject": f"Tailored CV & cover letter — {job_title} at {company}",
            "html": html,
        })
        print(f"  ✅ CV email sent to {user_email}")
        return True
    except Exception as e:
        print(f"  ❌ CV email error: {e}")
        return False
