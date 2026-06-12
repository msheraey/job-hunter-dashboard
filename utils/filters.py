"""
utils/filters.py — All text filtering: junk titles, nationality, gender,
normalization, validation. Pure functions, zero dependencies, fully testable.
"""
import re

JUNK_PATTERNS = [
    re.compile(r"jobs in (uae|dubai|abu dhabi|sharjah).*(20\d\d)", re.I),
    re.compile(r"\d+\+?\s+(jobs|vacancies)", re.I),
    re.compile(r"^\d+\s+(jobs|vacancies)\s*$", re.I),
    re.compile(r"'s post", re.I),
    re.compile(r"jobs?,\s+employment", re.I),
]
NATIONALITY_SKIP = ["UAEN", "UAE NATIONAL", "EMIRATI", "NATIONAL ONLY"]
FEMALE_ONLY = [re.compile(p, re.I) for p in [r"\bfemale(s)?\s+only\b", r"\bladies\s+only\b", r"\bfemale\s+candidates?\s+only\b", r"\bonly\s+female(s)?\b"]]
MALE_ONLY   = [re.compile(p, re.I) for p in [r"\bmale(s)?\s+only\b", r"\bgentlemen\s+only\b", r"\bmale\s+candidates?\s+only\b", r"\bonly\s+male(s)?\b"]]

def is_junk(title):
    return any(p.search(title) for p in JUNK_PATTERNS)

def is_nationality_restricted(title):
    return any(kw in title.upper() for kw in NATIONALITY_SKIP)

def is_gender_restricted(text, user_gender):
    if not user_gender or user_gender == "prefer_not_to_say":
        return False
    t = text or ""
    if user_gender == "male":
        return any(p.search(t) for p in FEMALE_ONLY)
    if user_gender == "female":
        return any(p.search(t) for p in MALE_ONLY)
    return False

def normalize_title(title):
    return re.sub(r"\s+", " ", title.strip().lower())

def validate_title(title):
    t = title.strip()
    return 3 <= len(t) <= 80 and bool(re.search(r"[a-zA-Z]", t))

def make_fingerprint(title, company, location):
    fp = f"{normalize_title(title)}|{(company or '').lower()}|{(location or 'UAE').lower()}"
    return re.sub(r"[^a-z0-9|]", "", fp)[:200]

# ── Industry inference ──────────────────────────────────────
INDUSTRY_KEYWORDS = {
    "Healthcare & Pharmacy": ["pharmacist","pharmacy","nurse","doctor","clinical","hospital",
        "medical","healthcare","patient","clinic","dental","radiology","lab","technician"],
    "Technology": ["developer","software","data","analyst","it support","programmer","devops",
        "cloud","cybersecurity","network","system","database","api","frontend","backend","full stack"],
    "Retail": ["retail","store","shop","merchandise","cashier","visual merchandising","floor manager"],
    "FMCG": ["fmcg","consumer goods","brand manager","trade marketing","modern trade"],
    "Finance & Banking": ["accountant","finance","bank","audit","tax","treasury","credit","risk",
        "investment","controller","payable","receivable","cfo"],
    "Logistics & Supply Chain": ["logistics","supply chain","warehouse","inventory","procurement",
        "purchase","shipping","freight","transport","distribution","driver","fleet"],
    "Hospitality & Tourism": ["hotel","restaurant","catering","tourism","travel","chef",
        "waiter","bartender","front desk","resort","guest service","f&b"],
    "Real Estate": ["real estate","property","leasing","broker","valuation","facility"],
    "Automotive": ["automotive","vehicle","dealership","mechanic","service advisor","parts"],
    "Education": ["teacher","professor","instructor","education","school","university",
        "trainer","faculty","academic","curriculum","learning"],
    "Construction & Engineering": ["civil","construction","architect","engineer","site manager",
        "quantity surveyor","structural","electrical","mechanical","project manager"],
    "Media & Marketing": ["marketing","social media","content","seo","digital","brand",
        "advertising","campaign","communications","pr","copywriter"],
    "HR & Recruitment": ["hr","human resources","recruitment","talent","hiring",
        "recruiter","payroll","employee","onboarding","people"],
}

def infer_industry(title="", description=""):
    """Keyword fallback — used when AI scoring does not return an industry."""
    text = f"{title} {description}".lower()
    scores = {}
    for industry, words in INDUSTRY_KEYWORDS.items():
        hits = sum(1 for w in words if w in text)
        if hits:
            scores[industry] = hits
    return max(scores, key=scores.get) if scores else "Other"
