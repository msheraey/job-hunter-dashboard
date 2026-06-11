"""
web_dashboard_cloud.py — ENTRY SHIM.
Railway's CMD (gunicorn web_dashboard_cloud:app) is unchanged;
the real application lives in api/app.py.
"""
from config import validate_env
validate_env()
from api.app import app  # noqa: F401
