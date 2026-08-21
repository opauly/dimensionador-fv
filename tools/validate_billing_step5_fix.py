from __future__ import annotations
"""
Live validation for the Step 5 subscribe/payment-method architecture fix
(PLAN_PHASE16.md §5.2 point 3 / §5.3's `payment-method/session` bullet,
both corrected 2026-08-20). Run for real against Oscar's ONVO test-mode
account and the real Supabase project, through the ACTUAL FastAPI app
(`vrm_api.main.app`, via `TestClient`) — same "curl replacement" precedent
as `tools/validate_billing_step3.py`, scoped to just what this fix changed.

This script cannot drive the real `sdk.onvopay.com` browser widget (no
browser automation is set up in this repo/environment) — but the widget's
own client-side behaviour is not a black box this script has to guess at:
ONVO's own OpenAPI spec (`https://docs.onvopay.com/openapi.yaml`) states
`security: [SecretApiKey, PublishableApiKey]` on BOTH `POST /v1/payment-
methods` (already known, §0.2b finding 7) AND `POST /v1/subscriptions/{id}
/confirm` — but only `[SecretApiKey]` on the plain `POST /v1/subscriptions
/{id}` update. That is a real, load-bearing discovery this script makes and
then checks empirically: it simulates exactly what a publishable-key-only
browser widget CAN legally do — create a payment method with the
publishable key, then call `/confirm` with the publishable key alone (never
the secret key) — for BOTH the first-subscribe case (an `incomplete`
subscription) and the replace-card case (an already `trialing`/`active`
subscription), because `/confirm`'s security scheme is the only
subscription-mutating endpoint a browser could possibly reach unassisted.
If `/confirm` on an already-active subscription is refused with just the
publishable key, or does something other than swap the payment method,
that is reported plainly as a real gap in the plan's assumption — not
papered over.

Every throwaway `vrm.customers` row is named "Phase 16 Step 5 fix
validation — safe to delete" and DELETED at the end (cascade takes
billing_customers/subscriptions/subscription_invoices/sites with it). ONVO
objects cannot be deleted through ONVO's confirmed API surface — any
still-live subscription is canceled before this script exits (best-effort).

Leak check: identical discipline to `tools/validate_billing_step3.py` — see
that script's own `__main__` comment for why the capture handler is scoped
to the "vrm_api" logger namespace and never the root logger.

Usage:
    python -m tools.validate_billing_step5_fix
"""
import contextlib
import io
import logging
import os
import sys
import uuid

import requests
from dotenv import load_dotenv

load_dotenv()

from fastapi.testclient import TestClient

from database.supabase_client import get_client
from vrm_api import onvo
from vrm_api.main import app

BASE_URL = "https://api.onvopay.com/v1"
MARKER = "Phase 16 Step 5 fix validation — safe to delete"

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


def check(label: str, ok: bool, detail: str = "") -> bool:
    _results.append((label, ok, detail))
    tag = "OK  " if ok else "FAIL"
    print(f"  {tag} {label}" + (f" — {detail}" if detail else ""))
    return ok


