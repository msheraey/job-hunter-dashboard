#!/usr/bin/env python3
"""
Job Hunter Scraper v3 — Server Edition
Runs on Render.com — no Chrome, no Playwright, no Mac dependencies
Uses httpx to fetch Google Jobs search results directly
"""

import os
import re
import json
import time
import random
import threading
from datetime import date, timedelta, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
import anthropic
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests

# ── Config ────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "8972917892:AAGs_Z6xWc67poi7EfVdJpPoJJb_3hs8sJo")
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "8872960522")
SHEET_ID          = os.environ.get("SHEET_ID", "")
SHEET_NAME        = "Sheet1"
TODAY             = date.today().strftime("%Y-%m-%d")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── Google Sheets ─────────────────────────────────────────────────────────
def get_creds():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if creds_json:
        return ServiceAccountCredentials.from_json_keyfile_dict(
            json.loads(creds_json), scope
        )
    return ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)


def get_sheet():
    client_gs = gspread.authorize(get_creds())
    return client_gs.open_by_key(SHEET_ID).worksheet(SHEET_NAME)


def load_seen_before():
    """Load previously seen job keys from Google Sheets to avoid duplicates."""
    seen = set()
    try:
        sheet = get_sheet()
        rows  = sheet.get_all_values()
        if len(rows) < 2:
            return seen
        headers = [h.strip().lower() for h in rows[0]]
        def col(*names):
            for n in names:
                try: return headers.index(n.lower())
                except ValueError: pass
            return None
        c_title   = col("job title", "title")
        c_company = col("company")
        for row in rows[1:]:
            def cell(idx):
                return row[idx].strip() if idx is not None and idx < len(row) else ""
            t = cell(c_title).lower()
            c = cell(c_company).lower()
            if t and c:
                seen.add(f"{c}_{t}")
    except Exception as e:
        print(f"load_seen_before error: {e}")
    return seen


def save_jobs_to_sheet(jobs):
    """Append matched jobs to Google Sheets."""
    try:
        sheet    = get_sheet()
        existing = sheet.get_all_values()
        # Ensure header row exists
        expected_headers = [
            "Date Found", "Score", "Company", "Job Title",
            "Location", "Date Listed", "Platform",
            "Industry", "Match Reason", "Flag",
            "Seen Before", "Link", "Status"
        ]
        if not existing or existing[0] != expected_headers:
            if not existing:
                sheet.append_row(expected_headers)
            else:
                sheet.insert_row(expected_headers, 1)

        rows_to_add = []
        for job in jobs:
            rows_to_add.append([
                TODAY,
                f"{job.get('score', 0)}%",
                job.get("company", ""),
                job.get("title", ""),
                job.get("location", "UAE"),
                job.get("date_listed", "Recent"),
                job.get("platform", "Google Jobs"),
                job.get("industry", "General"),
                job.get("reason", ""),
                job.get("flag", "none"),
                "👀 Seen" if job.get("seen_before") else "🆕 New",
                job.get("link", ""),
                "New",
            ])
        if rows_to_add:
            sheet.append_rows(rows_to_add, value_input_option="USER_ENTERED")
        return len(rows_to_add)
    except Exception as e:
        print(f"save_jobs_to_sheet error: {e}")
        return 0

