"""
core/logger.py — RunLogger: persistent run logs in Supabase scrape_logs.
Every cron run and manual trigger is fully traceable in the admin dashboard.
"""
from datetime import datetime, timezone
from config import get_supabase

class RunLogger:
    def __init__(self, run_type="run"):
        self.run_type = run_type
        self.lines = []
        self.total_scraped = 0
        self.total_saved = 0
        self.errors = 0
        self.log_id = None
        try:
            r = get_supabase().table("scrape_logs").insert({
                "started_at": datetime.now(timezone.utc).isoformat(),
                "status": "running",
                "log_text": f"[{run_type}] started",
                "total_scraped": 0, "total_saved": 0,
            }).execute()
            self.log_id = r.data[0]["id"]
            print(f"📋 Log entry created: {self.log_id}")
        except Exception as e:
            print(f"⚠️ Could not create log entry: {e}")

    def add(self, msg, print_it=True):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self.lines.append(f"[{ts}] {msg}")
        if "❌" in msg or "⚠️" in msg:
            self.errors += 1
        if print_it:
            print(msg)
        if len(self.lines) % 10 == 0:
            self._flush()

    def _flush(self):
        if not self.log_id:
            return
        try:
            get_supabase().table("scrape_logs").update({
                "log_text": "\n".join(self.lines[-500:]),
                "total_scraped": self.total_scraped,
                "total_saved": self.total_saved,
                "error_count": self.errors,
            }).eq("id", self.log_id).execute()
        except Exception as e:
            print(f"⚠️ Log flush error: {e}")

    def finish(self, success=True, error=None):
        if not self.log_id:
            return
        try:
            upd = {
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "status": "success" if success else "error",
                "log_text": "\n".join(self.lines[-500:]),
                "total_scraped": self.total_scraped,
                "total_saved": self.total_saved,
                "error_count": self.errors,
            }
            if error:
                upd["error"] = str(error)[:1000]
            get_supabase().table("scrape_logs").update(upd).eq("id", self.log_id).execute()
            print(f"📋 Log saved — {'success' if success else 'error'}")
        except Exception as e:
            print(f"⚠️ Log finish error: {e}")
