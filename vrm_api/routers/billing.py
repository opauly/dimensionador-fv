from __future__ import annotations
"""
`vrm_api`'s customer-facing HTTP surface for ONVO billing (PLAN_PHASE16.md
§0.3, §5.1-5.3, §8 Step 3). Structural template: `routers/vrm_link.py` — a
router that talks to a third party on a customer's behalf, with tenancy
checks and typed error responses.

All the JUDGEMENT lives in `vrm_api/billing.py` (`reconcile_customer()` /
`apply_entitlements()`) and all the ONVO TRANSPORT lives in
`vrm_api/onvo.py` — this file calls both, reimplements neither. Every
handler below is, in shape, "check tenancy, do the one ONVO call this
action needs (if any), call `billing.reconcile_customer()`, return the
fresh state" — `billing.reconcile_customer()` is what turns our own POST's
response into trustworthy state (§0.5: "never parse our own POST's response
into state"), never this router parsing an ONVO response body itself.

── Tenancy (§6.4, restated for billing) ────────────────────────────────────
Every handler calls `tenancy.get_customer(customer_id)` as its first real
statement — never trusts that Next.js already checked (control 2). And
control 3, the one this file is most at risk of getting wrong: **no ONVO
object id is ever accepted from a request body without a fresh re-read
confirming it belongs to this customer.** Concretely:
  - `plan_id` is always OUR OWN `vrm.plans.id` (validated against
    active/mode/account_types/self_serve in `_validate_target_plan()`),
    never an ONVO `priceId` from the browser.
  - `payment_method_id` (`BillingPaymentMethodRequest`, the standalone
    attach primitive — see that model's own docstring for why it is not
    currently in the SDK-widget call path) is the ONE place an ONVO id
    genuinely arrives in a request body, when it is used. It is NEVER used
    without first calling `_verify_payment_method()`, a fresh
    `GET /v1/payment-methods/{id}` with our secret key confirming the id
    resolves to THIS customer's `onvo_customer_id` (or is genuinely
    unattached) before it is ever passed to `onvo.update_subscription()`.
  - `POST /subscription` (§5.2, corrected Step 5 2026-08-20) deliberately
    creates its ONVO subscription with `payment_method_id=None` — the SDK
    widget that collects the card needs the resulting `onvo_subscription_id`
    to render AT ALL, so no `payment_method_id` can possibly exist yet at
    the point this endpoint runs. The card that widget later collects is
    never reported back to this server as a trusted id from the browser —
    only ever re-read by the NEXT `billing.reconcile_customer()` call
    (`POST /v1/billing/refresh`), same as every other ONVO id below.
  - Every other ONVO id this file ever sends to ONVO (`onvo_customer_id`,
    `onvo_subscription_id`, `default_payment_method_id`) is read off OUR
    OWN mirror rows (`vrm.billing_customers`/`vrm.subscriptions`), which are
    only ever populated by `billing.reconcile_customer()` for the
    tenancy-checked `customer_id` — never off anything a caller sent.
  - A grep-able assertion for the tester agent: no model in
    `vrm_api/schemas.py`'s `Billing*Request` family has a field named (or
    shaped like) an ONVO subscription/customer/price id. The only ONVO-id
    -shaped field on any request model is `payment_method_id`
    (`BillingPaymentMethodRequest` only), and its handling is exactly the
    paragraph above.

── Duplicate-subscription safety (§5.4) ────────────────────────────────────
Three guards, all built here (not just the UI-level one, which is Next.js's
job and out of scope for this file):
  1. Reconcile-before-create — every mutation that can produce a NEW ONVO
     subscription (`subscribe`, `change`) calls `billing.reconcile_customer()`
     first, so a subscription created by a lost previous response is FOUND
     rather than duplicated.
  2. The database's own partial unique index (migration 025:
     `idx_vrm_subscriptions_one_live_per_customer`,
     `customer_id WHERE canceled_at IS NULL`) — this file additionally
     CLAIMS that index as an application-level mutex, before ever calling
     ONVO, via `_acquire_subscribe_lock()`: it inserts a placeholder
     `vrm.subscriptions` row for this customer BEFORE the ONVO create call.
     Two truly concurrent requests for the same customer race on that
     INSERT; the loser gets a unique-violation immediately (no ONVO call
     made at all) and is turned into `409 subscription_already_exists`. The
     winner "promotes" the placeholder in place once ONVO responds
     (`_promote_subscribe_lock()`), so the very next reconcile's
     conditional-UPDATE finds and updates that row rather than inserting a
     second one. This is what makes the concurrent-duplicate-create test in
     §8 Step 3's validation list actually hold under real concurrency, not
     just under a disabled submit button.
  3. UI-level submit-disable is Next.js's job (§5.4 point 3) — not built
     here, noted so its absence from this file isn't mistaken for an
     oversight.

── No CORS, no docs, one auth mechanism ────────────────────────────────────
`dependencies=[Depends(require_pipeline_key)]` on the router (matches every
other router in this API) — this file never accepts a session token, only
the pipeline key. Every 401 "who is this" question is a Next.js problem
before it ever reaches here.

── The webhook intake specifically (§4.1, §4.2, §6.5, §8 Step 4) ──────────
`POST /webhook-event` is the ONLY thing in this file with no `customer_id`
in its request body at all — a webhook names an ONVO object, not one of our
own ids, so tenancy has nothing to check here until AFTER resolution. It
writes a `vrm.billing_events` row FIRST, durably, before any resolution or
reconcile is attempted (§4.1: "durability before work") — every webhook
delivery this endpoint ever sees gets a row, including one whose
`secret_ok` somehow arrives `False` (should never happen; the Next.js
receiver rejects those before ever forwarding — see that route's own
header comment). §4.2's resolution ladder — `vrm.subscriptions.
onvo_subscription_id` → `vrm.subscription_invoices.onvo_invoice_id`/
`.payment_intent_id` → `vrm.billing_customers.onvo_customer_id` — is
implemented against every id-shaped field actually present in `data`
(`_webhook_candidate_ids()`), not a single generic `data.id`, because
§0.2b finding 9's confirmed real payload shapes for
`subscription.renewal.succeeded`/`.failed` carry `subscriptionId`/
`paymentIntentId`/`customerId` (or a nested `customer.id`) instead of one
generic `id` field. An unresolved event is `status='ignored'` — normal,
never an error (§4.2: the same ONVO account may also carry the Solar
Design Tool's unrelated one-off payment traffic). A resolved event calls
`billing.reconcile_customer()` — never applies the payload's own fields to
any mirror row (§0.5) — and is marked `'applied'` or `'error'`;
`post_reconcile_due()` below additionally retries `'error'`-status rows,
so a reconcile that failed because ONVO was briefly unreachable gets a
second chance on the next daily sweep (§4.4).
"""
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from database.supabase_client import get_client

