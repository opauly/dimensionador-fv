from __future__ import annotations
"""
The domain layer for ONVO billing (PLAN_PHASE16.md §0.3, §4, §8 Step 2). All
the judgement in this phase lives here — `vrm_api/onvo.py` is transport
only, and nothing outside this module ever writes `vrm.customers.plan`,
`site_limit`, `billing_status`, or `provisioning_state` (the third writer
being `lib/server/db/admin.ts`, on the Next.js side, unchanged by this
phase — PLAN_PHASE16.md §0.1/§11).

Two functions, exactly the shape §4 designs:

  `reconcile_customer(customer_id)` — the ONLY code that writes the mirror
  tables (`vrm.billing_customers`, `vrm.subscriptions`,
  `vrm.subscription_invoices`). Read-through, not event-sourced (§0.5): it
  never applies a webhook payload, never trusts its own previous write,
  always re-reads ONVO with the secret key and overwrites the mirror
  wholesale. Every mutation this product performs elsewhere (Step 3's
  subscribe/cancel/change endpoints) is required to end by calling this —
  see §11's "never parse our own POST's response into state."

  `apply_entitlements(customer_id)` — the only path from money to
  `plan`/`site_limit`/`billing_status`/`provisioning_state`, called only
  from `reconcile_customer()` (§4.5). It never talks to ONVO directly; it
  only reads what `reconcile_customer()` just wrote to the mirror.

── The concurrency guard (§4.3 rule 6) ─────────────────────────────────────
Every mirror upsert here is conditional on `last_synced_at < fetched_at`
(`fetched_at` stamped once, before this reconcile's first ONVO call —
`_conditional_upsert()`'s docstring has the mechanics). Two concurrent
`reconcile_customer()` calls therefore resolve to whichever one READ later,
never whichever one WROTE last — the only ordering rule this system needs,
and one that depends on nothing inside ONVO's own (unordered, un-timestamped
— §0.2b finding 9) payloads.

── Status → entitlement mapping (§4.5 rule 2, filled in from §0.2b finding
   4's closed 7-value vocabulary) ───────────────────────────────────────
See `_STATUS_ENTITLEMENT` below. `past_due` counts as entitled (Q8's 7-day
grace policy — implemented by simply treating the status as entitled while
it lasts; ONVO's own dunning cycle is what eventually moves it to `active`
or a terminal state, this module does not run a separate timer). Any status
NOT in the map is unrecognized (ONVO added a value with no notice) and HOLDS
current entitlement rather than dropping it — §4.5 rule 2's own reasoning:
over-granting for a day is a far smaller failure than locking a paying
customer out of their own data over a third party's enum change.

── Entitled status is necessary but NOT sufficient — the payment-method gap
   (fixed here, live-validation finding, 2026-08-20) ────────────────────
`routers/billing.py:post_subscription()` creates the ONVO subscription with
`paymentBehavior: allow_incomplete`, `trialPeriodDays: 7`, and **no**
`paymentMethodId` — and §0.2b finding 11, re-confirmed live while building
this fix, means ONVO reports that subscription as `status: "trialing"`
**immediately**, before any card is ever collected. §0.6 Q2's decision
("card required upfront") is a product intent, not something ONVO's
`status` field enforces on our behalf. A caller who calls `POST
/v1/billing/subscription` and then `POST /v1/billing/refresh` directly
(skipping the SDK widget's card-entry step entirely) would otherwise walk
straight into `_STATUS_ENTITLEMENT["trialing"] == True` and be granted a
full trial with no card ever collected. `apply_entitlements()` below
therefore treats "status is entitled-shaped" as necessary but not
sufficient: it additionally requires `vrm.billing_customers.
default_payment_method_id` to be non-null for this customer before
granting/promoting. If the status is entitled-shaped but there is no
payment method on file, this is folded into the SAME `'hold'` branch
`_classify_status()` already uses for an unrecognized status — do not
grant, do not promote, log loudly (`billing.entitled_status_no_payment_
method`) — because the reasoning is identical: an ambiguous "should we
grant?" state is safer held than guessed. This covers both a signup still
mid-flow (waiting for the SDK step) and a payment method detached after
the fact (an admin/ONVO-dashboard action — not exposed to customers, §5.3);
in the latter case ONVO's own dunning cycle naturally moves `status` off an
entitled value on the next failed renewal attempt, and ordinary
classification takes it from there.
"""
import logging
import os
from datetime import datetime, timezone

