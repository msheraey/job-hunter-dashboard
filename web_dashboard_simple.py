#!/usr/bin/env python3
"""
Job Hunter Dashboard - Simple Version (No Login)
For personal use only
"""

import os
import json
from datetime import datetime, date
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)

# HTML Template with no login
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mohammed's Job Hunter</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; }
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        .header { background: white; border-radius: 20px; padding: 30px; margin-bottom: 30px; box-shadow: 0 10px 30px rgba(0,0,0,0.1); text-align: center; }
        .header h1 { color: #333; margin-bottom: 10px; }
        .header p { color: #666; }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .stat-card { background: white; border-radius: 15px; padding: 25px; text-align: center; box-shadow: 0 5px 15px rgba(0,0,0,0.1); }
        .stat-card .number { font-size: 36px; font-weight: bold; color: #667eea; }
        .stat-card .label { color: #666; margin-top: 10px; }
        .job-table { background: white; border-radius: 20px; overflow: hidden; box-shadow: 0 5px 15px rgba(0,0,0,0.1); }
        table { width: 100%; border-collapse: collapse; }
        th { background: #667eea; color: white; padding: 15px; text-align: left; }
        td { padding: 15px; border-bottom: 1px solid #f0f0f0; }
        tr:hover { background: #f8f9ff; }
        .score-high { color: #10b981; font-weight: bold; }
        .score-mid { color: #f59e0b; font-weight: bold; }
        .score-low { color: #ef4444; font-weight: bold; }
        .btn { padding: 8px 16px; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; text-decoration: none; display: inline-block; }
        .btn-primary { background: #667eea; color: white; }
        .btn-success { background: #10b981; color: white; }
        .status { display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 12px; }
        .status-new { background: #dbeafe; color: #2563eb; }
        .status-applied { background: #d1fae5; color: #059669; }
        .search-bar { margin-bottom: 20px; display: flex; gap: 10px; }
        .search-bar input { flex: 1; padding: 12px; border: 2px solid #e0e0e0; border-radius: 10px; font-size: 16px; }
        .search-bar button { padding: 12px 24px; background: #667eea; color: white; border: none; border-radius: 10px; cursor: pointer; }
        .filters { display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }
        .filter-btn { padding: 8px 16px; border: 2px solid #e0e0e0; background: white; border-radius: 20px; cursor: pointer; }
        .filter-btn.active { background: #667eea; color: white; border-color: #667eea; }
        @media (max-width: 768px) {
            .container { padding: 10px; }
            th, td { padding: 8px; font-size: 12px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎯 Mohammed's Job Hunter</h1>
            <p>AI-powered job matching • Tailored CVs • Smart tracking</p>
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
                <div class="number">{{ stats.today }}</div>
                <div class="label">Found Today</div>
            </div>
        </div>
        
        <div class="filters">
            <button class="filter-btn active" onclick="filterJobs('all')">All Jobs</button>
            <button class="filter-btn" onclick="filterJobs('high')">80%+ Matches</button>
            <button class="filter-btn" onclick="filterJobs('applied')">Applied</button>
            <button class="filter-btn" onclick="filterJobs('new')">New</button>
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
                        <th>Score</th>
                        <th>Job Title</th>
                        <th>Company</th>
                        <th>Platform</th>
                        <th>Status</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody id="jobTableBody">
                    {% for job in jobs %}
                    <tr data-score="{{ job.score }}" data-status="{{ job.status }}" data-title="{{ job.title.lower() }}" data-company="{{ job.company.lower() }}">
                        <td>{{ loop.index }}</td>
                        <td class="score-{% if job.score >= 80 %}high{% elif job.score >= 60 %}mid{% else %}low{% endif %}">{{ job.score }}%</td>
                        <td><a href="{{ job.link }}" target="_blank" style="color: #667eea; text-decoration: none;">{{ job.title[:80] }}</a></td>
                        <td>{{ job.company[:50] }}</td>
                        <td>{{ job.platform }}</td>
                        <td><span class="status status-{{ job.status.lower() }}">{{ job.status }}</span></td>
                        <td>
                            <a href="{{ job.link }}" target="_blank" class="btn btn-primary" style="padding: 4px 12px; font-size: 12px;">View</a>
                            <button class="btn btn-success" style="padding: 4px 12px; font-size: 12px;" onclick="generateCV('{{ job.link }}', '{{ job.title }}')">📄 CV</button>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        
        {% if not jobs %}
        <div style="text-align: center; padding: 40px; background: white; border-radius: 20px;">
            <p>No jobs found. Run your scraper to add jobs!</p>
            <p style="margin-top: 10px;">💡 Run: <code>python3 scraper.py</code> in your terminal</p>
        </div>
        {% endif %}
    </div>
    
    <script>
        function filterJobs(type) {
            const rows = document.querySelectorAll('#jobTableBody tr');
            rows.forEach(row => {
                const score = parseInt(row.dataset.score);
                const status = row.dataset.status;
                if (type === 'all') row.style.display = '';
                else if (type === 'high') row.style.display = score >= 80 ? '' : 'none';
                else if (type === 'applied') row.style.display = status === 'applied' ? '' : 'none';
                else if (type === 'new') row.style.display = status === 'new' ? '' : 'none';
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
        
        function generateCV(link, title) {
            alert('CV generation for: ' + title + '\n\nSend this link to your Telegram bot:\n' + link);
        }
    </script>
</body>
</html>
"""

# Sample job data - replace with your actual data source
def get_jobs():
    """Get jobs from your Excel file or Google Sheets"""
    jobs = []
    
    # Try to read from your Excel file first
    try:
        from openpyxl import load_workbook
        tracker_file = os.path.expanduser("~/Desktop/JobHunter/job_tracker.xlsx")
        if os.path.exists(tracker_file):
            wb = load_workbook(tracker_file, data_only=True)
            if "Master Tracker" in wb.sheetnames:
                ws = wb["Master Tracker"]
                today = date.today().strftime("%Y-%m-%d")
                for row in ws.iter_rows(min_row=2, values_only=True):
                    if row[0] and row[1] and row[2] and row[3]:
                        score_str = str(row[1]).replace('%', '')
                        try:
                            score = int(score_str)
                        except:
                            score = 0
                        jobs.append({
                            'title': str(row[3])[:200],
                            'company': str(row[2])[:100],
                            'platform': str(row[4]) if row[4] else 'Unknown',
                            'link': str(row[7]) if row[7] else '#',
                            'score': score,
                            'status': 'New'
                        })
    except Exception as e:
        print(f"Error reading Excel: {e}")
    
    # Sort by score
    jobs.sort(key=lambda x: -x['score'])
    return jobs

@app.route('/')
def dashboard():
    jobs = get_jobs()
    stats = {
        'total': len(jobs),
        'high_score': len([j for j in jobs if j['score'] >= 80]),
        'applied': 0,  # You can add applied tracking later
        'today': len([j for j in jobs if j.get('date', '') == date.today().strftime("%Y-%m-%d")])
    }
    return render_template_string(HTML_TEMPLATE, jobs=jobs, stats=stats)

@app.route('/generate-cv', methods=['POST'])
def generate_cv():
    data = request.json
    return jsonify({'success': True})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
