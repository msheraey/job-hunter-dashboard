"""
core/jwt_auth.py — Supabase JWT verification (HS256, project JWT secret).
Lenient/transitional: callers still pass user_id in the body; if a bearer
token is present we verify it actually belongs to that user_id. Once the
frontend reliably sends tokens and REQUIRE_AUTH=true, missing/invalid
tokens are rejected outright instead of silently falling back.
"""
import jwt
import config


def verify_jwt(token):
    """Decode + verify a Supabase access token. Returns the `sub` (auth UID) or None."""
    if not token or not config.SUPABASE_JWT_SECRET:
        return None
    try:
        payload = jwt.decode(
            token, config.SUPABASE_JWT_SECRET,
            algorithms=["HS256"], audience="authenticated",
        )
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


def _bearer_token(request):
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer "):].strip()
    return None


def resolve_user_id(body, request):
    """Return (user_id, error_response_or_None).

    - No token present → fall back to body.user_id (legacy/transitional).
    - Token present but invalid/expired → reject.
    - Token present and valid but doesn't match claimed body.user_id → reject.
    """
    claimed = body.get("user_id")
    token = _bearer_token(request)
    if not token:
        return claimed, None
    verified = verify_jwt(token)
    if not verified:
        return None, ({"error": "invalid or expired token"}, 401)
    if claimed and claimed != verified:
        return None, ({"error": "token does not match user_id"}, 403)
    return verified, None
