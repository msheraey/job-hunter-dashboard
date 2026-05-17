#!/usr/bin/env python3
"""
Job Hunter Scraper — Cloud Version
Runs on Render with headless Playwright + Google Sheets
"""

from playwright.sync_api import sync_playwright
import anthropic
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import json
import requests
import time
from datetime import date

# ── CONFIG ────────────────────────────────────────────────
TODAY = date.today().strftime("%Y-%m-%d")
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '8972917892:AAGs_Z6xWc67poi7EfVdJpPoJJb_3hs8sJo')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '8872960522')
SHEET_ID = os.environ.get('SHEET_ID', '')
SHEET_NAME = "Job Hunter Data"
ANTHROPIC_KEY = os.environ.get('ANTHROPIC_API_KEY', '')

SKIP_KEYWORDS = ['UAEN', 'UAE NATIONAL', 'EMIRATI', 'NATIONAL ONLY', 'NATIONALS ONLY']

MY_RESUME = """
Mohammed Alsheraery — Area Manager / Cluster Manager / Operations Manager
11+ years UAE healthcare, pharmacy and retail experience (14 years total including Egypt)
Skills: Multi-branch operations, P&L oversight, procurement, supply chain,
e-commerce (Amazon, Noon, Talabat, Instashop, Carrefour, Sharaf DG),
DHA/MOH/DOH compliance, team leadership, inventory management,
vendor coordination, SOP development, KPI tracking, revenue growth,
retail coaching, call center operations, delivery logistics
Achievements: 56% YOY sales growth, 19% regional uplift in 6 months,
94.6% target achievement, built top-ranked e-pharmacy from zero,
managed 7+ branches simultaneously, 1200+ Google reviews at 5 stars
"""

# ── GOOGLE SHEETS ─────────────────────────────────────────
def get_creds():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    if creds_json:
        return ServiceAccountCredentials.from_json_keyfile_dict(json.loads(creds_json), scope)
    return ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)

def load_seen_before():
    """Load previously scraped company+title pairs from Google Sheets"""
    seen = set()
    if not SHEET_ID:
        return seen
    try:
        client = gspread.authorize(get_creds())
        sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
        records = sheet.get_all_records()
        for row in records:
            company = str(row.get('Company', '')).lower().strip()
            title = str(row.get('Job Title', '')).lower().strip()
            if company and title:
                seen.add(f"{company}_{title}")
    except Exception as e:
        print(f"load_seen_before error: {e}")
    return seen

def ensure_headers(sheet):
    """Make sure the sheet has correct headers"""
    try:
        first_row = sheet.row_values(1)
        expected = ['Date', 'Score', 'Company', 'Job Title', 'Platform', 'Salary', 'Link', 'Status']
        if first_row != expected:
            sheet.insert_row(expected, 1)
    except Exception as e:
        print(f"ensure_headers error: {e}")

def save_to_sheets(all_jobs):
    """Save scraped jobs to Google Sheets"""
    if not SHEET_ID or not all_jobs:
        return
    try:
        client = gspread.authorize(get_creds())
        sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
        ensure_headers(sheet)

        rows = []
        for job in all_jobs:
            rows.append([
                TODAY,
                f"{job['score']}%",
                job['company'],
                job['title'],
                job['platform'],
                job.get('salary', 'TBD'),
                job['link'],
                'New'
            ])

        if rows:
            sheet.append_rows(rows, value_input_option='USER_ENTERED')
            new = len([j for j in all_jobs if not j.get('seen_before')])
            seen = len([j for j in all_jobs if j.get('seen_before')])
            print(f"✅ Saved {len(rows)} jobs to Google Sheets ({new} new, {seen} seen before)")
    except Exception as e:
        print(f"save_to_sheets error: {e}")

