"""
services/synonyms.py — Semantic title expansion.
When a user adds a title, AI generates up to 3 synonym titles and adds them
to the pool linked to the same user — one scrape covers naming variants.
Controlled by SEMANTIC_EXPAND flag.
"""
import re
import json
import config
import prompts
from services.scorer import ai_complete
from utils.filters import validate_title, normalize_title
from core.db import safe_select, safe_insert

def expand_title(title):
    """Return up to 3 validated synonym titles (may be empty on AI failure)."""
    if not config.SEMANTIC_EXPAND:
        return []
    text = ai_complete(prompts.synonym_prompt(title), label="synonyms", lane="interactive")
    if not text:
        return []
    cleaned = re.sub(r"```json|```", "", text).strip()
    m = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    out = []
    seen = {normalize_title(title)}
    for t in arr:
        if isinstance(t, str) and validate_title(t) and normalize_title(t) not in seen:
            seen.add(normalize_title(t))
            out.append(t.strip())
    return out[:3]

def link_user_title(user_id, title_row):
    existing = safe_select("user_titles", user_id=user_id, title_id=title_row["id"])
    if not existing:
        safe_insert("user_titles", {"user_id": user_id, "title_id": title_row["id"]})
