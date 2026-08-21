"""
Seed `vrm.plans` in TEST mode with the final tier pricing Oscar approved
(PLAN_PHASE16.md §0.6 Q1/Q13/Q14), against REAL ONVO product/price objects
created live via `POST /v1/products` then `POST /v1/prices`
(PLAN_PHASE16.md §0.2b finding 2 for the exact request shapes; §8 Step 1).

Creates exactly four (product, price) pairs — Starter and Growth, each
monthly and annual. Fleet gets no row (custom/contact-only, Q14). Single
Report gets no row either (a one-off $9.99 purchase, not a subscription,
Q14 — out of scope for this phase, §9). Each product/price is named/
described `"VRM Monitor — <Tier> (<interval>)"` so it is identifiable as
the real v1 catalogue in the ONVO dashboard, distinct from Step 0's throw-
away `"Phase 16 Step 0 probe — safe to delete"` objects — this script does
NOT reuse or reference those; it creates fresh ones.

This is a one-off seed script, not idempotent by re-running blindly: running
it twice would create eight ONVO price objects and (thanks to vrm.plans'
own `UNIQUE (onvo_price_id)` and the partial `UNIQUE (plan_key,
billing_interval, currency, mode) WHERE active`) the second run's inserts
would collide on the sellable-plan partial index and fail loudly rather
than silently duplicate — this script checks for an existing active row
per (plan_key, interval) FIRST and skips creating a new ONVO object if one
is already seeded, so it IS safe to re-run to fill in whatever is missing.

Safety discipline, same as `tools/onvo_probe.py`:
  - ONVO_SECRET_KEY is never printed, logged, or included in any exception
    message.
  - Refuses to run unless ONVO_MODE == 'test' AND the secret key itself
    looks like a test key — this script must never create a live-mode
    product/price.
  - Writes vrm.plans rows via `database.supabase_client.get_client()`,
    this repo's established Supabase access pattern (SUPABASE_SERVICE_ROLE_KEY).

Usage:
    python -m tools.seed_onvo_plans
"""
from __future__ import annotations

import os
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client

BASE_URL = "https://api.onvopay.com/v1"

MODE = os.environ.get("ONVO_MODE")
SECRET_KEY = os.environ.get("ONVO_SECRET_KEY")

if not SECRET_KEY:
    print("ONVO_SECRET_KEY not set in the environment. Aborting.", file=sys.stderr)
    sys.exit(1)

if MODE != "test" or not SECRET_KEY.startswith("onvo_test_secret_key_"):
    print(
        "ONVO_MODE is not 'test', or ONVO_SECRET_KEY does not look like a test key. "
        "Refusing to run — this script must never create a live-mode product/price.",
        file=sys.stderr,
    )
    sys.exit(1)

HEADERS = {"Authorization": f"Bearer {SECRET_KEY}", "Content-Type": "application/json"}

# lib/plans.ts:PLANS — read, not guessed (PLAN_PHASE16.md §8 Step 1).
#   starter: accountTypes ['installer', 'owner']
#   growth:  accountTypes ['installer']
PLAN_SEEDS = [
    {
        "plan_key": "starter",
        "label": "Starter",
        "site_limit": 10,
        "account_types": ["installer", "owner"],
        "self_serve": True,
        "sort_order": 10,
        "intervals": [
            {"billing_interval": "month", "amount_minor": 2999},   # $29.99/mo
            {"billing_interval": "year", "amount_minor": 29999},   # $299.99/yr
        ],
    },
    {
        "plan_key": "growth",
        "label": "Growth",
        "site_limit": 50,
        "account_types": ["installer"],
        "self_serve": True,
        "sort_order": 20,
        "intervals": [
            {"billing_interval": "month", "amount_minor": 9999},   # $99.99/mo
            {"billing_interval": "year", "amount_minor": 99999},   # $999.99/yr
        ],
    },
]


def _post(path: str, payload: dict) -> dict:
    r = requests.post(f"{BASE_URL}{path}", headers=HEADERS, json=payload, timeout=30)
    if r.status_code not in (200, 201):
        # Never let the secret key leak into an exception message — it isn't
        # in the response body/headers we're printing here, but keep this
        # explicit rather than assuming.
        raise RuntimeError(f"ONVO {path} -> {r.status_code}: {r.text[:500]}")
    return r.json()


