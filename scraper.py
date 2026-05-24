#!/usr/bin/env python3
"""
Job Hunter Scraper v4 — Render Edition (Monthly Full Sweep)
- 16 job titles × 5 trusted sites = 80 SerpAPI searches
- Last 7 days listings only
- No quantity cap — takes all results in the time window
- Trusted source filter: LinkedIn, Bayt, Indeed, Naukrigulf, GulfTalent only
- Claude Haiku + prompt caching for cost efficiency
"""

import os
import re
import json
import time
import threading
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests

# ── Config ────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "")
SHEET_ID          = os.environ.get("SHEET_ID", "")
SERPAPI_KEY       = os.environ.get("SERPAPI_KEY", "")
SHEET_NAME        = "Sheet1"
TODAY             = date.today().strftime("%Y-%m-%d")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── Trusted platforms ─────────────────────────────────────────────────────
TRUSTED_DOMAINS = [
    "linkedin.com",
    "bayt.com",
    "indeed.com",
    "naukrigulf.com",
    "gulftalent.com",
]

TRUSTED_VIA = [
    "linkedin", "bayt", "indeed", "naukrigulf", "gulftalent",
]

# ── 16 target job titles ──────────────────────────────────────────────────
SEARCH_QUERIES = [
    ("regional manager",            "regional manager UAE"),
    ("area manager",                "area manager UAE"),
    ("district manager",            "district manager retail UAE"),
    ("cluster manager",             "cluster manager UAE"),
    ("operations manager",          "operations manager retail UAE"),
    ("pharmacy manager",            "pharmacy manager UAE"),
    ("pharmacist in charge",        "pharmacist in charge UAE"),
    ("retail manager",              "retail manager UAE"),
    ("ecommerce manager",           "ecommerce manager UAE"),
    ("digital commerce manager",    "digital commerce manager UAE"),
    ("marketplace manager",         "marketplace manager UAE"),
    ("omnichannel manager",         "omnichannel manager UAE"),
    ("division manager",            "division manager retail UAE"),
    ("supply chain manager",        "supply chain manager retail UAE"),
    ("business development manager","business development manager pharmacy UAE"),
    ("general manager retail",      "general manager retail pharmacy UAE"),
]

TRUSTED_SITES = [
    ("LinkedIn",   "linkedin.com"),
    ("Bayt",       "bayt.com"),
    ("Indeed",     "indeed.com"),
    ("Naukrigulf", "naukrigulf.com"),
    ("GulfTalent", "gulftalent.com"),
]

# ── Junk title filter ─────────────────────────────────────────────────────
JUNK_PATTERNS = [
    re.compile(r"jobs in (uae|dubai|abu dhabi|sharjah).*(20\d\d)", re.I),
    re.compile(r"\d+\+?\s+(jobs|vacancies)", re.I),
    re.compile(r"employment\s+\d+\s+\w+\s+20\d\d", re.I),
    re.compile(r"'s post", re.I),
    re.compile(r"jobs?,\s+employment", re.I),
    re.compile(r"careers?\s*&\s*jobs", re.I),
    re.compile(r"may 20\d\d\)$", re.I),
    re.compile(r"^\d+\s+(jobs|vacancies)\s*$", re.I),
]

def is_junk(title):
    return any(p.search(title) for p in JUNK_PATTERNS)

# ── Skip / block keywords ─────────────────────────────────────────────────
SKIP_KEYWORDS = [
    "UAEN", "UAE NATIONAL", "EMIRATI", "NATIONAL ONLY",
    "FEMALE ONLY", "FEMALES ONLY", "HINDI SPEAKING", "URDU SPEAKING",
]

HARD_BLOCK = [
    "aluminium", "aluminum", "glazing", "facade", "fabrication",
    "aquatic", "swimming", "swim", "lifeguard",
    "restaurant manager", "chef", "culinary", "f&b manager",
    "civil engineer", "mechanical engineer", "electrical engineer",
    "construction manager", "contracting", "fitout",
    "software engineer", "developer", "programmer", "devops",
    "investment banker", "wealth manager", "hedge fund",
    "nurse manager", "doctor", "physician", "surgeon", "dentist",
    "marine lubricant", "ship management", "maritime",
    "real estate broker", "property consultant",
    "hair stylist", "salon stylist",
]

PARTIAL_FIT = [
    "3pl manager", "third party logistics", "warehouse manager",
    "distribution center manager", "dc manager",
]

