"""
prompts.py — Every AI prompt in the system, in one place.
Iterate on prompt quality here without touching business logic.
"""

def scoring_prompt(job_title, company, description, user_profile, industries):
    return f"""You are a UAE job matching expert. Score this job against the candidate.

JOB:
Title: {job_title}
Company: {company}
Description: {(description or 'Not provided')[:1200]}

CANDIDATE:
{user_profile[:1500]}

Scoring guide:
90-100: Candidate meets ALL core requirements with direct experience
70-89: Meets most requirements, minor gaps
50-69: Relevant background but missing key requirements
30-49: Partial match, significant gaps
0-29: Poor fit

Return ONLY valid JSON (no markdown):
{{"score": 0-100, "industry": "one of: {industries}", "match_bullets": ["job requires X → candidate has Y (cite actual evidence)", "...up to 5 items"], "gap_bullets": ["job requires X → candidate lacks it", "...up to 4 items, empty array if no gaps"], "seniority": "entry/mid/senior/director", "remote": "onsite/hybrid/remote/unknown", "visa_likelihood": "high/medium/low"}}

Rules: Each bullet must name the specific requirement from the job AND the matching (or missing) evidence from the candidate. No generic phrases. gap_bullets = [] if no significant gaps."""


def synonym_prompt(title):
    return f"""Generate 3 alternative job titles a UAE job seeker searching "{title}" should also search.

Rules:
- Same role, different naming convention only
- 2-4 words maximum per title — short titles only
- Must be titles actually posted on LinkedIn, Indeed, Bayt, or Naukrigulf
- No invented compound phrases, no descriptions, no industry qualifiers
- If the original is already short/common, return closely related standard variants only

Return ONLY a JSON array of 3 strings, no markdown: ["title1","title2","title3"]"""


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
7. Use "Dear {company} Team," if no hiring manager name available

Return ONLY valid JSON — no markdown, no preamble:
{{"recipient": "Dear {company} Team,", "para1": "...", "para2": "...", "para3": "...", "closing": "Yours sincerely"}}"""


def tailored_cv_prompt(user_profile, cv_text, job, parsed_structure=None):
    title = job.get('title', '')
    company = job.get('company', '')
    description = (job.get('description') or '')[:2500]

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
        exp_block = (cv_text or '')[:8000]
        exp_count = cv_text.count("\n") // 8 if cv_text else 0

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
{(cv_text or '')[:5000]}

STEP 1 — KEYWORD EXTRACTION (do this mentally before writing):
Identify the 10-15 most important keywords from the job description: required skills, tools,
methodologies, certifications, and domain terms (e.g. "CRM", "P&L management", "B2B sales",
"SAP", "agile", "KPI tracking"). For each keyword, decide if the candidate's actual experience
covers it. If yes, it MUST appear naturally in their bullets or skills section.

ABSOLUTE RULES — these are non-negotiable:
1. INCLUDE EVERY ROLE listed above — you must output exactly {exp_count} experience items. Removing any role is forbidden.
2. INCLUDE all education, certifications, and qualifications exactly as provided — do not drop any.
3. REORDER bullets within each role so the most job-relevant achievements come first.
4. REWRITE bullet text to be stronger and ATS-optimised — use exact keywords from the job
   description wherever the candidate genuinely has that experience. Keep all real facts, numbers, dates.
5. Professional Summary (2-3 sentences): name-drop the job title, highlight the candidate's
   most relevant experience, and include 2-3 keywords from the job description.
6. Skills section: list every keyword from the job description that the candidate genuinely has.
   Group as core skills, tools/software, and languages. Do not invent skills.
7. Do NOT invent experience, companies, dates, qualifications, or skills.
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
    return f"""You are an ATS (Applicant Tracking System) analyzer. Compare this CV against the job posting and give a detailed breakdown.

JOB: {job.get('title')} at {job.get('company')}
Description: {(job.get('description') or '')[:1200]}

CV:
{(cv_text or '')[:3000]}

ATS score guide:
90-100 = Excellent — strong keyword match, all requirements met
70-89  = Good — most requirements met, minor gaps
50-69  = Fair — some relevant experience but key gaps
30-49  = Weak — missing several core requirements
0-29   = Poor — significant mismatch