def _create_test_card(onvo_customer_id: str, *, auth_key: str, number: str = "4242424242424242") -> str:
    """Mirrors what the SDK widget's own iframe does — create a payment
    method directly against ONVO with ONLY the publishable key (§0.2b
    finding 7). `number` defaults to ONVO's documented always-succeeding
    test card."""
    r = requests.post(
        f"{BASE_URL}/payment-methods",
        headers={"Authorization": f"Bearer {auth_key}", "Content-Type": "application/json"},
        json={
            "type": "card", "customerId": onvo_customer_id,
            "card": {"number": number, "expMonth": 12, "expYear": 2030,
                      "cvv": "123", "holderName": MARKER},
            "billing": {"address": {"country": "CR", "city": "San Jose", "line1": "Calle 1",
                                     "postalCode": "10101"}, "name": MARKER, "phone": "+50688880000"},
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["id"]


def _confirm_subscription_pub(onvo_subscription_id: str, payment_method_id: str) -> requests.Response:
    """The SAME call `vrm_api/onvo.py:confirm_subscription()` makes
    server-side, but authenticated with ONLY the publishable key — this is
    the thing the browser widget would have to be doing internally for the
    plan's "our server never sees card data, the widget alone finishes the
    attach" claim to hold. Deliberately NOT going through `onvo.py` (which
    always uses the secret key) — this needs the raw call, publishable-key-
    only, to actually test what a browser could do."""
    return requests.post(
        f"{BASE_URL}/subscriptions/{onvo_subscription_id}/confirm",
        headers={"Authorization": f"Bearer {PUBLISHABLE_KEY}", "Content-Type": "application/json"},
        json={"paymentMethodId": payment_method_id},
        timeout=30,
    )


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
    slug = f"zzz-billing-step5fix-{uuid.uuid4().hex[:10]}"
    row = {"name": MARKER, "slug": slug, "auth_email": f"{slug}@example.com", **overrides}
    created = vrm.table("customers").insert(row).execute().data[0]
    _created_customer_ids.append(created["id"])
    return created


def _customer_by_id(customer_id: str) -> dict:
    return vrm.table("customers").select("*").eq("id", customer_id).limit(1).execute().data[0]


def _billing_customer_by_id(customer_id: str) -> dict | None:
    rows = vrm.table("billing_customers").select("*").eq("customer_id", customer_id).limit(1).execute().data
    return rows[0] if rows else None


def _live_sub_row(customer_id: str) -> dict | None:
    rows = (
        vrm.table("subscriptions").select("*").eq("customer_id", customer_id)
        .is_("canceled_at", "null").order("created_at", desc=True).limit(1).execute().data
    )
    return rows[0] if rows else None


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {PIPELINE_KEY}"}


def main() -> None:
    print("=" * 78)
    print(f"Step 5 fix validation — ONVO_MODE={MODE!r}, base URL={BASE_URL}")
    print("=" * 78)

    client = TestClient(app, headers=_auth_headers())
    starter_month = _get_plan("starter", "month")
    print(f"Using seeded plan: starter/month id={starter_month['id']}")

    # ═══════════════════════════════════════════════════════════════════
    # 1. POST /subscription with the OLD-style body (payment_method_id
    #    present) must now be REJECTED at the schema level — the field is
    #    gone, extra="forbid" rejects it outright.
    # ═══════════════════════════════════════════════════════════════════
    print("\n1. Old-style subscribe body (payment_method_id present) is rejected")
    cust_z = _make_customer(account_type="owner")
    r = client.post("/v1/billing/subscription", json={
        "customer_id": cust_z["id"], "plan_id": starter_month["id"], "payment_method_id": "whatever",
    })
    check("old-style body with payment_method_id -> 422 (extra field forbidden)",
          r.status_code == 422, f"{r.status_code}: {r.text}")

    # ═══════════════════════════════════════════════════════════════════
    # 2. First-time subscribe, corrected contract: {customer_id, plan_id}
    #    only -> an `incomplete` ONVO subscription, no payment method.
    # ═══════════════════════════════════════════════════════════════════
    print("\n2. POST /subscription {customer_id, plan_id} -> incomplete, no card")
    cust_a = _make_customer(account_type="owner")
    r = client.post("/v1/billing/subscription", json={"customer_id": cust_a["id"], "plan_id": starter_month["id"]})
    check("POST /subscription 200", r.status_code == 200, str(r.text))
    sub_body = r.json()
    check("response is EXACTLY {onvo_subscription_id, onvo_customer_id, publishable_key}",
          set(sub_body.keys()) == {"onvo_subscription_id", "onvo_customer_id", "publishable_key"}, str(sub_body.keys()))
    check("publishable_key is the real configured one", sub_body.get("publishable_key") == PUBLISHABLE_KEY)
    sub_id = sub_body["onvo_subscription_id"]
    onvo_customer_id_a = sub_body["onvo_customer_id"]
    _created_onvo_subscription_ids.append(sub_id)

    onvo_sub = onvo.get_subscription(sub_id)
    print(f"  [ONVO state] immediately after create: status={onvo_sub.get('status')!r} "
          f"paymentMethodId={onvo_sub.get('paymentMethodId')!r}")
    # REAL FINDING (2026-08-20, this script's first run): with
    # `trial_period_days=7` also set at creation (as this call always
    # does), ONVO reports `status: trialing` immediately, NOT `incomplete`
    # as PLAN_PHASE16.md §5.2 point 3's prose says — `incomplete` is what
    # ONVO reports when it actually ATTEMPTS a charge and that fails/has no
    # card; a subscription with a trial period has nothing to attempt yet.
    # See `routers/billing.py:post_subscription()`'s own docstring for the
    # full correction and its consequence (a real, flagged, NOT-fixed-here
    # gap: `apply_entitlements()` treats `trialing` as entitled, so a
    # reconcile against this exact subscription — before ANY card is ever
    # collected — would already grant full entitlements).
    check("ONVO reports status == 'trialing' immediately (trial_period_days set, not 'incomplete')",
          onvo_sub.get("status") == "trialing", str(onvo_sub.get("status")))
    check("ONVO ITSELF reports no paymentMethodId attached yet", not onvo_sub.get("paymentMethodId"),
          str(onvo_sub.get("paymentMethodId")))

    mirror_row = vrm.table("subscriptions").select("*").eq("onvo_subscription_id", sub_id).limit(1).execute().data
    check("mirror row exists (promoted from the placeholder, not left as pending:...)",
          bool(mirror_row) and not mirror_row[0]["onvo_subscription_id"].startswith("pending:"), str(mirror_row))

    # ── A second subscribe attempt while the first has no card yet must
    #    still be refused (guard 1 doesn't care about ONVO's status, only
    #    OUR mirror's canceled_at). ─────────────────────────────────────
    r = client.post("/v1/billing/subscription", json={"customer_id": cust_a["id"], "plan_id": starter_month["id"]})
    check("second subscribe before any card is attached -> 409 subscription_already_exists",
          r.status_code == 409 and r.json().get("detail", {}).get("code") == "subscription_already_exists",
          str(r.text))

    # ═══════════════════════════════════════════════════════════════════
    # 3. Simulate the SDK widget finishing the attach — publishable-key-
    #    only, exactly what the browser can legally do per ONVO's own
    #    OpenAPI security scheme for /confirm.
    # ═══════════════════════════════════════════════════════════════════
    print("\n3. Simulate the widget: create a card + /confirm, PUBLISHABLE KEY ONLY")
    pm_a = _create_test_card(onvo_customer_id_a, auth_key=PUBLISHABLE_KEY)
    confirm_resp = _confirm_subscription_pub(sub_id, pm_a)
    check("POST /subscriptions/{id}/confirm with PUBLISHABLE KEY ONLY succeeds (2xx)",
          200 <= confirm_resp.status_code < 300, f"{confirm_resp.status_code}: {confirm_resp.text}")
    confirmed_state = confirm_resp.json() if confirm_resp.ok else {}
    print(f"  [ONVO state] /confirm response (publishable-key-only): status={confirmed_state.get('status')!r} "
          f"paymentMethodId={confirmed_state.get('paymentMethodId')!r}")

    onvo_sub_after_confirm = onvo.get_subscription(sub_id)
    print(f"  [ONVO state] re-read with SECRET key after confirm: status={onvo_sub_after_confirm.get('status')!r} "
          f"paymentMethodId={onvo_sub_after_confirm.get('paymentMethodId')!r} "
          f"trialEnd={onvo_sub_after_confirm.get('trialEnd')!r}")
    check("subscription moved OFF 'incomplete' after /confirm",
          onvo_sub_after_confirm.get("status") != "incomplete", str(onvo_sub_after_confirm.get("status")))
    check("subscription's paymentMethodId now matches the card the widget created",
          onvo_sub_after_confirm.get("paymentMethodId") == pm_a, str(onvo_sub_after_confirm.get("paymentMethodId")))

    # ═══════════════════════════════════════════════════════════════════
    # 4. The browser's post-onSuccess call: POST /v1/billing/refresh — the
    #    ONLY thing allowed to move plan/site_limit/pm_* into our mirror.
    # ═══════════════════════════════════════════════════════════════════
    print("\n4. POST /refresh (the browser's post-onSuccess call) -> real entitlement")
    r = client.post("/v1/billing/refresh", json={"customer_id": cust_a["id"]})
    check("POST /refresh 200", r.status_code == 200, str(r.text))
    status_body = r.json()
    print(f"  [our mirror, post-refresh] status={status_body.get('status')!r} "
          f"billing_status={status_body.get('billing_status')!r} plan_key={status_body.get('plan_key')!r} "
          f"site_limit={status_body.get('site_limit')!r} pm_last4={status_body.get('pm_last4')!r}")
    check("after refresh: plan_key == starter", status_body.get("plan_key") == "starter", str(status_body.get("plan_key")))
    check("after refresh: site_limit == plan's grant", status_body.get("site_limit") == starter_month["site_limit"])
    check("after refresh: a payment method is now mirrored (pm_last4 present)", bool(status_body.get("pm_last4")))
    check("after refresh: site_limit_source flipped to 'plan' (§3.6 portal-subscribe writer)",
          _customer_by_id(cust_a["id"]).get("site_limit_source") == "plan")

    # ═══════════════════════════════════════════════════════════════════
    # 5. payment-method/session — refused with no_active_subscription for a
    #    customer who has never subscribed.
    # ═══════════════════════════════════════════════════════════════════
    print("\n5. payment-method/session refuses a customer with no live subscription")
    cust_b = _make_customer(account_type="owner")
    r = client.post("/v1/billing/payment-method/session", json={"customer_id": cust_b["id"]})
    check("POST /payment-method/session with no subscription -> 409 no_active_subscription",
          r.status_code == 409 and r.json().get("detail", {}).get("code") == "no_active_subscription", str(r.text))

    # ═══════════════════════════════════════════════════════════════════
    # 6. payment-method/session for the (now-active) customer from step 2:
    #    returns the REAL live subscription id, then the same
    #    publishable-key-only /confirm swap for the replace-card path.
    # ═══════════════════════════════════════════════════════════════════
    print("\n6. payment-method/session (replace-card path) + widget-style card swap")
    r = client.post("/v1/billing/payment-method/session", json={"customer_id": cust_a["id"]})
    check("POST /payment-method/session 200 for an active customer", r.status_code == 200, str(r.text))
    session_body = r.json()
    check("session response is EXACTLY {onvo_subscription_id, onvo_customer_id, publishable_key}",
          set(session_body.keys()) == {"onvo_subscription_id", "onvo_customer_id", "publishable_key"},
          str(session_body.keys()))
    mirror_live = _live_sub_row(cust_a["id"])
    check("session's onvo_subscription_id matches OUR mirror's current live subscription",
          bool(mirror_live) and session_body.get("onvo_subscription_id") == mirror_live["onvo_subscription_id"],
          f"session={session_body.get('onvo_subscription_id')} mirror={mirror_live and mirror_live.get('onvo_subscription_id')}")
    check("session's onvo_customer_id matches", session_body.get("onvo_customer_id") == onvo_customer_id_a)

    invoices_before = onvo.list_invoices(subscription_id=sub_id)
    pm_a2 = _create_test_card(onvo_customer_id_a, auth_key=PUBLISHABLE_KEY)
    confirm_resp_2 = _confirm_subscription_pub(session_body["onvo_subscription_id"], pm_a2)
    print(f"  [ONVO state] /confirm on an ALREADY-{onvo_sub_after_confirm.get('status')} subscription, "
          f"publishable-key-only -> HTTP {confirm_resp_2.status_code}")
    check("POST /subscriptions/{id}/confirm on an already-active/trialing subscription, "
          "PUBLISHABLE KEY ONLY, succeeds (2xx) — this is the architectural claim the replace-card "
          "flow depends on",
          200 <= confirm_resp_2.status_code < 300, f"{confirm_resp_2.status_code}: {confirm_resp_2.text}")

    onvo_sub_after_swap = onvo.get_subscription(sub_id)
    print(f"  [ONVO state] re-read with SECRET key after card-swap confirm: status={onvo_sub_after_swap.get('status')!r} "
          f"paymentMethodId={onvo_sub_after_swap.get('paymentMethodId')!r}")
    check("paymentMethodId actually swapped to the NEW card",
          onvo_sub_after_swap.get("paymentMethodId") == pm_a2, str(onvo_sub_after_swap.get("paymentMethodId")))
    check("subscription status unaffected by the card swap (still not 'incomplete')",
          onvo_sub_after_swap.get("status") != "incomplete", str(onvo_sub_after_swap.get("status")))
    invoices_after = onvo.list_invoices(subscription_id=sub_id)
    check("no NEW invoice was created just from confirming a card swap on an already-paid-up subscription",
          len(invoices_after) == len(invoices_before),
          f"before={len(invoices_before)} after={len(invoices_after)}")

    r = client.post("/v1/billing/refresh", json={"customer_id": cust_a["id"]})
    check("POST /refresh 200 after the card swap", r.status_code == 200, str(r.text))
    status_after_swap = r.json()
    billing_row_after_swap = _billing_customer_by_id(cust_a["id"])
    print(f"  [our mirror, post-refresh] pm_last4={status_after_swap.get('pm_last4')!r} "
          f"default_payment_method_id={billing_row_after_swap and billing_row_after_swap.get('default_payment_method_id')!r}")
    check("vrm.billing_customers.default_payment_method_id updated to the NEW card, "
          "from the RECONCILE (not from anything this script's request bodies carried)",
          bool(billing_row_after_swap) and billing_row_after_swap.get("default_payment_method_id") == pm_a2,
          str(billing_row_after_swap and billing_row_after_swap.get("default_payment_method_id")))

    # ═══════════════════════════════════════════════════════════════════
    # 7. Regression: cancel(at_period_end) -> resume still work (Step 3's
    #    already-verified code, untouched by this fix, re-checked here).
    # ═══════════════════════════════════════════════════════════════════
    print("\n7. Regression — cancel(at_period_end) -> resume, unaffected by this fix")
    r = client.post("/v1/billing/subscription/cancel", json={"customer_id": cust_a["id"], "mode": "at_period_end"})
    check("POST /subscription/cancel 200", r.status_code == 200, str(r.text))
    check("cancel_at_period_end mirrored true", r.json().get("cancel_at_period_end") is True)
    r = client.post("/v1/billing/subscription/resume", json={"customer_id": cust_a["id"]})
    check("POST /subscription/resume 200", r.status_code == 200, str(r.text))
    check("cancel_at_period_end cleared", r.json().get("cancel_at_period_end") is False)

    # ── Cleanup ──────────────────────────────────────────────────────────
    print("\nCleanup — cancelling any still-live ONVO subscriptions, deleting throwaway vrm.customers rows …")
    for created_sub_id in _created_onvo_subscription_ids:
        if created_sub_id.startswith("pending:"):
            continue
        try:
            current = onvo.get_subscription(created_sub_id)
            if current.get("status") != "canceled":
                onvo.cancel_subscription(created_sub_id)
                print(f"  cancelled ONVO subscription {created_sub_id}")
        except onvo.OnvoError as exc:
            print(f"  WARN could not cancel/verify ONVO subscription {created_sub_id} — {exc}")

    for customer_id in _created_customer_ids:
        try:
            vrm.table("customers").delete().eq("id", customer_id).execute()
        except Exception as exc:  # noqa: BLE001 — cleanup best-effort
            print(f"  WARN could not delete throwaway customer {customer_id} — {exc}")
    print(f"  deleted {len(_created_customer_ids)} throwaway vrm.customers row(s)")
    print(f"  ONVO objects (customers/subscriptions/payment methods) are left in test mode, marked {MARKER!r}.")


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

    # Same discipline as `tools/validate_billing_step3.py`'s own __main__
    # block — captures ONLY "vrm_api" and its children, INFO and up, NEVER
    # the root logger, NEVER DEBUG. See that script for the full reasoning.
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
    _leak_substring = "_" + "secret_key_"
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
        print("Step 5 fix validation FAILED.")
        raise SystemExit(1)
    print("Step 5 fix validation gate PASSED.")
