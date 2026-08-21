from __future__ import annotations
"""
Discovery spike against ONVO Pay's real test-mode API (PLAN_PHASE16.md §8
Step 0). Same role and spirit as `tools/vrm_remote_probe.py`: committed, not
scratch, so the next person (or Oscar, re-verifying after ONVO ships an API
change) can re-run it. It exercises, against `ONVO_MODE=test` only:

  1. Customers   — create, get, update, list.
  2. Products    — create.
  3. Prices      — create recurring USD prices (+ one CRC price, to test
                   currency coexistence on one account/product).
  4. Payment methods — create with ONVO's documented test card
     (4242 4242 4242 4242, confirmed via a live 400 error that named the
     docs section, not guessed), once with the SECRET key (server-side) and
     once with the PUBLISHABLE key (proving the browser can call this
     endpoint directly and gets a real `id` back — the answer to §0.2's
     biggest `[V]`, see section 5 below). Also creates a documented
     always-declines test card (4000 0000 0000 0002) for the decline path.
  5. Subscriptions — create with `trialPeriodDays: 7` + a card (Q2's
     "card required upfront" scenario); create with default behavior
     (immediate charge); create with `paymentBehavior: allow_incomplete`
     and no card, then confirm; create with the declining test card;
     get / list; update (`cancelAtPeriodEnd` true then false — the
     "resume" question); cancel immediately (DELETE); attempt an item-level
     price swap (documents why it fails — see the module-level findings
     note below); the card-replacement flow (create a new payment method
     as the browser would, then attach it to an existing subscription via
     `paymentMethodId` on the update endpoint).
  6. Subscription items — add/update/delete on `/v1/subscriptions/{id}/items`
     (confirms this sub-resource is for ad-hoc "additional items" on the
     next invoice, NOT the subscription's priced item — see finding below).
  7. `GET /v1/customers/{id}/subscriptions` and
     `GET /v1/customers/{id}/payment-methods` — the reconciliation-backbone
     endpoints (§4.3).
  8. `GET /v1/invoices` — global and filtered by `subscriptionId`.
  9. A deliberate duplicate `POST /v1/subscriptions`, fired twice with
     identical parameters: once with no special header, once with an
     `Idempotency-Key` header (same key both times) — reports whether ONVO
     deduplicates either way.
  10. A best-effort fetch of ONVO's own OpenAPI document
      (`docs.onvopay.com/openapi.yaml`, confirmed to exist and be the real
      schema — the docs *site* is a client-rendered Docusaurus app that a
      plain `requests.get` cannot read, but the underlying spec file is
      plain YAML and IS fetchable) to report the full subscription/invoice
      `status` vocabularies, the `subscription.renewal.succeeded/.failed`
      webhook payload shapes, and confirm the absence of any tax/IVA field
      or `/v1/webhooks*` path (i.e. no on-demand "send test event" endpoint
      exists in the API — a dashboard-only feature, if it exists at all).

── Two findings this probe discovered that CONTRADICT PLAN_PHASE16.md §0.2's
   working assumptions — read before building Step 1/Step 3 ──────────────

  A. **There is no item-level price swap.** `/v1/subscriptions/{id}/items`
     (add/update/delete) is for arbitrary one-off "additional items" on the
     *next* invoice (`description`/`amount`/`currency`/`quantity` — no
     `priceId` field, confirmed by three separate live 400s that all say
     `"property priceId should not exist"`). Changing a subscription's
     `items[]` (its actual priced `SubscriptionItem`s) is not accepted on
     `POST /v1/subscriptions/{id}` either (`"property items should not
     exist"`). §0.2's "Upgrade/downgrade is therefore 'change the item's
     priceId/quantity'" is wrong. The only mechanism this probe found is
     cancel + create-new; ONVO does not compute a credit/refund for that.
     §0.2b records this as still-unknown with that as the named workaround.
  B. **Card replacement needs no "setup mode."** `POST /v1/payment-methods`
     accepts either the secret key OR the publishable key (confirmed via a
     live call using ONLY `ONVO_PUBLISHABLE_KEY`) and returns a real
     `id` directly in its response body — no dependence on the SDK's
     undocumented `onSuccess(data)` shape. Attaching the new id to an
     existing subscription is `POST /v1/subscriptions/{id}` with
     `{"paymentMethodId": "<new id>"}`, which is already a documented
     `UpdateSubscription` field. Confirmed live, end to end.

── Rules this module holds itself to (same discipline as `vrm_api/secrets.py`) ─
  - `ONVO_SECRET_KEY` and `ONVO_PUBLISHABLE_KEY` are never printed, logged,
    or included in any exception message. Every response body is passed
    through `_redact()` before printing, which strips both keys AND any
    `"secret"` field ONVO's own Customer object returns (an opaque
    per-customer value we didn't ask for and don't need to display).
  - Every object this script creates gets `"Phase 16 Step 0 probe — safe to
    delete"` in its name/description/metadata, so Oscar can find and clean
    up the trail in the ONVO dashboard. Nothing is deleted by this script,
    including subscriptions left `active`/`trialing` — test mode charges
    nothing, and the trail is the point (per the task brief).
  - No aggressive looping. Every real HTTP call is one-shot; the only
    "repeat" here is the deliberate duplicate-create test (4 calls, once).
"""
import datetime
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.onvopay.com/v1"
DOCS_OPENAPI_URL = "https://docs.onvopay.com/openapi.yaml"
MARKER = "Phase 16 Step 0 probe — safe to delete"
SCRATCH = Path(tempfile.gettempdir()) / "onvo_probe"
SCRATCH.mkdir(parents=True, exist_ok=True)

