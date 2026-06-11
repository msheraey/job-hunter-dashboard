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

def cv_cover_letter_prompt(user_profile, cv_text, job):
    return f"""You are an expert UAE career writer. Write a tailored cover letter and tailored CV for this application.

JOB: {job.get('title')} at {job.get('company')}
Location: {job.get('location', 'UAE')}
Description: {(job.get('description') or '')[:800]}

CANDIDATE PROFILE:
{user_profile}

CANDIDATE CV:
{(cv_text or '')[:2500]}

Format response EXACTLY:
===COVER_LETTER===
(full cover letter, 3-4 short paragraphs)
===TAILORED_CV===
(full tailored CV)
===END==="""

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
