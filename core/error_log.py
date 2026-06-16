"""
core/error_log.py — Fire-and-forget error capture for failures outside a
RunLogger-backed batch run. Never raises; never put PII or secrets in context.
"""
from datetime import datetime, timezone
from core.db import safe_insert

def log_error(source, message, context=None):
    safe_insert("error_log", {
        "source": source,
        "message": str(message)[:500],
        "context": str(context)[:500] if context else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }, label="error_log")
