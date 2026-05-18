#!/usr/bin/env python3
"""
Job Hunter Scraper — Cloud Version (httpx + BeautifulSoup, no browser)
Works on any Python version, no Playwright/greenlet needed.
"""

import asyncio
import httpx
from bs4 import BeautifulSoup
import anthropic
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import json
import requests
from datetime import date

# ── CONFIG ────────────────────────────────────────────────
TODAY          = date.today().strftime("%Y-%m-%d")
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '8972917892:AAGs_Z6xWc67poi7EfVdJpPoJJb_3hs8sJo')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '8872960522')
SHEET_ID       = os.environ.get('SHEET_ID', '')
SHEET_NAME     = "Sheet1"
ANTHROPIC_KEY  = os.environ.get('ANTHROPIC_API_KEY', '')

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

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache',
}

# ── HELPERS ───────────────────────────────────────────────
def fix_link(href, base):
    """Always return a valid absolute URL."""
    if not href or href.strip() in ('#', '', 'javascript:void(0)'):
        return '#'
    href = href.strip()
    if href.startswith('http'):
        return href
    if href.startswith('//'):
        return 'https:' + href
    return base.rstrip('/') + ('/' if not href.startswith('/') else '') + href

def extract_salary(text):
    import re
    for p in [r'AED[\s]?[\d,]+[\s]?[-–][\s]?[\d,]+',
              r'[\d,]+[\s]?[-–][\s]?[\d,]+[\s]?AED',
              r'AED[\s]?[\d,]+']:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(0).strip()
    return "TBD"

def is_uae_national(title):
    return any(w in title.upper() for w in SKIP_KEYWORDS)

# ── GOOGLE SHEETS ─────────────────────────────────────────
def get_creds():
    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    if creds_json:
        return ServiceAccountCredentials.from_json_keyfile_dict(
            json.loads(creds_json), scope)
    return ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)

def load_seen_before():
    seen = set()
    if not SHEET_ID:
        return seen
    try:
        client = gspread.authorize(get_creds())
        sheet  = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
        for row in sheet.get_all_records():
            company = str(row.get('Company', '')).lower().strip()
            title   = str(row.get('Job Title', '')).lower().strip()
            if company and title:
                seen.add(f"{company}_{title}")
    except Exception as e:
        print(f"load_seen_before error: {e}")
    return seen

def save_to_sheets(all_jobs):
    if not SHEET_ID or not all_jobs:
        return
    try:
        client = gspread.authorize(get_creds())
        sheet  = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
        if not sheet.row_values(1):
            sheet.append_row(['Date','Score','Company','Job Title',
                              'Platform','Salary','Link','Status'])
        rows = [[TODAY, f"{j['score']}%", j['company'], j['title'],
                 j['platform'], j.get('salary', 'TBD'), j['link'], 'New']
                for j in all_jobs]
        sheet.append_rows(rows, value_input_option='USER_ENTERED')
        print(f"✅ Saved {len(rows)} jobs to Google Sheets")
    except Exception as e:
        print(f"save_to_sheets error: {e}")

# ── TELEGRAM ──────────────────────────────────────────────
def send_telegram(message):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10)
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
        f"🆕 New: <b>{len(new_jobs)}</b> | 👀 Seen: <b>{len(seen_jobs)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Reply <code>cv [number]</code> to generate CV"
    )
    def send_batch(jobs, label):
        if not jobs:
            return
        send_telegram(f"<b>{label}</b>")
        batch = []
        for i, job in enumerate(jobs, 1):
            e = "🔥" if job['score'] >= 80 else "⭐" if job['score'] >= 70 else "✅"
            batch.append(
                f"{e} <b>#{i} — {job['score']}%</b>\n"
                f"📋 {job['title']}\n🏢 {job['company']}\n"
                f"💰 {job.get('salary','TBD')}\n📱 {job['platform']}\n"
                f"🔗 <a href='{job['link']}'>Apply</a>"
            )
            if len(batch) == 5 or i == len(jobs):
                send_telegram("\n━━━━━━━━━━━━\n".join(batch))
                batch = []
    send_batch(new_jobs,  "🆕 NEW JOBS:")
    send_batch(seen_jobs, "👀 SEEN BEFORE:")
    send_telegram("🌐 Dashboard: https://job-hunter-dashboard-75ex.onrender.com")

