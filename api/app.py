"""
api/app.py — Flask application. ALL legacy routes preserved (Lovable frontend
contract unchanged) + new routes: job-status, upload-cv, premium/*, self-test.
"""
import threading
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timezone

import config
from config import get_supabase
from core.db import safe_select, safe_update, safe_delete, safe_insert
from core.selftest import run_all as selftest_all
from core.logger import RunLogger
from services.scraper import run_full_scrape, search_jobs
from services.matcher import (search_and_score_for_user, refresh_matches_for_user,
                              set_job_status)
from services.archiver import archive_old_jobs, get_old_jobs
from services.cv_generator import generate_cv_cover_letter
from services.cv_parser import parse_cv
from services.synonyms import expand_title, link_user_title
from services.scraper import get_or_create_title
from services import premium
from utils.filters import validate_title

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

@app.after_request
def after_request(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return resp

@app.route("/", defaults={"path": ""}, methods=["OPTIONS"])
@app.route("/<path:path>", methods=["OPTIONS"])
def options_handler(path):
    return "", 204

def _user(user_id):
    rows = safe_select("users", id=user_id)
    return rows[0] if rows else None

# ── Health & admin ───────────────────────────────────────────
@app.route("/health")
def health():
    return jsonify({"status": "ok", "ts": datetime.now(timezone.utc).isoformat()})

@app.route("/api/self-test")
def api_self_test():
    return jsonify(selftest_all())

@app.route("/")
def dashboard():
    from api.dashboard import render_dashboard
    return render_dashboard()

@app.route("/api/logs")
def api_logs():
    try:
        rows = get_supabase().table("scrape_logs").select(
            "id,started_at,finished_at,status,total_scraped,total_saved,error").order(
            "started_at", desc=True).limit(30).execute().data or []
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)[:200]}), 500

@app.route("/api/logs/<log_id>")
def api_log_detail(log_id):
    rows = safe_select("scrape_logs", id=log_id)
    return jsonify(rows[0] if rows else {"error": "not found"})

@app.route("/api/analytics")
def api_analytics():
    try:
        sb = get_supabase()
        users = sb.table("users").select("id", count="exact").execute().count or 0
        jobs = sb.table("job_pool").select("id", count="exact").execute().count or 0
        matches = sb.table("user_job_matches").select("id", count="exact").gte("score", 60).execute().count or 0
        titles = sb.table("title_pool").select("id", count="exact").execute().count or 0
        applied = sb.table("user_job_matches").select("id", count="exact").eq("status", "applied").execute().count or 0
        skipped = sb.table("user_job_matches").select("id", count="exact").eq("status", "skipped").execute().count or 0
        return jsonify({
            "users": users,
            "jobs_in_pool": jobs,
            "matches_60plus": matches,
            "titles": titles,
            "applied_total": applied,
            "skipped_total": skipped,
        })
    except Exception as e:
        return jsonify({"error": str(e)[:200]}), 500

@app.route("/api/system-health")
def api_system_health():
    return jsonify(selftest_all())

@app.route("/api/credit-status")
def api_credit_status():
    from core.selftest import check_dataforseo
    return jsonify({"dataforseo": check_dataforseo()})

# ── Scrape & score triggers ──────────────────────────────────
@app.route("/api/run-scraper", methods=["POST"])
def api_run_scraper():
    def bg():
        logger = RunLogger("manual_scrape")
        try:
            run_full_scrape(logger)
            logger.finish(success=True)
        except Exception as e:
            logger.add(f"❌ Fatal: {e}")
            logger.finish(success=False, error=e)
    threading.Thread(target=bg, daemon=True).start()
    return jsonify({"started": True})

@app.route("/api/score-and-email", methods=["POST"])
def api_score_and_email():
    def bg():
        from services.notifications import notify_daily
        logger = RunLogger("manual_score")
        try:
            users = safe_select("users")
            for u in users:
                logger.add(f"Processing {u.get('email')}")
                matches = search_and_score_for_user(u, logger=logger)
                notify_daily(u, matches, log=logger.add)
            logger.finish(success=True)
        except Exception as e:
            logger.add(f"❌ Fatal: {e}")
            logger.finish(success=False, error=e)
    threading.Thread(target=bg, daemon=True).start()
    return jsonify({"started": True})

# ── User-facing: matches, titles, status ─────────────────────
@app.route("/api/refresh-matches", methods=["POST"])
def api_refresh_matches():
    body = request.get_json(silent=True) or {}
    user = _user(body.get("user_id"))
    if not user:
        return jsonify({"error": "user not found"}), 404
    safe_update("users", {"last_active": datetime.now(timezone.utc).isoformat()}, id=user["id"])
    return jsonify(refresh_matches_for_user(user))

