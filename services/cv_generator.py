"""
services/cv_generator.py — CV + cover letter generation with completeness guarantee.

Flow:
  1. Parse CV text into a complete skeleton (cv_parser_structured)
  2. Pass skeleton + full CV text to AI for tailoring (rewrite, never filter)
  3. Validate AI output: if any roles missing, re-inject from skeleton
  4. Render to DOCX via docx_builder

Token budgets (critical — 200 was causing systematic truncation):
  Cover letter: 900 tokens  (JSON with 3 paragraphs ~400-600 tokens)
  Tailored CV:  2800 tokens (full JSON with all roles/bullets ~1200-2500 tokens)
"""
import re
import prompts
from services.scorer import ai_complete
from services.docx_builder import build_cv, build_cover_letter
from services.cv_parser_structured import extract_structure
from utils.ai_json import extract_json as _parse_json

CV_MAX_TOKENS = 3200
CL_MAX_TOKENS = 900


def _validate_and_repair(ai_data, parsed, user):
    if not ai_data:
        ai_data = {}
    for field in ("name", "phone", "email", "linkedin", "location"):
        if not ai_data.get(field) and parsed.get(field):
            ai_data[field] = parsed[field]
    if not ai_data.get("name") and user.get("name"):
        ai_data["name"] = user["name"]
    if not ai_data.get("email") and user.get("email"):
        ai_data["email"] = user["email"]

    original_roles = parsed.get("_raw_experience") or []
    ai_roles = ai_data.get("experience") or []
    # Key on (title, company) so two roles at the same company are treated as distinct
    ai_role_keys = {
        ((r.get("title") or "").lower().strip(), (r.get("company") or "").lower().strip())
        for r in ai_roles
    }
    required = len(original_roles)
    got = len(ai_roles)
    if got < required:
        print(f"  ⚠️ CV repair: AI returned {got}/{required} roles — re-injecting missing")
        for orig in original_roles:
            key = ((orig.get("title") or "").lower().strip(), (orig.get("company") or "").lower().strip())
            if key not in ai_role_keys:
                ai_roles.append({
                    "title": orig.get("title", ""),
                    "company": orig.get("company", ""),
                    "location": "",
                    "start_date": orig.get("start_date", ""),
                    "end_date": orig.get("end_date", "Present"),
                    "bullets": orig.get("bullets") or [],
                })
                ai_role_keys.add(key)
        ai_data["experience"] = ai_roles

    if not ai_data.get("education") and parsed.get("_raw_education"):
        ai_data["education"] = [{"degree": l, "institution": "", "year": ""} for l in parsed["_raw_education"][:6]]
    if not ai_data.get("certifications") and parsed.get("_raw_certs"):
        ai_data["certifications"] = [{"name": l, "issuer": "", "year": ""} for l in parsed["_raw_certs"][:8]]
    if not ai_data.get("skills") and parsed.get("_raw_skills"):
        ai_data["skills"] = {"core": parsed["_raw_skills"][:8], "technical": [], "languages": []}
    return ai_data


def _safe_name(user, job):
    name_slug = re.sub(r"[^a-zA-Z0-9]", "_", (user.get("name") or "candidate").strip())
    co_slug = re.sub(r"[^a-zA-Z0-9]", "_", (job.get("company") or "")[:20])
    return name_slug, co_slug


def generate_cover_letter_docx(user, job):
    profile = user.get("profile_summary", "")
    cv_text = user.get("cv_text", "")
    raw = ai_complete(prompts.cover_letter_prompt(profile, cv_text, job),
                      label="cover_letter", max_tokens=CL_MAX_TOKENS)
    data = _parse_json(raw)
    if not data or not any(data.get(k) for k in ("para1", "para2", "para3")):
        print(f"  ⚠️ Cover letter parse failed — raw: {str(raw)[:200]}")
        return None, None, ""
    name_slug, co_slug = _safe_name(user, job)
    try:
        docx_bytes = build_cover_letter(data, user)
    except Exception as e:
        print(f"  ❌ Cover letter DOCX build failed: {e}")
        return None, None, ""
    plain = "\n\n".join(filter(None, [
        data.get("recipient", ""), data.get("para1", ""),
        data.get("para2", ""), data.get("para3", ""),
        data.get("closing", "Yours sincerely,"), user.get("name", ""),
    ]))
    return docx_bytes, f"{name_slug}_Cover_Letter_{co_slug}.docx", plain


def generate_cv_docx(user, job):
    profile = user.get("profile_summary", "")
    cv_text = user.get("cv_text", "")
    if not cv_text and not profile:
        return None, None, ""
    parsed = extract_structure(cv_text) if cv_text else {}
    raw = ai_complete(prompts.tailored_cv_prompt(profile, cv_text, job, parsed_structure=parsed),
                      label="tailored_cv", max_tokens=CV_MAX_TOKENS)
    data = _validate_and_repair(_parse_json(raw) or {}, parsed, user)
    name_slug, co_slug = _safe_name(user, job)
    try:
        docx_bytes = build_cv(data)
    except Exception as e:
        print(f"  ❌ CV DOCX build failed: {e}")
        return None, None, ""
    plain = f"{data.get('name', '')} — {job.get('title', '')} at {job.get('company', '')}"
    return docx_bytes, f"{name_slug}_CV_{co_slug}.docx", plain


def generate_cv_cover_letter(user, job):
    _, _, cl = generate_cover_letter_docx(user, job)
    _, _, cv = generate_cv_docx(user, job)
    return cl, cv