from vrm_api import billing, onvo, tenancy
from vrm_api.deps import require_pipeline_key
from vrm_api.schemas import (
    BillingAddressRequest,
    BillingCancelRequest,
    BillingChangeRequest,
    BillingInvoiceOut,
    BillingInvoicesOut,
    BillingPaymentMethodRequest,
    BillingPaymentMethodSessionOut,
    BillingPaymentMethodSessionRequest,
    BillingPlanOut,
    BillingPlansOut,
    BillingPruneSignupsOut,
    BillingReconcileDueOut,
    BillingReconcileDueResult,
    BillingRefreshRequest,
    BillingResumeRequest,
    BillingStatusOut,
    BillingSubscribeOut,
    BillingSubscribeRequest,
    BillingTrialRemindersOut,
    BillingWebhookEventOut,
    BillingWebhookEventRequest,
)

logger = logging.getLogger("vrm_api.billing_router")

router = APIRouter(prefix="/v1/billing", tags=["billing"],
                   dependencies=[Depends(require_pipeline_key)])

SCHEMA = "vrm"

# §4.4's on-read staleness trigger: refresh if the mirror is older than
# this, or unconditionally if the current status is transitional (not yet
# settled). §0.2b finding 4's closed vocabulary: `incomplete` (created,
# first charge not yet resolved — a retry is scheduled) and `past_due`
# (mid-retry-cycle) are the two genuinely "still moving" states; `trialing`,
# `active`, `canceled`, `unpaid`, `incomplete_expired` are all settled-until-
# something-external-happens, which the 5-minute/webhook/sweep triggers
# already cover.
_TRANSITIONAL_STATUSES = {"incomplete", "past_due"}
_STALE_AFTER = timedelta(minutes=5)
_SWEEP_STALE_AFTER = timedelta(hours=48)

# §3.7/§3.8's retention windows for the Step 7 prune sweep. signup_requests'
# two numbers are stated verbatim in the plan: "unconsumed rows past
# expires_at + 7 days, consumed rows past consumed_at + 30 days." rate_limits
# has no stated number — its windows top out at 24h (`signup_email`, §6.6's
# own table), so anything with a `window_start` more than 2 days old can
# never be read by a live rate-limit check again; kept as a named constant
# rather than a magic number so it's obvious this is a safety margin, not a
# transcribed plan value.
_SIGNUP_UNCONSUMED_GRACE = timedelta(days=7)
_SIGNUP_CONSUMED_RETENTION = timedelta(days=30)
_RATE_LIMIT_RETENTION = timedelta(days=2)


def _t(name: str):
    return get_client().schema(SCHEMA).table(name)


def _onvo_mode() -> str:
    return os.environ.get("ONVO_MODE", "test")


def _publishable_key() -> str:
    key = os.environ.get("ONVO_PUBLISHABLE_KEY", "")
    if not key:
        # Configuration problem, not a customer problem — never a 4xx.
        raise HTTPException(status_code=502, detail={"code": "billing_unavailable"})
    return key


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _plan_label_key(plan_key: str | None) -> str | None:
    return f"billing.plan.{plan_key}" if plan_key else None


def _billing_customer_row(customer_id: str) -> dict | None:
    rows = _t("billing_customers").select("*").eq("customer_id", customer_id).limit(1).execute().data
    return rows[0] if rows else None


def _current_live_subscription_row(customer_id: str) -> dict | None:
    """The customer's current, non-canceled `vrm.subscriptions` row, if
    any. Backed by migration 025's own partial unique index, so there is at
    most one — except for the narrow, self-correcting window while
    `_acquire_subscribe_lock()` holds a placeholder row mid-creation (see
    that function's own docstring)."""
    rows = (
        _t("subscriptions").select("*").eq("customer_id", customer_id)
        .is_("canceled_at", "null").order("created_at", desc=True).limit(1).execute().data
    )
    return rows[0] if rows else None


def _most_recent_subscription_row(customer_id: str) -> dict | None:
    """Falls back to the most recently created subscription of ANY kind
    (including a canceled/lapsed one) — mirrors
    `vrm_api/billing.py:_current_mirror_subscription()`'s own fallback, so
    a lapsed customer's LAST plan/interval still displays sensibly instead
    of a blank status card."""
    rows = (
        _t("subscriptions").select("*").eq("customer_id", customer_id)
        .order("created_at", desc=True).limit(1).execute().data
    )
    return rows[0] if rows else None


def _active_site_count(customer_id: str) -> int:
    result = (
        _t("sites").select("id", count="exact")
        .eq("customer_id", customer_id).eq("active", True)
        .limit(1).execute()
    )
    return result.count or 0


def _read_only_state(customer_id: str) -> dict:
    """The same small summary shape `billing.reconcile_customer()` returns
    (`vrm_api/billing.py:_billing_state()`), built WITHOUT calling ONVO —
    used when `get_status()` decides a refresh isn't needed (§4.4's
    staleness bound). Reads only what a PRIOR reconcile already wrote."""
    customer = tenancy.get_customer(customer_id)
    sub = _current_live_subscription_row(customer_id) or _most_recent_subscription_row(customer_id)
    return {
        "customer_id": customer_id,
        "plan": customer.get("plan"),
        "site_limit": customer.get("site_limit"),
        "billing_status": customer.get("billing_status"),
        "provisioning_state": customer.get("provisioning_state"),
        "subscription": sub,
        "billing_customer": _billing_customer_row(customer_id),
    }


def _needs_staleness_refresh(customer_id: str) -> bool:
    billing_row = _billing_customer_row(customer_id)
    if billing_row is None:
        # Never touched billing at all — reconcile_customer() would make no
        # ONVO calls anyway (billing.py's own documented no-op case).
        return False
    sub = _current_live_subscription_row(customer_id) or _most_recent_subscription_row(customer_id)
    if sub is None:
        # A billing_customers row exists (an ONVO customer was created) but
        # no subscription has ever been mirrored — worth one refresh to
        # find out why.
        return True
    if sub.get("status") in _TRANSITIONAL_STATUSES:
        return True
    last_synced = _parse_ts(sub.get("last_synced_at"))
    return last_synced is None or (datetime.now(timezone.utc) - last_synced) > _STALE_AFTER


