#!/usr/bin/env python3
import os
import json
import threading
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

from supabase import create_client
supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY"))

# ============================================================================
# Helper Functions
# ============================================================================

def update_user_last_active(user_id):
    try:
        supabase.table("users").update({"last_active_at": datetime.now(timezone.utc).isoformat()}).eq("id", user_id).execute()
    except:
        pass

def get_analytics_data():
    """Fetch all analytics data from existing tables"""
    
    # Overview stats
    total_jobs = supabase.table("job_pool").select("id", count="exact").execute().count or 0
    new_jobs_24h = supabase.table("job_pool").select("id", count="exact").gt("created_at", (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()).execute().count or 0
    active_users = supabase.table("users").select("id", count="exact").eq("is_active", True).execute().count or 0
    total_users = supabase.table("users").select("id", count="exact").execute().count or 0
    scrapes_today = supabase.table("title_pool").select("id", count="exact").gte("last_scraped", datetime.now(timezone.utc).date().isoformat()).execute().count or 0
    daily_limit = 200
    
    # Match stats
    avg_match_score = supabase.table("user_job_matches").select("score").execute().data or []
    avg_score = round(sum(m.get("score", 0) for m in avg_match_score) / len(avg_match_score)) if avg_match_score else 0
    total_matches = len(avg_match_score)
    high_matches = len([m for m in avg_match_score if m.get("score", 0) >= 80])
    
    # Jobs over time (last 30 days)
    jobs_over_time = []
    for i in range(30):
        date = (datetime.now(timezone.utc) - timedelta(days=i)).date().isoformat()
        count = supabase.table("job_pool").select("id", count="exact").gte("created_at", date).lt("created_at", (datetime.fromisoformat(date) + timedelta(days=1)).isoformat()).execute().count or 0
        jobs_over_time.append({"date": date, "count": count})
    
    # Industry distribution
    industries = supabase.table("job_pool").select("industry").execute().data or []
    industry_counts = {}
    for j in industries:
        ind = j.get("industry") or "Unknown"
        industry_counts[ind] = industry_counts.get(ind, 0) + 1
    industry_distribution = [{"name": k, "count": v} for k, v in sorted(industry_counts.items(), key=lambda x: -x[1])[:10]]
    
    # Match score distribution
    score_ranges = {"0-20": 0, "21-40": 0, "41-60": 0, "61-80": 0, "81-100": 0}
    for m in avg_match_score:
        score = m.get("score", 0)
        if score <= 20: score_ranges["0-20"] += 1
        elif score <= 40: score_ranges["21-40"] += 1
        elif score <= 60: score_ranges["41-60"] += 1
        elif score <= 80: score_ranges["61-80"] += 1
        else: score_ranges["81-100"] += 1
    
    # Users over time
    users_over_time = []
    for i in range(30):
        date = (datetime.now(timezone.utc) - timedelta(days=i)).date().isoformat()
        count = supabase.table("users").select("id", count="exact").gte("created_at", date).lt("created_at", (datetime.fromisoformat(date) + timedelta(days=1)).isoformat()).execute().count or 0
        users_over_time.append({"date": date, "count": count})
    
    # Gender distribution
    genders = supabase.table("users").select("gender").execute().data or []
    gender_counts = {"male": 0, "female": 0, "prefer_not_to_say": 0}
    for u in genders:
        g = u.get("gender") or "prefer_not_to_say"
        gender_counts[g] = gender_counts.get(g, 0) + 1
    
    # CV upload rate
    cv_uploaded = supabase.table("users").select("id", count="exact").not_.is_("cv_text", "null").execute().count or 0
    cv_rate = round(cv_uploaded / total_users * 100) if total_users > 0 else 0
    
    # Last scrape status
    last_scrape = supabase.table("scrape_logs").select("started_at,status").order("started_at", desc=True).limit(1).execute().data
    last_scrape_status = last_scrape[0] if last_scrape else None
    
    return {
        "overview": {
            "total_jobs": total_jobs,
            "new_jobs_24h": new_jobs_24h,
            "active_users": active_users,
            "total_users": total_users,
            "scrapes_today": scrapes_today,
            "daily_limit": daily_limit,
            "scrapes_remaining": daily_limit - scrapes_today,
            "avg_match_score": avg_score,
            "total_matches": total_matches,
            "high_matches": high_matches,
            "cv_upload_rate": cv_rate,
            "last_scrape_status": last_scrape_status
        },
        "jobs_over_time": jobs_over_time,
        "industry_distribution": industry_distribution,
        "score_distribution": score_ranges,
        "users_over_time": users_over_time,
        "gender_distribution": gender_counts
    }

# ============================================================================
# API Routes
# ============================================================================

@app.route('/')
def dashboard():
    return build_dashboard_html()

@app.route('/health')
def health():
    return jsonify({"status": "ok"})

@app.route('/api/analytics')
def api_analytics():
    try:
        return jsonify(get_analytics_data())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/credit-status')
def api_credit_status():
    """Returns credit/balance info and dashboard links for all services"""
    
    credits = {
        "dataforseo": {
            "name": "DataForSEO",
            "has_api": False,
            "link": "https://app.dataforseo.com/billing/balance",
            "message": "Check dashboard for balance",
            "status": "unknown",
            "icon": "💰"
        },
        "gemini": {
            "name": "Google Gemini",
            "has_api": False,
            "link": "https://console.cloud.google.com/apis/credentials",
            "message": "Check Google Cloud Console → Billing",
            "status": "unknown",
            "icon": "🤖"
        },
        "anthropic": {
            "name": "Anthropic (Claude)",
            "has_api": False,
            "link": "https://console.anthropic.com/settings/billing",
            "message": "Check dashboard for credits",
            "status": "unknown",
            "icon": "🧠"
        },
        "resend": {
            "name": "Resend (Email)",
            "has_api": False,
            "link": "https://resend.com/billing",
            "message": "Check dashboard for email credits",
            "status": "unknown",
            "icon": "📧"
        },
        "serper": {
            "name": "Serper.dev",
            "has_api": False,
            "link": "https://serper.dev/usage",
            "message": "Check dashboard for API credits",
            "status": "unknown",
            "icon": "🔍"
        },
        "supabase": {
            "name": "Supabase",
            "has_api": False,
            "link": "https://supabase.com/dashboard/project/_/settings/billing",
            "message": "Check dashboard for usage",
            "status": "unknown",
            "icon": "🗄️"
        },
        "railway": {
            "name": "Railway",
            "has_api": False,
            "link": "https://railway.app/account/billing",
            "message": "Check dashboard for credits",
            "status": "unknown",
            "icon": "🚂"
        },
        "lovable": {
            "name": "Lovable (Frontend)",
            "has_api": False,
            "link": "https://lovable.dev/settings/billing",
            "message": "Check dashboard for subscription",
            "status": "unknown",
            "icon": "💜"
        }
    }
    
    import requests
    
    # DataForSEO
    try:
        resp = requests.post(
            "https://api.dataforseo.com/v3/serp/google/jobs/task_post",
            auth=(os.environ.get("DATAFORSEO_LOGIN"), os.environ.get("DATAFORSEO_PASSWORD")),
            json=[{"keyword": "test", "location_name": "United Arab Emirates"}],
            timeout=10
        )
        if resp.status_code == 200:
            credits["dataforseo"]["status"] = "healthy"
        elif resp.status_code == 402:
            credits["dataforseo"]["status"] = "error"
            credits["dataforseo"]["message"] = "⚠️ Payment Required - Check balance"
        else:
            credits["dataforseo"]["status"] = "degraded"
    except:
        credits["dataforseo"]["status"] = "error"
    
    # Gemini
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        try:
            resp = requests.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={gemini_key}", timeout=10)
            if resp.status_code == 200:
                credits["gemini"]["status"] = "healthy"
            elif resp.status_code == 403:
                credits["gemini"]["status"] = "error"
                credits["gemini"]["message"] = "Invalid or expired API key"
            else:
                credits["gemini"]["status"] = "degraded"
        except:
            credits["gemini"]["status"] = "error"
    else:
        credits["gemini"]["status"] = "missing"
    
    # Anthropic
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": anthropic_key, "anthropic-version": "2023-06-01"},
                json={"model": "claude-3-haiku-20240307", "max_tokens": 1, "messages": [{"role": "user", "content": "Hi"}]},
                timeout=10
            )
            if resp.status_code == 401:
                credits["anthropic"]["status"] = "error"
                credits["anthropic"]["message"] = "Invalid API key"
            elif resp.status_code == 200 or resp.status_code == 400:
                credits["anthropic"]["status"] = "healthy"
            else:
                credits["anthropic"]["status"] = "degraded"
        except:
            credits["anthropic"]["status"] = "error"
    else:
        credits["anthropic"]["status"] = "missing"
    
    # Resend
    resend_key = os.environ.get("RESEND_API_KEY")
    if resend_key:
        credits["resend"]["status"] = "configured"
    else:
        credits["resend"]["status"] = "missing"
    
    # Serper
    serper_key = os.environ.get("SERPER_API_KEY")
    if serper_key:
        credits["serper"]["status"] = "configured"
    else:
        credits["serper"]["status"] = "missing"
    
    # Supabase
    try:
        supabase.table("users").select("id").limit(1).execute()
        credits["supabase"]["status"] = "healthy"
    except:
        credits["supabase"]["status"] = "error"
    
    # Railway status page
    try:
        resp = requests.get("https://status.railway.app/api/status", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            all_good = all(c.get("status") == "operational" for c in data.get("components", []))
            credits["railway"]["status"] = "healthy" if all_good else "degraded"
            if not all_good:
                down_services = [c.get("name") for c in data.get("components", []) if c.get("status") != "operational"]
                credits["railway"]["message"] = f"Down: {', '.join(down_services)}"
        else:
            credits["railway"]["status"] = "unknown"
    except:
        credits["railway"]["status"] = "unknown"
    
    # Lovable frontend
    try:
        resp = requests.get("https://jobhunter.ae", timeout=5)
        if resp.status_code == 200:
            credits["lovable"]["status"] = "healthy"
        else:
            credits["lovable"]["status"] = "degraded"
    except:
        credits["lovable"]["status"] = "error"
    
    return jsonify(credits)

@app.route('/api/seo-status')
def api_seo_status():
    """Check Google Analytics and SEO metrics"""
    
    import requests
    from bs4 import BeautifulSoup
    
    seo = {
        "google_analytics": {
            "configured": False,
            "tracking_id": None,
            "status": "missing",
            "setup_link": "https://analytics.google.com/",
            "icon": "📊"
        },
        "google_search_console": {
            "configured": False,
            "status": "missing",
            "setup_link": "https://search.google.com/search-console",
            "icon": "🔎"
        },
        "sitemap": {
            "exists": False,
            "url": "https://jobhunter.ae/sitemap.xml",
            "status": "unknown",
            "icon": "🗺️"
        },
        "robots_txt": {
            "exists": False,
            "url": "https://jobhunter.ae/robots.txt",
            "status": "unknown",
            "icon": "🤖"
        },
        "meta_tags": {
            "title": None,
            "description": None,
            "status": "unknown",
            "icon": "📝"
        },
        "performance": {
            "load_time_ms": None,
            "status": "unknown",
            "icon": "⚡"
        }
    }
    
    # Check sitemap
    try:
        resp = requests.get("https://jobhunter.ae/sitemap.xml", timeout=5)
        if resp.status_code == 200:
            seo["sitemap"]["exists"] = True
            seo["sitemap"]["status"] = "healthy"
        else:
            seo["sitemap"]["status"] = "missing"
    except:
        seo["sitemap"]["status"] = "unreachable"
    
    # Check robots.txt
    try:
        resp = requests.get("https://jobhunter.ae/robots.txt", timeout=5)
        if resp.status_code == 200:
            seo["robots_txt"]["exists"] = True
            seo["robots_txt"]["status"] = "healthy"
            if "sitemap" in resp.text.lower():
                seo["robots_txt"]["sitemap_referenced"] = True
        else:
            seo["robots_txt"]["status"] = "missing"
    except:
        seo["robots_txt"]["status"] = "unreachable"
    
    # Check meta tags and performance
    try:
        start_time = datetime.now()
        resp = requests.get("https://jobhunter.ae", timeout=10)
        load_time = (datetime.now() - start_time).total_seconds() * 1000
        
        seo["performance"]["load_time_ms"] = round(load_time, 0)
        if load_time < 1000:
            seo["performance"]["status"] = "excellent"
        elif load_time < 2000:
            seo["performance"]["status"] = "good"
        elif load_time < 4000:
            seo["performance"]["status"] = "fair"
        else:
            seo["performance"]["status"] = "poor"
        
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            title_tag = soup.find('title')
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            seo["meta_tags"]["title"] = title_tag.text.strip() if title_tag else None
            seo["meta_tags"]["description"] = meta_desc.get('content', '').strip() if meta_desc else None
            
            # Check for GA tracking
            ga_present = 'gtag' in resp.text or 'google-analytics' in resp.text or 'G-' in resp.text
            if ga_present:
                seo["google_analytics"]["configured"] = True
                seo["google_analytics"]["status"] = "healthy"
                
                # Try to extract GA ID
                import re
                ga_match = re.search(r'G-[A-Z0-9]+', resp.text)
                if ga_match:
                    seo["google_analytics"]["tracking_id"] = ga_match.group(0)
            
            if seo["meta_tags"]["title"] and seo["meta_tags"]["description"]:
                seo["meta_tags"]["status"] = "healthy"
            elif seo["meta_tags"]["title"]:
                seo["meta_tags"]["status"] = "warning"
            else:
                seo["meta_tags"]["status"] = "error"
    except:
        seo["meta_tags"]["status"] = "unreachable"
    
    return jsonify(seo)

@app.route('/api/logs')
def api_logs():
    try:
        logs = supabase.table("scrape_logs").select("id,started_at,finished_at,status,total_scraped,total_saved,error").order("started_at", desc=True).limit(20).execute().data or []
        return jsonify({"logs": logs})
    except Exception as e:
        return jsonify({"error": str(e), "logs": []})

@app.route('/api/logs/<log_id>')
def api_log_detail(log_id):
    try:
        result = supabase.table("scrape_logs").select("log_text,status,error").eq("id", log_id).execute()
        return jsonify(result.data[0] if result.data else {"error": "Not found"})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/api/run-scraper', methods=['POST'])
def api_run_scraper():
    def do_scrape():
        from scraper_v2 import run_full_scrape
        run_full_scrape()
    threading.Thread(target=do_scrape, daemon=True).start()
    return jsonify({"status": "started"})

@app.route('/api/score-and-email', methods=['POST'])
def api_score_and_email():
    def do_score_email():
        from scraper_v2 import search_and_score_for_user, RunLogger
        from email_service import send_job_matches_email
        try:
            logger = RunLogger("score_and_email")
            users = supabase.table("users").select("*").eq("is_active", True).execute().data or []
            for user in users:
                try:
                    matched = search_and_score_for_user(user, logger=logger)
                    if matched:
                        sent = send_job_matches_email(user["email"], user.get("name"), matched)
                        logger.add(f"  ✉️ {user.get('email')}: {len(matched)} matches — email {'sent' if sent else 'failed'}")
                    else:
                        logger.add(f"  — {user.get('email')}: no 60%+ matches")
                except Exception as ue:
                    logger.add(f"  ❌ {user.get('email')}: {ue}")
            logger.finish(success=True)
        except Exception as e:
            print(f"❌ score_and_email error: {e}")
    threading.Thread(target=do_score_email, daemon=True).start()
    return jsonify({"log": ["Scoring + emailing all active users in the background. Check the Logs tab in 1-2 minutes for results."]})

@app.route('/api/generate-cv', methods=['POST'])
def api_generate_cv():
    from scraper_v2 import generate_cv_cover_letter
    from email_service import send_cv_cover_letter_email
    data = request.json or {}
    try:
        user = supabase.table("users").select("*").eq("id", data.get("user_id")).execute().data
        job = supabase.table("job_pool").select("*").eq("id", data.get("job_id")).execute().data
        if not user or not job:
            return jsonify({"error": "Not found"}), 404
        cover_letter, tailored_cv = generate_cv_cover_letter(user[0], job[0])
        sent = send_cv_cover_letter_email(user[0]["email"], user[0].get("name"), job[0]["title"], job[0]["company"], tailored_cv, cover_letter)
        return jsonify({"success": True, "emailed": sent})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/refresh-matches', methods=['POST'])
def api_refresh_matches():
    from scraper_v2 import refresh_matches_for_user
    data = request.json or {}
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    try:
        update_user_last_active(user_id)
        user = supabase.table("users").select("*").eq("id", user_id).execute().data
        if not user:
            return jsonify({"error": "User not found"}), 404
        result = refresh_matches_for_user(user[0])
        return jsonify({
            "matches": result["matches"],
            "pending_titles": result["pending_titles"]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/add-title', methods=['POST'])
def api_add_title():
    from scraper_v2 import validate_title, normalize_title, search_jobs
    data = request.json or {}
    user_id = data.get("user_id")
    keyword = (data.get("keyword") or "").strip()
    is_signup = data.get("is_signup", False)
    if not user_id or not keyword:
        return jsonify({"error": "user_id and keyword required"}), 400
    if not validate_title(keyword):
        return jsonify({"error": "Invalid title"}), 400
    
    existing = supabase.table("user_titles").select("id").eq("user_id", user_id).execute()
    current_count = len(existing.data or [])
    if current_count >= 5:
        return jsonify({"error": "Maximum 5 job titles allowed"}), 400
    
    if not is_signup:
        urow = supabase.table("users").select("titles_updated_at").eq("id", user_id).execute().data
        if urow and urow[0].get("titles_updated_at"):
            try:
                last = datetime.fromisoformat(str(urow[0]["titles_updated_at"]).replace("Z", "+00:00"))
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                days_since = (datetime.now(timezone.utc) - last).days
                if days_since < 14:
                    days_left = 14 - days_since
                    return jsonify({"error": f"You can update your titles again in {days_left} day(s)."}), 429
            except:
                pass
    
    normalized = normalize_title(keyword)
    title_result = supabase.table("title_pool").select("*").eq("normalized", normalized).execute()
    title_record = title_result.data[0] if title_result.data else supabase.table("title_pool").insert({"keyword": keyword, "normalized": normalized, "request_count": 0}).execute().data[0]
    try:
        supabase.table("user_titles").insert({"user_id": user_id, "title_id": title_record["id"]}).execute()
    except:
        pass
    
    if not is_signup:
        supabase.table("users").update({"titles_updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", user_id).execute()
    
    def bg():
        ud = supabase.table("users").select("gender").eq("id", user_id).execute().data
        search_jobs(keyword, user_gender=ud[0].get("gender") if ud else None)
    threading.Thread(target=bg, daemon=True).start()
    return jsonify({"success": True, "title_id": title_record["id"]})

@app.route('/api/can-edit-titles', methods=['POST'])
def api_can_edit_titles():
    data = request.json or {}
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    try:
        urow = supabase.table("users").select("titles_updated_at").eq("id", user_id).execute().data
        if not urow or not urow[0].get("titles_updated_at"):
            return jsonify({"can_edit": True, "days_left": 0})
        last = datetime.fromisoformat(str(urow[0]["titles_updated_at"]).replace("Z", "+00:00"))
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        days_since = (datetime.now(timezone.utc) - last).days
        if days_since >= 14:
            return jsonify({"can_edit": True, "days_left": 0})
        return jsonify({"can_edit": False, "days_left": 14 - days_since})
    except Exception as e:
        return jsonify({"can_edit": True, "days_left": 0})

@app.route('/api/delete-title', methods=['POST'])
def api_delete_title():
    data = request.json or {}
    tid = data.get("id")
    if not tid:
        return jsonify({"ok": False, "error": "id required"}), 400
    try:
        supabase.table("user_titles").delete().eq("title_id", tid).execute()
        supabase.table("title_pool").delete().eq("id", tid).execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/delete-user', methods=['POST'])
def api_delete_user():
    data = request.json or {}
    uid = data.get("id")
    if not uid:
        return jsonify({"ok": False, "error": "id required"}), 400
    try:
        supabase.table("user_job_matches").delete().eq("user_id", uid).execute()
        supabase.table("user_titles").delete().eq("user_id", uid).execute()
        try:
            supabase.table("feedback").delete().eq("user_id", uid).execute()
        except Exception:
            pass
        supabase.table("users").delete().eq("id", uid).execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ============================================================================
# HTML Dashboard Builder
# ============================================================================

def build_dashboard_html():
    try:
        jobs = supabase.table("job_pool").select("*").order("created_at", desc=True).limit(200).execute().data or []
        titles = supabase.table("title_pool").select("*").order("request_count", desc=True).execute().data or []
        users = supabase.table("users").select("id,name,email,gender,cv_text,is_active,created_at,last_active_at").execute().data or []
        try:
            logs = supabase.table("scrape_logs").select("id,started_at,finished_at,status,total_scraped,total_saved,error").order("started_at", desc=True).limit(20).execute().data or []
        except:
            logs = []
        try:
            feedback = supabase.table("feedback").select("id,rating,comment,user_id,created_at").order("created_at", desc=True).limit(100).execute().data or []
            fb_user_ids = [f["user_id"] for f in feedback if f.get("user_id")]
            email_map = {}
            if fb_user_ids:
                fb_users = supabase.table("users").select("id,email").in_("id", fb_user_ids).execute().data or []
                email_map = {u["id"]: u["email"] for u in fb_users}
            for f in feedback:
                f["email"] = email_map.get(f.get("user_id"), "anonymous")
        except Exception as e:
            print(f"❌ Feedback load error: {e}")
            feedback = []
        today = datetime.now(timezone.utc).date().isoformat()
    except Exception as e:
        return "<h1>DB Error: " + str(e) + "</h1>"
    
    # Build jobs rows
    rows = []
    for i, j in enumerate(jobs, 1):
        score = j.get("score") or 0
        if score >= 80:
            sbg = "#dcfce7;color:#166534"
        elif score >= 60:
            sbg = "#fef9c3;color:#854d0e"
        else:
            sbg = "#fee2e2;color:#991b1b"
        score_html = '<span style="background:' + sbg + ';padding:2px 8px;border-radius:20px;font-size:12px;font-weight:600">' + str(score) + '%</span>' if score else '<span style="color:#94a3b8">&mdash;</span>'
        posted = (j.get("posted_at") or "")[:10] or "&mdash;"
        link = j.get("link") or "#"
        rows.append(f"""<tr>
            <td>{i}</td>
            <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{j.get("title") or ""}</td>
            <td>{j.get("company") or ""}</td>
            <td>{j.get("location") or "UAE"}</td>
            <td style="font-size:12px;color:#64748b">{j.get("platform") or ""}</td>
            <td>{posted}</td>
            <td>{j.get("salary") or "&mdash;"}</td>
            <td>{score_html}</td>
            <td><a href="{link}" target="_blank" style="background:#2563eb;color:white;padding:4px 10px;border-radius:6px;text-decoration:none;font-size:12px">View</a></td>
        </tr>""")
    jobs_html = "".join(rows) or '<tr><td colspan="9" style="text-align:center;padding:32px;color:#94a3b8">No jobs yet</td></tr>'
    
    # Build titles rows
    rows = []
    for i, t in enumerate(titles, 1):
        ls = (t.get("last_scraped") or "")[:16].replace("T", " ")
        ls_date = (t.get("last_scraped") or "")[:10]
        if ls_date == today:
            status = '<span style="background:#dcfce7;color:#166534;padding:2px 8px;border-radius:20px;font-size:12px">Fresh</span>'
        elif ls_date:
            status = '<span style="background:#fef9c3;color:#854d0e;padding:2px 8px;border-radius:20px;font-size:12px">Stale</span>'
        else:
            status = '<span style="background:#f1f5f9;color:#64748b;padding:2px 8px;border-radius:20px;font-size:12px">Never</span>'
        tid = json.dumps(t.get("id"))
        del_btn = f'<button onclick=\'delTitle({tid})\' style="background:#dc2626;color:white;border:none;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:12px">Delete</button>'
        rows.append(f"<tr><td>{i}</td><td>{t.get('keyword') or ''}</td><td>{ls or 'Never'}</td><td>{t.get('request_count') or 0}</td><td>{status}</td><td>{del_btn}</td></tr>")
    titles_html = "".join(rows) or '<tr><td colspan="6" style="text-align:center;padding:32px;color:#94a3b8">No titles yet</td></tr>'
    
    # Build users rows
    rows = []
    for i, u in enumerate(users, 1):
        uid = json.dumps(u.get("id"))
        last_active = (u.get("last_active_at") or "")[:10] or "Never"
        del_btn = f'<button onclick=\'delUser({uid})\' style="background:#dc2626;color:white;border:none;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:12px">Delete</button>'
        rows.append(f"""<tr>
            <td>{i}</td>
            <td>{u.get("name") or "&mdash;"}</td>
            <td>{u.get("email") or ""}</td>
            <td>{u.get("gender") or "&mdash;"}</td>
            <td>{"✓" if u.get("cv_text") else "✗"}</td>
            <td>{(u.get("created_at") or "")[:10]}</td>
            <td>{last_active}</td>
            <td>{"✓" if u.get("is_active") else "✗"}</td>
            <td>{del_btn}</td>
        </tr>""")
    users_html = "".join(rows) or '<tr><td colspan="9" style="text-align:center;padding:32px;color:#94a3b8">No users yet</td></tr>'
    
    # Build logs rows
    rows = []
    for i, l in enumerate(logs, 1):
        s = l.get("status") or ""
        if s == "success":
            bbg = "#dcfce7;color:#166534"
        elif s == "error":
            bbg = "#fee2e2;color:#991b1b"
        else:
            bbg = "#dbeafe;color:#1d4ed8"
        badge = f'<span style="background:{bbg};padding:2px 8px;border-radius:20px;font-size:12px">{s}</span>'
        lid = str(l.get("id") or "")
        started = (l.get("started_at") or "")[:16].replace("T", " ")
        finished = (l.get("finished_at") or "&mdash;")[:16].replace("T", " ")
        view_btn = f'<button onclick=\'showLog("{lid}")\' style="background:#2563eb;color:white;border:none;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:12px">View</button>'
        rows
