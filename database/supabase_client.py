from __future__ import annotations
import os
import threading
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

_local = threading.local()


def get_client() -> Client:
    """One client per thread: the dev server is threaded, and a single HTTP/2 connection shared by several threads fails with
    "httpx.ReadError: [Errno 35] Resource temporarily unavailable"."""
    client = getattr(_local, "client", None)
    if client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        client = _local.client = create_client(url, key)
    return client


def ping() -> bool:
    """Returns True if Supabase is reachable. Used in startup health check."""
    try:
        get_client().table("app_settings").select("key").limit(1).execute()
        return True
    except Exception:
        return False
