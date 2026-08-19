from __future__ import annotations
"""
The only code path allowed to touch a customer's Victron VRM personal access
token, in storage or out of it (PLAN_PHASE15.md §2).

Every function here is a thin wrapper around one of the three
`SECURITY DEFINER` RPCs migration 024 adds to the `vrm` schema —
`vrm.set_customer_vrm_token` / `vrm.read_customer_vrm_token` /
`vrm.clear_customer_vrm_token` (see that migration's header for the Vault
design these wrap: Supabase Vault, reached because `vault` itself is never
exposed to PostgREST and must never be). This module reaches Postgres
exactly the way every other `vrm_api` module does —
`database.supabase_client.get_client().schema("vrm").rpc(...)`
(`vrm_api/tenancy.py` does the equivalent for `.table(...)` calls) — no new
client, no direct `vault.*` access, no raw SQL.

── Rules this module exists to enforce (PLAN_PHASE15.md §2.5) ─────────────
Restated here because this is the one file in the product where getting them
wrong is catastrophic — a leaked token reads every installation on a
customer's VRM account, including installations they don't own but that are
shared with them.

  1. A token is never logged, in whole or in part, by this module. No
     `logger.*` call below includes a token value, and no exception raised
     here carries the underlying Postgres/PostgREST error text verbatim —
     that text can legitimately echo back the value it choked on, so every
     `except` collapses to a short, fixed, customer-safe message and lets
     the caller's own logging (if any) capture only what THIS module chose
     to say.
  2. `read_customer_vrm_token()` returns the token to its immediate caller
     and only that caller. From the instant it returns non-`None`, the
     caller inherits every rule in this docstring: never logged, never
     written into `vrm.jobs.params` (a sync job's params are
     `{customer_id, site_id, start, end}` — the token is read fresh inside
     the job, per run, precisely so it never sits in a stored `params`
     blob), never returned from an HTTP endpoint.
  3. `read_customer_vrm_token()` returns `None` — it does not raise — when
     the customer has no live token (never connected one, or disconnected
     it). A sync of a disconnected customer is a clean no-op, not an
     exception path (§2.2).
  4. `set_`/`clear_` never see, handle, or log a Vault secret id. The
     wrapper functions keep that entirely inside Postgres; this module
     passes only a `customer_id` and, for `set_`, a token.

No endpoint built on top of this module may ever return a stored token, in
whole or in part — not even "last 4 characters." The UI shows connection
*state* (`connected as <vrm_account_email> since <date>`), never the secret
(§2.5 rule 2).
"""
import logging

from database.supabase_client import get_client

logger = logging.getLogger("vrm_api.secrets")

SCHEMA = "vrm"


class VrmSecretsError(Exception):
    """Base class for this module's errors. Never constructed with a token
    or a raw Postgres/PostgREST error string in the message — see the
    module docstring's rule 1."""


class VrmCustomerNotFound(VrmSecretsError):
    """`customer_id` does not name a real `vrm.customers` row. Raised by
    `set_customer_vrm_token`/`clear_customer_vrm_token`, whose underlying
    wrapper functions reject an unknown customer rather than silently
    no-op'ing. `read_customer_vrm_token` deliberately does NOT raise this —
    see its own docstring for why "no such customer" and "no live token"
    are folded into the same `None` there."""


def _rpc(name: str, params: dict):
    return get_client().schema(SCHEMA).rpc(name, params).execute()


def set_customer_vrm_token(customer_id: str, token: str) -> None:
    """Stores `token` in Vault for `customer_id` — creating the secret on
    first connect, or updating it in place on reconnect (the wrapper
    function decides which; this module never sees the difference or a
    vault id either way). Called only from the connect flow (Step 4/5); the
    caller holds `token` for exactly as long as this call takes and must not
    retain it afterwards.

    Raises `VrmCustomerNotFound` if `customer_id` doesn't name a real
    `vrm.customers` row, `VrmSecretsError` for anything else that goes
    wrong (Vault unavailable, PostgREST denied the call, etc.).
    """
    try:
        _rpc("set_customer_vrm_token", {"p_customer_id": customer_id, "p_token": token})
    except Exception as exc:  # noqa: BLE001 — rule 1: never log/re-raise this verbatim
        logger.warning("set_customer_vrm_token failed for customer_id=%s", customer_id)
        if "no such customer" in str(exc).lower():
            raise VrmCustomerNotFound(f"No such customer {customer_id!r}.") from None
        raise VrmSecretsError("Could not store the VRM token.") from None


def read_customer_vrm_token(customer_id: str) -> str | None:
    """Returns the live token for `customer_id`, or `None` if the customer
    has never connected one, has disconnected it, or doesn't exist at all
    (rule 3 — deliberately one case, not three, at this layer; a sync job
    calls this and treats `None` as "skip, nothing to do," never as a
    reason to inspect why).

    The returned value IS the customer's credential — see the module
    docstring's rule 2 before doing anything with it besides calling
    `victron/vrm_remote.py` and discarding it.
    """
    try:
        result = _rpc("read_customer_vrm_token", {"p_customer_id": customer_id})
    except Exception:  # noqa: BLE001 — rule 1
        logger.warning("read_customer_vrm_token failed for customer_id=%s", customer_id)
        raise VrmSecretsError("Could not read the VRM token.") from None
    return result.data


def clear_customer_vrm_token(customer_id: str) -> None:
    """Deletes the Vault secret for `customer_id` — not just the pointer,
    see `vrm.clear_customer_vrm_token`'s own comment — and stamps
    `vrm.customers.vrm_token_revoked_at`. Called from the disconnect flow
    (Step 4/5) and from admin disconnect (Step 6). Idempotent from this
    module's point of view: the underlying wrapper function no-ops the
    delete when there's no secret to remove, but still stamps
    `vrm_token_revoked_at` and requires a real customer to do so.

    Raises `VrmCustomerNotFound` if `customer_id` doesn't name a real
    `vrm.customers` row, `VrmSecretsError` for anything else that goes
    wrong.
    """
    try:
        _rpc("clear_customer_vrm_token", {"p_customer_id": customer_id})
    except Exception as exc:  # noqa: BLE001 — rule 1
        logger.warning("clear_customer_vrm_token failed for customer_id=%s", customer_id)
        if "no such customer" in str(exc).lower():
            raise VrmCustomerNotFound(f"No such customer {customer_id!r}.") from None
        raise VrmSecretsError("Could not clear the VRM token.") from None
