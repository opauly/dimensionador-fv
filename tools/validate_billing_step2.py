from __future__ import annotations
"""
Step 2 validation gate (PLAN_PHASE16.md §8 Step 2) — `vrm_api/onvo.py` +
`vrm_api/billing.py`, run for real against Oscar's ONVO test-mode account
and the real Supabase project. No HTTP surface exists yet (that's Step 3);
this script calls `vrm_api.billing.reconcile_customer()` /
`apply_entitlements()` directly, the same way a future router will.

Every assertion in PLAN_PHASE16.md §8 Step 2's own validation list is a real
check here (not eyeballed): the mirror after a reconcile matches ONVO
field-for-field; `site_limit_source='manual'` really blocks a write;
promotion happens in the same write as the site_limit raise and never
reverts; `cancelAtPeriodEnd` retention; a dropped-entitlement customer's
`vrm.sites` row is provably untouched (row count + content, not eyeballed);
an unrecognized status holds entitlement and logs loudly; two concurrent
reconciles land one coherent state.

Every throwaway `vrm.customers` row this script creates is named
`"Phase 16 Step 2 validation — safe to delete"` and DELETED at the end
(cascade takes `vrm.billing_customers`/`vrm.subscriptions`/
`vrm.subscription_invoices`/`vrm.sites` with it — migration 012/025's own
`ON DELETE CASCADE`). The ONVO-side objects (customers/products/prices/
subscriptions) cannot be deleted through ONVO's API (no such operation is
in §0.2b's confirmed list) — they are left in place, marked
`"Phase 16 Step 2 validation — safe to delete"` in name/description/
metadata, same convention `tools/onvo_probe.py` established, and any
subscription still live at the end of this run is canceled immediately
(best-effort) so nothing keeps "billing" in test mode after this script
exits.

Leak check: every line this script prints AND every log record this
product's own loggers emit (the "vrm_api" logger and its children
vrm_api.billing/vrm_api.onvo — deliberately NOT the root logger; see the
`__main__` block's own comment on why raising the root logger to DEBUG is
itself a leak vector, via httpx/httpcore's verbose header logging) is
captured and scanned at the end for the literal `ONVO_SECRET_KEY` value and
for the generic substring `_secret_key_` — both must be absent. This is the
automated half of PLAN_PHASE16.md §8 Step 2's "grep the process output"
requirement; the tester agent should additionally pipe this script's real
stdout through `grep -c '_secret_key_'` by hand and confirm zero hits,
since a check this important is worth two independent looks.

Usage:
    python -m tools.validate_billing_step2
"""
import concurrent.futures
import contextlib
import io
import logging
import os
import sys
import time
import uuid

import requests
from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client
from vrm_api import billing, onvo

BASE_URL = "https://api.onvopay.com/v1"
MARKER = "Phase 16 Step 2 validation — safe to delete"

MODE = os.environ.get("ONVO_MODE")
SECRET_KEY = os.environ.get("ONVO_SECRET_KEY")

if not SECRET_KEY:
    print("ONVO_SECRET_KEY not set in the environment. Aborting.", file=sys.stderr)
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


