from __future__ import annotations
"""
Step 3 validation gate (PLAN_PHASE16.md §8 Step 3) — `vrm_api/routers/
billing.py` + its `vrm_api/schemas.py` models, run for real against Oscar's
ONVO test-mode account and the real Supabase project, through the ACTUAL
FastAPI app (`vrm_api.main.app`, via Starlette's `TestClient` — a real ASGI
request/response cycle including routing, `Depends(require_pipeline_key)`,
and pydantic validation, not a direct call into handler functions). This is
this script's "curl" — a small Python script exercising the real HTTP
surface end to end, per §8 Step 3's own "your call" wording.

Every §8 Step 3 validation-list item is a real, asserted check here:
  - every endpoint, end-to-end;
  - the duplicate-create guard under REAL concurrency (two threads, two
    independent TestClient/ASGI transports, genuinely racing);
  - the change-plan over-site-limit guard (`over_site_limit`, nothing
    applied without `confirm`, applies with it);
  - `plan_not_available` for a `pending_subscription` customer on a
    non-`self_serve` plan, and NOT for an `active` customer on the same
    plan (two different code paths, both actually exercised: subscribe for
    the pending case, change for the active case, since an active customer
    already holding a live subscription would otherwise hit
    `subscription_already_exists` before the self_serve check ever ran);
  - the tamper cases: (a) by inspection, no `Billing*Request` model in
    `vrm_api/schemas.py` has any field shaped like an ONVO id other than
    `payment_method_id`, whose handling is re-verify-before-trust
    (asserted programmatically below, not just eyeballed); (b) a
    `payment_method_id` belonging to a DIFFERENT ONVO customer is rejected
    (`payment_method_not_owned`), not silently attached — two throwaway
    customers/cards created specifically for this.

Every throwaway `vrm.customers` row is named
"Phase 16 Step 3 validation — safe to delete" and DELETED at the end
(cascade takes billing_customers/subscriptions/subscription_invoices/sites
with it). Every throwaway `vrm.plans` row this script creates (the one
non-self-serve plan needed for the plan_not_available test) is deleted too.
ONVO-side objects (customers/products/prices/subscriptions/payment methods)
cannot be deleted through ONVO's confirmed API surface — left in test mode,
marked with the same MARKER string, any still-live subscription canceled
before this script exits (best-effort).

Leak check: identical discipline to `tools/validate_billing_step2.py` —
this script's own stdout AND every log record from this product's OWN
loggers ("vrm_api" and its children: vrm_api.billing, vrm_api.onvo,
vrm_api.billing_router) are captured and scanned for `ONVO_SECRET_KEY`'s
real value and the generic substring `_secret_key_`. The ROOT logger is
NEVER touched and NEVER raised to DEBUG — see the `__main__` block's own
comment. This matters MORE this step than Step 2's, because this script
also drives `TestClient`, which routes through `httpx`/`httpcore`
internally for the ASGI transport; scoping the capture handler to the
"vrm_api" namespace (a sibling of "httpx"/"httpcore", never an ancestor)
keeps that library's own verbose logging structurally unreachable here,
exactly like Step 2's script already established.

Usage:
    python -m tools.validate_billing_step3
"""
import concurrent.futures
import contextlib
import io
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

from fastapi.testclient import TestClient

from database.supabase_client import get_client
from vrm_api import onvo, schemas
from vrm_api.main import app

BASE_URL = "https://api.onvopay.com/v1"
MARKER = "Phase 16 Step 3 validation — safe to delete"

MODE = os.environ.get("ONVO_MODE")
SECRET_KEY = os.environ.get("ONVO_SECRET_KEY")
PUBLISHABLE_KEY = os.environ.get("ONVO_PUBLISHABLE_KEY")
PIPELINE_KEY = os.environ.get("PIPELINE_API_KEY")

if not SECRET_KEY or not PUBLISHABLE_KEY or not PIPELINE_KEY:
    print("ONVO_SECRET_KEY / ONVO_PUBLISHABLE_KEY / PIPELINE_API_KEY not all set "
          "in the environment. Aborting.", file=sys.stderr)
    sys.exit(1)
if MODE != "test" or not SECRET_KEY.startswith("onvo_test_secret_key_"):
    print(
        "ONVO_MODE is not 'test', or ONVO_SECRET_KEY does not look like a test "
        "key. Refusing to run — this script must never touch a live-mode account.",
        file=sys.stderr,
    )
    sys.exit(1)