from database.supabase_client import get_client
from vrm_api import onvo, tenancy

logger = logging.getLogger("vrm_api.billing")

SCHEMA = "vrm"

# status -> True (entitled) / False (not entitled). Closed vocabulary,
# §0.2b finding 4. `unpaid`'s mapping is a documented ASSUMPTION, not a
# confirmed ONVO semantic — see the comment on that line.
_STATUS_ENTITLEMENT: dict[str, bool] = {
    "active": True,
    "trialing": True,
    "past_due": True,  # Q8 grace period — see module docstring
    "canceled": False,
    "incomplete_expired": False,
    # Never successfully charged even once — no access was ever earned.
    # Matches §0.2b finding 11's observed decline behaviour: a subscription
    # created with a declining card lands here immediately.
    "incomplete": False,
    # ASSUMPTION, not a confirmed ONVO semantic — Step 0 (§0.2b) did not
    # specifically test what triggers `unpaid` vs `canceled` vs an
    # exhausted `past_due` retry cycle. Treated as not-entitled because it
    # is, by name, a subscription ONVO itself no longer considers current.
    # Revisit if customers land here more than rarely in practice.
    "unpaid": False,
}

# vrm.customers.billing_status vocabulary — this dict body IS the
# documentation (§3.6: "no CHECK constraint on that column exists, so this
# is your call to make and document"). Deliberately close to ONVO's own raw
# status rather than collapsing everything into the plan's five-value
# example, because a support agent reading `billing_status='incomplete'`
# ("they entered a card that never actually charged") learns something a
# flattened `'canceled'` would hide. Values:
#   'none'       — no subscription has ever been found for this customer
#                  (never subscribed, or a still-pending signup).
#   'trialing'   — ONVO status `trialing`.
#   'active'     — ONVO status `active`.
#   'past_due'   — ONVO status `past_due` (Q8's grace window; still
#                  entitled).
#   'incomplete' — ONVO status `incomplete`: created, never successfully
#                  charged. Not entitled.
#   'unpaid'     — ONVO status `unpaid` (see the ASSUMPTION comment above).
#                  Not entitled.
#   'canceled'   — ONVO status `canceled` OR `incomplete_expired` — from a
#                  support/UI point of view both mean "this subscription is
#                  over, there is no access," so they share one bucket here.
# An unrecognized ONVO status leaves billing_status untouched (§4.5 rule 2's
# "hold" behaviour applies to this column too, not just plan/site_limit).
_BILLING_STATUS_FOR_ONVO_STATUS: dict[str, str] = {
    "active": "active",
    "trialing": "trialing",
    "past_due": "past_due",
    "canceled": "canceled",
    "incomplete_expired": "canceled",
    "incomplete": "incomplete",
    "unpaid": "unpaid",
}


def _t(name: str):
    return get_client().schema(SCHEMA).table(name)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


# ═══════════════════════════════════════════════════════════════════════
# reconcile_customer — the only thing that writes the mirror (§4.3)
# ═══════════════════════════════════════════════════════════════════════

