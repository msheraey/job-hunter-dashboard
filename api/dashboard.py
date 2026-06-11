"""
api/dashboard.py — Rebuilt admin dashboard. Single self-contained page:
system health, analytics, credit balance, run triggers, live log viewer.
Auto-refreshes; zero build tools; fetches the JSON APIs the backend already has.
"""

def render_dashboard():
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>JobHunter — Admin</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#0B1829;color:#D8D0C0;padding:20px;min-height:100vh}
.wrap{max-width:1100px;margin:0 auto}
h1{font-size:22px;color:#F0EAD8}h1 span{color:#C9A84C}
.sub{font-size:12px;color:#7A7060;margin:4px 0 20px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-bottom:20px}
.card{background:#111F30;border:1px solid #1C3050;border-radius:8px;padding:14px}
.v{font-size:24px;font-weight:800;color:#F0EAD8}.v.ok{color:#4ECB7A}.v.bad{color:#E07070}
.l{font-size:10px;color:#6A6050;text-transform:uppercase;letter-spacing:.06em;margin-top:4px}
.sec{font-size:11px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#C9A84C;
  border-bottom:1px solid #1C3050;padding-bottom:6px;margin:24px 0 12px}
.row{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}
button{background:#C9A84C;color:#0B1829;border:none;border-radius:6px;padding:10px 16px;
  font-weight:700;font-size:13px;cursor:pointer}
button.ghost{background:#1C3050;color:#D8D0C0}
button:disabled{opacity:.5;cursor:wait}
.hgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}
.hcard{background:#111F30;border:1px solid #1C3050;border-radius:8px;padding:10px 12px;font-size:12px}
.hname{font-weight:700;color:#E8E0D0}.hmsg{color:#7A7060;font-size:11px;margin-top:2px;word-break:break-word}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.dot.g{background:#4ECB7A}.dot.r{background:#E07070}
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;color:#C9A84C;font-size:10px;text-transform:uppercase;padding:8px;border-bottom:1px solid #1C3050}
td{padding:8px;border-bottom:1px solid #111E2C;color:#C8C0B0}
.st-success{color:#4ECB7A}.st-error{color:#E07070}.st-running{color:#C9A84C}
pre{background:#070F1A;border:1px solid #1C3050;border-radius:8px;padding:12px;font-size:11px;
  max-height:340px;overflow:auto;white-space:pre-wrap;display:none;margin-top:10px;color:#A8A090}
#toast{position:fixed;bottom:20px;right:20px;background:#C9A84C;color:#0B1829;padding:10px 16px;
  border-radius:8px;font-weight:700;font-size:13px;display:none}
</style></head>
<body><div class="wrap">
<h1>JobHunter <span>Admin</span></h1>
<p class="sub">Auto-refreshes every 30s · <span id="ts"></span></p>

<div class="grid" id="stats"></div>

<p class="sec">System Health</p>
<div class="hgrid" id="health"></div>

<p class="sec">Actions</p>
<div class="row">
  <button onclick="trigger('/api/run-scraper','Scrape started')">▶ Run Scraper</button>
  <button onclick="trigger('/api/score-and-email','Scoring started')">▶ Score &amp; Email</button>
  <button class="ghost" onclick="loadAll()">↻ Refresh</button>
  <button class="ghost" onclick="selfTest()">🩺 Self-Test</button>
</div>

<p class="sec">Recent Runs</p>
<table><thead><tr><th>Started</th><th>Status</th><th>Scraped</th><th>Saved</th><th>Log</th></tr></thead>
<tbody id="logs"></tbody></table>
<pre id="logview"></pre>

<div id="toast"></div>
</div>
<script>
const $=id=>document.getElementById(id);
function toast(m){const t=$('toast');t.textContent=m;t.style.display='block';setTimeout(()=>t.style.display='none',3000)}
async function j(u,opt){const r=await fetch(u,opt);return r.json()}
async function trigger(url,msg){try{await j(url,{method:'POST'});toast(msg);setTimeout(loadLogs,2000)}catch(e){toast('Failed: '+e)}}
async function loadStats(){try{const d=await j('/api/analytics');
  $('stats').innerHTML=['users','jobs_in_pool','matches_60plus','titles'].map(k=>
  `<div class="card"><div class="v">${d[k]??'—'}</div><div class="l">${k.replaceAll('_',' ')}</div></div>`).join('')}catch(e){}}
async function loadHealth(){try{const d=await j('/api/system-health');
  $('health').innerHTML=Object.entries(d).filter(([k,v])=>typeof v==='object').map(([k,v])=>
  `<div class="hcard"><span class="dot ${v.ok?'g':'r'}"></span><span class="hname">${k}</span>
   <div class="hmsg">${v.msg||''}</div></div>`).join('')}catch(e){}}
async function loadLogs(){try{const rows=await j('/api/logs');
  $('logs').innerHTML=rows.map(r=>
  `<tr><td>${(r.started_at||'').slice(0,16).replace('T',' ')}</td>
   <td class="st-${r.status}">${r.status}</td><td>${r.total_scraped??0}</td>
   <td>${r.total_saved??0}</td>
   <td><button class="ghost" style="padding:4px 10px;font-size:11px" onclick="viewLog('${r.id}')">view</button></td></tr>`).join('')}catch(e){}}
async function viewLog(id){try{const d=await j('/api/logs/'+id);
  const p=$('logview');p.textContent=d.log_text||'(empty)';p.style.display='block';p.scrollIntoView({behavior:'smooth'})}catch(e){}}
async function selfTest(){toast('Running self-test…');await loadHealth();toast('Self-test done')}
function loadAll(){$('ts').textContent=new Date().toLocaleTimeString();loadStats();loadHealth();loadLogs()}
loadAll();setInterval(loadAll,30000);
</script></body></html>"""