def _status_response(state: dict) -> BillingStatusOut:
    """Builds `BillingStatusOut` from a state dict shaped like
    `billing.reconcile_customer()`'s return value (or `_read_only_state()`
    above) — a pure read of what a reconcile already wrote/confirmed. Every
    mutation endpoint in this router returns this, so the browser always
    sees fresh state after its own action (§4.4's post-mutation trigger)
    without a second round trip."""
    customer_id = state["customer_id"]
    sub = state.get("subscription") or {}
    billing_row = state.get("billing_customer") or {}
    site_limit = state.get("site_limit")
    active_sites = _active_site_count(customer_id)
    over_limit = site_limit is not None and active_sites > site_limit
    plan_key = state.get("plan")
    billing_status = state.get("billing_status")
    # `billing.apply_entitlements()`'s `trial_expired` billing_status
    # (2026-08-29 fix) is a LOCAL classification — ONVO's own mirrored
    # `sub["status"]` never changes to reflect it (ONVO still reports
    # "trialing" forever for a subscription it never got a card to
    # charge). Reporting the raw ONVO status here regardless would put the
    # customer-facing "Trial" badge right back to lying about what's
    # actually true — the exact bug this fix exists to close.
    reported_status = "trial_expired" if billing_status == "trial_expired" else sub.get("status")
    return BillingStatusOut(
        customer_id=customer_id,
        plan_key=plan_key,
        plan_label_key=_plan_label_key(plan_key),
        billing_status=billing_status,
        provisioning_state=state.get("provisioning_state") or "active",
        status=reported_status,
        billing_interval=sub.get("billing_interval"),
        currency=sub.get("currency"),
        amount_minor=sub.get("amount_minor"),
        current_period_end=sub.get("current_period_end"),
        cancel_at_period_end=bool(sub.get("cancel_at_period_end")),
        trial_end=sub.get("trial_end"),
        pm_brand=billing_row.get("pm_brand"),
        pm_last4=billing_row.get("pm_last4"),
        pm_exp_month=billing_row.get("pm_exp_month"),
        pm_exp_year=billing_row.get("pm_exp_year"),
        billing_address=billing_row.get("billing_address") or {},
        site_limit=site_limit,
        active_sites=active_sites,
        over_limit=over_limit,
    )


def _validate_target_plan(customer: dict, plan_id: str) -> dict:
    """§3.1: a plan is buyable by this customer only if it's `active`, in
    our own current `ONVO_MODE`, and this customer's `account_type` is in
    its `account_types`. A customer who is still `pending_subscription`
    (never subscribed) is additionally restricted to `self_serve` plans —
    an ALREADY-`active` customer changing/adding a plan is NOT restricted
    by `self_serve` (§3.1's own note: Oscar can hand-place an existing
    customer on Fleet and this must not block that)."""
    mode = _onvo_mode()
    rows = (
        _t("plans").select("*")
        .eq("id", plan_id).eq("active", True).eq("mode", mode)
        .limit(1).execute().data
    )
    if not rows:
        raise HTTPException(status_code=403, detail={"code": "plan_not_available"})
    plan_row = rows[0]
    account_types = plan_row.get("account_types") or []
    if customer.get("account_type") not in account_types:
        raise HTTPException(status_code=403, detail={"code": "plan_not_available"})
    if customer.get("provisioning_state") == "pending_subscription" and not plan_row.get("self_serve"):
        raise HTTPException(status_code=403, detail={"code": "plan_not_available"})
    return plan_row


def _verify_payment_method(payment_method_id: str, onvo_customer_id: str) -> dict:
    """§6.4 control 3's sharpest instance in this file: a `payment_method_id`
    always arrives having been created by the BROWSER directly against
    ONVO (§0.2b finding 7) — this server must re-read it with the secret
    key and confirm it resolves to THIS customer's `onvo_customer_id`
    before it is ever attached to a subscription. A payment method with no
    `customerId` at all (genuinely unattached) is accepted; one attached to
    a DIFFERENT customer is refused outright — this is exactly the tamper
    case §8 Step 3's validation list calls out by name."""
    try:
        pm = onvo.get_payment_method(payment_method_id)
    except onvo.OnvoNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "payment_method_not_found"}) from None
    except onvo.OnvoError as exc:
        logger.warning("billing: could not verify payment method %s — %s", payment_method_id, exc)
        raise HTTPException(status_code=502, detail={"code": "billing_unavailable"}) from None
    pm_customer_id = pm.get("customerId")
    if pm_customer_id and pm_customer_id != onvo_customer_id:
        # Deliberately does NOT say which customer it belongs to — same
        # non-naming discipline as tenancy.VrmAccountAlreadyLinked.
        raise HTTPException(status_code=403, detail={"code": "payment_method_not_owned"})
    return pm


def _ensure_billing_customer(customer: dict) -> dict:
    """Returns this customer's `vrm.billing_customers` row, creating the
    ONVO customer + mirror row the first time this customer ever touches
    billing (§5.2 step 2). Idempotent under concurrency: `customer_id` is
    the table's own PRIMARY KEY, so a lost insert race from a second
    concurrent call is a real Postgres error here, caught and treated as
    "someone else's row is now the row" — the same pattern
    `vrm_api/billing.py:_conditional_upsert()` already uses for exactly
    this situation."""
    existing = _billing_customer_row(customer["id"])
    if existing is not None:
        return existing

    mode = _onvo_mode()
    email = customer.get("billing_email") or customer.get("contact_email") or customer.get("auth_email") or ""
    try:
        onvo_customer = onvo.create_customer(
            name=customer.get("name") or customer["id"],
            email=email,
            metadata={"vrm_customer_id": customer["id"], "env": mode},
        )
    except onvo.OnvoError as exc:
        logger.warning("billing: failed to create ONVO customer for customer_id=%s — %s", customer["id"], exc)
        raise HTTPException(status_code=502, detail={"code": "billing_unavailable"}) from None

    try:
        _t("billing_customers").insert({
            "customer_id": customer["id"], "onvo_customer_id": onvo_customer["id"], "mode": mode,
        }).execute()
    except Exception:  # noqa: BLE001 — a lost insert race on the PK, not a real failure
        logger.info("billing: lost an insert race creating billing_customers for customer_id=%s", customer["id"])

    row = _billing_customer_row(customer["id"])
    return row or {"customer_id": customer["id"], "onvo_customer_id": onvo_customer["id"], "mode": mode}


