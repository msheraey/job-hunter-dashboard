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