def is_skip(title):
    return any(kw in title.upper() for kw in SKIP_KEYWORDS)

def pre_screen(title, company=""):
    text = (title + " " + company).lower()
    for kw in HARD_BLOCK:
        if kw in text:
            return "block", f"Hard disqualifier: '{kw}'"
    for kw in PARTIAL_FIT:
        if kw in text:
            return "flag", f"Partial fit: '{kw}'"
    return "ok", ""

# ── Candidate resume ──────────────────────────────────────────────────────
MY_RESUME = """
CANDIDATE: Mohammed Alsheraery
NATIONALITY: Egyptian (not UAE National)
LOCATION: Dubai, UAE
LANGUAGES: Arabic (Native), English (Professional)
UAE DRIVING LICENCE: Yes — own vehicle

TARGET SENIORITY: Management roles only.
HARD DISQUALIFIERS REGARDLESS OF INDUSTRY:
- Staff pharmacist, pharmacy technician, junior pharmacist, trainee
- Coordinator, executive, specialist, assistant level roles
- Any role requiring less than 5 years experience

QUALIFICATIONS:
- Bachelor of Pharmacy — Misr University, Cairo, 2011
- DHA Licensed Pharmacist — Dubai Health Authority (active)
- LinkedIn Learning: Power BI, Lean Six Sigma, Operational Excellence

INDUSTRIES WITH GENUINE EXPERIENCE:
- Pharmacy / Healthcare Retail (14 years — primary)
- Multi-branch Retail (FMCG, health, wellness, supplements)
- E-Commerce / Marketplace (Amazon, Noon, Talabat, Instashop, Carrefour, Sharaf DG)
- Omnichannel / Last-mile delivery operations
- Supply chain oversight (inventory, procurement, vendor — NOT warehouse floor)

HARD DISQUALIFIER INDUSTRIES:
- Construction, fabrication, aluminium, glazing, facade
- Aquatics, sports, swimming
- Hospitality, F&B, hotel operations
- Engineering, IT, software
- Finance, banking, investment
- Pure warehouse / DC floor management
- Manufacturing, heavy industry
- Automotive, marine, aerospace

EXPERIENCE:
1. Regional Manager — 800 Pharmacy & Marina Pharmacy Group (Jul 2025–Mar 2026)
   30+ branches Dubai/Abu Dhabi/Sharjah | 2 Cluster Managers | 19% YOY growth |
   94.6% of highest-ever target | Full P&L, compliance, staffing, KPI

2. Division Manager — 800 Pharmacy & Marina Pharmacy Group (Mar–Jul 2025)
   Delivery division | Amazon, Noon, Talabat, Instashop oversight

3. Branch Manager A-Class — Life Pharmacy, Dubai & Abu Dhabi (Dec 2021–Mar 2025)
   1,200+ 5-star reviews | 20% revenue uplift | DHA/DOH/MOH compliance | P&L

4. Omnichannel Manager & Store Manager — United Pharmacy Group (Nov 2014–Jul 2023)
   Built e-commerce across 6 UAE platforms | Quadrupled online sales in 6 months |
   100% YOY growth at Galleria Mall | Best Employee & Store Manager 2015

KEY SKILLS: Multi-branch ops, P&L, omnichannel, e-commerce platform management,
DHA/MOH/DOH compliance, team leadership, FEFO inventory, SOP, KPI/Power BI,
customer retention, B2B portal, call centre, delivery logistics, supplier negotiation
"""

# ── Claude scoring with prompt caching ───────────────────────────────────
CACHED_SYSTEM = (
    "You are a strict recruitment screener for a UAE job seeker. Evaluate honestly.\n\n"
    "CANDIDATE:\n" + MY_RESUME + "\n\n"
    "SCORING RULES — apply strictly:\n\n"
    "HARD DISQUALIFIERS → score 0-15, apply: false, flag: 'hard_block'\n"
    "- Staff pharmacist, technician, junior, coordinator, assistant → max 15\n"
    "- Wrong industry: construction, fabrication, glazing, aquatics, engineering,\n"
    "  hospitality/F&B, manufacturing, warehouse floor, finance, automotive, maritime\n"
    "- UAE Nationals / Emiratis / gender restricted\n"
    "- Requires <5 years experience → max 20\n\n"
    "PARTIAL FIT → score 35-55, apply: false, flag: '3pl_partial'\n"
    "- Primary requirement is 3PL/DC warehouse floor management\n\n"
    "GOOD FIT → score 56-74, apply: true, flag: 'none'\n"
    "- Matches industry and function with minor gaps\n\n"
    "STRONG FIT → score 75-89, apply: true, flag: 'none'\n"
    "- Closely matches experience, industry, seniority\n\n"
    "EXCEPTIONAL → score 90-100, apply: true, flag: 'none'\n"
    "- Precisely aligned: pharmacy/retail management, UAE, senior level\n\n"
    "Read the full description before scoring. A pharmacist staff role scores max 15\n"
    "even if the industry matches. A brand agency ecommerce role scores low despite title.\n\n"
    'Reply ONLY as JSON (no other text):\n'
    '{"score":<0-100>,"apply":<true/false>,"reason":"<one sentence>",'
    '"industry":"<industry>","flag":"<none|junior|overqualified|3pl_partial|hard_block>"}'
)