Return ONLY valid JSON:
{{
  "ats_score": 0-100,
  "label": "Excellent or Good or Fair or Weak or Poor",
  "score_breakdown": {{
    "keyword_match": 0-100,
    "experience_match": 0-100,
    "skills_match": 0-100,
    "education_match": 0-100
  }},
  "missing_keywords": ["keyword in job description that is absent from the CV — up to 8 items"],
  "strengths": ["specific thing the CV does well for this exact role — 3 items"],
  "improvements": ["specific, actionable change that would raise the ATS score — 3 items"]
}}"""


def salary_estimate_prompt(job):
    return f"""Estimate the monthly salary range in AED for this UAE job. Use your knowledge of the UAE market.

JOB: {job.get('title')} at {job.get('company')}
Location: {job.get('location', 'UAE')}
Description: {(job.get('description') or '')[:600]}
Listed salary: {job.get('salary', 'Not specified')}

Return ONLY valid JSON:
{{"min_aed": number, "max_aed": number, "confidence": "high/medium/low", "basis": "one sentence on what this is based on"}}"""


def red_flags_prompt(job, search_snippets=""):
    return f"""Analyze this UAE job posting for red flags (scam signals, exploitative terms, vague employers, unrealistic promises, fee requests, commission-only traps).

JOB: {job.get('title')} at {job.get('company')}
Platform: {job.get('platform', '')}
Description: {(job.get('description') or '')[:1000]}
{f'WEB CONTEXT: {search_snippets[:800]}' if search_snippets else ''}

Return ONLY valid JSON:
{{"risk_level": "low/medium/high", "flags": ["each specific concern found — empty list if clean"], "positives": ["trust signals found"], "advice": "one sentence recommendation"}}"""


def interview_prep_prompt(job, user_profile):
    return f"""Generate interview preparation for this UAE job application.

JOB: {job.get('title')} at {job.get('company')}
Description: {(job.get('description') or '')[:800]}

CANDIDATE: {user_profile[:600]}

Include exactly 6 likely_questions covering: 2 role-specific technical questions, 2 behavioural STAR-method questions, 1 salary negotiation question, 1 culture/team fit question.
All questions and answers must be specific to THIS role and company — no generic placeholders.

Return ONLY valid JSON — no markdown, no explanation:
{{
  "likely_questions": [
    {{"q": "specific interview question", "approach": "one-sentence answer strategy tailored to this candidate's background"}}
  ],
  "questions_to_ask": [
    "smart, specific question for the interviewer that shows research into this role",
    "second smart question",
    "third smart question"
  ],
  "key_selling_points": [
    "specific strength this candidate has that directly matches this role",
    "second specific strength",
    "third specific strength"
  ]
}}"""


def job_summary_prompt(job):
    return f"""Summarize this job posting in exactly 3 bullet points. Each bullet must be a concrete, specific fact. Focus on: what the role does day-to-day, what core requirements are needed, and what makes this opportunity notable.

JOB: {job.get('title')} at {job.get('company')}
Location: {job.get('location', 'UAE')}
Description: {(job.get('description') or '')[:1200]}

Return ONLY a JSON array of exactly 3 strings — no markdown:
["bullet describing primary responsibility", "bullet describing key requirements", "bullet describing opportunity or notable aspect"]"""


def skills_gap_prompt(missing_keywords_list, target_titles):
    keywords_text = "\n".join(f"- {kw}" for kw in missing_keywords_list[:40])
    return f"""Analyze this job seeker's skills gaps based on what is consistently missing across their job applications.

TARGET ROLES: {', '.join(target_titles[:5])}

KEYWORDS MISSING FROM CV (appearing in job requirements):
{keywords_text}

Return ONLY valid JSON:
{{
  "critical_gaps": ["skill or tool missing from 3+ job requirements — top 5 most impactful"],
  "nice_to_have": ["helpful but not critical skill — top 3"],
  "quick_wins": ["specific certification or short course that closes a critical gap — top 3"],
  "estimated_impact": "one sentence on how addressing the top 2 gaps would change match scores"
}}"""


def company_research_prompt(company, job_title):
    return f"""You are a UAE job market researcher. Provide factual information about this company for a job applicant.

Company: {company}
Role being applied for: {job_title}

Return ONLY valid JSON:
{{
  "overview": "2-sentence company overview from your knowledge",
  "industry": "industry sector",
  "uae_presence": "description of UAE operations if known, otherwise 'Information not available'",
  "culture_notes": "one sentence on culture/work environment if known",
  "interview_style": "typical interview process for this type of company if known"
}}"""
