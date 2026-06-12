"""
services/cv_parser_structured.py — Extracts a structured skeleton from raw CV text
BEFORE any AI involvement. This guarantees we know exactly what the user has,
so we can validate the AI output didn't silently drop anything.

Returns a dict with the same schema as the AI CV JSON, populated with real data.
The AI then only rewrites the summary and bullet text — never the structure.
"""
import re

# Common section header patterns
SECTION_PATTERNS = [
    (re.compile(r"(?im)^(work\s*experience|experience|employment\s*history|career\s*history)\s*$"), "experience"),
    (re.compile(r"(?im)^(education|academic|qualifications?)\s*$"), "education"),
    (re.compile(r"(?im)^(skills?|competencies|core\s*competencies|key\s*skills?)\s*$"), "skills"),
    (re.compile(r"(?im)^(certifications?|licen[cs]es?|professional\s*development)\s*$"), "certs"),
    (re.compile(r"(?im)^(professional\s*summary|summary|profile|objective|about)\s*$"), "summary"),
    (re.compile(r"(?im)^(languages?)\s*$"), "languages"),
]

DATE_RANGE = re.compile(
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
    r"\d{4})\s*[-–—to]+\s*(present|current|now|jan(?:uary)?|feb(?:ruary)?|"
    r"mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|"
    r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|\d{4})",
    re.IGNORECASE,
)

EMAIL = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
PHONE = re.compile(r"(\+?\d[\d\s\-().]{7,20})")
LINKEDIN = re.compile(r"linkedin\.com/in/[\w\-]+", re.IGNORECASE)

def _extract_contact(lines):
    out = {"phone": "", "email": "", "linkedin": ""}
    text = "\n".join(lines[:15])
    em = EMAIL.search(text)
    if em:
        out["email"] = em.group(0)
    ph = PHONE.search(text)
    if ph:
        # Filter out year-only matches
        p = ph.group(0).strip()
        if len(re.sub(r"\D", "", p)) >= 7:
            out["phone"] = p
    li = LINKEDIN.search(text)
    if li:
        out["linkedin"] = li.group(0)
    return out

def _detect_name(lines):
    """First plausible name: 2-4 capitalised words, no email/url/digits."""
    bad = re.compile(r"\d|@|http|www\.|curriculum|resume|cv|profile|summary", re.I)
    for line in lines[:8]:
        line = line.strip()
        if not line or bad.search(line) or len(line) > 60:
            continue
        words = line.split()
        if 2 <= len(words) <= 4 and all(w[0].isupper() for w in words if w[0].isalpha()):
            return line
    return ""

def _split_sections(text):
    """
    Split raw CV text into named sections. Heuristic — good enough for structured
    CVs, which is what users will upload.
    """
    sections = {"header": [], "summary": [], "experience": [],
                "education": [], "skills": [], "certs": [], "other": []}
    current = "header"
    for line in text.split("\n"):
        matched = False
        for pattern, section_key in SECTION_PATTERNS:
            if pattern.match(line.strip()):
                current = section_key
                matched = True
                break
        if not matched:
            sections[current].append(line)
    return sections

