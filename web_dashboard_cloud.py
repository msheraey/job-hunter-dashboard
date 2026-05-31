#!/usr/bin/env python3
"""
JobHunter Web Dashboard
Multi-user job matching platform
Deployable to Railway
"""

import os
import threading
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)

scraper_status = {
    "running": False,
    "last_run": None,
    "last_result": None,
    "progress": 0,
    "step": ""
}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>JobHunter AI Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; }
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        .header { background: white; border-radius: 20px; padding: 30px; margin-bottom: 30px; box-shadow: 0 10px 30px rgba(0,0,0,0.1); }
        .header h1 { color: #333; margin-bottom: 10px; }
        .header p { color: #666; }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .stat-card { background: white; border-radius: 15px; padding: 25px; text-align: center; box-shadow: 0 5px 15px rgba(0,0,0,0.1); transition: transform 0.2s; }
        .stat-card:hover { transform: translateY(-5px); }
        .stat-card .number { font-size: 36px; font-weight: bold; color: #667eea; }
        .stat-card .label { color: #666; margin-top: 10px; }
        .filters { background: white; border-radius: 15px; padding: 20px; margin-bottom: 30px; display: flex; gap: 15px; flex-wrap: wrap; align-items: center; }
        .filter-btn { padding: 10px 20px; border: 2px solid #e0e0e0; background: white; border-radius: 10px; cursor: pointer; transition: all 0.2s; }
        .filter-btn.active { background: #667eea; color: white; border-color: #667eea; }
        .filter-btn:hover { border-color: #667eea; }
        .job-table { background: white; border-radius: 20px; overflow: hidden; box-shadow: 0 5px 15px rgba(0,0,0,0.1); }
        table { width: 100%; border-collapse: collapse; }
        th { background: #667eea; color: white; padding: 15px; text-align: left; font-weight: 600; }
        td { padding: 15px; border-bottom: 1px solid #f0f0f0; }
        tr:hover { background: #f8f9ff; }
        .btn { padding: 8px 16px; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; transition: all 0.2s; margin: 0 5px; }
        .btn-primary { background: #667eea; color: white; }
        .btn-primary:hover { background: #5a67d8; }
        .search-bar { display: flex; gap: 10px; margin-bottom: 20px; }
        .search-bar input { flex: 1; padding: 12px; border: 2px solid #e0e0e0; border-radius: 10px; font-size: 16px; }
        .search-bar button { padding: 12px 24px; background: #667eea; color: white; border: none; border-radius: 10px; cursor: pointer; }
        .progress-wrap { display: none; margin-top: 18px; }
        .progress-meta { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
        .progress-step { color: #555; font-size: 14px; flex: 1; }
        .progress-pct { font-weight: 700; color: #667eea; font-size: 16px; min-width: 48px; text-align: right; }
        .progress-track { background: #e8e8f3; border-radius: 12px; height: 14px; overflow: hidden; }
        .progress-fill { height: 100%; width: 0%; border-radius: 12px; background: linear-gradient(90deg, #667eea 0%, #764ba2 100%); transition: width 0.6s cubic-bezier(0.4,0,0.2,1); }
        @media (max-width: 768px) {
            .container { padding: 10px; }
            th, td { padding: 10px; font-size: 12px; }
            .btn { padding: 4px 8px; font-size: 10px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎯 JobHunter AI Dashboard</h1>
            <p>AI-powered job matching • Smart tracking</p>
            <button id="scraperBtn" class="btn btn-primary" onclick="triggerScraper()" style="margin-top: 15px; padding: 12px 30px; font-size: 16px;">🔍 Run Scraper</button>
            <div id="progressWrap" class="progress-wrap">
                <div class="progress-meta">
                    <span id="progressStep" class="progress-step">Starting...</span>
                    <span id="progressPct" class="progress-pct">0%</span>
                </div>
                <div class="progress-track">
                    <div id="progressFill" class="progress-fill"></div>
                </div>
            </div>
        </div>

        <div class="stats">
            <div class="stat-card">
                <div class="number">{{ stats.total }}</div>
                <div class="label">Total Jobs</div>
            </div>
            <div class="stat-card">
                <div class="number">{{ stats.linkedin }}</div>
                <div class="label">LinkedIn</div>
            </div>
            <div class="stat-card">
                <div class="number">{{ stats.indeed }}</div>
                <div class="label">Indeed</div>
            </div>
            <div class="stat-card">
                <div class="number">{{ stats.other }}</div>
                <div class="label">Other Platforms</div>
            </div>
        </div>

        <div class="filters">
            <button class="filter-btn active" onclick="filterJobs('all')">All Jobs</button>
            <button class="filter-btn" onclick="filterJobs('linkedin')">LinkedIn</button>
            <button class="filter-btn" onclick="filterJobs('indeed')">Indeed</button>
            <button class="filter-btn" onclick="filterJobs('bayt')">Bayt</button>
        </div>

        <div class="search-bar">
            <input type="text" id="searchInput" placeholder="Search by job title or company..." onkeyup="searchJobs()">
            <button onclick="searchJobs()">🔍 Search</button>
        </div>

        <div class="job-table">
            <table id="jobTable">
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Job Title</th>
                        <th>Company</th>
                        <th>Location</th>
                        <th>Platform</th>
                        <th>Posted</th>
                        <th>Salary</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody id="jobTableBody">
                    {% for job in jobs %}
                    <tr data-platform="{{ job.platform|lower }}" data-title="{{ job.title|lower }}" data-company="{{ job.company|lower }}">
                        <td>{{ loop.index }}</td>
                        <td><a href="{{ job.link }}" target="_blank" style="color: #667eea; text-decoration: none;">{{ job.title[:60] }}{% if job.title|length > 60 %}...{% endif %}</a></td>
                        <td>{{ job.company[:40] }}</td>
                        <td style="font-size:13px; color:#555;">{{ job.location or 'UAE' }}</td>
                        <td style="font-size:13px;">{{ job.platform }}</td>
                        <td style="color:#888; font-size:13px;">{{ job.posted_at[:10] if job.posted_at else '—' }}</td>
                        <td style="font-size:13px;">{{ job.salary or '—' }}</td>
                        <td>
                            <button class="btn btn-primary" onclick="window.open('{{ job.link }}', '_blank')">View</button>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    <script>
        function filterJobs(type) {
            const rows = document.querySelectorAll('#jobTableBody tr');
            rows.forEach(row => {
                const platform = row.dataset.platform;
                if (type === 'all') row.style.display = '';
                else row.style.display = platform.includes(type) ? '' : 'none';
            });
            document.querySelectorAll('.filter-btn').forEach(btn => btn.classList.remove('active'));
            event.target.classList.add('active');
        }

        function searchJobs() {
            const searchTerm = document.getElementById('searchInput').value.toLowerCase();
            const rows = document.querySelectorAll('#jobTableBody tr');
            rows.forEach(row => {
                const title = row.dataset.title;
                const company = row.dataset.company;
                row.style.display = (title.includes(searchTerm) || company.includes(searchTerm)) ? '' : 'none';
            });
        }

        function setProgress(pct, step) {
            document.getElementById('progressFill').style.width = pct + '%';
            document.getElementById('progressPct').textContent = pct + '%';
            if (step) document.getElementById('progressStep').textContent = step;
        }

        function showProgress(visible) {
            document.getElementById('progressWrap').style.display = visible ? 'block' : 'none';
        }

        function triggerScraper() {
            const btn = document.getElementById('scraperBtn');
            btn.disabled = true;
            btn.textContent = '⏳ Starting...';
            showProgress(true);
            setProgress(0, '🚀 Connecting...');

            fetch('/trigger-scraper', { method: 'POST' })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    btn.textContent = '🔄 Running...';
                    pollScraperStatus();
                } else {
                    btn.disabled = false;
                    btn.textContent = '🔍 Run Scraper';
                    showProgress(false);
                    alert('⚠️ ' + data.error);
                }
            })
            .catch(() => {
                btn.disabled = false;
                btn.textContent = '🔍 Run Scraper';
                showProgress(false);
            });
        }

        function pollScraperStatus() {
            const btn = document.getElementById('scraperBtn');
            const interval = setInterval(() => {
                fetch('/scraper-status')
                .then(r => r.json())
                .then(data => {
                    setProgress(data.progress || 0, data.step || '');
                    if (!data.running) {
                        clearInterval(interval);
                        setProgress(100, data.step || '✅ Done!');
                        btn.textContent = '✅ Done!';
                        setTimeout(() => {
                            btn.disabled = false;
                            btn.textContent = '🔍 Run Scraper';
                            showProgress(false);
                            location.reload();
                        }, 3000);
                    }
                });
            }, 3000);
        }

        fetch('/scraper-status').then(r => r.json()).then(data => {
            if (data.running) {
                const btn = document.getElementById('scraperBtn');
                btn.disabled = true;
                btn.textContent = '🔄 Running...';
                showProgress(true);
                setProgress(data.progress || 0, data.step || '🔄 Running...');
                pollScraperStatus();
            }
        });
    </script>
</body>
</html>
"""

def load_jobs():
    """Load jobs from Supabase"""
    try:
        from scraper_v2 import supabase
        result = supabase.table("job_pool")\
            .select("*")\
            .order("last_scraped", desc=True)\
            .limit(500)\
            .execute()
        return result.data or []
    except Exception as e:
        print(f"Error loading jobs: {e}")
        return []

@app.route('/')
def dashboard():
    jobs = load_jobs()
    stats = {
        'total': len(jobs),
        'linkedin': len([j for j in jobs if 'linkedin' in (j.get('platform') or '').lower()]),
        'indeed': len([j for j in jobs if 'indeed' in (j.get('platform') or '').lower()]),
        'other': len([j for j in jobs if 'linkedin' not in (j.get('platform') or '').lower() and 'indeed' not in (j.get('platform') or '').lower()])
    }
    return render_template_string(HTML_TEMPLATE, jobs=jobs, stats=stats)

@app.route('/trigger-scraper', methods=['POST'])
def trigger_scraper():
    global scraper_status
    if scraper_status["running"]:
        return jsonify({'success': False, 'error': 'Scraper is already running.'})

    def run_scraper_thread():
        global scraper_status
        scraper_status["running"] = True
        scraper_status["progress"] = 0
        scraper_status["step"] = "🚀 Starting..."
        scraper_status["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M")

        try:
            from scraper_v2 import search_jobs
            keywords = [
                "pharmacy manager UAE",
                "area manager UAE",
                "operations manager UAE",
                "retail manager UAE",
                "regional manager UAE",
            ]
            total = len(keywords)
            for i, keyword in enumerate(keywords):
                pct = int((i / total) * 90)
                scraper_status["step"] = f"🔍 Searching: {keyword}"
                scraper_status["progress"] = pct
                search_jobs(keyword)

            scraper_status["last_result"] = "✅ Done"
            scraper_status["progress"] = 100
            scraper_status["step"] = "✅ Done!"
        except Exception as e:
            scraper_status["last_result"] = f"❌ Error: {str(e)}"
            scraper_status["step"] = f"❌ Error: {str(e)[:80]}"
        finally:
            scraper_status["running"] = False

    threading.Thread(target=run_scraper_thread, daemon=True).start()
    return jsonify({'success': True, 'message': 'Scraper started!'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