# ── AI MATCHING ───────────────────────────────────────────
def match_job(title, company, salary=""):
    if not ANTHROPIC_KEY:
        return 70, True
    try:
        ai  = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        msg = ai.messages.create(
            model="claude-haiku-4-5", max_tokens=100,
            messages=[{"role": "user", "content":
                f"Score 0-100 for resume match. Reply ONLY:\n"
                f"SCORE: [number]\nAPPLY: [YES or NO]\n\n"
                f"RESUME: {MY_RESUME}\n"
                f"JOB: {title} at {company}\nSALARY: {salary or 'Not listed'}"}])
        result = msg.content[0].text
        score  = int([l for l in result.split('\n')
                      if 'SCORE:' in l][0].split(':')[1].strip())
        return score, 'YES' in result
    except Exception as e:
        print(f"match_job error: {e}")
        return 0, False

# ── SCRAPERS ─────────────────────────────────────────────
async def scrape_bayt(client, seen_set, on_progress=None):
    """Scrape Bayt.com UAE job listings."""
    jobs = []
    searches = [
        ("area manager",       "area-manager-jobs"),
        ("operations manager", "operations-manager-jobs"),
        ("pharmacy manager",   "pharmacy-manager-jobs"),
        ("ecommerce manager",  "e-commerce-manager-jobs"),
        ("cluster manager",    "cluster-manager-jobs"),
        ("regional manager",   "regional-manager-jobs"),
        ("retail manager",     "retail-manager-jobs"),
    ]
    n = len(searches)
    for i, (label, slug) in enumerate(searches):
        pct = 10 + int(((i + 1) / n) * 17)
        try:
            url = f"https://www.bayt.com/en/uae/jobs/{slug}/"
            r   = await client.get(url, headers={**HEADERS, 'Referer': 'https://www.bayt.com/'})
            soup = BeautifulSoup(r.text, 'lxml')

            # Try every known Bayt list-item selector
            items = (soup.select('li[data-job-id]')
                     or soup.select('li[class*="has-pointer-d"]')
                     or soup.select('li.media.list-item')
                     or soup.select('.jobs-list li')
                     or soup.select('li.t-row'))

            count = 0
            for item in items[:15]:
                try:
                    # Title selectors — ordered most → least specific
                    title_el = (item.select_one('h2.t-size-xl a')
                                or item.select_one('h2 a')
                                or item.select_one('[class*="jb-title"] a')
                                or item.select_one('a[href*="/en/uae/jobs/"]'))
                    if not title_el:
                        continue
                    title = title_el.get_text(strip=True)
                    if len(title) < 5:
                        continue

                    # Company selectors
                    company_el = (item.select_one('[class*="jb-company"]')
                                  or item.select_one('[class*="jb-attrs"] a')
                                  or item.select_one('b[class*="t-default"]')
                                  or item.select_one('.t-muted-l'))
                    company = company_el.get_text(strip=True) if company_el else "Unknown"

                    href = title_el.get('href', '#')
                    link = fix_link(href, 'https://www.bayt.com')
                    salary = extract_salary(item.get_text())
                    key    = f"{company.lower()}_{title.lower()}"
                    jobs.append({"title": title, "company": company, "link": link,
                                 "platform": "Bayt", "salary": salary,
                                 "seen_before": key in seen_set})
                    count += 1
                except Exception:
                    continue

            msg = f"🏢 Bayt: {label} → {count} jobs found"
            if on_progress:
                on_progress(msg, pct)
            print(f"  {msg}")
            await asyncio.sleep(1.5)
        except Exception as e:
            msg = f"🏢 Bayt: {label} → error ({str(e)[:40]})"
            if on_progress:
                on_progress(msg, pct)
            print(f"  {msg}")
    return jobs


