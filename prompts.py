"""
prompts.py — Every AI prompt in the system, in one place.
Iterate on prompt quality here without touching business logic.
"""

def scoring_prompt(job_title, company, description, user_profile, industries):
    return f"""You are a job matching expert for the UAE market. Score this job against the candidate and classify the job.

JOB:
Title: {job_title}
Company: {company}
Description: {(description or 'Not provided')[:500]}

CANDIDATE:
{user_profile[:800]}

Return ONLY JSON (no markdown):
{{"score": 0-100, "industry": "one of: {industries}", "reason": "why this score, under 15 words", "seniority": "entry/mid/senior/director", "remote": "onsite/hybrid/remote/unknown", "visa_likelihood": "high/medium/low"}}"""

def synonym_prompt(title):
    return f"""Generate 3 alternative job titles a UAE job seeker searching "{title}" should also search. Same role, different naming. Return ONLY a JSON array of strings, no markdown. Example: ["title1","title2","title3"]"""

def cover_letter_prompt(user_profile, cv_text, job):
    title = job.get('title', '')
    company = job.get('company', '')
    location = job.get('location', 'UAE')
    description = (job.get('description') or '')[:1200]
    return f"""You are a senior UAE career consultant. Write a targeted cover letter for this application.

JOB:
Title: {title}
Company: {company}
Location: {location}
Description: {description}

CANDIDATE PROFILE:
{user_profile[:600]}

CANDIDATE CV:
{(cv_text or '')[:1500]}

STRICT RULES:
1. THREE paragraphs only
2. Para 1 (2-3 sentences): Open with a specific, concrete hook about THIS company or role challenge — NOT a generic opener
3. Para 2 (3-4 sentences): 2-3 SPECIFIC achievements with real numbers (team size, branch count, revenue, %). If career transition, explicitly name the transferable skill and why it applies here
4. Para 3 (2 sentences): What you bring to the first 90 days + one-line close
5. BANNED phrases — using any = automatic rejection:
   "I am excited to apply", "I am writing to express", "proven track record", "I am confident that",
   "I would be a great fit", "passionate about", "dynamic", "leverage my skills", "results-driven",
   "I am pleased to", "further my career", "align with my goals", "strong background"
6. Total: 180-220 words. Tone matches the company (tech = sharp/data-driven; traditional = professional)
7. Use "Dear {{company}} Team," if no hiring manager name available

Return ONLY valid JSON — no markdown, no preamble:
{{"recipient": "Dear {company} Team,", "para1": "...", "para2": "...", "para3": "...", "closing": "Yours sincerely"}}"""

