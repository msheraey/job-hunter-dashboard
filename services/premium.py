"""
services/premium.py — Premium intelligence endpoints (working code):
ATS score + CV feedback, salary estimates, company red flags,
interview prep, company site + LinkedIn page lookup.
Red flags & company info use Serper web search when SERPER_API_KEY is set;
otherwise degrade gracefully to AI-knowledge-only.
"""
import re
import json
import requests
import config
import prompts
from services.scorer import ai_complete

def _parse_json(text):
    if not text:
        return None
    cleaned = re.sub(r"```json|```", "", text).strip()
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
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
    data = _parse_json(ai_complete(prompts.ats_score_prompt(user.get("cv_text", ""), job), label="ats"))
    return data or {"error": "AI unavailable — try again shortly"}

def salary_estimate(job):
    data = _parse_json(ai_complete(prompts.salary_estimate_prompt(job), label="salary"))
    return data or {"error": "AI unavailable — try again shortly"}

def red_flags(job):
    company = job.get("company", "")
    snippets = ""
    if company and company != "Unknown":
        snippets = _serper_search(f'"{company}" UAE reviews complaints scam', num=5)
    data = _parse_json(ai_complete(prompts.red_flags_prompt(job, snippets), label="red_flags"))
    if data:
        data["live_search_used"] = bool(snippets)
        return data
    return {"error": "AI unavailable — try again shortly"}

def interview_prep(user, job):
    profile = user.get("profile_summary", "") or (user.get("cv_text", "") or "")[:600]
    data = _parse_json(ai_complete(prompts.interview_prep_prompt(job, profile), label="interview"))
    return data or {"error": "AI unavailable — try again shortly"}

def company_info(job):
    """Company website + LinkedIn page. Needs SERPER_API_KEY for live lookup."""
    company = job.get("company", "")
    if not company or company == "Unknown":
        return {"error": "Company name not available for this job"}
    if not config.SERPER_API_KEY:
        return {"error": "Live company lookup requires SERPER_API_KEY (set in Railway)",
                "company": company}
    website = _serper_first_link(f'"{company}" UAE official website')
    linkedin = _serper_first_link(f'site:linkedin.com/company "{company}"')
    return {"company": company, "website": website, "linkedin": linkedin,
            "note": None if (website or linkedin) else "No confident results found"}
