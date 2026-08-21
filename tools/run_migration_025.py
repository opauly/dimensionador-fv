"""
Migration 025 helper — ONVO billing + public signup schema (PLAN_PHASE16.md
§3, §8 Step 1): vrm.plans, vrm.billing_customers, vrm.subscriptions,
vrm.subscription_invoices, vrm.billing_events, vrm.signup_requests,
vrm.rate_limits, and four new columns on vrm.customers
(site_limit_source, billing_status, provisioning_state, origin).

Checks whether migration 025 has been applied, reachable through PostgREST,
and then runs Step 1's actual validation gate (PLAN_PHASE16.md §8 Step 1):

  1. Every new table/column exists.
  2. The partial unique index on vrm.subscriptions really refuses a second
     live row for the same customer (insert one, then attempt a conflicting
     second insert, and confirm PostgREST reports the failure).
  3. site_limit_source defaults to 'manual' on EVERY existing vrm.customers
     row — counted, not eyeballed.
  4. provisioning_state defaults to 'active' and origin to 'admin' on EVERY
     existing row — counted; asserts zero rows are 'pending_subscription'.
  5. vrm.rate_limits' upsert-and-return (vrm.increment_rate_limit()) is
     really atomic: fires N concurrent increments against the same
     bucket/key/window and asserts the final count is exactly N.

It does NOT apply the migration: paste
  `database/migrations/025_billing.sql`
into
  Project -> SQL Editor -> New query -> Run

Usage:
    python -m tools.run_migration_025
"""
from __future__ import annotations

import concurrent.futures
import os
import time
import uuid

import requests
from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client

SQL_PATH = "database/migrations/025_billing.sql"

NEW_TABLES = [
    "plans",
    "billing_customers",
    "subscriptions",
    "subscription_invoices",
    "billing_events",
    "signup_requests",
    "rate_limits",
]
NEW_CUSTOMER_COLUMNS = [
    "site_limit_source", "billing_status", "provisioning_state", "origin",
]

db = get_client()
vrm = db.schema("vrm")

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SERVICE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

print("Checking migration 025 — tables + columns …\n")

missing: list[str] = []

for table in NEW_TABLES:
    try:
        vrm.table(table).select("*").limit(1).execute()
        print(f"  OK      vrm.{table}")
    except Exception as exc:  # noqa: BLE001 — surfacing the raw PostgREST error is the point
        missing.append(f"vrm.{table}")
        print(f"  MISSING vrm.{table} — {str(exc)[:150]}")

for col in NEW_CUSTOMER_COLUMNS:
    try:
        vrm.table("customers").select(col).limit(1).execute()
        print(f"  OK      vrm.customers.{col}")
    except Exception as exc:  # noqa: BLE001
        missing.append(f"vrm.customers.{col}")
        print(f"  MISSING vrm.customers.{col} — {str(exc)[:150]}")

# The atomic-increment RPC — required for check 5 below.
try:
    vrm.rpc("increment_rate_limit", {
        "p_bucket": "migration_025_probe", "p_key": "startup_check",
        "p_window_start": "2000-01-01T00:00:00Z",
    }).execute()
    print("  OK      vrm.increment_rate_limit() callable")
    vrm.table("rate_limits").delete().eq("bucket", "migration_025_probe").execute()
except Exception as exc:  # noqa: BLE001
    missing.append("vrm.increment_rate_limit()")
    print(f"  MISSING vrm.increment_rate_limit() — {str(exc)[:150]}")

print()

if missing:
    print("─" * 68)
    print("Not ready — the objects above are missing. Paste the SQL below into")
    print(f"the Supabase SQL Editor and run it (source: {SQL_PATH}). It is")
    print("idempotent — safe to run even if some objects already exist.")
    print("─" * 68)
    print()
    with open(SQL_PATH) as f:
        print(f.read())
    raise SystemExit(1)

print("─" * 68)
print("Objects present. Running Step 1's validation gate (PLAN_PHASE16.md §8) …")
print("─" * 68)
print()

ok = True

# ── 1. Partial unique index on vrm.subscriptions really refuses a second
#      live row for the same customer ───────────────────────────────────
print("1. vrm.subscriptions — one live subscription per customer …")
test_slug = f"zzz-migration-025-test-{int(time.time())}"
sub_customer: dict | None = None
try:
    sub_customer = (vrm.table("customers")
                     .insert({"name": "Migration 025 test customer (safe to delete)",
                              "slug": test_slug})
                     .execute().data[0])
    cust_id = sub_customer["id"]
    print(f"   OK   created throwaway test customer {cust_id} (slug={test_slug})")

    first_sub_id = str(uuid.uuid4())
    row1 = {
        "customer_id": cust_id,
        "onvo_subscription_id": f"sub_test_{first_sub_id}",
        "mode": "test",
        "status": "trialing",
        "last_synced_at": "2026-01-01T00:00:00Z",
    }
    vrm.table("subscriptions").insert(row1).execute()
    print("   OK   first live subscription row inserted")

    second_sub_id = str(uuid.uuid4())
    row2 = {**row1, "onvo_subscription_id": f"sub_test_{second_sub_id}"}
    try:
        vrm.table("subscriptions").insert(row2).execute()
        ok = False
        print("   FAIL a second live (canceled_at IS NULL) subscription row for the "
              "SAME customer was accepted — the partial unique index is not working!")
    except Exception as exc:  # noqa: BLE001 — a rejection IS the expected outcome
        print(f"   OK   second live subscription row for the same customer was "
              f"REJECTED — {str(exc)[:150]}")

    # A CANCELED second row must be allowed (the index is partial, not global).
    row3 = {**row1, "onvo_subscription_id": f"sub_test_{uuid.uuid4()}",
            "status": "canceled", "canceled_at": "2026-01-02T00:00:00Z"}
    vrm.table("subscriptions").insert(row3).execute()
    print("   OK   a CANCELED second row for the same customer was accepted "
          "(the index is partial, not a blanket one-row-per-customer rule)")

