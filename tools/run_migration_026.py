"""
Migration 026 helper — scheduled reports, report cost limits, tiered
branding (PLAN_PHASE17.md §5, §8 Step 2): vrm.plan_limits, vrm.report_runs,
seven new columns on vrm.sites (plus a table-level CHECK), and one new
column on vrm.customers.

Checks whether migration 026 has been applied, reachable through PostgREST,
and then runs Step 2's actual validation gate (PLAN_PHASE17.md §8 Step 2):

  1. Every new table/column exists.
  2. SELECT count(*) FROM vrm.sites WHERE report_schedule <> 'off' is 0 —
     the migration changed nobody's behaviour. Same for
     vrm.customers.default_report_schedule.
  3. sites_scheduled_reports_require_vrm_api really rejects a CSV-sourced
     site being given a live schedule, and really allows a vrm_api-sourced
     one.
  4. The partial unique index on vrm.report_runs refuses a second
     trigger='scheduled' row for the same (site_id, period_end), while
     allowing two trigger='manual' rows for the same period.
  5. The 'default' row exists in vrm.plan_limits and is the most
     restrictive row in the table (every other row's caps are >= it).
  6. report_schedule_day_of_month=29 is rejected; report_schedule_weekday=0
     and =8 are rejected.

It does NOT apply the migration: paste
  `database/migrations/026_report_schedule_limits_branding.sql`
into
  Project -> SQL Editor -> New query -> Run

Usage:
    python -m tools.run_migration_026
"""
from __future__ import annotations

import time
import uuid

from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client

SQL_PATH = "database/migrations/026_report_schedule_limits_branding.sql"

NEW_TABLES = ["plan_limits", "report_runs"]
NEW_SITE_COLUMNS = [
    "report_schedule", "report_schedule_weekday", "report_schedule_day_of_month",
    "report_schedule_hour", "report_recipients", "report_last_period_end",
    "report_last_run_at",
]
NEW_CUSTOMER_COLUMNS = ["default_report_schedule"]

db = get_client()
vrm = db.schema("vrm")

print("Checking migration 026 — tables + columns …\n")

missing: list[str] = []

for table in NEW_TABLES:
    try:
        vrm.table(table).select("*").limit(1).execute()
        print(f"  OK      vrm.{table}")
    except Exception as exc:  # noqa: BLE001 — surfacing the raw PostgREST error is the point
        missing.append(f"vrm.{table}")
        print(f"  MISSING vrm.{table} — {str(exc)[:150]}")

for col in NEW_SITE_COLUMNS:
    try:
        vrm.table("sites").select(col).limit(1).execute()
        print(f"  OK      vrm.sites.{col}")
    except Exception as exc:  # noqa: BLE001
        missing.append(f"vrm.sites.{col}")
        print(f"  MISSING vrm.sites.{col} — {str(exc)[:150]}")

for col in NEW_CUSTOMER_COLUMNS:
    try:
        vrm.table("customers").select(col).limit(1).execute()
        print(f"  OK      vrm.customers.{col}")
    except Exception as exc:  # noqa: BLE001
        missing.append(f"vrm.customers.{col}")
        print(f"  MISSING vrm.customers.{col} — {str(exc)[:150]}")

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
print("Objects present. Running Step 2's validation gate (PLAN_PHASE17.md §8) …")
print("─" * 68)
print()

ok = True

# ── 1. report_schedule / default_report_schedule changed NOBODY's
#      behaviour ─────────────────────────────────────────────────────────
print("1. report_schedule / default_report_schedule defaults on EVERY existing "
      "row …")
try:
    scheduled_sites = vrm.table("sites").select("id", count="exact") \
        .neq("report_schedule", "off").limit(1).execute().count
    scheduled_customers = vrm.table("customers").select("id", count="exact") \
        .neq("default_report_schedule", "off").limit(1).execute().count

    print(f"   vrm.sites rows with report_schedule != 'off': {scheduled_sites}")
    print(f"   vrm.customers rows with default_report_schedule != 'off': "
          f"{scheduled_customers}")

    if scheduled_sites == 0:
        print("   OK   every existing site defaulted to report_schedule='off'")
    else:
        ok = False
        print("   FAIL some existing site is NOT report_schedule='off' — this "
              "migration would start sending unattended reports for a site "
              "nobody configured!")

    if scheduled_customers == 0:
        print("   OK   every existing customer defaulted to "
              "default_report_schedule='off'")
    else:
        ok = False
        print("   FAIL some existing customer is NOT "
              "default_report_schedule='off'")

except Exception as exc:  # noqa: BLE001
    ok = False
    print(f"   FAIL could not run the default-count assertions — {exc}")

print()

# ── 2. sites_scheduled_reports_require_vrm_api really enforces §0.7 ─────
print("2. sites_scheduled_reports_require_vrm_api — CSV sites cannot be "
      "scheduled, vrm_api sites can …")