def reconcile_customer(customer_id: str) -> dict:
    """Re-reads this customer's billing state from ONVO and overwrites the
    mirror wholesale, then runs the entitlement writer. Returns a plain
    dict summary (not a raw ONVO payload — §4.3 step 8) suitable for a
    caller (a router, later steps, or a validation script) to inspect.

    Safe to call for a customer who has never touched billing at all: if no
    `vrm.billing_customers` row exists yet, this makes no ONVO calls and
    simply runs `apply_entitlements()` (which, finding no subscription in
    the mirror either, leaves `plan`/`site_limit` untouched — §4.5's
    "not entitled and never was" case).
    """
    tenancy.get_customer(customer_id)  # NotAuthorized if customer_id is bogus
    fetched_at = datetime.now(timezone.utc)  # §4.3 step 1 — BEFORE the first ONVO call

    billing_row = _billing_customer_row(customer_id)
    if billing_row is None:
        apply_entitlements(customer_id)
        return _billing_state(customer_id)

    onvo_customer_id = billing_row["onvo_customer_id"]
    mode = billing_row.get("mode") or os.environ.get("ONVO_MODE", "test")

    # §4.3 step 2 — the LIST call, not get-by-id: the only way to discover
    # a subscription created out-of-band (ONVO's dashboard, or a create
    # call whose response we lost). There is no `subscription.created`
    # event (§0.5).
    raw_subscriptions = onvo.list_customer_subscriptions(onvo_customer_id)
    # §4.3 step 3.
    raw_payment_methods = onvo.list_customer_payment_methods(onvo_customer_id)
    onvo_customer = onvo.get_customer(onvo_customer_id)

    current_raw_sub = _pick_current_raw_subscription(raw_subscriptions)

    # §4.3 step 4 — renewals for the active subscription only.
    raw_invoices: list[dict] = []
    if current_raw_sub is not None:
        raw_invoices = onvo.list_invoices(subscription_id=current_raw_sub["id"])

    default_pm = _pick_default_payment_method(
        raw_payment_methods, current_raw_sub["paymentMethodId"] if current_raw_sub else None,
    )
    billing_address: dict = {}
    if default_pm is not None:
        try:
            pm_detail = onvo.get_payment_method(default_pm["id"])
            billing_address = (pm_detail.get("billing") or {}).get("address") or {}
        except onvo.OnvoError:
            logger.warning(
                "billing reconcile: could not fetch payment method detail "
                "for customer_id=%s (non-fatal — billing_address left stale).",
                customer_id,
            )

    # §4.3 step 5/6 — upsert every mirror row wholesale, each conditional
    # on last_synced_at < fetched_at.
    _upsert_billing_customer(customer_id, onvo_customer, default_pm, billing_address, mode, fetched_at)

    mirror_sub_id = None
    for raw_sub in raw_subscriptions:
        # Every subscription this customer has at ONVO gets its own mirror
        # row, not just the current one — Q3's cancel-and-restart design
        # means a customer can accumulate several over time, and each is
        # real history worth keeping (§4.3 step 5's "upsert every mirror
        # row"). §4.3 step 7 (resolve onvo_price_id -> plan_key via
        # vrm.plans, NULL if unrecognized) happens inside this call.
        row = _upsert_subscription(customer_id, raw_sub, mode, fetched_at)
        if current_raw_sub is not None and raw_sub.get("id") == current_raw_sub.get("id"):
            mirror_sub_id = row["id"]

    if mirror_sub_id is not None:
        _upsert_invoices(customer_id, mirror_sub_id, raw_invoices, fetched_at)

    apply_entitlements(customer_id)
    return _billing_state(customer_id)


def _billing_customer_row(customer_id: str) -> dict | None:
    rows = _t("billing_customers").select("*").eq("customer_id", customer_id).limit(1).execute().data
    return rows[0] if rows else None


def _pick_current_raw_subscription(subscriptions: list[dict]) -> dict | None:
    """§4.5 rule 1's selection ("the non-canceled one; if several, the most
    recently created"), applied to ONVO's raw list — used before anything
    is written, to decide which subscription's invoices to fetch (§4.3
    step 4) and which payment method counts as "default" for display."""
    if not subscriptions:
        return None

    def _created(sub: dict) -> datetime:
        return _parse_ts(sub.get("createdAt")) or datetime.min.replace(tzinfo=timezone.utc)

    ordered = sorted(subscriptions, key=_created, reverse=True)
    live = [s for s in ordered if s.get("status") != "canceled"]
    if len(live) > 1:
        logger.error(
            "billing.multiple_live_subscriptions_at_onvo customer has %d "
            "non-canceled ONVO subscriptions (%s) — should be impossible "
            "given the duplicate-create guard (§5.4, Step 3). Using the "
            "most recently created for invoice/payment-method resolution.",
            len(live), [s.get("id") for s in live],
        )
    return live[0] if live else ordered[0]


def _pick_default_payment_method(payment_methods: list[dict], current_pm_id: str | None) -> dict | None:
    """The payment method actually attached to the current subscription
    wins, if any; otherwise the most recently created active one; otherwise
    None (a customer with no card on file at all)."""
    if current_pm_id:
        for pm in payment_methods:
            if pm.get("id") == current_pm_id:
                return pm
    active = [pm for pm in payment_methods if pm.get("status") == "active"] or payment_methods
    if not active:
        return None
    return sorted(active, key=lambda pm: pm.get("createdAt") or "", reverse=True)[0]


