"""
api/dashboard.py — JobHunter admin panel. A self-contained, multi-tab SaaS-style
control room rendered as a single HTML string (no build step, no framework).

Tabs: Dashboard · Runs · Jobs · Users · Analytics · Diagnostics · Settings.
It consumes the JSON APIs the backend already exposes:
  /api/analytics · /api/system-health · /api/logs · /api/logs/<id>
  /api/run-scraper (POST) · /api/score-and-email (POST)

Chart.js is loaded from CDN. No backend routes are modified by this file.
"""


def render_dashboard():
    return r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>JobHunter · Admin</title>
<link rel="icon" href="/favicon.ico">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
:root{
  --bg-base:#08090E;--bg-panel:#0F1118;--bg-card:#13151E;--bg-hover:#1A1D28;
  --border:#22252F;--border-soft:#1A1C24;
  --text:#E6E8EF;--text-dim:#9398A6;--text-faint:#5C6070;
  --accent:#7C3AED;--accent-soft:rgba(124,58,237,.14);--accent-bright:#9F67FF;
  --green:#22C55E;--red:#EF4444;--amber:#F59E0B;--blue:#3B82F6;
  --radius:14px;--radius-sm:10px;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{
  font-family:'Inter',system-ui,-apple-system,sans-serif;
  background:var(--bg-base);color:var(--text);
  -webkit-font-smoothing:antialiased;display:flex;min-height:100vh;
}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:6px}
::-webkit-scrollbar-track{background:transparent}

/* ── Sidebar ─────────────────────────────────────────── */
.sidebar{
  width:236px;flex-shrink:0;background:var(--bg-panel);
  border-right:1px solid var(--border-soft);padding:22px 14px;
  display:flex;flex-direction:column;position:sticky;top:0;height:100vh;
}
.brand{display:flex;align-items:center;gap:11px;padding:0 8px 22px;margin-bottom:8px}
.brand .logo{
  width:34px;height:34px;border-radius:9px;background:linear-gradient(135deg,var(--accent),var(--accent-bright));
  display:grid;place-items:center;font-weight:800;font-size:18px;color:#fff;
  box-shadow:0 4px 14px rgba(124,58,237,.4);
}
.brand .name{font-weight:700;font-size:15px;letter-spacing:-.01em}
.brand .name small{display:block;font-weight:500;font-size:11px;color:var(--text-faint);letter-spacing:.02em}
.nav{display:flex;flex-direction:column;gap:2px;flex:1}
.nav button{
  display:flex;align-items:center;gap:11px;width:100%;text-align:left;
  background:none;border:none;color:var(--text-dim);font-family:inherit;font-size:13.5px;
  font-weight:500;padding:10px 12px;border-radius:var(--radius-sm);cursor:pointer;transition:.13s;
}
.nav button:hover{background:var(--bg-hover);color:var(--text)}
.nav button.active{background:var(--accent-soft);color:var(--accent-bright);font-weight:600}
.nav button svg{width:17px;height:17px;flex-shrink:0;stroke-width:2}
.nav .sep{font-size:10px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;
  color:var(--text-faint);padding:16px 12px 6px}
.side-foot{font-size:11px;color:var(--text-faint);padding:10px 12px;line-height:1.5}
.side-foot .pulse{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--green);margin-right:6px;box-shadow:0 0 0 3px rgba(34,197,94,.18)}

/* ── Main ────────────────────────────────────────────── */
.main{flex:1;min-width:0;display:flex;flex-direction:column}
.topbar{
  display:flex;align-items:center;justify-content:space-between;gap:16px;
  padding:18px 30px;border-bottom:1px solid var(--border-soft);position:sticky;top:0;
  background:rgba(8,9,14,.82);backdrop-filter:blur(12px);z-index:20;
}
.topbar h1{font-size:19px;font-weight:700;letter-spacing:-.02em}
.topbar .crumb{font-size:12px;color:var(--text-faint);margin-top:2px}
.topbar .right{display:flex;align-items:center;gap:10px}
.content{padding:26px 30px 60px;max-width:1240px;width:100%}
.tab-page{display:none;animation:fade .25s ease}
.tab-page.active{display:block}
@keyframes fade{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}

