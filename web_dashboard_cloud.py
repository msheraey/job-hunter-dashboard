#!/usr/bin/env python3
import os
import threading
from datetime import datetime, timezone
from flask import Flask, request, jsonify

app = Flask(__name__)

from supabase import create_client
supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY"))

@app.route('/')
def dashboard():
    try:
        jobs = supabase.table("job_pool").select("*").order("created_at", desc=True).limit(200).execute().data or []
        titles = supabase.table("title_pool").select("*").order("request_count", desc=True).execute().data or []
        users = supabase.table("users").select("id,name,email,gender,cv_text,is_active,created_at").execute().data or []
        try:
            logs = supabase.table("scrape_logs").select("id,started_at,finished_at,status,total_scraped,total_saved,error").order("started_at", desc=True).limit(20).execute().data or []
        except:
            logs = []
        today = datetime.now(timezone.utc).date().isoformat()
    except Exception as e:
        return f"<h1>DB Error: {e}</h1>", 500

    jobs_html = ""
    for i, j in enumerate(jobs, 1):
        score = j.get('score') or 0
        score_badge = f'<span style="background:{"#dcfce7;color:#166534" if score>=80 else "#fef9c3;color:#854d0e" if score>=60 else "#fee2e2;color:#991b1b"};padding:2px 8px;border-radius:20px;font-size:12px;font-weight:600">{score}%</span>' if score else '<span style="color:#94a3b8">—</span>'
        posted = (j.get('posted_at') or '')[:10] or '—'
        jobs_html += f'<tr><td>{i}</td><td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{j.get("title","")}</td><td>{j.get("company","")}</td><td>{j.get("location","UAE")}</td><td style="font-size:12px;color:#64748b">{j.get("platform","")}</td><td>{posted}</td><td>{j.get("salary") or "—"}</td><td>{score_badge}</td><td><a href="{j.get("link","#")}" target="_blank" style="background:#2563eb;color:white;padding:4px 10px;border-radius:6px;text-decoration:none;font-size:12px">View</a></td></tr>'

    titles_html = ""
    for i, t in enumerate(titles, 1):
        ls = (t.get('last_scraped') or '')[:16].replace('T',' ')
        status = '<span style="background:#dcfce7;color:#166534;padding:2px 8px;border-radius:20px;font-size:12px">Fresh</span>' if (t.get('last_scraped') or '')[:10] == today else '<span style="background:#fef9c3;color:#854d0e;padding:2px 8px;border-radius:20px;font-size:12px">Stale</span>' if t.get('last_scraped') else '<span style="background:#f1f5f9;color:#64748b;padding:2px 8px;border-radius:20px;font-size:12px">Never</span>'
        titles_html += f'<tr><td>{i}</td><td>{t.get("keyword","")}</td><td>{ls or "Never"}</td><td>{t.get("request_count",0)}</td><td>{status}</td></tr>'

    users_html = ""
    for i, u in enumerate(users, 1):
        users_html += f'<tr><td>{i}</td><td>{u.get("name","—")}</td><td>{u.get("email","")}</td><td>{u.get("gender","—")}</td><td>{"✓" if u.get("cv_text") else "✗"}</td><td>{(u.get("created_at") or "")[:10]}</td><td>{"✓" if u.get("is_active") else "✗"}</td></tr>'

    logs_html = ""
    for i, l in enumerate(logs, 1):
        s = l.get('status','')
        badge = f'<span style="background:{"#dcfce7;color:#166534" if s=="success" else "#fee2e2;color:#991b1b" if s=="error" else "#dbeafe;color:#1d4ed8"};padding:2px 8px;border-radius:20px;font-size:12px">{s}</span>'
        logs_html += f'<tr><td>{i}</td><td>{(l.get("started_at") or "")[:16].replace("T"," ")}</td><td>{(l.get("finished_at") or "—")[:16].replace("T"," ")}</td><td>{badge}</td><td>{l.get("total_scraped",0)}</td><td>{l.get("total_saved",0)}</td><td><button onclick="showLog('" + l.get('id','') + "')" style="background:#2563eb;color:white;border:none;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:12px">View</button></td></tr>'

    scraped_today = len([t for t in titles if (t.get("last_scraped","") or "")[:10] == today])

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>JobHunter Admin</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f1f5f9;color:#1e293b}}
.hdr{{background:linear-gradient(135deg,#1e40af,#3b82f6);color:white;padding:20px 32px;display:flex;justify-content:space-between;align-items:center}}
.hdr h1{{font-size:22px;font-weight:700}}
.wrap{{max-width:1200px;margin:0 auto;padding:24px 16px}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:16px;margin-bottom:24px}}
.stat{{background:white;border-radius:12px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
.stat .v{{font-size:32px;font-weight:700;color:#1e40af}}
.stat .l{{font-size:13px;color:#64748b;margin-top:4px}}
.card{{background:white;border-radius:12px;padding:24px;box-shadow:0 1px 3px rgba(0,0,0,.08);margin-bottom:20px}}
.tabs{{display:flex;gap:4px;margin-bottom:20px;border-bottom:2px solid #e2e8f0}}
.tab{{padding:10px 20px;cursor:pointer;font-size:14px;font-weight:500;color:#64748b;border-bottom:2px solid transparent;margin-bottom:-2px}}
.tab.on{{color:#2563eb;border-bottom-color:#2563eb}}
.pane{{display:none}}.pane.on{{display:block}}
table{{width:100%;border-collapse:collapse}}
th{{text-align:left;font-size:12px;font-weight:600;color:#64748b;text-transform:uppercase;padding:8px 12px;border-bottom:2px solid #f1f5f9}}
td{{padding:10px 12px;border-bottom:1px solid #f8fafc;font-size:14px}}
tr:hover td{{background:#f8fafc}}
.log-box{{background:#0f172a;color:#94a3b8;border-radius:8px;padding:16px;font-family:monospace;font-size:12px;max-height:400px;overflow-y:auto;margin-top:12px;white-space:pre-wrap;line-height:1.6}}
.sp{{display:inline-block;width:14px;height:14px;border:2px solid currentColor;border-top-color:transparent;border-radius:50%;animation:spin .8s linear infinite;vertical-align:middle;margin-right:6px}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
input,select{{padding:8px 12px;border:1px solid #e2e8f0;border-radius:8px;font-size:14px}}
#msg{{margin-top:16px;font-size:14px;color:#64748b}}
</style></head>
<body>
<div class="hdr">
  <div><h1>JobHunter Admin</h1><small style="opacity:.8;font-size:13px">Backend dashboard</small></div>
  <div style="text-align:right;font-size:13px;opacity:.9">{len(jobs)} jobs &middot; {len(titles)} titles &middot; {len(users)} users</div>
</div>
<div class="wrap">
  <div class="stats">
    <div class="stat"><div class="v">{len(jobs)}</div><div class="l">Jobs in Pool</div></div>
    <div class="stat"><div class="v">{len(titles)}</div><div class="l">Active Titles</div></div>
    <div class="stat"><div class="v">{len(users)}</div><div class="l">Users</div></div>
    <div class="stat"><div class="v">{scraped_today}</div><div class="l">Scraped Today</div></div>
    <div class="stat"><div class="v">{len(logs)}</div><div class="l">Scrape Runs</div></div>
  </div>
  <div class="tabs">
    <div class="tab on" onclick="show('jobs',this)">Job Pool</div>
    <div class="tab" onclick="show('titles',this)">Titles</div>
    <div class="tab" onclick="show('users',this)">Users</div>
    <div class="tab" onclick="show('scraper',this)">Run Scraper</div>
    <div class="tab" onclick="show('logs',this)">Logs</div>
  </div>
  <div id="jobs" class="pane on card">
    <div style="display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap">
      <input id="qs" placeholder="Search..." oninput="filter()" style="flex:1;min-width:200px">
      <select id="qp" onchange="filter()"><option value="">All Platforms</option><option>LinkedIn</option><option>Indeed</option><option>Bayt.com</option><option>Naukrigulf</option><option>GulfTalent.com</option></select>
    </div>
    <table id="jt"><thead><tr><th>#</th><th>Title</th><th>Company</th><th>Location</th><th>Platform</th><th>Posted</th><th>Salary</th><th>Score</th><th></th></tr></thead>
    <tbody>{jobs_html or '<tr><td colspan="9" style="text-align:center;padding:32px;color:#94a3b8">No jobs yet — run the scraper</td></tr>'}</tbody></table>
  </div>
  <div id="titles" class="pane card">
    <table><thead><tr><th>#</th><th>Keyword</th><th>Last Scraped</th><th>Requests</th><th>Status</th></tr></thead>
    <tbody>{titles_html or '<tr><td colspan="5" style="text-align:center;padding:32px;color:#94a3b8">No titles yet</td></tr>'}</tbody></table>
  </div>
  <div id="users" class="pane card">
    <table><thead><tr><th>#</th><th>Name</th><th>Email</th><th>Gender</th><th>CV</th><th>Joined</th><th>Active</th></tr></thead>
    <tbody>{users_html or '<tr><td colspan="7" style="text-align:center;padding:32px;color:#94a3b8">No users yet</td></tr>'}</tbody></table>
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
    <tbody id="lb">{logs_html or '<tr><td colspan="7" style="text-align:center;padding:32px;color:#94a3b8">No logs yet</td></tr>'}</tbody></table>
    <div id="ld" style="display:none">
      <div style="display:flex;justify-content:space-between;margin-top:16px;margin-bottom:8px">
        <strong>Log Detail</strong>
        <button onclick="document.getElementById('ld').style.display='none'" style="background:#f1f5f9;border:none;padding:4px 10px;border-radius:6px;cursor:pointer">Close</button>
      </div>
      <div id="lc" class="log-box">Loading...</div>
    </div>
  </div>
</div>
<script>
function show(id,el){{
  document.querySelectorAll('.pane').forEach(function(p){{p.className='pane'}});
  document.querySelectorAll('.tab').forEach(function(t){{t.className='tab'}});
  document.getElementById(id).className='pane on';
  el.className='tab on';
  if(id==='logs') loadLogs();
}}
function filter(){{
  var q=document.getElementById('qs').value.toLowerCase();
  var p=document.getElementById('qp').value.toLowerCase();
  document.querySelectorAll('#jt tbody tr').forEach(function(r){{
    var t=r.textContent.toLowerCase();
    r.style.display=(!q||t.indexOf(q)>-1)&&(!p||t.indexOf(p)>-1)?'':'none';
  }});
}}
function setMsg(h){{var e=document.getElementById('msg');e.style.display='block';e.innerHTML=h;}}
function runScraper(){{
  var b=document.getElementById('sb');
  b.disabled=true;b.innerHTML='<span class="sp"></span>Starting...';
  setMsg('Scraper running in background — check Logs tab in 30 seconds...');
  fetch('/api/run-scraper',{{method:'POST'}})
    .then(function(r){{return r.json();}})
    .then(function(){{b.disabled=false;b.innerHTML='&#9654; Run Scraper Now';setMsg('Started! <a href="#" onclick="show(\'logs\',document.querySelectorAll(\'.tab\')[4]);return false;">View Logs</a>');}})
    .catch(function(e){{b.disabled=false;b.innerHTML='&#9654; Run Scraper Now';setMsg('Error: '+e);}});
}}
function runEmail(){{
  var b=document.getElementById('eb');
  b.disabled=true;b.innerHTML='<span class="sp"></span>Processing...';
  setMsg('Scoring and emailing...');
  fetch('/api/score-and-email',{{method:'POST'}})
    .then(function(r){{return r.json();}})
    .then(function(d){{b.disabled=false;b.innerHTML='Score + Email Users';var h='';for(var i=0;i<d.log.length;i++)h+='<div>'+d.log[i]+'</div>';setMsg(h);}})
    .catch(function(e){{b.disabled=false;b.innerHTML='Score + Email Users';setMsg('Error: '+e);}});
}}
function loadLogs(){{
  fetch('/api/logs').then(function(r){{return r.json();}}).then(function(d){{
    var b=document.getElementById('lb');
    if(!d.logs||!d.logs.length){{b.innerHTML='<tr><td colspan="7" style="text-align:center;padding:32px;color:#94a3b8">No logs yet</td></tr>';return;}}
    var h='';
    for(var i=0;i<d.logs.length;i++){{
      var l=d.logs[i];
      var s=l.status||'';
      var bg=s==='success'?'#dcfce7;color:#166534':s==='error'?'#fee2e2;color:#991b1b':'#dbeafe;color:#1d4ed8';
      h+='<tr><td>'+(i+1)+'</td><td>'+((l.started_at||'').slice(0,16).replace('T',' '))+'</td><td>'+((l.finished_at||'—').slice(0,16).replace('T',' '))+'</td>';
      h+='<td><span style="background:'+bg+';padding:2px 8px;border-radius:20px;font-size:12px">'+s+'</span></td>';
      h+='<td>'+(l.total_scraped||0)+'</td><td>'+(l.total_saved||0)+'</td>';
      h+='<td><button onclick="showLog(\''+l.id+'\')" style="background:#2563eb;color:white;border:none;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:12px">View</button></td></tr>';
    }}
    b.innerHTML=h;
  }});
}}
function showLog(id){{
  var d=document.getElementById('ld');var c=document.getElementById('lc');
  d.style.display='block';c.textContent='Loading...';
  d.scrollIntoView({{behavior:'smooth'}});
  fetch('/api/logs/'+id).then(function(r){{return r.json();}}).then(function(d){{c.textContent=d.log_text||'No content yet';c.scrollTop=c.scrollHeight;}});
}}
</script>
</body></html>"""
    return html


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
    title_record = title_result.data[0] if title_result.data else supabase.table("title_pool").insert({"keyword": keyword, "normalized": normalized, "request_count": 0}).execute().data[0]
    try:
        supabase.table("user_titles").insert({"user_id": user_id, "title_id": title_record["id"]}).execute()
    except:
        pass
    def bg():
        ud = supabase.table("users").select("gender").eq("id", user_id).execute().data
        search_jobs(keyword, user_gender=ud[0].get("gender") if ud else None)
    threading.Thread(target=bg, daemon=True).start()
    return jsonify({"success": True, "title_id": title_record["id"]})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