# ── Candidate profile ─────────────────────────────────────────────────────
MY_RESUME = """
CANDIDATE: Mohammed Alsheraery
NATIONALITY: Egyptian (not UAE National)
LOCATION: Dubai, UAE
LANGUAGES: Arabic (Native), English (Professional)
UAE DRIVING LICENCE: Yes — own vehicle

QUALIFICATIONS:
- Bachelor of Pharmacy (B.Pharm) — Misr University, Cairo, 2011
- DHA Licensed Pharmacist — Dubai Health Authority (active)
- LinkedIn Learning: Power BI, Lean Six Sigma, Operational Excellence

INDUSTRIES WITH GENUINE EXPERIENCE:
- Pharmacy / Healthcare Retail (primary — 14 years)
- Multi-branch Retail (FMCG, health, wellness, supplements)
- E-Commerce / Marketplace Management (Amazon, Noon, Talabat, Instashop, Carrefour, Sharaf DG)
- Omnichannel / Last-mile delivery operations
- Supply chain oversight (inventory, procurement, vendor — NOT warehouse floor)

INDUSTRIES WITH NO EXPERIENCE (hard disqualifiers):
- Construction, fabrication, aluminium, glazing, facade
- Aquatics, sports, swimming
- Hospitality, F&B, hotel operations
- Engineering, IT, software
- Finance, banking, investment
- Pure warehouse / DC floor management
- Manufacturing, heavy industry
- Automotive, marine, aerospace

TARGET ROLES:
Regional Manager | Area Manager | Cluster Manager | Operations Manager |
Pharmacy Manager | E-Commerce Manager | Omnichannel Manager |
Supply Chain Manager (oversight) | Retail Manager | District Manager

EXPERIENCE (most recent first):
1. Regional Manager — 800 Pharmacy & Marina Pharmacy Group, Dubai (Jul 2025–Mar 2026)
   - 30+ pharmacy branches, Dubai/Abu Dhabi/Sharjah
   - Managed 2 Cluster Managers, 7 direct branch managers
   - 19% YOY growth, 94.6% of highest-ever regional target
   - Full P&L, compliance, staffing, KPI accountability

2. Division Manager — 800 Pharmacy & Marina Pharmacy Group, Dubai (Mar 2025–Jul 2025)
   - Delivery division: staffing, logistics, performance, expansion
   - Marketplace oversight: Amazon, Noon, Talabat, Instashop

3. Branch Manager A-Class — Life Pharmacy, Dubai & Abu Dhabi (Dec 2021–Mar 2025)
   - 1,200+ 5-star Google reviews, 20% revenue uplift via mall partnership
   - DHA/DOH/MOH compliance, SOP enforcement, P&L

4. Omnichannel Manager & Store Manager — United Pharmacy Group, Dubai (Nov 2014–Jul 2023)
   - Built e-commerce from zero across 6 UAE platforms — quadrupled online sales in 6 months
   - 100% YOY sales growth at Galleria Mall — Best Employee & Store Manager 2015

KEY SKILLS: Multi-branch ops, P&L, omnichannel strategy, e-commerce platform management,
DHA/MOH/DOH compliance, team leadership, FEFO inventory, SOP development, KPI/Power BI,
customer retention, B2B portal, call centre, delivery logistics, supplier negotiation
"""

# ── Hard block keywords ───────────────────────────────────────────────────
HARD_BLOCK = [
    "aluminium", "aluminum", "glazing", "facade", "fabrication", "workshop",
    "aquatic", "swimming", "swim", "lifeguard", "pool instructor",
    "restaurant manager", "chef", "culinary", "f&b manager", "food & beverage",
    "civil engineer", "mechanical engineer", "electrical engineer", "site engineer",
    "construction manager", "contracting", "fitout manager", "fit out manager",
    "software engineer", "developer", "programmer", "devops", "data scientist",
    "investment banker", "wealth manager", "hedge fund",
    "cnc operator", "machinist", "production line",
    "nurse manager", "doctor", "physician", "surgeon", "dentist",
    "marine lubricant", "ship management", "maritime",
    "real estate broker", "property consultant",
    "hair stylist", "salon stylist", "beauty therapist",
]

PARTIAL_FIT = [
    "3pl manager", "third party logistics", "warehouse manager",
    "distribution center manager", "dc manager", "fulfilment centre manager",
]

SKIP_KEYWORDS = [
    "UAEN", "UAE NATIONAL", "EMIRATI", "NATIONAL ONLY", "NATIONALS ONLY",
    "FEMALE ONLY", "FEMALES ONLY", "LADY ONLY", "HINDI SPEAKING", "URDU SPEAKING",
]

