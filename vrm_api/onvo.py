from __future__ import annotations
"""
Authenticated HTTP client for ONVO Pay's API (PLAN_PHASE16.md §0.3, §8 Step 2).

Transport only: this module knows paths, headers, retries, and how to turn
an HTTP failure into a typed exception. It knows nothing about
`vrm.customers`, `vrm.subscriptions`, or any other row in this product's own
schema — that judgement lives in `vrm_api/billing.py`, never here (§0.3's
naming rule, restated).

Base URL, auth, and every path/method below are exactly what
PLAN_PHASE16.md §0.2b's live Step 0 probe confirmed against Oscar's real
ONVO test-mode account — nothing here is guessed or "improved":
  - Base URL: `https://api.onvopay.com/v1` (§0.2b finding 1).
  - Auth: `Authorization: Bearer <ONVO_SECRET_KEY>` (§0.2 [C]).
  - Every *update* to an existing object is `POST /v1/<resource>/{id}`, NOT
    `PUT`/`PATCH` — both 404 with `"Cannot PUT/PATCH ..."` (§0.2b finding 1).
    The one documented exception, `PATCH /v1/subscriptions/{id}/items/
    {itemId}`, is irrelevant here: Q3 ruled out item-level price changes
    entirely (§0.2b finding 6 — cancel-and-restart instead), so this module
    never touches the `/items` sub-resource at all.
  - Cancel is `DELETE /v1/subscriptions/{id}` and is synchronous — `status`
    flips to `canceled` and `canceledAt` is stamped in the same response
    (§0.2b finding 12).
  - `paymentBehavior` is exactly `allow_incomplete` | `default_incomplete`
    (§0.2b finding 3) — `create_subscription()` raises `ValueError` on
    anything else rather than silently forwarding a typo to ONVO.
  - `Idempotency-Key` is NOT honored by ONVO on `POST /v1/subscriptions`
    (§0.2b finding 8, confirmed live, with and without the header) — this
    module does not send one; duplicate-creation safety is entirely
    `vrm_api/billing.py`'s and, later, `routers/billing.py`'s job (§5.4).

── Retry policy ────────────────────────────────────────────────────────────
Timeouts on every call (`DEFAULT_TIMEOUT_S`). Retried with exponential
backoff + jitter ONLY on 429 and 5xx — a real rejection (any other 4xx) is
never retried: retrying can't fix a bad request, and for a CREATE call it
risks producing a second real object at ONVO (compounded by the fact that
`Idempotency-Key` does nothing here, finding 8 above). A network error or a
timeout is likewise never retried by this module, for the same
duplicate-creation reason: an unanswered request's server-side outcome is
unknown, and blindly retrying a `POST` in that state is exactly the failure
mode this repo's other HTTP client (`victron/vrm_remote.py`) also refuses to
paper over — it raises immediately instead and lets the caller (a reconcile,
always following any mutation, per §0.5) find out what actually happened.

── The one rule that matters most in this file (PLAN_PHASE16.md §8 Step 2,
   §11, and `vrm_api/secrets.py`'s own module docstring rule 1, restated
   for a different secret) ──────────────────────────────────────────────
No function here ever logs, or puts into a raised exception's message:
`ONVO_SECRET_KEY`, or a raw request/response body. Every exception below
carries only the HTTP method, the endpoint path, and the status code.
Headers are built fresh immediately before each call (`_headers()`) and are
never stored, logged, or serialized — same discipline
`victron/vrm_remote.py`'s module docstring holds itself to for a Victron
token, applied here to ONVO's secret key instead.
"""
import logging
import os
import random
import time

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("vrm_api.onvo")

BASE_URL = "https://api.onvopay.com/v1"
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_MAX_RETRIES = 4
DEFAULT_BACKOFF_BASE_S = 1.0
DEFAULT_BACKOFF_MAX_S = 20.0

_VALID_PAYMENT_BEHAVIORS = ("allow_incomplete", "default_incomplete")


class OnvoError(Exception):
    """Base class for this module's errors. Every subclass below is
    constructed with only an HTTP method/path/status code — never a header,
    a key, or a response/request body. See the module docstring."""


class OnvoAuthError(OnvoError):
    """ONVO rejected our secret key (401/403 on any call). This should never
    happen in normal operation — if it does, `ONVO_SECRET_KEY` itself is
    wrong or has been rotated, not a per-customer problem."""


