"""
api/app.py — Flask application. ALL legacy routes preserved (Lovable frontend
contract unchanged) + new routes: job-status, upload-cv, premium/*, self-test.
"""
import hmac
import time
import threading
import concurrent.futures
from collections import Counter
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timezone

import config
from config import get_supabase
from core.db import safe_select, safe_update, safe_delete, safe_insert
from core.selftest import run_all as selftest_all
from core.logger import RunLogger
from core.jwt_auth import resolve_user_id
from services.scraper import run_full_scrape, search_jobs
from services.matcher import (search_and_score_for_user, refresh_matches_for_user,
                              set_job_status, update_match_notes)
from services.archiver import archive_old_jobs, get_old_jobs
from services.cv_generator import generate_cv_cover_letter
from services.cv_parser import parse_cv
from services.synonyms import expand_title, link_user_title
from services.scraper import get_or_create_title
from services import premium
from utils.filters import validate_title

app = Flask(__name__)
# CORS headers are set in the @after_request hook below — no need for flask-cors here.
# (Keeping the import for potential future use but not initialising it to avoid duplicate headers.)

# Bounded thread pool for all background tasks — prevents unbounded thread spawning under load.
_bg_pool = concurrent.futures.ThreadPoolExecutor(max_workers=20, thread_name_prefix="jh-bg")

# Per-user refresh rate limiter (in-memory): prevents rapid AI-budget burn from repeated calls.
_refresh_ts: dict = {}
_refresh_lock = threading.Lock()
_REFRESH_COOLDOWN_S = 5

@app.after_request
def after_request(resp):
    origin = request.headers.get("Origin")
    if origin in config.ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization,X-Admin-Token"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return resp

def require_admin():
    """Gate admin-trigger routes with a shared secret. Returns an error
    response to short-circuit the route, or None if authorized."""
    if not config.ADMIN_TOKEN:
        return jsonify({"error": "ADMIN_TOKEN not configured on server"}), 503
    provided = request.headers.get("X-Admin-Token", "")
    if not hmac.compare_digest(provided, config.ADMIN_TOKEN):
        return jsonify({"error": "unauthorized"}), 401
    return None

@app.route("/", defaults={"path": ""}, methods=["OPTIONS"])
@app.route("/<path:path>", methods=["OPTIONS"])
def options_handler(path):
    return "", 204

@app.route("/favicon.ico")
def favicon():
    """Serve an inline SVG favicon so browsers stop hitting the catch-all
    OPTIONS route (which returned 405 for GET /favicon.ico)."""
    from flask import Response
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        '<rect width="32" height="32" rx="8" fill="#7C3AED"/>'
        '<text x="16" y="22" text-anchor="middle" font-family="system-ui,sans-serif" '
        'font-size="18" font-weight="700" fill="#fff">J</text></svg>'
    )
    return Response(svg, mimetype="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=86400"})

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
            "id,started_at,finished_at,status,total_scraped,total_saved,error,error_count").order(
            "started_at", desc=True).limit(30).execute().data or []
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)[:200]}), 500

@app.route("/api/error-log")
def api_error_log():
    try:
        limit = min(int(request.args.get("limit", 100)), 500)
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "limit and offset must be integers"}), 400
    try:
        rows = get_supabase().table("error_log").select("*").order(
            "created_at", desc=True).limit(limit).offset(offset).execute().data or []
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)[:200]}), 500

@app.route("/api/breaker-status")
def api_breaker_status():
    from core.retry import CircuitBreaker
    return jsonify(CircuitBreaker.status_all())

@app.route("/api/logs/<log_id>")
def api_log_detail(log_id):
    rows = safe_select("scrape_logs", id=log_id)
    if not rows:
        return jsonify({"error": "not found"}), 404
    return jsonify(rows[0])