def pre_screen(title, company=""):
    text = (title + " " + company).lower()
    for kw in HARD_BLOCK:
        if kw in text:
            return "block", f"Hard disqualifier: '{kw}'"
    for kw in PARTIAL_FIT:
        if kw in text:
            return "flag", f"Partial fit — 3PL: '{kw}'"
    return "ok", ""

def is_skip(title):
    up = title.upper()
    return any(kw in up for kw in SKIP_KEYWORDS)

# ── Claude match prompt ───────────────────────────────────────────────────
MATCH_PROMPT = """You are a strict recruitment screener. Evaluate honestly.

CANDIDATE:
{resume}

JOB:
Title: {title}
Company: {company}
Location: {location}
Date Listed: {date_listed}
Description: {description}

SCORING RULES:

HARD DISQUALIFIERS → score 0-15, apply: false, flag: "hard_block"
- Industry candidate has zero experience: construction, fabrication, aluminium/glazing,
  aquatics/swimming, engineering, hospitality/F&B, manufacturing, warehouse floor,
  finance/banking, automotive, maritime, beauty therapy
- UAE Nationals / Emiratis / gender restricted
- Entry-level (executive, coordinator, assistant, specialist) → score max 25

PARTIAL FIT → score 35-55, apply: false, flag: "3pl_partial"
- Primary requirement is 3PL/DC warehouse floor management
- Too junior for 14-year seniority

GOOD FIT → score 56-74, apply: true, flag: "none"
STRONG FIT → score 75-89, apply: true, flag: "none"
EXCEPTIONAL → score 90-100, apply: true, flag: "none"
- Precisely aligned: pharmacy, multi-branch retail, e-commerce, area/regional/ops mgmt UAE

IMPORTANT: Read the full description. A "Senior eCommerce Manager" at a brand agency
or lottery company scores low because the actual function doesn't match.

Reply ONLY as JSON (no other text):
{{"score":<0-100>,"apply":<true/false>,"reason":"<one sentence>","industry":"<industry>","flag":"<none|junior|overqualified|3pl_partial|hard_block>"}}"""