async def scrape_naukrigulf(client, seen_set, on_progress=None):
    """Scrape Naukrigulf UAE job listings."""
    jobs = []
    searches = [
        ("area manager",       "area-manager-jobs-in-uae"),
        ("operations manager", "operations-manager-jobs-in-uae"),
        ("pharmacy manager",   "pharmacy-manager-jobs-in-uae"),
        ("ecommerce manager",  "ecommerce-manager-jobs-in-uae"),
        ("cluster manager",    "cluster-manager-jobs-in-uae"),
        ("regional manager",   "regional-manager-jobs-in-uae"),
        ("retail manager",     "retail-manager-jobs-in-uae"),
    ]
    n = len(searches)
    for i, (label, slug) in enumerate(searches):
        pct = 27 + int(((i + 1) / n) * 17)
        try:
            url  = f"https://www.naukrigulf.com/{slug}"
            r    = await client.get(url)
            soup = BeautifulSoup(r.text, 'lxml')

            items = (soup.select('[class*="tuple-card"]')
                     or soup.select('[class*="job-tuple"]')
                     or soup.select('[class*="job-listing"]')
                     or soup.select('article')
                     or soup.select('[class*="tuple"]'))

            count = 0
            for item in items[:15]:
                try:
                    title_el = (item.select_one('a[class*="title"]')
                                or item.select_one('h3 a')
                                or item.select_one('h2 a')
                                or item.select_one('.job-title a'))
                    if not title_el:
                        continue
                    title = title_el.get_text(strip=True)
                    if len(title) < 5:
                        continue
                    company_el = (item.select_one('[class*="company-name"]')
                                  or item.select_one('[class*="org"]')
                                  or item.select_one('.comp-name')
                                  or item.select_one('[class*="employer"]'))
                    company = company_el.get_text(strip=True) if company_el else "Unknown"
                    href    = title_el.get('href', '#')
                    link    = fix_link(href, 'https://www.naukrigulf.com')
                    salary  = extract_salary(item.get_text())
                    key     = f"{company.lower()}_{title.lower()}"
                    if company != "Unknown":
                        jobs.append({"title": title, "company": company, "link": link,
                                     "platform": "Naukrigulf", "salary": salary,
                                     "seen_before": key in seen_set})
                        count += 1
                except Exception:
                    continue

            msg = f"🔎 Naukrigulf: {label} → {count} jobs found"
            if on_progress:
                on_progress(msg, pct)
            print(f"  {msg}")
            await asyncio.sleep(1.5)
        except Exception as e:
            msg = f"🔎 Naukrigulf: {label} → error ({str(e)[:40]})"
            if on_progress:
                on_progress(msg, pct)
            print(f"  {msg}")
    return jobs