@app.route("/api/analytics")
def api_analytics():
    try:
        sb = get_supabase()
        def _c(table, **filters):
            q = sb.table(table).select("id", count="exact")
            for k, v in filters.items():
                q = q.eq(k, v) if not k.startswith("gte_") else q.gte(k[4:], v)
            return q.execute().count or 0

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
            f_users   = ex.submit(lambda: sb.table("users").select("id", count="exact").execute().count or 0)
            f_jobs    = ex.submit(lambda: sb.table("job_pool").select("id", count="exact").execute().count or 0)
            f_matches = ex.submit(lambda: sb.table("user_job_matches").select("id", count="exact").gte("score", 60).execute().count or 0)
            f_titles  = ex.submit(lambda: sb.table("title_pool").select("id", count="exact").execute().count or 0)
            f_applied = ex.submit(lambda: sb.table("user_job_matches").select("id", count="exact").eq("status", "applied").execute().count or 0)
            f_skipped = ex.submit(lambda: sb.table("user_job_matches").select("id", count="exact").eq("status", "skipped").execute().count or 0)
        return jsonify({
            "users": f_users.result(),
            "jobs_in_pool": f_jobs.result(),
            "matches_60plus": f_matches.result(),
            "titles": f_titles.result(),
            "applied_total": f_applied.result(),
            "skipped_total": f_skipped.result(),
        })
    except Exception as e:
        return jsonify({"error": str(e)[:200]}), 500

@app.route("/api/jobs")
def api_jobs():
    try:
        limit = min(int(request.args.get("limit", 50)), 500)
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "limit and offset must be integers"}), 400
    try:
        q = get_supabase().table("job_pool").select("*", count="exact")
        kw = request.args.get("search_keyword")
        if kw:
            q = q.eq("search_keyword", kw)
        r = q.order("posted_at", desc=True).limit(limit).offset(offset).execute()
        return jsonify({"jobs": r.data or [], "total": r.count or 0})
    except Exception as e:
        return jsonify({"error": str(e)[:200]}), 500

@app.route("/api/users")
def api_users():
    err = require_admin()
    if err:
        return err
    try:
        limit = min(int(request.args.get("limit", 50)), 500)
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "limit and offset must be integers"}), 400
    try:
        rows = get_supabase().table("users").select(
            "id,email,name,notify_pref,last_active,cv_text,profile_summary"
        ).order("last_active", desc=True).limit(limit).offset(offset).execute().data or []
        out = [{
            "id": r["id"], "email": r.get("email"), "name": r.get("name"),
            "notify_pref": r.get("notify_pref"), "last_active": r.get("last_active"),
            "has_cv": bool(r.get("cv_text")), "has_profile": bool(r.get("profile_summary")),
        } for r in rows]
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)[:200]}), 500

@app.route("/api/system-health")
def api_system_health():
    return jsonify(selftest_all())

@app.route("/api/check-links", methods=["POST"])
def api_check_links():
    err = require_admin()
    if err:
        return err
    from services.link_checker import check_links
    from core.logger import RunLogger
    logger = RunLogger("check_links")
    result = check_links(log=logger.add)
    logger.finish(success=True)
    return jsonify(result)

@app.route("/api/credit-status")
def api_credit_status():
    from core.selftest import check_dataforseo
    return jsonify({"dataforseo": check_dataforseo()})

@app.route("/api/dataforseo-pingback", methods=["GET", "POST"])
def api_dataforseo_pingback():
    """DataForSEO calls this when an async scrape task finishes. Fetch+save
    happens in the background so DataForSEO gets an instant 200."""
    task_id = request.args.get("id")
    keyword = request.args.get("keyword")
    if not task_id or not keyword:
        return jsonify({"error": "id and keyword required"}), 400
    from services.scraper import handle_pingback
    _bg_pool.submit(handle_pingback, task_id, keyword)
    return jsonify({"ok": True})

# ── Scrape & score triggers ──────────────────────────────────
@app.route("/api/run-scraper", methods=["POST"])
def api_run_scraper():
    err = require_admin()
    if err:
        return err
    def bg():
        logger = RunLogger("manual_scrape")
        try:
            run_full_scrape(logger)
            logger.finish(success=True)
        except Exception as e:
            logger.add(f"❌ Fatal: {e}")
            logger.finish(success=False, error=e)
    _bg_pool.submit(bg)
    return jsonify({"started": True})

def _paginated_users():
    """Fetch all users in 50-row pages to avoid a full-table load into memory."""
    off, batch = 0, 50
    while True:
        page = get_supabase().table("users").select("*").range(off, off + batch - 1).execute().data or []
        yield from page
        if len(page) < batch:
            break
        off += batch