# ── ONVO helpers (payment-method creation isn't in vrm_api/onvo.py at all —
#    per PLAN_PHASE16.md §5.2/§6.3, a card is only ever entered client-side
#    through ONVO's own SDK; this script makes the same raw call
#    tools/onvo_probe.py already does, standing in for "the browser") ──────
def _create_test_card(onvo_customer_id: str) -> str:
    r = requests.post(
        f"{BASE_URL}/payment-methods",
        headers={"Authorization": f"Bearer {SECRET_KEY}", "Content-Type": "application/json"},
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
    slug = f"zzz-billing-step2-{uuid.uuid4().hex[:10]}"
    row = {
        "name": MARKER, "slug": slug,
        "auth_email": f"{slug}@example.com",
        **overrides,
    }
    created = vrm.table("customers").insert(row).execute().data[0]
    _created_customer_ids.append(created["id"])
    return created


def _fresh_customer() -> dict:
    return vrm.table("customers").select("*").eq("id", _created_customer_ids[-1]).limit(1).execute().data[0]


def _customer_by_id(customer_id: str) -> dict:
    return vrm.table("customers").select("*").eq("id", customer_id).limit(1).execute().data[0]


def _link_onvo_customer(customer_id: str, onvo_customer_id: str) -> None:
    """Stands in for what Step 3's subscribe endpoint will do (§5.2 step
    2): create/record the ONVO customer BEFORE reconcile is ever called —
    reconcile_customer() requires a vrm.billing_customers row to know which
    ONVO customer to read."""
    vrm.table("billing_customers").insert({
        "customer_id": customer_id, "onvo_customer_id": onvo_customer_id, "mode": "test",
    }).execute()


def _create_subscription(onvo_customer_id: str, pm_id: str, plan_row: dict, *, trial_days: int | None = None) -> dict:
    sub = onvo.create_subscription(
        customer_id=onvo_customer_id, price_id=plan_row["onvo_price_id"],
        payment_method_id=pm_id, trial_period_days=trial_days,
        description=MARKER, metadata={"purpose": MARKER},
    )
    _created_onvo_subscription_ids.append(sub["id"])
    return sub


def main() -> None:
    print("=" * 78)
    print(f"Step 2 validation — ONVO_MODE={MODE!r}, base URL={BASE_URL}")
    print("=" * 78)

    starter_month = _get_plan("starter", "month")
    print(f"\nUsing seeded plan: starter/month, vrm.plans.id={starter_month['id']}, "
          f"onvo_price_id={starter_month['onvo_price_id']}, site_limit={starter_month['site_limit']}")

    # ── Test 1: create + reconcile, mirror matches ONVO, plan/site_limit set ─
    print("\n1. Create ONVO customer+subscription for a throwaway customer -> "
          "reconcile -> mirror matches ONVO, plan/site_limit set")
    cust_a = _make_customer(site_limit_source="plan")
    onvo_cust_a = onvo.create_customer(name=MARKER, email=f"{cust_a['slug']}@example.com")
    pm_a = _create_test_card(onvo_cust_a["id"])
    _link_onvo_customer(cust_a["id"], onvo_cust_a["id"])
    sub_a = _create_subscription(onvo_cust_a["id"], pm_a, starter_month, trial_days=7)

    state_a = billing.reconcile_customer(cust_a["id"])
    mirror_sub_a = state_a["subscription"]
    check("mirror subscription exists after reconcile", mirror_sub_a is not None)
    if mirror_sub_a:
        check("mirror onvo_subscription_id matches ONVO", mirror_sub_a["onvo_subscription_id"] == sub_a["id"])
        check("mirror status matches ONVO", mirror_sub_a["status"] == sub_a["status"], mirror_sub_a["status"])
        check("mirror plan_key resolved to starter", mirror_sub_a["plan_key"] == "starter", str(mirror_sub_a["plan_key"]))
        check("mirror amount_minor matches ONVO's price", mirror_sub_a["amount_minor"] == starter_month["amount_minor"])
        check("mirror currency matches ONVO's price", mirror_sub_a["currency"] == "USD")
    check("customer.plan set to starter", state_a["plan"] == "starter", str(state_a["plan"]))
    check("customer.site_limit raised to plan's grant", state_a["site_limit"] == starter_month["site_limit"], str(state_a["site_limit"]))
    check("customer.billing_status == trialing", state_a["billing_status"] == "trialing", str(state_a["billing_status"]))

    billing_row_a = state_a["billing_customer"]
    check("billing_customers row exists with a default payment method", bool(billing_row_a and billing_row_a.get("default_payment_method_id")))
    if billing_row_a:
        check("billing_customers pm_last4 == 4242", billing_row_a.get("pm_last4") == "4242", str(billing_row_a.get("pm_last4")))

    # ── Test 2: site_limit_source='manual' really blocks the write ──────────
    print("\n2. site_limit_source='manual' -> reconcile again -> site_limit UNTOUCHED")
    vrm.table("customers").update({"site_limit_source": "manual", "site_limit": 777}).eq("id", cust_a["id"]).execute()
    state_a2 = billing.reconcile_customer(cust_a["id"])
    check("site_limit stayed at the hand-set 777, not reset to the plan's grant",
          state_a2["site_limit"] == 777, str(state_a2["site_limit"]))
    check("plan is still updated even though site_limit is manual (only site_limit is guarded)",
          state_a2["plan"] == "starter", str(state_a2["plan"]))

    # ── Test 3: promotion (pending_subscription -> active, one-way) ─────────
    print("\n3. Promotion — pending_subscription + site_limit=0 -> subscribe -> "
          "reconcile -> provisioning_state='active' AND site_limit raised, same write")
    cust_b = _make_customer(
        provisioning_state="pending_subscription", site_limit=0,
        site_limit_source="plan", plan="trial", origin="self_serve",
    )
    check("customer B starts pending_subscription/site_limit=0", cust_b["provisioning_state"] == "pending_subscription" and cust_b["site_limit"] == 0)

    onvo_cust_b = onvo.create_customer(name=MARKER, email=f"{cust_b['slug']}@example.com")
    pm_b = _create_test_card(onvo_cust_b["id"])
    _link_onvo_customer(cust_b["id"], onvo_cust_b["id"])
    sub_b = _create_subscription(onvo_cust_b["id"], pm_b, starter_month, trial_days=7)

    state_b = billing.reconcile_customer(cust_b["id"])
    check("promotion: provisioning_state -> active", state_b["provisioning_state"] == "active", str(state_b["provisioning_state"]))
    check("promotion: site_limit raised to plan's grant in the SAME reconcile", state_b["site_limit"] == starter_month["site_limit"], str(state_b["site_limit"]))
    check("promotion: plan set to starter", state_b["plan"] == "starter", str(state_b["plan"]))

    print("   cancelling that subscription immediately, then reconciling again "
         "-> provisioning_state must STAY 'active' (one-way)")
    onvo.cancel_subscription(sub_b["id"])
    state_b2 = billing.reconcile_customer(cust_b["id"])
    check("provisioning_state stays 'active' after the subscription lapses (rule 8, one-way)",
          state_b2["provisioning_state"] == "active", str(state_b2["provisioning_state"]))
    check("plan falls back to 'trial' once not entitled", state_b2["plan"] == "trial", str(state_b2["plan"]))
    check("site_limit falls back to 0 (site_limit_source='plan')", state_b2["site_limit"] == 0, str(state_b2["site_limit"]))

    # ── Test 4: cancelAtPeriodEnd retains entitlement ────────────────────────
    print("\n4. cancelAtPeriodEnd=true -> reconcile -> entitlement RETAINED, "
          "cancel_at_period_end=true in the mirror")
    cust_c = _make_customer(site_limit_source="plan")
    onvo_cust_c = onvo.create_customer(name=MARKER, email=f"{cust_c['slug']}@example.com")
    pm_c = _create_test_card(onvo_cust_c["id"])
    _link_onvo_customer(cust_c["id"], onvo_cust_c["id"])
    sub_c = _create_subscription(onvo_cust_c["id"], pm_c, starter_month, trial_days=None)  # immediate charge -> active
    state_c0 = billing.reconcile_customer(cust_c["id"])
    check("customer C is entitled before the cancel-at-period-end flag", state_c0["plan"] == "starter", str(state_c0["plan"]))

    onvo.update_subscription(sub_c["id"], cancel_at_period_end=True)
    state_c1 = billing.reconcile_customer(cust_c["id"])
    check("cancel_at_period_end mirrored true", bool(state_c1["subscription"] and state_c1["subscription"].get("cancel_at_period_end") is True))
    check("entitlement RETAINED (plan still starter, not dropped)", state_c1["plan"] == "starter", str(state_c1["plan"]))
    check("site_limit still the plan's grant", state_c1["site_limit"] == starter_month["site_limit"], str(state_c1["site_limit"]))

    # ── Test 5: dropped entitlement never touches vrm.sites ─────────────────
    print("\n5. Cancel immediately -> reconcile -> entitlement DROPPED, and "
          "vrm.sites row for this customer is provably UNTOUCHED")
    site_row = vrm.table("sites").insert({
        "customer_id": cust_c["id"], "site_id": f"{cust_c['slug']}-house",
        "display_name": "Step 2 validation site (safe to delete)", "active": True,
    }).execute().data[0]
    before_site = vrm.table("sites").select("*").eq("id", site_row["id"]).limit(1).execute().data[0]

    onvo.cancel_subscription(sub_c["id"])
    state_c2 = billing.reconcile_customer(cust_c["id"])
    check("entitlement dropped: plan falls back to trial", state_c2["plan"] == "trial", str(state_c2["plan"]))
    check("entitlement dropped: site_limit falls back to 0", state_c2["site_limit"] == 0, str(state_c2["site_limit"]))

    after_site = vrm.table("sites").select("*").eq("id", site_row["id"]).limit(1).execute().data[0]
    site_count = vrm.table("sites").select("id", count="exact").eq("customer_id", cust_c["id"]).limit(1).execute().count
    check("vrm.sites row count for this customer is still exactly 1", site_count == 1, str(site_count))
    check("vrm.sites row is byte-for-byte unchanged (active flag + every field)", before_site == after_site)
    check("vrm.sites.active is still true — no site was deactivated", after_site.get("active") is True)

    # ── Test 6: an invented status HOLDS entitlement and logs loudly ────────
    print("\n6. Feed an invented status directly -> entitlement HELD, error logged")
    log_records: list[str] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            log_records.append(self.format(record))

    handler = _ListHandler()
    handler.setLevel(logging.ERROR)
    logging.getLogger("vrm_api.billing").addHandler(handler)

    before_c3 = _customer_by_id(cust_c["id"])
    mirror_sub_row = vrm.table("subscriptions").select("id").eq("onvo_subscription_id", sub_c["id"]).limit(1).execute().data[0]
    vrm.table("subscriptions").update({"status": "some_future_onvo_status_xyz"}).eq("id", mirror_sub_row["id"]).execute()

    billing.apply_entitlements(cust_c["id"])  # NOT reconcile_customer() — must not re-fetch from ONVO and overwrite the injected status
    after_c3 = _customer_by_id(cust_c["id"])

    logging.getLogger("vrm_api.billing").removeHandler(handler)

    check("plan held (unchanged) for an unrecognized status", after_c3["plan"] == before_c3["plan"], f"{before_c3['plan']!r} -> {after_c3['plan']!r}")
    check("site_limit held (unchanged) for an unrecognized status", after_c3["site_limit"] == before_c3["site_limit"])
    check("billing_status held (unchanged) for an unrecognized status", after_c3["billing_status"] == before_c3["billing_status"])
    check("an error-level log line was produced for the unrecognized status",
          any("billing.unrecognized_status" in r and "some_future_onvo_status_xyz" in r for r in log_records),
          f"{len(log_records)} error record(s) captured")

    # Restore the real status so cleanup/cancel below still makes sense.
    vrm.table("subscriptions").update({"status": "canceled"}).eq("id", mirror_sub_row["id"]).execute()

    # ── Test 7: two concurrent reconciles -> one coherent final state ───────
    print("\n7. Two concurrent reconcile_customer() calls -> exactly one "
          "coherent final state, no torn/interleaved write")
    cust_d = _make_customer(site_limit_source="plan")
    onvo_cust_d = onvo.create_customer(name=MARKER, email=f"{cust_d['slug']}@example.com")
    pm_d = _create_test_card(onvo_cust_d["id"])
    _link_onvo_customer(cust_d["id"], onvo_cust_d["id"])
    sub_d = _create_subscription(onvo_cust_d["id"], pm_d, starter_month, trial_days=7)
    billing.reconcile_customer(cust_d["id"])  # first reconcile creates the mirror row — the race below only exercises the UPDATE path

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(billing.reconcile_customer, cust_d["id"]) for _ in range(2)]
        concurrent.futures.wait(futures)
        for f in futures:
            f.result()  # re-raise if either call failed

    mirror_rows_d = vrm.table("subscriptions").select("*").eq("customer_id", cust_d["id"]).execute().data
    check("exactly one mirror subscription row for customer D", len(mirror_rows_d) == 1, str(len(mirror_rows_d)))
    if mirror_rows_d:
        row = mirror_rows_d[0]
        check("that row's onvo_subscription_id matches ONVO's real subscription", row["onvo_subscription_id"] == sub_d["id"])
        check("that row is not torn: status is a real, non-null value", bool(row.get("status")))
        check("that row is not torn: last_synced_at is set", bool(row.get("last_synced_at")))

    # ── Cleanup ──────────────────────────────────────────────────────────────
    print("\nCleanup — cancelling any still-live ONVO subscriptions, deleting throwaway vrm.customers rows …")
    for sub_id in _created_onvo_subscription_ids:
        try:
            current = onvo.get_subscription(sub_id)
            if current.get("status") not in ("canceled",):
                onvo.cancel_subscription(sub_id)
                print(f"  cancelled ONVO subscription {sub_id}")
        except onvo.OnvoError as exc:
            print(f"  WARN could not cancel/verify ONVO subscription {sub_id} — {exc}")

    for customer_id in _created_customer_ids:
        try:
            vrm.table("customers").delete().eq("id", customer_id).execute()
        except Exception as exc:  # noqa: BLE001 — cleanup best-effort, report and move on
            print(f"  WARN could not delete throwaway customer {customer_id} — {exc}")
    print(f"  deleted {len(_created_customer_ids)} throwaway vrm.customers row(s) (cascade took their "
          "billing_customers/subscriptions/subscription_invoices/sites rows with them)")
    print(f"  ONVO objects (customers/subscriptions/products/prices) are left in test mode, "
          f"marked {MARKER!r} — no delete-customer operation exists in ONVO's confirmed API surface.")


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
    # vrm_api.billing/vrm_api.onvo), at INFO and up — NEVER the root logger,
    # and NEVER DEBUG. Raising the ROOT logger to DEBUG was tried in an
    # earlier version of this script and is exactly the mistake to avoid:
    # it also turns on httpx/httpcore/hpack's own DEBUG loggers, which dump
    # full request headers — including this process's Supabase
    # Authorization bearer token — in cleartext. Scoping the handler to the
    # "vrm_api" logger namespace (a sibling of "httpx"/"httpcore", not an
    # ancestor) makes that class of leak structurally unreachable here,
    # rather than something this script has to remember not to do.
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
        print("Step 2 validation FAILED.")
        raise SystemExit(1)
    print("Step 2 validation gate PASSED.")
