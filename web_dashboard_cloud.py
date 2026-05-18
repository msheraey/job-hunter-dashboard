#!/usr/bin/env python3
"""
Job Hunter Web Dashboard - Google Sheets Version
Deployable to Render.com
"""

import os
import json
from datetime import date, datetime
from flask import Flask, render_template_string, request, jsonify, redirect, url_for
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests

import threading
app = Flask(__name__)

# Track scraper state
scraper_status = {"running": False, "last_run": None, "last_result": None, "progress": 0, "step": ""}

# Google Sheets setup
SHEET_ID = os.environ.get('SHEET_ID', 'YOUR_SHEET_ID_HERE')
SHEET_NAME = "Sheet1"

# Telegram
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '8972917892:AAGs_Z6xWc67poi7EfVdJpPoJJb_3hs8sJo')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '8872960522')

def get_creds():
    """Get Google Sheets credentials"""
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    if creds_json:
        creds_dict = json.loads(creds_json)
        return ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)

def get_sheet():
    """Connect to Google Sheets jobs tab"""
    client = gspread.authorize(get_creds())
    return client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

def get_config_sheet():
    """Get or create the Config worksheet for dashboard triggers"""
    client = gspread.authorize(get_creds())
    spreadsheet = client.open_by_key(SHEET_ID)
    try:
        return spreadsheet.worksheet("Config")
    except:
        ws = spreadsheet.add_worksheet("Config", 10, 2)
        ws.update('A1:B1', [['trigger', 'IDLE']])
        return ws

def load_jobs():
    """Load jobs from Google Sheets"""
    try:
        sheet = get_sheet()
        records = sheet.get_all_records()
        jobs = []
        for row in records:
            if row.get('Job Title') and row.get('Company'):
                jobs.append({
                    'title': str(row.get('Job Title', ''))[:200],
                    'company': str(row.get('Company', ''))[:100],
                    'platform': str(row.get('Platform', 'Unknown')),
                    'link': str(row.get('Link', '#')),
                    'salary': str(row.get('Salary', 'TBD')),
                    'score': int(str(row.get('Score', '0')).replace('%', '')) if row.get('Score') else 0,
                    'date': str(row.get('Date', ''))[:10] if row.get('Date') else '',
                    'status': str(row.get('Status', 'New'))
                })
        jobs.sort(key=lambda x: -x['score'])
        return jobs
    except Exception as e:
        print(f"Error loading jobs: {e}")
        return []

def add_job(job_data):
    """Add a new job to Google Sheets"""
    try:
        sheet = get_sheet()
        sheet.append_row([
            job_data.get('date', date.today().strftime('%Y-%m-%d')),
            f"{job_data.get('score', 0)}%",
            job_data.get('company', ''),
            job_data.get('title', ''),
            job_data.get('platform', ''),
            job_data.get('salary', 'TBD'),
            job_data.get('link', ''),
            'New'
        ])
        return True
    except Exception as e:
        print(f"Error adding job: {e}")
        return False

def update_job_status(row_num, status):
    """Update job status (Applied, Interview, Rejected)"""
    try:
        sheet = get_sheet()
        sheet.update_cell(row_num + 2, 8, status)  # Column H is Status
        return True
    except Exception as e:
        print(f"Error updating status: {e}")
        return False