@app.route("/api/score-and-email", methods=["POST"])
def api_score_and_email():
    err = require_admin()
    if err:
        return err
    def bg():
        from services.notifications import notify_daily
        logger = RunLogger("manual_score")
        try:
            for u in _paginated_users():
                logger.add(f"Processing {u.get('email')}")
                matches = search_and_score_for_user(u, logger=logger)
                notify_daily(u, matches, log=logger.add)
            logger.finish(success=True)
        except Exception as e:
            logger.add(f"❌ Fatal: {e}")
            logger.finish(success=False, error=e)
    _bg_pool.submit(bg)
    return jsonify({"started": True})

# ── User-facing: matches, titles, status ─────────────────────
@app.route("/api/refresh-matches", methods=["POST"])
def api_refresh_matches():
    body = request.get_json(silent=True) or {}
    user_id, err = resolve_user_id(body, request)
    if err:
        return err
    with _refresh_lock:
        last = _refresh_ts.get(user_id, 0)
        now = time.time()
        if now - last < _REFRESH_COOLDOWN_S:
            wait = int(_REFRESH_COOLDOWN_S - (now - last))
            return jsonify({"error": f"Please wait {wait}s before refreshing again"}), 429
        _refresh_ts[user_id] = now
    user = _user(user_id)
    if not user:
        return jsonify({"error": "user not found"}), 404
    safe_update("users", {"last_active": datetime.now(timezone.utc).isoformat()}, id=user["id"])
    return jsonify(refresh_matches_for_user(user))

@app.route("/api/job-status", methods=["POST"])
def api_job_status():
    """Update job status. Accepted: new | skipped | applied | interview | offer | rejected."""
    body = request.get_json(silent=True) or {}
    user_id, err = resolve_user_id(body, request)
    if err:
        return err
    ok = set_job_status(user_id, body.get("job_id"), body.get("status"))
    return jsonify({"ok": ok}), (200 if ok else 400)


@app.route("/api/update-match-notes", methods=["POST"])
def api_update_match_notes():
    """Save free-text notes against a job match (recruiter name, follow-up, etc.)."""
    body = request.get_json(silent=True) or {}
    user_id, err = resolve_user_id(body, request)
    if err:
        return err
    ok = update_match_notes(user_id, body.get("job_id"),
                            (body.get("notes") or "")[:2000])
    return jsonify({"ok": ok}), (200 if ok else 400)