@app.route("/api/job-status", methods=["POST"])
def api_job_status():
    body = request.get_json(silent=True) or {}
    ok = set_job_status(body.get("user_id"), body.get("job_id"), body.get("status"))
    return jsonify({"ok": ok}), (200 if ok else 400)

@app.route("/api/add-title", methods=["POST"])
def api_add_title():
    body = request.get_json(silent=True) or {}
    user_id, keyword = body.get("user_id"), (body.get("title") or "").strip()
    if not user_id or not validate_title(keyword):
        return jsonify({"error": "invalid title"}), 400
    title_row, is_new = get_or_create_title(keyword)
    if not title_row:
        return jsonify({"error": "could not create title"}), 500
    link_user_title(user_id, title_row)
    def bg():
        try:
            user = _user(user_id) or {}
            search_jobs(keyword, user_gender=user.get("gender"))
            for syn in expand_title(keyword):
                syn_row, _ = get_or_create_title(syn)
                if syn_row:
                    link_user_title(user_id, syn_row)
                    search_jobs(syn, user_gender=user.get("gender"))
        except Exception as e:
            print(f"  ❌ add-title bg: {e}")
    threading.Thread(target=bg, daemon=True).start()
    return jsonify({"added": [keyword], "title_id": title_row["id"], "expanding": config.SEMANTIC_EXPAND})

@app.route("/api/get-titles", methods=["POST"])
def api_get_titles():
    """Return the user's tracked titles with metadata and job pool counts."""
    body = request.get_json(silent=True) or {}
    user_id = body.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    links = safe_select("user_titles", user_id=user_id)
    if not links:
        return jsonify({"titles": []})
    title_ids = [l["title_id"] for l in links]
    link_map = {l["title_id"]: l["id"] for l in links}
    try:
        titles = get_supabase().table("title_pool").select(
            "id,keyword,normalized,last_scraped").in_("id", title_ids).execute().data or []
    except Exception as e:
        return jsonify({"error": str(e)[:200]}), 500
    result = []
    for t in titles:
        try:
            count = get_supabase().table("job_pool").select(
                "id", count="exact").eq("search_keyword", t["normalized"]).execute().count or 0
        except Exception:
            count = 0
        result.append({
            "user_title_id": link_map.get(t["id"]),
            "title_id": t["id"],
            "keyword": t["keyword"],
            "last_scraped": t["last_scraped"],
            "job_count": count,
        })
    return jsonify({"titles": result})

@app.route("/api/can-edit-titles", methods=["POST"])
def api_can_edit_titles():
    body = request.get_json(silent=True) or {}
    links = safe_select("user_titles", user_id=body.get("user_id"))
    return jsonify({"can_add": len(links) < 10, "count": len(links), "max": 10})

@app.route("/api/delete-title", methods=["POST"])
def api_delete_title():
    body = request.get_json(silent=True) or {}
    ok = safe_delete("user_titles", user_id=body.get("user_id"), title_id=body.get("title_id"))
    return jsonify({"ok": ok})

@app.route("/api/delete-user", methods=["POST"])
def api_delete_user():
    body = request.get_json(silent=True) or {}
    uid = body.get("user_id")
    if not uid:
        return jsonify({"error": "user_id required"}), 400
    safe_delete("user_job_matches", user_id=uid)
    safe_delete("user_titles", user_id=uid)
    ok = safe_delete("users", id=uid)
    return jsonify({"ok": ok})

# ── CV: generate + upload ────────────────────────────────────
@app.route("/api/generate-cv", methods=["POST"])
def api_generate_cv():
    body = request.get_json(silent=True) or {}
    user = _user(body.get("user_id"))
    jobs = safe_select("job_pool", id=body.get("job_id"))
    if not user:
        return jsonify({"error": "User not found"}), 404
    if not jobs:
        return jsonify({"error": "Job not found"}), 404
    if not user.get("cv_text") and not user.get("profile_summary"):
        return jsonify({"error": "Please add your profile summary or upload your CV first"}), 422

    from services.cv_generator import generate_cover_letter_docx, generate_cv_docx
    import base64

    cl_bytes, cl_file, cl_plain = generate_cover_letter_docx(user, jobs[0])
    cv_bytes, cv_file, cv_plain = generate_cv_docx(user, jobs[0])

    if not cl_bytes and not cv_bytes:
        return jsonify({"error": "Generation failed — all AI providers unavailable, try again"}), 502

    result = {
        "cover_letter": cl_plain,
        "tailored_cv": cv_plain,
        "cover_letter_ok": bool(cl_bytes),
        "tailored_cv_ok": bool(cv_bytes),
        "cl_docx_b64": base64.b64encode(cl_bytes).decode() if cl_bytes else None,
        "cv_docx_b64": base64.b64encode(cv_bytes).decode() if cv_bytes else None,
        "cl_filename": cl_file,
        "cv_filename": cv_file,
        "job_title": jobs[0].get("title", ""),
        "company": jobs[0].get("company", ""),
    }
    # Email in background
    def send_bg():
        try:
            from email_service import send_cv_cover_letter_email
            send_cv_cover_letter_email(
                user["email"], user.get("name", ""),
                jobs[0].get("title"), jobs[0].get("company"),
                cv_plain, cl_plain)
        except Exception as e:
            print(f"  ⚠️ CV email: {e}")
    import threading
    threading.Thread(target=send_bg, daemon=True).start()
    return jsonify(result)

