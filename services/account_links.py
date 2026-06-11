"""
services/account_links.py — SCAFFOLD (structure only, per roadmap decision June 11)

Linked job-site accounts shown in the user profile page.

REALITY CHECK (documented so no future session forgets):
  - LinkedIn: OAuth exists for profile data; job APPLICATION via API is partner-only.
  - Indeed / Bayt / Naukrigulf / GulfTalent: NO public OAuth.
  - Therefore "linked" for these sites = session established in Capacitor in-app
    webview (mobile phase). Backend stores link STATUS + metadata only.
    Never store raw passwords.

TABLE (in migrations.sql): user_linked_accounts
  user_id | site (linkedin/indeed/bayt/naukrigulf/gulftalent)
  status (unlinked/linked/expired) | linked_at | meta jsonb

PLANNED CONTRACT:
  get_links(user_id)            -> list of 5 sites with status
  set_link(user_id, site, status, meta) -> upsert
"""

SITES = ["linkedin", "indeed", "bayt", "naukrigulf", "gulftalent"]

def get_links(user_id: str):
    raise NotImplementedError("Scaffold — build with profile page update")

def set_link(user_id: str, site: str, status: str, meta: dict | None = None):
    raise NotImplementedError("Scaffold — build with profile page update")
