from __future__ import annotations
import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        _client = create_client(url, key)
    return _client


def ping() -> bool:
    """Returns True if Supabase is reachable. Used in startup health check."""
    try:
        get_client().table("app_settings").select("key").limit(1).execute()
        return True
    except Exception:
        return False