def _resolve_plan_row(onvo_price_id: str | None, mode: str) -> dict | None:
    """§4.3 step 7 — resolve `onvo_price_id` -> our own `plan_key`/
    `site_limit` via `vrm.plans`. Returns None if unrecognized; the caller
    must never fail the sync over an unseeded price."""
    if not onvo_price_id:
        return None
    rows = (
        _t("plans").select("plan_key, site_limit, billing_interval, currency, amount_minor")
        .eq("onvo_price_id", onvo_price_id).eq("mode", mode).limit(1).execute().data
    )
    return rows[0] if rows else None


def _conditional_upsert(table: str, conflict_col: str, conflict_val, payload: dict, fetched_at: datetime) -> dict:
    """Upsert `payload` into `table`, keyed by `conflict_col`, honoring the
    §4.3 rule 6 concurrency guard: a write only lands if the existing row's
    `last_synced_at` is NULL or strictly earlier than `fetched_at` (this
    reconcile's own read-time stamp, stamped once, before ONVO was ever
    called). Two concurrent reconciles therefore resolve to whichever one
    READ later, never whichever one WROTE last.

    The `UPDATE ... WHERE conflict_col = X AND (last_synced_at IS NULL OR
    last_synced_at < fetched_at)` is one atomic round trip through
    PostgREST — Postgres evaluates and applies it as a single statement, so
    there is no window between "check" and "write" for another reconcile to
    land in. If it updates nothing, one of two things is true: (a) no row
    exists yet (attempt an INSERT — extremely rare in this product's actual
    call pattern, since every table this is used for is only ever reconciled
    after the row-creating step has already run once), or (b) a row exists
    but a concurrent reconcile that read *later* already won the race — in
    which case this call deliberately does nothing further; losing that race
    on purpose is the whole mechanism, not a bug. Case (a)'s own small
    window (a plain SELECT, then an INSERT) is backstopped by the table's
    own UNIQUE constraint on `conflict_col`: a lost insert race raises, is
    caught, and is treated as "someone else's row is now the row."

    Returns the row as it stands after this call (whichever reconcile's
    write actually won), so callers (e.g. to link a subscription's own uuid
    into `vrm.subscription_invoices.subscription_id`) never need a second
    round trip to find out.
    """
    fetched_at_iso = fetched_at.isoformat()
    row_payload = {**payload, "last_synced_at": fetched_at_iso}
    t = _t(table)

    updated = (
        t.update(row_payload)
        .eq(conflict_col, conflict_val)
        .or_(f"last_synced_at.is.null,last_synced_at.lt.{fetched_at_iso}")
        .execute()
        .data
    )
    if not updated:
        # Select conflict_col itself, not "id" — every table this helper is
        # used for has conflict_col, but not every one has an `id` column
        # under that exact name (vrm.billing_customers' own PK is
        # customer_id, not id).
        existing = t.select(conflict_col).eq(conflict_col, conflict_val).limit(1).execute().data
        if not existing:
            try:
                t.insert({conflict_col: conflict_val, **row_payload}).execute()
            except Exception:  # noqa: BLE001 — a lost insert race, not a real failure
                logger.info(
                    "billing reconcile: lost an insert race on %s.%s=%s to a "
                    "concurrent reconcile.", table, conflict_col, conflict_val,
                )
        # else: a fresher concurrent reconcile already holds this row — its
        # write wins; ours is deliberately dropped (§4.3 rule 6).

    row = t.select("*").eq(conflict_col, conflict_val).limit(1).execute().data
    return row[0] if row else row_payload