# HTML Template
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Job Hunter AI Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; }
        
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        
        /* Header */
        .header { background: white; border-radius: 20px; padding: 30px; margin-bottom: 30px; box-shadow: 0 10px 30px rgba(0,0,0,0.1); }
        .header h1 { color: #333; margin-bottom: 10px; }
        .header p { color: #666; }
        
        /* Stats */
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .stat-card { background: white; border-radius: 15px; padding: 25px; text-align: center; box-shadow: 0 5px 15px rgba(0,0,0,0.1); transition: transform 0.2s; }
        .stat-card:hover { transform: translateY(-5px); }
        .stat-card .number { font-size: 36px; font-weight: bold; color: #667eea; }
        .stat-card .label { color: #666; margin-top: 10px; }
        
        /* Filters */
        .filters { background: white; border-radius: 15px; padding: 20px; margin-bottom: 30px; display: flex; gap: 15px; flex-wrap: wrap; align-items: center; }
        .filter-btn { padding: 10px 20px; border: 2px solid #e0e0e0; background: white; border-radius: 10px; cursor: pointer; transition: all 0.2s; }
        .filter-btn.active { background: #667eea; color: white; border-color: #667eea; }
        .filter-btn:hover { border-color: #667eea; }
        
        /* Job Table */
        .job-table { background: white; border-radius: 20px; overflow: hidden; box-shadow: 0 5px 15px rgba(0,0,0,0.1); }
        table { width: 100%; border-collapse: collapse; }
        th { background: #667eea; color: white; padding: 15px; text-align: left; font-weight: 600; }
        td { padding: 15px; border-bottom: 1px solid #f0f0f0; }
        tr:hover { background: #f8f9ff; }
        
        .score { font-weight: bold; }
        .score-high { color: #10b981; }
        .score-mid { color: #f59e0b; }
        .score-low { color: #ef4444; }
        
        .status-badge { display: inline-block; padding: 5px 12px; border-radius: 20px; font-size: 12px; font-weight: 600; }
        .status-new { background: #dbeafe; color: #2563eb; }
        .status-applied { background: #d1fae5; color: #059669; }
        .status-interview { background: #fef3c7; color: #d97706; }
        .status-rejected { background: #fee2e2; color: #dc2626; }
        
        .btn { padding: 8px 16px; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; transition: all 0.2s; margin: 0 5px; }
        .btn-primary { background: #667eea; color: white; }
        .btn-primary:hover { background: #5a67d8; transform: translateY(-2px); }
        .btn-success { background: #10b981; color: white; }
        .btn-success:hover { background: #059669; }
        .btn-warning { background: #f59e0b; color: white; }
        .btn-danger { background: #ef4444; color: white; }
        
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); justify-content: center; align-items: center; z-index: 1000; }
        .modal-content { background: white; border-radius: 20px; padding: 30px; max-width: 500px; width: 90%; }
        
        .search-bar { display: flex; gap: 10px; margin-bottom: 20px; }
        .search-bar input { flex: 1; padding: 12px; border: 2px solid #e0e0e0; border-radius: 10px; font-size: 16px; }
        .search-bar button { padding: 12px 24px; background: #667eea; color: white; border: none; border-radius: 10px; cursor: pointer; }
        
        /* Progress Bar */
        .progress-wrap { display: none; margin-top: 18px; }
        .progress-meta { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
        .progress-step { color: #555; font-size: 14px; flex: 1; }
        .progress-pct { font-weight: 700; color: #667eea; font-size: 16px; min-width: 48px; text-align: right; }
        .progress-track { background: #e8e8f3; border-radius: 12px; height: 14px; overflow: hidden; box-shadow: inset 0 2px 4px rgba(0,0,0,0.06); }
        .progress-fill { height: 100%; width: 0%; border-radius: 12px;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            transition: width 0.6s cubic-bezier(0.4,0,0.2,1);
            position: relative; overflow: hidden; }
        .progress-fill::after { content: ''; position: absolute; top: 0; left: -100%;
            width: 60%; height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.35), transparent);
            animation: shimmer 1.6s infinite; }
        @keyframes shimmer { to { left: 200%; } }

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
            <h1>🎯 Job Hunter AI Dashboard</h1>
            <p>AI-powered job matching • Tailored CVs • Smart tracking</p>
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
                <div class="number">{{ stats.high_score }}</div>
                <div class="label">80%+ Matches</div>
            </div>
            <div class="stat-card">
                <div class="number">{{ stats.applied }}</div>
                <div class="label">Applied</div>
            </div>
            <div class="stat-card">
                <div class="number">{{ stats.interview }}</div>
                <div class="label">Interviews</div>
            </div>
        </div>
        
        <div class="filters">
            <button class="filter-btn active" onclick="filterJobs('all')">All Jobs</button>
            <button class="filter-btn" onclick="filterJobs('high')">80%+ Matches</button>
            <button class="filter-btn" onclick="filterJobs('applied')">Applied</button>
            <button class="filter-btn" onclick="filterJobs('new')">New</button>
        </div>
        
        <div class="search-bar">
            <input type="text" id="searchInput" placeholder="Search by job title, company, or platform..." onkeyup="searchJobs()">
            <button onclick="searchJobs()">🔍 Search</button>
        </div>
        
        <div class="job-table">
            <table id="jobTable">
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Score</th>
                        <th>Job Title</th>
                        <th>Company</th>
                        <th>Platform</th>
                        <th>Date Found</th>
                        <th>Status</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody id="jobTableBody">
                    {% for job in jobs %}
                    <tr data-score="{{ job.score }}" data-status="{{ job.status }}" data-title="{{ job.title.lower() }}" data-company="{{ job.company.lower() }}">
                        <td>{{ loop.index }}</td>
                        <td class="score score-{% if job.score >= 80 %}high{% elif job.score >= 60 %}mid{% else %}low{% endif %}">{{ job.score }}%</td>
                        <td><a href="{{ job.link }}" target="_blank" style="color: #667eea; text-decoration: none;">{{ job.title[:60] }}{% if job.title|length > 60 %}...{% endif %}</a></td>
                        <td>{{ job.company[:40] }}</td>
                        <td>{{ job.platform }}</td>
                        <td style="color:#888; font-size:13px; white-space:nowrap;">{{ job.date if job.date else '—' }}</td>
                        <td><span class="status-badge status-{{ job.status.lower() }}">{{ job.status }}</span></td>
                        <td>
                            <button class="btn btn-primary" onclick="viewJob('{{ job.link }}')">View</button>
                            <button class="btn btn-success" onclick="generateCV('{{ loop.index0 }}')">CV</button>
                            <select onchange="updateStatus({{ loop.index0 }}, this.value)" class="btn" style="padding: 6px; margin-left: 5px;">
                                <option value="">Update</option>
                                <option value="Applied">✅ Applied</option>
                                <option value="Interview">📞 Interview</option>
                                <option value="Rejected">❌ Rejected</option>
                            </select>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    
    <div id="cvModal" class="modal">
        <div class="modal-content">
            <h2>📄 Generate CV & Cover Letter</h2>
            <p id="cvJobInfo" style="margin: 20px 0;"></p>
            <p>This uses AI to tailor your CV specifically for this job.</p>
            <div style="display: flex; gap: 10px; justify-content: flex-end; margin-top: 20px;">
                <button onclick="closeModal()" class="btn" style="background: #e0e0e0;">Cancel</button>
                <button onclick="confirmGenerate()" class="btn btn-success">Generate</button>
            </div>
            <div id="cvProgress" style="display: none; margin-top: 20px; text-align: center;">
                ⏳ Generating... Check your Telegram in 30-60 seconds
            </div>
        </div>
    </div>
    
    <script>
        let allJobs = {{ jobs | tojson }};
        let currentJobIndex = -1;
        
        function filterJobs(type) {
            const rows = document.querySelectorAll('#jobTableBody tr');
            rows.forEach(row => {
                const score = parseInt(row.dataset.score);
                const status = row.dataset.status;
                
                if (type === 'all') row.style.display = '';
                else if (type === 'high') row.style.display = score >= 80 ? '' : 'none';
                else if (type === 'applied') row.style.display = status === 'Applied' ? '' : 'none';
                else if (type === 'new') row.style.display = status === 'New' ? '' : 'none';
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
                if (title.includes(searchTerm) || company.includes(searchTerm)) {
                    row.style.display = '';
                } else {
                    row.style.display = 'none';
                }
            });
        }
        
        function viewJob(link) {
            window.open(link, '_blank');
        }
        
        function generateCV(index) {
            currentJobIndex = index;
            const job = allJobs[index];
            document.getElementById('cvJobInfo').innerHTML = `<strong>${job.title}</strong><br>${job.company}`;
            document.getElementById('cvModal').style.display = 'flex';
        }
        
        function closeModal() {
            document.getElementById('cvModal').style.display = 'none';
            document.getElementById('cvProgress').style.display = 'none';
        }
        
        function confirmGenerate() {
            const job = allJobs[currentJobIndex];
            document.getElementById('cvProgress').style.display = 'block';
            
            fetch('/generate-cv', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ job: job })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('✅ CV generation started! Check your Telegram.');
                    closeModal();
                } else {
                    alert('Error: ' + data.error);
                }
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
                    const pct = data.progress || 0;
                    const step = data.step || '';
                    setProgress(pct, step);

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

        // Restore progress bar if scraper is already running on page load
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

        function updateStatus(index, status) {
            if (!status) return;
            const job = allJobs[index];
            
            fetch('/update-status', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ job: job, status: status })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    location.reload();
                }
            });
        }
    </script>
</body>
</html>
"""

@app.route('/')
def dashboard():
    jobs = load_jobs()
    
    stats = {
        'total': len(jobs),
        'high_score': len([j for j in jobs if j['score'] >= 80]),
        'applied': len([j for j in jobs if j['status'] == 'Applied']),
        'interview': len([j for j in jobs if j['status'] == 'Interview'])
    }
    
    return render_template_string(HTML_TEMPLATE, jobs=jobs, stats=stats)

@app.route('/generate-cv', methods=['POST'])
def generate_cv():
    data = request.json
    job = data.get('job', {})
    
    # Here you would call your Telegram bot or CV builder
    # For now, we'll just acknowledge
    return jsonify({'success': True, 'message': 'CV generation started'})

@app.route('/trigger-scraper', methods=['POST'])
def trigger_scraper():
    global scraper_status
    if scraper_status["running"]:
        return jsonify({'success': False, 'error': 'Scraper is already running. Check Telegram for updates.'})

    def run_scraper_thread():
        global scraper_status
        scraper_status["running"] = True
        scraper_status["progress"] = 0
        scraper_status["step"] = "🚀 Starting..."
        scraper_status["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M")

        def progress_callback(step, pct):
            scraper_status["step"] = step
            scraper_status["progress"] = pct

        try:
            from scraper import run as scraper_run
            count = scraper_run(progress_callback=progress_callback)
            scraper_status["last_result"] = f"✅ Found {count} jobs"
            scraper_status["progress"] = 100
            scraper_status["step"] = f"✅ Done! {count} jobs found"
        except Exception as e:
            scraper_status["last_result"] = f"❌ Error: {str(e)}"
            scraper_status["step"] = f"❌ Error: {str(e)[:80]}"
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID,
                      "text": f"❌ Scraper error: {str(e)[:300]}",
                      "parse_mode": "HTML"},
                timeout=10
            )
        finally:
            scraper_status["running"] = False

    thread = threading.Thread(target=run_scraper_thread, daemon=True)
    thread.start()
    return jsonify({'success': True, 'message': 'Scraper started!'})

@app.route('/scraper-status')
def get_scraper_status():
    return jsonify(scraper_status)

@app.route('/update-status', methods=['POST'])
def update_status():
    data = request.json
    job = data.get('job', {})
    status = data.get('status', '')

    try:
        sheet = get_sheet()
        all_values = sheet.get_all_values()
        job_link = job.get('link', '')

        for i, row in enumerate(all_values[1:], start=1):  # skip header row
            if len(row) >= 7 and row[6] == job_link:  # column G (index 6) is Link
                sheet.update_cell(i + 1, 8, status)   # column 8 = Status
                return jsonify({'success': True})

        return jsonify({'success': False, 'error': 'Job not found in sheet'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)