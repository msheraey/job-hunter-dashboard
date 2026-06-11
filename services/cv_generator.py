"""
services/cv_generator.py — Tailored CV + cover letter via the AI chain.
Delimiter parsing (robust) with JSON fallback for older responses.
"""
import re
import json
import prompts
from services.scorer import ai_complete

def generate_cv_cover_letter(user, job):
    prompt = prompts.cv_cover_letter_prompt(
        user.get("profile_summary", ""), user.get("cv_text", ""), job)
    content = ai_complete(prompt, label="cv_generation")
    if not content:
        return "", ""
    cover, cv = "", ""
    if "===COVER_LETTER===" in content and "===TAILORED_CV===" in content:
        after = content.split("===COVER_LETTER===", 1)[1]
        cover = after.split("===TAILORED_CV===", 1)[0].strip()
        cv = after.split("===TAILORED_CV===", 1)[1].split("===END===", 1)[0].strip()
    if not cover and not cv:
        try:
            data = json.loads(re.sub(r"```json|```", "", content).strip())
            cover = data.get("cover_letter", "")
            cv = data.get("tailored_cv", "")
        except (json.JSONDecodeError, AttributeError):
            pass
    if not cover and not cv and content.strip():
        cover = content.strip()
    return cover, cv