class OnvoNotFoundError(OnvoError):
    """404 — the requested object (customer/subscription/payment method/
    invoice) does not exist at ONVO. Distinguished from a generic rejection
    so `vrm_api/billing.py` can tell "this id is stale" apart from "this
    request was malformed"."""


class OnvoRequestError(OnvoError):
    """Any other 4xx — a real rejection (bad parameters, a business-rule
    ONVO enforces, etc). Never retried by this module — see the module
    docstring's retry policy."""


class OnvoUnavailableError(OnvoError):
    """A 5xx after the retry budget was exhausted, a network error, a
    request timeout, or a response body that didn't parse as JSON."""


def _secret_key() -> str:
    key = os.environ.get("ONVO_SECRET_KEY", "")
    if not key:
        # Deliberately a plain OnvoError, not a crash on import — a process
        # that never calls into this module (most of vrm_api, most of the
        # time) must not fail to start just because ONVO isn't configured
        # yet in this environment.
        raise OnvoError("ONVO_SECRET_KEY is not set.")
    return key


def _headers() -> dict:
    # Built immediately before each call, never stored, never logged — see
    # the module docstring's "one rule that matters most."
    return {"Authorization": f"Bearer {_secret_key()}", "Content-Type": "application/json"}


def _backoff_delay(attempt: int, retry_after: str | None) -> float:
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            pass
    base = min(DEFAULT_BACKOFF_BASE_S * (2 ** (attempt - 1)), DEFAULT_BACKOFF_MAX_S)
    return base * (0.5 + random.random())  # jitter: 0.5x-1.5x of base