def _acquire_subscribe_lock(customer_id: str) -> str:
    """Claims migration 025's own partial unique index
    (`idx_vrm_subscriptions_one_live_per_customer`,
    `customer_id WHERE canceled_at IS NULL`) as an application-level mutex
    BEFORE this process ever calls ONVO's create-subscription endpoint —
    see this file's module docstring, "Duplicate-subscription safety",
    guard 2. Returns a synthetic placeholder `onvo_subscription_id`
    (`"pending:<uuid>"` — cannot collide with a real ONVO id) that
    `_promote_subscribe_lock()` rewrites in place once ONVO responds, or
    `_release_subscribe_lock()` deletes if the ONVO call itself fails."""
    placeholder_id = f"pending:{uuid.uuid4().hex}"
    try:
        _t("subscriptions").insert({
            "customer_id": customer_id,
            "onvo_subscription_id": placeholder_id,
            "mode": _onvo_mode(),
            "status": "pending_local",
            "last_synced_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception:  # noqa: BLE001 — a genuine unique-violation IS the guard firing
        logger.info("billing: subscribe lock refused for customer_id=%s — a live subscription already exists", customer_id)
        raise HTTPException(status_code=409, detail={"code": "subscription_already_exists"}) from None
    return placeholder_id


def _release_subscribe_lock(placeholder_id: str) -> None:
    """Cleanup for when the ONVO create call fails AFTER the lock was
    acquired — a customer must never be left permanently locked out by a
    failed attempt."""
    _t("subscriptions").delete().eq("onvo_subscription_id", placeholder_id).execute()


def _promote_subscribe_lock(placeholder_id: str, real_onvo_subscription_id: str) -> None:
    """Rewrites the placeholder row's id in place so the immediately-
    following `billing.reconcile_customer()` call's conditional-UPDATE
    (`_conditional_upsert()`, keyed on `onvo_subscription_id`) finds and
    updates THIS row instead of inserting a second one."""
    _t("subscriptions").update({
        "onvo_subscription_id": real_onvo_subscription_id,
        "status": "pending_local",
    }).eq("onvo_subscription_id", placeholder_id).execute()


def _mark_site_limit_tracks_plan(customer: dict) -> None:
    """§3.6 (migration 025's own comment on `site_limit_source`): 'plan' is
    set "when a customer subscribes through the portal" — not only at
    self-serve signup time (§5.5 step 2 does that for a brand-new row; this
    is the other writer, for an existing admin-created customer whose
    `site_limit_source` is still the protective 'manual' default because
    they have never subscribed before). Without this, a legacy customer's
    very first real subscription would reconcile correctly but
    `apply_entitlements()` would refuse to raise their `site_limit` — the
    exact bug §3.6's own comment names ("frozen forever, because the
    entitlement writer would politely refuse to raise it"), generalized
    from signup to any first portal subscribe. A customer whose
    `site_limit_source` is ALREADY 'plan' (a repeat subscriber, or a signup
    that already set it) is left untouched — this is a no-op write, not a
    re-derivation."""
    if customer.get("site_limit_source") != "plan":
        _t("customers").update({"site_limit_source": "plan"}).eq("id", customer["id"]).execute()


# ═══════════════════════════════════════════════════════════════════════
# §5.1 — read endpoints
# ═══════════════════════════════════════════════════════════════════════

@router.get("/status", response_model=BillingStatusOut)
def get_status(customer_id: str = Query(...)) -> BillingStatusOut:
    tenancy.get_customer(customer_id)
    if _needs_staleness_refresh(customer_id):
        try:
            state = billing.reconcile_customer(customer_id)
        except onvo.OnvoError as exc:
            # A read must not 5xx just because ONVO is unreachable right
            # now (§4.4's freshness promise is "within 24h even if every
            # webhook is lost," not "every read is synchronous with ONVO")
            # — fall back to the mirror's last-known state and log loudly.
            logger.warning("billing.status: on-read refresh failed for customer_id=%s — %s", customer_id, exc)
            state = _read_only_state(customer_id)
    else:
        state = _read_only_state(customer_id)
    return _status_response(state)


@router.get("/plans", response_model=BillingPlansOut)
def get_plans(customer_id: str = Query(...)) -> BillingPlansOut:
    customer = tenancy.get_customer(customer_id)
    mode = _onvo_mode()
    rows = (
        _t("plans").select("*")
        .eq("active", True).eq("mode", mode)
        .contains("account_types", [customer.get("account_type")])
        .order("sort_order")
        .execute().data
    ) or []
    if customer.get("provisioning_state") == "pending_subscription":
        # §3.1: a not-yet-paying customer may only see/subscribe to a
        # self-serve plan. An already-active customer is not filtered here.
        rows = [r for r in rows if r.get("self_serve")]
    current_plan_key = customer.get("plan")
    return BillingPlansOut(plans=[
        BillingPlanOut(
            id=r["id"], plan_key=r["plan_key"], plan_label_key=_plan_label_key(r["plan_key"]),
            billing_interval=r["billing_interval"], currency=r["currency"], amount_minor=r["amount_minor"],
            site_limit=r.get("site_limit"), self_serve=bool(r.get("self_serve")),
            is_current=(r["plan_key"] == current_plan_key),
        )
        for r in rows
    ])


@router.get("/invoices", response_model=BillingInvoicesOut)
def get_invoices(
    customer_id: str = Query(...), limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
) -> BillingInvoicesOut:
    tenancy.get_customer(customer_id)
    rows = (
        _t("subscription_invoices").select("*").eq("customer_id", customer_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit)  # one extra row, to detect has_more without a second count query
        .execute().data
    ) or []
    has_more = len(rows) > limit
    rows = rows[:limit]
    return BillingInvoicesOut(
        invoices=[
            BillingInvoiceOut(
                id=r["id"], status=r.get("status"), currency=r.get("currency"),
                total_minor=r.get("total_minor"), subtotal_minor=r.get("subtotal_minor"),
                original_total_minor=r.get("original_total_minor"),
                period_start=r.get("period_start"), period_end=r.get("period_end"),
                attempt_count=r.get("attempt_count"), last_payment_attempt=r.get("last_payment_attempt"),
                next_payment_attempt=r.get("next_payment_attempt"),
            )
            for r in rows
        ],
        has_more=has_more,
    )


# ═══════════════════════════════════════════════════════════════════════
# §5.2 — subscribe
# ═══════════════════════════════════════════════════════════════════════

@router.post("/subscription", response_model=BillingSubscribeOut)
def post_subscription(body: BillingSubscribeRequest) -> BillingSubscribeOut:
    """§5.2, corrected at Step 5 (2026-08-20) — see this router's module
    docstring's "Duplicate-subscription safety" section and
    `BillingSubscribeRequest`'s own docstring for the full "why": the ONVO
    SDK widget that collects the card needs a real `subscriptionId` to
    render AT ALL, so this endpoint creates the ONVO subscription FIRST,
    with `paymentBehavior: allow_incomplete` and no payment method, and
    returns immediately.

    **Correction found live while building this fix (`tools/
    validate_billing_step5_fix.py`, 2026-08-20), not by the plan**: with
    `trial_period_days=7` also set at creation (as this call always does,
    per Q2), the subscription does NOT come back `status: incomplete` as
    §5.2 point 3's prose says — it comes back `status: trialing`,
    immediately, with no payment method attached. (`incomplete` is what
    ONVO reports when it actually ATTEMPTS a charge and that charge fails
    or has no card to try — a subscription with a trial period has nothing
    to attempt yet, so it starts `trialing` instead.) This does not change
    this function's own logic at all (it never branches on the ONVO status
    it gets back — it only needs the id), but it DOES mean
    `apply_entitlements()`'s "trialing is entitled" mapping (unchanged,
    Step 2's own work) would grant full entitlements to a customer who has
    NEVER supplied any payment method at all, the instant a reconcile runs
    against this subscription — which is exactly why the deliberate
    omission below (no `reconcile_customer()` call here) matters MORE than
    the plan's own "nothing entitled to reconcile toward" reasoning
    implies: it is the ONLY thing currently standing between "subscribed"
    and "entitled with no card on file," because `POST /v1/billing/refresh`
    itself does not check for a payment method before entitling either.
    Flagged in the coder's report as a real gap for the architect/manager —
    not fixed here, since fixing it is a product/entitlement-writer design
    decision outside this fix's scope (subscribe + payment-method/session
    only)."""
    customer = tenancy.get_customer(body.customer_id)

    # Guard 1 (§5.4): reconcile-before-create.
    state = billing.reconcile_customer(body.customer_id)
    existing_sub = state.get("subscription")
    if existing_sub is not None and existing_sub.get("canceled_at") is None:
        raise HTTPException(status_code=409, detail={"code": "subscription_already_exists"})

    plan_row = _validate_target_plan(customer, body.plan_id)

    # Guard 2 (§5.4): claim the DB mutex BEFORE any ONVO call.
    placeholder_id = _acquire_subscribe_lock(body.customer_id)
    try:
        billing_row = _ensure_billing_customer(customer)
        onvo_customer_id = billing_row["onvo_customer_id"]
        try:
            sub = onvo.create_subscription(
                customer_id=onvo_customer_id, price_id=plan_row["onvo_price_id"],
                payment_method_id=None,
                payment_behavior="allow_incomplete",
                trial_period_days=7,  # Q2, final: 7-day trial — comes back `trialing`
                                       # immediately (not `incomplete`, see this
                                       # function's own docstring), no card yet
                metadata={"vrm_customer_id": customer["id"], "plan_key": plan_row["plan_key"], "env": _onvo_mode()},
            )
        except onvo.OnvoError as exc:
            logger.warning("billing.subscribe: ONVO create_subscription failed for customer_id=%s — %s", customer["id"], exc)
            raise HTTPException(status_code=502, detail={"code": "billing_unavailable"}) from None
    except HTTPException:
        _release_subscribe_lock(placeholder_id)
        raise

    _promote_subscribe_lock(placeholder_id, sub["id"])
    _mark_site_limit_tracks_plan(customer)
    # Deliberately NO `billing.reconcile_customer()` call here (§5.2 point 5)
    # — see this function's own docstring for why this matters more than
    # the plan's original "nothing entitled yet" reasoning: the placeholder
    # row is already promoted to the real id so the browser's post-
    # `onSuccess` refresh call finds and updates it rather than creating a
    # duplicate, and — for now — is also the only thing standing between
    # "subscribed" and "entitled with no card on file."

    return BillingSubscribeOut(
        onvo_subscription_id=sub["id"], onvo_customer_id=onvo_customer_id,
        publishable_key=_publishable_key(),
    )


# ═══════════════════════════════════════════════════════════════════════
# §5.3 — change plan, cancel, resume, payment method, address
# ═══════════════════════════════════════════════════════════════════════

@router.post("/subscription/change", response_model=BillingStatusOut)
def post_subscription_change(body: BillingChangeRequest) -> BillingStatusOut:
    """Q3, final answer: cancel-and-restart, no proration, both directions
    immediate — there is no ONVO mechanism to change a subscription's price
    in place (§0.2b finding 6). Reuses the existing default payment method;
    the customer is not asked to re-enter a card just to change plans."""
    customer = tenancy.get_customer(body.customer_id)
    state = billing.reconcile_customer(body.customer_id)
    current_sub = state.get("subscription")
    if current_sub is None or current_sub.get("canceled_at") is not None:
        raise HTTPException(status_code=409, detail={"code": "no_active_subscription"})

    plan_row = _validate_target_plan(customer, body.plan_id)

    # Q5(b)'s guard: block only NEW site creation over the limit, never the
    # plan change itself — but the customer must be told BEFORE it applies,
    # not after, hence the confirm round-trip.
    active_sites = _active_site_count(body.customer_id)
    new_limit = plan_row.get("site_limit")
    if new_limit is not None and active_sites > new_limit and not body.confirm:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "over_site_limit",
                "requires_confirmation": True,
                "current_site_count": active_sites,
                "new_site_limit": new_limit,
            },
        )

    billing_row = _billing_customer_row(body.customer_id)
    default_pm_id = (billing_row or {}).get("default_payment_method_id")
    if not billing_row or not default_pm_id:
        raise HTTPException(status_code=400, detail={"code": "no_payment_method"})

    try:
        onvo.cancel_subscription(current_sub["onvo_subscription_id"])
    except onvo.OnvoError as exc:
        logger.warning("billing.change: failed to cancel current subscription for customer_id=%s — %s", body.customer_id, exc)
        raise HTTPException(status_code=502, detail={"code": "billing_unavailable"}) from None

    # Re-reconcile BEFORE claiming the subscribe lock: the cancel above is
    # synchronous at ONVO (§0.2b finding 12) but our OWN mirror row still
    # shows canceled_at=NULL until a reconcile re-reads it — and
    # `_acquire_subscribe_lock()` relies on migration 025's partial unique
    # index (`customer_id WHERE canceled_at IS NULL`) to detect "no live
    # row." Without this reconcile, the still-stale old row would make that
    # very index reject the new placeholder insert, misreporting a genuine
    # cancel-and-restart as `subscription_already_exists`.
    billing.reconcile_customer(body.customer_id)

    placeholder_id = _acquire_subscribe_lock(body.customer_id)
    try:
        onvo_customer_id = billing_row["onvo_customer_id"]
        # The pm id came from OUR OWN mirror, not the request body — but
        # control 3's discipline is "never trust an ONVO id without a
        # fresh re-read," full stop, so it is re-verified here too.
        _verify_payment_method(default_pm_id, onvo_customer_id)
        try:
            new_sub = onvo.create_subscription(
                customer_id=onvo_customer_id, price_id=plan_row["onvo_price_id"],
                payment_method_id=default_pm_id,
                # No trial on a plan change — Q2's 7-day trial is a
                # first-subscription benefit, not something a plan switch
                # re-grants.
                metadata={"vrm_customer_id": body.customer_id, "plan_key": plan_row["plan_key"], "env": _onvo_mode()},
            )
        except onvo.OnvoError as exc:
            logger.warning("billing.change: failed to create new subscription for customer_id=%s — %s", body.customer_id, exc)
            raise HTTPException(status_code=502, detail={"code": "billing_unavailable"}) from None
    except HTTPException:
        _release_subscribe_lock(placeholder_id)
        raise

    _promote_subscribe_lock(placeholder_id, new_sub["id"])
    new_state = billing.reconcile_customer(body.customer_id)
    return _status_response(new_state)