def match_job(title, company, location="", description="", date_listed=""):
    status, reason = pre_screen(title, company)
    if status == "block":
        return 0, False, reason, "Disqualified", "hard_block"

    job_content = (
        f"Title: {title}\n"
        f"Company: {company}\n"
        f"Location: {location or 'UAE'}\n"
        f"Date Listed: {date_listed or 'Recent'}\n"
        f"Description: {description[:1500] if description else 'Not provided'}"
    )

    for attempt in range(5):
        try:
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                system=[{
                    "type":          "text",
                    "text":          CACHED_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": job_content}],
            )
            raw  = re.sub(r"```json|```", "", msg.content[0].text).strip()
            data = json.loads(raw)

            score    = int(data.get("score", 0))
            apply    = bool(data.get("apply", False))
            reason   = str(data.get("reason", ""))
            industry = str(data.get("industry", "General"))
            flag     = str(data.get("flag", "none"))

            if flag == "3pl_partial": score = min(score, 55); apply = False
            if flag == "hard_block":  score = min(score, 15); apply = False

            return score, apply, reason, industry, flag

        except anthropic.RateLimitError:
            wait = 2 * (2 ** attempt)
            if attempt < 4:
                time.sleep(wait)
            else:
                return 0, False, "Rate limit exceeded", "Unknown", "none"
        except (json.JSONDecodeError, KeyError) as e:
            return 0, False, f"Parse error: {e}", "Unknown", "none"
        except Exception as e:
            return 0, False, str(e), "Unknown", "none"


# ── SerpAPI fetch ─────────────────────────────────────────────────────────
def fetch_jobs(query_label, search_query, site_name, site_domain, seen_set):
    """
    Fetches jobs for one title + one site combination.
    Uses google_jobs engine with 7-day window, no quantity cap.
    Only keeps jobs with trusted source link.
    """
    jobs = []

    if not SERPAPI_KEY:
        print(f"  ❌ SERPAPI_KEY not set")
        return jobs

    try:
        params = {
            "engine":   "google_jobs",
            "q":        search_query,          # Clean query — no site: filter (not supported by google_jobs)
            "location": "United Arab Emirates",
            "gl":       "ae",
            "hl":       "en",
            "chips":    "date_posted:week",   # Last 7 days
            "api_key":  SERPAPI_KEY,
            # No 'num' param — get all results in the time window
        }

        response = requests.get(
            "https://serpapi.com/search",
            params=params,
            timeout=30,
        )

        if response.status_code != 200:
            print(f"    ⚠ {response.status_code} — {query_label} [{site_name}]")
            return jobs

        data = response.json()

        if "error" in data:
            # No results for this query/site combo — normal, not an error
            return jobs

        job_results = data.get("jobs_results", [])
        if not job_results:
            return jobs

        for job_data in job_results:
            title   = job_data.get("title", "").strip()
            company = job_data.get("company_name", "Unknown").strip()

            if is_junk(title) or len(title) < 5 or is_skip(title):
                continue

            # Find trusted link from apply_options
            apply_options    = job_data.get("apply_options", [])
            trusted_link     = ""
            trusted_platform = site_name

            for opt in apply_options:
                opt_link = opt.get("link", "")
                if any(d in opt_link for d in TRUSTED_DOMAINS):
                    trusted_link     = opt_link
                    trusted_platform = opt.get("title", site_name)
                    break

            # Fallback to via field + share link
            if not trusted_link:
                via = job_data.get("via", "").lower()
                if any(tv in via for tv in TRUSTED_VIA):
                    trusted_link     = job_data.get("share_link", "")
                    trusted_platform = job_data.get("via", site_name)

            if not trusted_link:
                continue

            ext         = job_data.get("detected_extensions", {})
            location    = job_data.get("location", "UAE") or ext.get("location", "UAE")
            date_listed = ext.get("posted_at", "Recent")
            description = job_data.get("description", "")
            key         = f"{company.lower()}_{title.lower()}"

            jobs.append({
                "title":       title,
                "company":     company,
                "location":    location,
                "date_listed": date_listed,
                "link":        trusted_link,
                "platform":    trusted_platform,
                "description": description[:1500],
                "seen_before": key in seen_set,
                "query":       query_label,
            })

    except Exception as e:
        print(f"    ❌ Error — {query_label} [{site_name}]: {e}")

    return jobs


# ── Google Sheets ─────────────────────────────────────────────────────────
def get_creds():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if creds_json:
        return ServiceAccountCredentials.from_json_keyfile_dict(
            json.loads(creds_json), scope)
    return ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)

