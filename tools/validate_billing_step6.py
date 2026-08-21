from __future__ import annotations
"""
Live validation for PLAN_PHASE16.md §8 Step 6 (admin billing visibility +
customer-facing failure banners). Run for real against Oscar's ONVO
test-mode account, the real Supabase project, and the real, already-running
`vrm_api` (through `TestClient`, same "curl replacement" precedent as
`tools/validate_billing_step5_fix.py` / `tools/validate_billing_step3.py`)
AND the real, already-running Next.js dev server's webhook route
(`POST http://localhost:3000/api/webhooks/onvo`, a genuine HTTP call — that
route has no `vrm_api` equivalent to TestClient against).

This step's own new code (`app/(admin)/admin/customers/actions.ts`'s three
new Server Actions, `app/(admin)/admin/activity`'s two new panels,
`lib/server/db/admin.ts`'s three new/extended reads, `components/app/
BillingBanners`) is almost entirely a THIN LAYER over endpoints Steps 2-5.5
already built and validated (`POST /v1/billing/refresh`, `POST /v1/billing/
subscription/cancel`, `GET`-shaped direct Postgres reads). What this script
actually re-proves, for real:

  1. `mode='immediate'` cancel (Q4's admin-only escape hatch, wired to a
     caller for the first time this step) really does cancel the ONVO
     subscription NOW — re-read with the SECRET key after the call, not
     just trusted from our own mirror.
  2. `mode='at_period_end'` cancel, reachable from the SAME new admin
     surface, leaves the ONVO subscription live with `cancelAtPeriodEnd`
     set — re-read the same way.
  3. `POST /v1/billing/refresh` — the exact mechanism `promoteToActiveAction()`
     (Next.js) calls — genuinely re-promotes a `pending_subscription`
     customer back to `active` when ONVO shows an entitled subscription
     WITH a payment method (the real "promotion never fired" repair), and
     genuinely does NOTHING for a `pending_subscription` customer with no
     entitled subscription at all (the documented, correct no-op — a
     promote button cannot manufacture money that was never paid).
  4. A wrong-secret webhook delivery against the REAL Next.js route lands a
     `vrm.billing_events` row with `secret_ok=false` — the one thing
     `BillingEventsTable.tsx` must render distinguishably.
  5. `vrm.signup_requests` — a fresh row is visible via the exact read
     `listRecentSignups()` performs, within seconds.
  6. The exact Postgres state a `past_due` / over-limit customer would have
     is written and re-read correctly (`vrm.customers.billing_status`,
     `.site_limit`, `active` site count) — `BillingBanners.tsx`'s own
     condition (`billing_status === 'past_due'` / `over_limit`) is then
     checked against that real row's shape, not re-triggered through a
     live renewal failure (impractical to force inside a short test-mode
     run — see this script's own note at that section).

What this script deliberately does NOT do: drive a real browser against
`/admin/customers` or `/app` with an authenticated Supabase session — no
browser automation is set up in this repo/environment (same limitation
`validate_billing_step5_fix.py` already states for the ONVO SDK widget).
`npm run build`/`typecheck`/`lint` (run separately, see the coder's own
report) confirm the React/TSX layer compiles and type-matches these same
wire shapes; `tools/validate_admin_db.ts` (scratchpad, not committed) calls
`lib/server/db/admin.ts`'s real functions directly against this same test
data to confirm the exact rows these panels render are shaped as expected.

Every throwaway `vrm.customers` row is named "zzz-billing-step6 validation
— safe to delete" and DELETED at the end (cascade takes billing_customers/
subscriptions/subscription_invoices/sites with it), matching every prior
billing validation script's own convention. Throwaway `vrm.signup_requests`
rows are deleted too. ONVO objects cannot be deleted through ONVO's
confirmed API surface; any still-live subscription is canceled first
(best-effort).

Leak check: identical discipline to every prior billing validation script —
scoped to the "vrm_api" logger namespace, INFO and up, never DEBUG, never
the root logger; stdout + every captured log record scanned for the raw
ONVO secret key value, the webhook secret value, and the service-role key.

Usage:
    python -m tools.validate_billing_step6
"""
import contextlib
import hashlib
import io
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