@app.route("/api/set-interview-date", methods=["POST"])
def api_set_interview_date():
    """Set or clear the interview date for a job match."""
    from core.db import safe_upsert
    body = request.get_json(silent=True) or {}
    user_id, err = resolve_user_id(body, request)
    if err:
        return err
    job_id = body.get("job_id")
    interview_date = body.get("interview_date")  # ISO string or null
    if not user_id or not job_id:
        return jsonify({"error": "user_id and job_id required"}), 400
    if interview_date is not None and interview_date != "":
        try:
            datetime.fromisoformat(str(interview_date).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return jsonify({"error": "interview_date must be a valid ISO datetime string"}), 400
    ok = safe_upsert("user_job_matches",
                     {"user_id": user_id, "job_id": job_id,
                      "interview_date": interview_date},
                     on_conflict="user_id,job_id", label="interview_date")
    return jsonify({"ok": ok})

@app.route("/api/add-title", methods=["POST"])
def api_add_title():
    body = request.get_json(silent=True) or {}
    user_id, err = resolve_user_id(body, request)
    if err:
        return err
    keyword = (body.get("title") or "").strip()
    if not user_id or not validate_title(keyword):
        return jsonify({"error": "invalid title"}), 400
    title_row, is_new = get_or_create_title(keyword)
    if not title_row:
        return jsonify({"error": "could not create title"}), 500
    link_user_title(user_id, title_row)
    from core.error_log import log_error as _log_error
    def bg():
        try:
            user = _user(user_id) or {}
            search_jobs(keyword, user_gender=user.get("gender"))
            for syn in expand_title(keyword):
                # Enforce 10-title limit — synonyms must not push user over cap
                if len(safe_select("user_titles", user_id=user_id)) >= 10:
                    break
                syn_row, _ = get_or_create_title(syn)
                if syn_row:
                    link_user_title(user_id, syn_row)
                    search_jobs(syn, user_gender=user.get("gender"))
        except Exception as e:
            _log_error("app.add_title", str(e))
    _bg_pool.submit(bg)
    return jsonify({"added": [keyword], "title_id": title_row["id"], "expanding": config.SEMANTIC_EXPAND})

@app.route("/api/get-titles", methods=["POST"])
def api_get_titles():
    """Return the user's tracked titles with metadata and job pool counts."""
    body = request.get_json(silent=True) or {}
    user_id, err = resolve_user_id(body, request)
    if err:
        return err
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
    # Fetch job counts for all keywords in one query instead of N round-trips
    normalized_kws = [t["normalized"] for t in titles if t.get("normalized")]
    try:
        count_rows = get_supabase().table("job_pool").select(
            "search_keyword").in_("search_keyword", normalized_kws).execute().data or []
        kw_counts = Counter(r["search_keyword"] for r in count_rows)
    except Exception:
        kw_counts = {}
    result = [{
        "user_title_id": link_map.get(t["id"]),
        "title_id": t["id"],
        "keyword": t["keyword"],
        "last_scraped": t["last_scraped"],
        "job_count": kw_counts.get(t.get("normalized", ""), 0),
    } for t in titles]
    return jsonify({"titles": result})

@app.route("/api/can-edit-titles", methods=["POST"])
def api_can_edit_titles():
    body = request.get_json(silent=True) or {}
    user_id, err = resolve_user_id(body, request)
    if err:
        return err
    links = safe_select("user_titles", user_id=user_id)
    return jsonify({"can_add": len(links) < 10, "count": len(links), "max": 10})

@app.route("/api/delete-title", methods=["POST"])
def api_delete_title():
    body = request.get_json(silent=True) or {}
    user_id, err = resolve_user_id(body, request)
    if err:
        return err
    # Accept user_title_id (PK of user_titles row) or legacy title_id field
    user_title_id = body.get("user_title_id") or body.get("title_id")
    if not user_id or not user_title_id:
        return jsonify({"error": "user_id and title_id required"}), 400
    # Delete by primary key of user_titles, scoped to user for safety
    ok = safe_delete("user_titles", id=user_title_id, user_id=user_id)
    return jsonify({"ok": ok})

@app.route("/api/delete-user", methods=["POST"])
def api_delete_user():
    body = request.get_json(silent=True) or {}
    uid, err = resolve_user_id(body, request)
    if err:
        return err
    if not uid:
        return jsonify({"error": "user_id required"}), 400
    safe_delete("user_job_matches", user_id=uid)
    safe_delete("user_titles", user_id=uid)
    safe_delete("user_linked_accounts", user_id=uid)
    ok = safe_delete("users", id=uid)
    return jsonify({"ok": ok})

# ── Account links ────────────────────────────────────────────
@app.route("/api/account-links", methods=["POST"])
def api_get_account_links():
    """Return linked-platform status for the user's profile page."""
    body = request.get_json(silent=True) or {}
    user_id, err = resolve_user_id(body, request)
    if err:
        return err
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    from services.account_links import get_links
    return jsonify({"links": get_links(user_id)})

@app.route("/api/set-account-link", methods=["POST"])
def api_set_account_link():
    """Set or clear a platform link (linked / unlinked / expired)."""
    body = request.get_json(silent=True) or {}
    user_id, err = resolve_user_id(body, request)
    if err:
        return err
    site = body.get("site")
    status = body.get("status", "linked")
    if not user_id or not site:
        return jsonify({"error": "user_id and site required"}), 400
    from services.account_links import set_link, SITES, VALID_STATUSES
    if site not in SITES:
        return jsonify({"error": f"site must be one of: {', '.join(SITES)}"}), 400
    if status not in VALID_STATUSES:
        return jsonify({"error": "status must be linked, unlinked, or expired"}), 400
    ok = set_link(user_id, site, status, body.get("meta"))
    return jsonify({"ok": ok}), (200 if ok else 400)

# ── CV: generate + upload ────────────────────────────────────
@app.route("/api/generate-cv", methods=["POST"])
def api_generate_cv():
    import traceback, base64
    from services.cv_generator import generate_cover_letter_docx, generate_cv_docx
    try:
        body = request.get_json(silent=True) or {}
        user_id, err = resolve_user_id(body, request)
        if err:
            return err
        user = _user(user_id)
        jobs = safe_select("job_pool", id=body.get("job_id"))
        if not user:
            return jsonify({"error": "User not found"}), 404
        if not jobs:
            return jsonify({"error": "Job not found"}), 404
        if not user.get("cv_text") and not user.get("profile_summary"):
            return jsonify({"error": "Please add your profile summary or upload your CV first"}), 422

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
        def send_bg():
            try:
                from email_service import send_cv_cover_letter_email
                send_cv_cover_letter_email(
                    user["email"], user.get("name", ""),
                    jobs[0].get("title"), jobs[0].get("company"),
                    cv_plain, cl_plain)
            except Exception:
                pass
        _bg_pool.submit(send_bg)
        return jsonify(result)
    except Exception as e:
        tb = traceback.format_exc()
        print(f"  ❌ generate-cv error: {tb}")
        return jsonify({"error": str(e), "traceback": tb[-800:]}), 500

@app.route("/api/download-cv", methods=["POST"])
def api_download_cv():
    """Direct file download endpoint for the CV DOCX."""
    from flask import send_file
    from services.cv_generator import generate_cv_docx
    import io
    body = request.get_json(silent=True) or {}
    user_id, err = resolve_user_id(body, request)
    if err:
        return err
    user = _user(user_id)
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
    user_id, err = resolve_user_id(body, request)
    if err:
        return err
    user = _user(user_id)
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

_MAX_CV_BYTES = 5 * 1024 * 1024  # 5 MB

@app.route("/api/upload-cv", methods=["POST"])
def api_upload_cv():
    user_id, err = resolve_user_id({"user_id": request.form.get("user_id")}, request)
    if err:
        return err
    f = request.files.get("file")
    if not user_id or not f:
        return jsonify({"error": "user_id and file required"}), 400
    data = f.read(_MAX_CV_BYTES + 1)
    if len(data) > _MAX_CV_BYTES:
        return jsonify({"error": "File too large (max 5 MB)"}), 413
    result = parse_cv(data, f.filename)
    if result["error"]:
        return jsonify({"error": result["error"]}), 422
    if len(result.get("text") or "") < 100:
        return jsonify({"error": "CV parsed but appears empty or unreadable — please check the file format"}), 422
    from core.error_log import log_error as _log_error
    safe_update("users", {"cv_text": result["text"]}, id=user_id)
    # Clear unactioned matches so they get re-scored against the new CV.
    # Guard: only runs after confirming the CV parsed successfully (length check above).
    def _clear_unactioned():
        try:
            rows = get_supabase().table("user_job_matches").select(
                "id").eq("user_id", user_id).eq("status", "new").execute().data or []
            if rows:
                ids = [r["id"] for r in rows]
                get_supabase().table("user_job_matches").delete().in_("id", ids).execute()
        except Exception as e:
            _log_error("app.upload_cv_clear", str(e))
    _bg_pool.submit(_clear_unactioned)
    return jsonify({"ok": True, "name_detected": result["name"],
                    "chars": len(result["text"]), "rescoring": True})

# ── Premium intelligence ─────────────────────────────────────
def _premium_ctx():
    body = request.get_json(silent=True) or {}
    user_id, err = resolve_user_id(body, request)
    if err:
        return None, None, err
    jobs = safe_select("job_pool", id=body.get("job_id"))
    return _user(user_id), (jobs[0] if jobs else None), None

@app.route("/api/premium/ats-score", methods=["POST"])
def api_ats():
    user, job, err = _premium_ctx()
    if err:
        return err
    if not user or not job:
        return jsonify({"error": "user or job not found"}), 404
    return jsonify(premium.ats_score(user, job))

@app.route("/api/premium/salary", methods=["POST"])
def api_salary():
    _, job, err = _premium_ctx()
    if err:
        return err
    if not job:
        return jsonify({"error": "job not found"}), 404
    return jsonify(premium.salary_estimate(job))

@app.route("/api/premium/red-flags", methods=["POST"])
def api_red_flags():
    _, job, err = _premium_ctx()
    if err:
        return err
    if not job:
        return jsonify({"error": "job not found"}), 404
    return jsonify(premium.red_flags(job))

@app.route("/api/premium/interview-prep", methods=["POST"])
def api_interview():
    user, job, err = _premium_ctx()
    if err:
        return err
    if not user or not job:
        return jsonify({"error": "user or job not found"}), 404
    return jsonify(premium.interview_prep(user, job))

@app.route("/api/premium/company-info", methods=["POST"])
def api_company():
    _, job, err = _premium_ctx()
    if err:
        return err
    if not job:
        return jsonify({"error": "job not found"}), 404
    return jsonify(premium.company_info(job))

@app.route("/api/job-summary", methods=["POST"])
def api_job_summary():
    """3-bullet AI summary of a job posting. Cached in job_pool."""
    _, job, err = _premium_ctx()
    if err:
        return err
    if not job:
        return jsonify({"error": "job not found"}), 404
    return jsonify(premium.job_summary(job))

@app.route("/api/skills-gap", methods=["POST"])
def api_skills_gap():
    """Cross-job skills gap analysis for the user."""
    body = request.get_json(silent=True) or {}
    user_id, err = resolve_user_id(body, request)
    if err:
        return err
    user = _user(user_id)
    if not user:
        return jsonify({"error": "user not found"}), 404
    # Collect user's tracked title keywords
    from services.matcher import _user_titles
    titles = _user_titles(user["id"])
    title_keywords = [t["keyword"] for t in titles]
    return jsonify(premium.skills_gap(user["id"], title_keywords))

# ── Application board (Kanban) ────────────────────────────────
@app.route("/api/application-board", methods=["POST"])
def api_application_board():
    """Return all user matches grouped by status for the Kanban board."""
    body = request.get_json(silent=True) or {}
    user_id, err = resolve_user_id(body, request)
    if err:
        return err
    user = _user(user_id)
    if not user:
        return jsonify({"error": "user not found"}), 404
    try:
        rows = get_supabase().table("user_job_matches").select(
            "job_id,score,status,match_reason,quality_score,notes,interview_date"
        ).eq("user_id", user["id"]).gte("score", config.MATCH_THRESHOLD).execute().data or []
    except Exception as e:
        return jsonify({"error": str(e)[:200]}), 500
    if not rows:
        return jsonify({"board": {"new": [], "applied": [], "interview": [],
                                   "offer": [], "rejected": [], "skipped": []}})
    ids = [r["job_id"] for r in rows]
    rmap = {r["job_id"]: r for r in rows}
    try:
        jobs = get_supabase().table("job_pool").select(
            "id,title,company,location,posted_at,link,platform,salary,"
            "salary_min_aed,salary_max_aed,industry,seniority,remote_status,visa_likelihood,link_active"
        ).in_("id", ids).execute().data or []
    except Exception as e:
        return jsonify({"error": str(e)[:200]}), 500
    board = {"new": [], "applied": [], "interview": [],
             "offer": [], "rejected": [], "skipped": []}
    for j in jobs:
        r = rmap.get(j["id"], {})
        j["score"] = r.get("score", 0)
        j["status"] = r.get("status", "new")
        j["match_reason"] = r.get("match_reason")
        j["quality_score"] = r.get("quality_score", 0)
        j["notes"] = r.get("notes")
        j["interview_date"] = r.get("interview_date")
        bucket = j["status"] if j["status"] in board else "new"
        board[bucket].append(j)
    for bucket in board:
        board[bucket].sort(key=lambda x: x.get("score", 0), reverse=True)
    return jsonify({"board": board})

# ── Old jobs ─────────────────────────────────────────────────
@app.route("/api/old-jobs")
def api_old_jobs():
    try:
        limit = min(int(request.args.get("limit", 100)), 500)
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "limit and offset must be integers"}), 400
    return jsonify(get_old_jobs(limit=limit, offset=offset))

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