def get_sheet():
    return gspread.authorize(get_creds()).open_by_key(SHEET_ID).worksheet(SHEET_NAME)

def load_seen_before():
    seen = set()
    try:
        rows = get_sheet().get_all_values()
        if len(rows) < 2:
            return seen
        headers = [h.strip().lower() for h in rows[0]]
        def col(*names):
            for n in names:
                try: return headers.index(n.lower())
                except ValueError: pass
            return None
        ct = col("job title", "title")
        cc = col("company")
        for row in rows[1:]:
            def cell(i):
                return row[i].strip() if i is not None and i < len(row) else ""
            if cell(ct) and cell(cc):
                seen.add(f"{cell(cc).lower()}_{cell(ct).lower()}")
    except Exception as e:
        print(f"load_seen_before error: {e}")
    return seen

def save_jobs_to_sheet(jobs):
    try:
        sheet    = get_sheet()
        existing = sheet.get_all_values()
        headers  = [
            "Date Found", "Score", "Company", "Job Title",
            "Location", "Date Listed", "Platform",
            "Industry", "Match Reason", "Flag",
            "Seen Before", "Link", "Status"
        ]
        if not existing or existing[0] != headers:
            if not existing: sheet.append_row(headers)
            else:            sheet.insert_row(headers, 1)

        rows = []
        for j in jobs:
            rows.append([
                TODAY, f"{j.get('score',0)}%",
                j.get("company",""), j.get("title",""),
                j.get("location","UAE"), j.get("date_listed","Recent"),
                j.get("platform","Google Jobs"), j.get("industry","General"),
                j.get("reason",""), j.get("flag","none"),
                "👀 Seen" if j.get("seen_before") else "🆕 New",
                j.get("link",""), "New",
            ])
        if rows:
            sheet.append_rows(rows, value_input_option="USER_ENTERED")
        return len(rows)
    except Exception as e:
        print(f"save_jobs_to_sheet error: {e}")
        return 0


# ── Telegram ──────────────────────────────────────────────────────────────
def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10,
        )
    except Exception as e:
        print(f"Telegram error: {e}")