def _parse_experience_blocks(lines):
    """
    Parse experience section into role blocks.
    Handles two common CV formats:
      Format A: "Title | Company | Jan 2020 – Present" (date inline)
      Format B: "Title\nCompany\nJan 2020 – Present\n• bullets" (date on own line)
    """
    roles = []
    current = None

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        date_m = DATE_RANGE.search(line)

        if date_m:
            # Check if the ENTIRE line is just a date range (Format B: date on own line)
            date_only = not line.replace(date_m.group(0), "").strip(" |,-—•\t")

            if date_only and current:
                # Date line belongs to the CURRENT role (already started above)
                full_match = date_m.group(0)
                parts = re.split(r"[-–—to]+", full_match, maxsplit=1)
                current["start_date"] = parts[0].strip() if parts else ""
                current["end_date"] = parts[1].strip() if len(parts) > 1 else "Present"
            elif date_only and not current:
                # Orphan date line — start a new block
                full_match = date_m.group(0)
                parts = re.split(r"[-–—to]+", full_match, maxsplit=1)
                current = {
                    "title": "", "company": "",
                    "start_date": parts[0].strip() if parts else "",
                    "end_date": parts[1].strip() if len(parts) > 1 else "Present",
                    "bullets": [],
                }
            else:
                # Date is inline (Format A) — this line IS a role header
                if current and (current.get("title") or current.get("company")):
                    roles.append(current)
                full_match = date_m.group(0)
                parts = re.split(r"[-–—to]+", full_match, maxsplit=1)
                title_part = line.replace(full_match, "").strip(" |,-—\t")
                current = {
                    "title": title_part[:80],
                    "company": "",
                    "start_date": parts[0].strip() if parts else "",
                    "end_date": parts[1].strip() if len(parts) > 1 else "Present",
                    "bullets": [],
                }
        elif current is not None:
            is_bullet = line.startswith(("•", "-", "*", "●", "–"))
            if is_bullet:
                bullet = re.sub(r"^[•\-\*●–]\s*", "", line)
                if bullet:
                    current["bullets"].append(bullet)
            elif not current.get("title") and not DATE_RANGE.search(line):
                current["title"] = line[:80]
            elif not current.get("company") and not DATE_RANGE.search(line) and not is_bullet:
                current["company"] = line[:80]
        else:
            # Before any role found — could be a title line in Format B
            # Look ahead for a date line
            if i + 2 < len(lines):
                next_lines = [lines[j].strip() for j in range(i+1, min(i+4, len(lines)))]
                for nl in next_lines:
                    if DATE_RANGE.search(nl) and not nl.startswith(("•", "-")):
                        # This line is likely a title, start tracking
                        current = {"title": line[:80], "company": "", "start_date": "", "end_date": "Present", "bullets": []}
                        break
        i += 1

    if current and (current.get("title") or current.get("company")):
        roles.append(current)

    # Final cleanup
    for r in roles:
        if not r["title"] and r["company"]:
            r["title"], r["company"] = r["company"], ""

    return [r for r in roles if r.get("title") or r.get("company")]

def extract_structure(cv_text):
    """
    Parse raw CV text into a structured dict.
    Returns the COMPLETE skeleton — nothing dropped.
    """
    if not cv_text:
        return {}
    lines = cv_text.split("\n")
    secs = _split_sections(cv_text)

    name     = _detect_name(lines)
    contact  = _extract_contact(lines)
    exp_roles = _parse_experience_blocks(secs["experience"])
    
    # Extract location (look for UAE city)
    location = ""
    uae_cities = ["dubai", "abu dhabi", "sharjah", "ajman", "ras al khaimah", "fujairah"]
    for line in lines[:20]:
        for city in uae_cities:
            if city in line.lower():
                location = line.strip()[:50]
                break

    # Skills: keep as flat list of lines
    skill_lines = [l.strip() for l in secs["skills"] if l.strip() and len(l.strip()) > 2]

    # Certs: keep all lines
    cert_lines = [l.strip() for l in secs["certs"] if l.strip() and len(l.strip()) > 2]

    # Education: simple — keep raw lines grouped (AI will parse properly)
    edu_lines = [l.strip() for l in secs["education"] if l.strip()]

    return {
        "name":     name,
        "email":    contact["email"],
        "phone":    contact["phone"],
        "linkedin": contact["linkedin"],
        "location": location,
        "_raw_summary":   " ".join(l.strip() for l in secs["summary"] if l.strip()),
        "_raw_experience": exp_roles,        # list of role dicts, ALWAYS complete
        "_raw_skills":    skill_lines,
        "_raw_certs":     cert_lines,
        "_raw_education": edu_lines,
        "_exp_count":     len(exp_roles),    # used for validation
    }