@router.post("/subscription/cancel", response_model=BillingStatusOut)
def post_subscription_cancel(body: BillingCancelRequest) -> BillingStatusOut:
    tenancy.get_customer(body.customer_id)
    state = billing.reconcile_customer(body.customer_id)
    current_sub = state.get("subscription")
    if current_sub is None or current_sub.get("canceled_at") is not None:
        raise HTTPException(status_code=409, detail={"code": "no_active_subscription"})

    onvo_subscription_id = current_sub["onvo_subscription_id"]
    try:
        if body.mode == "immediate":
            # Q4: graceful-only in v1's customer-facing UI. Immediate is
            # built and tenancy-checked exactly like every other action in
            # this file, but has no admin caller today — Step 6 (admin) is
            # what is expected to actually expose this to Oscar as a
            # support action. Nothing in THIS endpoint restricts it to
            # admin; the tenancy check above is the only gate that applies.
            onvo.cancel_subscription(onvo_subscription_id)
        else:
            onvo.update_subscription(onvo_subscription_id, cancel_at_period_end=True)
    except onvo.OnvoError as exc:
        logger.warning("billing.cancel: ONVO call failed for customer_id=%s mode=%s — %s", body.customer_id, body.mode, exc)
        raise HTTPException(status_code=502, detail={"code": "billing_unavailable"}) from None

    return _status_response(billing.reconcile_customer(body.customer_id))