def match_job(title, company, location="", description="", date_listed=""):
    status, reason = pre_screen(title, company)
    if status == "block":
        return 0, False, reason, "Disqualified", "hard_block"

    # ── Prompt caching ────────────────────────────────────────────────────
    # The candidate CV + scoring rules are identical for every job call.
    # Marking them with cache_control means Anthropic caches them after
    # the first request — subsequent calls pay $0.03/MTok instead of
    # $0.25/MTok (Haiku input price), saving ~88% on those tokens.
    # Only the job-specific part (title/company/description) is fresh each time.

    cached_system = (
        "You are a strict recruitment screener. Evaluate honestly.\n\n"
        "CANDIDATE:\n"
        + MY_RESUME
        + "\n\nSCORING RULES:\n"
        "HARD DISQUALIFIERS → score 0-15, apply: false, flag: 'hard_block'\n"
        "- Industry candidate has zero experience: construction, fabrication, aluminium/glazing,\n"
        "  aquatics/swimming, engineering, hospitality/F&B, manufacturing, warehouse floor,\n"
        "  finance/banking, automotive, maritime, beauty therapy\n"
        "- UAE Nationals / Emiratis / gender restricted\n"
        "- Entry-level (executive, coordinator, assistant, specialist) → score max 25\n\n"
        "PARTIAL FIT → score 35-55, apply: false, flag: '3pl_partial'\n"
        "- Primary requirement is 3PL/DC warehouse floor management\n"
        "- Too junior for 14-year seniority\n\n"
        "GOOD FIT → score 56-74, apply: true, flag: 'none'\n"
        "STRONG FIT → score 75-89, apply: true, flag: 'none'\n"
        "EXCEPTIONAL → score 90-100, apply: true, flag: 'none'\n"
        "- Precisely aligned: pharmacy, multi-branch retail, e-commerce, area/regional/ops mgmt UAE\n\n"
        "IMPORTANT: Read the full description carefully. A 'Senior eCommerce Manager' at a brand\n"
        "agency or lottery company scores low because the actual function does not match.\n\n"
        "Reply ONLY as JSON (no other text):\n"
        '{"score":<0-100>,"apply":<true/false>,"reason":"<one sentence>","industry":"<industry>","flag":"<none|junior|overqualified|3pl_partial|hard_block>"}'
    )

    # Job-specific part — small, not cached, changes every call
    job_content = (
        f"JOB TO EVALUATE:\n"
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
                system=[
                    {
                        "type": "text",
                        "text": cached_system,
                        "cache_control": {"type": "ephemeral"},  # Cache CV + rules
                    }
                ],
                messages=[
                    {"role": "user", "content": job_content}  # Only job details sent fresh
                ],
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

# ── Google Jobs HTTP scraper ──────────────────────────────────────────────
SEARCH_QUERIES = [
    ("area manager",         "area manager UAE Dubai"),
    ("operations manager",   "operations manager retail UAE Dubai"),
    ("pharmacy manager",     "pharmacy manager UAE DHA Dubai"),
    ("ecommerce manager",    "ecommerce manager UAE marketplace Dubai"),
    ("cluster manager",      "cluster manager UAE retail Dubai"),
    ("regional manager",     "regional manager retail UAE Dubai"),
    ("supply chain manager", "supply chain manager UAE Dubai"),
    ("retail manager",       "retail operations manager UAE Dubai"),
    ("district manager",     "district manager retail UAE Dubai"),
    ("omnichannel manager",  "omnichannel manager UAE Dubai"),
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
]


def fetch_google_jobs(query_label, search_query, seen_set):
    """
    Fetches Google Jobs results for a search query using httpx.
    Parses job cards from the HTML response.
    Returns list of job dicts.
    """
    jobs      = []
    encoded   = search_query.replace(" ", "+")
    url       = f"https://www.google.com/search?q={encoded}&ibp=htl;jobs&hl=en&gl=ae&tbs=qdr:w"
    headers   = {
        "User-Agent":      random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer":         "https://www.google.com/",
    }

    try:
        with httpx.Client(follow_redirects=True, timeout=20) as http:
            response = http.get(url, headers=headers)

        if response.status_code != 200:
            print(f"  ⚠ Google returned {response.status_code} for: {query_label}")
            return jobs

        html = response.text

        # ── Parse job data from Google's JSON-LD or embedded data ────────
        # Google embeds job data in script tags as JSON
        # Try to extract structured job data first
        json_matches = re.findall(
            r'"jobTitle"\s*:\s*"([^"]+)".*?"employerName"\s*:\s*"([^"]+)"',
            html, re.DOTALL
        )

        # Also try the standard Google Jobs card format in HTML
        # Extract job blocks using pattern matching on the raw HTML
        job_blocks = re.findall(
            r'<div[^>]*class="[^"]*(?:iFjolb|PwjeAc|EimVGf)[^"]*"[^>]*>(.*?)</div>\s*</div>',
            html, re.DOTALL
        )

        # ── Method 1: Extract from JSON embedded in page ──────────────────
        # Google Jobs embeds data as: {"jobTitle":"...","employerName":"...","jobLocation":"..."}
        job_data_pattern = re.findall(
            r'\{[^{}]*"jobTitle"\s*:\s*"([^"]+)"[^{}]*"employerName"\s*:\s*"([^"]+)"[^{}]*\}',
            html
        )

        extracted = []

        if job_data_pattern:
            for title, company in job_data_pattern[:15]:
                title   = title.strip()
                company = company.strip()
                if len(title) < 5 or len(company) < 2:
                    continue
                extracted.append({
                    "title":       title,
                    "company":     company,
                    "location":    "UAE",
                    "date_listed": "Recent",
                    "link":        f"https://www.google.com/search?q={title.replace(' ', '+')}+{company.replace(' ', '+')}+UAE+job",
                    "description": "",
                })

        # ── Method 2: Regex extraction from page text ─────────────────────
        if not extracted:
            # Strip HTML tags and extract text
            clean = re.sub(r'<[^>]+>', '\n', html)
            clean = re.sub(r'&amp;', '&', clean)
            clean = re.sub(r'&nbsp;', ' ', clean)
            clean = re.sub(r'&#\d+;', '', clean)
            lines = [l.strip() for l in clean.split('\n') if l.strip() and len(l.strip()) > 3]

            # Job title patterns common in Google Jobs results
            title_pattern = re.compile(
                r'^((?:Senior |Junior |Lead |Head of |Director of |VP |'
                r'Assistant |Deputy )?'
                r'(?:Area|Regional|Operations|Pharmacy|Retail|Cluster|'
                r'Supply Chain|E-Commerce|Ecommerce|Omnichannel|District|'
                r'Store|Branch|Division) Manager.*?)$',
                re.IGNORECASE
            )

            seen_titles = set()
            for i, line in enumerate(lines):
                m = title_pattern.match(line)
                if m and line not in seen_titles and len(line) < 100:
                    seen_titles.add(line)
                    title   = line
                    company = lines[i + 1] if i + 1 < len(lines) else "Unknown"
                    # Clean up company — skip if it looks like a location or date
                    if re.search(r'^\d|ago$|Dubai|UAE|Abu Dhabi', company, re.I):
                        company = "Unknown"

                    location = "UAE"
                    for j in range(i + 1, min(i + 6, len(lines))):
                        loc_m = re.search(r'(Dubai|Abu Dhabi|Sharjah|Ajman|UAE|Ras Al Khaimah)', lines[j])
                        if loc_m:
                            location = loc_m.group(0)
                            break

                    date_listed = "Recent"
                    for j in range(i + 1, min(i + 8, len(lines))):
                        date_m = re.search(
                            r'(\d+\s+(?:hour|day|week)s?\s+ago|today|just posted|posted \d)',
                            lines[j], re.IGNORECASE
                        )
                        if date_m:
                            date_listed = date_m.group(0)
                            break

                    extracted.append({
                        "title":       title,
                        "company":     company,
                        "location":    location,
                        "date_listed": date_listed,
                        "link":        f"https://www.google.com/search?q={title.replace(' ', '+')}+{company.replace(' ', '+')}+UAE+jobs",
                        "description": "",
                    })

                    if len(extracted) >= 15:
                        break

        # ── Method 3: Try known UAE job board results embedded in Google ──
        # Google Jobs often shows results from Bayt, LinkedIn, Indeed in its panel
        # These have structured URLs we can extract
        bayt_links = re.findall(r'(https://www\.bayt\.com/[^\s"&>]+)', html)
        indeed_links = re.findall(r'(https://ae\.indeed\.com/[^\s"&>]+)', html)
        naukri_links = re.findall(r'(https://www\.naukrigulf\.com/[^\s"&>]+)', html)

        all_links = list(set(bayt_links + indeed_links + naukri_links))[:10]

        # If we got direct job board links, fetch them for better data
        for link in all_links[:5]:
            try:
                with httpx.Client(follow_redirects=True, timeout=10) as http:
                    r = http.get(link, headers=headers)
                page_text = re.sub(r'<[^>]+>', '\n', r.text)
                page_text = re.sub(r'\s+', ' ', page_text)

                # Extract title from page
                title_m = re.search(r'<title>([^<|–-]+)', r.text)
                if title_m:
                    title = title_m.group(1).strip()[:80]
                    # Remove site name suffix
                    title = re.sub(r'\s*[-|]\s*(?:Bayt|Indeed|Naukrigulf).*$', '', title, flags=re.I).strip()

                    if len(title) > 5:
                        location_m = re.search(r'(Dubai|Abu Dhabi|Sharjah|UAE)', page_text)
                        date_m = re.search(r'(\d+ (?:day|hour|week)s? ago|today)', page_text, re.I)

                        extracted.append({
                            "title":       title,
                            "company":     "Unknown",
                            "location":    location_m.group(0) if location_m else "UAE",
                            "date_listed": date_m.group(0) if date_m else "Recent",
                            "link":        link,
                            "description": page_text[:1500],
                        })
            except:
                continue

        # ── Deduplicate and build final job list ──────────────────────────
        count = 0
        for job_data in extracted:
            if count >= 10:
                break

            title   = job_data["title"].strip()
            company = job_data["company"].strip()

            if len(title) < 5:
                continue
            if is_skip(title):
                print(f"    🚫 UAE National — {title[:45]}")
                continue

            key         = f"{company.lower()}_{title.lower()}"
            seen_before = key in seen_set

            jobs.append({
                "title":       title,
                "company":     company,
                "location":    job_data.get("location", "UAE"),
                "date_listed": job_data.get("date_listed", "Recent"),
                "link":        job_data.get("link", ""),
                "platform":    "Google Jobs",
                "description": job_data.get("description", ""),
                "seen_before": seen_before,
                "query":       query_label,
            })
            count += 1
            print(f"    📌 {title[:50]} — {company[:30]}")

    except Exception as e:
        print(f"  ❌ Error fetching Google Jobs for '{query_label}': {e}")

    print(f"  ✅ {query_label}: {count} found")
    return jobs

# ── Telegram ──────────────────────────────────────────────────────────────
def send_telegram(text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id":                  TELEGRAM_CHAT_ID,
                "text":                     text,
                "parse_mode":               "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
    except Exception as e:
        print(f"Telegram error: {e}")


def send_telegram_results(matched):
    if not matched:
        send_telegram(f"🔍 Job Hunter v3 — {TODAY}\n\n❌ No matching jobs found today.")
        return

    new_jobs  = [j for j in matched if not j.get("seen_before")]
    seen_jobs = [j for j in matched if j.get("seen_before")]

    send_telegram(
        f"🎯 <b>JOB HUNTER v3 — {TODAY}</b>\n"
        f"🆕 New: <b>{len(new_jobs)}</b> | 👀 Seen: <b>{len(seen_jobs)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )

    def fmt(i, job):
        score = job["score"]
        emoji = "🔥" if score >= 80 else "⭐" if score >= 70 else "✅"
        flag  = " ⚠️3PL" if job.get("flag") == "3pl_partial" else ""
        return (
            f"{emoji} <b>#{i} — {score}%</b>{flag}\n"
            f"📋 {job['title']}\n"
            f"🏢 {job['company']}\n"
            f"📍 {job.get('location', 'UAE')}\n"
            f"📅 {job.get('date_listed', 'Recent')}\n"
            f"🏭 {job.get('industry', 'N/A')}\n"
            f"💡 {job.get('reason', '')}\n"
            f"🔗 <a href='{job['link']}'>Apply Now</a>"
        )

    for label, jobs_list, start in [
        ("🆕 <b>NEW JOBS:</b>", new_jobs, 1),
        ("👀 <b>SEEN BEFORE:</b>", seen_jobs, len(new_jobs) + 1),
    ]:
        if not jobs_list:
            continue
        send_telegram(label)
        batch = []
        for i, job in enumerate(jobs_list, start):
            batch.append(fmt(i, job))
            if len(batch) == 5 or i == start + len(jobs_list) - 1:
                send_telegram("\n━━━━━━━━━━━━\n".join(batch))
                batch = []

# ── Parallel Claude analysis ──────────────────────────────────────────────
def analyze_wrapper(job):
    try:
        score, apply_flag, reason, industry, flag = match_job(
            job["title"],
            job["company"],
            job.get("location", "UAE"),
            job.get("description", ""),
            job.get("date_listed", ""),
        )
        job.update({"score": score, "reason": reason, "industry": industry, "flag": flag})
        return job, apply_flag
    except Exception as e:
        job.update({"score": 0, "reason": str(e), "industry": "Unknown", "flag": "none"})
        return job, False

# ── Main run function ─────────────────────────────────────────────────────
def run(progress_callback=None):
    """
    Main entry point called by web_dashboard_cloud.py.
    progress_callback(step: str, pct: int) updates the dashboard progress bar.
    Returns count of matched jobs saved.
    """

    def progress(step, pct):
        print(f"[{pct}%] {step}")
        if progress_callback:
            progress_callback(step, pct)

    progress("🚀 Starting Job Hunter v3...", 2)

    send_telegram(
        f"🚀 Job Hunter v3 started — {TODAY}\n"
        f"🌐 Google Jobs — {len(SEARCH_QUERIES)} role categories\n"
        f"🧠 Full description matching active"
    )

    progress("📂 Loading seen jobs from Google Sheets...", 5)
    seen_set  = load_seen_before()
    all_jobs  = []
    seen_keys = set()

    total_queries = len(SEARCH_QUERIES)

    for i, (query_label, search_query) in enumerate(SEARCH_QUERIES):
        pct = 5 + int((i / total_queries) * 45)
        progress(f"🔍 Searching: {query_label}...", pct)

        jobs = fetch_google_jobs(query_label, search_query, seen_set)

        for job in jobs:
            key = f"{job['title'].lower()}_{job['company'].lower()}"
            if key not in seen_keys and len(job["title"]) >= 5:
                seen_keys.add(key)
                all_jobs.append(job)

        # Polite delay between Google requests — critical
        delay = random.uniform(6, 12)
        time.sleep(delay)

    progress(f"📊 {len(all_jobs)} unique jobs found — analysing with AI...", 52)

    if not all_jobs:
        progress("⚠️ No jobs scraped — Google may have blocked. Try again later.", 100)
        send_telegram("⚠️ No jobs scraped — Google may have blocked. Try again in a few hours.")
        return 0

    # Parallel Claude analysis
    matched   = []
    blocked   = 0
    skipped   = 0
    total     = len(all_jobs)

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(analyze_wrapper, job): job for job in all_jobs}
        done    = 0
        for future in as_completed(futures):
            done += 1
            pct   = 52 + int((done / total) * 38)
            job, apply_flag = future.result()
            title = job["title"]
            score = job.get("score", 0)
            flag  = job.get("flag", "none")

            if is_skip(title):
                continue
            if flag == "hard_block":
                blocked += 1
                continue
            if apply_flag and score >= 50:
                matched.append(job)
                progress(f"✅ Match: {title[:40]} ({score}%)", pct)
            else:
                skipped += 1

    matched.sort(key=lambda x: (-x["score"], x.get("seen_before", False)))

    progress("💾 Saving results to Google Sheets...", 92)
    saved = save_jobs_to_sheet(matched)

    progress("📱 Sending Telegram summary...", 96)
    send_telegram_results(matched)

    summary = (
        f"✅ <b>Job Hunter v3 Complete — {TODAY}</b>\n"
        f"🎯 Matched: {len(matched)}\n"
        f"⛔ Blocked: {blocked}\n"
        f"❌ Skipped: {skipped}\n"
        f"💾 Saved to Sheets: {saved}"
    )
    send_telegram(summary)
    progress(f"✅ Done! {len(matched)} jobs matched.", 100)

    print(f"\n{'='*50}")
    print(f"✅ Matched: {len(matched)}")
    print(f"⛔ Blocked: {blocked}")
    print(f"❌ Skipped: {skipped}")
    print(f"{'='*50}")

    return len(matched)


if __name__ == "__main__":
    run()
