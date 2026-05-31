import os
print("Testing imports...")
print(f"SUPABASE_URL: {os.environ.get('SUPABASE_URL', 'NOT SET')[:20]}")
print(f"SUPABASE_KEY: {os.environ.get('SUPABASE_KEY', 'NOT SET')[:10]}")

from supabase import create_client
print("supabase imported ok")

supabase = create_client(os.environ.get('SUPABASE_URL'), os.environ.get('SUPABASE_KEY'))
print("supabase client created ok")

from scraper_v2 import search_jobs
print("scraper_v2 imported ok")
