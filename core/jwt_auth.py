"""
core/jwt_auth.py — Auth stub: returns user_id from the request body.
JWT verification removed; re-add when RLS / stricter auth is needed.
"""


def resolve_user_id(body, request):
    """Return (user_id, error_response_or_None)."""
    return body.get("user_id"), None