def _upsert_billing_customer(
    customer_id: str, onvo_customer: dict, default_pm: dict | None,
    billing_address: dict, mode: str, fetched_at: datetime,
) -> dict:
    card = (default_pm or {}).get("card") or {}
    payload = {
        "onvo_customer_id": onvo_customer.get("id"),
        "mode": mode,
        "billing_name": onvo_customer.get("name"),
        "billing_email": onvo_customer.get("email"),
        # Mirrors ONVO's own shape verbatim (§3.2) — sourced from the
        # default payment method's `billing.address` (the only place ONVO
        # actually carries a billing address; `Customer.address` was
        # observed null and is not settable — see onvo.py:get_payment_
        # method()'s docstring).
        "billing_address": {
            "city": billing_address.get("city"),
            "country": billing_address.get("country"),
            "line1": billing_address.get("line1"),
            "line2": billing_address.get("line2"),
            "postalCode": billing_address.get("postalCode"),
            "state": billing_address.get("state"),
        } if billing_address else {},
        "default_payment_method_id": (default_pm or {}).get("id"),
        "pm_brand": card.get("brand"),
        "pm_last4": card.get("last4"),
        "pm_exp_month": card.get("expMonth"),
        "pm_exp_year": card.get("expYear"),
    }
    return _conditional_upsert("billing_customers", "customer_id", customer_id, payload, fetched_at)


def _upsert_subscription(customer_id: str, sub: dict, mode: str, fetched_at: datetime) -> dict:
    items = sub.get("items") or []
    price_id = items[0].get("priceId") if items else None
    plan_row = _resolve_plan_row(price_id, sub.get("mode") or mode)
    latest_invoice = sub.get("latestInvoice") or {}

    payload = {
        "customer_id": customer_id,
        "mode": sub.get("mode") or mode,
        # NULL if unrecognized — never fail the sync over an unseeded price
        # (§3.3, §4.3 step 7).
        "plan_key": plan_row["plan_key"] if plan_row else None,
        "onvo_price_id": price_id,
        # Sourced from vrm.plans (plan_row), NOT from ONVO's own response —
        # fixed 2026-08-21, live-testing finding: the original code assumed
        # ONVO's price object carried a nested `recurring.interval` field
        # (a reasonable-looking guess, never checked against a real
        # payload). A real subscription's raw JSON, inspected directly,
        # shows ONVO's price object has no `recurring` key at all — just
        # `type: "recurring"` as a flat string alongside `currency`/
        # `unitAmount`, with the actual interval (month/year) exposed
        # nowhere on this object. `currency`/`amount_minor` stay sourced
        # from ONVO's response below (those fields genuinely ARE there);
        # only `billing_interval` needed the vrm.plans fallback, which is
        # `NULL` in the same "unrecognized price" case `plan_key` already
        # handles, not a new failure mode.
        "billing_interval": plan_row["billing_interval"] if plan_row else None,
        "currency": (items[0].get("price") or {}).get("currency") if items else None,
        "amount_minor": (items[0].get("price") or {}).get("unitAmount") if items else None,
        "status": sub.get("status"),
        "cancel_at_period_end": bool(sub.get("cancelAtPeriodEnd") or False),
        "cancel_at": sub.get("cancelAt"),
        "canceled_at": sub.get("canceledAt"),
        "current_period_start": sub.get("currentPeriodStart"),
        "current_period_end": sub.get("currentPeriodEnd"),
        "trial_start": sub.get("trialStart"),
        "trial_end": sub.get("trialEnd"),
        "latest_invoice_id": latest_invoice.get("id") or sub.get("latestInvoiceId"),
        "latest_invoice_status": latest_invoice.get("status"),
        "raw": sub,
    }
    return _conditional_upsert("subscriptions", "onvo_subscription_id", sub["id"], payload, fetched_at)


def _upsert_invoices(customer_id: str, subscription_row_id: str, invoices: list[dict], fetched_at: datetime) -> None:
    for inv in invoices:
        payload = {
            "customer_id": customer_id,
            "subscription_id": subscription_row_id,
            "status": inv.get("status"),
            "currency": inv.get("currency"),
            "total_minor": inv.get("total"),
            "subtotal_minor": inv.get("subTotal"),
            "original_total_minor": inv.get("originalTotal"),
            "period_start": inv.get("periodStart"),
            "period_end": inv.get("periodEnd"),
            "attempt_count": inv.get("attemptCount"),
            "last_payment_attempt": inv.get("lastPaymentAttempt"),
            "next_payment_attempt": inv.get("nextPaymentAttempt"),
            "payment_intent_id": inv.get("paymentIntentId"),
            "raw": inv,
        }
        _conditional_upsert("subscription_invoices", "onvo_invoice_id", inv["id"], payload, fetched_at)


