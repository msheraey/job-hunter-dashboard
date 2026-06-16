"""
services/scorer.py — AI provider chain, split into isolated lanes so a
failure storm in one feature can't trip breakers that block another:
  - "scoring": Groq (free, ~0.5s) → Gemini → Haiku. Used by nightly job scoring.
  - "interactive": Gemini → Groq → Haiku. Used by premium features, CV/cover
    letter generation, and title-synonym expansion.
Each lane has its own circuit breaker per provider; one provider being down
costs ~zero time. Single scoring AI call returns score + reason + classification
(industry/seniority/remote/visa) — classification enriches job_pool on first score.
"""
import re
import json
import time
import requests
import config
import prompts
from utils.filters import infer_industry
from utils.ai_json import extract_json
from core.retry import CircuitBreaker, RateLimitError
from core.db import safe_update

groq_breaker_scoring     = CircuitBreaker("scoring_groq",     threshold=4, cooldown=120)
gemini_breaker_scoring   = CircuitBreaker("scoring_gemini",   threshold=4, cooldown=120)
haiku_breaker_scoring    = CircuitBreaker("scoring_haiku",    threshold=4, cooldown=180)

groq_breaker_interactive   = CircuitBreaker("interactive_groq",   threshold=4, cooldown=120)
gemini_breaker_interactive = CircuitBreaker("interactive_gemini", threshold=4, cooldown=120)
haiku_breaker_interactive  = CircuitBreaker("interactive_haiku",  threshold=4, cooldown=180)

INDUSTRY_MAP = {
    # Longer/more specific keys listed first for readability; map_industry uses longest-key-wins
    "supermarket": "Retail", "grocery": "Retail",
    "healthcare": "Healthcare & Pharmacy", "pharmaceutical": "Healthcare & Pharmacy",
    "pharmacy": "Healthcare & Pharmacy", "pharma": "Healthcare & Pharmacy",
    "medical": "Healthcare & Pharmacy", "health": "Healthcare & Pharmacy",
    "hospitality": "Hospitality & Tourism", "tourism": "Hospitality & Tourism",
    "hotel": "Hospitality & Tourism", "restaurant": "Hospitality & Tourism",
    "retail": "Retail", "fmcg": "FMCG", "consumer goods": "FMCG",
    "logistics": "Logistics & Supply Chain", "supply chain": "Logistics & Supply Chain",
    "logistic": "Logistics & Supply Chain", "supply": "Logistics & Supply Chain",
    "technology": "Technology", "software": "Technology", "tech": "Technology",
    "banking": "Finance & Banking", "finance": "Finance & Banking", "fintech": "Finance & Banking",
    "real estate": "Real Estate", "property management": "Real Estate",
    "automotive": "Automotive", "dealership": "Automotive",
    "education": "Education",
    "construction": "Construction & Engineering", "engineering": "Construction & Engineering",
    "engineer": "Construction & Engineering",
    "marketing": "Media & Marketing", "advertising": "Media & Marketing", "media": "Media & Marketing",
    "recruitment": "HR & Recruitment", "human resources": "HR & Recruitment", "hr": "HR & Recruitment",
}

def map_industry(text):
    if not text:
        return "Other"
    t = text.lower()
    if text in config.INDUSTRY_LIST:
        return text
    # Longest-key-wins: more specific/multi-word keys beat short ambiguous ones
    best, best_len = None, 0
    for k, v in INDUSTRY_MAP.items():
        if k in t and len(k) > best_len:
            best, best_len = v, len(k)
    return best or "Other"

def parse_ai_json(text, title="", description=""):
    """Extract the result dict from an AI response. Defensive against markdown fences."""
    out = {"score": None, "industry": None, "reason": None,
           "seniority": None, "remote": None, "visa_likelihood": None}
    if not text:
        out["industry"] = infer_industry(title, description)
        return out
    data = extract_json(text)
    if isinstance(data, dict):
        v = data.get("score")
        if v is not None:
            try:
                out["score"] = max(0, min(100, int(v)))
            except (ValueError, TypeError):
                pass
        out["industry"] = map_industry(data.get("industry"))
        # New bullet format: match_bullets + gap_bullets
        mb = data.get("match_bullets") or []
        gb = data.get("gap_bullets") or []
        if isinstance(mb, list) and mb:
            match_b = [str(b).strip() for b in mb[:5] if b]
            if not isinstance(gb, list):
                print(f"  ⚠️ gap_bullets wrong type ({type(gb).__name__}) — discarding")
                gb = []
            gap_b = [str(b).strip() for b in gb[:4] if b]
            out["reason"] = json.dumps({"m": match_b, "g": gap_b})
        else:
            # Legacy plain-string reason
            r = data.get("reason")
            out["reason"] = str(r).strip()[:300] if r else None
        out["seniority"] = data.get("seniority")
        out["remote"] = data.get("remote")
        out["visa_likelihood"] = data.get("visa_likelihood")
    if out["score"] is None:
        # Prefer a number explicitly labelled as a score over any arbitrary number
        cleaned = re.sub(r"```json|```", "", text).strip()
        m2 = re.search(r'"score"\s*:\s*(\d+)', cleaned)
        if not m2:
            m2 = re.search(r'\bscore\b["\s:]*(\d+)', cleaned, re.IGNORECASE)
        if m2:
            out["score"] = max(0, min(100, int(m2.group(1))))
    if not out["industry"] or out["industry"] == "Other":
        keyword_industry = infer_industry(title, description)
        if keyword_industry != "Other":
            out["industry"] = keyword_industry
    return out


