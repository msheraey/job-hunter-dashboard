"""
services/premium.py — Premium intelligence endpoints.
ATS score + breakdown, salary estimates, company red flags,
interview prep, company lookup, job summary, skills gap analysis.
Red flags & company info use Serper web search when SERPER_API_KEY is set.
"""
import re
import json
import requests
import config
import prompts
from services.scorer import ai_complete
from core.db import safe_update, safe_select

# Token budgets per feature
ATS_TOKENS        = 600
SALARY_TOKENS     = 200
RED_FLAGS_TOKENS  = 400
INTERVIEW_TOKENS  = 900
SUMMARY_TOKENS    = 200
SKILLS_GAP_TOKENS = 400
COMPANY_TOKENS    = 300


def _parse_json(text):
    if not text:
        return None
    cleaned = re.sub(r"```json|```", "", text).strip()
    m = re.search(r"(\{.*\}|\[.*\])", cleaned, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _serper_search(query, num=5):
    """Optional live web context. Returns snippets text or ''."""
    if not config.SERPER_API_KEY:
        return ""
    try:
        r = requests.post("https://google.serper.dev/search",
                          headers={"X-API-KEY": config.SERPER_API_KEY, "Content-Type": "application/json"},
                          json={"q": query, "num": num}, timeout=10)
        if r.status_code != 200:
            return ""
        organic = r.json().get("organic", [])
        return "\n".join(f"{o.get('title','')}: {o.get('snippet','')}" for o in organic[:num])
    except requests.RequestException:
        return ""


def _serper_first_link(query):
    if not config.SERPER_API_KEY:
        return None
    try:
        r = requests.post("https://google.serper.dev/search",
                          headers={"X-API-KEY": config.SERPER_API_KEY, "Content-Type": "application/json"},
                          json={"q": query, "num": 3}, timeout=10)
        if r.status_code != 200:
            return None
        organic = r.json().get("organic", [])
        return organic[0]["link"] if organic else None
    except (requests.RequestException, KeyError, IndexError):
        return None


def ats_score(user, job):
    cv_text = user.get("cv_text") or user.get("profile_summary") or ""
    if not cv_text:
        return {"error": "No CV uploaded — please upload your CV first for ATS analysis"}
    data = _parse_json(ai_complete(prompts.ats_score_prompt(cv_text, job),
                                   label="ats", max_tokens=ATS_TOKENS))
    if not data:
        return {"error": "AI unavailable — try again shortly"}
    # Ensure label is present
    if "label" not in data and "ats_score" in data:
        s = data["ats_score"]
        data["label"] = ("Excellent" if s >= 90 else "Good" if s >= 70 else
                         "Fair" if s >= 50 else "Weak" if s >= 30 else "Poor")
    return data


def salary_estimate(job):
    data = _parse_json(ai_complete(prompts.salary_estimate_prompt(job),
                                   label="salary", max_tokens=SALARY_TOKENS))
    if not data:
        return {"error": "AI unavailable — try again shortly"}
    # Persist salary range to job_pool for future display
    if job.get("id") and data.get("min_aed") and not job.get("salary_min_aed"):
        safe_update("job_pool", {
            "salary_min_aed": data["min_aed"],
            "salary_max_aed": data.get("max_aed"),
        }, label="salary_persist", id=job["id"])
    return data


def red_flags(job):
    company = job.get("company", "")
    snippets = ""
    if company and company != "Unknown":
        snippets = _serper_search(f'"{company}" UAE reviews complaints scam', num=5)
    data = _parse_json(ai_complete(prompts.red_flags_prompt(job, snippets),
                                   label="red_flags", max_tokens=RED_FLAGS_TOKENS))
    if data:
        data["live_search_used"] = bool(snippets)
        return data
    return {"error": "AI unavailable — try again shortly"}


def interview_prep(user, job):
    profile = user.get("profile_summary") or (user.get("cv_text") or "")[:800]
    if not profile:
        return {"error": "Please add a profile summary or upload your CV first"}
    raw = ai_complete(prompts.interview_prep_prompt(job, profile),
                      label="interview", max_tokens=INTERVIEW_TOKENS)
    data = _parse_json(raw)
    if not data:
        print(f"  ⚠️ interview_prep parse failed — raw: {str(raw)[:300]}")
        return {"error": "AI unavailable — try again shortly"}
    # Normalise likely_questions to always be list of dicts
    lq = data.get("likely_questions") or []
    normalised = []
    for q in lq:
        if isinstance(q, dict):
            normalised.append(q)
        elif isinstance(q, str):
            normalised.append({"q": q, "approach": ""})
    data["likely_questions"] = normalised
    return data


def job_summary(job):
    """3-bullet AI summary of job posting. Cached in job_pool.summary_bullets."""
    if job.get("summary_bullets"):
        try:
            return {"bullets": json.loads(job["summary_bullets"])}
        except (json.JSONDecodeError, TypeError):
            pass
    raw = ai_complete(prompts.job_summary_prompt(job),
                      label="job_summary", max_tokens=SUMMARY_TOKENS)
    data = _parse_json(raw)
    if not data or not isinstance(data, list):
        return {"error": "AI unavailable — try again shortly"}
    bullets = [str(b) for b in data[:3]]
    # Cache in job_pool
    if job.get("id"):
        safe_update("job_pool", {"summary_bullets": json.dumps(bullets)},
                    label="summary_cache", id=job["id"])
    return {"bullets": bullets}


def skills_gap(user_id, user_titles):
    """Cross-job skills gap: aggregate missing keywords from recent ATS scores."""
    from config import get_supabase
    try:
        rows = get_supabase().table("user_job_matches").select(
            "job_id,score").eq("user_id", user_id).gte(
            "score", 60).order("score", desc=True).limit(20).execute().data or []
    except Exception as e:
        return {"error": f"Could not load matches: {str(e)[:80]}"}

    if not rows:
        return {"error": "No matches found — add job titles and let the system score some jobs first"}

    ids = [r["job_id"] for r in rows[:20]]
    try:
        jobs = get_supabase().table("job_pool").select(
            "id,title,company,description").in_("id", ids).execute().data or []
    except Exception:
        return {"error": "AI unavailable — try again shortly"}

    if not jobs:
        return {"error": "No job data available for analysis"}

    # Run ATS-style keyword extraction on top jobs
    keyword_frequency = {}
    for job in jobs[:8]:
        desc = job.get("description") or ""
        # Simple keyword extraction: words 5+ chars that appear in description
        words = re.findall(r'\b[a-zA-Z]{5,}\b', desc.lower())
        for w in set(words):
            keyword_frequency[w] = keyword_frequency.get(w, 0) + 1

    # Top recurring keywords not in a basic stop-list
    stopwords = {"which", "their", "about", "would", "could", "should", "other",
                 "within", "through", "across", "where", "years", "while",
                 "these", "those", "company", "position", "looking"}
    missing = [kw for kw, count in sorted(keyword_frequency.items(),
               key=lambda x: -x[1]) if count >= 2 and kw not in stopwords][:40]

    data = _parse_json(ai_complete(prompts.skills_gap_prompt(missing, user_titles),
                                   label="skills_gap", max_tokens=SKILLS_GAP_TOKENS))
    if not data:
        return {"error": "AI unavailable — try again shortly"}
    return data


def company_info(job):
    """Company website + LinkedIn + AI-generated overview."""
    company = job.get("company", "")
    if not company or company == "Unknown":
        return {"error": "Company name not available for this job"}

    website = None
    linkedin = None
    if config.SERPER_API_KEY:
        website = _serper_first_link(f'"{company}" UAE official website')
        linkedin = _serper_first_link(f'site:linkedin.com/company "{company}"')

    # Always enrich with AI knowledge regardless of Serper
    ai_data = _parse_json(ai_complete(
        prompts.company_research_prompt(company, job.get("title", "")),
        label="company_info", max_tokens=COMPANY_TOKENS))

    return {
        "company": company,
        "website": website,
        "linkedin": linkedin,
        "overview": (ai_data or {}).get("overview"),
        "uae_presence": (ai_data or {}).get("uae_presence"),
        "culture_notes": (ai_data or {}).get("culture_notes"),
        "interview_style": (ai_data or {}).get("interview_style"),
        "live_search_used": bool(config.SERPER_API_KEY),
    }