def _current_mirror_subscription(customer_id: str) -> dict | None:
    """The customer's current subscription AS ALREADY WRITTEN TO THE
    MIRROR (used by `apply_entitlements()`, which never talks to ONVO
    directly — it only reads what `reconcile_customer()` just wrote).
    §4.5 rule 1: the non-canceled one; if several (should be impossible,
    the partial unique index on migration 025 backs this up — see that
    migration's own comment on why it uses `canceled_at IS NULL` as its
    named fallback), the most recently created, logged loudly. If every
    subscription found is canceled, the most recently created one is still
    returned — it IS "the current subscription," just a lapsed one (§4.5's
    "entitled -> then not entitled" case); only a customer with NO
    subscription row at all gets `None` (§4.5's "never was" case).
    """
    rows = (
        _t("subscriptions").select("*").eq("customer_id", customer_id)
        .order("created_at", desc=True).execute().data
    )
    if not rows:
        return None
    live = [r for r in rows if r.get("canceled_at") is None]
    if len(live) > 1:
        logger.error(
            "billing.multiple_live_subscriptions customer_id=%s has %d "
            "non-canceled vrm.subscriptions rows (%s) — the partial unique "
            "index (migration 025) should have made this impossible. Using "
            "the most recently created.",
            customer_id, len(live), [r["onvo_subscription_id"] for r in live],
        )
    return live[0] if live else rows[0]


def _classify_status(status: str | None) -> str:
    """Returns `'entitled'`, `'not_entitled'`, or `'hold'` (§4.5 rule 2).
    `'hold'` is logged here, loudly, at error level — this IS the one place
    an unrecognized ONVO status becomes visible, since the caller is
    required to touch nothing further when it sees `'hold'`."""
    if status in _STATUS_ENTITLEMENT:
        return "entitled" if _STATUS_ENTITLEMENT[status] else "not_entitled"
    logger.error(
        "billing.unrecognized_status: ONVO subscription status %r is not in "
        "our known vocabulary (%s). Holding current entitlement rather than "
        "guessing (§4.5 rule 2) — over-granting for a day is a far smaller "
        "failure than locking a paying customer out over a third party's "
        "enum change.",
        status, sorted(_STATUS_ENTITLEMENT),
    )
    return "hold"


# ═══════════════════════════════════════════════════════════════════════
# apply_entitlements — the only path from money to plan/site_limit (§4.5)
# ═══════════════════════════════════════════════════════════════════════

