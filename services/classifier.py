"""
services/classifier.py — Job quality score (pure heuristic, zero AI cost).
AI classification (industry/seniority/visa) happens inside scorer.py on the
same call as scoring. This module covers the non-AI quality signals.
"""
from datetime import datetime, timezone

def quality_score(job):
    """0-100 heuristic: completeness + recency + platform trust."""
    s = 0
    if job.get("salary"):
        s += 25
    desc = job.get("description") or ""
    if len(desc) > 400:
        s += 20
    elif len(desc) > 150:
        s += 10
    p = job.get("posted_at")
    if p:
        try:
            pd = datetime.fromisoformat(str(p).replace("Z", "+00:00"))
            if pd.tzinfo is None:
                pd = pd.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - pd).days
            if age <= 3:
                s += 30
            elif age <= 7:
                s += 20
            elif age <= 14:
                s += 10
        except (ValueError, TypeError):
            pass
    platform = (job.get("platform") or "").lower()
    if "linkedin" in platform:
        s += 15
    elif any(x in platform for x in ("bayt", "indeed", "gulftalent", "naukrigulf")):
        s += 10
    if (job.get("company") or "Unknown") != "Unknown":
        s += 10
    return min(100, s)