def send_telegram_results(matched):
    if not matched:
        send_telegram(f"🔍 Job Hunter — {TODAY}\n\n❌ No matching jobs found.")
        return

    new  = [j for j in matched if not j.get("seen_before")]
    seen = [j for j in matched if j.get("seen_before")]

    send_telegram(
        f"🎯 <b>JOB HUNTER — {TODAY}</b>\n"
        f"🆕 New: <b>{len(new)}</b> | 👀 Seen: <b>{len(seen)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )

    def fmt(i, j):
        s = j["score"]
        e = "🔥" if s >= 80 else "⭐" if s >= 70 else "✅"
        f = " ⚠️3PL" if j.get("flag") == "3pl_partial" else ""
        return (
            f"{e} <b>#{i} — {s}%</b>{f}\n"
            f"📋 {j['title']}\n🏢 {j['company']}\n"
            f"📍 {j.get('location','UAE')} | 📅 {j.get('date_listed','Recent')}\n"
            f"🏭 {j.get('industry','N/A')}\n💡 {j.get('reason','')}\n"
            f"🔗 <a href='{j['link']}'>Apply Now</a>"
        )

    for label, lst, start in [
        ("🆕 <b>NEW JOBS:</b>", new, 1),
        ("👀 <b>SEEN BEFORE:</b>", seen, len(new)+1),
    ]:
        if not lst: continue
        send_telegram(label)
        batch = []
        for i, j in enumerate(lst, start):
            batch.append(fmt(i, j))
            if len(batch) == 5 or i == start + len(lst) - 1:
                send_telegram("\n━━━━━━━━━━━━\n".join(batch))
                batch = []


# ── Parallel analysis ─────────────────────────────────────────────────────
def analyze_wrapper(job):
    try:
        score, apply_flag, reason, industry, flag = match_job(
            job["title"], job["company"],
            job.get("location","UAE"),
            job.get("description",""),
            job.get("date_listed",""),
        )
        job.update({"score": score, "reason": reason,
                    "industry": industry, "flag": flag})
        return job, apply_flag
    except Exception as e:
        job.update({"score": 0, "reason": str(e),
                    "industry": "Unknown", "flag": "none"})
        return job, False


# ── Main ──────────────────────────────────────────────────────────────────
def run(progress_callback=None):
    def progress(step, pct):
        print(f"[{pct}%] {step}")
        if progress_callback:
            progress_callback(step, pct)

    total_searches = len(SEARCH_QUERIES)

    progress(f"🚀 Job Hunter — Monthly Full Sweep ({total_searches} searches)", 2)
    send_telegram(
        f"🚀 Job Hunter Monthly Sweep — {TODAY}\n"
        f"🔍 {total_searches} role searches | Trusted sources only\n"
        f"📅 Last 7 days"
    )

    progress("📂 Loading seen jobs...", 3)
    seen_set  = load_seen_before()
    all_jobs  = []
    seen_keys = set()
    total_q   = len(SEARCH_QUERIES)

    for i, (query_label, search_query) in enumerate(SEARCH_QUERIES):
        pct = 3 + int(((i) / total_q) * 47)
        progress(f"🔍 {query_label}", pct)

        # Use first trusted site name as label — filtering happens on results
        jobs = fetch_jobs(query_label, search_query, "Google Jobs", "", seen_set)

        new_count = 0
        for job in jobs:
            key = f"{job['title'].lower()}_{job['company'].lower()}"
            if key not in seen_keys and len(job["title"]) >= 5:
                seen_keys.add(key)
                all_jobs.append(job)
                new_count += 1

        if new_count:
            print(f"    ✅ {new_count} unique jobs added")

        time.sleep(0.5)

    progress(f"📊 {len(all_jobs)} unique jobs — scoring with AI...", 52)

    if not all_jobs:
        progress("⚠️ No trusted jobs found.", 100)
        send_telegram("⚠️ No trusted jobs found in this sweep.")
        return 0

    matched = []
    blocked = skipped = 0
    total   = len(all_jobs)

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(analyze_wrapper, job): job for job in all_jobs}
        done    = 0
        for future in as_completed(futures):
            done += 1
            pct  = 52 + int((done / total) * 38)
            job, apply_flag = future.result()
            flag  = job.get("flag", "none")
            score = job.get("score", 0)

            if is_skip(job["title"]):
                continue
            if flag == "hard_block":
                blocked += 1
                continue
            if apply_flag and score >= 50:
                matched.append(job)
                progress(f"✅ {job['title'][:40]} ({score}%)", pct)
            else:
                skipped += 1

    matched.sort(key=lambda x: (-x["score"], x.get("seen_before", False)))

    progress("💾 Saving to Google Sheets...", 92)
    saved = save_jobs_to_sheet(matched)

    progress("📱 Sending Telegram...", 96)
    send_telegram_results(matched)

    send_telegram(
        f"✅ <b>Monthly Sweep Complete — {TODAY}</b>\n"
        f"🔍 Searched: {total_searches} queries\n"
        f"📋 Scraped: {len(all_jobs)} unique jobs\n"
        f"🎯 Matched: {len(matched)}\n"
        f"⛔ Blocked: {blocked}\n"
        f"❌ Skipped: {skipped}\n"
        f"💾 Saved: {saved}"
    )

    progress(f"✅ Done! {len(matched)} jobs matched.", 100)

    print(f"\n{'='*50}")
    print(f"🔍 Searched:  {total_searches} queries")
    print(f"📋 Scraped:   {len(all_jobs)} unique jobs")
    print(f"✅ Matched:   {len(matched)}")
    print(f"⛔ Blocked:   {blocked}")
    print(f"❌ Skipped:   {skipped}")
    print(f"{'='*50}")

    return len(matched)


if __name__ == "__main__":
    run()