# ── TELEGRAM ──────────────────────────────────────────────
def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def send_telegram_job_list(all_jobs):
    new_jobs  = [j for j in all_jobs if not j.get('seen_before')]
    seen_jobs = [j for j in all_jobs if j.get('seen_before')]

    if not all_jobs:
        send_telegram(f"🔍 Job Hunter ran on {TODAY}\n\n❌ No matching jobs found today.")
        return

    send_telegram(
        f"🎯 <b>JOB HUNTER — {TODAY}</b>\n"
        f"🆕 New: <b>{len(new_jobs)}</b> | 👀 Seen Before: <b>{len(seen_jobs)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 Reply with job number to generate CV\nExample: <code>cv 3</code>"
    )

    def send_batch(jobs, label):
        if not jobs:
            return
        send_telegram(f"<b>{label}</b>")
        batch = []
        for i, job in enumerate(jobs, 1):
            score = job['score']
            emoji = "🔥" if score >= 80 else "⭐" if score >= 70 else "✅"
            batch.append(
                f"{emoji} <b>#{i} — {score}%</b>\n"
                f"📋 {job['title']}\n"
                f"🏢 {job['company']}\n"
                f"💰 {job.get('salary', 'TBD')}\n"
                f"📱 {job['platform']}\n"
                f"🔗 <a href='{job['link']}'>Apply Now</a>"
            )
            if len(batch) == 5 or i == len(jobs):
                send_telegram("\n━━━━━━━━━━━━\n".join(batch))
                batch = []

    send_batch(new_jobs, "🆕 NEW JOBS:")
    send_batch(seen_jobs, "👀 SEEN BEFORE (still open):")
    send_telegram(
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📄 Reply <code>cv [number]</code> to generate CV\n"
        f"🌐 Dashboard: https://job-hunter-dashboard-75ex.onrender.com"
    )

# ── AI MATCHING ───────────────────────────────────────────
def match_job(title, company, salary=""):
    if not ANTHROPIC_KEY:
        return 70, True   # fallback if no API key
    try:
        ai = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        msg = ai.messages.create(
            model="claude-haiku-4-5",
            max_tokens=100,
            messages=[{"role": "user", "content":
                f"Score this job 0-100 for this resume. Reply ONLY:\nSCORE: [number]\nAPPLY: [YES or NO]\n\nRESUME: {MY_RESUME}\nJOB: {title} at {company}\nSALARY: {salary or 'Not listed'}"}]
        )
        result = msg.content[0].text
        score_line = [l for l in result.split('\n') if 'SCORE:' in l][0]
        score = int(score_line.split(':')[1].strip().split('/')[0])
        apply = 'YES' in result
        return score, apply
    except:
        return 0, False

