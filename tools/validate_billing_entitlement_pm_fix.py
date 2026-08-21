from __future__ import annotations
"""
Live validation for the entitlement-without-a-payment-method security fix
(`vrm_api/billing.py:apply_entitlements()`, fixed 2026-08-20 — see that
function's module docstring, "Entitled status is necessary but NOT
sufficient").

THE BUG: `POST /v1/billing/subscription` creates the ONVO subscription with
`trialPeriodDays: 7` and no `paymentMethodId` (§5.2, corrected 2026-08-20).
`tools/validate_billing_step5_fix.py` was the first script to observe, live,
that ONVO reports that subscription as `status: "trialing"` IMMEDIATELY —
not `incomplete` as the plan's original prose assumed — with no card ever
attached. Before this fix, `apply_entitlements()` mapped `trialing` straight
to "entitled" (`_STATUS_ENTITLEMENT["trialing"] = True`), so a caller who
skipped the ONVO SDK's card-entry widget entirely (e.g. calling
`POST /v1/billing/subscription` then `POST /v1/billing/refresh` directly,
as this script's own §1 below does) would receive a full 7-day trial with
NO card ever collected — directly defeating PLAN_PHASE16.md §0.6 Q2's
"card required upfront" decision.

THE FIX: `apply_entitlements()` now additionally requires
`vrm.billing_customers.default_payment_method_id` to be non-null before
granting/promoting on an entitled-shaped status. If it's missing, the
existing 'hold' branch (`_classify_status()`'s own mechanism for an
unrecognized status) is used instead — grant nothing, promote nothing, log
`billing.entitled_status_no_payment_method` loudly.

This script proves, against Oscar's real ONVO test-mode account and the
real Supabase project, through the ACTUAL FastAPI app
(`vrm_api.main.app`, via `TestClient`, same "curl replacement" precedent as
`tools/validate_billing_step5_fix.py`):

  1. THE EXPLOIT PATH, PROVEN CLOSED: subscribe with no card, refresh
     directly (no SDK widget, no card ever attached) -> plan/site_limit/
     provisioning_state must NOT change, even though the mirrored
     subscription shows status='trialing'.
  2. THE LEGITIMATE PATH, STILL WORKS: same customer, NOW attach a card via
     the same publishable-key-only pattern `validate_billing_step5_fix.py`
     uses (mirrors exactly what the SDK widget's own iframe does) -> refresh
     again -> entitlement now DOES grant, provisioning_state promotes.
  3. AN ALREADY-ENTITLED CUSTOMER DOES NOT REGRESS: reconcile again -> still
     entitled, no spurious `billing.entitled_status_no_payment_method` log
     line.

Every throwaway `vrm.customers` row is named "Phase 16 entitlement/PM fix
validation — safe to delete" and DELETED at the end (cascade takes
billing_customers/subscriptions/subscription_invoices/sites with it). ONVO
objects cannot be deleted through ONVO's confirmed API surface — any still-
live subscription is canceled before this script exits (best-effort).

Leak check: identical discipline to `tools/validate_billing_step5_fix.py`.

Usage:
    python -m tools.validate_billing_entitlement_pm_fix
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
MARKER = "Phase 16 entitlement/PM fix validation — safe to delete"

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
    what the browser SDK widget does internally to finish attaching a card,
    per §0.2b finding 7 / `validate_billing_step5_fix.py`'s own precedent."""
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
    slug = f"zzz-billing-pmfix-{uuid.uuid4().hex[:10]}"
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
    print(f"Entitlement/payment-method fix validation — ONVO_MODE={MODE!r}, base URL={BASE_URL}")
    print("=" * 78)

    client = TestClient(app, headers=_auth_headers())
    starter_month = _get_plan("starter", "month")
    print(f"Using seeded plan: starter/month id={starter_month['id']}")

    # ═══════════════════════════════════════════════════════════════════
    # 1. THE ACTUAL EXPLOIT, PROVEN CLOSED.
    #    A throwaway signup-like customer (provisioning_state=
    #    'pending_subscription', site_limit=0, site_limit_source='plan' —
    #    the real shape §5.5's signup verification handler produces)
    #    subscribes with no card, then calls refresh DIRECTLY — the exact
    #    "skip the SDK widget" path a raw HTTP client could take.
    # ═══════════════════════════════════════════════════════════════════
    print("\n1. THE EXPLOIT: subscribe (no card) -> refresh directly, no SDK step ever run")
    cust_a = _make_customer(
        account_type="owner", plan="trial", site_limit=0,
        site_limit_source="plan", provisioning_state="pending_subscription",
    )
    before = _customer_by_id(cust_a["id"])
    print(f"  [pre-subscribe state] plan={before.get('plan')!r} site_limit={before.get('site_limit')!r} "
          f"provisioning_state={before.get('provisioning_state')!r} billing_status={before.get('billing_status')!r}")

    r = client.post("/v1/billing/subscription", json={"customer_id": cust_a["id"], "plan_id": starter_month["id"]})
    check("POST /subscription 200", r.status_code == 200, str(r.text))
    sub_body = r.json()
    sub_id = sub_body["onvo_subscription_id"]
    onvo_customer_id_a = sub_body["onvo_customer_id"]
    _created_onvo_subscription_ids.append(sub_id)

    onvo_sub = onvo.get_subscription(sub_id)
    print(f"  [ONVO state] immediately after create: status={onvo_sub.get('status')!r} "
          f"paymentMethodId={onvo_sub.get('paymentMethodId')!r}")
    check("ONVO itself reports status == 'trialing' (entitled-shaped) with NO card attached — "
          "this is the exact exploit precondition",
          onvo_sub.get("status") == "trialing" and not onvo_sub.get("paymentMethodId"),
          f"status={onvo_sub.get('status')!r} paymentMethodId={onvo_sub.get('paymentMethodId')!r}")

    # The exploit step: call refresh DIRECTLY. No card was ever created, no
    # /confirm was ever called — this is the raw-HTTP-client bypass path.
    r = client.post("/v1/billing/refresh", json={"customer_id": cust_a["id"]})
    check("POST /refresh 200", r.status_code == 200, str(r.text))
    status_body = r.json()
    print(f"  [refresh response] status={status_body.get('status')!r} plan_key={status_body.get('plan_key')!r} "
          f"site_limit={status_body.get('site_limit')!r} provisioning_state={status_body.get('provisioning_state')!r}")

    after = _customer_by_id(cust_a["id"])
    print(f"  [post-refresh vrm.customers row] plan={after.get('plan')!r} site_limit={after.get('site_limit')!r} "
          f"provisioning_state={after.get('provisioning_state')!r} billing_status={after.get('billing_status')!r}")

    check("mirrored ONVO subscription status is STILL 'trialing' (confirms the exploit precondition held "
          "through the refresh, this isn't a false negative from status having changed)",
          status_body.get("status") == "trialing", str(status_body.get("status")))
    check("EXPLOIT CLOSED: plan did NOT change (still 'trial')",
          after.get("plan") == before.get("plan") == "trial", f"before={before.get('plan')!r} after={after.get('plan')!r}")
    check("EXPLOIT CLOSED: site_limit did NOT change (still 0)",
          after.get("site_limit") == before.get("site_limit") == 0,
          f"before={before.get('site_limit')!r} after={after.get('site_limit')!r}")
    check("EXPLOIT CLOSED: provisioning_state did NOT promote (still 'pending_subscription')",
          after.get("provisioning_state") == before.get("provisioning_state") == "pending_subscription",
          f"before={before.get('provisioning_state')!r} after={after.get('provisioning_state')!r}")
    billing_row_a = _billing_customer_by_id(cust_a["id"])
    check("vrm.billing_customers.default_payment_method_id is genuinely NULL (confirms WHY it was held)",
          bool(billing_row_a) and billing_row_a.get("default_payment_method_id") is None,
          str(billing_row_a and billing_row_a.get("default_payment_method_id")))

    # ═══════════════════════════════════════════════════════════════════
    # 2. THE LEGITIMATE PATH STILL WORKS. Same customer, now actually
    #    attaches a card (the SDK-widget-equivalent flow), refreshes again
    #    -> entitlement grants, provisioning_state promotes.
    # ═══════════════════════════════════════════════════════════════════
    print("\n2. THE LEGITIMATE PATH: attach a real card via /confirm, refresh again")
    pm_a = _create_test_card(onvo_customer_id_a, auth_key=PUBLISHABLE_KEY)
    confirm_resp = _confirm_subscription_pub(sub_id, pm_a)
    check("POST /subscriptions/{id}/confirm with PUBLISHABLE KEY ONLY succeeds (2xx)",
          200 <= confirm_resp.status_code < 300, f"{confirm_resp.status_code}: {confirm_resp.text}")

    r = client.post("/v1/billing/refresh", json={"customer_id": cust_a["id"]})
    check("POST /refresh 200 after card attached", r.status_code == 200, str(r.text))
    status_after_card = r.json()
    print(f"  [refresh response] plan_key={status_after_card.get('plan_key')!r} "
          f"site_limit={status_after_card.get('site_limit')!r} "
          f"provisioning_state={status_after_card.get('provisioning_state')!r} "
          f"pm_last4={status_after_card.get('pm_last4')!r}")

    after_card = _customer_by_id(cust_a["id"])
    check("LEGITIMATE GRANT: plan_key == 'starter' now",
          status_after_card.get("plan_key") == "starter", str(status_after_card.get("plan_key")))
    check("LEGITIMATE GRANT: site_limit == plan's grant now",
          status_after_card.get("site_limit") == starter_month["site_limit"],
          f"{status_after_card.get('site_limit')} vs {starter_month['site_limit']}")
    check("LEGITIMATE GRANT: provisioning_state promoted to 'active' (§4.5 rule 8)",
          after_card.get("provisioning_state") == "active", str(after_card.get("provisioning_state")))
    check("a payment method is now mirrored (pm_last4 present)", bool(status_after_card.get("pm_last4")))

    # ═══════════════════════════════════════════════════════════════════
    # 3. AN ALREADY-ENTITLED CUSTOMER DOES NOT REGRESS. Reconcile again;
    #    still entitled, and no spurious "no payment method" log line.
    # ═══════════════════════════════════════════════════════════════════
    print("\n3. REGRESSION CHECK: reconcile an already-legitimately-entitled customer again")
    log_capture = io.StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setLevel(logging.INFO)
    billing_logger = logging.getLogger("vrm_api.billing")
    billing_logger.addHandler(handler)
    try:
        r = client.post("/v1/billing/refresh", json={"customer_id": cust_a["id"]})
    finally:
        billing_logger.removeHandler(handler)
    check("POST /refresh 200 (second reconcile of an already-entitled customer)",
          r.status_code == 200, str(r.text))
    status_regression = r.json()
    still_entitled = _customer_by_id(cust_a["id"])
    check("still entitled: plan_key unchanged ('starter')",
          status_regression.get("plan_key") == "starter", str(status_regression.get("plan_key")))
    check("still entitled: provisioning_state still 'active' (one-way promotion held)",
          still_entitled.get("provisioning_state") == "active", str(still_entitled.get("provisioning_state")))
    captured_log = log_capture.getvalue()
    check("NO spurious 'entitled_status_no_payment_method' log line for an already-entitled, "
          "payment-method-on-file customer",
          "billing.entitled_status_no_payment_method" not in captured_log,
          captured_log[:500] if "billing.entitled_status_no_payment_method" in captured_log else "(clean)")

    # ── Cleanup ──────────────────────────────────────────────────────────
    print("\nCleanup — cancelling any still-live ONVO subscriptions, deleting throwaway vrm.customers rows …")
    for created_sub_id in _created_onvo_subscription_ids:
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

    # Same discipline as `tools/validate_billing_step5_fix.py`'s own __main__
    # block — captures ONLY "vrm_api" and its children, INFO and up, NEVER
    # the root logger, NEVER DEBUG.
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
        print("Entitlement/payment-method fix validation FAILED.")
        raise SystemExit(1)
    print("Entitlement/payment-method fix validation gate PASSED.")