@router.post("/subscription/resume", response_model=BillingStatusOut)
def post_subscription_resume(body: BillingResumeRequest) -> BillingStatusOut:
    tenancy.get_customer(body.customer_id)
    state = billing.reconcile_customer(body.customer_id)
    current_sub = state.get("subscription")
    if current_sub is None or current_sub.get("canceled_at") is not None:
        raise HTTPException(status_code=409, detail={"code": "no_active_subscription"})

    try:
        onvo.update_subscription(current_sub["onvo_subscription_id"], cancel_at_period_end=False)
    except onvo.OnvoError as exc:
        logger.warning("billing.resume: ONVO call failed for customer_id=%s — %s", body.customer_id, exc)
        raise HTTPException(status_code=502, detail={"code": "billing_unavailable"}) from None

    return _status_response(billing.reconcile_customer(body.customer_id))


@router.post("/payment-method/session", response_model=BillingPaymentMethodSessionOut)
def post_payment_method_session(body: BillingPaymentMethodSessionRequest) -> BillingPaymentMethodSessionOut:
    """The replace-card path (§5.3, corrected at Step 5 2026-08-20 — see
    `BillingPaymentMethodSessionOut`'s own docstring): first-time subscribe
    gets its `onvo_subscription_id` straight from `POST /subscription`
    (§5.2) and never calls this endpoint. This one is for a customer who
    ALREADY has a live subscription and wants to replace its card — the SDK
    widget needs that real `subscriptionId` to render a working card form,
    exactly like first-time subscribe does, not just a `customerId`.
    Refused with `no_active_subscription` if there is nothing to attach a
    new card to (a `pending_subscription`/lapsed customer with no live
    subscription must go through `POST /subscription` instead)."""
    tenancy.get_customer(body.customer_id)
    current_sub = _current_live_subscription_row(body.customer_id)
    billing_row = _billing_customer_row(body.customer_id)
    if current_sub is None or billing_row is None:
        raise HTTPException(status_code=409, detail={"code": "no_active_subscription"})
    return BillingPaymentMethodSessionOut(
        onvo_subscription_id=current_sub["onvo_subscription_id"],
        onvo_customer_id=billing_row["onvo_customer_id"],
        publishable_key=_publishable_key(),
    )


@router.post("/payment-method", response_model=BillingStatusOut)
def post_payment_method(body: BillingPaymentMethodRequest) -> BillingStatusOut:
    """Replaces the card on the customer's CURRENT subscription (§5.3) —
    the browser already created `payment_method_id` directly against ONVO
    (see `post_payment_method_session()` above); this call re-verifies it
    and attaches it. §0.2b finding 7, confirmed live end to end."""
    tenancy.get_customer(body.customer_id)
    billing_row = _billing_customer_row(body.customer_id)
    if billing_row is None:
        raise HTTPException(status_code=400, detail={"code": "no_payment_method"})

    _verify_payment_method(body.payment_method_id, billing_row["onvo_customer_id"])

    current_sub = _current_live_subscription_row(body.customer_id)
    if current_sub is None:
        raise HTTPException(status_code=409, detail={"code": "no_active_subscription"})

    try:
        onvo.update_subscription(current_sub["onvo_subscription_id"], payment_method_id=body.payment_method_id)
    except onvo.OnvoError as exc:
        logger.warning("billing.payment_method: ONVO call failed for customer_id=%s — %s", body.customer_id, exc)
        raise HTTPException(status_code=502, detail={"code": "billing_unavailable"}) from None

    return _status_response(billing.reconcile_customer(body.customer_id))


@router.put("/address", response_model=BillingStatusOut)
def put_address(body: BillingAddressRequest) -> BillingStatusOut:
    """Written to ONVO first, then mirrored from the reconcile — never from
    the request body directly (§0.5's read-through principle, restated for
    this endpoint by §5.3). ONVO's only real home for a billing address is
    a payment method's `billing.address` (`onvo.py:get_payment_method()`'s
    own docstring), so this requires the customer to already have a
    default payment method on file."""
    tenancy.get_customer(body.customer_id)
    billing_row = _billing_customer_row(body.customer_id)
    default_pm_id = (billing_row or {}).get("default_payment_method_id")
    if not billing_row or not default_pm_id:
        raise HTTPException(status_code=400, detail={"code": "no_payment_method"})

    try:
        onvo.update_payment_method(
            default_pm_id, billing={"address": body.address.model_dump(exclude_none=True)},
        )
    except onvo.OnvoError as exc:
        logger.warning("billing.address: ONVO call failed for customer_id=%s — %s", body.customer_id, exc)
        raise HTTPException(status_code=502, detail={"code": "billing_unavailable"}) from None

    return _status_response(billing.reconcile_customer(body.customer_id))


@router.post("/refresh", response_model=BillingStatusOut)
def post_refresh(body: BillingRefreshRequest) -> BillingStatusOut:
    """A plain reconcile (§5.3) — what the browser calls after the SDK's
    own `onSuccess` fires (§5.2: 'a hint to refresh, never a state
    change'). Rate-limiting this per customer is Next.js's job (§6.5) —
    this endpoint itself has no rate limit of its own, same division of
    responsibility as every other pipeline-key-only endpoint in this API."""
    tenancy.get_customer(body.customer_id)
    return _status_response(billing.reconcile_customer(body.customer_id))


