#!/usr/bin/env python3
import os
import threading
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Allow cross-origin requests from the Lovable frontend

from supabase import create_client
supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY"))

def build_dashboard_html():
    try:
        jobs = supabase.table("job_pool").select("*").order("created_at", desc=True).limit(200).execute().data or []
        titles = supabase.table("title_pool").select("*").order("request_count", desc=True).execute().data or []
        users = supabase.table("users").select("id,name,email,gender,cv_text,is_active,created_at").execute().data or []
        try:
            logs = supabase.table("scrape_logs").select("id,started_at,finished_at,status,total_scraped,total_saved,error").order("started_at", desc=True).limit(20).execute().data or []
        except:
            logs = []
        try:
            feedback = supabase.table("feedback").select("id,rating,comment,user_id,created_at").order("created_at", desc=True).limit(100).execute().data or []
            # map user_id -> email for readability
            fb_user_ids = [f["user_id"] for f in feedback if f.get("user_id")]
            email_map = {}
            if fb_user_ids:
                fb_users = supabase.table("users").select("id,email").in_("id", fb_user_ids).execute().data or []
                email_map = {u["id"]: u["email"] for u in fb_users}
            for f in feedback:
                f["email"] = email_map.get(f.get("user_id"), "anonymous")
        except:
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
        rows.append(
            "<tr><td>" + str(i) + "</td>"
            + '<td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + (j.get("title") or "") + "</td>"
            + "<td>" + (j.get("company") or "") + "</td>"
            + "<td>" + (j.get("location") or "UAE") + "</td>"
            + '<td style="font-size:12px;color:#64748b">' + (j.get("platform") or "") + "</td>"
            + "<td>" + posted + "</td>"
            + "<td>" + (j.get("salary") or "&mdash;") + "</td>"
            + "<td>" + score_html + "</td>"
            + '<td><a href="' + link + '" target="_blank" style="background:#2563eb;color:white;padding:4px 10px;border-radius:6px;text-decoration:none;font-size:12px">View</a></td>'
            + "</tr>"
        )
    jobs_html = "".join(rows) or '<tr><td colspan="9" style="text-align:center;padding:32px;color:#94a3b8">No jobs yet &mdash; run the scraper</td></tr>'

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
        del_btn = '<button onclick=\'delTitle(' + tid + ')\' style="background:#dc2626;color:white;border:none;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:12px">Delete</button>'
        rows.append("<tr><td>" + str(i) + "</td><td>" + (t.get("keyword") or "") + "</td><td>" + (ls or "Never") + "</td><td>" + str(t.get("request_count") or 0) + "</td><td>" + status + "</td><td>" + del_btn + "</td></tr>")
    titles_html = "".join(rows) or '<tr><td colspan="6" style="text-align:center;padding:32px;color:#94a3b8">No titles yet</td></tr>'

    # Build users rows
    rows = []
    for i, u in enumerate(users, 1):
        uid = json.dumps(u.get("id"))
        del_btn = '<button onclick=\'delUser(' + uid + ')\' style="background:#dc2626;color:white;border:none;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:12px">Delete</button>'
        rows.append(
            "<tr><td>" + str(i) + "</td>"
            + "<td>" + (u.get("name") or "&mdash;") + "</td>"
            + "<td>" + (u.get("email") or "") + "</td>"
            + "<td>" + (u.get("gender") or "&mdash;") + "</td>"
            + "<td>" + ("&#10003;" if u.get("cv_text") else "&#10007;") + "</td>"
            + "<td>" + (u.get("created_at") or "")[:10] + "</td>"
            + "<td>" + ("&#10003;" if u.get("is_active") else "&#10007;") + "</td>"
            + "<td>" + del_btn + "</td>"
            + "</tr>"
        )
    users_html = "".join(rows) or '<tr><td colspan="8" style="text-align:center;padding:32px;color:#94a3b8">No users yet</td></tr>'

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
        badge = '<span style="background:' + bbg + ';padding:2px 8px;border-radius:20px;font-size:12px">' + s + "</span>"
        lid = str(l.get("id") or "")
        started = (l.get("started_at") or "")[:16].replace("T", " ")
        finished = (l.get("finished_at") or "&mdash;")[:16].replace("T", " ")
        view_btn = '<button onclick=\'showLog("' + lid + '")\' style="background:#2563eb;color:white;border:none;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:12px">View</button>'
        rows.append(
            "<tr><td>" + str(i) + "</td>"
            + "<td>" + started + "</td>"
            + "<td>" + finished + "</td>"
            + "<td>" + badge + "</td>"
            + "<td>" + str(l.get("total_scraped") or 0) + "</td>"
            + "<td>" + str(l.get("total_saved") or 0) + "</td>"
            + "<td>" + view_btn + "</td></tr>"
        )
    logs_html = "".join(rows) or '<tr><td colspan="7" style="text-align:center;padding:32px;color:#94a3b8">No logs yet</td></tr>'

    # Build feedback rows
    rows = []
    for i, f in enumerate(feedback, 1):
        rating = f.get("rating") or 0
        stars = "★" * int(rating) + "☆" * (5 - int(rating)) if rating else "—"
        when = (f.get("created_at") or "")[:16].replace("T", " ")
        comment = (f.get("comment") or "").replace("<", "&lt;").replace(">", "&gt;") or "—"
        rows.append(
            "<tr><td>" + str(i) + "</td>"
            + "<td style=\"white-space:nowrap\">" + when + "</td>"
            + "<td style=\"color:#f59e0b\">" + stars + "</td>"
            + "<td>" + comment + "</td>"
            + "<td style=\"font-size:12px;color:#64748b\">" + (f.get("email") or "anonymous") + "</td></tr>"
        )
    feedback_html = "".join(rows) or '<tr><td colspan="5" style="text-align:center;padding:32px;color:#94a3b8">No feedback yet</td></tr>'

    scraped_today = len([t for t in titles if (t.get("last_scraped") or "")[:10] == today])

    page = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>JobHunter Admin</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f1f5f9;color:#1e293b}