def _call_groq(prompt, max_tokens=200):
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {config.GROQ_API_KEY}", "Content-Type": "application/json"},
        json={"model": "llama-3.3-70b-versatile",
              "messages": [{"role": "user", "content": prompt}],
              "temperature": 0.1, "max_tokens": max_tokens},
        timeout=30,
    )
    if r.status_code == 429:
        raise RateLimitError("groq 429")
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _call_gemini(prompt, max_tokens=200):
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={config.GEMINI_API_KEY}",
        json={"contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"temperature": 0.1, "maxOutputTokens": max_tokens}},
        timeout=30,
    )
    if r.status_code == 429:
        raise RateLimitError("gemini 429")
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _call_haiku(prompt, max_tokens=200):
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": config.ANTHROPIC_API_KEY,
                 "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": "claude-haiku-4-5", "max_tokens": max_tokens,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=30,
    )
    if r.status_code == 429:
        raise RateLimitError("haiku 429")
    r.raise_for_status()
    data = r.json()
    if "content" not in data:
        raise RuntimeError(f"haiku bad response: {str(data)[:100]}")
    return data["content"][0]["text"]


LANES = {
    "scoring": [
        ("groq",   groq_breaker_scoring,   _call_groq,   lambda: config.GROQ_API_KEY),
        ("gemini", gemini_breaker_scoring, _call_gemini, lambda: config.GEMINI_API_KEY),
        ("haiku",  haiku_breaker_scoring,  _call_haiku,  lambda: config.ANTHROPIC_API_KEY),
    ],
    "interactive": [
        ("gemini", gemini_breaker_interactive, _call_gemini, lambda: config.GEMINI_API_KEY),
        ("groq",   groq_breaker_interactive,   _call_groq,   lambda: config.GROQ_API_KEY),
        ("haiku",  haiku_breaker_interactive,  _call_haiku,  lambda: config.ANTHROPIC_API_KEY),
    ],
}


def ai_complete(prompt, label="ai", max_tokens=200, lane="interactive"):
    """Run prompt through the lane's provider chain. Returns raw text or None."""
    for name, breaker, fn, has_key in LANES[lane]:
        if not has_key() or breaker.is_open():
            continue
        try:
            text = fn(prompt, max_tokens)
            breaker.record_success()
            return text
        except RateLimitError as e:
            # Rate-limited, not down — don't penalize the breaker, just move on.
            print(f"    ⏳ {name}/{lane} rate-limited for {label}: {str(e)[:80]}")
        except Exception as e:
            breaker.record_failure()
            print(f"    ⚠️ {name}/{lane} failed for {label}: {str(e)[:80]}")
    return None


def score_job(job, user_profile):
    """Score one job. Returns parsed dict (score may be None on total failure)."""
    prompt = prompts.scoring_prompt(
        job.get("title", ""), job.get("company", ""),
        job.get("description", ""), user_profile, ", ".join(config.INDUSTRY_LIST))
    text = ai_complete(prompt, label="scoring", max_tokens=600, lane="scoring")
    return parse_ai_json(text, title=job.get("title", ""), description=job.get("description", ""))


def score_jobs_for_user(jobs, user):
    """Score up to MAX_JOBS_PER_USER within MAX_SECONDS_PER_USER. Enrich job_pool."""
    profile_parts = []
    if user.get("profile_summary"):
        profile_parts.append(f"Summary: {user['profile_summary']}")
    if user.get("cv_text"):
        profile_parts.append(f"CV: {user['cv_text'][:1200]}")
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
        ai_industry = result.get("industry")
        should_enrich = (
            job.get("id") and ai_industry and ai_industry != "Other"
            and ai_industry != job.get("industry")  # always overwrite if AI has a better value
        )
        if should_enrich:
            enrich = {"industry": ai_industry}
            if result.get("seniority"):
                enrich["seniority"] = result["seniority"]
            if result.get("remote"):
                enrich["remote_status"] = result["remote"]
            if result.get("visa_likelihood"):
                enrich["visa_likelihood"] = result["visa_likelihood"]
            safe_update("job_pool", enrich, label="enrich", id=job["id"])
            job.update(enrich)
        elif job.get("id") and result.get("seniority") and not job.get("seniority"):
            # Still write seniority/remote/visa even if industry already set
            partial = {}
            if result.get("seniority") and not job.get("seniority"):
                partial["seniority"] = result["seniority"]
            if result.get("remote") and not job.get("remote_status"):
                partial["remote_status"] = result["remote"]
            if result.get("visa_likelihood") and not job.get("visa_likelihood"):
                partial["visa_likelihood"] = result["visa_likelihood"]
            if partial:
                safe_update("job_pool", partial, label="enrich_partial", id=job["id"])
                job.update(partial)
    for job in jobs[config.MAX_JOBS_PER_USER:]:
        job["score"] = 0
    return jobs