from fastapi.testclient import TestClient

from database.supabase_client import get_client
from vrm_api import onvo
from vrm_api.main import app

ONVO_BASE_URL = "https://api.onvopay.com/v1"
MARKER = "zzz-billing-step6 validation — safe to delete"

MODE = os.environ.get("ONVO_MODE")
SECRET_KEY = os.environ.get("ONVO_SECRET_KEY")
PUBLISHABLE_KEY = os.environ.get("ONVO_PUBLISHABLE_KEY")
PIPELINE_KEY = os.environ.get("PIPELINE_API_KEY")
NEXTJS_BASE_URL = os.environ.get("VALIDATE_NEXTJS_URL", "http://localhost:3000")

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

# `ONVO_WEBHOOK_SECRET` lives only in the Next.js app's own env
# (`victron-monitor/web/.env.local`, a different project's key pair from
# this repo's root `.env` — see that file's own header comment), not the
# root `.env` `load_dotenv()` above already read. Not actually NEEDED for
# section 5's check to work (a deliberately-wrong header value proves the
# rejection path regardless of what the real secret is) — read here only so
# the leak-check at the bottom of this file can also confirm the real value
# never appears in this script's own captured output.
WEBHOOK_SECRET = None
_web_env_path = os.path.join(os.path.dirname(__file__), "..", "victron-monitor", "web", ".env.local")
if os.path.exists(_web_env_path):
    with open(_web_env_path, "r", encoding="utf-8") as _f:
        for _line in _f:
            if _line.startswith("ONVO_WEBHOOK_SECRET="):
                WEBHOOK_SECRET = _line.split("=", 1)[1].strip()
                break

db = get_client()
vrm = db.schema("vrm")

_results: list[tuple[str, bool, str]] = []
_created_customer_ids: list[str] = []
_created_onvo_subscription_ids: list[str] = []
_created_signup_request_ids: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    _results.append((label, ok, detail))
    tag = "OK  " if ok else "FAIL"
    print(f"  {tag} {label}" + (f" — {detail}" if detail else ""))
    return ok