def _request(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    json_body: dict | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict:
    url = f"{BASE_URL}{path}"
    attempt = 0
    while True:
        try:
            response = requests.request(
                method, url, headers=_headers(), params=params, json=json_body, timeout=timeout_s,
            )
        except requests.exceptions.Timeout:
            # Never retried — see module docstring: an unanswered request's
            # server-side outcome is unknown, and this is a POST-heavy API
            # with no working idempotency key (finding 8).
            raise OnvoUnavailableError(f"Timed out calling ONVO ({method} {path}).") from None
        except requests.exceptions.RequestException:
            raise OnvoUnavailableError(f"Network error calling ONVO ({method} {path}).") from None

        if response.status_code in (401, 403):
            raise OnvoAuthError(f"ONVO rejected our credentials ({response.status_code} on {method} {path}).")
        if response.status_code == 404:
            raise OnvoNotFoundError(f"Not found: {method} {path}.")

        if response.status_code == 429 or response.status_code >= 500:
            attempt += 1
            if attempt > max_retries:
                logger.warning(
                    "ONVO %s for %s %s; retry budget exhausted (attempt=%s, max_retries=%s).",
                    response.status_code, method, path, attempt, max_retries,
                )
                raise OnvoUnavailableError(
                    f"ONVO returned {response.status_code} for {method} {path} "
                    "and the retry budget was exhausted."
                )
            delay = _backoff_delay(attempt, response.headers.get("Retry-After"))
            logger.warning(
                "ONVO %s for %s %s; retrying (attempt %s/%s) after %.1fs.",
                response.status_code, method, path, attempt, max_retries, delay,
            )
            time.sleep(delay)
            continue

        if 400 <= response.status_code < 500:
            # A real rejection — never retried (see module docstring).
            raise OnvoRequestError(f"ONVO rejected {method} {path} ({response.status_code}).")

        if not response.ok:
            raise OnvoUnavailableError(f"ONVO returned {response.status_code} for {method} {path}.")

        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            raise OnvoUnavailableError(
                f"ONVO returned a non-JSON response for {method} {path}."
            ) from None


def _unwrap_list(body) -> list[dict]:
    """ONVO's list endpoints are inconsistent about the envelope: `GET
    /customers`, `GET /customers/{id}/subscriptions`, and `GET /invoices`
    all return `{"data": [...], "meta": {...}}` (§0.2b finding 1, confirmed
    live), while `GET /customers/{id}/payment-methods` returns a bare JSON
    array (confirmed live at Step 2 — see the coder's own shape probe,
    referenced in this phase's build notes). Accepting either shape here
    means every caller in `vrm_api/billing.py` gets a plain `list[dict]`
    regardless of which envelope a given endpoint happens to use."""
    if isinstance(body, list):
        return body
    if isinstance(body, dict) and isinstance(body.get("data"), list):
        return body["data"]
    return []


# ── Customers ────────────────────────────────────────────────────────────

def create_customer(*, name: str, email: str, metadata: dict | None = None) -> dict:
    """`POST /v1/customers` (§0.2b finding 1).

    `metadata` is accepted here for call-site symmetry with
    `create_subscription()` (whose `metadata` field IS accepted by ONVO,
    per §0.2 [C]'s own docs example) but is DELIBERATELY NEVER SENT — Step 3
    found live that `POST /v1/customers` rejects it outright
    (`400 "property metadata should not exist"`), the exact same shape of
    surprise §0.2b finding 2 already recorded for price creation rejecting
    `description`. Callers may keep passing `metadata` (harmless, silently
    dropped) rather than needing to know this per-endpoint quirk themselves.
    """
    body: dict = {"name": name, "email": email}
    return _request("POST", "/customers", json_body=body)


def get_customer(onvo_customer_id: str) -> dict:
    """`GET /v1/customers/{id}` (§0.2b finding 1)."""
    return _request("GET", f"/customers/{onvo_customer_id}")


def list_customer_subscriptions(onvo_customer_id: str) -> list[dict]:
    """`GET /v1/customers/{id}/subscriptions` (§0.2b finding 1) — the
    reconciliation backbone (§4.3 step 2): the only way to discover a
    subscription created out-of-band, since ONVO documents no
    `subscription.created` event."""
    return _unwrap_list(_request("GET", f"/customers/{onvo_customer_id}/subscriptions"))


def list_customer_payment_methods(onvo_customer_id: str) -> list[dict]:
    """`GET /v1/customers/{id}/payment-methods` (§0.2b finding 1) — a bare
    JSON array, not `{"data": [...]}` (see `_unwrap_list`'s docstring)."""
    return _unwrap_list(_request("GET", f"/customers/{onvo_customer_id}/payment-methods"))


# ── Payment methods ─────────────────────────────────────────────────────

def get_payment_method(onvo_payment_method_id: str) -> dict:
    """`GET /v1/payment-methods/{id}` (§0.2b finding 1). Unlike the
    customer-scoped list endpoint above, the single-object GET embeds
    `billing.address` (confirmed live at Step 2) — this is the only call
    that returns a billing address anywhere in ONVO's object model; ONVO's
    own `Customer.address` field is not settable (`POST /v1/customers/{id}`
    with a `billing` key returns `400 "property billing should not
    exist"`, confirmed live) and was observed `null` in every case."""
    return _request("GET", f"/payment-methods/{onvo_payment_method_id}")


def update_payment_method(onvo_payment_method_id: str, *, billing: dict) -> dict:
    """`POST /v1/payment-methods/{id}` (§0.2b finding 1 — an update, despite
    the verb; `PUT`/`PATCH` both 404, same POST-to-id pattern as
    `update_subscription()`). Added at Step 3 (PLAN_PHASE16.md §8, billing
    address) — Step 2 confirmed the METHOD+PATH for this call but never had
    a caller for it; this is that caller, following the exact same
    `_request()` plumbing as every other function in this module (no new
    transport logic). `billing` is ONVO's own shape, the same one
    `POST /v1/payment-methods` accepts at creation
    (`{"address": {...}, "name": ..., "phone": ...}`, §0.2b finding 2) —
    `routers/billing.py:put_address()` sends only the `address` sub-object,
    since that's the only thing the customer-facing address form collects.
    The caller is responsible for re-reading the payment method first and
    confirming it belongs to the calling customer before invoking this
    (§6.4 control 3) — this module has no concept of "this customer",
    same division of responsibility as `update_subscription()`'s own
    docstring."""
    return _request(
        "POST", f"/payment-methods/{onvo_payment_method_id}",
        json_body={"billing": billing},
    )


# ── Subscriptions ────────────────────────────────────────────────────────

def create_subscription(
    *,
    customer_id: str,
    price_id: str,
    quantity: int = 1,
    payment_method_id: str | None = None,
    trial_period_days: int | None = None,
    payment_behavior: str | None = None,
    description: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """`POST /v1/subscriptions` (§0.2b findings 1/2). One item per
    subscription only — Q3's cancel-and-restart design (§0.2b finding 6)
    means this product never sends more than one `{priceId, quantity}` in
    `items`, and there is no in-place item-price-change mechanism to build
    against anyway.

    `payment_behavior`, if given, MUST be one of ONVO's confirmed enum
    values (`allow_incomplete` | `default_incomplete`, §0.2b finding 3) —
    anything else raises `ValueError` here rather than silently reaching
    ONVO as an unrecognized string.
    """
    if payment_behavior is not None and payment_behavior not in _VALID_PAYMENT_BEHAVIORS:
        raise ValueError(
            f"Unknown paymentBehavior {payment_behavior!r} — ONVO's confirmed "
            f"enum (§0.2b finding 3) is {_VALID_PAYMENT_BEHAVIORS!r}."
        )
    body: dict = {
        "customerId": customer_id,
        "items": [{"priceId": price_id, "quantity": quantity}],
    }
    if payment_method_id:
        body["paymentMethodId"] = payment_method_id
    if trial_period_days is not None:
        body["trialPeriodDays"] = trial_period_days
    if payment_behavior is not None:
        body["paymentBehavior"] = payment_behavior
    if description:
        body["description"] = description
    if metadata:
        body["metadata"] = metadata
    return _request("POST", "/subscriptions", json_body=body)


def get_subscription(onvo_subscription_id: str) -> dict:
    """`GET /v1/subscriptions/{id}` (§0.2b finding 1)."""
    return _request("GET", f"/subscriptions/{onvo_subscription_id}")


def cancel_subscription(onvo_subscription_id: str) -> dict:
    """`DELETE /v1/subscriptions/{id}` (§0.2b finding 1) — immediate cancel,
    confirmed synchronous: `status` flips to `canceled` and `canceledAt` is
    stamped in the same response (§0.2b finding 12). No refund/credit is
    computed by ONVO for this call (§0.2b finding 6) — that is Q3's
    resolved "no proration" answer, not something this module works around."""
    return _request("DELETE", f"/subscriptions/{onvo_subscription_id}")


def update_subscription(
    onvo_subscription_id: str,
    *,
    cancel_at_period_end: bool | None = None,
    payment_method_id: str | None = None,
) -> dict:
    """`POST /v1/subscriptions/{id}` (§0.2b finding 1 — an update, despite
    the verb; `PUT`/`PATCH` both 404). Confirmed fields:
      - `cancelAtPeriodEnd`: graceful-cancel / resume toggle. Setting `True`
        then `False` genuinely clears a pending cancellation (§0.2b
        finding 12, confirmed live both directions).
      - `paymentMethodId`: card replacement on an existing subscription
        (§0.2b finding 7) — confirmed live end to end. The caller is
        responsible for re-reading the payment method first and confirming
        it belongs to this customer before calling this (§6.4 control 3 —
        this module never makes that check itself, it has no concept of
        "this customer").
    At least one of the two must be given — this function refuses to send
    an empty update."""
    body: dict = {}
    if cancel_at_period_end is not None:
        body["cancelAtPeriodEnd"] = cancel_at_period_end
    if payment_method_id is not None:
        body["paymentMethodId"] = payment_method_id
    if not body:
        raise ValueError("update_subscription() called with nothing to update.")
    return _request("POST", f"/subscriptions/{onvo_subscription_id}", json_body=body)


def confirm_subscription(onvo_subscription_id: str, *, payment_method_id: str) -> dict:
    """`POST /v1/subscriptions/{id}/confirm` (§0.2 [C], §0.2b finding 1) —
    moves an `incomplete` subscription (created with `paymentBehavior:
    allow_incomplete` and no payment method) to `active`, charging
    immediately (§0.2b finding 11, confirmed live)."""
    return _request(
        "POST", f"/subscriptions/{onvo_subscription_id}/confirm",
        json_body={"paymentMethodId": payment_method_id},
    )


# ── Invoices ─────────────────────────────────────────────────────────────

def list_invoices(
    *, subscription_id: str | None = None, customer_id: str | None = None, limit: int = 100,
) -> list[dict]:
    """`GET /v1/invoices` (§0.2b finding 1), filtered by `subscriptionId`
    and/or `customerId`. Returns `{"data": [...], "meta": {...}}` — see
    `_unwrap_list`."""
    params: dict = {"limit": limit}
    if subscription_id:
        params["subscriptionId"] = subscription_id
    if customer_id:
        params["customerId"] = customer_id
    return _unwrap_list(_request("GET", "/invoices", params=params))
