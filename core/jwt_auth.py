"""
core/jwt_auth.py — Supabase JWT verification (HS256, project JWT secret).
Callers still pass user_id in the body; if a bearer token is present we
verify it actually belongs to that user_id. With REQUIRE_AUTH=true, a
missing or invalid token is rejected outright instead of falling back to
the unverified body user_id.
 
Fix notes (2026-06-21):
  - Supabase JWT secrets are base64url-encoded strings. PyJWT needs the
      raw bytes, so we decode the secret before passing it to jwt.decode().
        - Added options={"verify_aud": True} explicitly (already default in
            PyJWT ≥ 2.x, but stated clearly for readability).
              - Wrapped decode in a second try/except that logs the specific error
                  so Railway logs show *why* a token was rejected (expired, bad sig, etc.)
                      rather than silently returning None.
                        - REQUIRE_AUTH env-var check unchanged.
                        """
import base64
import logging
import jwt
import config

logger = logging.getLogger(__name__)


def _decode_secret(raw: str) -> bytes:
        """Supabase JWT secret is base64url-encoded.  Decode it to raw bytes
            for PyJWT.  If decoding fails (plain-text secret), fall back to UTF-8
                so the function works with both formats."""
        try:
                    # Add padding if needed
                    padded = raw + "=" * (-len(raw) % 4)
                    return base64.urlsafe_b64decode(padded)
        except Exception:
          return raw.encode("utf-8")


def verify_jwt(token: str):
        """Decode + verify a Supabase access token.
            Returns the `sub` (auth UID) on success, or None on any failure.
                """
        if not token or not config.SUPABASE_JWT_SECRET:
                    if not config.SUPABASE_JWT_SECRET:
                                    logger.warning("SUPABASE_JWT_SECRET is not set — cannot verify JWT")
                                return None
                secret_bytes = _decode_secret(config.SUPABASE_JWT_SECRET)
    try:
                payload = jwt.decode(
                                token,
                                secret_bytes,
                                algorithms=["HS256"],
                                audience="authenticated",
                                options={"verify_aud": True},
                )
        return payload.get("sub")
except jwt.ExpiredSignatureError:
        logger.info("JWT rejected: token has expired")
except jwt.InvalidAudienceError:
        logger.warning("JWT rejected: audience mismatch (expected 'authenticated')")
except jwt.InvalidSignatureError:
        logger.warning("JWT rejected: signature verification failed — check SUPABASE_JWT_SECRET")
except jwt.PyJWTError as exc:
        logger.warning("JWT rejected: %s", exc)
    return None


def _bearer_token(request):
        header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
                return header[len("Bearer "):].strip()
    return None


def resolve_user_id(body, request):
        """Return (user_id, error_response_or_None).

            - No token present:
                    - REQUIRE_AUTH=true  → reject.
                            - REQUIRE_AUTH=false → fall back to body.user_id (legacy/transitional).
                                - Token present but invalid/expired → reject.
                                    - Token present and valid but doesn't match claimed body.user_id → reject.
                                        """
    from flask import jsonify
    claimed = body.get("user_id")
    token = _bearer_token(request)

    if not token:
                if config.REQUIRE_AUTH:
                                return None, (jsonify({"error": "authorization required"}), 401)
                            return claimed, None

    verified = verify_jwt(token)
    if not verified:
                return None, (jsonify({"error": "invalid or expired token"}), 401)

    if claimed and claimed != verified:
                return None, (jsonify({"error": "token does not match user_id"}), 403)

    return verified, None
