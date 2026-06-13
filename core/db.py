"""
core/db.py — Safe Supabase helpers. No bare excepts anywhere else;
all DB error handling funnels through here with context labels.
"""
from config import get_supabase

def safe_select(table, columns="*", label=None, **filters):
    """SELECT with filters. Returns list (never raises)."""
    try:
        q = get_supabase().table(table).select(columns)
        for k, v in filters.items():
            q = q.eq(k, v)
        return q.execute().data or []
    except Exception as e:
        print(f"  ⚠️ DB select {label or table}: {e}")
        return []

def safe_insert(table, row, label=None):
    try:
        r = get_supabase().table(table).insert(row).execute()
        return r.data[0] if r.data else None
    except Exception as e:
        print(f"  ⚠️ DB insert {label or table}: {e}")
        return None

def safe_upsert(table, row, on_conflict, label=None):
    try:
        get_supabase().table(table).upsert(row, on_conflict=on_conflict).execute()
        return True
    except Exception as e:
        print(f"  ⚠️ DB upsert {label or table}: {e}")
        return False

def safe_update(table, values, label=None, **filters):
    if not filters:
        print(f"  ⚠️ safe_update refused: no filters on {table} (would update all rows)")
        return False
    try:
        q = get_supabase().table(table).update(values)
        for k, v in filters.items():
            q = q.eq(k, v)
        q.execute()
        return True
    except Exception as e:
        print(f"  ⚠️ DB update {label or table}: {e}")
        return False

def safe_delete(table, label=None, **filters):
    if not filters:
        print(f"  ⚠️ safe_delete refused: no filters on {table} (would delete all rows)")
        return False
    try:
        q = get_supabase().table(table).delete()
        for k, v in filters.items():
            q = q.eq(k, v)
        q.execute()
        return True
    except Exception as e:
        print(f"  ⚠️ DB delete {label or table}: {e}")
        return False