@router.post("/reconcile-due", response_model=BillingReconcileDueOut)
def post_reconcile_due() -> BillingReconcileDueOut:
    """The scheduled-sweep entry point (§4.4's fourth trigger). No
    `customer_id` — pipeline-key only, meant to be called by GitHub Actions
    `cron:` and by `/admin` (§8 Step 4 wires up the actual caller; this
    step's job, per the coder brief, is only to make the endpoint exist and
    work). Selects every non-canceled subscription whose `current_period_end`
    is in the past, whose status is transitional, or whose mirror hasn't
    synced in 48h (§4.4's own list) and reconciles each one. One
    customer's ONVO error never aborts the sweep for everyone else.

    Also retries `vrm.billing_events` rows stuck in `status='error'` (§4.4's
    own table: "plus retrying vrm.billing_events rows stuck in error") — a
    webhook that resolved to a real customer but whose own
    `reconcile_customer()` call failed at the time (e.g. ONVO briefly
    unreachable). This is folded into the SAME due-customer set and the SAME
    reconcile loop below (one reconcile per customer, not two), because a
    customer named by a stuck `error` event may not otherwise be "due" by
    the subscription-staleness scan above — e.g. the very first webhook for
    a brand-new subscription, arriving before any `vrm.subscriptions` row
    exists to be scanned in the first place.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - _SWEEP_STALE_AFTER
    candidates = (
        _t("subscriptions").select("customer_id, status, current_period_end, last_synced_at")
        .is_("canceled_at", "null")
        .execute().data
    ) or []

    due_customer_ids: set[str] = set()
    for row in candidates:
        current_period_end = _parse_ts(row.get("current_period_end"))
        last_synced = _parse_ts(row.get("last_synced_at"))
        status = row.get("status")
        if (
            (current_period_end is not None and current_period_end < now)
            or status in _TRANSITIONAL_STATUSES
            or last_synced is None
            or last_synced < cutoff
        ):
            due_customer_ids.add(row["customer_id"])

    error_events = (
        _t("billing_events").select("id, customer_id").eq("status", "error")
        .not_.is_("customer_id", "null")
        .execute().data
    ) or []
    error_event_ids_by_customer: dict[str, list[str]] = {}
    for event in error_events:
        customer_id = event["customer_id"]
        due_customer_ids.add(customer_id)
        error_event_ids_by_customer.setdefault(customer_id, []).append(event["id"])

    results: list[BillingReconcileDueResult] = []
    for customer_id in sorted(due_customer_ids):
        event_ids = error_event_ids_by_customer.get(customer_id, [])
        try:
            billing.reconcile_customer(customer_id)
            results.append(BillingReconcileDueResult(customer_id=customer_id, ok=True))
            for event_id in event_ids:
                _t("billing_events").update({
                    "status": "applied", "processed_at": now.isoformat(),
                }).eq("id", event_id).execute()
        except Exception as exc:  # noqa: BLE001 — one customer's failure must not abort the sweep
            logger.warning("billing.reconcile_due: reconcile failed for customer_id=%s — %s", customer_id, exc)
            results.append(BillingReconcileDueResult(customer_id=customer_id, ok=False, error=str(exc)))
            for event_id in event_ids:
                _t("billing_events").update({
                    "error": str(exc)[:500], "processed_at": now.isoformat(),
                }).eq("id", event_id).execute()

    return BillingReconcileDueOut(checked=len(due_customer_ids), results=results)


@router.post("/trial-reminders", response_model=BillingTrialRemindersOut)
def post_trial_reminders() -> BillingTrialRemindersOut:
    """The daily "your trial ends tomorrow" sweep (real live-test feedback,
    2026-08-29) — same shape as `reconcile-due`/`prune-signups` above:
    no `customer_id`, pipeline-key only, meant to be called once a day by
    a GitHub Actions `cron:` (a new workflow, or a new step alongside
    `billing-reconcile.yml`'s existing one). All the actual logic lives in
    `vrm_api/billing.py:send_trial_ending_reminders()` — this endpoint is
    just the HTTP door into it.
    """
    return BillingTrialRemindersOut(**billing.send_trial_ending_reminders())


@router.post("/prune-signups", response_model=BillingPruneSignupsOut)
def post_prune_signups() -> BillingPruneSignupsOut:
    """The Step 7 retention sweep for `vrm.signup_requests` (§3.7) and
    `vrm.rate_limits` (§3.8) — "a retention job that never runs is a
    retention policy that doesn't exist." Same shape as `reconcile-due`
    above: no `customer_id`, pipeline-key only, meant to be called by the
    same daily GitHub Actions `cron:`. Selects ids first and deletes by id
    (same pattern `jobs.py:sweep_stale_jobs()` and
    `storage.py:sweep_orphan_uploads()` already use) so the response can
    report an accurate count rather than guessing from the delete call's own
    (not size-limited) response.

    Two independent deletes, neither gated on the other:
      - `vrm.signup_requests`: unconsumed rows past `expires_at +
        _SIGNUP_UNCONSUMED_GRACE` (7d), OR consumed rows past `consumed_at +
        _SIGNUP_CONSUMED_RETENTION` (30d). A consumed row within its 30-day
        window is kept regardless of how old `expires_at` is — the whole
        point of keeping it is "how did this account get created?", which
        `expires_at` has nothing to do with once the row is consumed.
      - `vrm.rate_limits`: any row whose `window_start` is older than
        `_RATE_LIMIT_RETENTION` — a fixed-window counter has no other notion
        of "done," see the constant's own comment above.
    """
    now = datetime.now(timezone.utc)

    unconsumed_cutoff = (now - _SIGNUP_UNCONSUMED_GRACE).isoformat()
    consumed_cutoff = (now - _SIGNUP_CONSUMED_RETENTION).isoformat()

    stale_unconsumed = (
        _t("signup_requests").select("id").is_("consumed_at", "null")
        .lt("expires_at", unconsumed_cutoff).execute().data
    ) or []
    stale_consumed = (
        _t("signup_requests").select("id").not_.is_("consumed_at", "null")
        .lt("consumed_at", consumed_cutoff).execute().data
    ) or []
    signup_ids = sorted({row["id"] for row in stale_unconsumed} | {row["id"] for row in stale_consumed})
    if signup_ids:
        _t("signup_requests").delete().in_("id", signup_ids).execute()

    rate_limit_cutoff = (now - _RATE_LIMIT_RETENTION).isoformat()
    stale_rate_limits = (
        _t("rate_limits").select("bucket, key, window_start")
        .lt("window_start", rate_limit_cutoff).execute().data
    ) or []
    if stale_rate_limits:
        # A single filtered delete — the composite primary key
        # (bucket, key, window_start) has no standalone id to delete by, and
        # the same `window_start < cutoff` filter that selected these rows
        # above is exactly what should delete them, so there's no race
        # between the select and the delete worth guarding against here.
        _t("rate_limits").delete().lt("window_start", rate_limit_cutoff).execute()

    logger.info(
        "billing.prune_signups: deleted %d signup_requests row(s), %d rate_limits row(s)",
        len(signup_ids), len(stale_rate_limits),
    )
    return BillingPruneSignupsOut(
        signup_requests_deleted=len(signup_ids), rate_limits_deleted=len(stale_rate_limits),
    )


# ═══════════════════════════════════════════════════════════════════════
# Webhook intake (§4.1, §4.2, §6.5, §8 Step 4)
# ═══════════════════════════════════════════════════════════════════════

def _webhook_candidate_ids(data: dict) -> list[str]:
    """§4.2's resolution ladder is written against a single `data.id`
    field, but §0.2b finding 9's confirmed real payload shapes for
    `subscription.renewal.succeeded`/`.failed` — the only two event types
    this product actually expects to receive — carry no generic `id` field
    at all: `subscriptionId`/`paymentIntentId`/`customerId` (succeeded) or
    `subscriptionId`/`paymentIntentId`/`customer.id` (failed) instead. This
    collects every id-shaped string actually present in `data` so the
    ladder below can resolve a real delivery, not just the single generic
    shape the plan's prose described before Step 0 confirmed the real one.
    Order here doesn't matter — `_resolve_webhook_customer()` tries every
    candidate against each table in the ladder's own table order."""
    candidates: list[str] = []
    for key in ("id", "subscriptionId", "invoiceId", "paymentIntentId", "customerId"):
        value = data.get(key)
        if isinstance(value, str) and value:
            candidates.append(value)
    customer = data.get("customer")
    if isinstance(customer, dict):
        value = customer.get("id")
        if isinstance(value, str) and value:
            candidates.append(value)
    return candidates


def _resolve_webhook_customer(candidates: list[str]) -> str | None:
    """§4.2's resolution ladder, in table order: `vrm.subscriptions.
    onvo_subscription_id` → `vrm.subscription_invoices.onvo_invoice_id` /
    `.payment_intent_id` → `vrm.billing_customers.onvo_customer_id`. First
    table with ANY matching candidate wins. Returns `None` if nothing
    matches anywhere — normal, not an error (§4.2: this ONVO account may
    also carry the Solar Design Tool's unrelated one-off payment traffic)."""
    if not candidates:
        return None

    rows = (
        _t("subscriptions").select("customer_id")
        .in_("onvo_subscription_id", candidates).limit(1).execute().data
    )
    if rows:
        return rows[0]["customer_id"]

    rows = (
        _t("subscription_invoices").select("customer_id")
        .in_("onvo_invoice_id", candidates).limit(1).execute().data
    )
    if rows:
        return rows[0]["customer_id"]

    rows = (
        _t("subscription_invoices").select("customer_id")
        .in_("payment_intent_id", candidates).limit(1).execute().data
    )
    if rows:
        return rows[0]["customer_id"]

    rows = (
        _t("billing_customers").select("customer_id")
        .in_("onvo_customer_id", candidates).limit(1).execute().data
    )
    if rows:
        return rows[0]["customer_id"]

    return None


@router.post("/webhook-event", response_model=BillingWebhookEventOut)
def post_webhook_event(body: BillingWebhookEventRequest) -> BillingWebhookEventOut:
    """Intake from the Next.js webhook receiver (§4.1) — see this file's
    module docstring, "The webhook intake specifically", for the full
    picture. Always answers `{"ok": true}` once the `vrm.billing_events`
    row is durably written, even if resolution finds nothing or the
    subsequent reconcile fails (§4.1's response policy: "Recorded
    successfully → 200, even if the subsequent reconcile fails... A non-2xx
    buys nothing"). The one case that legitimately 5xxs here is the insert
    itself failing (database down) — left to `main.py`'s own unhandled-
    exception handler, same as every other endpoint in this API."""
    payload = body.payload
    event_type = payload.get("type") if isinstance(payload.get("type"), str) else None
    data = payload.get("data")
    data = data if isinstance(data, dict) else {}
    candidates = _webhook_candidate_ids(data)
    subscription_id_hint = data.get("subscriptionId") if isinstance(data.get("subscriptionId"), str) else None

    # §4.1: durability before work — this row lands BEFORE any resolution
    # or reconcile is attempted, so a crash after this point still leaves
    # the delivery durably visible for §4.4's sweeper.
    inserted = _t("billing_events").insert({
        "event_type": event_type,
        "payload": payload,
        "secret_ok": body.secret_ok,
        "subscription_id": subscription_id_hint,
    }).execute().data
    event = inserted[0] if inserted else None
    event_id = event.get("id") if event else None

    def _mark(status: str, **fields) -> None:
        if not event_id:
            return
        _t("billing_events").update({
            "status": status, "processed_at": datetime.now(timezone.utc).isoformat(), **fields,
        }).eq("id", event_id).execute()

    if not body.secret_ok:
        # Should never actually happen — the Next.js receiver rejects a
        # bad/missing/misconfigured secret before ever forwarding here
        # (§6.5), including writing its OWN vrm.billing_events row for that
        # case directly. If a forged delivery somehow still reaches this
        # far, this endpoint does nothing further with it beyond the row
        # above — which is the only thing that makes an attempted forgery
        # visible at all (§3.5).
        return BillingWebhookEventOut(ok=True)

    customer_id = _resolve_webhook_customer(candidates)
    if customer_id is None:
        # §4.2: normal, not an error — the same ONVO account may also carry
        # the Solar Design Tool's unrelated one-off project-payment usage.
        _mark("ignored")
        return BillingWebhookEventOut(ok=True)

    _t("billing_events").update({"customer_id": customer_id}).eq("id", event_id).execute()

    try:
        # §0.5: the event only tells us WHO to re-read — it is never
        # applied itself. Never `tenancy.get_customer()`-checked separately:
        # `customer_id` here came from OUR OWN mirror row (§4.2/§6.4), not
        # from anything in the request body, so `reconcile_customer()`'s own
        # internal `tenancy.get_customer()` call is the only check needed.
        billing.reconcile_customer(customer_id)
    except Exception as exc:  # noqa: BLE001 — one webhook's failure must not 5xx the delivery; §4.4's sweeper retries 'error' rows
        logger.warning(
            "billing.webhook_event: reconcile failed for customer_id=%s event_type=%s — %s",
            customer_id, event_type, exc,
        )
        _mark("error", error=str(exc)[:500])
        return BillingWebhookEventOut(ok=True)

    _mark("applied")
    return BillingWebhookEventOut(ok=True)