def _create_test_card(onvo_customer_id: str, *, auth_key: str, number: str = "4242424242424242") -> str:
    """Mirrors the SDK widget's own iframe — publishable-key-only, same as
    `validate_billing_step5_fix.py:_create_test_card()`."""
    r = requests.post(
        f"{ONVO_BASE_URL}/payment-methods",
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
    return requests.post(
        f"{ONVO_BASE_URL}/subscriptions/{onvo_subscription_id}/confirm",
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
    slug = f"zzz-billing-step6-{uuid.uuid4().hex[:10]}"
    row = {"name": MARKER, "slug": slug, "auth_email": f"{slug}@example.com", **overrides}
    created = vrm.table("customers").insert(row).execute().data[0]
    _created_customer_ids.append(created["id"])
    return created


def _customer_by_id(customer_id: str) -> dict:
    return vrm.table("customers").select("*").eq("id", customer_id).limit(1).execute().data[0]


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {PIPELINE_KEY}"}


def _subscribe_and_card(client: TestClient, customer: dict, plan_row: dict) -> str:
    """The real subscribe -> widget-simulated card attach -> refresh
    sequence `validate_billing_step5_fix.py` already established — reused
    here just to get to "an entitled, carded subscription" quickly, since
    THAT sequence (not this script's own new admin actions) is what Steps 3
    and 5 already validate for its own sake."""
    r = client.post("/v1/billing/subscription", json={"customer_id": customer["id"], "plan_id": plan_row["id"]})
    r.raise_for_status()
    sub_body = r.json()
    sub_id = sub_body["onvo_subscription_id"]
    _created_onvo_subscription_ids.append(sub_id)
    onvo_customer_id = sub_body["onvo_customer_id"]

    pm_id = _create_test_card(onvo_customer_id, auth_key=PUBLISHABLE_KEY)
    confirm_resp = _confirm_subscription_pub(sub_id, pm_id)
    confirm_resp.raise_for_status()

    r = client.post("/v1/billing/refresh", json={"customer_id": customer["id"]})
    r.raise_for_status()
    return sub_id


def main() -> None:
    print("=" * 78)
    print(f"Step 6 validation — ONVO_MODE={MODE!r}, vrm_api base=TestClient, Next.js base={NEXTJS_BASE_URL!r}")
    print("=" * 78)

    client = TestClient(app, headers=_auth_headers())
    starter_month = _get_plan("starter", "month")
    print(f"Using seeded plan: starter/month id={starter_month['id']}")

    # ═══════════════════════════════════════════════════════════════════
    # 1. Admin cancel — mode='at_period_end' (the SAME endpoint the
    #    customer-facing UI already uses, now reachable from
    #    `billingCancelAction(customerId, 'at_period_end')`) — real ONVO
    #    state re-read with the secret key, not just our own mirror.
    # ═══════════════════════════════════════════════════════════════════
    print("\n1. Admin cancel — mode='at_period_end'")
    cust_a = _make_customer(account_type="owner")
    sub_id_a = _subscribe_and_card(client, cust_a, starter_month)
    onvo_before = onvo.get_subscription(sub_id_a)
    check("ONVO subscription entitled-shaped before cancel", onvo_before.get("status") in ("trialing", "active"),
          str(onvo_before.get("status")))

    r = client.post("/v1/billing/subscription/cancel", json={"customer_id": cust_a["id"], "mode": "at_period_end"})
    check("POST /subscription/cancel mode=at_period_end -> 200", r.status_code == 200, str(r.text))
    check("mirror reports cancel_at_period_end=True", r.json().get("cancel_at_period_end") is True)

    onvo_after = onvo.get_subscription(sub_id_a)
    print(f"  [ONVO, secret-key re-read] status={onvo_after.get('status')!r} "
          f"cancelAtPeriodEnd={onvo_after.get('cancelAtPeriodEnd')!r} canceledAt={onvo_after.get('canceledAt')!r}")
    check("ONVO itself reports cancelAtPeriodEnd=True", onvo_after.get("cancelAtPeriodEnd") is True,
          str(onvo_after.get("cancelAtPeriodEnd")))
    check("ONVO subscription is STILL LIVE (not immediately canceled)",
          onvo_after.get("status") != "canceled" and not onvo_after.get("canceledAt"),
          f"status={onvo_after.get('status')} canceledAt={onvo_after.get('canceledAt')}")

    # ═══════════════════════════════════════════════════════════════════
    # 2. Admin cancel — mode='immediate' (Q4's admin-only escape hatch,
    #    reachable from a UI caller for the first time this step).
    # ═══════════════════════════════════════════════════════════════════
    print("\n2. Admin cancel — mode='immediate'")
    cust_b = _make_customer(account_type="owner")
    sub_id_b = _subscribe_and_card(client, cust_b, starter_month)

    r = client.post("/v1/billing/subscription/cancel", json={"customer_id": cust_b["id"], "mode": "immediate"})
    check("POST /subscription/cancel mode=immediate -> 200", r.status_code == 200, str(r.text))

    onvo_after_immediate = onvo.get_subscription(sub_id_b)
    print(f"  [ONVO, secret-key re-read] status={onvo_after_immediate.get('status')!r} "
          f"canceledAt={onvo_after_immediate.get('canceledAt')!r}")
    check("ONVO subscription status == 'canceled' — REAL, re-read with the secret key",
          onvo_after_immediate.get("status") == "canceled", str(onvo_after_immediate.get("status")))
    check("ONVO subscription canceledAt is set", bool(onvo_after_immediate.get("canceledAt")),
          str(onvo_after_immediate.get("canceledAt")))
    check("customer immediately lost entitlement (plan back to trial-equivalent, site_limit 0)",
          _customer_by_id(cust_b["id"]).get("site_limit") == 0,
          str(_customer_by_id(cust_b["id"]).get("site_limit")))

    r = client.post("/v1/billing/subscription/cancel", json={"customer_id": cust_b["id"], "mode": "immediate"})
    check("a SECOND cancel on an already-canceled subscription -> 409 no_active_subscription (not a crash)",
          r.status_code == 409, str(r.text))

    # ═══════════════════════════════════════════════════════════════════
    # 3. Promote to active — the REAL "promotion never fired" repair.
    #    `promoteToActiveAction()` (Next.js) calls exactly
    #    `POST /v1/billing/refresh` — reused here directly, since that IS
    #    the mechanism (no second endpoint to test).
    # ═══════════════════════════════════════════════════════════════════
    print("\n3. Promote to active — real repair: entitled+carded, but provisioning_state stuck")
    cust_c = _make_customer(account_type="owner", provisioning_state="pending_subscription", site_limit=0, site_limit_source="plan")
    _subscribe_and_card(client, cust_c, starter_month)
    after_normal_refresh = _customer_by_id(cust_c["id"])
    check("normal refresh already promoted this customer (sanity check on the fixture itself)",
          after_normal_refresh.get("provisioning_state") == "active",
          str(after_normal_refresh.get("provisioning_state")))

    # Simulate "the promotion never fired" — ONVO genuinely shows an
    # entitled, carded subscription (unchanged, still true), but our own
    # provisioning_state got stuck back on pending_subscription (the exact
    # support scenario §7's failure-modes table describes).
    vrm.table("customers").update({"provisioning_state": "pending_subscription"}).eq("id", cust_c["id"]).execute()
    stuck = _customer_by_id(cust_c["id"])
    check("fixture: provisioning_state forced back to pending_subscription", stuck.get("provisioning_state") == "pending_subscription")

    r = client.post("/v1/billing/refresh", json={"customer_id": cust_c["id"]})
    check("POST /refresh (== Promote to active) -> 200", r.status_code == 200, str(r.text))
    promoted_body = r.json()
    print(f"  [after promote] provisioning_state={promoted_body.get('provisioning_state')!r} "
          f"billing_status={promoted_body.get('billing_status')!r} plan_key={promoted_body.get('plan_key')!r}")
    check("Promote to active REPAIRED provisioning_state back to 'active' — the real mechanism works",
          promoted_body.get("provisioning_state") == "active", str(promoted_body.get("provisioning_state")))

    # ═══════════════════════════════════════════════════════════════════
    # 4. Promote to active — the documented correct NO-OP: a
    #    pending_subscription customer with NO entitled subscription at
    #    all. A promote button cannot manufacture money that was never
    #    paid.
    # ═══════════════════════════════════════════════════════════════════
    print("\n4. Promote to active — correct no-op: never paid at all")
    cust_d = _make_customer(account_type="owner", provisioning_state="pending_subscription", site_limit=0, site_limit_source="plan")
    r = client.post("/v1/billing/refresh", json={"customer_id": cust_d["id"]})
    check("POST /refresh on a never-subscribed pending customer -> 200 (not an error)", r.status_code == 200, str(r.text))
    check("provisioning_state UNCHANGED — correct: this customer never paid",
          r.json().get("provisioning_state") == "pending_subscription", str(r.json().get("provisioning_state")))
    check("site_limit still 0 — no entitlement was manufactured", r.json().get("site_limit") == 0, str(r.json().get("site_limit")))

    # ═══════════════════════════════════════════════════════════════════
    # 5. Wrong-secret webhook — against the REAL, running Next.js route,
    #    not vrm_api directly (that route is the only place a rejected
    #    secret is ever recorded — vrm_api's own /webhook-event is never
    #    reached on this path, see app/api/webhooks/onvo/route.ts).
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n5. Wrong-secret webhook against {NEXTJS_BASE_URL}/api/webhooks/onvo (REAL HTTP)")
    marker_payload = {"type": "subscription.renewal.failed", "data": {"marker": MARKER}}
    try:
        webhook_resp = requests.post(
            f"{NEXTJS_BASE_URL}/api/webhooks/onvo",
            headers={"X-Webhook-Secret": "definitely-the-wrong-secret", "Content-Type": "application/json"},
            json=marker_payload, timeout=15,
        )
        check("wrong-secret webhook -> 401", webhook_resp.status_code == 401, str(webhook_resp.status_code))
        check("response body is empty (§6.5: never confirm/deny anything)", webhook_resp.text == "", repr(webhook_resp.text))

        # Confirm the row landed, via the EXACT read `listBillingEvents()`
        # (Next.js) uses — same table, same order, checked from this
        # script's own Supabase client since Python and the Node admin.ts
        # read the identical Postgres row.
        rows = (
            vrm.table("billing_events").select("*")
            .eq("secret_ok", False).order("received_at", desc=True).limit(5).execute().data
        )
        matching = [row for row in rows if (row.get("payload") or {}).get("data", {}).get("marker") == MARKER]
        check("a vrm.billing_events row with secret_ok=false was recorded for THIS delivery",
              bool(matching), f"found {len(matching)} matching row(s) among {len(rows)} recent secret_ok=false rows")
    except requests.RequestException as exc:
        check("Next.js dev server reachable at " + NEXTJS_BASE_URL, False, str(exc))

    # ═══════════════════════════════════════════════════════════════════
    # 6. Recent signups — a fresh vrm.signup_requests row, visible via the
    #    exact read listRecentSignups() performs, within seconds (inserted
    #    directly — the fastest real path to a staging row per this step's
    #    own validation note; a real POST through the public Server Action
    #    is Step 5.5's own already-validated territory).
    # ═══════════════════════════════════════════════════════════════════
    print("\n6. Recent signups — a fresh vrm.signup_requests row appears immediately")
    token_hash = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    signup_email = f"zzz-billing-step6-signup-{uuid.uuid4().hex[:8]}@example.com"
    now = datetime.now(timezone.utc)
    signup_row = vrm.table("signup_requests").insert({
        "email": signup_email, "token_hash": token_hash, "name": MARKER,
        "account_type": "owner", "ui_language": "en",
        "created_at": now.isoformat(), "expires_at": (now + timedelta(hours=24)).isoformat(),
    }).execute().data[0]
    _created_signup_request_ids.append(signup_row["id"])

    read_back = (
        vrm.table("signup_requests").select("*")
        .order("created_at", desc=True).limit(10).execute().data
    )
    check("fresh signup row is immediately visible in the newest-first read listRecentSignups() performs",
          any(r["id"] == signup_row["id"] for r in read_back),
          f"row id {signup_row['id']} in top 10 of {len(read_back)}")
    check("unconsumed, not-yet-expired -> would render 'Awaiting verification' (expired=false)",
          signup_row.get("consumed_at") is None and datetime.fromisoformat(signup_row["expires_at"]) > now)

    # ═══════════════════════════════════════════════════════════════════
    # 7. past_due / over-limit banner data contract — real Postgres state,
    #    checked against BillingBanners.tsx's own condition
    #    (billing_status === 'past_due' / over_limit). Forcing a REAL
    #    renewal failure needs ONVO to actually attempt a renewal charge,
    #    which does not happen inside a short test-mode run (no "trigger
    #    renewal now" endpoint is documented) — simulated directly in the
    #    mirror instead, exactly as this step's own validation note allows.
    # ═══════════════════════════════════════════════════════════════════
    print("\n7. past_due / over-limit banner data contract (simulated in the mirror)")
    cust_e = _make_customer(account_type="owner", plan="starter", site_limit=1, site_limit_source="manual", billing_status="active")
    vrm.table("customers").update({"billing_status": "past_due"}).eq("id", cust_e["id"]).execute()
    past_due_row = _customer_by_id(cust_e["id"])
    check("customer row now billing_status='past_due' — BillingBanners.tsx's exact showPastDue condition",
          past_due_row.get("billing_status") == "past_due", str(past_due_row.get("billing_status")))

    # over_limit is computed at read time (active_sites > site_limit) by
    # vrm_api/routers/billing.py:_status_response() — not a stored column —
    # so this checks the SAME two real facts BillingStatusOut.over_limit is
    # derived from, both freshly read from Postgres.
    site_row = vrm.table("sites").insert({
        "customer_id": cust_e["id"], "site_id": f"{cust_e['slug']}-site-1", "display_name": "Site 1",
        "timezone": "America/Costa_Rica", "system_type": "hybrid", "active": True,
    }).execute().data[0]
    site_row_2 = vrm.table("sites").insert({
        "customer_id": cust_e["id"], "site_id": f"{cust_e['slug']}-site-2", "display_name": "Site 2",
        "timezone": "America/Costa_Rica", "system_type": "hybrid", "active": True,
    }).execute().data[0]
    active_count = vrm.table("sites").select("id", count="exact").eq("customer_id", cust_e["id"]).eq("active", True).limit(1).execute().count
    check("2 active sites vs. site_limit=1 -> over_limit is True by BillingStatusOut's own formula",
          active_count is not None and active_count > past_due_row.get("site_limit", 0),
          f"active_sites={active_count} site_limit={past_due_row.get('site_limit')}")

    # And the SAME status endpoint every customer's own /app/billing read
    # calls confirms it end to end (no ONVO calls needed — this customer
    # has no vrm.billing_customers row, so reconcile_customer() is a no-op
    # per its own documented fast path).
    status_resp = client.get(f"/v1/billing/status?customer_id={cust_e['id']}")
    check("GET /v1/billing/status -> 200", status_resp.status_code == 200, str(status_resp.text))
    status_body = status_resp.json()
    print(f"  [GET /status] billing_status={status_body.get('billing_status')!r} over_limit={status_body.get('over_limit')!r} "
          f"active_sites={status_body.get('active_sites')!r} site_limit={status_body.get('site_limit')!r}")
    check("GET /v1/billing/status reports over_limit=True for real", status_body.get("over_limit") is True)
    check("GET /v1/billing/status reports billing_status='past_due' for real (untouched by the no-op reconcile)",
          status_body.get("billing_status") == "past_due", str(status_body.get("billing_status")))

    # ── Cleanup ──────────────────────────────────────────────────────────
    print("\nCleanup — cancelling any still-live ONVO subscriptions, deleting throwaway rows …")
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

    for signup_id in _created_signup_request_ids:
        try:
            vrm.table("signup_requests").delete().eq("id", signup_id).execute()
        except Exception as exc:  # noqa: BLE001 — cleanup best-effort
            print(f"  WARN could not delete throwaway signup_requests row {signup_id} — {exc}")
    print(f"  deleted {len(_created_signup_request_ids)} throwaway vrm.signup_requests row(s)")
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

    # Same discipline as every prior billing validation script's own
    # __main__ block — captures ONLY "vrm_api" and its children, INFO and
    # up, NEVER the root logger, NEVER DEBUG.
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
    leak = (
        SECRET_KEY in captured
        or _leak_substring in captured
        or (WEBHOOK_SECRET and WEBHOOK_SECRET in captured)
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "\0impossible\0") in captured
        or os.environ.get("SUPABASE_SECRET_KEY", "\0impossible\0") in captured
        or PIPELINE_KEY in captured
    )
    print("\n" + "=" * 78)
    print("LEAK CHECK (automated): scanned this run's stdout + every log record for "
          "the raw ONVO secret key, its key-prefix substring, the webhook secret, "
          "the pipeline key, and the Supabase service-role/secret key.")
    print(f"  {'FAIL - LEAK DETECTED' if leak else 'OK   - no leak found'}")
    print("=" * 78)

    n_ok = sum(1 for _, ok, _ in _results if ok)
    n_total = len(_results)
    print(f"\n{n_ok}/{n_total} checks passed.")
    if failed_hard or leak or n_ok != n_total:
        print("Step 6 validation FAILED.")
        raise SystemExit(1)
    print("Step 6 validation gate PASSED.")