/* ── Buttons ─────────────────────────────────────────── */
.btn{
  display:inline-flex;align-items:center;gap:7px;background:var(--accent);color:#fff;border:none;
  font-family:inherit;font-weight:600;font-size:13px;padding:9px 16px;border-radius:var(--radius-sm);
  cursor:pointer;transition:.14s;white-space:nowrap;
}
.btn:hover{background:var(--accent-bright);transform:translateY(-1px)}
.btn:active{transform:none}
.btn:disabled{opacity:.55;cursor:wait;transform:none}
.btn.ghost{background:var(--bg-card);color:var(--text);border:1px solid var(--border)}
.btn.ghost:hover{background:var(--bg-hover);border-color:var(--accent)}
.btn.danger{background:rgba(239,68,68,.12);color:#FCA5A5;border:1px solid rgba(239,68,68,.3)}
.btn.danger:hover{background:rgba(239,68,68,.2)}
.btn.sm{padding:6px 11px;font-size:12px}
.btn svg{width:15px;height:15px;stroke-width:2}

/* ── Cards & grids ───────────────────────────────────── */
.grid{display:grid;gap:14px}
.kpis{grid-template-columns:repeat(auto-fit,minmax(190px,1fr))}
.card{
  background:var(--bg-card);border:1px solid var(--border-soft);border-radius:var(--radius);
  padding:18px;position:relative;overflow:hidden;
}
.kpi .top{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}
.kpi .ico{width:36px;height:36px;border-radius:10px;display:grid;place-items:center;background:var(--accent-soft)}
.kpi .ico svg{width:18px;height:18px;color:var(--accent-bright);stroke-width:2}
.kpi .val{font-size:30px;font-weight:800;letter-spacing:-.03em;line-height:1}
.kpi .lbl{font-size:12px;color:var(--text-dim);margin-top:7px;font-weight:500}
.kpi .delta{font-size:11px;color:var(--text-faint);margin-top:3px}
.section-h{display:flex;align-items:center;justify-content:space-between;margin:30px 0 14px}
.section-h h2{font-size:15px;font-weight:700;letter-spacing:-.01em}
.section-h .hint{font-size:12px;color:var(--text-faint)}

/* ── Health ──────────────────────────────────────────── */
.health-grid{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
.hcard{display:flex;align-items:flex-start;gap:12px;padding:15px 16px}
.hcard .dot{width:9px;height:9px;border-radius:50%;margin-top:5px;flex-shrink:0}
.hcard .dot.g{background:var(--green);box-shadow:0 0 0 3px rgba(34,197,94,.16)}
.hcard .dot.r{background:var(--red);box-shadow:0 0 0 3px rgba(239,68,68,.16)}
.hcard .hname{font-weight:600;font-size:13.5px;text-transform:capitalize}
.hcard .hmsg{font-size:11.5px;color:var(--text-dim);margin-top:3px;word-break:break-word;font-family:'JetBrains Mono',monospace}
.badge{display:inline-flex;align-items:center;gap:5px;font-size:11px;font-weight:600;padding:3px 9px;border-radius:20px}
.badge.g{background:rgba(34,197,94,.13);color:#4ADE80}
.badge.r{background:rgba(239,68,68,.13);color:#F87171}
.badge.a{background:rgba(245,158,11,.13);color:#FBBF24}

/* ── Tables ──────────────────────────────────────────── */
.tbl-wrap{background:var(--bg-card);border:1px solid var(--border-soft);border-radius:var(--radius);overflow:hidden}
table{width:100%;border-collapse:collapse;font-size:13px}
thead th{
  text-align:left;font-size:10.5px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;
  color:var(--text-faint);padding:13px 18px;border-bottom:1px solid var(--border-soft);background:var(--bg-panel);
}
tbody td{padding:13px 18px;border-bottom:1px solid var(--border-soft);color:var(--text-dim)}
tbody tr:last-child td{border-bottom:none}
tbody tr{transition:.1s}
tbody tr:hover{background:var(--bg-hover)}
td .mono{font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--text)}
.st{font-weight:600;text-transform:capitalize}
.st-success{color:var(--green)}.st-error{color:var(--red)}.st-running{color:var(--amber)}

/* ── Empty / placeholder ─────────────────────────────── */
.empty{text-align:center;padding:46px 20px;color:var(--text-faint)}
.empty .eico{width:48px;height:48px;border-radius:14px;background:var(--accent-soft);display:grid;place-items:center;margin:0 auto 16px}
.empty .eico svg{width:24px;height:24px;color:var(--accent-bright)}
.empty h3{font-size:15px;color:var(--text);font-weight:600;margin-bottom:6px}
.empty p{font-size:13px;max-width:420px;margin:0 auto;line-height:1.6}

/* ── Skeleton ────────────────────────────────────────── */
.sk{background:linear-gradient(90deg,var(--bg-card) 25%,var(--bg-hover) 50%,var(--bg-card) 75%);
  background-size:200% 100%;animation:shimmer 1.4s infinite;border-radius:6px}
@keyframes shimmer{from{background-position:200% 0}to{background-position:-200% 0}}

/* ── Charts ──────────────────────────────────────────── */
.chart-grid{grid-template-columns:1.4fr 1fr}
.chart-box{padding:20px}
.chart-box h3{font-size:13.5px;font-weight:600;margin-bottom:4px}
.chart-box .sub{font-size:11.5px;color:var(--text-faint);margin-bottom:16px}
.chart-canvas{position:relative;height:260px}

/* ── Toast ───────────────────────────────────────────── */
#toasts{position:fixed;bottom:22px;right:22px;display:flex;flex-direction:column;gap:10px;z-index:200}
.toast{
  display:flex;align-items:center;gap:10px;background:var(--bg-card);border:1px solid var(--border);
  color:var(--text);padding:12px 16px;border-radius:var(--radius-sm);font-size:13px;font-weight:500;
  box-shadow:0 12px 36px rgba(0,0,0,.5);min-width:240px;animation:slideIn .26s cubic-bezier(.2,.8,.2,1);
}
.toast .ti{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.toast.ok .ti{background:var(--green)}.toast.err .ti{background:var(--red)}.toast.info .ti{background:var(--accent-bright)}
@keyframes slideIn{from{opacity:0;transform:translateX(40px)}to{opacity:1;transform:none}}

/* ── Drawer (slide-over for logs) ────────────────────── */
.scrim{position:fixed;inset:0;background:rgba(0,0,0,.6);backdrop-filter:blur(2px);opacity:0;
  pointer-events:none;transition:.22s;z-index:90}
.scrim.show{opacity:1;pointer-events:auto}
.drawer{
  position:fixed;top:0;right:0;height:100vh;width:min(640px,94vw);background:var(--bg-panel);
  border-left:1px solid var(--border);transform:translateX(100%);transition:transform .28s cubic-bezier(.2,.8,.2,1);
  z-index:100;display:flex;flex-direction:column;
}
.drawer.show{transform:none}
.drawer .dh{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;
  padding:20px 22px;border-bottom:1px solid var(--border-soft)}
.drawer .dh h3{font-size:15px;font-weight:700}
.drawer .dh .meta{font-size:12px;color:var(--text-faint);margin-top:4px;font-family:'JetBrains Mono',monospace}
.drawer .xb{background:var(--bg-card);border:1px solid var(--border);color:var(--text-dim);
  width:32px;height:32px;border-radius:8px;cursor:pointer;display:grid;place-items:center;flex-shrink:0}
.drawer .xb:hover{color:var(--text);border-color:var(--accent)}
.drawer .dbody{flex:1;overflow:auto;padding:18px 22px}
.drawer .dstats{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px}
.drawer .dstat{background:var(--bg-card);border:1px solid var(--border-soft);border-radius:10px;padding:10px 14px}
.drawer .dstat .v{font-size:18px;font-weight:700}.drawer .dstat .l{font-size:10.5px;color:var(--text-faint);text-transform:uppercase;letter-spacing:.05em;margin-top:2px}
.logpre{background:#05060A;border:1px solid var(--border-soft);border-radius:var(--radius-sm);
  padding:16px;font-family:'JetBrains Mono',monospace;font-size:12px;line-height:1.7;color:#B8BDCC;
  white-space:pre-wrap;word-break:break-word}

/* ── Modal (confirm) ─────────────────────────────────── */
.modal{
  position:fixed;inset:0;display:none;place-items:center;z-index:150;
  background:rgba(0,0,0,.62);backdrop-filter:blur(3px);padding:20px;
}
.modal.show{display:grid;animation:fade .2s}
.modal .box{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);
  padding:24px;width:min(420px,100%);box-shadow:0 24px 60px rgba(0,0,0,.6)}
.modal .box h3{font-size:16px;font-weight:700;margin-bottom:8px}
.modal .box p{font-size:13.5px;color:var(--text-dim);line-height:1.6;margin-bottom:22px}
.modal .box .acts{display:flex;gap:10px;justify-content:flex-end}

/* ── Settings rows ───────────────────────────────────── */
.set-row{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:16px 0;border-bottom:1px solid var(--border-soft)}
.set-row:last-child{border-bottom:none}
.set-row .info h4{font-size:13.5px;font-weight:600}
.set-row .info p{font-size:12px;color:var(--text-faint);margin-top:3px}
select,input.txt{background:var(--bg-base);border:1px solid var(--border);color:var(--text);
  font-family:inherit;font-size:13px;padding:8px 12px;border-radius:8px;outline:none}
select:focus,input.txt:focus{border-color:var(--accent)}

@media(max-width:880px){
  .sidebar{width:64px;padding:18px 8px}
  .brand .name,.nav button span,.nav .sep,.side-foot{display:none}
  .nav button{justify-content:center;padding:11px}
  .brand{justify-content:center;padding-bottom:14px}
  .chart-grid{grid-template-columns:1fr}
  .content{padding:20px 16px 50px}.topbar{padding:16px}
}
</style>
</head>
<body>

<!-- ── Sidebar ── -->
<aside class="sidebar">
  <div class="brand">
    <div class="logo">J</div>
    <div class="name">JobHunter<small>Admin Console</small></div>
  </div>
  <nav class="nav" id="nav">
    <button data-tab="dashboard" class="active">__I_grid__<span>Dashboard</span></button>
    <button data-tab="runs">__I_play__<span>Runs</span></button>
    <button data-tab="jobs">__I_brief__<span>Jobs</span></button>
    <button data-tab="users">__I_users__<span>Users</span></button>
    <div class="sep">Insights</div>
    <button data-tab="analytics">__I_chart__<span>Analytics</span></button>
    <button data-tab="diagnostics">__I_pulse__<span>Diagnostics</span></button>
    <div class="sep">System</div>
    <button data-tab="settings">__I_cog__<span>Settings</span></button>
  </nav>
  <div class="side-foot"><span class="pulse"></span>Live · <span id="sideTime">—</span></div>
</aside>

<!-- ── Main ── -->
<div class="main">
  <header class="topbar">
    <div>
      <h1 id="pageTitle">Dashboard</h1>
      <div class="crumb" id="pageCrumb">Operational overview</div>
    </div>
    <div class="right">
      <button class="btn ghost sm" onclick="refreshAll()">__I_refresh__ Refresh</button>
    </div>
  </header>

  <div class="content">

    <!-- ══ DASHBOARD ══ -->
    <section class="tab-page active" id="tab-dashboard">
      <div class="grid kpis" id="kpis"></div>

      <div class="section-h"><h2>System health</h2><span class="hint" id="healthSummary">checking…</span></div>
      <div class="grid health-grid" id="healthMini"></div>

      <div class="section-h"><h2>Quick actions</h2></div>
      <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr))">
        <div class="card" style="display:flex;flex-direction:column;gap:12px">
          <div><strong style="font-size:14px">Run scraper</strong>
          <p style="font-size:12px;color:var(--text-dim);margin-top:4px">Sweep all tracked titles for fresh jobs.</p></div>
          <button class="btn" onclick="confirmAction('Run scraper now?','This kicks off a full scrape across every tracked title. It runs in the background.','/api/run-scraper','Scrape started')">__I_play__ Run scraper</button>
        </div>
        <div class="card" style="display:flex;flex-direction:column;gap:12px">
          <div><strong style="font-size:14px">Score &amp; email</strong>
          <p style="font-size:12px;color:var(--text-dim);margin-top:4px">Re-score matches and send daily digests.</p></div>
          <button class="btn ghost" onclick="confirmAction('Score &amp; email all users?','This scores matches for every user and sends their daily digest emails.','/api/score-and-email','Scoring started')">__I_mail__ Score &amp; email</button>
        </div>
      </div>
    </section>

    <!-- ══ RUNS ══ -->
    <section class="tab-page" id="tab-runs">
      <div class="section-h">
        <h2>Recent runs</h2>
        <div style="display:flex;gap:8px">
          <button class="btn sm" onclick="confirmAction('Run scraper now?','Kicks off a full background scrape.','/api/run-scraper','Scrape started')">__I_play__ Run scraper</button>
          <button class="btn ghost sm" onclick="confirmAction('Score &amp; email?','Scores matches and emails all users.','/api/score-and-email','Scoring started')">__I_mail__ Score &amp; email</button>
        </div>
      </div>
      <div class="tbl-wrap">
        <table>
          <thead><tr><th>Started</th><th>Status</th><th>Scraped</th><th>Saved</th><th>Duration</th><th></th></tr></thead>
          <tbody id="runsBody"></tbody>
        </table>
      </div>
    </section>

    <!-- ══ JOBS ══ -->
    <section class="tab-page" id="tab-jobs">
      <div class="grid kpis" id="jobsKpis" style="margin-bottom:18px"></div>
      <div class="tbl-wrap">
        <div class="empty">
          <div class="eico">__I_brief__</div>
          <h3>Job browser coming soon</h3>
          <p>There's no read API for individual job records yet. The pool size above is live from <span class="mono" style="font-family:'JetBrains Mono',monospace">/api/analytics</span>. Add a <span class="mono" style="font-family:'JetBrains Mono',monospace">/api/jobs</span> endpoint to list and filter postings here.</p>
        </div>
      </div>
    </section>

    <!-- ══ USERS ══ -->
    <section class="tab-page" id="tab-users">
      <div class="grid kpis" id="usersKpis" style="margin-bottom:18px"></div>
      <div class="tbl-wrap">
        <div class="empty">
          <div class="eico">__I_users__</div>
          <h3>User directory coming soon</h3>
          <p>No list endpoint for users exists yet — only aggregate counts via <span class="mono" style="font-family:'JetBrains Mono',monospace">/api/analytics</span>. Add a <span class="mono" style="font-family:'JetBrains Mono',monospace">/api/users</span> endpoint to manage accounts from here.</p>
        </div>
      </div>
    </section>

    <!-- ══ ANALYTICS ══ -->
    <section class="tab-page" id="tab-analytics">
      <div class="grid chart-grid">
        <div class="card chart-box">
          <h3>Conversion funnel</h3>
          <div class="sub">Jobs in pool → qualified matches → applied</div>
          <div class="chart-canvas"><canvas id="funnelChart"></canvas></div>
        </div>
        <div class="card chart-box">
          <h3>Match outcomes</h3>
          <div class="sub">Distribution across statuses</div>
          <div class="chart-canvas"><canvas id="outcomeChart"></canvas></div>
        </div>
      </div>
      <div class="section-h"><h2>Scrape volume</h2><span class="hint">Jobs scraped vs saved per recent run</span></div>
      <div class="card chart-box">
        <div class="chart-canvas"><canvas id="volumeChart"></canvas></div>
      </div>
    </section>

    <!-- ══ DIAGNOSTICS ══ -->
    <section class="tab-page" id="tab-diagnostics">
      <div class="section-h">
        <h2>Service health</h2>
        <button class="btn ghost sm" onclick="runSelfTest()">__I_pulse__ Run self-test</button>
      </div>
      <div class="grid health-grid" id="healthFull"></div>

      <div class="section-h"><h2>DataForSEO credit</h2></div>
      <div class="grid kpis" id="creditBox"></div>
    </section>

    <!-- ══ SETTINGS ══ -->
    <section class="tab-page" id="tab-settings">
      <div class="card" style="max-width:680px">
        <div class="set-row">
          <div class="info"><h4>Auto-refresh interval</h4><p>How often the dashboard re-polls the APIs.</p></div>
          <select id="refreshSel" onchange="setInterval2(this.value)">
            <option value="0">Off</option>
            <option value="15000">15 seconds</option>
            <option value="30000" selected>30 seconds</option>
            <option value="60000">60 seconds</option>
          </select>
        </div>
        <div class="set-row">
          <div class="info"><h4>API base</h4><p>All calls are same-origin against this deployment.</p></div>
          <span class="mono" style="font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--text-dim)" id="apiBase">—</span>
        </div>
        <div class="set-row">
          <div class="info"><h4>Force full reload</h4><p>Clear cached state and re-fetch everything.</p></div>
          <button class="btn ghost sm" onclick="location.reload()">__I_refresh__ Reload</button>
        </div>
      </div>
      <div class="card" style="max-width:680px;margin-top:14px">
        <h4 style="font-size:13.5px;font-weight:600;margin-bottom:10px">Endpoints in use</h4>
        <div style="font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--text-dim);line-height:2">
          <div>GET&nbsp;&nbsp;/api/analytics</div>
          <div>GET&nbsp;&nbsp;/api/system-health</div>
          <div>GET&nbsp;&nbsp;/api/logs · /api/logs/&lt;id&gt;</div>
          <div>POST /api/run-scraper · /api/score-and-email</div>
        </div>
      </div>
    </section>

  </div>
</div>

<!-- ── Drawer ── -->
<div class="scrim" id="scrim" onclick="closeDrawer()"></div>
<aside class="drawer" id="drawer">
  <div class="dh">
    <div><h3 id="drawerTitle">Run log</h3><div class="meta" id="drawerMeta"></div></div>
    <button class="xb" onclick="closeDrawer()">__I_x__</button>
  </div>
  <div class="dbody">
    <div class="dstats" id="drawerStats"></div>
    <div class="logpre" id="drawerLog">Loading…</div>
  </div>
</aside>

<!-- ── Confirm modal ── -->
<div class="modal" id="modal">
  <div class="box">
    <h3 id="modalTitle">Are you sure?</h3>
    <p id="modalBody"></p>
    <div class="acts">
      <button class="btn ghost sm" onclick="closeModal()">Cancel</button>
      <button class="btn sm" id="modalOk">Confirm</button>
    </div>
  </div>
</div>

<div id="toasts"></div>

<script>
/* ── Icons (injected as placeholders to avoid brace clashes) ── */
const ICONS={
  grid:'<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>',
  play:'<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><polygon points="6 4 20 12 6 20 6 4"/></svg>',
  brief:'<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>',
  users:'<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
  chart:'<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>',
  pulse:'<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>',
  cog:'<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
  refresh:'<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>',
  mail:'<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 5L2 7"/></svg>',
  x:'<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
};
// KPI icon set
const KI={users:'users',jobs:'brief',matches:'chart',applied:'pulse',titles:'grid',skipped:'x'};
document.body.innerHTML=document.body.innerHTML.replace(/__I_(\w+)__/g,(_,k)=>ICONS[k]||'');

const $=s=>document.querySelector(s);
const $$=s=>document.querySelectorAll(s);
let state={analytics:null,health:null,logs:null};
let pollTimer=null,pollMs=30000;
let charts={};

/* ── Toast ── */
function toast(msg,kind){
  const t=document.createElement('div');t.className='toast '+(kind||'info');
  t.innerHTML='<span class="ti"></span><span>'+msg+'</span>';
  $('#toasts').appendChild(t);
  setTimeout(()=>{t.style.opacity='0';t.style.transform='translateX(40px)';t.style.transition='.3s';
    setTimeout(()=>t.remove(),320)},3200);
}

/* ── Fetch helpers ── */
async function getJSON(u){const r=await fetch(u);if(!r.ok)throw new Error('HTTP '+r.status);return r.json();}
async function postJSON(u){const r=await fetch(u,{method:'POST'});if(!r.ok)throw new Error('HTTP '+r.status);return r.json();}

/* ── Tabs ── */
const TITLES={dashboard:['Dashboard','Operational overview'],runs:['Runs','Scrape & scoring history'],
  jobs:['Jobs','Job pool'],users:['Users','Account base'],analytics:['Analytics','Trends & conversion'],
  diagnostics:['Diagnostics','Service health & credits'],settings:['Settings','Dashboard configuration']};
function switchTab(name){
  $$('.nav button').forEach(b=>b.classList.toggle('active',b.dataset.tab===name));
  $$('.tab-page').forEach(p=>p.classList.toggle('active',p.id==='tab-'+name));
  $('#pageTitle').textContent=TITLES[name][0];
  $('#pageCrumb').textContent=TITLES[name][1];
  if(name==='analytics')drawCharts();
  location.hash=name;
}
$('#nav').addEventListener('click',e=>{const b=e.target.closest('button[data-tab]');if(b)switchTab(b.dataset.tab);});

/* ── Renderers ── */
function kpiCard(icon,val,lbl,delta){
  return '<div class="card kpi"><div class="top"><div class="ico">'+(ICONS[icon]||'')+'</div></div>'+
    '<div class="val">'+val+'</div><div class="lbl">'+lbl+'</div>'+
    (delta?'<div class="delta">'+delta+'</div>':'')+'</div>';
}
function skeletonKpis(n){let h='';for(let i=0;i<n;i++)h+='<div class="card kpi"><div class="sk" style="height:36px;width:36px;border-radius:10px;margin-bottom:14px"></div><div class="sk" style="height:30px;width:70%;margin-bottom:10px"></div><div class="sk" style="height:12px;width:50%"></div></div>';return h;}

function renderKpis(){
  const d=state.analytics;if(!d)return;
  $('#kpis').innerHTML=
    kpiCard('users',fmt(d.users),'Total users')+
    kpiCard('brief',fmt(d.jobs_in_pool),'Jobs in pool')+
    kpiCard('chart',fmt(d.matches_60plus),'Matches ≥ 60')+
    kpiCard('pulse',fmt(d.applied_total),'Applications',fmt(d.skipped_total)+' skipped');
  $('#jobsKpis').innerHTML=
    kpiCard('brief',fmt(d.jobs_in_pool),'Jobs in pool')+
    kpiCard('grid',fmt(d.titles),'Tracked titles')+
    kpiCard('chart',fmt(d.matches_60plus),'Qualified matches');
  $('#usersKpis').innerHTML=
    kpiCard('users',fmt(d.users),'Total users')+
    kpiCard('pulse',fmt(d.applied_total),'Total applications')+
    kpiCard('x',fmt(d.skipped_total),'Total skipped');
}
function fmt(n){return (n==null)?'—':Number(n).toLocaleString();}

function healthCardHTML(name,v){
  const ok=v&&v.ok;
  return '<div class="card hcard"><span class="dot '+(ok?'g':'r')+'"></span><div style="min-width:0">'+
    '<div class="hname">'+name+'</div><div class="hmsg">'+((v&&v.msg)||(ok?'ok':'unavailable'))+'</div></div></div>';
}
function renderHealth(){
  const d=state.health;if(!d)return;
  const entries=Object.entries(d).filter(([k,v])=>v&&typeof v==='object'&&'ok'in v);
  const html=entries.map(([k,v])=>healthCardHTML(k,v)).join('');
  $('#healthFull').innerHTML=html;
  $('#healthMini').innerHTML=html;
  const okN=entries.filter(([k,v])=>v.ok).length;
  const total=entries.length;
  const all=d.all_ok;
  $('#healthSummary').innerHTML='<span class="badge '+(all?'g':(okN>0?'a':'r'))+'">'+okN+'/'+total+' healthy</span>';
  renderCredit();
}
function renderCredit(){
  const d=state.health;if(!d||!d.dataforseo){return;}
  const bal=parseBalance(d.dataforseo.msg);
  const disp=(bal==null)?'—':'$'+parseFloat(bal).toFixed(4);
  const ok=d.dataforseo.ok;
  $('#creditBox').innerHTML=
    kpiCard('pulse',disp,'DataForSEO balance',ok?'connected':'check key')+
    '<div class="card kpi"><div class="top"><div class="ico">'+ICONS.brief+'</div></div>'+
    '<div class="val"><span class="badge '+(ok?'g':'r')+'">'+(ok?'online':'offline')+'</span></div>'+
    '<div class="lbl">Provider status</div></div>';
}
// "balance $0.2734" -> "0.2734"
function parseBalance(msg){if(!msg)return null;const m=String(msg).match(/-?\d+(\.\d+)?/);return m?m[0]:null;}

function renderRuns(){
  const rows=state.logs;if(!rows)return;
  if(!rows.length){$('#runsBody').innerHTML='<tr><td colspan="6"><div class="empty"><h3>No runs yet</h3><p>Trigger a scrape to see history here.</p></div></td></tr>';return;}
  $('#runsBody').innerHTML=rows.map(r=>{
    const dur=duration(r.started_at,r.finished_at);
    return '<tr><td><span class="mono">'+ts(r.started_at)+'</span></td>'+
      '<td><span class="st st-'+r.status+'">'+(r.status||'—')+'</span></td>'+
      '<td>'+(r.total_scraped??0)+'</td><td>'+(r.total_saved??0)+'</td>'+
      '<td>'+dur+'</td>'+
      '<td style="text-align:right"><button class="btn ghost sm" onclick="openLog(\''+r.id+'\')">View log</button></td></tr>';
  }).join('');
}
function ts(s){if(!s)return '—';return String(s).slice(0,16).replace('T',' ');}
function duration(a,b){if(!a||!b)return '—';const d=(new Date(b)-new Date(a))/1000;if(isNaN(d)||d<0)return '—';
  if(d<60)return Math.round(d)+'s';return Math.floor(d/60)+'m '+Math.round(d%60)+'s';}

/* ── Charts ── */
function chartOpts(extra){return Object.assign({responsive:true,maintainAspectRatio:false,
  plugins:{legend:{labels:{color:'#9398A6',font:{family:'Inter',size:12},boxWidth:12,padding:14}}},
  scales:{x:{ticks:{color:'#5C6070',font:{family:'Inter',size:11}},grid:{color:'#1A1C24'}},
          y:{ticks:{color:'#5C6070',font:{family:'Inter',size:11}},grid:{color:'#1A1C24'}}}},extra||{});}
function drawCharts(){
  if(!state.analytics)return;
  const d=state.analytics;
  // Funnel
  mkChart('funnelChart','bar',{
    labels:['Jobs in pool','Matches ≥60','Applied'],
    datasets:[{label:'Count',data:[d.jobs_in_pool||0,d.matches_60plus||0,d.applied_total||0],
      backgroundColor:['#7C3AED','#9F67FF','#22C55E'],borderRadius:8,barThickness:54}]
  },chartOpts({plugins:{legend:{display:false}}}));
  // Outcomes donut
  const newish=Math.max(0,(d.matches_60plus||0)-(d.applied_total||0)-(d.skipped_total||0));
  mkChart('outcomeChart','doughnut',{
    labels:['Active','Applied','Skipped'],
    datasets:[{data:[newish,d.applied_total||0,d.skipped_total||0],
      backgroundColor:['#7C3AED','#22C55E','#5C6070'],borderColor:'#13151E',borderWidth:3}]
  },{responsive:true,maintainAspectRatio:false,cutout:'62%',
    plugins:{legend:{position:'bottom',labels:{color:'#9398A6',font:{family:'Inter',size:12},boxWidth:12,padding:14}}}});
  // Volume (from logs, chronological)
  const logs=(state.logs||[]).slice().reverse();
  mkChart('volumeChart','line',{
    labels:logs.map(r=>ts(r.started_at).slice(5)),
    datasets:[
      {label:'Scraped',data:logs.map(r=>r.total_scraped||0),borderColor:'#7C3AED',backgroundColor:'rgba(124,58,237,.15)',fill:true,tension:.35,pointRadius:3},
      {label:'Saved',data:logs.map(r=>r.total_saved||0),borderColor:'#22C55E',backgroundColor:'rgba(34,197,94,.12)',fill:true,tension:.35,pointRadius:3}
    ]
  },chartOpts({}));
}
function mkChart(id,type,data,opts){
  const el=document.getElementById(id);if(!el)return;
  if(charts[id])charts[id].destroy();
  charts[id]=new Chart(el,{type,data,options:opts});
}

/* ── Drawer (log viewer) ── */
async function openLog(id){
  $('#scrim').classList.add('show');$('#drawer').classList.add('show');
  $('#drawerLog').textContent='Loading…';$('#drawerStats').innerHTML='';
  try{
    const d=await getJSON('/api/logs/'+id);
    $('#drawerTitle').textContent='Run '+String(id).slice(0,8);
    $('#drawerMeta').textContent=ts(d.started_at)+'  →  '+(d.finished_at?ts(d.finished_at):'running');
    $('#drawerStats').innerHTML=
      dstat(d.status,'Status','st-'+d.status)+
      dstat(d.total_scraped??0,'Scraped')+
      dstat(d.total_saved??0,'Saved')+
      dstat(duration(d.started_at,d.finished_at),'Duration');
    $('#drawerLog').textContent=d.log_text||(d.error?('ERROR: '+d.error):'(no log output)');
  }catch(e){$('#drawerLog').textContent='Failed to load log: '+e.message;toast('Could not load log','err');}
}
function dstat(v,l,cls){return '<div class="dstat"><div class="v '+(cls||'')+'">'+v+'</div><div class="l">'+l+'</div></div>';}
function closeDrawer(){$('#scrim').classList.remove('show');$('#drawer').classList.remove('show');}

/* ── Confirm modal ── */
let pendingAction=null;
function confirmAction(title,body,url,okMsg){
  $('#modalTitle').innerHTML=title;$('#modalBody').innerHTML=body;
  pendingAction={url,okMsg};$('#modal').classList.add('show');
}
function closeModal(){$('#modal').classList.remove('show');pendingAction=null;}
$('#modalOk').addEventListener('click',async()=>{
  if(!pendingAction)return;const{url,okMsg}=pendingAction;closeModal();
  try{await postJSON(url);toast(okMsg,'ok');setTimeout(loadLogs,2200);}
  catch(e){toast('Failed: '+e.message,'err');}
});

/* ── Self-test ── */
async function runSelfTest(){
  toast('Running self-test…','info');
  try{state.health=await getJSON('/api/system-health');renderHealth();toast('Self-test complete','ok');}
  catch(e){toast('Self-test failed: '+e.message,'err');}
}

/* ── Loaders ── */
async function loadAnalytics(){try{state.analytics=await getJSON('/api/analytics');renderKpis();if($('#tab-analytics').classList.contains('active'))drawCharts();}catch(e){toast('Analytics failed','err');}}
async function loadHealth(){try{state.health=await getJSON('/api/system-health');renderHealth();}catch(e){toast('Health check failed','err');}}
async function loadLogs(){try{state.logs=await getJSON('/api/logs');renderRuns();if($('#tab-analytics').classList.contains('active'))drawCharts();}catch(e){toast('Logs failed','err');}}
function stamp(){const t=new Date().toLocaleTimeString();$('#sideTime').textContent=t;}
async function refreshAll(){stamp();await Promise.all([loadAnalytics(),loadHealth(),loadLogs()]);}

/* ── Auto-refresh ── */
function setInterval2(ms){pollMs=+ms;if(pollTimer)clearInterval(pollTimer);if(pollMs>0)pollTimer=setInterval(refreshAll,pollMs);}

/* ── Init ── */
$('#kpis').innerHTML=skeletonKpis(4);
$('#apiBase').textContent=location.origin;
const hash=(location.hash||'').replace('#','');
if(hash&&TITLES[hash])switchTab(hash);
refreshAll();
setInterval2(30000);
document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeDrawer();closeModal();}});
</script>
</body>
</html>"""