@app.route("/api/download-cv", methods=["POST"])
def api_download_cv():
    """Direct file download endpoint for the CV DOCX."""
    from flask import send_file
    from services.cv_generator import generate_cv_docx
    import io
    body = request.get_json(silent=True) or {}
    user = _user(body.get("user_id"))
    jobs = safe_select("job_pool", id=body.get("job_id"))
    if not user or not jobs:
        return jsonify({"error": "not found"}), 404
    cv_bytes, filename, _ = generate_cv_docx(user, jobs[0])
    if not cv_bytes:
        return jsonify({"error": "generation failed"}), 502
    return send_file(
        io.BytesIO(cv_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=filename or "CV.docx",
    )

@app.route("/api/download-cover-letter", methods=["POST"])
def api_download_cover_letter():
    """Direct file download endpoint for the Cover Letter DOCX."""
    from flask import send_file
    from services.cv_generator import generate_cover_letter_docx
    import io
    body = request.get_json(silent=True) or {}
    user = _user(body.get("user_id"))
    jobs = safe_select("job_pool", id=body.get("job_id"))
    if not user or not jobs:
        return jsonify({"error": "not found"}), 404
    cl_bytes, filename, _ = generate_cover_letter_docx(user, jobs[0])
    if not cl_bytes:
        return jsonify({"error": "generation failed"}), 502
    return send_file(
        io.BytesIO(cl_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=filename or "Cover_Letter.docx",
    )

@app.route("/api/upload-cv", methods=["POST"])
def api_upload_cv():
    user_id = request.form.get("user_id")
    f = request.files.get("file")
    if not user_id or not f:
        return jsonify({"error": "user_id and file required"}), 400
    result = parse_cv(f.read(), f.filename)
    if result["error"]:
        return jsonify({"error": result["error"]}), 422
    safe_update("users", {"cv_text": result["text"]}, id=user_id)
    return jsonify({"ok": True, "name_detected": result["name"], "chars": len(result["text"])})

# ── Premium intelligence ─────────────────────────────────────
def _premium_ctx():
    body = request.get_json(silent=True) or {}
    user = _user(body.get("user_id"))
    jobs = safe_select("job_pool", id=body.get("job_id"))
    return user, (jobs[0] if jobs else None)

@app.route("/api/premium/ats-score", methods=["POST"])
def api_ats():
    user, job = _premium_ctx()
    if not user or not job:
        return jsonify({"error": "user or job not found"}), 404
    return jsonify(premium.ats_score(user, job))

@app.route("/api/premium/salary", methods=["POST"])
def api_salary():
    _, job = _premium_ctx()
    if not job:
        return jsonify({"error": "job not found"}), 404
    return jsonify(premium.salary_estimate(job))

@app.route("/api/premium/red-flags", methods=["POST"])
def api_red_flags():
    _, job = _premium_ctx()
    if not job:
        return jsonify({"error": "job not found"}), 404
    return jsonify(premium.red_flags(job))

@app.route("/api/premium/interview-prep", methods=["POST"])
def api_interview():
    user, job = _premium_ctx()
    if not user or not job:
        return jsonify({"error": "user or job not found"}), 404
    return jsonify(premium.interview_prep(user, job))

@app.route("/api/premium/company-info", methods=["POST"])
def api_company():
    _, job = _premium_ctx()
    if not job:
        return jsonify({"error": "job not found"}), 404
    return jsonify(premium.company_info(job))

# ── Old jobs ─────────────────────────────────────────────────
@app.route("/api/old-jobs")
def api_old_jobs():
    return jsonify(get_old_jobs(limit=int(request.args.get("limit", 100)),
                                offset=int(request.args.get("offset", 0))))

@app.route("/api/restore-job", methods=["POST"])
def api_restore_job():
    body = request.get_json(silent=True) or {}
    rows = safe_select("old_jobs", id=body.get("job_id"))
    if not rows:
        return jsonify({"error": "not found"}), 404
    job = rows[0]
    restore = {k: v for k, v in job.items()
               if k not in ("id", "original_id", "age_days_at_move", "moved_at")}
    new_row = safe_insert("job_pool", restore, label="restore")
    if new_row:
        safe_delete("old_jobs", id=job["id"])
        return jsonify({"ok": True, "new_id": new_row["id"]})
    return jsonify({"error": "restore failed"}), 500
