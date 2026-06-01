#!/usr/bin/env python3
"""
JobHunter Web Dashboard — Railway deployment
"""

import os
import threading
from datetime import datetime, timezone
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)

from supabase import create_client
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>JobHunter Admin</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f1f5f9; color: #1e293b; }
        .header { background: linear-gradient(135deg, #1e40af, #3b82f6); color: white; padding: 20px 32px; display: flex; justify-content: space-between; align-items: center; }
        .header h1 { font-size: 22px; font-weight: 700; }
        .container { max-width: 1200px; margin: 0 auto; padding: 24px 16px; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; margin-bottom: 24px; }
        .stat-card { background: white; border-radius: 12px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
        .stat-card .value { font-size: 32px; font-weight: 700; color: #1e40af; }
        .stat-card .label { font-size: 13px; color: #64748b; margin-top: 4px; }
        .card { background: white; border-radius: 12px; padding: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); margin-bottom: 20px; }
        .card h2 { font-size: 16px; font-weight: 600; margin-bottom: 16px; }
        .btn { display: inline-flex; align-items: center; gap: 8px; padding: 10px 20px; border-radius: 8px; border: none; cursor: pointer; font-size: 14px; font-weight: 600; transition: all 0.2s; text-decoration: none; }
        .btn-primary { background: #2563eb; color: white; }
        .btn-primary:hover { background: #1d4ed8; }
        .btn-success { background: #059669; color: white; }
        .btn-sm { padding: 6px 12px; font-size: 13px; }
        .btn-gray { background: #f1f5f9; color: #64748b; }
        table { width: 100%; border-collapse: collapse; }
        th { text-align: left; font-size: 12px; font-weight: 600; color: #64748b; text-transform: uppercase; padding: 8px 12px; border-bottom: 2px solid #f1f5f9; }
        td { padding: 10px 12px; border-bottom: 1px solid #f8fafc; font-size: 14px; }
        tr:hover td { background: #f8fafc; }
        .badge { display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; }
        .badge-high { background: #dcfce7; color: #166534; }
        .badge-mid { background: #fef9c3; color: #854d0e; }
        .badge-low { background: #fee2e2; color: #991b1b; }
        .badge-none { background: #f1f5f9; color: #64748b; }
        .badge-running { background: #dbeafe; color: #1d4ed8; }
        .badge-error { background: #fee2e2; color: #991b1b; }
        .truncate { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .log-box { background: #0f172a; color: #94a3b8; border-radius: 8px; padding: 16px; font-family: monospace; font-size: 12px; max-height: 400px; overflow-y: auto; margin-top: 12px; white-space: pre-wrap; line-height: 1.6; }
        .spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid currentColor; border-top-color: transparent; border-radius: 50%; animation: spin 0.8s linear infinite; vertical-align: middle; margin-right: 6px; }
        @keyframes spin { to { transform: rotate(360deg); } }
        .tabs { display: flex; gap: 4px; margin-bottom: 20px; border-bottom: 2px solid #e2e8f0; }
        .tab { padding: 10px 20px; cursor: pointer; font-size: 14px; font-weight: 500; color: #64748b; border-bottom: 2px solid transparent; margin-bottom: -2px; }
        .tab.active { color: #2563eb; border-bottom-color: #2563eb; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        .filter-row { display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
        .filter-row input, .filter-row select { padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 8px; font-size: 14px; }
        #scraperMsg { margin-top: 16px; font-size: 14px; color: #64748b; display: none; }
    </style>
</head>
<body>
<div class="header">
    <div>
        <h1>JobHunter Admin</h1>
        <small style="opacity:0.8;font-size:13px;">Backend dashboard</small>
    </div>
    <div style="text-align:right;font-size:13px;opacity:0.9;">
        {{ stats.total_jobs }} jobs &middot; {{ stats.total_titles }} titles &middot; {{ stats.total_users }} users
    </div>
</div>

<div class="container">
    <div class="stats-grid">
        <div class="stat-card"><div class="value">{{ stats.total_jobs }}</div><div class="label">Jobs in Pool</div></div>
        <div class="stat-card"><div class="value">{{ stats.total_titles }}</div><div class="label">Active Titles</div></div>
        <div class="stat-card"><div class="value">{{ stats.total_users }}</div><div class="label">Users</div></div>
        <div class="stat-card"><div class="value">{{ stats.scraped_today }}</div><div class="label">Scraped Today</div></div>
        <div class="stat-card"><div class="value">{{ stats.total_logs }}</div><div class="label">Scrape Runs</div></div>
    </div>

    <div class="tabs">
        <div class="tab active" id="tab-btn-jobs" onclick="showTab('jobs')">Job Pool</div>
        <div class="tab" id="tab-btn-titles" onclick="showTab('titles')">Titles</div>
        <div class="tab" id="tab-btn-users" onclick="showTab('users')">Users</div>
        <div class="tab" id="tab-btn-scraper" onclick="showTab('scraper')">Run Scraper</div>
        <div class="tab" id="tab-btn-logs" onclick="showTab('logs')">Logs</div>
    </div>

    <div id="tab-jobs" class="tab-content active">
        <div class="card">
            <div class="filter-row">
                <input type="text" id="jobSearch" placeholder="Search title or company..." oninput="filterJobs()" style="flex:1;min-width:200px">
                <select id="platformFilter" onchange="filterJobs()">
                    <option value="">All Platforms</option>
                    <option>LinkedIn</option>
                    <option>Indeed</option>
                    <option>Bayt.com</option>
                    <option>Naukrigulf</option>
                    <option>GulfTalent.com</option>
                </select>
            </div>
            <table id="jobsTable">
                <thead><tr><th>#</th><th>Title</th><th>Company</th><th>Location</th><th>Platform</th><th>Posted</th><th>Salary</th><th>Score</th><th></th></tr></thead>
                <tbody>
                {% for job in jobs %}
                <tr>
                    <td>{{ loop.index }}</td>
                    <td class="truncate" title="{{ job.title }}">{{ job.title }}</td>
                    <td class="truncate" title="{{ job.company }}">{{ job.company }}</td>
                    <td>{{ job.location or 'UAE' }}</td>
                    <td style="font-size:12px;color:#64748b;">{{ job.platform or '&mdash;' }}</td>
                    <td>{{ job.posted_at[:10] if job.posted_at else '&mdash;' }}</td>
                    <td>{{ job.salary or '&mdash;' }}</td>
                    <td>
                        {% if job.score %}
                            {% if job.score >= 80 %}<span class="badge badge-high">{{ job.score }}%</span>
                            {% elif job.score >= 60 %}<span class="badge badge-mid">{{ job.score }}%</span>
                            {% else %}<span class="badge badge-low">{{ job.score }}%</span>{% endif %}
                        {% else %}<span class="badge badge-none">&mdash;</span>{% endif %}
                    </td>
                    <td><a href="{{ job.link }}" target="_blank" class="btn btn-primary btn-sm">View</a></td>
                </tr>
                {% endfor %}
                {% if not jobs %}
                <tr><td colspan="9" style="text-align:center;padding:32px;color:#94a3b8;">No jobs yet — run the scraper first</td></tr>
                {% endif %}
                </tbody>
            </table>
        </div>
    </div>

    <div id="tab-titles" class="tab-content">
        <div class="card">
            <table>
                <thead><tr><th>#</th><th>Keyword</th><th>Last Scraped</th><th>Requests</th><th>Status</th></tr></thead>
                <tbody>
                {% for t in titles %}
                <tr>
                    <td>{{ loop.index }}</td>
                    <td>{{ t.keyword }}</td>
                    <td>{{ t.last_scraped[:16].replace('T',' ') if t.last_scraped else 'Never' }}</td>
                    <td>{{ t.request_count or 0 }}</td>
                    <td>
                        {% if t.last_scraped and t.last_scraped[:10] == today %}<span class="badge badge-high">Fresh</span>
                        {% elif t.last_scraped %}<span class="badge badge-mid">Stale</span>
                        {% else %}<span class="badge badge-none">Never scraped</span>{% endif %}
                    </td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    <div id="tab-users" class="tab-content">
        <div class="card">
            <table>
                <thead><tr><th>#</th><th>Name</th><th>Email</th><th>Gender</th><th>CV</th><th>Joined</th><th>Active</th></tr></thead>
                <tbody>
                {% for u in users %}
                <tr>
                    <td>{{ loop.index }}</td>
                    <td>{{ u.name or '&mdash;' }}</td>
                    <td>{{ u.email }}</td>
                    <td>{{ u.gender or '&mdash;' }}</td>
                    <td>{{ '&#10003;' if u.cv_text else '&#10007;' }}</td>
                    <td>{{ u.created_at[:10] if u.created_at else '&mdash;' }}</td>
                    <td>{{ '&#10003;' if u.is_active else '&#10007;' }}</td>
                </tr>
                {% endfor %}
                {% if not users %}
                <tr><td colspan="7" style="text-align:center;padding:32px;color:#94a3b8;">No users yet</td></tr>
                {% endif %}
                </tbody>
            </table>
        </div>
    </div>

    <div id="tab-scraper" class="tab-content">
        <div class="card">
            <h2>Run Scraper</h2>
            <p style="color:#64748b;font-size:14px;margin-bottom:20px;">
                Scrapes all active titles. Respects 24h cache. Daily ceiling: 200 scrapes.<br>
                Runs in background — check the Logs tab for progress.
            </p>
            <div style="display:flex;gap:12px;flex-wrap:wrap;">
                <button class="btn btn-primary" id="scrapeBtn" onclick="runScraper()">&#9654; Run Scraper Now</button>
                <button class="btn btn-success" id="scoreBtn" onclick="runScoringEmail()">Score + Email All Users</button>
            </div>
            <div id="scraperMsg"></div>
        </div>
    </div>

    <div id="tab-logs" class="tab-content">
        <div class="card">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
                <h2 style="margin:0">Scrape Run Logs</h2>
                <button class="btn btn-gray btn-sm" onclick="loadLogs()">Refresh</button>
            </div>
            <table id="logsTable">
                <thead><tr><th>#</th><th>Started</th><th>Finished</th><th>Status</th><th>Scraped</th><th>Saved</th><th></th></tr></thead>
                <tbody id="logsBody">
                {% for log in logs %}
                <tr>
                    <td>{{ loop.index }}</td>
                    <td>{{ log.started_at[:16].replace('T',' ') if log.started_at else '&mdash;' }}</td>
                    <td>{{ log.finished_at[:16].replace('T',' ') if log.finished_at else '&mdash;' }}</td>
                    <td>
                        {% if log.status == 'success' %}<span class="badge badge-high">success</span>
                        {% elif log.status == 'error' %}<span class="badge badge-error">error</span>
                        {% elif log.status == 'running' %}<span class="badge badge-running">running</span>
                        {% else %}<span class="badge badge-none">{{ log.status }}</span>{% endif %}
                    </td>
                    <td>{{ log.total_scraped or 0 }}</td>
                    <td>{{ log.total_saved or 0 }}</td>
                    <td><button class="btn btn-primary btn-sm" onclick="showLog('{{ log.id }}')">View</button></td>
                </tr>
                {% endfor %}
                {% if not logs %}
                <tr><td colspan="7" style="text-align:center;padding:32px;color:#94a3b8;">No logs yet</td></tr>
                {% endif %}
                </tbody>
            </table>
        </div>
        <div id="logDetail" style="display:none;" class="card">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                <h2 style="margin:0">Log Detail</h2>
                <button class="btn btn-gray btn-sm" onclick="document.getElementById('logDetail').style.display='none'">Close</button>
            </div>
            <div id="logDetailContent" class="log-box">Loading...</div>
        </div>
    </div>
</div>

<script>
function showTab(name) {
    var names = ['jobs','titles','users','scraper','logs'];
    for (var i = 0; i < names.length; i++) {
        var btn = document.getElementById('tab-btn-' + names[i]);
        var content = document.getElementById('tab-' + names[i]);
        if (btn) btn.className = 'tab' + (names[i] === name ? ' active' : '');
        if (content) content.className = 'tab-content' + (names[i] === name ? ' active' : '');
    }
    if (name === 'logs') loadLogs();
}

function filterJobs() {
    var q = document.getElementById('jobSearch').value.toLowerCase();
    var p = document.getElementById('platformFilter').value.toLowerCase();
    var rows = document.querySelectorAll('#jobsTable tbody tr');
    for (var i = 0; i < rows.length; i++) {
        var text = rows[i].textContent.toLowerCase();
        rows[i].style.display = (!q || text.indexOf(q) > -1) && (!p || text.indexOf(p) > -1) ? '' : 'none';
    }
}

function setMsg(html) {
    var el = document.getElementById('scraperMsg');
    el.style.display = 'block';
    el.innerHTML = html;
}

function runScraper() {
    var btn = document.getElementById('scrapeBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Starting...';
    setMsg('Scraper starting in background — check Logs tab in 30 seconds...');
    fetch('/api/run-scraper', {method: 'POST'})
        .then(function(r) { return r.json(); })
        .then(function(d) {
            btn.disabled = false;
            btn.innerHTML = '&#9654; Run Scraper Now';
            setMsg('Scraper running in background. <a href="#" onclick="showTab(\'logs\');return false;">Check Logs tab</a> for progress.');
        })
        .catch(function(e) {
            btn.disabled = false;
            btn.innerHTML = '&#9654; Run Scraper Now';
            setMsg('Error: ' + e);
        });
}

function runScoringEmail() {
    var btn = document.getElementById('scoreBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Processing...';
    setMsg('Scoring and emailing users...');
    fetch('/api/score-and-email', {method: 'POST'})
        .then(function(r) { return r.json(); })
        .then(function(d) {
            btn.disabled = false;
            btn.innerHTML = 'Score + Email All Users';
            var html = '';
            for (var i = 0; i < d.log.length; i++) html += '<div>' + d.log[i] + '</div>';
            setMsg(html);
        })
        .catch(function(e) {
            btn.disabled = false;
            btn.innerHTML = 'Score + Email All Users';
            setMsg('Error: ' + e);
        });
}

function loadLogs() {
    fetch('/api/logs')
        .then(function(r) { return r.json(); })
        .then(function(d) {
            var tbody = document.getElementById('logsBody');
            if (!d.logs || d.logs.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:32px;color:#94a3b8;">No logs yet</td></tr>';
                return;
            }
            var html = '';
            for (var i = 0; i < d.logs.length; i++) {
                var log = d.logs[i];
                var started = (log.started_at || '').slice(0,16).replace('T',' ');
                var finished = (log.finished_at || '—').slice(0,16).replace('T',' ');
                var badge = '';
                if (log.status === 'success') badge = '<span class="badge badge-high">success</span>';
                else if (log.status === 'error') badge = '<span class="badge badge-error">error</span>';
                else if (log.status === 'running') badge = '<span class="badge badge-running">running</span>';
                else badge = '<span class="badge badge-none">' + (log.status||'') + '</span>';
                html += '<tr>';
                html += '<td>' + (i+1) + '</td>';
                html += '<td>' + started + '</td>';
                html += '<td>' + finished + '</td>';
                html += '<td>' + badge + '</td>';
                html += '<td>' + (log.total_scraped||0) + '</td>';
                html += '<td>' + (log.total_saved||0) + '</td>';
                html += '<td><button class="btn btn-primary btn-sm" onclick="showLog(\'' + log.id + '\')">View</button></td>';
                html += '</tr>';
            }
            tbody.innerHTML = html;
        });
}

function showLog(id) {
    var detail = document.getElementById('logDetail');
    var content = document.getElementById('logDetailContent');
    detail.style.display = 'block';
    content.textContent = 'Loading...';
    detail.scrollIntoView({behavior: 'smooth'});
    fetch('/api/logs/' + id)
        .then(function(r) { return r.json(); })
        .then(function(d) {
            content.textContent = d.log_text || 'No log content yet';
            content.scrollTop = content.scrollHeight;
        });
}
</script>
</body>
</html>"""


def load_dashboard_data():
    try:
        jobs = supabase.table("job_pool").select("*").order("created_at", desc=True).limit(200).execute().data or []
        titles = supabase.table("title_pool").select("*").order("request_count", desc=True).execute().data or []
        users = supabase.table("users").select("id,name,email,gender,cv_text,is_active,created_at").order("created_at", desc=True).execute().data or []
        logs = supabase.table("scrape_logs").select("id,started_at,finished_at,status,total_scraped,total_saved,error").order("started_at", desc=True).limit(20).execute().data or []
        today = datetime.now(timezone.utc).date().isoformat()
        scraped_today = len([t for t in titles if t.get("last_scraped", "")[:10] == today])
        stats = {
            "total_jobs": len(jobs),
            "total_titles": len(titles),
            "total_users": len(users),
            "scraped_today": scraped_today,
            "jobs_with_scores": len([j for j in jobs if j.get("score")]),
            "total_logs": len(logs),
        }
        return jobs, titles, users, logs, stats, today
    except Exception as e:
        print(f"Dashboard load error: {e}")
        import traceback; traceback.print_exc()
        empty_stats = {"total_jobs":0,"total_titles":0,"total_users":0,"scraped_today":0,"jobs_with_scores":0,"total_logs":0}
        return [], [], [], [], empty_stats, ""


@app.route('/')
def dashboard():
    jobs, titles, users, logs, stats, today = load_dashboard_data()
    return render_template_string(HTML_TEMPLATE, jobs=jobs, titles=titles, users=users, logs=logs, stats=stats, today=today)


@app.route('/health')
def health():
    return jsonify({"status": "ok", "time": datetime.now(timezone.utc).isoformat()})


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
        if result.data:
            return jsonify(result.data[0])
        return jsonify({"error": "Not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/run-scraper', methods=['POST'])
def api_run_scraper():
    def do_scrape():
        from scraper_v2 import run_full_scrape
        run_full_scrape()
    threading.Thread(target=do_scrape, daemon=True).start()
    return jsonify({"status": "started"})


@app.route('/api/score-and-email', methods=['POST'])
def api_score_and_email():
    from scraper_v2 import search_and_score_for_user, RunLogger
    from email_service import send_job_matches_email
    log_lines = []
    try:
        logger = RunLogger("score_and_email")
        users = supabase.table("users").select("*").eq("is_active", True).execute().data or []
        if not users:
            logger.add("No active users yet")
            logger.finish(success=True)
            return jsonify({"log": ["No active users yet"]})
        for user in users:
            name = user.get('name') or user.get('email')
            logger.add("Processing " + name)
            matched = search_and_score_for_user(user, logger=logger)
            if matched:
                sent = send_job_matches_email(user["email"], user.get("name"), matched)
                msg = str(len(matched)) + " matches — email " + ("sent" if sent else "failed")
            else:
                msg = "No 60%+ matches found"
            logger.add(msg)
            log_lines.append(msg)
        logger.finish(success=True)
    except Exception as e:
        log_lines.append("Error: " + str(e))
    return jsonify({"log": log_lines})


@app.route('/api/generate-cv', methods=['POST'])
def api_generate_cv():
    from scraper_v2 import generate_cv_cover_letter
    from email_service import send_cv_cover_letter_email
    data = request.json or {}
    user_id = data.get("user_id")
    job_id = data.get("job_id")
    if not user_id or not job_id:
        return jsonify({"error": "user_id and job_id required"}), 400
    try:
        user = supabase.table("users").select("*").eq("id", user_id).execute().data
        job = supabase.table("job_pool").select("*").eq("id", job_id).execute().data
        if not user or not job:
            return jsonify({"error": "Not found"}), 404
        user, job = user[0], job[0]
        cover_letter, tailored_cv = generate_cv_cover_letter(user, job)
        if not cover_letter and not tailored_cv:
            return jsonify({"error": "Generation failed"}), 500
        sent = send_cv_cover_letter_email(
            user["email"], user.get("name"),
            job["title"], job["company"],
            tailored_cv, cover_letter
        )
        return jsonify({"success": True, "emailed": sent})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/add-title', methods=['POST'])
def api_add_title():
    from scraper_v2 import validate_title, normalize_title, search_jobs
    data = request.json or {}
    user_id = data.get("user_id")
    keyword = (data.get("keyword") or "").strip()
    if not user_id or not keyword:
        return jsonify({"error": "user_id and keyword required"}), 400
    if not validate_title(keyword):
        return jsonify({"error": "Invalid title"}), 400
    existing = supabase.table("user_titles").select("id").eq("user_id", user_id).execute()
    if len(existing.data or []) >= 5:
        return jsonify({"error": "Maximum 5 job titles allowed"}), 400
    normalized = normalize_title(keyword)
    title_result = supabase.table("title_pool").select("*").eq("normalized", normalized).execute()
    if title_result.data:
        title_record = title_result.data[0]
    else:
        title_record = supabase.table("title_pool").insert({
            "keyword": keyword, "normalized": normalized, "request_count": 0
        }).execute().data[0]
    try:
        supabase.table("user_titles").insert({
            "user_id": user_id, "title_id": title_record["id"]
        }).execute()
    except:
        pass
    def background_scrape():
        user_data = supabase.table("users").select("gender").eq("id", user_id).execute().data
        gender = user_data[0].get("gender") if user_data else None
        search_jobs(keyword, user_gender=gender)
    threading.Thread(target=background_scrape, daemon=True).start()
    return jsonify({"success": True, "title_id": title_record["id"]})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
