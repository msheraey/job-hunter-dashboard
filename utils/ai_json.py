"""
utils/ai_json.py — Shared defensive JSON extraction for AI responses.
Models wrap JSON in markdown fences or chatty prose; this strips both.
"""
import re
import json


def extract_json(text):
    """Best-effort extraction of a JSON object/array from raw model output.
    Returns the parsed value, or None if nothing parseable was found."""
    if not text:
        return None
    cleaned = re.sub(r"```json|```", "", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    m = re.search(r"(\{.*\}|\[.*\])", cleaned, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None