async def scrape_linkedin(client, seen_set, on_progress=None):
    """Scrape LinkedIn UAE jobs via the guest API."""
    jobs = []
    searches = [
        ("area manager",       "area+manager"),
        ("operations manager", "operations+manager+retail"),
        ("pharmacy manager",   "pharmacy+manager"),
        ("ecommerce manager",  "ecommerce+manager"),
        ("cluster manager",    "cluster+manager"),
        ("regional manager",   "regional+manager+retail"),
        ("retail manager",     "retail+operations+manager"),
    ]
    n = len(searches)
    for i, (label, query) in enumerate(searches):
        pct = 44 + int(((i + 1) / n) * 16)
        try:
            url = (f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
                   f"?keywords={query}&location=United+Arab+Emirates&f_TPR=r86400&start=0")
            r    = await client.get(url)
            soup = BeautifulSoup(r.text, 'lxml')
            items = soup.select('li')
            count = 0
            for item in items[:15]:
                try:
                    title_el   = item.select_one('.base-search-card__title, h3')
                    company_el = item.select_one('.base-search-card__subtitle, h4')
                    link_el    = item.select_one('a.base-card__full-link, a')
                    if not title_el or not company_el:
                        continue
                    title   = title_el.get_text(strip=True)
                    company = company_el.get_text(strip=True)
                    href    = link_el.get('href', '#') if link_el else '#'
                    link    = fix_link(href, 'https://www.linkedin.com')
                    if len(title) < 5:
                        continue
                    key = f"{company.lower()}_{title.lower()}"
                    jobs.append({"title": title, "company": company, "link": link,
                                 "platform": "LinkedIn", "salary": "TBD",
                                 "seen_before": key in seen_set})
                    count += 1
                except Exception:
                    continue

            msg = f"💼 LinkedIn: {label} → {count} jobs found"
            if on_progress:
                on_progress(msg, pct)
            print(f"  {msg}")
            await asyncio.sleep(1.5)
        except Exception as e:
            msg = f"💼 LinkedIn: {label} → error ({str(e)[:40]})"
            if on_progress:
                on_progress(msg, pct)
            print(f"  {msg}")
    return jobs


async def scrape_indeed(client, seen_set, on_progress=None):
    """Scrape Indeed UAE job listings."""
    jobs = []
    searches = [
        ("area manager",       "area+manager"),
        ("operations manager", "operations+manager"),
        ("pharmacy manager",   "pharmacy+manager"),
        ("cluster manager",    "cluster+manager"),
        ("retail manager",     "retail+operations+manager"),
    ]
    n = len(searches)
    for i, (label, query) in enumerate(searches):
        pct = 60 + int(((i + 1) / n) * 10)
        try:
            url  = f"https://ae.indeed.com/jobs?q={query}&l=UAE&fromage=1"
            r    = await client.get(url)
            soup = BeautifulSoup(r.text, 'lxml')
            items = soup.select('.job_seen_beacon, [class*="jobCard"], .resultContent')
            count = 0
            for item in items[:15]:
                try:
                    title_el   = item.select_one('h2 a, h2 span[title]')
                    company_el = item.select_one('[data-testid="company-name"], .companyName')
                    if not title_el:
                        continue
                    title   = title_el.get_text(strip=True)
                    company = company_el.get_text(strip=True) if company_el else "Unknown"
                    a_tag   = item.select_one('h2 a')
                    href    = a_tag.get('href', '#') if a_tag else '#'
                    link    = fix_link(href, 'https://ae.indeed.com')
                    salary  = extract_salary(item.get_text())
                    key     = f"{company.lower()}_{title.lower()}"
                    if len(title) > 5 and company != "Unknown":
                        jobs.append({"title": title, "company": company, "link": link,
                                     "platform": "Indeed", "salary": salary,
                                     "seen_before": key in seen_set})
                        count += 1
                except Exception:
                    continue

            msg = f"🔍 Indeed: {label} → {count} jobs found"
            if on_progress:
                on_progress(msg, pct)
            print(f"  {msg}")
            await asyncio.sleep(1.5)
        except Exception as e:
            msg = f"🔍 Indeed: {label} → error ({str(e)[:40]})"
            if on_progress:
                on_progress(msg, pct)
            print(f"  {msg}")
    return jobs