def extract_salary(text):
    import re
    for pattern in [
        r'AED[\s]?[\d,]+[\s]?[-–][\s]?[\d,]+',
        r'[\d,]+[\s]?[-–][\s]?[\d,]+[\s]?AED',
        r'AED[\s]?[\d,]+',
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(0).strip()
    return "TBD"

def is_uae_national(title):
    return any(w in title.upper() for w in SKIP_KEYWORDS)

def safe_goto(page, url, label):
    for attempt in range(2):
        try:
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            time.sleep(3)
            return True
        except:
            if attempt == 0:
                print(f"  Retrying {label}...")
                time.sleep(5)
            else:
                print(f"  Skipped {label} (timeout)")
                return False

# ── SCRAPERS ──────────────────────────────────────────────
def scrape_bayt(page, seen_set):
    jobs = []
    urls = [
        ("area manager",       "https://www.bayt.com/en/uae/jobs/area-manager-jobs/"),
        ("operations manager", "https://www.bayt.com/en/uae/jobs/operations-manager-jobs/"),
        ("pharmacy manager",   "https://www.bayt.com/en/uae/jobs/pharmacy-manager-jobs/"),
        ("ecommerce manager",  "https://www.bayt.com/en/uae/jobs/e-commerce-manager-jobs/"),
        ("cluster manager",    "https://www.bayt.com/en/uae/jobs/cluster-manager-jobs/"),
        ("regional manager",   "https://www.bayt.com/en/uae/jobs/regional-manager-jobs/"),
        ("retail manager",     "https://www.bayt.com/en/uae/jobs/retail-manager-jobs/"),
    ]
    for label, url in urls:
        if not safe_goto(page, url, f"Bayt {label}"):
            continue
        try:
            items = page.query_selector_all('li[class*="has-pointer-d"]')
            count = 0
            for item in items[:10]:
                try:
                    title   = item.query_selector('h2').inner_text().strip()
                    company = item.query_selector('[class*="company"]').inner_text().strip()
                    link    = item.query_selector('a').get_attribute('href')
                    salary  = extract_salary(item.inner_text())
                    key = f"{company.lower()}_{title.lower()}"
                    if title and len(title) > 5:
                        jobs.append({"title": title, "company": company,
                            "link": f"https://www.bayt.com{link}",
                            "platform": "Bayt", "salary": salary,
                            "seen_before": key in seen_set})
                        count += 1
                except: continue
            print(f"  Bayt {label}: {count} jobs")
        except Exception as e:
            print(f"  Bayt {label} error: {e}")
    return jobs

def scrape_naukrigulf(page, seen_set):
    jobs = []
    urls = [
        ("area manager",       "https://www.naukrigulf.com/area-manager-jobs-in-uae"),
        ("operations manager", "https://www.naukrigulf.com/operations-manager-jobs-in-uae"),
        ("pharmacy manager",   "https://www.naukrigulf.com/pharmacy-manager-jobs-in-uae"),
        ("ecommerce manager",  "https://www.naukrigulf.com/ecommerce-manager-jobs-in-uae"),
        ("cluster manager",    "https://www.naukrigulf.com/cluster-manager-jobs-in-uae"),
        ("regional manager",   "https://www.naukrigulf.com/regional-manager-jobs-in-uae"),
        ("retail manager",     "https://www.naukrigulf.com/retail-manager-jobs-in-uae"),
    ]
    for label, url in urls:
        if not safe_goto(page, url, f"Naukrigulf {label}"):
            continue
        try:
            time.sleep(2)
            items = page.query_selector_all('[class*="tuple"]')
            count = 0
            for item in items[:10]:
                try:
                    title_el = item.query_selector('a[class*="title"], h3 a, h2 a, a')
                    if not title_el: continue
                    title = title_el.inner_text().strip()
                    if len(title) < 5: continue
                    try:
                        company = item.query_selector('[class*="company"], [class*="org"]').inner_text().strip()
                    except:
                        company = "Unknown"
                    link = title_el.get_attribute('href') or ''
                    if not link.startswith('http'):
                        link = f"https://www.naukrigulf.com{link}"
                    salary = extract_salary(item.inner_text())
                    key = f"{company.lower()}_{title.lower()}"
                    if company != "Unknown":
                        jobs.append({"title": title, "company": company,
                            "link": link, "platform": "Naukrigulf",
                            "salary": salary, "seen_before": key in seen_set})
                        count += 1
                except: continue
            print(f"  Naukrigulf {label}: {count} jobs")
        except Exception as e:
            print(f"  Naukrigulf {label} error: {e}")
    return jobs

def scrape_indeed(page, seen_set):
    jobs = []
    urls = [
        ("area manager",       "https://ae.indeed.com/jobs?q=area+manager&l=UAE&fromage=1"),
        ("operations manager", "https://ae.indeed.com/jobs?q=operations+manager&l=UAE&fromage=1"),
        ("pharmacy manager",   "https://ae.indeed.com/jobs?q=pharmacy+manager&l=UAE&fromage=1"),
        ("ecommerce manager",  "https://ae.indeed.com/jobs?q=ecommerce+manager&l=UAE&fromage=1"),
        ("cluster manager",    "https://ae.indeed.com/jobs?q=cluster+manager&l=UAE&fromage=1"),
        ("retail manager",     "https://ae.indeed.com/jobs?q=retail+operations+manager&l=UAE&fromage=1"),
    ]
    for label, url in urls:
        if not safe_goto(page, url, f"Indeed {label}"):
            continue
        try:
            items = page.query_selector_all('.job_seen_beacon, [class*="jobCard"]')
            count = 0
            for item in items[:10]:
                try:
                    title   = item.query_selector('h2').inner_text().strip()
                    company = item.query_selector('[class*="company"]').inner_text().strip()
                    link    = item.query_selector('a').get_attribute('href')
                    salary  = extract_salary(item.inner_text())
                    key = f"{company.lower()}_{title.lower()}"
                    if title and len(title) > 5:
                        jobs.append({"title": title, "company": company,
                            "link": f"https://ae.indeed.com{link}",
                            "platform": "Indeed", "salary": salary,
                            "seen_before": key in seen_set})
                        count += 1
                except: continue
            print(f"  Indeed {label}: {count} jobs")
        except Exception as e:
            print(f"  Indeed {label} error: {e}")
    return jobs

def scrape_linkedin(page, seen_set):
    jobs = []
    urls = [
        ("area manager",       "https://www.linkedin.com/jobs/search/?keywords=area+manager&location=UAE&f_TPR=r86400"),
        ("operations manager", "https://www.linkedin.com/jobs/search/?keywords=operations+manager+retail&location=UAE&f_TPR=r86400"),
        ("pharmacy manager",   "https://www.linkedin.com/jobs/search/?keywords=pharmacy+manager&location=UAE&f_TPR=r86400"),
        ("ecommerce manager",  "https://www.linkedin.com/jobs/search/?keywords=ecommerce+manager&location=UAE&f_TPR=r86400"),
        ("cluster manager",    "https://www.linkedin.com/jobs/search/?keywords=cluster+manager&location=UAE&f_TPR=r86400"),
        ("retail manager",     "https://www.linkedin.com/jobs/search/?keywords=retail+operations+manager&location=UAE&f_TPR=r86400"),
    ]
    for label, url in urls:
        if not safe_goto(page, url, f"LinkedIn {label}"):
            continue
        try:
            time.sleep(3)
            items = page.query_selector_all('[data-job-id]')
            count = 0
            for item in items[:10]:
                try:
                    title_el = item.query_selector('a[class*="job-card-container__link"], a[class*="job-card-list__title"], a')
                    if not title_el: continue
                    title = title_el.inner_text().strip()
                    if len(title) < 5: continue
                    try:
                        company = item.query_selector('[class*="company-name"], [class*="subtitle"], h4').inner_text().strip()
                    except:
                        company = "Unknown"
                    link = title_el.get_attribute('href') or ''
                    if not link.startswith('http'):
                        link = f"https://www.linkedin.com{link}"
                    salary = extract_salary(item.inner_text())
                    key = f"{company.lower()}_{title.lower()}"
                    if company != "Unknown":
                        jobs.append({"title": title, "company": company,
                            "link": link, "platform": "LinkedIn",
                            "salary": salary, "seen_before": key in seen_set})
                        count += 1
                except: continue
            print(f"  LinkedIn {label}: {count} jobs")
        except Exception as e:
            print(f"  LinkedIn {label} error: {e}")
    return jobs

# ── MAIN ──────────────────────────────────────────────────
def run():
    """Main entry point — called from Flask background thread or CLI"""
    all_apply = []
    deduped   = set()

    send_telegram(f"🚀 Job Hunter started — {TODAY}\nScanning Bayt, Naukrigulf, Indeed, LinkedIn...")
    print(f"\n{'='*50}\n🚀 Job Hunter Cloud — {TODAY}\n{'='*50}")

    seen_set = load_seen_before()
    print(f"📂 {len(seen_set)} previously seen jobs loaded from Sheets")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--single-process',
            ]
        )
        context = browser.new_context(
            user_agent=(
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
            viewport={'width': 1280, 'height': 800}
        )
        page = context.new_page()

        print("\n🔍 Scraping Bayt...")
        all_raw = scrape_bayt(page, seen_set)

        print("\n🔍 Scraping Naukrigulf...")
        all_raw += scrape_naukrigulf(page, seen_set)

        print("\n🔍 Scraping Indeed...")
        all_raw += scrape_indeed(page, seen_set)

        print("\n🔍 Scraping LinkedIn...")
        all_raw += scrape_linkedin(page, seen_set)

        browser.close()

    print(f"\n📊 Total scraped: {len(all_raw)} — now AI-matching...")
    send_telegram(f"📊 Scraped {len(all_raw)} jobs. Running AI match...")

    for job in all_raw:
        title   = job['title']
        company = job['company']
        key     = f"{title.lower()}_{company.lower()}"

        if key in deduped or len(title) < 8 or company == "Unknown":
            continue
        deduped.add(key)

        if is_uae_national(title):
            print(f"🚫 SKIP (UAE National) — {title}")
            continue

        score, apply = match_job(title, company, job.get('salary', ''))

        if apply and score >= 60:
            tag = "👀 SEEN" if job.get('seen_before') else "🆕 NEW"
            print(f"{tag} ({score}%) — {title} @ {company} [{job['platform']}]")
            all_apply.append({**job, "score": score})
        else:
            print(f"❌ SKIP ({score}%) — {title} @ {company}")

    all_apply.sort(key=lambda x: -x['score'])
    save_to_sheets(all_apply)
    send_telegram_job_list(all_apply)

    print(f"\n{'='*50}")
    print(f"🎯 DONE — {len(all_apply)} matching jobs saved to Google Sheets")
    print('='*50)
    return len(all_apply)

if __name__ == "__main__":
    run()