def apply_entitlements(customer_id: str) -> None:
    """Called only from `reconcile_customer()`. Never talks to ONVO. Reads
    the customer row and the mirror `vrm.subscriptions` table, then writes
    at most one UPDATE to `vrm.customers` covering whichever of
    `plan`/`site_limit`/`billing_status`/`provisioning_state` actually
    changed — logged as one line with old->new values (§4.5 rule 7)."""
    customer = tenancy.get_customer(customer_id)
    subscription = _current_mirror_subscription(customer_id)

    updates: dict = {}
    changed: list[str] = []

    def _set(field: str, new_value) -> None:
        old_value = customer.get(field)
        if new_value != old_value:
            updates[field] = new_value
            changed.append(f"{field}: {old_value!r} -> {new_value!r}")

    if subscription is None:
        # §4.5's "not entitled and never was" case: no subscription row
        # found at all — a legacy/manually-managed customer, or a signup
        # that hasn't reached checkout. plan/site_limit are NEVER touched
        # here, in either direction — that is the entire point of this
        # branch (§3.6's own trap: touching site_limit for a
        # 'pending_subscription' row created with the wrong default would
        # freeze it at 0 forever; touching it for a legacy hand-managed row
        # would silently overwrite a negotiated deal).
        _set("billing_status", "none")
    else:
        onvo_status = subscription.get("status")
        classification = _classify_status(onvo_status)

        if classification == "entitled" and not (_billing_customer_row(customer_id) or {}).get(
            "default_payment_method_id"
        ):
            # Status alone is necessary but not sufficient — see module
            # docstring's "Entitled status is necessary but NOT sufficient"
            # section. Folded into the same 'hold' branch _classify_status()
            # already uses for an unrecognized status: do not grant, do not
            # promote, this IS the visible record (§4.5 rule 2's reasoning,
            # extended).
            logger.error(
                "billing.entitled_status_no_payment_method customer_id=%s "
                "subscription %s has status=%r (entitled-shaped per "
                "_STATUS_ENTITLEMENT) but vrm.billing_customers."
                "default_payment_method_id is not set for this customer — "
                "holding current entitlement, granting nothing, promoting "
                "nothing. Either a signup that has not completed the ONVO "
                "SDK card step yet, or a payment method detached after "
                "entitlement was already granted.",
                customer_id, subscription.get("onvo_subscription_id"), onvo_status,
            )
            classification = "hold"

        if classification == "hold":
            # §4.5 rule 2 — touch NOTHING, not even billing_status. The
            # error line from _classify_status() (unrecognized status) or
            # the entitled-but-no-payment-method check above is the record.
            pass
        else:
            new_billing_status = _BILLING_STATUS_FOR_ONVO_STATUS.get(onvo_status, customer.get("billing_status"))
            _set("billing_status", new_billing_status)

            site_limit_source = customer.get("site_limit_source")

            if classification == "entitled":
                plan_key = subscription.get("plan_key")
                if plan_key:
                    _set("plan", plan_key)
                    # The site_limit_source trap this exists to prevent
                    # (§3.6): a hand-negotiated site_limit must NEVER be
                    # overwritten by a plan's default grant.
                    if site_limit_source == "plan":
                        plan_row = _resolve_plan_row(subscription.get("onvo_price_id"), subscription.get("mode"))
                        if plan_row is not None:
                            # NULL here means "unlimited" (§3.1's own
                            # convention) and IS a value worth writing, not
                            # a signal to skip.
                            _set("site_limit", plan_row.get("site_limit"))
                else:
                    # The subscription's onvo_price_id has no matching
                    # vrm.plans row (e.g. a hand-built ONVO price for a
                    # Fleet deal that was never seeded). The customer PAID
                    # — asymmetric risk (§4.5 rule 2's own reasoning
                    # applies here too) says promotion below must still
                    # happen; we just can't derive a plan label or a site
                    # grant, so those two fields are left untouched and
                    # this is logged loudly for a human to seed the price.
                    logger.error(
                        "billing.unresolved_price customer_id=%s subscription "
                        "%s is entitled (status=%s) but its onvo_price_id has "
                        "no matching vrm.plans row — plan/site_limit left "
                        "untouched. Seed vrm.plans for this price.",
                        customer_id, subscription.get("onvo_subscription_id"), onvo_status,
                    )

                # §4.5 rule 8 — promotion, one-way, same write as
                # plan/site_limit above.
                if customer.get("provisioning_state") == "pending_subscription":
                    _set("provisioning_state", "active")

            else:  # not_entitled, and a subscription WAS found (a real,
                    # lapsed customer — §4.5's "entitled -> then not
                    # entitled" case)
                _set("plan", "trial")
                if site_limit_source == "plan":
                    _set("site_limit", 0)
                # Deliberately NOT reverting provisioning_state — §4.5 rule
                # 8: promotion is one-way. A lapsed real tenant is not a
                # pending signup again; their site_limit dropping to 0 (if
                # site_limit_source='plan') is the entire enforcement, and
                # canAddSite() is what acts on it. No site is ever
                # deactivated, hidden, or deleted by this function, ever.

    if updates:
        _t("customers").update(updates).eq("id", customer_id).execute()
        logger.info("billing.entitlement_changed customer_id=%s: %s", customer_id, "; ".join(changed))
        if updates.get("provisioning_state") == "active":
            logger.info(
                "signup.promoted customer_id=%s plan=%s site_limit=%s",
                customer_id, updates.get("plan", customer.get("plan")),
                updates.get("site_limit", customer.get("site_limit")),
            )


def _billing_state(customer_id: str) -> dict:
    """A small, typed-enough summary for a caller (a router in Step 3, or
    this step's own validation script) — never a raw ONVO payload (§4.3
    step 8)."""
    customer = tenancy.get_customer(customer_id)
    subscription = _current_mirror_subscription(customer_id)
    billing_row = _billing_customer_row(customer_id)
    return {
        "customer_id": customer_id,
        "plan": customer.get("plan"),
        "site_limit": customer.get("site_limit"),
        "site_limit_source": customer.get("site_limit_source"),
        "billing_status": customer.get("billing_status"),
        "provisioning_state": customer.get("provisioning_state"),
        "subscription": subscription,
        "billing_customer": billing_row,
    }
