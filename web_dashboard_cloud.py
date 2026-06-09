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
    try:
        total_jobs = supabase.table("job_pool").select("id", count="exact").execute().count or 0
        new_jobs_24h = supabase.table("job_pool").select("id", count="exact").gt("created_at", (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()).execute().count or 0
        active_users = supabase.table("users").select("id", count="exact").eq("is_active", True).execute().count or 0
        total_users = supabase.table("users").select("id", count="exact").execute().count or 0
        scrapes_today = supabase.table("title_pool").select("id", count="exact").gte("last_scraped", datetime.now(timezone.utc).date().isoformat()).execute().count or 0
        daily_limit = 200
        
        match_data = supabase.table("user_job_matches").select("score").execute().data or []
        avg_score = round(sum(m.get("score", 0) for m in match_data) / len(match_data)) if match_data else 0
        total_matches = len(match_data)
        high_matches = len([m for m in match_data if m.get("score", 0) >= 80])
        
        cv_uploaded = supabase.table("users").select("id", count="exact").not_.is_("cv_text", "null").execute().count or 0
        cv_rate = round(cv_uploaded / total_users * 100) if total_users > 0 else 0
        
        last_scrape = supabase.table("scrape_logs").select("started_at,status").order("started_at", desc=True).limit(1).execute().data
        last_scrape_status = last_scrape[0] if last_scrape else None
        
        # Jobs over time (last 30 days)
        jobs_over_time = []
        for i in range(29, -1, -1):
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
        
        # Score distribution
        score_ranges = {"0-20": 0, "21-40": 0, "41-60": 0, "61-80": 0, "81-100": 0}
        for m in match_data:
            score = m.get("score", 0)
            if score <= 20: score_ranges["0-20"] += 1
            elif score <= 40: score_ranges["21-40"] += 1
            elif score <= 60: score_ranges["41-60"] += 1
            elif score <= 80: score_ranges["61-80"] += 1
            else: score_ranges["81-100"] += 1
        
        # Users over time
        users_over_time = []
        for i in range(29, -1, -1):
            date = (datetime.now(timezone.utc) - timedelta(days=i)).date().isoformat()
            count = supabase.table("users").select("id", count="exact").gte("created_at", date).lt("created_at", (datetime.fromisoformat(date) + timedelta(days=1)).isoformat()).execute().count or 0
            users_over_time.append({"date": date, "count": count})
        
        # Gender distribution
        genders = supabase.table("users").select("gender").execute().data or []
        gender_counts = {"male": 0, "female": 0, "prefer_not_to_say": 0, "not_specified": 0}
        for u in genders:
            g = u.get("gender")
            if g == "male": gender_counts["male"] += 1
            elif g == "female": gender_counts["female"] += 1
            elif g == "prefer_not_to_say": gender_counts["prefer_not_to_say"] += 1
            else: gender_counts["not_specified"] += 1
        
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
    except Exception as e:
        print(f"Analytics error: {e}")
        return {"error": str(e)}

def get_system_health():
    """Check status of all external services"""
    import requests
    health = {}
    
    # Supabase
    try:
        supabase.table("users").select("id").limit(1).execute()
        health["supabase"] = {"status": "healthy", "message": "Connected", "icon": "🟢"}
    except Exception as e:
        health["supabase"] = {"status": "error", "message": str(e)[:50], "icon": "🔴"}
    
    # DataForSEO
    try:
        resp = requests.post(
            "https://api.dataforseo.com/v3/serp/google/jobs/task_post",
            auth=(os.environ.get("DATAFORSEO_LOGIN"), os.environ.get("DATAFORSEO_PASSWORD")),
            json=[{"keyword": "test", "location_name": "United Arab Emirates"}],
            timeout=10
        )
        if resp.status_code == 200:
            health["dataforseo"] = {"status": "healthy", "message": "API ready", "icon": "🟢"}
        elif resp.status_code == 402:
            health["dataforseo"] = {"status": "warning", "message": "Check balance", "icon": "🟡"}
        else:
            health["dataforseo"] = {"status": "degraded", "message": f"HTTP {resp.status_code}", "icon": "🟡"}
    except Exception as e:
        health["dataforseo"] = {"status": "error", "message": str(e)[:50], "icon": "🔴"}
    
    # Gemini
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        try:
            resp = requests.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={gemini_key}", timeout=10)
            if resp.status_code == 200:
                health["gemini"] = {"status": "healthy", "message": "API ready", "icon": "🟢"}
            else:
                health["gemini"] = {"status": "error", "message": "Invalid key", "icon": "🔴"}
        except:
            health["gemini"] = {"status": "error", "message": "Connection failed", "icon": "🔴"}
    else:
        health["gemini"] = {"status": "missing", "message": "API key not set", "icon": "⚫"}
    
    # Resend
    if os.environ.get("RESEND_API_KEY"):
        health["resend"] = {"status": "healthy", "message": "Email ready", "icon": "🟢"}
    else:
        health["resend"] = {"status": "missing", "message": "API key not set", "icon": "⚫"}
    
    # Railway
    try:
        resp = requests.get("https://status.railway.app/api/status", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            all_good = all(c.get("status") == "operational" for c in data.get("components", []))
            health["railway"] = {"status": "healthy" if all_good else "degraded", "message": "Operational" if all_good else "Some issues", "icon": "🟢" if all_good else "🟡"}
        else:
            health["railway"] = {"status": "unknown", "message": "Status page unreachable", "icon": "⚫"}
    except:
        health["railway"] = {"status": "unknown", "message": "Cannot reach status page", "icon": "⚫"}
    
    # Lovable frontend
    try:
        resp = requests.get("https://jobhunter.ae", timeout=5)
        if resp.status_code == 200:
            health["lovable"] = {"status": "healthy", "message": "Frontend online", "icon": "🟢"}
        else:
            health["lovable"] = {"status": "degraded", "message": f"HTTP {resp.status_code}", "icon": "🟡"}
    except:
        health["lovable"] = {"status": "error", "message": "Cannot reach frontend", "icon": "🔴"}
    
    return health

def get_credit_status():
    """Get credit/balance info with dashboard links"""
    credits = {
        "dataforseo": {
            "name": "DataForSEO",
            "link": "https://app.dataforseo.com/billing/balance",
            "message": "Check dashboard for balance",
            "icon": "💰"
        },
        "gemini": {
            "name": "Google Gemini",
            "link": "https://console.cloud.google.com/apis/credentials",
            "message": "Check Google Cloud Console",
            "icon": "🤖"
        },
        "anthropic": {
            "name": "Anthropic Claude",
            "link": "https://console.anthropic.com/settings/billing",
            "message": "Check dashboard for credits",
            "icon": "🧠"
        },
        "resend": {
            "name": "Resend Email",
            "link": "https://resend.com/billing",
            "message": "Check email credits",
            "icon": "📧"
        },
        "supabase": {
            "name": "Supabase",
            "link": "https://supabase.com/dashboard/project/_/settings/billing",
            "message": "Check usage",
            "icon": "🗄️"
        },
        "railway": {
            "name": "Railway",
            "link": "https://railway.app/account/billing",
            "message": "Check credits",
            "icon": "🚂"
        }
    }
    return credits

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

@app.route('/api/system-health')
def api_system_health():
    try:
        return jsonify(get_system_health())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/credit-status')
def api_credit_status():
    try:
        return jsonify(get_credit_status())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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

@app.route('/api/old-jobs')
def api_old_jobs():
    try:
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        result = supabase.table("old_jobs").select("*").order("moved_at", desc=True).limit(limit).offset(offset).execute()
        jobs = result.data or []
        return jsonify({"jobs": jobs, "total": len(jobs)})
    except Exception as e:
        return jsonify({"error": str(e), "jobs": []})

@app.route('/api/restore-job', methods=['POST'])
def api_restore_job():
    data = request.json or {}
    job_id = data.get("job_id")
    if not job_id:
        return jsonify({"error": "job_id required"}), 400
    try:
        old = supabase.table("old_jobs").select("*").eq("id", job_id).execute().data
        if not old:
            return jsonify({"success": False, "message": "Job not found"})
        job = old[0]
        job.pop("moved_at", None)
        job.pop("original_id", None)
        job.pop("age_days_at_move", None)
        supabase.table("job_pool").insert(job).execute()
        supabase.table("old_jobs").delete().eq("id", job_id).execute()
        return jsonify({"success": True, "message": "Job restored"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

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
            print(f"Feedback load error: {e}")
            feedback = []
        today = datetime.now(timezone.utc).date().isoformat()
    except Exception as e:
        return f"<h1>DB Error: {str(e)}</h1>"
    
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
        score_html = f'<span style="background:{sbg};padding:2px 8px;border-radius:20px;font-size:12px;font-weight:600">{score}%</span>' if score else '<span style="color:#94a3b8">&mdash;</span>'
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
        rows.append(f"<tr><td>{i}</td><td>{started}</td><td>{finished}</td><td>{badge}</td><td>{l.get('total_scraped') or 0}</td><td>{l.get('total_saved') or 0}</td><td>{view_btn}</td></tr>")
    logs_html = "".join(rows) or '<tr><td colspan="7" style="text-align:center;padding:32px;color:#94a3b8">No logs yet</td></tr>'
    
    # Build feedback rows
    rows = []
    for i, f in enumerate(feedback, 1):
        rating = f.get("rating") or 0
        stars = "★" * int(rating) + "☆" * (5 - int(rating)) if rating else "—"
        when = (f.get("created_at") or "")[:16].replace("T", " ")
        comment = (f.get("comment") or "").replace("<", "&lt;").replace(">", "&gt;") or "—"
        rows.append(f"<tr><td>{i}</td><td style=\"white-space:nowrap\">{when}</td><td style=\"color:#f59e0b\">{stars}</td><td>{comment}</td><td style=\"font-size:12px;color:#64748b\">{f.get('email') or 'anonymous'}</td></tr>")
    feedback_html = "".join(rows) or '<tr><td colspan="5" style="text-align:center;padding:32px;color:#94a3b8">No feedback yet</td></tr>'
    
    scraped_today = len([t for t in titles if (t.get("last_scraped") or "")[:10] == today])
    
    page = f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>JobHunter Admin Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f1f5f9;color:#1e293b}}
.hdr{{background:linear-gradient(135deg,#1e40af,#3b82f6);color:white;padding:20px 32px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap}}
.hdr h1{{font-size:22px;font-weight:700}}
.wrap{{max-width:1400px;margin:0 auto;padding:24px 16px}}
.stats-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px;margin-bottom:24px}}
.stat-card{{background:white;border-radius:12px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.08);transition:transform 0.2s}}
.stat-card:hover{{transform:translateY(-2px)}}
.stat-card .value{{font-size:32px;font-weight:700;color:#1e40af}}
.stat-card .label{{font-size:13px;color:#64748b;margin-top:4px}}
.stat-card .trend{{font-size:11px;margin-top:8px;color:#22c55e}}
.card{{background:white;border-radius:12px;padding:24px;box-shadow:0 1px 3px rgba(0,0,0,.08);margin-bottom:20px}}
.tabs{{display:flex;gap:4px;margin-bottom:20px;border-bottom:2px solid #e2e8f0;flex-wrap:wrap}}
.tab{{padding:10px 20px;cursor:pointer;font-size:14px;font-weight:500;color:#64748b;border-bottom:2px solid transparent;margin-bottom:-2px;transition:all 0.2s}}
.tab:hover{{color:#2563eb}}
.tab.on{{color:#2563eb;border-bottom-color:#2563eb}}
.pane{{display:none}}
.pane.on{{display:block}}
table{{width:100%;border-collapse:collapse}}
th{{text-align:left;font-size:12px;font-weight:600;color:#64748b;text-transform:uppercase;padding:8px 12px;border-bottom:2px solid #f1f5f9}}
td{{padding:10px 12px;border-bottom:1px solid #f8fafc;font-size:14px}}
tr:hover td{{background:#f8fafc}}
.log-box{{background:#0f172a;color:#94a3b8;border-radius:8px;padding:16px;font-family:monospace;font-size:12px;max-height:400px;overflow-y:auto;margin-top:12px;white-space:pre-wrap;line-height:1.6}}
.sp{{display:inline-block;width:14px;height:14px;border:2px solid currentColor;border-top-color:transparent;border-radius:50%;animation:spin .8s linear infinite;vertical-align:middle;margin-right:6px}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
input,select{{padding:8px 12px;border:1px solid #e2e8f0;border-radius:8px;font-size:14px}}
#msg{{margin-top:16px;font-size:14px;color:#64748b}}
.chart-container{{max-width:100%;margin-bottom:20px}}
.chart-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(350px,1fr));gap:24px}}
.health-item{{display:flex;justify-content:space-between;align-items:center;padding:12px;background:#f8fafc;border-radius:8px;margin-bottom:8px}}
.credit-item{{display:flex;justify-content:space-between;align-items:center;padding:12px;background:#f8fafc;border-radius:8px;margin-bottom:8px}}
.credit-link{{color:#2563eb;text-decoration:none;font-size:13px}}
.credit-link:hover{{text-decoration:underline}}
.status-dot{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:8px}}
.refresh-btn{{background:#f1f5f9;color:#64748b;padding:6px 12px;border:none;border-radius:8px;cursor:pointer;font-size:13px}}
.refresh-btn:hover{{background:#e2e8f0}}
</style></head>
<body>
<div class="hdr">
  <div><h1>🎯 JobHunter Admin</h1><small style="opacity:.8;font-size:13px">Professional Dashboard</small></div>
  <div style="text-align:right;font-size:13px;opacity:.9">{len(jobs)} jobs · {len(titles)} titles · {len(users)} users</div>
</div>
<div class="wrap">
  <div class="tabs">
    <div class="tab on" onclick="showTab('overview',this)">📊 Overview</div>
    <div class="tab" onclick="showTab('jobs',this)">💼 Job Pool</div>
    <div class="tab" onclick="showTab('titles',this)">🔍 Titles</div>
    <div class="tab" onclick="showTab('users',this)">👥 Users</div>
    <div class="tab" onclick="showTab('scraper',this)">⚙️ Run Scraper</div>
    <div class="tab" onclick="showTab('logs',this)">📝 Logs</div>
    <div class="tab" onclick="showTab('feedback',this)">💬 Feedback</div>
    <div class="tab" onclick="showTab('oldjobs',this)">📦 Old Jobs</div>
    <div class="tab" onclick="showTab('analytics',this)">📈 Analytics</div>
    <div class="tab" onclick="showTab('health',this)">🩺 System Health</div>
    <div class="tab" onclick="showTab('credits',this)">💰 Credits</div>
  </div>
  
  <!-- ==================== OVERVIEW TAB ==================== -->
  <div id="overview" class="pane on">
    <div class="stats-grid" id="overview-stats">Loading...</div>
  </div>
  
  <!-- ==================== JOB POOL TAB ==================== -->
  <div id="jobs" class="pane card">
    <div style="display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap">
      <input id="qs" placeholder="Search jobs..." oninput="filterJobs()" style="flex:1;min-width:200px">
      <select id="qp" onchange="filterJobs()"><option value="">All Platforms</option><option>LinkedIn</option><option>Indeed</option><option>Bayt.com</option><option>Naukrigulf</option><option>GulfTalent.com</option></select>
    </div>
    <div style="overflow-x:auto">
      <table id="jt"><thead><tr><th>#</th><th>Title</th><th>Company</th><th>Location</th><th>Platform</th><th>Posted</th><th>Salary</th><th>Score</th><th></th></tr></thead>
      <tbody>{jobs_html}</tbody></table>
    </div>
  </div>
  
  <!-- ==================== TITLES TAB ==================== -->
  <div id="titles" class="pane card">
    <div style="overflow-x:auto">
      <table><tr><thead><tr><th>#</th><th>Keyword</th><th>Last Scraped</th><th>Requests</th><th>Status</th><th></th></tr></thead>
      <tbody>{titles_html}</tbody></table>
    </div>
  </div>
  
  <!-- ==================== USERS TAB ==================== -->
  <div id="users" class="pane card">
    <div style="overflow-x:auto">
      <table><tr><thead><tr><th>#</th><th>Name</th><th>Email</th><th>Gender</th><th>CV</th><th>Joined</th><th>Last Active</th><th>Active</th><th></th></tr></thead>
      <tbody>{users_html}</tbody></table>
    </div>
  </div>
  
  <!-- ==================== SCRAPER TAB ==================== -->
  <div id="scraper" class="pane card">
    <h2 style="margin-bottom:16px">Run Scraper</h2>
    <p style="color:#64748b;font-size:14px;margin-bottom:20px">Scrapes all active titles. Respects 24h cache. Daily ceiling: 200 scrapes.</p>
    <div style="display:flex;gap:12px;flex-wrap:wrap">
      <button id="sb" onclick="runScraper()" style="background:#2563eb;color:white;padding:10px 20px;border:none;border-radius:8px;cursor:pointer;font-size:14px;font-weight:600">▶ Run Scraper Now</button>
      <button id="eb" onclick="runEmail()" style="background:#059669;color:white;padding:10px 20px;border:none;border-radius:8px;cursor:pointer;font-size:14px;font-weight:600">✉️ Score + Email Users</button>
    </div>
    <div id="msg"></div>
  </div>
  
  <!-- ==================== LOGS TAB ==================== -->
  <div id="logs" class="pane card">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <h2 style="margin:0">Scrape Logs</h2>
      <button onclick="loadLogs()" class="refresh-btn">🔄 Refresh</button>
    </div>
    <div style="overflow-x:auto">
      <table><tr><thead><tr><th>#</th><th>Started</th><th>Finished</th><th>Status</th><th>Scraped</th><th>Saved</th><th></th></tr></thead>
      <tbody id="lb">{logs_html}</tbody></table>
    </div>
    <div id="ld" style="display:none;margin-top:16px">
      <div style="display:flex;justify-content:space-between;margin-bottom:8px">
        <strong>📄 Log Detail</strong>
        <button onclick="document.getElementById('ld').style.display='none'" class="refresh-btn">Close</button>
      </div>
      <div id="lc" class="log-box">Loading...</div>
    </div>
  </div>
  
  <!-- ==================== FEEDBACK TAB ==================== -->
  <div id="feedback" class="pane card">
    <h2 style="margin-bottom:16px">User Feedback</h2>
    <div style="overflow-x:auto">
      <table><tr><thead><tr><th>#</th><th>Date</th><th>Rating</th><th>Comment</th><th>From</th></tr></thead>
      <tbody>{feedback_html}</tbody></table>
    </div>
  </div>
  
  <!-- ==================== OLD JOBS TAB ==================== -->
  <div id="oldjobs" class="pane card">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <h2 style="margin:0">📦 Archived Jobs (&gt;30 days old)</h2>
      <button onclick="loadOldJobs()" class="refresh-btn">🔄 Refresh</button>
    </div>
    <div style="margin-bottom:16px;padding:12px;background:#fef3c7;border-radius:8px;color:#92400e">
      ⚠️ Jobs older than 30 days are automatically moved here. They no longer appear in user matches but can be restored if needed.
    </div>
    <div style="overflow-x:auto">
      <table style="width:100%">
        <thead><tr><th>Title</th><th>Company</th><th>Location</th><th>Age at move</th><th>Moved on</th><th>Action</th></tr></thead>
        <tbody id="old-jobs-body"><tr><td colspan="6" style="text-align:center">Loading...</td></tr></tbody>
      </table>
    </div>
  </div>
  
  <!-- ==================== ANALYTICS TAB ==================== -->
  <div id="analytics" class="pane card">
    <h2 style="margin-bottom:20px">📈 Analytics Dashboard</h2>
    <div class="chart-grid">
      <div class="chart-container"><canvas id="jobsChart"></canvas><p style="text-align:center;margin-top:8px;font-size:12px;color:#64748b">Jobs Over Time (30 days)</p></div>
      <div class="chart-container"><canvas id="industryChart"></canvas><p style="text-align:center;margin-top:8px;font-size:12px;color:#64748b">Industry Distribution</p></div>
      <div class="chart-container"><canvas id="scoreChart"></canvas><p style="text-align:center;margin-top:8px;font-size:12px;color:#64748b">Match Score Distribution</p></div>
      <div class="chart-container"><canvas id="usersChart"></canvas><p style="text-align:center;margin-top:8px;font-size:12px;color:#64748b">User Growth (30 days)</p></div>
      <div class="chart-container"><canvas id="genderChart"></canvas><p style="text-align:center;margin-top:8px;font-size:12px;color:#64748b">Gender Distribution</p></div>
      <div class="chart-container"><canvas id="cvChart"></canvas><p style="text-align:center;margin-top:8px;font-size:12px;color:#64748b">CV Upload Rate</p></div>
    </div>
  </div>
  
  <!-- ==================== SYSTEM HEALTH TAB ==================== -->
  <div id="health" class="pane card">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px">
      <h2 style="margin:0">🩺 System Health</h2>
      <button onclick="loadHealth()" class="refresh-btn">🔄 Check Now</button>
    </div>
    <div id="health-status">Loading...</div>
  </div>
  
  <!-- ==================== CREDITS TAB ==================== -->
  <div id="credits" class="pane card">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px">
      <h2 style="margin:0">💰 Credit & Billing Links</h2>
      <button onclick="loadCredits()" class="refresh-btn">🔄 Refresh</button>
    </div>
    <div id="credits-status">Loading...</div>
  </div>
</div>

<script>
// ==================== TAB SWITCHING ====================
function showTab(tabId, el) {{
  document.querySelectorAll('.pane').forEach(p => p.className = 'pane');
  document.querySelectorAll('.tab').forEach(t => t.className = 'tab');
  document.getElementById(tabId).className = 'pane on';
  el.className = 'tab on';
  
  if(tabId === 'logs') loadLogs();
  if(tabId === 'oldjobs') loadOldJobs();
  if(tabId === 'analytics') loadAnalytics();
  if(tabId === 'health') loadHealth();
  if(tabId === 'credits') loadCredits();
  if(tabId === 'overview') loadOverview();
}}

// ==================== OVERVIEW ====================
function loadOverview() {{
  fetch('/api/analytics')
    .then(r => r.json())
    .then(d => {{
      if(d.error) {{
        document.getElementById('overview-stats').innerHTML = `<div class="stat-card"><div class="value">Error</div><div class="label">${{d.error}}</div></div>`;
        return;
      }}
      var o = d.overview;
      document.getElementById('overview-stats').innerHTML = `
        <div class="stat-card"><div class="value">${{o.total_jobs}}</div><div class="label">Total Jobs</div></div>
        <div class="stat-card"><div class="value">+${{o.new_jobs_24h}}</div><div class="label">New Jobs (24h)</div><div class="trend">↑ fresh</div></div>
        <div class="stat-card"><div class="value">${{o.active_users}}/${{o.total_users}}</div><div class="label">Active / Total Users</div></div>
        <div class="stat-card"><div class="value">${{o.scrapes_today}}/${{o.daily_limit}}</div><div class="label">Scrapes Today</div><div class="trend">${{o.scrapes_remaining}} remaining</div></div>
        <div class="stat-card"><div class="value">${{o.avg_match_score}}%</div><div class="label">Avg Match Score</div><div class="trend">${{o.high_matches}} high matches</div></div>
        <div class="stat-card"><div class="value">${{o.total_matches}}</div><div class="label">Total Matches</div></div>
        <div class="stat-card"><div class="value">${{o.cv_upload_rate}}%</div><div class="label">CV Upload Rate</div></div>
      `;
    }})
    .catch(e => document.getElementById('overview-stats').innerHTML = `<div class="stat-card"><div class="value">Error</div><div class="label">${{e}}</div></div>`);
}}

// ==================== JOB FILTER ====================
function filterJobs() {{
  var q = document.getElementById('qs').value.toLowerCase();
  var p = document.getElementById('qp').value.toLowerCase();
  document.querySelectorAll('#jt tbody tr').forEach(r => {{
    var t = r.textContent.toLowerCase();
    r.style.display = (!q || t.indexOf(q) > -1) && (!p || t.indexOf(p) > -1) ? '' : 'none';
  }});
}}

// ==================== SCRAPER FUNCTIONS ====================
function setMsg(h) {{
  var e = document.getElementById('msg');
  e.style.display = 'block';
  e.innerHTML = h;
  setTimeout(() => {{ e.style.display = 'none'; }}, 10000);
}}

function runScraper() {{
  var b = document.getElementById('sb');
  b.disabled = true;
  b.innerHTML = '<span class="sp"></span>Starting...';
  setMsg('🔄 Scraper running in background...');
  fetch('/api/run-scraper',{{method:'POST'}})
    .then(r => r.json())
    .then(() => {{ b.disabled = false; b.innerHTML = '▶ Run Scraper Now'; setMsg('✅ Started! Check Logs tab in 30 seconds.'); }})
    .catch(e => {{ b.disabled = false; b.innerHTML = '▶ Run Scraper Now'; setMsg('❌ Error: ' + e); }});
}}

function runEmail() {{
  var b = document.getElementById('eb');
  b.disabled = true;
  b.innerHTML = '<span class="sp"></span>Processing...';
  setMsg('📧 Scoring and emailing...');
  fetch('/api/score-and-email',{{method:'POST'}})
    .then(r => r.json())
    .then(d => {{ b.disabled = false; b.innerHTML = '✉️ Score + Email Users'; var h = ''; for(var i=0;i<d.log.length;i++) h += '<div>' + d.log[i] + '</div>'; setMsg(h); }})
    .catch(e => {{ b.disabled = false; b.innerHTML = '✉️ Score + Email Users'; setMsg('❌ Error: ' + e); }});
}}

// ==================== LOGS ====================
function loadLogs() {{
  fetch('/api/logs').then(r => r.json()).then(d => {{
    var b = document.getElementById('lb');
    if(!d.logs||!d.logs.length){{ b.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:32px;color:#94a3b8">No logs yet</td></tr>'; return; }}
    var h = '';
    for(var i=0;i<d.logs.length;i++){{
      var l = d.logs[i], s = l.status||'', bg = s==='success'?'#dcfce7;color:#166534':s==='error'?'#fee2e2;color:#991b1b':'#dbeafe;color:#1d4ed8';
      h += `<tr><td>${{i+1}}</td><td>${{(l.started_at||'').slice(0,16).replace('T',' ')}}</td><td>${{(l.finished_at||'').slice(0,16).replace('T',' ')}}</td>`;
      h += `<td><span style="background:${{bg}};padding:2px 8px;border-radius:20px;font-size:12px">${{s}}</span></td>`;
      h += `<td>${{l.total_scraped||0}}</td><td>${{l.total_saved||0}}</td>`;
      h += `<td><button class="vlog" data-id="${{l.id}}" style="background:#2563eb;color:white;border:none;padding:4px 10px;border-radius:6px;cursor:pointer">View</button></td></tr>`;
    }}
    b.innerHTML = h;
    document.querySelectorAll('.vlog').forEach(btn => btn.addEventListener('click', function(){{ showLog(this.getAttribute('data-id')); }}));
  }});
}}

function showLog(id) {{
  var d = document.getElementById('ld'), c = document.getElementById('lc');
  d.style.display = 'block'; c.textContent = 'Loading...'; d.scrollIntoView({{behavior:'smooth'}});
  fetch('/api/logs/'+id).then(r => r.json()).then(d => {{ c.textContent = d.log_text||'No content yet'; c.scrollTop = c.scrollHeight; }});
}}

// ==================== OLD JOBS ====================
function loadOldJobs() {{
  fetch('/api/old-jobs?limit=100')
    .then(r => r.json())
    .then(data => {{
      if(data.error){{ document.getElementById('old-jobs-body').innerHTML = `<tr><td colspan="6" style="text-align:center;color:red">Error: ${{data.error}}</td></tr>`; return; }}
      if(!data.jobs || data.jobs.length === 0){{ document.getElementById('old-jobs-body').innerHTML = '<tr><td colspan="6" style="text-align:center">No archived jobs yet</td></tr>'; return; }}
      var html = '';
      for(var i=0;i<data.jobs.length;i++){{
        var j = data.jobs[i];
        html += `<tr><td>${{j.title || 'N/A'}}</td><td>${{j.company || 'N/A'}}</td><td>${{j.location || 'UAE'}}</td><td>${{j.age_days_at_move || '?'}} days</td><td>${{(j.moved_at || '').slice(0,10)}}</td><td><button onclick="restoreJob('${{j.id}}')" style="background:#10b981;color:white;border:none;padding:4px 10px;border-radius:6px;cursor:pointer">Restore</button></td></tr>`;
      }}
      document.getElementById('old-jobs-body').innerHTML = html;
    }});
}}

function restoreJob(jobId) {{
  if(!confirm('Restore this job to active pool?')) return;
  fetch('/api/restore-job',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{job_id:jobId}})}})
    .then(r => r.json())
    .then(data => {{ if(data.success){{ alert('Restored!'); loadOldJobs(); }}else{{ alert('Error: '+data.message); }} }});
}}

// ==================== ANALYTICS ====================
let jobsChart, industryChart, scoreChart, usersChart, genderChart, cvChart;

function loadAnalytics() {{
  fetch('/api/analytics')
    .then(r => r.json())
    .then(d => {{
      if(d.error) return;
      
      if(jobsChart) jobsChart.destroy();
      jobsChart = new Chart(document.getElementById('jobsChart'), {{ type: 'line', data: {{ labels: d.jobs_over_time.map(x => x.date), datasets: [{{ label: 'Jobs Added', data: d.jobs_over_time.map(x => x.count), borderColor: '#2563eb', fill: false }}] }}, options: {{ responsive: true }} }});
      
      if(industryChart) industryChart.destroy();
      industryChart = new Chart(document.getElementById('industryChart'), {{ type: 'pie', data: {{ labels: d.industry_distribution.map(x => x.name), datasets: [{{ data: d.industry_distribution.map(x => x.count), backgroundColor: ['#2563eb','#dc2626','#f59e0b','#10b981','#8b5cf6','#ec489a','#06b6d4','#84cc16','#f97316','#6366f1'] }}] }}, options: {{ responsive: true }} }});
      
      if(scoreChart) scoreChart.destroy();
      scoreChart = new Chart(document.getElementById('scoreChart'), {{ type: 'bar', data: {{ labels: Object.keys(d.score_distribution), datasets: [{{ label: 'Matches', data: Object.values(d.score_distribution), backgroundColor: '#f59e0b' }}] }}, options: {{ responsive: true }} }});
      
      if(usersChart) usersChart.destroy();
      usersChart = new Chart(document.getElementById('usersChart'), {{ type: 'line', data: {{ labels: d.users_over_time.map(x => x.date), datasets: [{{ label: 'Users Added', data: d.users_over_time.map(x => x.count), borderColor: '#10b981', fill: false }}] }}, options: {{ responsive: true }} }});
      
      if(genderChart) genderChart.destroy();
      genderChart = new Chart(document.getElementById('genderChart'), {{ type: 'pie', data: {{ labels: ['Male','Female','Prefer not','Not specified'], datasets: [{{ data: [d.gender_distribution.male, d.gender_distribution.female, d.gender_distribution.prefer_not_to_say, d.gender_distribution.not_specified], backgroundColor: ['#3b82f6','#ec489a','#94a3b8','#cbd5e1'] }}] }}, options: {{ responsive: true }} }});
      
      if(cvChart) cvChart.destroy();
      cvChart = new Chart(document.getElementById('cvChart'), {{ type: 'doughnut', data: {{ labels: ['CV Uploaded','No CV'], datasets: [{{ data: [d.overview.cv_upload_rate, 100 - d.overview.cv_upload_rate], backgroundColor: ['#10b981','#e2e8f0'] }}] }}, options: {{ responsive: true }} }});
    }});
}}

// ==================== SYSTEM HEALTH ====================
function loadHealth() {{
  fetch('/api/system-health')
    .then(r => r.json())
    .then(h => {{
      var html = '';
      for(var service in h) {{
        html += `<div class="health-item"><div><span class="status-dot ${{h[service].status === 'healthy' ? 'green' : (h[service].status === 'warning' ? 'yellow' : 'red')}}"></span><strong>${{service.toUpperCase()}}</strong></div><div><span style="color:${{h[service].status === 'healthy' ? '#22c55e' : (h[service].status === 'warning' ? '#f59e0b' : '#dc2626')}}">${{h[service].icon}} ${{h[service].message}}</span></div></div>`;
      }}
      document.getElementById('health-status').innerHTML = html;
    }});
}}

// ==================== CREDITS ====================
function loadCredits() {{
  fetch('/api/credit-status')
    .then(r => r.json())
    .then(c => {{
      var html = '';
      for(var service in c) {{
        html += `<div class="credit-item"><div><strong>${{c[service].icon}} ${{c[service].name}}</strong></div><div><a href="${{c[service].link}}" target="_blank" class="credit-link">Check Balance →</a><span style="margin-left:12px;font-size:12px;color:#64748b">${{c[service].message}}</span></div></div>`;
      }}
      document.getElementById('credits-status').innerHTML = html;
    }});
}}

// ==================== DELETE FUNCTIONS ====================
function delTitle(id) {{
  if(!confirm('Delete this title? Cannot be undone.')) return;
  fetch('/api/delete-title',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{id:id}})}})
    .then(r => r.json())
    .then(d => {{ if(d.ok){{ location.reload(); }}else{{ alert('Error: '+d.error); }} }});
}}

function delUser(id) {{
  if(!confirm('Delete this user? Cannot be undone.')) return;
  fetch('/api/delete-user',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{id:id}})}})
    .then(r => r.json())
    .then(d => {{ if(d.ok){{ location.reload(); }}else{{ alert('Error: '+d.error); }} }});
}}

// Load initial data
loadOverview();
</script>
<style>
.green{{background:#22c55e; box-shadow:0 0 0 2px #f8fafc,0 0 0 4px #22c55e20;}}
.yellow{{background:#f59e0b; box-shadow:0 0 0 2px #f8fafc,0 0 0 4px #f59e0b20;}}
.red{{background:#dc2626; box-shadow:0 0 0 2px #f8fafc,0 0 0 4px #dc262620;}}
</style>
</body></html>"""
    
    return page

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