db = get_client()
vrm = db.schema("vrm")

_results: list[tuple[str, bool, str]] = []
_created_customer_ids: list[str] = []
_created_onvo_subscription_ids: list[str] = []
_created_plan_ids: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    _results.append((label, ok, detail))
    tag = "OK  " if ok else "FAIL"
    print(f"  {tag} {label}" + (f" — {detail}" if detail else ""))
    return ok


# ── Raw ONVO helpers — same precedent as tools/validate_billing_step2.py
#    and tools/seed_onvo_plans.py: payment-method/product/price creation
#    isn't (and, for cards, per §5.2/§6.3, must never be) something
#    vrm_api/onvo.py wraps as a server-initiated action. These stand in for
#    "the browser" and "a one-off catalogue seed" respectively. ──────────
def _create_test_card(onvo_customer_id: str, *, auth_key: str) -> str:
    r = requests.post(
        f"{BASE_URL}/payment-methods",
        headers={"Authorization": f"Bearer {auth_key}", "Content-Type": "application/json"},
        json={
            "type": "card", "customerId": onvo_customer_id,
            "card": {"number": "4242424242424242", "expMonth": 12, "expYear": 2030,
                      "cvv": "123", "holderName": MARKER},
            "billing": {"address": {"country": "CR", "city": "San Jose", "line1": "Calle 1",
                                     "postalCode": "10101"}, "name": MARKER, "phone": "+50688880000"},
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["id"]


def _create_throwaway_price(name_suffix: str, amount_minor: int = 199) -> tuple[str, str]:
    """A real ONVO product+price, minimal cost, used ONLY as the target of
    the `plan_not_available` test's throwaway `vrm.plans` row — that test
    needs a real, valid `onvo_price_id` (the column is NOT NULL/UNIQUE) but
    never actually completes a subscription against it in the refused
    case, and the one case that DOES subscribe against it (the
    active-customer/not-refused case) is a real, cancel-able test-mode
    subscription like any other in this script."""
    headers = {"Authorization": f"Bearer {SECRET_KEY}", "Content-Type": "application/json"}
    product = requests.post(f"{BASE_URL}/products", headers=headers, json={
        "name": f"{MARKER} — product ({name_suffix})",
    }, timeout=30)
    product.raise_for_status()
    product_id = product.json()["id"]
    price = requests.post(f"{BASE_URL}/prices", headers=headers, json={
        "productId": product_id, "currency": "USD", "unitAmount": amount_minor,
        "type": "recurring", "recurring": {"interval": "month", "intervalCount": 1},
    }, timeout=30)
    price.raise_for_status()
    return product_id, price.json()["id"]


def _get_plan(plan_key: str, billing_interval: str = "month") -> dict:
    rows = (
        vrm.table("plans").select("*")
        .eq("plan_key", plan_key).eq("billing_interval", billing_interval)
        .eq("mode", "test").eq("active", True).limit(1).execute().data
    )
    if not rows:
        raise RuntimeError(
            f"No seeded vrm.plans row for {plan_key}/{billing_interval}/test — "
            "run `python -m tools.seed_onvo_plans` first."
        )
    return rows[0]


def _make_customer(**overrides) -> dict:
    slug = f"zzz-billing-step3-{uuid.uuid4().hex[:10]}"
    row = {
        "name": MARKER, "slug": slug,
        "auth_email": f"{slug}@example.com",
        **overrides,
    }
    created = vrm.table("customers").insert(row).execute().data[0]
    _created_customer_ids.append(created["id"])
    return created


def _customer_by_id(customer_id: str) -> dict:
    return vrm.table("customers").select("*").eq("id", customer_id).limit(1).execute().data[0]


def _billing_customer_by_id(customer_id: str) -> dict | None:
    rows = vrm.table("billing_customers").select("*").eq("customer_id", customer_id).limit(1).execute().data
    return rows[0] if rows else None


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {PIPELINE_KEY}"}


def main() -> None:
    print("=" * 78)
    print(f"Step 3 validation — ONVO_MODE={MODE!r}, base URL={BASE_URL}")
    print("=" * 78)

    client = TestClient(app, headers=_auth_headers())

    # ── Tamper-case-by-inspection: no Billing*Request model carries an ────
    #    ONVO id other than payment_method_id (§6.4 control 3, §8 Step 3's
    #    own "assert this by reading the models" instruction). ────────────
    print("\n0. Inspect every Billing*Request model for an ONVO-id-shaped field")
    onvo_id_like = {"onvo_customer_id", "onvo_subscription_id", "price_id", "onvo_price_id",
                    "product_id", "onvo_product_id", "invoice_id", "onvo_invoice_id"}
    request_models = [
        getattr(schemas, name) for name in dir(schemas)
        if name.startswith("Billing") and name.endswith("Request")
    ]
    check("found the expected Billing*Request models", len(request_models) >= 8, str(len(request_models)))
    offending: list[str] = []
    for model in request_models:
        fields = set(model.model_fields.keys())
        bad = fields & onvo_id_like
        if bad:
            offending.append(f"{model.__name__}: {bad}")
    check("no Billing*Request model has an ONVO-id-shaped field "
          "(payment_method_id is the one deliberate exception, and it is NOT in this set)",
          not offending, "; ".join(offending))

    starter_month = _get_plan("starter", "month")
    growth_month = _get_plan("growth", "month")
    print(f"\nUsing seeded plans: starter/month id={starter_month['id']} "
          f"site_limit={starter_month['site_limit']}, growth/month id={growth_month['id']} "
          f"site_limit={growth_month['site_limit']}")

    # ═══════════════════════════════════════════════════════════════════
    # 1. GET /status, GET /plans, GET /invoices — a customer who has never
    #    touched billing at all.
    # ═══════════════════════════════════════════════════════════════════
    print("\n1. Read endpoints for a customer who never touched billing")
    cust_a = _make_customer(account_type="owner")
    r = client.get("/v1/billing/status", params={"customer_id": cust_a["id"]})
    check("GET /status 200", r.status_code == 200, str(r.status_code))
    status_body = r.json()
    check("provisioning_state == 'active' (admin-created default)", status_body.get("provisioning_state") == "active")
    check("no live subscription -> status is None", status_body.get("status") is None)

    r = client.get("/v1/billing/plans", params={"customer_id": cust_a["id"]})
    check("GET /plans 200", r.status_code == 200, str(r.status_code))
    plans_body = r.json()["plans"]
    check("starter plan is in the list for an owner", any(p["plan_key"] == "starter" for p in plans_body))
    check("growth plan is NOT in the list for an owner (installer-only)", not any(p["plan_key"] == "growth" for p in plans_body))
    check("no onvo id leaked into the plan list", all("onvo_price_id" not in p and "onvo_product_id" not in p for p in plans_body))

    r = client.get("/v1/billing/invoices", params={"customer_id": cust_a["id"]})
    check("GET /invoices 200 with an empty list", r.status_code == 200 and r.json()["invoices"] == [], str(r.json()))

    # ═══════════════════════════════════════════════════════════════════
    # 2. payment-method/session -> browser-style card creation with the
    #    PUBLISHABLE key -> POST /subscription -> full status lifecycle.
    # ═══════════════════════════════════════════════════════════════════
    print("\n2. payment-method/session -> create a card with the PUBLISHABLE "
          "key (mirrors the real browser flow) -> POST /subscription")
    r = client.post("/v1/billing/payment-method/session", json={"customer_id": cust_a["id"]})
    check("POST /payment-method/session 200", r.status_code == 200, str(r.text))
    session_body = r.json()
    check("session returns the real publishable key", session_body.get("publishable_key") == PUBLISHABLE_KEY)
    onvo_customer_id_a = session_body["onvo_customer_id"]
    check("billing_customers row now exists", _billing_customer_by_id(cust_a["id"]) is not None)

    pm_a = _create_test_card(onvo_customer_id_a, auth_key=PUBLISHABLE_KEY)  # the publishable key alone — §0.2b finding 7

    r = client.post("/v1/billing/subscription", json={
        "customer_id": cust_a["id"], "plan_id": starter_month["id"], "payment_method_id": pm_a,
    })
    check("POST /subscription 200", r.status_code == 200, str(r.text))
    sub_body = r.json()
    if r.status_code == 200:
        _created_onvo_subscription_ids.append(sub_body["onvo_subscription_id"])
    check("response carries onvo_subscription_id/onvo_customer_id/publishable_key, nothing else sensitive",
          set(sub_body.keys()) == {"onvo_subscription_id", "onvo_customer_id", "publishable_key"})

    r = client.get("/v1/billing/status", params={"customer_id": cust_a["id"]})
    status_body = r.json()
    check("after subscribe: plan_key == starter", status_body.get("plan_key") == "starter", str(status_body.get("plan_key")))
    check("after subscribe: site_limit == plan's grant", status_body.get("site_limit") == starter_month["site_limit"])
    check("after subscribe: billing_status == trialing", status_body.get("billing_status") == "trialing", str(status_body.get("billing_status")))
    check("after subscribe: site_limit_source flipped to 'plan' (§3.6, portal-subscribe writer)",
          _customer_by_id(cust_a["id"]).get("site_limit_source") == "plan")

    # ── A second subscribe (non-concurrent) must be refused outright ─────
    r = client.post("/v1/billing/subscription", json={
        "customer_id": cust_a["id"], "plan_id": starter_month["id"], "payment_method_id": pm_a,
    })
    check("second (sequential) subscribe -> 409 subscription_already_exists",
          r.status_code == 409 and r.json().get("detail", {}).get("code") == "subscription_already_exists",
          str(r.text))

    r = client.get("/v1/billing/invoices", params={"customer_id": cust_a["id"]})
    check("GET /invoices now has at least 1 row (the trial invoice)", len(r.json()["invoices"]) >= 1, str(r.json()))

    # ═══════════════════════════════════════════════════════════════════
    # 3. cancel (at_period_end) -> resume -> payment-method replace -> address
    # ═══════════════════════════════════════════════════════════════════
    print("\n3. cancel(at_period_end) -> resume -> payment-method replace -> address")
    r = client.post("/v1/billing/subscription/cancel", json={"customer_id": cust_a["id"], "mode": "at_period_end"})
    check("POST /subscription/cancel 200", r.status_code == 200, str(r.text))
    check("cancel_at_period_end mirrored true", r.json().get("cancel_at_period_end") is True)
    check("still entitled (graceful cancel keeps access) — plan still starter", r.json().get("plan_key") == "starter")

    r = client.post("/v1/billing/subscription/resume", json={"customer_id": cust_a["id"]})
    check("POST /subscription/resume 200", r.status_code == 200, str(r.text))
    check("cancel_at_period_end cleared", r.json().get("cancel_at_period_end") is False)

    pm_a2 = _create_test_card(onvo_customer_id_a, auth_key=PUBLISHABLE_KEY)
    before_pm = _billing_customer_by_id(cust_a["id"])["default_payment_method_id"]
    r = client.post("/v1/billing/payment-method", json={"customer_id": cust_a["id"], "payment_method_id": pm_a2})
    check("POST /payment-method 200", r.status_code == 200, str(r.text))
    after_pm = _billing_customer_by_id(cust_a["id"])["default_payment_method_id"]
    check("default_payment_method_id actually changed to the new card", after_pm == pm_a2 and after_pm != before_pm,
          f"{before_pm} -> {after_pm}")

    r = client.put("/v1/billing/address", json={
        "customer_id": cust_a["id"],
        "address": {"city": "Cartago", "country": "CR", "line1": "Avenida 3", "postalCode": "30101"},
    })
    check("PUT /address 200", r.status_code == 200, str(r.text))
    mirrored_address = _billing_customer_by_id(cust_a["id"])["billing_address"]
    check("address mirrored from ONVO's own re-read, matches what was sent",
          mirrored_address.get("city") == "Cartago" and mirrored_address.get("line1") == "Avenida 3",
          str(mirrored_address))

    # ═══════════════════════════════════════════════════════════════════
    # 4. TAMPER CASE — a payment_method_id belonging to a DIFFERENT ONVO
    #    customer must be rejected, not silently attached.
    # ═══════════════════════════════════════════════════════════════════
    print("\n4. Tamper case — attach a payment method belonging to a DIFFERENT customer")
    cust_b = _make_customer(account_type="owner")
    r = client.post("/v1/billing/payment-method/session", json={"customer_id": cust_b["id"]})
    onvo_customer_id_b = r.json()["onvo_customer_id"]
    pm_b = _create_test_card(onvo_customer_id_b, auth_key=PUBLISHABLE_KEY)

    before_pm_tamper = _billing_customer_by_id(cust_a["id"])["default_payment_method_id"]
    r = client.post("/v1/billing/payment-method", json={"customer_id": cust_a["id"], "payment_method_id": pm_b})
    check("cross-customer payment_method_id -> 403 payment_method_not_owned",
          r.status_code == 403 and r.json().get("detail", {}).get("code") == "payment_method_not_owned",
          str(r.text))
    after_pm_tamper = _billing_customer_by_id(cust_a["id"])["default_payment_method_id"]
    check("cust_a's default_payment_method_id UNCHANGED after the rejected tamper attempt",
          after_pm_tamper == before_pm_tamper)

    # ── no_active_subscription — cust_b has a billing_customers row (from
    #    the session call above) but has never subscribed. ─────────────────
    print("\n4b. no_active_subscription — a customer with no live subscription")
    r = client.post("/v1/billing/subscription/cancel", json={"customer_id": cust_b["id"], "mode": "at_period_end"})
    check("cancel with no live subscription -> 409 no_active_subscription",
          r.status_code == 409 and r.json().get("detail", {}).get("code") == "no_active_subscription", str(r.text))
    r = client.post("/v1/billing/subscription/resume", json={"customer_id": cust_b["id"]})
    check("resume with no live subscription -> 409 no_active_subscription",
          r.status_code == 409 and r.json().get("detail", {}).get("code") == "no_active_subscription", str(r.text))
    r = client.post("/v1/billing/subscription/change", json={"customer_id": cust_b["id"], "plan_id": starter_month["id"], "confirm": True})
    check("change with no live subscription -> 409 no_active_subscription",
          r.status_code == 409 and r.json().get("detail", {}).get("code") == "no_active_subscription", str(r.text))

    # ── no_payment_method — a customer who has NEVER touched billing at ────
    #    all (no billing_customers row) cannot set an address. ─────────────
    cust_f = _make_customer(account_type="owner")
    r = client.put("/v1/billing/address", json={"customer_id": cust_f["id"], "address": {"city": "x"}})
    check("PUT /address with no billing_customers row at all -> 400 no_payment_method",
          r.status_code == 400 and r.json().get("detail", {}).get("code") == "no_payment_method", str(r.text))

    # ═══════════════════════════════════════════════════════════════════
    # 5. DUPLICATE-CREATE GUARD under REAL concurrency.
    # ═══════════════════════════════════════════════════════════════════
    print("\n5. Duplicate-create guard — two concurrent POST /subscription for "
          "the SAME (new) customer -> exactly one created, the other 409")
    cust_e = _make_customer(account_type="owner")
    r = client.post("/v1/billing/payment-method/session", json={"customer_id": cust_e["id"]})
    onvo_customer_id_e = r.json()["onvo_customer_id"]
    pm_e = _create_test_card(onvo_customer_id_e, auth_key=PUBLISHABLE_KEY)

    body_e = {"customer_id": cust_e["id"], "plan_id": starter_month["id"], "payment_method_id": pm_e}
    # Two INDEPENDENT TestClient instances (two independent ASGI transports/
    # portals) so this is a genuine race, not a single client serializing
    # requests under the hood.
    client_1 = TestClient(app, headers=_auth_headers())
    client_2 = TestClient(app, headers=_auth_headers())
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(client_1.post, "/v1/billing/subscription", json=body_e)
        f2 = pool.submit(client_2.post, "/v1/billing/subscription", json=body_e)
        r1, r2 = f1.result(), f2.result()

    codes = sorted([r1.status_code, r2.status_code])
    check("exactly one 200 and one 409 across the two concurrent calls", codes == [200, 409],
          f"{r1.status_code} / {r2.status_code}")
    winner = r1 if r1.status_code == 200 else r2
    loser = r2 if r1.status_code == 200 else r1
    check("the 409 carries code=subscription_already_exists",
          loser.json().get("detail", {}).get("code") == "subscription_already_exists", str(loser.text))
    if winner.status_code == 200:
        _created_onvo_subscription_ids.append(winner.json()["onvo_subscription_id"])

    mirror_rows_e = vrm.table("subscriptions").select("*").eq("customer_id", cust_e["id"]).execute().data
    live_rows_e = [row for row in mirror_rows_e if row.get("canceled_at") is None]
    check("exactly ONE live vrm.subscriptions row for customer E after the race", len(live_rows_e) == 1, str(len(live_rows_e)))

    # Cross-check against ONVO ITSELF, not just our own mirror — the real
    # assertion this test exists for: at most one non-canceled subscription
    # genuinely exists at ONVO for this customer.
    onvo_subs_e = onvo.list_customer_subscriptions(onvo_customer_id_e)
    live_onvo_subs_e = [s for s in onvo_subs_e if s.get("status") != "canceled"]
    check("exactly ONE non-canceled subscription at ONVO ITSELF for customer E (not just our mirror)",
          len(live_onvo_subs_e) == 1, str([s.get("id") for s in live_onvo_subs_e]))

    # ═══════════════════════════════════════════════════════════════════
    # 6. CHANGE PLAN — over-site-limit guard, then confirm.
    # ═══════════════════════════════════════════════════════════════════
    print("\n6. Change plan — over_site_limit guard (no confirm) -> confirm=true applies")
    cust_c = _make_customer(account_type="installer")
    r = client.post("/v1/billing/payment-method/session", json={"customer_id": cust_c["id"]})
    onvo_customer_id_c = r.json()["onvo_customer_id"]
    pm_c = _create_test_card(onvo_customer_id_c, auth_key=PUBLISHABLE_KEY)
    r = client.post("/v1/billing/subscription", json={
        "customer_id": cust_c["id"], "plan_id": growth_month["id"], "payment_method_id": pm_c,
    })
    check("cust_c subscribed to growth", r.status_code == 200, str(r.text))
    growth_sub_id = r.json()["onvo_subscription_id"]
    _created_onvo_subscription_ids.append(growth_sub_id)

    # 11 active sites — one more than starter's site_limit (10).
    site_rows = [
        {"customer_id": cust_c["id"], "site_id": f"{cust_c['slug']}-site-{i}",
         "display_name": f"{MARKER} site {i}", "active": True}
        for i in range(starter_month["site_limit"] + 1)
    ]
    vrm.table("sites").insert(site_rows).execute()

    r = client.post("/v1/billing/subscription/change", json={
        "customer_id": cust_c["id"], "plan_id": starter_month["id"], "confirm": False,
    })
    check("change without confirm -> 409 over_site_limit", r.status_code == 409, str(r.text))
    detail = r.json().get("detail", {})
    check("detail carries code=over_site_limit + requires_confirmation + the real numbers",
          detail.get("code") == "over_site_limit" and detail.get("requires_confirmation") is True
          and detail.get("current_site_count") == starter_month["site_limit"] + 1
          and detail.get("new_site_limit") == starter_month["site_limit"],
          str(detail))

    # Nothing applied yet — cust_c is still on growth.
    r = client.get("/v1/billing/status", params={"customer_id": cust_c["id"]})
    check("nothing applied: still on growth after the refused change", r.json().get("plan_key") == "growth", str(r.json().get("plan_key")))

    r = client.post("/v1/billing/subscription/change", json={
        "customer_id": cust_c["id"], "plan_id": starter_month["id"], "confirm": True,
    })
    check("change WITH confirm=true -> 200, actually applies", r.status_code == 200, str(r.text))
    if r.status_code == 200:
        change_body = r.json()
        check("plan_key now starter", change_body.get("plan_key") == "starter", str(change_body.get("plan_key")))
        check("over_limit now true (11 sites, starter's limit is 10) — nothing was deactivated, banner only",
              change_body.get("over_limit") is True and change_body.get("active_sites") == starter_month["site_limit"] + 1)
        new_starter_sub = vrm.table("subscriptions").select("onvo_subscription_id").eq("customer_id", cust_c["id"]).is_("canceled_at", "null").limit(1).execute().data
        if new_starter_sub:
            _created_onvo_subscription_ids.append(new_starter_sub[0]["onvo_subscription_id"])

    old_growth_row = vrm.table("subscriptions").select("*").eq("onvo_subscription_id", growth_sub_id).limit(1).execute().data
    check("the OLD growth subscription is canceled (cancel-and-restart, no proration, Q3 final)",
          bool(old_growth_row) and old_growth_row[0].get("canceled_at") is not None, str(old_growth_row))

    all_sites_c = vrm.table("sites").select("id", count="exact").eq("customer_id", cust_c["id"]).eq("active", True).execute()
    check("all 11 sites are still active — no site was ever deactivated (Q5(b))", all_sites_c.count == starter_month["site_limit"] + 1, str(all_sites_c.count))

    # ═══════════════════════════════════════════════════════════════════
    # 7. plan_not_available — pending_subscription customer refused on a
    #    non-self_serve plan; an ACTIVE customer is NOT refused on the
    #    same plan (two different code paths, both exercised for real).
    # ═══════════════════════════════════════════════════════════════════
    print("\n7. plan_not_available — pending customer refused; active customer not refused")
    throwaway_product_id, throwaway_price_id = _create_throwaway_price("plan_not_available test")
    throwaway_plan = vrm.table("plans").insert({
        "plan_key": f"zzz_step3_nonselfserve_{uuid.uuid4().hex[:6]}",
        "billing_interval": "month", "currency": "USD", "amount_minor": 199, "mode": "test",
        "onvo_product_id": throwaway_product_id, "onvo_price_id": throwaway_price_id,
        "site_limit": None, "account_types": ["owner", "installer"], "self_serve": False,
        "active": True, "sort_order": 999,
    }).execute().data[0]
    _created_plan_ids.append(throwaway_plan["id"])

    cust_d = _make_customer(
        account_type="owner", provisioning_state="pending_subscription",
        site_limit=0, site_limit_source="plan", plan="trial", origin="self_serve",
    )
    r = client.post("/v1/billing/subscription", json={
        "customer_id": cust_d["id"], "plan_id": throwaway_plan["id"], "payment_method_id": "irrelevant-not-reached",
    })
    check("pending_subscription customer on a non-self_serve plan -> 403 plan_not_available",
          r.status_code == 403 and r.json().get("detail", {}).get("code") == "plan_not_available", str(r.text))

    # cust_c is `active` (its very first subscribe promotes/keeps it active
    # via apply_entitlements — it was admin-created, so provisioning_state
    # was already 'active' from row-creation) and already holds a live
    # starter subscription from step 6 — changing it to the SAME
    # non-self_serve plan must NOT be blocked by self_serve (only by
    # account_type/active, both of which pass here).
    r = client.post("/v1/billing/subscription/change", json={
        "customer_id": cust_c["id"], "plan_id": throwaway_plan["id"], "confirm": True,
    })
    check("ACTIVE customer changing to the SAME non-self_serve plan -> NOT refused (200, not 403 plan_not_available)",
          r.status_code == 200, str(r.text))
    if r.status_code == 200:
        check("plan actually changed to the throwaway (non-self_serve) plan_key",
              r.json().get("plan_key") == throwaway_plan["plan_key"], str(r.json().get("plan_key")))
        newest_sub = vrm.table("subscriptions").select("onvo_subscription_id").eq("customer_id", cust_c["id"]).is_("canceled_at", "null").limit(1).execute().data
        if newest_sub:
            _created_onvo_subscription_ids.append(newest_sub[0]["onvo_subscription_id"])

    # ═══════════════════════════════════════════════════════════════════
    # 8. reconcile-due sweeper — backdate a mirror row's last_synced_at
    #    past the 48h cutoff, confirm the sweep picks it up and refreshes it.
    # ═══════════════════════════════════════════════════════════════════
    print("\n8. POST /reconcile-due — a row stale past 48h gets picked up and refreshed")
    stale_cutoff_row = vrm.table("subscriptions").select("id").eq("customer_id", cust_a["id"]).is_("canceled_at", "null").limit(1).execute().data
    if stale_cutoff_row:
        backdated = (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat()
        vrm.table("subscriptions").update({"last_synced_at": backdated}).eq("id", stale_cutoff_row[0]["id"]).execute()
        r = client.post("/v1/billing/reconcile-due", json={})
        check("POST /reconcile-due 200", r.status_code == 200, str(r.text))
        body = r.json()
        check("cust_a's stale subscription was among the customers checked", cust_a["id"] in [x["customer_id"] for x in body["results"]], str(body))
        cust_a_result = next((x for x in body["results"] if x["customer_id"] == cust_a["id"]), None)
        check("cust_a's reconcile-due entry succeeded (ok=true)", bool(cust_a_result and cust_a_result["ok"]), str(cust_a_result))
        refreshed_row = vrm.table("subscriptions").select("last_synced_at").eq("id", stale_cutoff_row[0]["id"]).limit(1).execute().data[0]
        check("last_synced_at actually advanced past the backdated value", refreshed_row["last_synced_at"] > backdated, str(refreshed_row))
    else:
        check("stale-row candidate found for the reconcile-due test", False, "no live subscription row for cust_a")

    # ── Cleanup ──────────────────────────────────────────────────────────
    print("\nCleanup — cancelling any still-live ONVO subscriptions, deleting "
          "throwaway vrm.plans/vrm.customers rows …")
    for sub_id in _created_onvo_subscription_ids:
        if sub_id.startswith("pending:"):
            continue
        try:
            current = onvo.get_subscription(sub_id)
            if current.get("status") != "canceled":
                onvo.cancel_subscription(sub_id)
                print(f"  cancelled ONVO subscription {sub_id}")
        except onvo.OnvoError as exc:
            print(f"  WARN could not cancel/verify ONVO subscription {sub_id} — {exc}")

    for plan_id in _created_plan_ids:
        try:
            vrm.table("plans").delete().eq("id", plan_id).execute()
        except Exception as exc:  # noqa: BLE001 — cleanup best-effort
            print(f"  WARN could not delete throwaway plan {plan_id} — {exc}")
    print(f"  deleted {len(_created_plan_ids)} throwaway vrm.plans row(s)")

    for customer_id in _created_customer_ids:
        try:
            vrm.table("customers").delete().eq("id", customer_id).execute()
        except Exception as exc:  # noqa: BLE001 — cleanup best-effort
            print(f"  WARN could not delete throwaway customer {customer_id} — {exc}")
    print(f"  deleted {len(_created_customer_ids)} throwaway vrm.customers row(s) (cascade took their "
          "billing_customers/subscriptions/subscription_invoices/sites rows with them)")
    print(f"  ONVO objects (customers/subscriptions/products/prices/payment methods) are left in "
          f"test mode, marked {MARKER!r} — no delete-customer/delete-product/delete-price operation "
          f"exists in ONVO's confirmed API surface.")


if __name__ == "__main__":
    buffer = io.StringIO()

    class _TeeStream:
        def __init__(self, real, sink):
            self._real = real
            self._sink = sink

        def write(self, s):
            self._real.write(s)
            self._sink.write(s)
            return len(s)

        def flush(self):
            self._real.flush()

    tee = _TeeStream(sys.stdout, buffer)

    # Captures ONLY this product's own loggers ("vrm_api" and its children
    # vrm_api.billing/vrm_api.onvo/vrm_api.billing_router), at INFO and up —
    # NEVER the root logger, and NEVER DEBUG. This is the exact mistake a
    # coder agent made during Step 2's own validation (leaked
    # SUPABASE_SERVICE_ROLE_KEY by raising the ROOT logger to DEBUG, which
    # also turns on httpx/httpcore/hpack's own DEBUG loggers that dump full
    # request headers — including this process's Supabase Authorization
    # bearer token — in cleartext). Scoping the handler to the "vrm_api"
    # logger namespace (a sibling of "httpx"/"httpcore", not an ancestor)
    # makes that class of leak structurally unreachable here, rather than
    # something this script has to remember not to do. This step's own
    # TestClient additionally drives httpx/httpcore internally for its ASGI
    # transport — exactly why this scoping matters even more here than it
    # did in Step 2.
    capture_handler = logging.StreamHandler(tee)
    capture_handler.setLevel(logging.INFO)
    app_logger = logging.getLogger("vrm_api")
    app_logger.addHandler(capture_handler)
    app_logger.setLevel(logging.INFO)

    failed_hard = False
    try:
        with contextlib.redirect_stdout(tee):
            main()
    except Exception:
        failed_hard = True
        import traceback
        traceback.print_exc()
    finally:
        app_logger.removeHandler(capture_handler)

    captured = buffer.getvalue()
    _leak_substring = "_" + "secret_key_"  # built at runtime, deliberately
    # never spelled out literally in a print()/log call anywhere in this
    # file — a raw `grep -c '_secret_key_' <output>` run by a human on this
    # script's real output must see zero hits when there is no real leak,
    # not one guaranteed hit from this check narrating itself.
    leak = SECRET_KEY in captured or _leak_substring in captured
    print("\n" + "=" * 78)
    print("LEAK CHECK (automated): scanned this run's stdout + every log record "
          "for the raw ONVO secret key value and its key-prefix substring.")
    print(f"  {'FAIL - LEAK DETECTED' if leak else 'OK   - no leak found'}")
    print("=" * 78)

    n_ok = sum(1 for _, ok, _ in _results if ok)
    n_total = len(_results)
    print(f"\n{n_ok}/{n_total} checks passed.")
    if failed_hard or leak or n_ok != n_total:
        print("Step 3 validation FAILED.")
        raise SystemExit(1)
    print("Step 3 validation gate PASSED.")