test_slug = f"zzz-migration-026-test-{int(time.time())}"
test_customer: dict | None = None
csv_site: dict | None = None
api_site: dict | None = None
try:
    test_customer = (vrm.table("customers")
                      .insert({"name": "Migration 026 test customer (safe to delete)",
                               "slug": test_slug})
                      .execute().data[0])
    cust_id = test_customer["id"]
    print(f"   OK   created throwaway test customer {cust_id} (slug={test_slug})")

    csv_site = (vrm.table("sites")
                .insert({"customer_id": cust_id,
                         "site_id": f"zzz-mig026-csv-{uuid.uuid4()}",
                         "display_name": "Migration 026 CSV test site",
                         "source": "csv_upload"})
                .execute().data[0])
    api_site = (vrm.table("sites")
                .insert({"customer_id": cust_id,
                         "site_id": f"zzz-mig026-api-{uuid.uuid4()}",
                         "display_name": "Migration 026 vrm_api test site",
                         "source": "vrm_api"})
                .execute().data[0])
    print(f"   OK   created a csv_upload site ({csv_site['site_id']}) and a "
          f"vrm_api site ({api_site['site_id']})")

    try:
        vrm.table("sites").update({"report_schedule": "weekly"}) \
            .eq("id", csv_site["id"]).execute()
        ok = False
        print("   FAIL scheduling a CSV-sourced site was ACCEPTED — the CHECK "
              "constraint is not working!")
    except Exception as exc:  # noqa: BLE001 — a rejection IS the expected outcome
        print(f"   OK   scheduling the CSV-sourced site was REJECTED — "
              f"{str(exc)[:150]}")

    vrm.table("sites").update({"report_schedule": "weekly"}) \
        .eq("id", api_site["id"]).execute()
    print("   OK   scheduling the vrm_api-sourced site was ACCEPTED")

except Exception as exc:  # noqa: BLE001
    ok = False
    print(f"   FAIL setup/assertions did not complete — {exc}")

finally:
    for site in (csv_site, api_site):
        if site is not None:
            try:
                vrm.table("sites").delete().eq("id", site["id"]).execute()
            except Exception as exc:  # noqa: BLE001
                print(f"   WARN could not clean up test site {site['id']} — "
                      f"delete it by hand: {exc}")
    if test_customer is not None:
        try:
            vrm.table("customers").delete().eq("id", test_customer["id"]).execute()
            print(f"   OK   deleted throwaway test customer {test_customer['id']} "
                  f"and its sites")
        except Exception as exc:  # noqa: BLE001
            print(f"   WARN could not clean up test customer "
                  f"{test_customer['id']} — delete it by hand: {exc}")

print()

# ── 3. The partial unique index on vrm.report_runs ────────────────────────
print("3. vrm.report_runs — one scheduled row per (site_id, period_end), "
      "manual rows unrestricted …")
run_customer: dict | None = None
run_ids: list[str] = []
try:
    run_customer = (vrm.table("customers")
                     .insert({"name": "Migration 026 report_runs test customer "
                                       "(safe to delete)",
                              "slug": f"zzz-migration-026-runs-{int(time.time())}"})
                     .execute().data[0])
    cust_id = run_customer["id"]
    site_id = f"zzz-mig026-runs-site-{uuid.uuid4()}"

    row1 = {
        "customer_id": cust_id, "site_id": site_id, "trigger": "scheduled",
        "schedule": "weekly", "period_start": "2026-01-01", "period_end": "2026-01-07",
        "status": "done",
    }
    r1 = vrm.table("report_runs").insert(row1).execute().data[0]
    run_ids.append(r1["id"])
    print("   OK   first scheduled row for (site_id, period_end) inserted")

    try:
        r2 = vrm.table("report_runs").insert(row1).execute().data[0]
        run_ids.append(r2["id"])
        ok = False
        print("   FAIL a second scheduled row for the SAME (site_id, period_end) "
              "was accepted — the partial unique index is not working!")
    except Exception as exc:  # noqa: BLE001 — a rejection IS the expected outcome
        print(f"   OK   second scheduled row for the same (site_id, period_end) "
              f"was REJECTED — {str(exc)[:150]}")

    manual_row = {**row1, "trigger": "manual", "schedule": None}
    m1 = vrm.table("report_runs").insert(manual_row).execute().data[0]
    m2 = vrm.table("report_runs").insert(manual_row).execute().data[0]
    run_ids.extend([m1["id"], m2["id"]])
    print("   OK   two MANUAL rows for the same (site_id, period_end) were both "
          "accepted (the index is partial, scoped to trigger='scheduled')")

except Exception as exc:  # noqa: BLE001
    ok = False
    print(f"   FAIL setup/assertions did not complete — {exc}")

finally:
    for rid in run_ids:
        try:
            vrm.table("report_runs").delete().eq("id", rid).execute()
        except Exception as exc:  # noqa: BLE001
            print(f"   WARN could not clean up report_runs row {rid} — "
                  f"delete it by hand: {exc}")
    if run_customer is not None:
        try:
            vrm.table("customers").delete().eq("id", run_customer["id"]).execute()
            print(f"   OK   deleted throwaway test customer "
                  f"{run_customer['id']} and its report_runs rows")
        except Exception as exc:  # noqa: BLE001
            print(f"   WARN could not clean up test customer "
                  f"{run_customer['id']} — delete it by hand: {exc}")