except Exception as exc:  # noqa: BLE001
    ok = False
    print(f"   FAIL setup/assertions did not complete — {exc}")

finally:
    if sub_customer is not None:
        try:
            vrm.table("subscriptions").delete().eq("customer_id", sub_customer["id"]).execute()
            vrm.table("customers").delete().eq("id", sub_customer["id"]).execute()
            print(f"   OK   deleted throwaway test customer {sub_customer['id']} and its rows")
        except Exception as exc:  # noqa: BLE001
            print(f"   WARN could not clean up test customer {sub_customer['id']} — "
                  f"delete it by hand: {exc}")

print()

# ── 2/3. Defaults on EVERY existing customer row ─────────────────────────
print("2. site_limit_source / provisioning_state / origin defaults on EVERY "
      "existing vrm.customers row …")
try:
    total = vrm.table("customers").select("id", count="exact").limit(1).execute().count
    not_manual = vrm.table("customers").select("id", count="exact") \
        .neq("site_limit_source", "manual").limit(1).execute().count
    not_active_state = vrm.table("customers").select("id", count="exact") \
        .neq("provisioning_state", "active").limit(1).execute().count
    pending = vrm.table("customers").select("id", count="exact") \
        .eq("provisioning_state", "pending_subscription").limit(1).execute().count
    not_admin_origin = vrm.table("customers").select("id", count="exact") \
        .neq("origin", "admin").limit(1).execute().count

    print(f"   total vrm.customers rows: {total}")
    print(f"   rows with site_limit_source != 'manual': {not_manual}")
    print(f"   rows with provisioning_state != 'active': {not_active_state}")
    print(f"   rows with provisioning_state = 'pending_subscription': {pending}")
    print(f"   rows with origin != 'admin': {not_admin_origin}")

    if not_manual == 0:
        print("   OK   every existing row defaulted to site_limit_source='manual'")
    else:
        ok = False
        print("   FAIL some existing row did NOT default to site_limit_source='manual' "
              "— a hand-negotiated site_limit could now be silently overwritten!")

    if not_active_state == 0 and pending == 0:
        print("   OK   every existing row defaulted to provisioning_state='active' "
              "(zero rows are 'pending_subscription')")
    else:
        ok = False
        print("   FAIL some existing row is NOT provisioning_state='active' — an "
              "existing customer could be gated into a checkout screen!")

    if not_admin_origin == 0:
        print("   OK   every existing row defaulted to origin='admin'")
    else:
        ok = False
        print("   FAIL some existing row did NOT default to origin='admin'")

except Exception as exc:  # noqa: BLE001
    ok = False
    print(f"   FAIL could not run the default-count assertions — {exc}")

print()

# ── 4. vrm.rate_limits' upsert-and-return is atomic under real concurrency ─
print("3. vrm.rate_limits — N concurrent increments against the same "
      "bucket/key/window …")
N = 25
bucket = "migration_025_concurrency_test"
key = f"probe-{uuid.uuid4().hex[:8]}"
window_start = "2026-01-01T00:00:00+00:00"

rpc_url = f"{SUPABASE_URL}/rest/v1/rpc/increment_rate_limit"
headers = {
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type": "application/json",
    "Content-Profile": "vrm",
}


def _fire_one(_: int) -> int:
    r = requests.post(
        rpc_url, headers=headers,
        json={"p_bucket": bucket, "p_key": key, "p_window_start": window_start},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


try:
    with concurrent.futures.ThreadPoolExecutor(max_workers=N) as pool:
        results = list(pool.map(_fire_one, range(N)))

    returned_counts = sorted(results)
    final_row = (vrm.table("rate_limits").select("count")
                 .eq("bucket", bucket).eq("key", key).eq("window_start", window_start)
                 .limit(1).execute().data)
    final_count = final_row[0]["count"] if final_row else None

    print(f"   fired {N} concurrent increments")
    print(f"   values RETURNING count handed back, sorted: {returned_counts}")
    print(f"   final row count read back from the table: {final_count}")

    if returned_counts == list(range(1, N + 1)) and final_count == N:
        print(f"   OK   every one of the {N} concurrent increments was applied exactly "
              f"once — no lost update, final count == {N}")
    else:
        ok = False
        print(f"   FAIL expected the RETURNING values to be exactly 1..{N} with no "
              f"repeats and a final count of {N} — the upsert is NOT atomic")

    vrm.table("rate_limits").delete().eq("bucket", bucket).eq("key", key).execute()

except Exception as exc:  # noqa: BLE001
    ok = False
    print(f"   FAIL concurrency test did not complete — {exc}")

print()
print("─" * 68)
if ok:
    print("Ready. Migration 025 is applied and Step 1's validation gate passes.")
    print("Next: seed vrm.plans in test mode with `python -m tools.seed_onvo_plans`.")
    print("─" * 68)
    raise SystemExit(0)
else:
    print("NOT ready — one or more checks above FAILED. See the FAIL lines.")
    print("─" * 68)
    raise SystemExit(1)
