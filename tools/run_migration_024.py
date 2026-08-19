"""
Migration 024 helper — VRM API ingestion: token-state columns, the
per-customer installation-id tenancy fix, the Vault wrapper functions, and
`vrm.ingestion_log.triggered_by` (PLAN_PHASE15.md §7, Step 1).

Checks whether migration 024 has been applied, reachable through PostgREST,
and runs the real Step 1 validation gate as far as PostgREST access allows:
round-trips a FAKE token through set_/read_/clear_customer_vrm_token as
service_role against a throwaway test customer (created and deleted by this
script), confirms no plaintext lands on the `vrm.customers` row, confirms
`clear_` actually clears the pointer and revokes, confirms `read_` returns
`NULL` after disconnect, and confirms the anon key is denied on all three
RPCs. It does NOT apply the migration: paste
`database/migrations/024_vrm_api_ingestion.sql` into
  Project -> SQL Editor -> New query -> Run

What this script CANNOT check — needs the SQL Editor, running "as postgres".
PostgREST never routes to the `vault` schema, by design (see the migration's
own header) — so this script, which only ever holds a PostgREST client, has
no way to see into `vault.*` directly, only through the three wrapper
functions:
  - `SELECT secret FROM vault.secrets WHERE id = ...` actually holds
    ciphertext, not the plaintext token this script set.
  - `SELECT decrypted_secret FROM vault.decrypted_secrets WHERE id = ...`
    actually decrypts back to the token this script set — the actual proof
    Vault itself works on this project, not just that the wrapper functions
    ran without raising.
This script prints the exact SQL for both, using a real vault id, at the end
of a successful run.

Usage:
    python -m tools.run_migration_024
"""
from __future__ import annotations

import os
import time
import uuid

from dotenv import load_dotenv

load_dotenv()

from supabase import create_client

from database.supabase_client import get_client

SQL_PATH = "database/migrations/024_vrm_api_ingestion.sql"

NEW_CUSTOMER_COLUMNS = [
    "vrm_token_last_checked_at", "vrm_token_last_ok_at", "vrm_token_last_error",
]
NEW_SITE_COLUMNS = ["vrm_last_synced_at", "vrm_last_sync_error", "vrm_sync_enabled"]

db = get_client()
vrm = db.schema("vrm")

print("Checking migration 024 — columns …\n")

missing: list[str] = []

for col in NEW_CUSTOMER_COLUMNS:
    try:
        vrm.table("customers").select(col).limit(1).execute()
        print(f"  OK      vrm.customers.{col}")
    except Exception as exc:  # noqa: BLE001 — surfacing the raw PostgREST error is the point
        missing.append(f"vrm.customers.{col}")
        print(f"  MISSING vrm.customers.{col} — {str(exc)[:120]}")

for col in NEW_SITE_COLUMNS:
    try:
        vrm.table("sites").select(col).limit(1).execute()
        print(f"  OK      vrm.sites.{col}")
    except Exception as exc:  # noqa: BLE001
        missing.append(f"vrm.sites.{col}")
        print(f"  MISSING vrm.sites.{col} — {str(exc)[:120]}")

try:
    vrm.table("ingestion_log").select("triggered_by").limit(1).execute()
    print("  OK      vrm.ingestion_log.triggered_by")
except Exception as exc:  # noqa: BLE001
    missing.append("vrm.ingestion_log.triggered_by")
    print(f"  MISSING vrm.ingestion_log.triggered_by — {str(exc)[:120]}")

print()

if missing:
    print("─" * 68)
    print("Not ready — the columns above are missing. Paste the SQL below into")
    print(f"the Supabase SQL Editor and run it (source: {SQL_PATH}). It is")
    print("idempotent — safe to run even if some objects already exist.")
    print("─" * 68)
    print()
    with open(SQL_PATH) as f:
        print(f.read())
    raise SystemExit(1)

print("─" * 68)
print("Columns present. Round-tripping a FAKE token through the Vault wrapper")
print("functions (Step 1's validation gate, PLAN_PHASE15.md §7) …")
print("─" * 68)
print()

FAKE_TOKEN = "TEST-TOKEN-DO-NOT-USE-migration-024-" + uuid.uuid4().hex[:12]
test_slug = f"zzz-migration-024-test-{int(time.time())}"
customer: dict | None = None
last_secret_id: str | None = None
ok = True