def main() -> None:
    db = get_client()
    vrm = db.schema("vrm")

    print(f"ONVO_MODE={MODE!r}. Seeding vrm.plans against REAL test-mode ONVO objects.\n")

    created: list[dict] = []

    for plan in PLAN_SEEDS:
        plan_key = plan["plan_key"]
        print(f"── {plan['label']} ({plan_key}) " + "─" * 40)

        product_id: str | None = None

        for interval in plan["intervals"]:
            billing_interval = interval["billing_interval"]
            amount_minor = interval["amount_minor"]

            existing = (
                vrm.table("plans")
                .select("id, onvo_price_id, onvo_product_id")
                .eq("plan_key", plan_key)
                .eq("billing_interval", billing_interval)
                .eq("currency", "USD")
                .eq("mode", "test")
                .eq("active", True)
                .limit(1)
                .execute()
                .data
            )
            if existing:
                print(f"  SKIP  {plan_key}/{billing_interval}: already seeded "
                      f"(vrm.plans.id={existing[0]['id']}, "
                      f"onvo_price_id={existing[0]['onvo_price_id']})")
                continue

            if product_id is None:
                product_name = f"VRM Monitor — {plan['label']}"
                product = _post("/products", {
                    "name": product_name,
                    "description": f"{product_name} — Phase 16 v1 self-serve catalogue",
                })
                product_id = product["id"]
                print(f"  OK    created ONVO product {product_id} ({product_name!r})")
                time.sleep(0.3)

            # ONVO's price-creation schema does not accept `description` at
            # all (confirmed live, PLAN_PHASE16.md §0.2b finding 2's exact
            # body) — only products do. `price_name` stays local, used only
            # for this script's own log line below.
            price_name = f"VRM Monitor — {plan['label']} ({billing_interval}ly)"
            price = _post("/prices", {
                "productId": product_id,
                "currency": "USD",
                "unitAmount": amount_minor,
                "type": "recurring",
                "recurring": {"interval": billing_interval, "intervalCount": 1},
            })
            price_id = price["id"]
            print(f"  OK    created ONVO price {price_id} "
                  f"({price_name!r}, unitAmount={amount_minor})")
            time.sleep(0.3)

            row = (
                vrm.table("plans")
                .insert({
                    "plan_key": plan_key,
                    "billing_interval": billing_interval,
                    "currency": "USD",
                    "amount_minor": amount_minor,
                    "mode": "test",
                    "onvo_product_id": product_id,
                    "onvo_price_id": price_id,
                    "site_limit": plan["site_limit"],
                    "account_types": plan["account_types"],
                    "self_serve": plan["self_serve"],
                    "active": True,
                    "sort_order": plan["sort_order"],
                })
                .execute()
                .data[0]
            )
            print(f"  OK    inserted vrm.plans row {row['id']}")
            created.append({
                "plan_key": plan_key, "billing_interval": billing_interval,
                "amount_minor": amount_minor, "onvo_product_id": product_id,
                "onvo_price_id": price_id, "vrm_plans_id": row["id"],
            })

        print()

    print("═" * 68)
    if created:
        print(f"Created/confirmed {len(created)} vrm.plans row(s) this run:")
        for c in created:
            print(f"  {c['plan_key']:<8} {c['billing_interval']:<6} "
                  f"${c['amount_minor'] / 100:>7.2f}  "
                  f"onvo_price_id={c['onvo_price_id']}  "
                  f"onvo_product_id={c['onvo_product_id']}  "
                  f"vrm.plans.id={c['vrm_plans_id']}")
    else:
        print("Nothing new created — all four rows were already seeded.")

    all_rows = (
        vrm.table("plans")
        .select("plan_key, billing_interval, currency, amount_minor, mode, "
                "onvo_price_id, onvo_product_id, self_serve, active, sort_order")
        .eq("mode", "test")
        .order("sort_order")
        .execute()
        .data
    )
    print(f"\nAll vrm.plans rows in mode='test' after this run ({len(all_rows)}):")
    for r in all_rows:
        print(f"  {r}")
    print("═" * 68)


if __name__ == "__main__":
    main()
