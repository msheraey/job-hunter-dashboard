"""
services/auth.py — SCAFFOLD (structure only, per roadmap decision June 11)

Social login via Supabase Auth OAuth providers.

PLANNED CONTRACT:
  Google login   → Supabase Auth handles dance; backend syncs users row on first login
  LinkedIn login → same flow, provider='linkedin_oidc'
  handle_oauth_callback(provider, supabase_user) -> users row (create or fetch)

NOTE: Most work is Supabase dashboard config (enable providers, redirect URLs)
+ Lovable frontend buttons. Backend only provisions the users row.
"""

def handle_oauth_callback(provider: str, supabase_user: dict):
    """Create/fetch app user after Supabase OAuth login. NOT IMPLEMENTED."""
    raise NotImplementedError("Scaffold — build when frontend OAuth buttons go live")
