"""
services/account_links.py — Linked job-site accounts (profile page).

NOTE: Real OAuth / auto-apply is partner-only on LinkedIn and unavailable on
other UAE boards. "Linked" here means the user has confirmed they have an
account on that platform. Status is stored in user_linked_accounts and shown
in the profile page so users can track which boards to apply through manually.
"""
from datetime import datetime, timezone
from typing import Optional
from core.db import safe_select, safe_upsert

# Ordered by relevance for UAE job seekers.
# SITE_META provides display name and URL for the frontend.
SITES = [
    "linkedin", "indeed", "bayt", "naukrigulf", "gulftalent",
    "dubizzle", "laimoon", "drjobs", "glassdoor", "monster",
    "xpatjobs", "ziprecruiter",
]

SITE_META = {
    "linkedin":    {"label": "LinkedIn",      "url": "https://www.linkedin.com/jobs"},
    "indeed":      {"label": "Indeed",        "url": "https://ae.indeed.com"},
    "bayt":        {"label": "Bayt",          "url": "https://www.bayt.com"},
    "naukrigulf":  {"label": "Naukri Gulf",   "url": "https://www.naukrigulf.com"},
    "gulftalent":  {"label": "Gulf Talent",   "url": "https://www.gulftalent.com"},
    "dubizzle":    {"label": "Dubizzle",      "url": "https://dubizzle.com/jobs"},
    "laimoon":     {"label": "Laimoon",       "url": "https://www.laimoon.com/ae/jobs"},
    "drjobs":      {"label": "DrJobs",        "url": "https://drjobs.ae"},
    "glassdoor":   {"label": "Glassdoor",     "url": "https://www.glassdoor.com/Job"},
    "monster":     {"label": "Monster",       "url": "https://www.monster.com"},
    "xpatjobs":    {"label": "Xpat Jobs",     "url": "https://www.xpatjobs.com"},
    "ziprecruiter":{"label": "ZipRecruiter",  "url": "https://www.ziprecruiter.com"},
}

VALID_STATUSES = ("unlinked", "linked", "expired")


def get_links(user_id: str):
    """Return link status for all platforms for this user."""
    rows = safe_select("user_linked_accounts", user_id=user_id)
    site_map = {r["site"]: r for r in rows}
    return [
        {
            "site": site,
            "label": SITE_META[site]["label"],
            "url": SITE_META[site]["url"],
            "status": site_map.get(site, {}).get("status", "unlinked"),
            "linked_at": site_map.get(site, {}).get("linked_at"),
            "meta": site_map.get(site, {}).get("meta"),
        }
        for site in SITES
    ]


def set_link(user_id: str, site: str, status: str, meta: Optional[dict] = None):
    """Upsert link status for one platform. Returns True on success."""
    if site not in SITES:
        return False
    if status not in VALID_STATUSES:
        return False
    row = {
        "user_id": user_id,
        "site": site,
        "status": status,
        "meta": meta or {},
    }
    if status == "linked":
        row["linked_at"] = datetime.now(timezone.utc).isoformat()
    return safe_upsert("user_linked_accounts", row,
                       on_conflict="user_id,site", label="link_account")