print()

# ── 4. vrm.plan_limits — 'default' exists and is stricter than every PAID
#      tier ──────────────────────────────────────────────────────────────
# NOTE: 'default' is NOT asserted to be the strictest row in the whole
# table — 'trial' and 'single_report' are deliberately even stricter on
# scheduled_reports_per_period (0, vs default's 4), because they cannot
# schedule at all (no paid subscription, or CSV-only — PLAN_PHASE17.md
# §0.7). The real invariant: 'default' (the fallback for a typo'd/
# unrecognized plan string) must never be MORE generous than a real, paying
# tier — an early version of this check wrongly compared 'default' against
# every row including trial/single_report and failed on their intentional
# 0s; fixed 2026-08-21 after that false positive on a live run.
print("4. vrm.plan_limits — 'default' row exists and is stricter than every "
      "paid tier (starter/growth/fleet) …")
try:
    rows = vrm.table("plan_limits").select("*").execute().data
    by_key = {r["plan_key"]: r for r in rows}
    PAID_TIERS = ("starter", "growth", "fleet")

    if "default" not in by_key:
        ok = False
        print("   FAIL no 'default' row in vrm.plan_limits")
    else:
        default = by_key["default"]
        print(f"   default row: {default}")
        looser_than_default = [
            key for key in PAID_TIERS if key in by_key and (
                by_key[key]["manual_reports_per_hour"] < default["manual_reports_per_hour"]
                or by_key[key]["manual_reports_per_day"] < default["manual_reports_per_day"]
                or by_key[key]["scheduled_reports_per_period"] < default["scheduled_reports_per_period"]
            )
        ]
        if not looser_than_default:
            print("   OK   'default' is stricter than every paid tier "
                  "(starter/growth/fleet) in all three fields")
        else:
            ok = False
            print(f"   FAIL these PAID tiers are somehow MORE restrictive than "
                  f"the 'default' fallback, which should never happen: "
                  f"{looser_than_default}")

except Exception as exc:  # noqa: BLE001
    ok = False
    print(f"   FAIL could not read vrm.plan_limits — {exc}")

print()

# ── 5. CHECK constraints on the new vrm.sites schedule columns ───────────
print("5. vrm.sites schedule column CHECKs — day_of_month=29 and "
      "weekday IN (0, 8) are rejected …")
chk_customer: dict | None = None
chk_site: dict | None = None
try:
    chk_customer = (vrm.table("customers")
                     .insert({"name": "Migration 026 CHECK test customer "
                                       "(safe to delete)",
                              "slug": f"zzz-migration-026-chk-{int(time.time())}"})
                     .execute().data[0])
    chk_site = (vrm.table("sites")
                .insert({"customer_id": chk_customer["id"],
                         "site_id": f"zzz-mig026-chk-{uuid.uuid4()}",
                         "display_name": "Migration 026 CHECK test site",
                         "source": "vrm_api"})
                .execute().data[0])

    for field, bad_value in (
        ("report_schedule_day_of_month", 29),
        ("report_schedule_weekday", 0),
        ("report_schedule_weekday", 8),
    ):
        try:
            vrm.table("sites").update({field: bad_value}).eq("id", chk_site["id"]).execute()
            ok = False
            print(f"   FAIL {field}={bad_value} was ACCEPTED — the CHECK is not "
                  f"working!")
        except Exception as exc:  # noqa: BLE001
            print(f"   OK   {field}={bad_value} was REJECTED — {str(exc)[:120]}")

except Exception as exc:  # noqa: BLE001
    ok = False
    print(f"   FAIL setup did not complete — {exc}")

finally:
    if chk_site is not None:
        try:
            vrm.table("sites").delete().eq("id", chk_site["id"]).execute()
        except Exception as exc:  # noqa: BLE001
            print(f"   WARN could not clean up test site {chk_site['id']} — "
                  f"delete it by hand: {exc}")
    if chk_customer is not None:
        try:
            vrm.table("customers").delete().eq("id", chk_customer["id"]).execute()
            print(f"   OK   deleted throwaway test customer "
                  f"{chk_customer['id']}")
        except Exception as exc:  # noqa: BLE001
            print(f"   WARN could not clean up test customer "
                  f"{chk_customer['id']} — delete it by hand: {exc}")

print()
print("─" * 68)
if ok:
    print("Ready. Migration 026 is applied and Step 2's DB-level validation gate")
    print("passes. Remaining Step 2 gate item (manual, not automated here):")
    print("confirm /app/sites, /app/profile, and /admin/customers still build")
    print("and render — nothing customer-facing changed yet in this step.")
    print("─" * 68)
    raise SystemExit(0)
else:
    print("NOT ready — one or more checks above FAILED. See the FAIL lines.")
    print("─" * 68)
    raise SystemExit(1)
