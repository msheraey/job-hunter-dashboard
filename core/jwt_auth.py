"""
core/jwt_auth.py — Supabase JWT verification (HS256, project JWT secret).
Callers still pass user_id in the body; if a bearer token is present we
verify it actually belongs to that user_id. With REQUIRE_AUTH=true, a
missing or invalid token is rejected outright instead of falling back to
the unverified body user_id.
"""
import base64
import logging
import jwt
import config

logger = logging.getLogger(__name__)


def _decode_secret(raw: str) -> bytes:
    """Supabase JWT secret is base64url-encoded. Decode to raw bytes for PyJWT.
    Falls back to UTF-8 if not base64url.
    """
    try:
        padded = raw + "=" * (-len(raw) % 4)
        return base64.urlsafe_b64decode(padded)
    except Exception:
        return raw.encode("utf-8")


def verify_jwt(token: str):
    """Decode and verify a Supabase JWT. Returns the sub (user id) or None."""
    if not token or not config.SUPABASE_JWT_SECRET:
        return None
    try:
        payload = jwt.decode(
            token,
            _decode_secret(config.SUPABASE_JWT_SECRET),
            algorithms=["HS256"],
            audience="authenticated",
            options={"verify_aud": True},
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
    """Return (user_id, error_response_or_None)."""
    from flask import jsonify
    claimed = body.get("user_id")
    token = _bearer_token(request)
    # If no JWT secret is configured we cannot verify tokens, so treat the
    # request the same as if no token was sent (respecting REQUIRE_AUTH).
    if not token or not config.SUPABASE_JWT_SECRET:
        if config.REQUIRE_AUTH:
            return None, (jsonify({"error": "authorization required"}), 401)
        return claimed, None
    verified = verify_jwt(token)
    if not verified:
        return None, (jsonify({"error": "invalid or expired token"}), 401)
    if claimed and claimed != verified:
        return None, (jsonify({"error": "token does not match user_id"}), 403)
    return verified, None
