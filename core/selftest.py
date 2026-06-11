"""
core/selftest.py — System health checks. Run at startup and on-demand
via /api/self-test. Tests every external dependency so a broken key or
table is caught BEFORE a run wastes the day's budget.
"""
import requests
import config
from config import get_supabase

def check_supabase():
    try:
        for t in ["users", "job_pool", "title_pool", "user_job_matches", "scrape_logs"]:
            get_supabase().table(t).select("*").limit(1).execute()
        return {"ok": True, "msg": "all tables reachable"}
    except Exception as e:
        return {"ok": False, "msg": str(e)[:200]}

def check_dataforseo():
    if not config.DATAFORSEO_LOGIN:
        return {"ok": False, "msg": "credentials not set"}
    try:
        r = requests.get("https://api.dataforseo.com/v3/appendix/user_data",
                         auth=(config.DATAFORSEO_LOGIN, config.DATAFORSEO_PASSWORD), timeout=10)
        if r.status_code == 200:
            d = r.json()["tasks"][0]["result"][0]
            bal = d.get("money", {}).get("balance", "?")
            return {"ok": True, "msg": f"balance ${bal}"}
        return {"ok": False, "msg": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"ok": False, "msg": str(e)[:200]}

def check_groq():
    if not config.GROQ_API_KEY:
        return {"ok": False, "msg": "key not set"}
    try:
        r = requests.get("https://api.groq.com/openai/v1/models",
                         headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"}, timeout=10)
        return {"ok": r.status_code == 200, "msg": "ready" if r.status_code == 200 else f"HTTP {r.status_code}"}
    except Exception as e:
        return {"ok": False, "msg": str(e)[:200]}

def check_gemini():
    if not config.GEMINI_API_KEY:
        return {"ok": False, "msg": "key not set"}
    try:
        r = requests.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={config.GEMINI_API_KEY}", timeout=10)
        return {"ok": r.status_code == 200, "msg": "ready" if r.status_code == 200 else f"HTTP {r.status_code}"}
    except Exception as e:
        return {"ok": False, "msg": str(e)[:200]}

def check_anthropic():
    if not config.ANTHROPIC_API_KEY:
        return {"ok": False, "msg": "key not set"}
    return {"ok": True, "msg": "key present"}

def check_resend():
    if not config.RESEND_API_KEY:
        return {"ok": False, "msg": "key not set"}
    return {"ok": True, "msg": "key present"}

def run_all():
    results = {
        "supabase":   check_supabase(),
        "dataforseo": check_dataforseo(),
        "groq":       check_groq(),
        "gemini":     check_gemini(),
        "anthropic":  check_anthropic(),
        "resend":     check_resend(),
    }
    results["all_ok"] = all(v["ok"] for k, v in results.items() if k in ("supabase", "dataforseo"))
    results["scoring_ok"] = any(results[k]["ok"] for k in ("groq", "gemini", "anthropic"))
    return results