# ── MAIN ──────────────────────────────────────────────────
def run(progress_callback=None):
    """Run full scrape + AI match pipeline.
    progress_callback(step: str, pct: int) is called throughout
    so the web dashboard can show a live progress bar.
    """
    def report(step, pct):
        print(f"[{pct:3d}%] {step}")
        if progress_callback:
            try:
                progress_callback(step, pct)
            except Exception:
                pass

    if not SHEET_ID:
        send_telegram("❌ SHEET_ID not set on Render — cannot save jobs. Aborting.")
        return 0
    if not ANTHROPIC_KEY:
        send_telegram("⚠️ ANTHROPIC_API_KEY not set — jobs will use default score 70.")

    report("🚀 Starting Job Hunter...", 2)
    send_telegram(f"🚀 Job Hunter started — {TODAY}\n"
                  f"Scanning Bayt, Naukrigulf, LinkedIn, Indeed...")
    print(f"\n{'='*50}\n🚀 Job Hunter Cloud — {TODAY}\n{'='*50}")

    report("📂 Loading previous jobs from Sheets...", 5)
    seen_set = load_seen_before()
    print(f"📂 {len(seen_set)} previously seen jobs loaded")

    async def scrape_all():
        async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True,
                                     timeout=30.0, verify=False) as client:
            # Bayt: 10% → 27%
            report("🏢 Searching Bayt...", 10)
            bayt_jobs = await scrape_bayt(client, seen_set, on_progress=report)

            # Naukrigulf: 27% → 44%
            report("🔎 Searching Naukrigulf...", 27)
            ng_jobs = await scrape_naukrigulf(client, seen_set, on_progress=report)

            # LinkedIn: 44% → 60%
            report("💼 Searching LinkedIn...", 44)
            li_jobs = await scrape_linkedin(client, seen_set, on_progress=report)

            # Indeed: 60% → 70%
            report("🔍 Searching Indeed...", 60)
            indeed_jobs = await scrape_indeed(client, seen_set, on_progress=report)

            all_jobs = bayt_jobs + ng_jobs + li_jobs + indeed_jobs
            report(f"✅ All platforms done — {len(all_jobs)} raw jobs collected", 70)
            return all_jobs

    report("🌐 Connecting to job boards...", 8)
    all_raw = asyncio.run(scrape_all())

    total_raw = len(all_raw)
    print(f"\n📊 Total scraped: {total_raw} — deduplicating + AI matching...")
    send_telegram(f"📊 Scraped {total_raw} jobs. Running AI match...")

    # Deduplicate before AI calls
    unique_jobs = []
    deduped = set()
    for job in all_raw:
        key = f"{job['title'].lower()}_{job['company'].lower()}"
        if (key not in deduped
                and len(job['title']) >= 8
                and job['company'] != "Unknown"):
            deduped.add(key)
            unique_jobs.append(job)

    total_unique = len(unique_jobs)
    report(f"🤖 AI matching {total_unique} unique jobs...", 72)

    all_apply = []
    for i, job in enumerate(unique_jobs):
        # Progress slides from 72% → 90% across the AI loop
        pct = 72 + int((i / max(total_unique, 1)) * 18)
        if i % 5 == 0 or i == total_unique - 1:
            short_title = job['title'][:35] + ('…' if len(job['title']) > 35 else '')
            report(f"🤖 AI matching {i+1}/{total_unique}: {short_title}", pct)

        if is_uae_national(job['title']):
            print(f"🚫 SKIP (UAE National) — {job['title']}")
            continue

        score, apply = match_job(job['title'], job['company'], job.get('salary', ''))
        if apply and score >= 60:
            tag = "👀 SEEN" if job.get('seen_before') else "🆕 NEW"
            print(f"  {tag} ({score}%) — {job['title']} @ {job['company']}")
            all_apply.append({**job, "score": score})
        else:
            print(f"  ❌ SKIP ({score}%) — {job['title']} @ {job['company']}")

    all_apply.sort(key=lambda x: -x['score'])

    report(f"💾 Saving {len(all_apply)} jobs to Google Sheets...", 91)
    save_to_sheets(all_apply)

    report("📱 Sending Telegram notification...", 96)
    send_telegram_job_list(all_apply)

    report(f"🎯 Done! {len(all_apply)} matching jobs saved", 100)
    print(f"\n🎯 DONE — {len(all_apply)} matching jobs saved")
    return len(all_apply)


if __name__ == "__main__":
    run()