def tailored_cv_prompt(user_profile, cv_text, job, parsed_structure=None):
    title = job.get('title', '')
    company = job.get('company', '')
    description = (job.get('description') or '')[:1200]

    # Build the experience block from parsed structure if available
    exp_block = ""
    exp_count = 0
    if parsed_structure and parsed_structure.get("_raw_experience"):
        roles = parsed_structure["_raw_experience"]
        exp_count = len(roles)
        lines = []
        for r in roles:
            lines.append(f"ROLE: {r.get('title','')} | {r.get('company','')} | {r.get('start_date','')} – {r.get('end_date','Present')}")
            for b in (r.get("bullets") or []):
                lines.append(f"  • {b}")
        exp_block = "\n".join(lines)
    else:
        exp_block = (cv_text or '')[:6000]
        exp_count = cv_text.count("\n") // 8 if cv_text else 0  # rough estimate

    return f"""You are an expert ATS-optimised CV writer for the UAE job market.
Your task is to TAILOR this candidate's CV for a specific role. You are REWRITING, not filtering.

TARGET ROLE:
Title: {title}
Company: {company}
Description: {description}

CANDIDATE PROFILE:
{user_profile[:600]}

CANDIDATE'S COMPLETE WORK HISTORY (ALL {exp_count} ROLES — you MUST include every single one):
{exp_block}

ADDITIONAL CV DATA:
{(cv_text or '')[:3000]}

ABSOLUTE RULES — these are non-negotiable:
1. INCLUDE EVERY ROLE listed above — you must output exactly {exp_count} experience items. Removing any role is forbidden.
2. INCLUDE all education, certifications, and qualifications exactly as provided — do not drop any.
3. You may REORDER bullets within a role to put the most job-relevant achievements first.
4. You may REWRITE bullet text to be stronger and more relevant — but preserve all real facts, numbers, and dates.
5. Write a tailored Professional Summary (2-3 sentences) highlighting what makes this candidate right for THIS role specifically. If it is a career pivot, frame the transferable skills as a strength.
6. Skills section: include keywords from the job description that the candidate genuinely has.
7. Do NOT invent experience, companies, dates, or qualifications.
8. UAE-standard format: no photo reference, no nationality, no date of birth.

Return ONLY valid JSON — no markdown, no preamble, no explanation:
{{
  "name": "Full Name from CV",
  "phone": "phone from CV",
  "email": "email from CV",
  "linkedin": "linkedin from CV or empty string",
  "location": "City, UAE",
  "summary": "2-3 sentence tailored summary",
  "experience": [
    {{
      "title": "exact job title from CV",
      "company": "exact company name from CV",
      "location": "city from CV",
      "start_date": "exact date from CV",
      "end_date": "exact date or Present",
      "bullets": ["rewritten bullet with metric", "rewritten bullet"]
    }}
  ],
  "education": [
    {{"degree": "exact degree from CV", "institution": "exact institution from CV", "year": "exact year"}}
  ],
  "certifications": [
    {{"name": "exact cert name", "issuer": "exact issuer", "year": "year"}}
  ],
  "skills": {{
    "core": ["skill1", "skill2"],
    "technical": ["tool1", "tool2"],
    "languages": ["Arabic (Native)", "English (Fluent)"]
  }}
}}"""

def ats_score_prompt(cv_text, job):
    return f"""You are an ATS (Applicant Tracking System) analyzer. Compare this CV against the job posting.

JOB: {job.get('title')} at {job.get('company')}
Description: {(job.get('description') or '')[:1000]}

CV:
{(cv_text or '')[:2500]}

Return ONLY JSON:
{{"ats_score": 0-100, "missing_keywords": ["up to 8 keywords from the job missing in the CV"], "strengths": ["3 things the CV does well for this job"], "improvements": ["3 specific changes to raise the score"]}}"""

def salary_estimate_prompt(job):
    return f"""Estimate the monthly salary range in AED for this UAE job. Use your knowledge of the UAE market.

JOB: {job.get('title')} at {job.get('company')}
Location: {job.get('location', 'UAE')}
Description: {(job.get('description') or '')[:600]}

Return ONLY JSON:
{{"min_aed": number, "max_aed": number, "confidence": "high/medium/low", "basis": "one sentence on what this is based on"}}"""

def red_flags_prompt(job, search_snippets=""):
    return f"""Analyze this UAE job posting for red flags (scam signals, exploitative terms, vague employers, unrealistic promises, fee requests, commission-only traps).

JOB: {job.get('title')} at {job.get('company')}
Platform: {job.get('platform', '')}
Description: {(job.get('description') or '')[:1000]}
{f'WEB CONTEXT: {search_snippets[:800]}' if search_snippets else ''}

Return ONLY JSON:
{{"risk_level": "low/medium/high", "flags": ["each specific concern found, empty list if clean"], "positives": ["trust signals found"], "advice": "one sentence recommendation"}}"""

def interview_prep_prompt(job, user_profile):
    return f"""Generate interview preparation for this UAE job application.

JOB: {job.get('title')} at {job.get('company')}
Description: {(job.get('description') or '')[:800]}

CANDIDATE: {user_profile[:600]}

Return ONLY JSON:
{{"likely_questions": [{{"q": "question", "approach": "how to answer in one sentence"}}] (6 questions: 2 role-specific, 2 behavioral, 1 salary, 1 culture), "questions_to_ask": ["3 smart questions for the interviewer"], "key_selling_points": ["3 things this candidate should emphasize"]}}"""
