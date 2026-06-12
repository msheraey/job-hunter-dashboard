"""
services/scorer.py — AI scoring chain: Groq (free, ~0.5s) → Gemini → Haiku.
Circuit breakers per provider; one provider being down costs ~zero time.
Single AI call returns score + reason + classification (industry/seniority/
remote/visa) — classification enriches job_pool on first score.
"""
import re
import json
import time
import requests
import config
import prompts
from utils.filters import infer_industry
from core.retry import CircuitBreaker
from core.db import safe_update

groq_breaker   = CircuitBreaker("groq", threshold=4, cooldown=120)
gemini_breaker = CircuitBreaker("gemini", threshold=4, cooldown=120)
haiku_breaker  = CircuitBreaker("haiku", threshold=4, cooldown=180)

INDUSTRY_MAP = {
    "health": "Healthcare & Pharmacy", "pharma": "Healthcare & Pharmacy", "medical": "Healthcare & Pharmacy",
    "retail": "Retail", "fmcg": "FMCG", "logistic": "Logistics & Supply Chain", "supply": "Logistics & Supply Chain",
    "tech": "Technology", "finance": "Finance & Banking", "bank": "Finance & Banking",
    "hospital": "Hospitality & Tourism", "tourism": "Hospitality & Tourism", "real estate": "Real Estate",
    "auto": "Automotive", "education": "Education", "construction": "Construction & Engineering",
    "engineer": "Construction & Engineering", "media": "Media & Marketing", "market": "Media & Marketing",
    "hr": "HR & Recruitment", "recruit": "HR & Recruitment",
}

def map_industry(text):
    if not text:
        return "Other"
    t = text.lower()
    if text in config.INDUSTRY_LIST:
        return text
    for k, v in INDUSTRY_MAP.items():
        if k in t:
            return v
    return "Other"

def parse_ai_json(text, title="", description=""):
    """Extract the result dict from an AI response. Defensive against markdown fences."""
    out = {"score": None, "industry": None, "reason": None,
           "seniority": None, "remote": None, "visa_likelihood": None}
    if not text:
        out["industry"] = infer_industry(title, description)
        return out
    cleaned = re.sub(r"```json|```", "", text).strip()
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            v = data.get("score")
            if v is not None:
                try:
                    out["score"] = max(0, min(100, int(v)))
                except (ValueError, TypeError):
                    pass
            out["industry"] = map_industry(data.get("industry"))
            r = data.get("reason")
            out["reason"] = str(r).strip()[:200] if r else None
            out["seniority"] = data.get("seniority")
            out["remote"] = data.get("remote")
            out["visa_likelihood"] = data.get("visa_likelihood")
        except json.JSONDecodeError:
            pass
    if out["score"] is None:
        m2 = re.search(r"\b([1-9]?\d|100)\b", cleaned)
        if m2:
            out["score"] = max(0, min(100, int(m2.group(1))))
    # Keyword fallback if AI returned no industry
    if not out["industry"] or out["industry"] == "Other":
        keyword_industry = infer_industry(title, description)
        if keyword_industry != "Other":
            out["industry"] = keyword_industry
    return out

def _call_groq(prompt):
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {config.GROQ_API_KEY}", "Content-Type": "application/json"},
        json={"model": "llama-3.3-70b-versatile",
              "messages": [{"role": "user", "content": prompt}],
              "temperature": 0.1, "max_tokens": 200},
        timeout=15,
    )
    if r.status_code == 429:
        raise RuntimeError("groq 429")
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

def _call_gemini(prompt):
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={config.GEMINI_API_KEY}",
        json={"contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"temperature": 0.1, "maxOutputTokens": 200}},
        timeout=15,
    )
    if r.status_code == 429:
        raise RuntimeError("gemini 429")
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]

def _call_haiku(prompt):
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": config.ANTHROPIC_API_KEY,
                 "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": "claude-haiku-4-5", "max_tokens": 200,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=15,
    )
    if r.status_code == 429:
        raise RuntimeError("haiku 429")
    r.raise_for_status()
    data = r.json()
    if "content" not in data:
        raise RuntimeError(f"haiku bad response: {str(data)[:100]}")
    return data["content"][0]["text"]

PROVIDERS = [
    ("groq",   groq_breaker,   _call_groq,   lambda: config.GROQ_API_KEY),
    ("gemini", gemini_breaker, _call_gemini, lambda: config.GEMINI_API_KEY),
    ("haiku",  haiku_breaker,  _call_haiku,  lambda: config.ANTHROPIC_API_KEY),
]

def ai_complete(prompt, label="ai"):
    """Run prompt through the provider chain. Returns raw text or None."""
    for name, breaker, fn, has_key in PROVIDERS:
        if not has_key() or breaker.is_open():
            continue
        try:
            text = fn(prompt)
            breaker.record_success()
            return text
        except Exception as e:
            breaker.record_failure()
            print(f"    ⚠️ {name} failed for {label}: {str(e)[:80]}")
    return None

def score_job(job, user_profile):
    """Score one job. Returns parsed dict (score may be None on total failure)."""
    prompt = prompts.scoring_prompt(
        job.get("title", ""), job.get("company", ""),
        job.get("description", ""), user_profile, ", ".join(config.INDUSTRY_LIST))
    text = ai_complete(prompt, label="scoring")
    return parse_ai_json(text, title=job.get("title", ""), description=job.get("description", ""))

def score_jobs_for_user(jobs, user):
    """Score up to MAX_JOBS_PER_USER within MAX_SECONDS_PER_USER. Enrich job_pool."""
    profile_parts = []
    if user.get("profile_summary"):
        profile_parts.append(f"Summary: {user['profile_summary']}")
    if user.get("cv_text"):
        profile_parts.append(f"CV: {user['cv_text'][:1000]}")
    if not profile_parts:
        return jobs
    user_profile = "\n".join(profile_parts)

    start = time.time()
    to_score = jobs[:config.MAX_JOBS_PER_USER]
    for i, job in enumerate(to_score):
        if time.time() - start > config.MAX_SECONDS_PER_USER:
            print(f"    ⏱️ Time budget — scored {i}/{len(to_score)}")
            for rest in to_score[i:]:
                rest.setdefault("score", 0)
            break
        result = score_job(job, user_profile)
        job["score"] = result["score"] if isinstance(result["score"], int) else 0
        job["match_reason"] = result["reason"]
        # Enrich job_pool once (first scorer wins)
        if job.get("id") and result["industry"] and not job.get("industry"):
            enrich = {"industry": result["industry"]}
            if result.get("seniority"):
                enrich["seniority"] = result["seniority"]
            if result.get("remote"):
                enrich["remote_status"] = result["remote"]
            if result.get("visa_likelihood"):
                enrich["visa_likelihood"] = result["visa_likelihood"]
            safe_update("job_pool", enrich, label="enrich", id=job["id"])
            job.update(enrich)
    for job in jobs[config.MAX_JOBS_PER_USER:]:
        job["score"] = 0
    return jobs
