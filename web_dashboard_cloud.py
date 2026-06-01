#!/usr/bin/env python3
"""
JobHunter Web Dashboard — Railway deployment
Clean version: Supabase backend, DataForSEO scraping, Resend email, AI scoring
"""

import os
import json
import threading
from datetime import datetime, timezone
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)

# ── Supabase (service role for backend writes) ─────────────────────────────
from supabase import create_client
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── HTML Template ──────────────────────────────────────────────────────────
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>JobHunter Admin Dashboard</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f1f5f9; color: #1e293b; }
        .header { background: linear-gradient(135deg, #1e40af, #3b82f6); color: white; padding: 20px 32px; display: flex; justify-content: space-between; align-items: center; }
        .header h1 { font-size: 22px; font-weight: 700; }
        .header small { opacity: 0.8; font-size: 13px; }
        .container { max-width: 1200px; margin: 0 auto; padding: 24px 16px; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }
        .stat-card { background: white; border-radius: 12px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
        .stat-card .value { font-size: 32px; font-weight: 700; color: #1e40af; }
        .stat-card .label { font-size: 13px; color: #64748b; margin-top: 4px; }
        .card { background: white; border-radius: 12px; padding: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); margin-bottom: 20px; }
        .card h2 { font-size: 16px; font-weight: 600; margin-bottom: 16px; color: #1e293b; }
        .btn { display: inline-flex; align-items: center; gap: 8px; padding: 10px 20px; border-radius: 8px; border: none; cursor: pointer; font-size: 14px; font-weight: 600; transition: all 0.2s; }
        .btn-primary { background: #2563eb; color: white; }
        .btn-primary:hover { background: #1d4ed8; }
        .btn-success { background: #059669; color: white; }
        .btn-success:hover { background: #047857; }
        .btn-sm { padding: 6px 12px; font-size: 13px; }
        table { width: 100%; border-collapse: collapse; }
        th { text-align: left; font-size: 12px; font-weight: 600; color: #64748b; text-transform: uppercase; padding: 8px 12px; border-bottom: 2px solid #f1f5f9; }
        td { padding: 12px; border-bottom: 1px solid #f8fafc; font-size: 14px; }
        tr:hover td { background: #f8fafc; }
        .badge { display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; }
        .badge-high { background: #dcfce7; color: #166534; }
        .badge-mid { background: #fef9c3; color: #854d0e; }
        .badge-low { background: #fee2e2; color: #991b1b; }
        .badge-none { background: #f1f5f9; color: #64748b; }
        .platform { font-size: 12px; color: #64748b; }
        .scrape-log { background: #0f172a; color: #94a3b8; border-radius: 8px; padding: 16px; font-family: monospace; font-size: 13px; max-height: 200px; overflow-y: auto; }
        .scrape-log .line { margin: 2px 0; }
        .scrape-log .ok { color: #4ade80; }
        .scrape-log .err { color: #f87171; }
        .scrape-log .info { color: #60a5fa; }
        .filter-row { display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; align-items: center; }
        .filter-row input, .filter-row select { padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 8px; font-size: 14px; }
        .truncate { max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        #scrapeStatus { display: none; margin-top: 12px; }
        .spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid #fff; border-top-color: transparent; border-radius: 50%; animation: spin 0.8s linear infinite; }
        @keyframes spin { to { transform: rotate(360deg); } }
        .tabs { display: flex; gap: 4px; margin-bottom: 20px; border-bottom: 2px solid #e2e8f0; }
        .tab { padding: 10px 20px; cursor: pointer; font-size: 14px; font-weight: 500; color: #64748b; border-bottom: 2px solid transparent; margin-bottom: -2px; }
        .tab.active { color: #2563eb; border-bottom-color: #2563eb; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
    </style>
</head>
<body>
<div class="header">
    <div>
        <h1>🎯 JobHunter Admin</h1>
        <small>Backend dashboard — not visible to users</small>
    </div>
    <div style="text-align:right">
        <div style="font-size:13px;opacity:0.9">{{ stats.total_jobs }} jobs in pool</div>
        <div style="font-size:12px;opacity:0.7">{{ stats.total_titles }} active titles</div>
    </div>
</div>

<div class="container">

    <!-- Stats -->
    <div class="stats-grid">
        <div class="stat-card">
            <div class="value">{{ stats.total_jobs }}</div>
            <div class="label">Total Jobs in Pool</div>
        </div>
        <div class="stat-card">
            <div class="value">{{ stats.total_titles }}</div>
            <div class="label">Title Pool Size</div>
        </div>
        <div class="stat-card">
            <div class="value">{{ stats.total_users }}</div>
            <div class="label">Registered Users</div>
        </div>
        <div class="stat-card">
            <div class="value">{{ stats.scraped_today }}</div>
            <div class="label">Scraped Today</div>
        </div>
        <div class="stat-card">
            <div class="value">{{ stats.jobs_with_scores }}</div>
            <div class="label">Scored Jobs</div>
        </div>
    </div>

    <!-- Tabs -->
    <div class="tabs">
        <div class="tab active" onclick="showTab('jobs')">Job Pool</div>
        <div class="tab" onclick="showTab('titles')">Title Pool</div>
        <div class="tab" onclick="showTab('users')">Users</div>
        <div class="tab" onclick="showTab('scraper')">Run Scraper</div>
    </div>

    <!-- Jobs Tab -->
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
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Title</th>
                        <th>Company</th>
                        <th>Location</th>
                        <th>Platform</th>
                        <th>Posted</th>
                        <th>Salary</th>
                        <th>Score</th>
                        <th></th>
                    </tr>
                </thead>
                <tbody>
                {% for job in jobs %}
                <tr>
                    <td>{{ loop.index }}</td>
                    <td class="truncate" title="{{ job.title }}">{{ job.title }}</td>
                    <td class="truncate" title="{{ job.company }}">{{ job.company }}</td>
                    <td>{{ job.location or 'UAE' }}</td>
                    <td class="platform">{{ job.platform or '—' }}</td>
                    <td>{{ job.posted_at[:10] if job.posted_at else '—' }}</td>
                    <td>{{ job.salary or '—' }}</td>
                    <td>
                        {% if job.score %}
                            {% if job.score >= 80 %}
                                <span class="badge badge-high">{{ job.score }}%</span>
                            {% elif job.score >= 60 %}
                                <span class="badge badge-mid">{{ job.score }}%</span>
                            {% else %}
                                <span class="badge badge-low">{{ job.score }}%</span>
                            {% endif %}
                        {% else %}
                            <span class="badge badge-none">—</span>
                        {% endif %}
                    </td>
                    <td><a href="{{ job.link }}" target="_blank" class="btn btn-primary btn-sm">View</a></td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    <!-- Titles Tab -->
    <div id="tab-titles" class="tab-content">
        <div class="card">
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Keyword</th>
                        <th>Last Scraped</th>
                        <th>Request Count</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                {% for t in titles %}
                <tr>
                    <td>{{ loop.index }}</td>
                    <td>{{ t.keyword }}</td>
                    <td>{{ t.last_scraped[:16].replace('T',' ') if t.last_scraped else 'Never' }}</td>
                    <td>{{ t.request_count or 0 }}</td>
                    <td>
                        {% if t.last_scraped and t.last_scraped[:10] == today %}
                            <span class="badge badge-high">Fresh</span>
                        {% elif t.last_scraped %}
                            <span class="badge badge-mid">Stale</span>
                        {% else %}
                            <span class="badge badge-none">New</span>
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    <!-- Users Tab -->
    <div id="tab-users" class="tab-content">
        <div class="card">
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Name</th>
                        <th>Email</th>
                        <th>Gender</th>
                        <th>CV</th>
                        <th>Joined</th>
                        <th>Active</th>
                    </tr>
                </thead>
                <tbody>
                {% for u in users %}
                <tr>
                    <td>{{ loop.index }}</td>
                    <td>{{ u.name or '—' }}</td>
                    <td>{{ u.email }}</td>
                    <td>{{ u.gender or '—' }}</td>
                    <td>{{ '✅' if u.cv_text else '❌' }}</td>
                    <td>{{ u.created_at[:10] if u.created_at else '—' }}</td>
                    <td>{{ '✅' if u.is_active else '❌' }}</td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    <!-- Scraper Tab -->
    <div id="tab-scraper" class="tab-content">
        <div class="card">
            <h2>Run Scraper</h2>
            <p style="color:#64748b;font-size:14px;margin-bottom:16px;">
                Scrapes all active titles in the pool. Respects 24h cache — only fetches stale titles.
                Daily ceiling: <strong>200 scrapes</strong>.
            </p>
            <div style="display:flex;gap:12px;flex-wrap:wrap;">
                <button class="btn btn-primary" onclick="runScraper()">
                    ▶ Run Scraper Now
                </button>
                <button class="btn btn-success" onclick="runScoringEmail()">
                    🤖 Score + Email All Users
                </button>
            </div>
            <div id="scrapeStatus" class="scrape-log" style="display:none;margin-top:16px;">
                <div class="line info">Starting...</div>
            </div>
        </div>
    </div>

</div>

<script>
function showTab(name) {
    document.querySelectorAll('.tab').forEach((t,i) => t.classList.toggle('active', ['jobs','titles','users','scraper'][i] === name));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    document.getElementById('tab-' + name).classList.add('active');
}

function filterJobs() {
    const q = document.getElementById('jobSearch').value.toLowerCase();
    const p = document.getElementById('platformFilter').value.toLowerCase();
    const rows = document.querySelectorAll('#jobsTable tbody tr');
    rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        const match = (!q || text.includes(q)) && (!p || text.includes(p));
        row.style.display = match ? '' : 'none';
    });
}

function runScraper() {
    const status = document.getElementById('scrapeStatus');
    status.style.display = 'block';
    status.innerHTML = '<div class="line info"><span class="spinner"></span> Running scraper...</div>';
    fetch('/api/run-scraper', {method: 'POST'})
        .then(r => r.json())
        .then(d => {
            status.innerHTML = d.log.map(l =>
                `<div class="line ${l.startsWith('✅') || l.startsWith('💾') ? 'ok' : l.startsWith('❌') ? 'err' : 'info'}">${l}</div>`
            ).join('') + `<div class="line ok">Done — ${d.total_saved} new jobs saved</div>`;
            setTimeout(() => location.reload(), 2000);
        })
        .catch(e => { status.innerHTML = `<div class="line err">Error: ${e}</div>`; });
}

function runScoringEmail() {
    const status = document.getElementById('scrapeStatus');
    status.style.display = 'block';
    status.innerHTML = '<div class="line info"><span class="spinner"></span> Scoring and emailing all users...</div>';
    fetch('/api/score-and-email', {method: 'POST'})
        .then(r => r.json())
        .then(d => {
            status.innerHTML = d.log.map(l =>
                `<div class="line ${l.includes('✅') ? 'ok' : l.includes('❌') ? 'err' : 'info'}">${l}</div>`
            ).join('');
        })
        .catch(e => { status.innerHTML = `<div class="line err">Error: ${e}</div>`; });
}
</script>
</body>
</html>
"""

# ── Load dashboard data ────────────────────────────────────────────────────
def load_dashboard_data():
    try:
        jobs = supabase.table("job_pool").select("*").order("created_at", desc=True).limit(200).execute().data or []
        titles = supabase.table("title_pool").select("*").order("request_count", desc=True).execute().data or []
        users = supabase.table("users").select("id,name,email,gender,cv_text,is_active,created_at").order("created_at", desc=True).execute().data or []

        today = datetime.now(timezone.utc).date().isoformat()
        scraped_today = len([t for t in titles if t.get("last_scraped", "")[:10] == today])
        jobs_with_scores = len([j for j in jobs if j.get("score")])

        stats = {
            "total_jobs": len(jobs),
            "total_titles": len(titles),
            "total_users": len(users),
            "scraped_today": scraped_today,
            "jobs_with_scores": jobs_with_scores,
        }
        return jobs, titles, users, stats, today
    except Exception as e:
        print(f"Dashboard load error: {e}")
        return [], [], [], {"total_jobs":0,"total_titles":0,"total_users":0,"scraped_today":0,"jobs_with_scores":0}, ""


# ── Routes ─────────────────────────────────────────────────────────────────
@app.route('/')
def dashboard():
    jobs, titles, users, stats, today = load_dashboard_data()
    return render_template_string(HTML_TEMPLATE, jobs=jobs, titles=titles, users=users, stats=stats, today=today)


@app.route('/health')
def health():
    return jsonify({"status": "ok", "time": datetime.now(timezone.utc).isoformat()})


@app.route('/api/run-scraper', methods=['POST'])
def api_run_scraper():
    def do_scrape():
        from scraper_v2 import search_jobs, get_cached_jobs
        titles = supabase.table("title_pool").select("*").execute().data or []
        for t in titles:
            search_jobs(t["keyword"])

    threading.Thread(target=do_scrape, daemon=True).start()
    return jsonify({"log": ["🚀 Scraper started in background — check back in 2 minutes"], "total_saved": 0})

        for t in titles:
            keyword = t["keyword"]
            log.append(f"🔍 {keyword}")
            jobs_before = len(get_cached_jobs(keyword))
            search_jobs(keyword)
            jobs_after = len(get_cached_jobs(keyword))
            new = jobs_after - jobs_before
            total_saved += new
            log.append(f"  ✅ +{new} new jobs" if new else f"  ✅ Cache fresh")

        log.append(f"\n✅ Total new jobs: {total_saved}")
    except Exception as e:
        log.append(f"❌ Error: {str(e)}")

    return jsonify({"log": log, "total_saved": total_saved})


@app.route('/api/score-and-email', methods=['POST'])
def api_score_and_email():
    from scraper_v2 import search_and_score_for_user
    from email_service import send_job_matches_email
    log = []

    try:
        users = supabase.table("users").select("*").eq("is_active", True).execute().data or []
        if not users:
            log.append("ℹ️ No active users")
            return jsonify({"log": log})

        for user in users:
            log.append(f"👤 {user.get('name') or user.get('email')}")
            matched = search_and_score_for_user(user)
            if matched:
                sent = send_job_matches_email(user["email"], user.get("name"), matched)
                log.append(f"  ✅ {len(matched)} matches, email {'sent' if sent else 'failed'}")
            else:
                log.append(f"  ℹ️ No 60%+ matches")

    except Exception as e:
        log.append(f"❌ Error: {str(e)}")

    return jsonify({"log": log})


@app.route('/api/generate-cv', methods=['POST'])
def api_generate_cv():
    """Generate CV + cover letter for a user/job combo and email it"""
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
            return jsonify({"error": "User or job not found"}), 404

        user, job = user[0], job[0]

        cover_letter, tailored_cv = generate_cv_cover_letter(user, job)
        if not cover_letter and not tailored_cv:
            return jsonify({"error": "Generation failed"}), 500

        sent = send_cv_cover_letter_email(
            user["email"],
            user.get("name"),
            job["title"],
            job["company"],
            tailored_cv,
            cover_letter
        )

        return jsonify({"success": True, "emailed": sent})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/add-title', methods=['POST'])
def api_add_title():
    """Add a title for a user — validates, deduplicates, triggers scrape if new"""
    from scraper_v2 import validate_title, normalize_title, search_jobs

    data = request.json or {}
    user_id = data.get("user_id")
    keyword = (data.get("keyword") or "").strip()

    if not user_id or not keyword:
        return jsonify({"error": "user_id and keyword required"}), 400

    if not validate_title(keyword):
        return jsonify({"error": "Invalid job title — must be at least 3 characters and contain letters"}), 400

    # Check user hasn't exceeded 5 titles
    existing = supabase.table("user_titles")\
        .select("id")\
        .eq("user_id", user_id)\
        .execute()
    if len(existing.data or []) >= 5:
        return jsonify({"error": "Maximum 5 job titles allowed"}), 400

    # Get or create title in pool
    normalized = normalize_title(keyword)
    title_result = supabase.table("title_pool")\
        .select("*")\
        .eq("normalized", normalized)\
        .execute()

    if title_result.data:
        title_record = title_result.data[0]
    else:
        title_record = supabase.table("title_pool").insert({
            "keyword": keyword,
            "normalized": normalized,
            "request_count": 0
        }).execute().data[0]

    # Link user to title
    try:
        supabase.table("user_titles").insert({
            "user_id": user_id,
            "title_id": title_record["id"]
        }).execute()
    except:
        pass  # Already exists — fine

    # Trigger scrape in background
    def background_scrape():
        user_data = supabase.table("users").select("gender").eq("id", user_id).execute().data
        gender = user_data[0].get("gender") if user_data else None
        search_jobs(keyword, user_gender=gender)

    threading.Thread(target=background_scrape, daemon=True).start()

    return jsonify({"success": True, "title_id": title_record["id"], "message": "Title added — scraping in background"})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