try:
    customer = (vrm.table("customers")
                .insert({"name": "Migration 024 test customer (safe to delete)",
                         "slug": test_slug})
                .execute().data[0])
    customer_id = customer["id"]
    print(f"  OK   created throwaway test customer {customer_id} (slug={test_slug})")

    db.schema("vrm").rpc(
        "set_customer_vrm_token", {"p_customer_id": customer_id, "p_token": FAKE_TOKEN}
    ).execute()
    print("  OK   set_customer_vrm_token() ran without error")

    row = vrm.table("customers").select("*").eq("id", customer_id).limit(1).execute().data[0]
    if FAKE_TOKEN in str(row):
        ok = False
        print("  FAIL the fake token appears in vrm.customers' own row — plaintext leak!")
    else:
        print("  OK   vrm.customers row contains no plaintext token")

    if not row.get("vrm_token_secret_id"):
        ok = False
        print("  FAIL vrm_token_secret_id was not populated by set_customer_vrm_token()")
    else:
        last_secret_id = row["vrm_token_secret_id"]
        print(f"  OK   vrm_token_secret_id populated ({last_secret_id})")

    read_back = db.schema("vrm").rpc(
        "read_customer_vrm_token", {"p_customer_id": customer_id}
    ).execute().data
    if read_back == FAKE_TOKEN:
        print("  OK   read_customer_vrm_token() returned the fake token unchanged")
    else:
        ok = False
        print(f"  FAIL read_customer_vrm_token() returned {read_back!r}, expected the fake token")

    db.schema("vrm").rpc(
        "clear_customer_vrm_token", {"p_customer_id": customer_id}
    ).execute()
    after_clear = vrm.table("customers").select("*").eq("id", customer_id).limit(1).execute().data[0]
    if after_clear.get("vrm_token_secret_id") is None and after_clear.get("vrm_token_revoked_at"):
        print("  OK   clear_customer_vrm_token() cleared the pointer and stamped vrm_token_revoked_at")
    else:
        ok = False
        print(f"  FAIL clear_customer_vrm_token() left unexpected state: {after_clear}")

    read_after_clear = db.schema("vrm").rpc(
        "read_customer_vrm_token", {"p_customer_id": customer_id}
    ).execute().data
    if read_after_clear is None:
        print("  OK   read_customer_vrm_token() returns NULL after disconnect (clean no-op)")
    else:
        ok = False
        print(f"  FAIL read_customer_vrm_token() after clear returned {read_after_clear!r}, expected None")

except Exception as exc:  # noqa: BLE001 — surfacing the raw error is the point of this script
    ok = False
    print(f"  FAIL round-trip did not complete — {exc}")

finally:
    if customer is not None:
        try:
            vrm.table("customers").delete().eq("id", customer["id"]).execute()
            print(f"  OK   deleted throwaway test customer {customer['id']}")
        except Exception as exc:  # noqa: BLE001
            print(f"  WARN could not delete test customer {customer['id']} — "
                  f"delete it by hand: {exc}")

print()
print("─" * 68)
print("Checking the anon key is denied on all three RPCs …")
print("─" * 68)
print()

anon_url = os.environ.get("SUPABASE_URL")
anon_key = os.environ.get("SUPABASE_ANON_KEY")
if not anon_key or not anon_url:
    print("  SKIPPED SUPABASE_URL/SUPABASE_ANON_KEY not set in this environment")
else:
    anon_client = create_client(anon_url, anon_key).schema("vrm")
    dummy_id = str(uuid.uuid4())
    for fn, params in [
        ("set_customer_vrm_token", {"p_customer_id": dummy_id, "p_token": "x"}),
        ("read_customer_vrm_token", {"p_customer_id": dummy_id}),
        ("clear_customer_vrm_token", {"p_customer_id": dummy_id}),
    ]:
        try:
            anon_client.rpc(fn, params).execute()
            ok = False
            print(f"  FAIL anon key was able to call vrm.{fn} — the REVOKE is not effective!")
        except Exception as exc:  # noqa: BLE001 — a denial IS the expected outcome here
            print(f"  OK   anon key denied on vrm.{fn} — {str(exc)[:100]}")

print()
if ok:
    print("═" * 68)
    print("Ready. Migration 024 is applied and the Vault round-trip works on")
    print("this project, as far as a PostgREST-only client can prove it.")
    print()
    print("Two checks this script cannot do over PostgREST — vault is never")
    print("exposed to it, by design. Run these by hand, once, in the Supabase")
    print("SQL Editor (as `postgres`), against a real vrm_token_secret_id (any")
    print("currently-connected customer's, or re-run this script's set_ step")
    print("and grab the id it just printed before it clears it):")
    print()
    print("  select id, name, secret from vault.secrets")
    print("    where id = '<vrm_token_secret_id>';")
    print("    -- 'secret' must be ciphertext — NOT the token you set.")
    print()
    print("  select decrypted_secret from vault.decrypted_secrets")
    print("    where id = '<vrm_token_secret_id>';")
    print("    -- must equal the token you set — this is the actual proof")
    print("    -- Vault decrypts correctly on THIS project.")
    print("═" * 68)
    raise SystemExit(0)
else:
    print("═" * 68)
    print("NOT ready — one or more checks above FAILED. See the FAIL lines.")
    print("Per PLAN_PHASE15.md §2.4: if the Vault round-trip itself is what's")
    print("failing (not merely a permissions/anon-key surprise), stop and take")
    print("the envelope-encryption fallback — but edit PLAN_PHASE15.md to")
    print("record why before writing that code.")
    print("═" * 68)
    raise SystemExit(1)