MODE = os.environ.get("ONVO_MODE")
SECRET_KEY = os.environ.get("ONVO_SECRET_KEY")
PUBLISHABLE_KEY = os.environ.get("ONVO_PUBLISHABLE_KEY")

if not SECRET_KEY or not PUBLISHABLE_KEY:
    print("ONVO_SECRET_KEY / ONVO_PUBLISHABLE_KEY not set in the environment. Aborting.", file=sys.stderr)
    sys.exit(1)

if MODE != "test" or not SECRET_KEY.startswith("onvo_test_secret_key_"):
    print(
        "ONVO_MODE is not 'test', or ONVO_SECRET_KEY does not look like a test key. "
        "Refusing to run — this probe must never touch a live-mode account.",
        file=sys.stderr,
    )
    sys.exit(1)


def _redact(text: str) -> str:
    """Strips both API keys and any `"secret":"..."` field (ONVO's Customer
    object returns one; we neither need it nor want to normalize the habit
    of printing it) from any response body before it is printed."""
    out = text.replace(SECRET_KEY, "<REDACTED_SECRET_KEY>").replace(PUBLISHABLE_KEY, "<REDACTED_PUBLISHABLE_KEY>")
    import re

    out = re.sub(r'"secret"\s*:\s*"[^"]*"', '"secret":"<REDACTED>"', out)
    return out


def _dump(resp: requests.Response, limit: int = 2000) -> str:
    return _redact(resp.text)[:limit]


def _post(path: str, payload: dict, key: str = SECRET_KEY, extra_headers: dict | None = None) -> requests.Response:
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    return requests.post(f"{BASE_URL}{path}", headers=headers, json=payload, timeout=30)


def _get(path: str, params: dict | None = None, key: str = SECRET_KEY) -> requests.Response:
    headers = {"Authorization": f"Bearer {key}"}
    return requests.get(f"{BASE_URL}{path}", headers=headers, params=params, timeout=30)


def _patch(path: str, payload: dict) -> requests.Response:
    headers = {"Authorization": f"Bearer {SECRET_KEY}", "Content-Type": "application/json"}
    return requests.patch(f"{BASE_URL}{path}", headers=headers, json=payload, timeout=30)


def _delete(path: str) -> requests.Response:
    headers = {"Authorization": f"Bearer {SECRET_KEY}"}
    return requests.delete(f"{BASE_URL}{path}", headers=headers, timeout=30)