.hdr{background:linear-gradient(135deg,#1e40af,#3b82f6);color:white;padding:20px 32px;display:flex;justify-content:space-between;align-items:center}
.hdr h1{font-size:22px;font-weight:700}
.wrap{max-width:1200px;margin:0 auto;padding:24px 16px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:16px;margin-bottom:24px}
.stat{background:white;border-radius:12px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.stat .v{font-size:32px;font-weight:700;color:#1e40af}
.stat .l{font-size:13px;color:#64748b;margin-top:4px}
.card{background:white;border-radius:12px;padding:24px;box-shadow:0 1px 3px rgba(0,0,0,.08);margin-bottom:20px}
.tabs{display:flex;gap:4px;margin-bottom:20px;border-bottom:2px solid #e2e8f0}
.tab{padding:10px 20px;cursor:pointer;font-size:14px;font-weight:500;color:#64748b;border-bottom:2px solid transparent;margin-bottom:-2px}
.tab.on{color:#2563eb;border-bottom-color:#2563eb}
.pane{display:none}.pane.on{display:block}
table{width:100%;border-collapse:collapse}
th{text-align:left;font-size:12px;font-weight:600;color:#64748b;text-transform:uppercase;padding:8px 12px;border-bottom:2px solid #f1f5f9}
td{padding:10px 12px;border-bottom:1px solid #f8fafc;font-size:14px}
tr:hover td{background:#f8fafc}
.log-box{background:#0f172a;color:#94a3b8;border-radius:8px;padding:16px;font-family:monospace;font-size:12px;max-height:400px;overflow-y:auto;margin-top:12px;white-space:pre-wrap;line-height:1.6}
.sp{display:inline-block;width:14px;height:14px;border:2px solid currentColor;border-top-color:transparent;border-radius:50%;animation:spin .8s linear infinite;vertical-align:middle;margin-right:6px}
@keyframes spin{to{transform:rotate(360deg)}}
input,select{padding:8px 12px;border:1px solid #e2e8f0;border-radius:8px;font-size:14px}
#msg{margin-top:16px;font-size:14px;color:#64748b}
</style></head>
<body>
<div class="hdr">
  <div><h1>JobHunter Admin</h1><small style="opacity:.8;font-size:13px">Backend dashboard</small></div>
  <div style="text-align:right;font-size:13px;opacity:.9">JOBCOUNT jobs &middot; TITLECOUNT titles &middot; USERCOUNT users</div>
</div>
<div class="wrap">
  <div class="stats">
    <div class="stat"><div class="v">JOBCOUNT</div><div class="l">Jobs in Pool</div></div>
    <div class="stat"><div class="v">TITLECOUNT</div><div class="l">Active Titles</div></div>
    <div class="stat"><div class="v">USERCOUNT</div><div class="l">Users</div></div>
    <div class="stat"><div class="v">TODAYCOUNT</div><div class="l">Scraped Today</div></div>
    <div class="stat"><div class="v">LOGCOUNT</div><div class="l">Scrape Runs</div></div>
  </div>
  <div class="tabs">
    <div class="tab on" onclick="show('jobs',this)">Job Pool</div>
    <div class="tab" onclick="show('titles',this)">Titles</div>
    <div class="tab" onclick="show('users',this)">Users</div>
    <div class="tab" onclick="show('scraper',this)">Run Scraper</div>
    <div class="tab" onclick="show('logs',this)">Logs</div>
    <div class="tab" onclick="show('feedback',this)">Feedback</div>
  </div>
  <div id="jobs" class="pane on card">
    <div style="display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap">
      <input id="qs" placeholder="Search..." oninput="filter()" style="flex:1;min-width:200px">
      <select id="qp" onchange="filter()"><option value="">All Platforms</option><option>LinkedIn</option><option>Indeed</option><option>Bayt.com</option><option>Naukrigulf</option><option>GulfTalent.com</option></select>
    </div>
    <table id="jt"><thead><tr><th>#</th><th>Title</th><th>Company</th><th>Location</th><th>Platform</th><th>Posted</th><th>Salary</th><th>Score</th><th></th></tr></thead>
    <tbody>JOBSHTML</tbody></table>
  </div>
  <div id="titles" class="pane card">
    <table><thead><tr><th>#</th><th>Keyword</th><th>Last Scraped</th><th>Requests</th><th>Status</th><th></th></tr></thead>
    <tbody>TITLESHTML</tbody></table>
  </div>
  <div id="users" class="pane card">
    <table><thead><tr><th>#</th><th>Name</th><th>Email</th><th>Gender</th><th>CV</th><th>Joined</th><th>Active</th><th></th></tr></thead>
    <tbody>USERSHTML</tbody></table>
  </div>
  <div id="scraper" class="pane card">
    <h2 style="margin-bottom:16px">Run Scraper</h2>
    <p style="color:#64748b;font-size:14px;margin-bottom:20px">Scrapes all active titles. Respects 24h cache. Daily ceiling: 200 scrapes.</p>
    <div style="display:flex;gap:12px;flex-wrap:wrap">
      <button id="sb" onclick="runScraper()" style="background:#2563eb;color:white;padding:10px 20px;border:none;border-radius:8px;cursor:pointer;font-size:14px;font-weight:600">&#9654; Run Scraper Now</button>
      <button id="eb" onclick="runEmail()" style="background:#059669;color:white;padding:10px 20px;border:none;border-radius:8px;cursor:pointer;font-size:14px;font-weight:600">Score + Email Users</button>
    </div>
    <div id="msg"></div>
  </div>
  <div id="logs" class="pane card">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <h2 style="margin:0">Scrape Logs</h2>
      <button onclick="loadLogs()" style="background:#f1f5f9;color:#64748b;padding:6px 12px;border:none;border-radius:8px;cursor:pointer;font-size:13px">Refresh</button>
    </div>
    <table><thead><tr><th>#</th><th>Started</th><th>Finished</th><th>Status</th><th>Scraped</th><th>Saved</th><th></th></tr></thead>
    <tbody id="lb">LOGSHTML</tbody></table>
    <div id="ld" style="display:none;margin-top:16px">
      <div style="display:flex;justify-content:space-between;margin-bottom:8px">
        <strong>Log Detail</strong>
        <button onclick="document.getElementById('ld').style.display='none'" style="background:#f1f5f9;border:none;padding:4px 10px;border-radius:6px;cursor:pointer">Close</button>
      </div>
      <div id="lc" class="log-box">Loading...</div>
    </div>
  </div>
  <div id="feedback" class="pane card">
    <h2 style="margin-bottom:16px">User Feedback</h2>
    <table><thead><tr><th>#</th><th>Date</th><th>Rating</th><th>Comment</th><th>From</th></tr></thead>
    <tbody>FEEDBACKHTML</tbody></table>
  </div>
</div>
<script>
function show(id,el){
  document.querySelectorAll('.pane').forEach(function(p){p.className='pane'});
  document.querySelectorAll('.tab').forEach(function(t){t.className='tab'});
  document.getElementById(id).className='pane on';
  el.className='tab on';
  if(id==='logs') loadLogs();
}
function filter(){
  var q=document.getElementById('qs').value.toLowerCase();
  var p=document.getElementById('qp').value.toLowerCase();
  document.querySelectorAll('#jt tbody tr').forEach(function(r){
    var t=r.textContent.toLowerCase();
    r.style.display=(!q||t.indexOf(q)>-1)&&(!p||t.indexOf(p)>-1)?'':'none';
  });
}
function setMsg(h){var e=document.getElementById('msg');e.style.display='block';e.innerHTML=h;}
function runScraper(){
  var b=document.getElementById('sb');
  b.disabled=true;b.innerHTML='<span class="sp"></span>Starting...';
  setMsg('Scraper running in background...');
  fetch('/api/run-scraper',{method:'POST'})
    .then(function(r){return r.json();})
    .then(function(){b.disabled=false;b.innerHTML='&#9654; Run Scraper Now';setMsg('Started! Check Logs tab in 30 seconds.');})
    .catch(function(e){b.disabled=false;b.innerHTML='&#9654; Run Scraper Now';setMsg('Error: '+e);});
}
function runEmail(){
  var b=document.getElementById('eb');
  b.disabled=true;b.innerHTML='<span class="sp"></span>Processing...';
  setMsg('Scoring and emailing...');
  fetch('/api/score-and-email',{method:'POST'})
    .then(function(r){return r.json();})
    .then(function(d){b.disabled=false;b.innerHTML='Score + Email Users';var h='';for(var i=0;i<d.log.length;i++)h+='<div>'+d.log[i]+'</div>';setMsg(h);})
    .catch(function(e){b.disabled=false;b.innerHTML='Score + Email Users';setMsg('Error: '+e);});
}
function loadLogs(){
  fetch('/api/logs').then(function(r){return r.json();}).then(function(d){
    var b=document.getElementById('lb');
    if(!d.logs||!d.logs.length){b.innerHTML='<tr><td colspan="7" style="text-align:center;padding:32px;color:#94a3b8">No logs yet</td></tr>';return;}
    var h='';
    for(var i=0;i<d.logs.length;i++){
      var l=d.logs[i];
      var s=l.status||'';
      var bg=s==='success'?'#dcfce7;color:#166534':s==='error'?'#fee2e2;color:#991b1b':'#dbeafe;color:#1d4ed8';
      h+='<tr><td>'+(i+1)+'</td><td>'+((l.started_at||'').slice(0,16).replace('T',' '))+'</td><td>'+((l.finished_at||'').slice(0,16).replace('T',' '))+'</td>';
      h+='<td><span style="background:'+bg+';padding:2px 8px;border-radius:20px;font-size:12px">'+s+'</span></td>';
      h+='<td>'+(l.total_scraped||0)+'</td><td>'+(l.total_saved||0)+'</td>';
      h+='<td><button onclick=\'showLog('+JSON.stringify(l.id)+')\' style="background:#2563eb;color:white;border:none;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:12px">View</button></td></tr>';
    }
    b.innerHTML=h;
  });
}
function showLog(id){
  var d=document.getElementById('ld');var c=document.getElementById('lc');
  d.style.display='block';c.textContent='Loading...';
  d.scrollIntoView({behavior:'smooth'});
  fetch('/api/logs/'+id).then(function(r){return r.json();}).then(function(d){c.textContent=d.log_text||'No content yet';c.scrollTop=c.scrollHeight;});
}
function delTitle(id){
  if(!confirm('Delete this title from the pool? This cannot be undone.'))return;
  fetch('/api/delete-title',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:id})})
    .then(function(r){return r.json();})
    .then(function(d){if(d.ok){location.reload();}else{alert('Error: '+(d.error||'failed'));}})
    .catch(function(e){alert('Error: '+e);});
}
function delUser(id){
  if(!confirm('Delete this user and all their matches/titles links? This cannot be undone.'))return;
  fetch('/api/delete-user',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:id})})
    .then(function(r){return r.json();})
    .then(function(d){if(d.ok){location.reload();}else{alert('Error: '+(d.error||'failed'));}})
    .catch(function(e){alert('Error: '+e);});
}
</script>
</body></html>"""

    page = page.replace("JOBCOUNT", str(len(jobs)))
    page = page.replace("TITLECOUNT", str(len(titles)))
    page = page.replace("USERCOUNT", str(len(users)))
    page = page.replace("TODAYCOUNT", str(scraped_today))
    page = page.replace("LOGCOUNT", str(len(logs)))
    page = page.replace("JOBSHTML", jobs_html)
    page = page.replace("TITLESHTML", titles_html)
    page = page.replace("USERSHTML", users_html)
    page = page.replace("LOGSHTML", logs_html)
    page = page.replace("FEEDBACKHTML", feedback_html)
    return page


@app.route('/')
def dashboard():
    return build_dashboard_html()


@app.route('/health')
def health():
    return jsonify({"status": "ok"})


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
    from scraper_v2 import search_and_score_for_user, RunLogger
    from email_service import send_job_matches_email
    log_lines = []
    try:
        logger = RunLogger("score_and_email")
        users = supabase.table("users").select("*").eq("is_active", True).execute().data or []
        if not users:
            return jsonify({"log": ["No active users yet"]})
        for user in users:
            matched = search_and_score_for_user(user, logger=logger)
            if matched:
                sent = send_job_matches_email(user["email"], user.get("name"), matched)
                log_lines.append(str(len(matched)) + " matches — email " + ("sent" if sent else "failed"))
            else:
                log_lines.append("No 60%+ matches for " + (user.get("email") or ""))
        logger.finish(success=True)
    except Exception as e:
        log_lines.append("Error: " + str(e))
    return jsonify({"log": log_lines})


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
    from datetime import timedelta
    data = request.json or {}
    user_id = data.get("user_id")
    keyword = (data.get("keyword") or "").strip()
    is_signup = data.get("is_signup", False)  # signup bypasses the cooldown
    if not user_id or not keyword:
        return jsonify({"error": "user_id and keyword required"}), 400
    if not validate_title(keyword):
        return jsonify({"error": "Invalid title"}), 400

    existing = supabase.table("user_titles").select("id").eq("user_id", user_id).execute()
    current_count = len(existing.data or [])
    if current_count >= 5:
        return jsonify({"error": "Maximum 5 job titles allowed"}), 400

    # 14-day cooldown on title changes (skipped during initial signup)
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

    # Stamp the change time (only for non-signup edits)
    if not is_signup:
        supabase.table("users").update({"titles_updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", user_id).execute()

    def bg():
        ud = supabase.table("users").select("gender").eq("id", user_id).execute().data
        search_jobs(keyword, user_gender=ud[0].get("gender") if ud else None)
    threading.Thread(target=bg, daemon=True).start()
    return jsonify({"success": True, "title_id": title_record["id"]})


@app.route('/api/can-edit-titles', methods=['POST'])
def api_can_edit_titles():
    """Returns whether the user can edit titles and days remaining if not."""
    from datetime import timedelta
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
        # remove any user links to this title first, then the title
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
        # clean up dependent rows first to avoid orphans
        supabase.table("user_job_matches").delete().eq("user_id", uid).execute()
        supabase.table("user_titles").delete().eq("user_id", uid).execute()
        try:
            supabase.table("feedback").delete().eq("user_id", uid).execute()
        except Exception:
            pass
        supabase.table("users").delete().eq("id", uid).execute()
        return jsonify({"ok": True, "note": "Removed from users table. Auth account (Supabase Auth) must be deleted separately if needed."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