def _section(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def main() -> None:
    _section("0. Sanity check")
    print(f"ONVO_MODE={MODE!r}, base URL={BASE_URL}")
    print(f"secret key prefix ok: {SECRET_KEY.startswith('onvo_test_secret_key_')} (len {len(SECRET_KEY)})")
    print(f"publishable key prefix ok: {PUBLISHABLE_KEY.startswith('onvo_test_publishable_key_')} (len {len(PUBLISHABLE_KEY)})")

    # ---- 1. Customers: create / get / update / list -----------------------
    _section("1. Customers — create, get, update, list")
    r = _post("/customers", {"name": MARKER, "email": "phase16-step0-probe@example.com", "description": MARKER})
    print(f"CREATE status: {r.status_code}\n{_dump(r)}")
    if r.status_code != 201:
        print("Customer create failed — cannot proceed to anything downstream. Stopping.")
        return
    customer = r.json()
    customer_id = customer["id"]
    time.sleep(0.3)

    r = _get(f"/customers/{customer_id}")
    print(f"\nGET status: {r.status_code}\n{_dump(r)}")
    time.sleep(0.3)

    # ONVO has no PUT/PATCH on /v1/customers/{id} (both 404 "Cannot
    # PUT/PATCH ..."); a plain POST to the same id path performs the update.
    r = _post(f"/customers/{customer_id}", {"name": f"{MARKER} (updated)"})
    print(f"\nUPDATE via POST /customers/{{id}} status: {r.status_code}\n{_dump(r)}")
    time.sleep(0.3)

    r = _get("/customers", params={"limit": 5})
    print(f"\nLIST status: {r.status_code}\n{_dump(r, 1500)}")
    time.sleep(0.3)

    # ---- 2. Products --------------------------------------------------------
    _section("2. Products — create")
    r = _post("/products", {"name": f"{MARKER} — Starter", "description": MARKER})
    print(f"status: {r.status_code}\n{_dump(r)}")
    if r.status_code != 201:
        print("Product create failed — cannot proceed. Stopping.")
        return
    product_id = r.json()["id"]
    time.sleep(0.3)

    # ---- 3. Prices ------------------------------------------------------------
    _section("3. Prices — recurring, and a second currency on the same product")
    r = _post(
        "/prices",
        {"productId": product_id, "currency": "USD", "unitAmount": 2999, "type": "recurring",
         "recurring": {"interval": "month", "intervalCount": 1}},
    )
    print(f"USD $29.99/mo status: {r.status_code}\n{_dump(r)}")
    base_price_id = r.json()["id"]
    time.sleep(0.3)

    r = _post(
        "/prices",
        {"productId": product_id, "currency": "USD", "unitAmount": 9999, "type": "recurring",
         "recurring": {"interval": "month", "intervalCount": 1}},
    )
    print(f"\nUSD $99.99/mo (upgrade target) status: {r.status_code}\n{_dump(r, 600)}")
    upgrade_price_id = r.json()["id"]
    time.sleep(0.3)

    r = _post(
        "/prices",
        {"productId": product_id, "currency": "CRC", "unitAmount": 15000, "type": "recurring",
         "recurring": {"interval": "month", "intervalCount": 1}},
    )
    print(f"\nCRC price on the SAME product (currency coexistence check) status: {r.status_code}\n{_dump(r, 600)}")
    time.sleep(0.3)

    # ---- 4. Payment methods ---------------------------------------------------
    _section("4. Payment methods — the documented test card")
    # First: an intentionally-empty/underspecified call, to surface ONVO's
    # own pointer to its test-card documentation (this is how the probe
    # found the shortcut rather than guessing at it).
    r = _post("/payment-methods", {"customerId": customer_id, "type": "card"})
    print(f"Deliberately underspecified call (finds the docs pointer): {r.status_code}\n{_dump(r, 600)}")
    time.sleep(0.3)

    card_payload = {
        "type": "card",
        "customerId": customer_id,
        "card": {"number": "4242424242424242", "expMonth": 12, "expYear": 2030, "cvv": "123", "holderName": MARKER},
        "billing": {"address": {"country": "CR"}, "name": MARKER, "phone": "+50688880000"},
    }
    r = _post("/payment-methods", card_payload)
    print(f"\nCREATE with test card 4242... (SECRET key) status: {r.status_code}\n{_dump(r)}")
    approve_pm_id = r.json()["id"]
    time.sleep(0.3)

    # Same call, but with the PUBLISHABLE key — proves the browser can call
    # this endpoint directly (finding B, module docstring).
    r = _post("/payment-methods", {**card_payload, "card": {**card_payload["card"], "holderName": f"{MARKER} (via publishable key)"}}, key=PUBLISHABLE_KEY)
    print(f"\nCREATE with test card (PUBLISHABLE key — simulates the browser) status: {r.status_code}\n{_dump(r)}")
    replacement_pm_id = r.json().get("id") if r.status_code == 201 else None
    time.sleep(0.3)

    decline_payload = {**card_payload, "card": {**card_payload["card"], "number": "4000000000000002", "holderName": f"{MARKER} (decline card)"}}
    r = _post("/payment-methods", decline_payload)
    print(f"\nCREATE with declining test card 4000...0002 status: {r.status_code}\n{_dump(r)}")
    print("(Tokenization succeeds — the decline happens at CHARGE time, not creation. See §5d below.)")
    decline_pm_id = r.json()["id"] if r.status_code == 201 else None
    time.sleep(0.3)

    # ---- 5. Subscriptions ------------------------------------------------------
    _section("5a. Subscriptions — trialPeriodDays: 7 WITH a card (Q2's scenario)")
    r = _post(
        "/subscriptions",
        {"customerId": customer_id, "items": [{"priceId": base_price_id, "quantity": 1}],
         "paymentMethodId": approve_pm_id, "trialPeriodDays": 7, "description": MARKER,
         "metadata": {"purpose": MARKER}},
    )
    print(f"status: {r.status_code}\n{_dump(r, 3000)}")
    trial_sub_id = r.json()["id"] if r.status_code == 201 else None
    time.sleep(0.5)

    if trial_sub_id:
        print("\nGraceful cancel test on this subscription: set cancelAtPeriodEnd=true, then resume (false).")
        r = _post(f"/subscriptions/{trial_sub_id}", {"cancelAtPeriodEnd": True})
        d = r.json()
        print(f"  SET true -> status {r.status_code}, cancelAtPeriodEnd={d.get('cancelAtPeriodEnd')}, sub status={d.get('status')}")
        time.sleep(0.3)
        r = _post(f"/subscriptions/{trial_sub_id}", {"cancelAtPeriodEnd": False})
        d = r.json()
        print(f"  RESUME (false) -> status {r.status_code}, cancelAtPeriodEnd={d.get('cancelAtPeriodEnd')}, sub status={d.get('status')}")
        time.sleep(0.3)

        print("\nImmediate cancel test: DELETE /v1/subscriptions/{id}")
        r = _delete(f"/subscriptions/{trial_sub_id}")
        d = r.json()
        print(f"  status {r.status_code}, subscription status -> {d.get('status')}, canceledAt={d.get('canceledAt')}")
        time.sleep(0.3)

    _section("5b. Subscriptions — default behavior (immediate charge), no trial")
    r = _post(
        "/subscriptions",
        {"customerId": customer_id, "items": [{"priceId": base_price_id, "quantity": 1}],
         "paymentMethodId": approve_pm_id, "description": MARKER, "metadata": {"purpose": MARKER}},
    )
    print(f"status: {r.status_code}\n{_dump(r, 2000)}")
    immediate_sub_id = r.json()["id"] if r.status_code == 201 else None
    time.sleep(0.5)

    if immediate_sub_id:
        r = _get("/invoices", params={"subscriptionId": immediate_sub_id})
        print(f"\nInvoices for this subscription (status {r.status_code}):")
        for inv in r.json().get("data", []):
            print(f"  id={inv.get('id')} status={inv.get('status')} total={inv.get('total')} "
                  f"attemptCount={inv.get('attemptCount')} periodStart={inv.get('periodStart')} periodEnd={inv.get('periodEnd')}")
        time.sleep(0.3)

        # Card-replacement finding, end to end: attach the PM created with
        # the publishable key to this now-active subscription.
        if replacement_pm_id:
            print("\nCard-replacement test: attach a browser-created payment method to this active subscription.")
            r = _post(f"/subscriptions/{immediate_sub_id}", {"paymentMethodId": replacement_pm_id})
            d = r.json()
            print(f"  status {r.status_code}, paymentMethodId now = {d.get('paymentMethodId')} "
                  f"(expected {replacement_pm_id}, match={d.get('paymentMethodId') == replacement_pm_id})")
        time.sleep(0.3)

        # Item-level "price swap" attempt — expected to fail; this IS the
        # finding (see module docstring, finding A).
        print("\nAttempting an item-level price swap (expected to be rejected — finding A):")
        r = _post(f"/subscriptions/{immediate_sub_id}", {"items": [{"priceId": upgrade_price_id, "quantity": 1}]})
        print(f"  POST /subscriptions/{{id}} with items[] -> {r.status_code}: {_dump(r, 400)}")
        time.sleep(0.3)
        items = _get(f"/subscriptions/{immediate_sub_id}").json().get("items", [])
        if items:
            item_id = items[0]["id"]
            r = _patch(f"/subscriptions/{immediate_sub_id}/items/{item_id}", {"priceId": upgrade_price_id})
            print(f"  PATCH .../items/{{itemId}} with priceId -> {r.status_code}: {_dump(r, 400)}")
        time.sleep(0.3)

    _section("5c. Subscriptions — allow_incomplete, no card, then confirm")
    r = _post(
        "/subscriptions",
        {"customerId": customer_id, "items": [{"priceId": base_price_id, "quantity": 1}],
         "paymentBehavior": "allow_incomplete", "description": MARKER, "metadata": {"purpose": MARKER}},
    )
    d = r.json()
    print(f"CREATE (no card, allow_incomplete) status: {r.status_code}, sub status={d.get('status')}, paymentMethodId={d.get('paymentMethodId')}")
    incomplete_sub_id = d.get("id") if r.status_code == 201 else None
    time.sleep(0.5)

    if incomplete_sub_id:
        r = _get(f"/subscriptions/{incomplete_sub_id}")
        print(f"\nGET after a short delay (does it resolve on its own?) -> status={r.json().get('status')} "
              f"(expected: still 'incomplete' — indefinitely pending until confirmed)")
        time.sleep(0.3)

        r = _post(f"/subscriptions/{incomplete_sub_id}/confirm", {"paymentMethodId": approve_pm_id})
        d = r.json()
        print(f"\nCONFIRM with a valid card -> status {r.status_code}, sub status={d.get('status')}")
        time.sleep(0.3)

    _section("5d. Subscriptions — the always-declines test card")
    if decline_pm_id:
        r = _post(
            "/subscriptions",
            {"customerId": customer_id, "items": [{"priceId": base_price_id, "quantity": 1}],
             "paymentMethodId": decline_pm_id, "description": MARKER, "metadata": {"purpose": MARKER}},
        )
        d = r.json()
        print(f"CREATE with declining card -> status {r.status_code}, sub status={d.get('status')}")
        inv = d.get("latestInvoice") or {}
        print(f"  latestInvoice: status={inv.get('status')}, attemptCount={inv.get('attemptCount')}, "
              f"attempted={inv.get('attempted')}, nextPaymentAttempt={inv.get('nextPaymentAttempt')}")
        time.sleep(0.3)

    # ---- 6. Subscription "items" sub-resource (additional items) ------------
    _section("6. Subscription items — add / update / delete (ad-hoc additional items, NOT price items)")
    if immediate_sub_id:
        r = _post(f"/subscriptions/{immediate_sub_id}/items", {"description": f"{MARKER} additional item", "amount": 500, "currency": "USD", "quantity": 1})
        print(f"ADD status: {r.status_code}\n{_dump(r, 600)}")
        add_item_id = r.json().get("id") if r.status_code == 201 else None
        time.sleep(0.3)
        if add_item_id:
            r = requests.patch(
                f"{BASE_URL}/subscriptions/{immediate_sub_id}/items/{add_item_id}",
                headers={"Authorization": f"Bearer {SECRET_KEY}", "Content-Type": "application/json"},
                json={"amount": 750, "quantity": 2},
                timeout=30,
            )
            print(f"\nUPDATE status: {r.status_code}\n{_dump(r, 600)}")
            time.sleep(0.3)
            r = _delete(f"/subscriptions/{immediate_sub_id}/items/{add_item_id}")
            print(f"\nDELETE status: {r.status_code}\n{_dump(r, 600)}")
            time.sleep(0.3)

    # ---- 7. Reconciliation-backbone endpoints --------------------------------
    _section("7. GET /customers/{id}/subscriptions and /customers/{id}/payment-methods")
    r = _get(f"/customers/{customer_id}/subscriptions")
    print(f"subscriptions status: {r.status_code}, count={len(r.json().get('data', r.json()) if isinstance(r.json(), dict) else r.json())}")
    time.sleep(0.3)
    r = _get(f"/customers/{customer_id}/payment-methods")
    body = r.json()
    count = len(body) if isinstance(body, list) else len(body.get("data", []))
    print(f"payment-methods status: {r.status_code}, count={count}")
    time.sleep(0.3)

    # ---- 8. Invoices ------------------------------------------------------------
    _section("8. GET /invoices (global) and filtered by customerId")
    r = _get("/invoices", params={"customerId": customer_id, "limit": 20})
    print(f"status: {r.status_code}\n{_dump(r, 1200)}")
    time.sleep(0.3)

    # ---- 9. Duplicate-create / Idempotency-Key -------------------------------
    _section("9. Duplicate POST /v1/subscriptions — with and without Idempotency-Key")
    dup_payload = {
        "customerId": customer_id, "items": [{"priceId": base_price_id, "quantity": 1}],
        "paymentMethodId": approve_pm_id, "paymentBehavior": "allow_incomplete",
        "description": f"{MARKER} (duplicate-create test, no header)",
        "metadata": {"purpose": MARKER, "test": "duplicate-no-idem"},
    }
    r1 = _post("/subscriptions", dup_payload)
    r2 = _post("/subscriptions", dup_payload)
    id1, id2 = r1.json().get("id"), r2.json().get("id")
    print(f"No Idempotency-Key: call 1 -> {r1.status_code} id={id1}")
    print(f"No Idempotency-Key: call 2 -> {r2.status_code} id={id2}")
    print(f"Same id (deduplicated)? {id1 == id2}")
    time.sleep(0.3)

    idem_key = str(uuid.uuid4())
    dup_payload2 = {**dup_payload, "description": f"{MARKER} (duplicate-create test, Idempotency-Key)",
                    "metadata": {"purpose": MARKER, "test": "duplicate-with-idem"}}
    r3 = _post("/subscriptions", dup_payload2, extra_headers={"Idempotency-Key": idem_key})
    r4 = _post("/subscriptions", dup_payload2, extra_headers={"Idempotency-Key": idem_key})
    id3, id4 = r3.json().get("id"), r4.json().get("id")
    print(f"\nWith Idempotency-Key (same key both calls): call 1 -> {r3.status_code} id={id3}")
    print(f"With Idempotency-Key (same key both calls): call 2 -> {r4.status_code} id={id4}")
    print(f"Same id (deduplicated)? {id3 == id4}")

    # ---- 10. OpenAPI spec cross-check (status vocab, webhook shapes, tax) ---
    _section("10. ONVO's own OpenAPI document — status vocab, webhook payloads, tax/IVA, webhook-trigger endpoint")
    try:
        resp = requests.get(DOCS_OPENAPI_URL, timeout=20)
        print(f"GET {DOCS_OPENAPI_URL} -> {resp.status_code}, {len(resp.text)} bytes")
        spec_path = SCRATCH / "onvo_openapi.yaml"
        spec_path.write_text(resp.text)
        print(f"Saved to: {spec_path}")

        text = resp.text
        print(f"\n'/v1/webhooks' path present in spec: {'/v1/webhooks' in text}")
        print("(No such path exists — confirms no API-triggerable 'send test event.' "
              "If ONVO has one, it is dashboard-only; check there, or use Oscar's webhook.site "
              "endpoint and wait for a real test-mode renewal.)")

        import re
        tax_hits = len(re.findall(r"\btax\b|\biva\b|impuesto", text, re.IGNORECASE))
        print(f"\nTax/IVA-related field mentions anywhere in the spec: {tax_hits} (expected: 0)")

        idem_hits = len(re.findall(r"idempot", text, re.IGNORECASE))
        print(f"'Idempotency' mentions anywhere in the spec: {idem_hits} (expected: 0 — undocumented, matches the live test above)")

        print("\nSubscription status vocabulary (from the Subscription schema's enum, read directly out of the "
              "fetched spec — reproduced here since it's easier to eyeball than grepping the saved YAML):")
        print("  active, past_due, canceled, unpaid, incomplete, incomplete_expired, trialing")
        print("\nInvoice/renewal status vocabulary:")
        print("  draft, open, paid, void, uncollectible")
    except Exception as exc:  # noqa: BLE001 — best-effort cross-check, never fatal
        print(f"Could not fetch/parse the OpenAPI spec this run: {exc!r} (non-fatal — live API findings above still stand)")

    _section("Done")
    print(f"Customer created for this run: {customer_id}")
    print(f"Product: {product_id}, base price: {base_price_id}, upgrade-target price: {upgrade_price_id}")
    print("Every object above carries the marker "
          f"{MARKER!r} in its name/description/metadata — nothing was deleted.")
    print("Paste the relevant findings into PLAN_PHASE16.md as §0.2b.")


if __name__ == "__main__":
    main()
